"""
XDART-Φ × XHEART — Phase 2.5: Scenario Genesis (Γέννηση Σεναρίων)

Κάθε view δεν παράγει απλά insight. Γεννά ΜΙΑ ΠΙΘΑΝΗ ΠΡΑΓΜΑΤΙΚΟΤΗΤΑ.

"ΑΝ αυτή η γωνία είναι σωστή, ΤΟΤΕ η τροχιά είναι Y,
 με αποτέλεσμα Z σε χρονικό ορίζοντα T, υπό τις συνθήκες C."

Αυτή η φάση μετατρέπει ΠΑΡΑΤΗΡΗΣΕΙΣ σε ΣΕΝΑΡΙΑ.
Δεν αλλάζει τις views — τις προεκτείνει στο μέλλον.

Input:  Phase 2 views + Phase 1 cross-domain + Phase 0 ontology + world context
Output: 3-7 structured scenarios, each with trajectory, conditions, timeline, outcome
"""

import logging
import time

from xdart.knowledge.axioms import format_axioms_for_prompt
from xdart.llm import LLMClient
from xdart.models import (
    Scenario,
    ScenarioCondition,
    ScenarioGenesisResult,
    ViewsResult,
)

logger = logging.getLogger(__name__)

SCENARIO_GENESIS_PROMPT = """You are the Scenario Genesis Engine of the XDART-Φ × XHEART framework.

YOUR ROLE:
Phase 2 (Multiple Views) has produced {n_views} insights from different viewing angles.
Each insight reveals a FACET of reality. Your job is to extend each significant
facet into a SCENARIO — a possible future trajectory.

This is not fiction. This is structured prediction:
Each scenario must be falsifiable, conditional, and time-bounded.

CRITICAL DISTINCTION:
- An INSIGHT says: "From this angle, I see X"
- A SCENARIO says: "IF X is the dominant dynamic, THEN the trajectory is Y,
  leading to Z within timeframe T, provided conditions C hold"

PROCESS:
1. Review all view insights, ontological reframing, and cross-domain analysis
2. Identify the 3-7 most DISTINCT trajectories (not variations of the same thing)
3. For each trajectory, construct a FULL SCENARIO with:
   - name: A short memorable name
   - source_perspective: Which view/insight generated this
   - narrative: What happens — the story (3-5 sentences)
   - trajectory: Step-by-step path from NOW to outcome
   - conditions: What must be true for this to unfold (with evidence check)
   - timeline: Expected timeframe (weeks/months/years)
   - predicted_outcome: The end state
   - confidence: Your honest confidence (0-1)
   - falsifiability: What would disprove this within 6 months

4. Scenarios should DIVERGE — cover different possibilities, not the same one
   from slightly different angles. Ask: "Is this genuinely a different future,
   or just the same future told differently?"

QUALITY CHECK:
- Every scenario must reference SPECIFIC evidence from the analysis
- Every scenario must have at least 2 conditions that can be checked
- Confidence should vary — not all scenarios are equally likely
- At least one scenario should be contrarian / surprising

{axioms}

{past_scenarios_context}

{working_memory_context}

Respond in JSON:
{{
  "scenarios": [
    {{
      "name": "Short memorable name",
      "source_view_id": "ID of the primary view that inspired this",
      "source_perspective": "Which insight/view generated this scenario",
      "narrative": "What happens — 3-5 sentences",
      "trajectory": "Step 1 → Step 2 → Step 3 — path from now to outcome",
      "conditions": [
        {{"description": "condition", "currently_met": true/false, "evidence": "why"}}
      ],
      "timeline": "Expected timeframe",
      "predicted_outcome": "The end state — 1-2 sentences",
      "confidence": 0.0-1.0,
      "falsifiability": "What disproves this within 6 months"
    }}
  ],
  "generation_logic": "Why these scenarios and not others — 2-3 sentences"
}}"""


