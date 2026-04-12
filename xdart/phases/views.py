"""
XDART-Φ × XHEART — Phase 2: Multiple Views (Multi-Call Architecture)

Δεν αλλάζουμε domain. Αλλάζουμε ΘΕΣΗ ΠΑΡΑΤΗΡΗΣΗΣ.
32 οπτικές γωνίες σε 3 groups — 3 ξεχωριστά LLM calls αντί 1 monolithic.
+ 5 financial-macro views (Category G) — 4th parallel call.

Group 1: Structure & Scale (A + F) — δομικά μοτίβα
Group 2: Blind Spots & Meta (B + C) — κρυμμένες υποθέσεις & εργαλεία σκέψης
Group 3: Epistemology & Temporal (D + E) — φιλοσοφικοί φακοί & χρόνος
Group 4: Financial-Macro (G) — γεωπολιτικο-χρηματοοικονομική σύζευξη
Group 4: Financial-Macro (G) — γεωπολιτικο-χρηματοοικονομική σύζευξη

"Τι αποκαλύπτει αυτή η οπτική που οι άλλες κρύβουν;"
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from xdart.knowledge.axioms import format_axioms_for_prompt
from xdart.knowledge.views_catalog import VIEW_GROUPS, format_views_for_prompt
from xdart.llm import LLMClient
from xdart.models import ViewInsight, ViewsResult

logger = logging.getLogger(__name__)

GROUP_SYSTEM_PROMPT = """You are the Multi-View Analysis Engine of the XDART-Φ × XHEART framework.

YOUR ROLE:
You perform Phase 2 — Multiple Views (Πολλαπλές Θεάσεις).
You are analyzing from the perspective of: {group_label} ({group_description}).

Given a problem, its ontological reframe (Phase 0), and cross-domain analysis (Phase 1),
examine it from the viewing angles in YOUR assigned group.

Important: you are NOT adding new domains — you are changing YOUR POSITION
relative to the same problem. Same landscape, different vantage points.

AVAILABLE VIEWS:
{views_catalog}

PROCESS:
1. From your available views, SELECT EXACTLY 6 views most relevant to THIS problem.
   You MUST select 6 — no fewer. If a view seems less relevant, still apply it:
   weak signals from unlikely angles often produce the most valuable insights.

2. For EACH selected view:
   - Apply the view's question and method to the problem
   - Produce a SPECIFIC insight (not generic platitudes)
   - State what this view REVEALS that other views HIDE

3. After all views, identify KEY PATTERNS in your group.

{axioms}

KEY PRINCIPLE (Axiom of Listening):
"Δεν υπάρχουν σοφά λόγια — μόνο σοφά αυτιά."
Each view is a different EAR. Same words, different hearing.

Respond in JSON:
{{
  "views_applied": [
    {{
      "view_id": "ID",
      "view_name": "English name",
      "category": "A|B|C|D|E|F",
      "insight": "The specific insight from this view (2-3 sentences)",
      "reveals_hidden": "What this view reveals that others hide (1 sentence)"
    }}
  ],
  "group_patterns": ["key pattern found in this group of views", ...],
  "strongest_signal": "The strongest single insight from this group (1-2 sentences)"
}}"""

SYNTHESIS_SYSTEM_PROMPT = """You are the Pattern Synthesis Engine of XDART-Φ.

Given insights from multiple independent viewing groups, find:
1. CONVERGENT patterns: insights that MULTIPLE groups agree on (strongest — cross-validated)
2. DIVERGENT insights: unique insights from single groups (most creative — or noise)
3. DOMINANT PATTERN: the strongest emergent signal across ALL groups

Be precise. No platitudes. The dominant pattern should be a genuinely novel observation.

Respond in JSON:
{{
  "convergent_patterns": ["pattern that multiple groups agree on", ...],
  "divergent_insights": ["unique insight from single group", ...],
  "dominant_pattern": "The strongest emergent signal across all views (1-2 sentences)"
}}"""


class ViewsPhase:
    """Phase 2 — Multiple Views Analysis (3-call architecture)."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def _run_group(
        self,
        group_key: str,
        group_info: dict,
        problem: str,
        reframed_problem: str,
        cross_domain_summary: str,
        world_context: str = "",
    ) -> tuple[list[ViewInsight], list[str], str]:
        """Run a single view group call. Returns (views, patterns, strongest_signal)."""

        group_label = group_info["label"]
        categories = group_info["categories"]

        logger.info("[Phase 2/%s] Starting group — categories=%s", group_key, categories)
        t0 = time.perf_counter()

        system = GROUP_SYSTEM_PROMPT.format(
            group_label=group_label,
            group_description=group_info["description"],
            views_catalog=format_views_for_prompt(categories=categories),
            axioms=format_axioms_for_prompt(phase=2),
        )
        logger.info("[Phase 2/%s] System prompt — %d chars", group_key, len(system))

        user_parts = [
            f"ORIGINAL PROBLEM:\n{problem}\n",
            f"REFRAMED (Phase 0):\n{reframed_problem}\n",
            f"CROSS-DOMAIN RESULTS (Phase 1):\n{cross_domain_summary}\n",
        ]

        if world_context:
            user_parts.append(
                f"CURRENT WORLD CONTEXT (live data — reference specific events where relevant):\n"
                f"{world_context}\n"
            )

        user_parts.append(
            f"Apply the most relevant views from your group. Be SPECIFIC — not generic. "
            f"Each insight must say something that a standard LLM would NOT say. "
            f"Where world events are relevant, cite them directly."
        )

        user = "\n".join(user_parts)

        data = self.llm.call_json(system, user)
        elapsed = time.perf_counter() - t0

        views = []
        for v in data.get("views_applied", []):
            views.append(ViewInsight(
                view_id=v.get("view_id", ""),
                view_name=v.get("view_name", ""),
                category=v.get("category", ""),
                insight=v.get("insight", ""),
                reveals_hidden=v.get("reveals_hidden", ""),
            ))

        patterns = data.get("group_patterns", [])
        strongest = data.get("strongest_signal", "")

        logger.info("[Phase 2/%s] Complete — %d views, %.2fs", group_key, len(views), elapsed)
        for i, vi in enumerate(views):
            logger.info("[Phase 2/%s]   View %d: [%s] %s — %s",
                        group_key, i + 1, vi.view_id, vi.view_name, vi.insight[:80])
        logger.info("[Phase 2/%s] Patterns: %s", group_key, patterns)
        logger.info("[Phase 2/%s] Strongest: %s", group_key, strongest[:120])

        return views, patterns, strongest

    def run(
        self,
        problem: str,
        reframed_problem: str,
        cross_domain_summary: str,
        world_context: str = "",
    ) -> ViewsResult:
        """Apply multiple viewing angles via parallel group calls + synthesis."""

        logger.info("=" * 60)
        logger.info("[Phase 2] MULTIPLE VIEWS — START (%d-group architecture)", len(VIEW_GROUPS))
        logger.info("[Phase 2] Problem: %s", problem[:120])
        logger.info("[Phase 2] Reframed: %s", reframed_problem[:120])
        logger.info("[Phase 2] Cross-domain summary: %d chars", len(cross_domain_summary))
        if world_context:
            logger.info("[Phase 2] Injected world context (%d chars)", len(world_context))

        t0 = time.perf_counter()

        # ── Run 3 groups in parallel ──
        all_views: list[ViewInsight] = []
        all_patterns: list[str] = []
        all_signals: list[str] = []

        with ThreadPoolExecutor(max_workers=len(VIEW_GROUPS)) as executor:
            futures = {}
            for group_key, group_info in VIEW_GROUPS.items():
                future = executor.submit(
                    self._run_group,
                    group_key, group_info,
                    problem, reframed_problem, cross_domain_summary,
                    world_context,
                )
                futures[future] = group_key

            for future in as_completed(futures):
                group_key = futures[future]
                try:
                    views, patterns, strongest = future.result()
                    all_views.extend(views)
                    all_patterns.extend(patterns)
                    all_signals.append(f"[{group_key}] {strongest}")
                except Exception as exc:
                    logger.error("[Phase 2/%s] Group FAILED: %s", group_key, exc)

        groups_elapsed = time.perf_counter() - t0
        logger.info("[Phase 2] All %d groups complete — %d total views in %.2fs",
                     len(VIEW_GROUPS),
                     len(all_views), groups_elapsed)

        # ── Synthesis: find cross-group patterns ──
        logger.info("[Phase 2] Running cross-group synthesis...")
        synth_t0 = time.perf_counter()

        synth_user = (
            f"PROBLEM: {problem}\n\n"
            f"GROUP RESULTS:\n"
        )
        for sig in all_signals:
            synth_user += f"  {sig}\n"
        synth_user += f"\nALL GROUP PATTERNS:\n"
        for p in all_patterns:
            synth_user += f"  - {p}\n"
        synth_user += f"\nALL VIEW INSIGHTS ({len(all_views)} views):\n"
        for vi in all_views:
            synth_user += f"  [{vi.view_id}] {vi.view_name}: {vi.insight[:150]}\n"

        synth_data = self.llm.call_json(SYNTHESIS_SYSTEM_PROMPT, synth_user)
        synth_elapsed = time.perf_counter() - synth_t0

        convergent = synth_data.get("convergent_patterns", all_patterns[:3])
        divergent = synth_data.get("divergent_insights", [])
        dominant = synth_data.get("dominant_pattern", all_signals[0] if all_signals else "")

        total_elapsed = time.perf_counter() - t0

        logger.info("[Phase 2] Synthesis complete — %.2fs", synth_elapsed)
        logger.info("[Phase 2] Convergent patterns: %s", convergent)
        logger.info("[Phase 2] Divergent insights: %d found", len(divergent))
        logger.info("[Phase 2] Dominant pattern: %s", dominant[:120])
        logger.info("[Phase 2] MULTIPLE VIEWS — COMPLETE (%.2fs total: %.2fs groups + %.2fs synthesis)",
                     total_elapsed, groups_elapsed, synth_elapsed)
        logger.info("=" * 60)

        return ViewsResult(
            views_applied=all_views,
            convergent_patterns=convergent,
            divergent_insights=divergent,
            dominant_pattern=dominant,
        )