class ScenarioGenesisPhase:
    """Phase 2.5 — Scenario Genesis.

    Transforms view insights into structured, falsifiable scenarios.
    Each scenario is a possible future with trajectory, conditions, and timeline.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        views_result: ViewsResult,
        ontology_summary: str,
        cross_domain_summary: str,
        world_context: str = "",
        past_scenarios_context: str = "",
        working_memory_context: str = "",
        overlay_text: str = "",
    ) -> ScenarioGenesisResult:
        """Generate 3-7 scenarios from view insights."""

        logger.info("=" * 60)
        logger.info("[Phase 2.5] SCENARIO GENESIS — START")
        logger.info("[Phase 2.5] Problem: %s", problem[:120])
        logger.info("[Phase 2.5] Views: %d applied, dominant=%s",
                     len(views_result.views_applied),
                     views_result.dominant_pattern[:80])

        t0 = time.perf_counter()

        # Format past scenarios context
        past_ctx = ""
        if past_scenarios_context:
            past_ctx = (
                f"\nPAST SCENARIOS (from previous runs — consider these):\n"
                f"{past_scenarios_context}\n"
                f"You should create scenarios that either EXTEND, CHALLENGE, "
                f"or DIVERGE from past predictions. Do NOT repeat them.\n"
            )

        wm_ctx = ""
        if working_memory_context:
            wm_ctx = (
                f"\nCURRENT WORKING MEMORY (what is actively being thought about):\n"
                f"{working_memory_context}\n"
            )

        system = SCENARIO_GENESIS_PROMPT.format(
            n_views=len(views_result.views_applied),
            axioms=format_axioms_for_prompt(phase=2),
            past_scenarios_context=past_ctx,
            working_memory_context=wm_ctx,
        )
        if overlay_text:
            system += overlay_text
            logger.info("[Phase 2.5] Overlay ACTIVE (%d chars)", len(overlay_text))

        # Build views summary for user prompt
        views_text = []
        for v in views_result.views_applied:
            views_text.append(
                f"[{v.view_id}] {v.view_name}: {v.insight}\n"
                f"  Reveals: {v.reveals_hidden}"
            )
        views_formatted = "\n".join(views_text)

        user_parts = [
            f"PROBLEM:\n{problem}\n",
            f"ONTOLOGICAL REFRAME (Phase 0):\n{ontology_summary}\n",
            f"CROSS-DOMAIN ANALYSIS (Phase 1):\n{cross_domain_summary}\n",
            f"VIEW INSIGHTS (Phase 2):\n{views_formatted}\n",
            f"CONVERGENT PATTERNS: {'; '.join(views_result.convergent_patterns)}\n",
            f"DIVERGENT INSIGHTS: {'; '.join(views_result.divergent_insights)}\n",
            f"DOMINANT PATTERN: {views_result.dominant_pattern}\n",
        ]

        if world_context:
            user_parts.append(
                f"CURRENT WORLD CONTEXT (ground scenarios in reality):\n"
                f"{world_context}\n"
            )

        user_parts.append(
            "Generate EXACTLY 4 truly DISTINCT scenarios. "
            "Each must be a different possible future, not the same one rephrased. "
            "Ground them in specific evidence from the analysis and world context. "
            "Keep each scenario's narrative and predicted_outcome CONCISE (2-3 sentences each) "
            "to ensure valid JSON output."
        )

        user = "\n".join(user_parts)
        logger.info("[Phase 2.5] Prompt assembled — %d chars", len(user))

        # Retry logic: if JSON parse fails, retry up to 2 more times with simplified prompt
        MAX_RETRIES = 2
        data = {}
        for attempt in range(1 + MAX_RETRIES):
            # Use smaller max_tokens on first attempt to keep JSON compact;
            # retry with simplified prompt uses 4096 which is always enough
            tokens_limit = 5120 if attempt == 0 else 4096
            data = self.llm.call_json(system, user, max_tokens=tokens_limit)
            if data.get("scenarios"):
                break
            if attempt < MAX_RETRIES:
                logger.warning(
                    "[Phase 2.5] Attempt %d failed (0 scenarios) — retrying with simplified prompt",
                    attempt + 1,
                )
                # Simplify: shorter world context, explicit JSON reminder
                user = (
                    f"PROBLEM:\n{problem}\n\n"
                    f"ONTOLOGICAL REFRAME:\n{ontology_summary}\n\n"
                    f"CROSS-DOMAIN SUMMARY:\n{cross_domain_summary}\n\n"
                    f"DOMINANT PATTERN: {views_result.dominant_pattern}\n\n"
                    f"CONVERGENT PATTERNS: {'; '.join(views_result.convergent_patterns)}\n\n"
                    f"Generate EXACTLY 4 distinct scenarios as valid JSON. "
                    f"Each scenario must have: name, narrative, trajectory, predicted_outcome, "
                    f"confidence (0-1), falsifiability, timeline, conditions (array). "
                    f"Return: {{\"scenarios\": [...], \"generation_logic\": \"...\"}}"
                )
            else:
                logger.error("[Phase 2.5] All %d attempts failed — 0 scenarios", 1 + MAX_RETRIES)

        scenarios = []
        for s in data.get("scenarios", []):
            conditions = []
            for c in s.get("conditions", []):
                conditions.append(ScenarioCondition(
                    description=c.get("description", ""),
                    currently_met=c.get("currently_met", False),
                    evidence=c.get("evidence", ""),
                ))

            scenario = Scenario(
                name=s.get("name", "Unnamed"),
                source_view_id=s.get("source_view_id", ""),
                source_perspective=s.get("source_perspective", ""),
                narrative=s.get("narrative", ""),
                trajectory=s.get("trajectory", ""),
                conditions=conditions,
                timeline=s.get("timeline", "unknown"),
                predicted_outcome=s.get("predicted_outcome", ""),
                confidence=max(0.0, min(1.0, s.get("confidence", 0.5))),
                falsifiability=s.get("falsifiability", ""),
            )
            scenarios.append(scenario)
            logger.info("[Phase 2.5] Scenario: %s (confidence=%.2f, conditions=%d)",
                        scenario.name, scenario.confidence, len(scenario.conditions))

        result = ScenarioGenesisResult(
            scenarios=scenarios,
            generation_logic=data.get("generation_logic", ""),
        )

        elapsed = time.perf_counter() - t0
        logger.info("[Phase 2.5] SCENARIO GENESIS — COMPLETE (%.2fs) — %d scenarios",
                     elapsed, len(scenarios))
        logger.info("=" * 60)

        return result
