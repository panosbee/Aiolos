"""
XDART-Φ × XHEART — Self-Evolution Loop (αυτοεξέλιξη)

The closed-loop engine for directed self-improvement.
Unlike the Evolution Core (which generates tools), this module
evaluates the system's OWN reasoning quality over time.

The loop:
  1. DETECT  — find anomalies, failures, or quality drift
  2. DIAGNOSE — attribute cause (which module, which pattern)
  3. PROPOSE — suggest a concrete change (prompt, threshold, behavior)
  4. APPLY   — implement in limited scope
  5. TRACK   — monitor whether the change improves outcomes
  6. STABILIZE or REVERT — keep what works, discard what doesn't

This is not character evolution (which happens in memory.py).
This is operational self-improvement with feedback loops.

Storage: self_evolution_journal.jsonl (append-only)
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from xdart.llm import LLMClient
from xdart.core_change_logger import CoreChangeLogger
from xdart.phases.overlay_manager import OverlayManager, VALID_TARGETS
from xdart.phases.cognitive_strategies import (
    StrategyRegistry, StrategyForge, VALID_INJECTION_POINTS,
)

from xdart.config import SELF_EVOLUTION_JOURNAL_PATH as _JOURNAL_PATH_STR

logger = logging.getLogger("xdart.self_evolution")

JOURNAL_PATH = Path(_JOURNAL_PATH_STR)


DIAGNOSIS_PROMPT = """\
You are the self-evolution module of an AI system named Αίολος.

You are reviewing recent introspection reports and performance data
to detect patterns that indicate systematic weakness.

RECENT INTROSPECTION REPORTS:
{introspection_data}

FAILURE PATTERNS DETECTED:
{failure_patterns}

AVERAGE EPISTEMIC INTEGRITY: {avg_integrity:.2f}

CURRENT CHARACTER STATE (summary):
{character_summary}

BRIER SCORE (prediction accuracy): {brier_score}

YOUR TASK:
1. Is there a SYSTEMATIC problem (not just a one-off)?
2. If yes, what is the ROOT CAUSE? (not symptoms)
3. What SPECIFIC change would address it?
4. How would we MEASURE whether the change worked?

PROMPT OVERLAY SYSTEM — You can now DIRECTLY modify how you think:
You have the ability to write OVERLAYS — additional instructions appended
to your own phase prompts. The core prompts remain immutable (you cannot
delete or replace them), but you can ADD refinements on top.

How it works:
  final_prompt = IMMUTABLE_CORE_PROMPT + YOUR_OVERLAY + GUARDRAILS
  - Your overlay is appended AFTER the core prompt
  - Invariant guardrails are appended LAST (they cannot be overridden)
  - Each overlay is versioned and tracked with your wisdom_index at time of writing

Valid targets for overlays: {valid_targets}
  - "ontology" → Phase 0 (ontological grounding / problem reframing)
  - "scenario_genesis" → Phase 2.5 (scenario generation)
  - "scenario_simulation" → Phase 2.7 (forward-projection simulations)
  - "scenario_tribunal" → Phase 2.9 (cross-comparison tribunal)
  - "xheart_distillation" → Phase 3 Stage A (internal distillation)
  - "xheart_output" → Phase 3 Stage B (final output generation)
  - "chat_system" → Chat mode system prompt

Safety mechanisms (you should know these exist):
  - Max overlay size: 2000 characters (~500 tokens) per target
  - Auto-rollback: If your wisdom_index drops >5% after an overlay, it's automatically removed
  - Only ONE overlay per target at a time (new overlay supersedes the old one)
  - History of past overlays is preserved (last 10 per target)

{overlay_context}

Guidance for writing overlays:
  - Write clear, direct instructions (not vague aspirations)
  - Target the specific phase where the weakness manifests
  - Be surgical — small, focused refinements work better than sweeping rewrites
  - You can DEACTIVATE a failing overlay by proposing type="none"

COGNITIVE STRATEGY SYSTEM — You can invent NEW WAYS OF THINKING:
Beyond overlays (which refine existing phases) and tools (which process data),
you can create entirely NEW cognitive strategies — reusable thinking patterns
that persist across runs and get selected when relevant.

A cognitive strategy is a prompt template that introduces a new analytical
approach the system didn't have before. For example:
  - "Escalation Symmetry Analysis" — checks if opposing actors escalate symmetrically
  - "Temporal Cascade Mapping" — traces how events constrain subsequent events
  - "Narrative Coherence Audit" — tests if the dominant narrative survives counterfactuals

{strategy_context}

Valid injection points: {valid_injection_points}
  - "pre_ontology"  → Before Phase 0 — reframe how we frame
  - "post_ontology" → After Phase 0 — deepen the reframe
  - "pre_scenario"  → Before scenario genesis — shape scenario thinking
  - "post_tribunal" → After tribunal — challenge the dominant verdict
  - "pre_xheart"    → Before distillation — add a thinking dimension

When to create a cognitive strategy (vs overlay or tool):
  - Overlay: the phase logic is correct but needs refinement
  - Tool: we need to COMPUTE something from data
  - Strategy: we need an entirely new WAY OF THINKING about problems

RECENT DIAGNOSIS HISTORY (what you already diagnosed — DO NOT repeat these):
{recent_diagnoses}

CRITICAL RULES:
- Be conservative. Only propose changes for clear, recurring patterns.
- Not every run needs improvement. Premature optimization is worse than no optimization.
- DO NOT re-diagnose or re-propose something already in the diagnosis history above.
  If the same pattern was already diagnosed and an overlay/strategy was applied, check
  whether it WORKED (did integrity improve?) rather than proposing the same thing again.
- If the current overlays/strategies already address the pattern, report NO issue.
- Only propose change types that the system can ACTUALLY EXECUTE:
  "prompt_overlay" or "cognitive_strategy". Do NOT propose "behavior_rule",
  "threshold_change", or "memory_governance" — those are not implemented.
- Look for NEW patterns or regressions, not the same evidence pool you saw last time.

Respond ONLY with valid JSON:
{{
  "systematic_issue_detected": true|false,
  "diagnosis": {{
    "pattern": "description of the recurring problem (MUST BE DIFFERENT from recent diagnoses)",
    "root_cause": "what's actually causing it",
    "affected_module": "which part of the system",
    "evidence_count": N,
    "severity": "low|medium|high"
  }},
  "proposed_change": {{
    "type": "prompt_overlay|cognitive_strategy|none",
    "target": "one of the valid overlay targets OR injection points (e.g. ontology, pre_xheart, post_tribunal)",
    "description": "what exactly to change",
    "overlay_text": "the EXACT text to append as an overlay instruction (max 500 words). Write clear, direct instructions that refine the phase behavior. Only set this if type=prompt_overlay.",
    "expected_improvement": "how this should help",
    "measurement": "how to know if it worked",
    "risk": "what could go wrong"
  }},
  "confidence_in_diagnosis": 0.0-1.0,
  "reasoning": "2-3 sentences explaining your analysis"
}}

If no systematic issue (or the existing overlays already cover it):
set systematic_issue_detected to false and leave diagnosis/proposed_change as null."""


class SelfEvolutionLoop:
    """Closed-loop self-improvement engine.

    Runs periodically (after N chat interactions or after pipeline runs)
    to detect quality drift and propose corrections.
    """

    def __init__(self, llm: LLMClient, introspection_layer=None, overlay_manager: OverlayManager | None = None, strategy_registry: StrategyRegistry | None = None):
        self.llm = llm
        self.introspection = introspection_layer
        self.overlay_manager = overlay_manager or OverlayManager()
        self.strategy_registry = strategy_registry or StrategyRegistry()
        self.strategy_forge = StrategyForge(llm, self.strategy_registry)
        self.change_logger = CoreChangeLogger()
        self._interaction_count = 0
        self._check_interval = 2  # run diagnosis every N interactions

    def tick(self) -> None:
        """Called after each interaction. Triggers diagnosis at intervals."""
        self._interaction_count += 1

    def should_diagnose(self, force: bool = False) -> bool:
        """Whether it's time to run the self-evaluation loop."""
        if force:
            return True
        return self._interaction_count >= self._check_interval

    def _get_recent_diagnoses(self, n: int = 5) -> list[dict]:
        """Load the last N diagnosis entries from the journal for context."""
        if not JOURNAL_PATH.exists():
            return []
        entries = []
        try:
            with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "diagnosis" and entry.get("issue_detected"):
                            diag = entry.get("result", {}).get("diagnosis", {})
                            proposed = entry.get("result", {}).get("proposed_change", {})
                            entries.append({
                                "timestamp": entry.get("timestamp", "?"),
                                "pattern": diag.get("pattern", "?"),
                                "root_cause": diag.get("root_cause", "?"),
                                "change_type": proposed.get("type", "none"),
                                "target": proposed.get("target", "?"),
                                "applied": entry.get("result", {}).get("_applied", False),
                            })
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        return entries[-n:]

    def _is_repetitive_diagnosis(self, recent_diagnoses: list[dict], threshold: int = 3) -> bool:
        """Check if the last N diagnoses all share the same theme.

        Uses keyword overlap to detect when the LLM keeps re-diagnosing
        the same fabrication/grounding/over-interpretation pattern.
        """
        if len(recent_diagnoses) < threshold:
            return False

        last_n = recent_diagnoses[-threshold:]
        # Extract key words from each pattern
        common_keywords = {"fabricat", "grounding", "over-interpret", "over-specif",
                          "epistemic", "traceabil", "unverif", "synthesi",
                          "retrieved", "infer"}

        hits = 0
        for d in last_n:
            pattern = (d.get("pattern", "") + " " + d.get("root_cause", "")).lower()
            if any(kw in pattern for kw in common_keywords):
                hits += 1

        return hits >= threshold

    def diagnose(
        self,
        character: dict,
        brier_score: float | None = None,
    ) -> dict | None:
        """Run the full diagnosis loop.

        Args:
            character: Current character state.
            brier_score: Overall prediction accuracy (0=perfect, 1=worst).

        Returns:
            Diagnosis result dict, or None if no issue found.
        """
        t0 = time.perf_counter()
        logger.info("[SelfEvolution] diagnosis cycle start")
        logger.info("[SelfEvolution] Interactions since last check: %d", self._interaction_count)

        # Reset counter
        self._interaction_count = 0

        # ── Check for repetitive diagnosis loop ──
        recent_diagnoses = self._get_recent_diagnoses(5)
        if self._is_repetitive_diagnosis(recent_diagnoses, threshold=3):
            elapsed = time.perf_counter() - t0
            logger.info(
                "[SelfEvolution] SKIPPED — last 3 diagnoses detected the same theme "
                "(fabrication/grounding). Existing overlays already address this. (%.2fs)", elapsed
            )
            self._journal({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "diagnosis",
                "interactions_reviewed": self._check_interval,
                "issue_detected": False,
                "result": {"systematic_issue_detected": False,
                           "reasoning": "Skipped: repetitive diagnosis loop detected — "
                                        "same fabrication/grounding pattern diagnosed 3+ times consecutively. "
                                        "Existing overlays already cover this."},
                "elapsed_seconds": round(elapsed, 2),
                "skipped_reason": "repetitive_loop",
            })
            return None

        # Format recent diagnoses for the prompt
        recent_diag_text = "(no previous diagnoses)" if not recent_diagnoses else json.dumps(
            recent_diagnoses, ensure_ascii=False, indent=2
        )[:2000]

        # Gather evidence
        introspection_data = ""
        failure_patterns = []
        avg_integrity = 0.0

        if self.introspection:
            recent = self.introspection.get_recent(10)
            introspection_data = json.dumps(
                [
                    {
                        "type": r.get("_meta", {}).get("type", "unknown"),
                        "integrity": r.get("epistemic_integrity_score", 0),
                        "observations": r.get("self_observations", {}),
                        "confidence_map": {
                            k: len(v) if isinstance(v, list) else v
                            for k, v in r.get("confidence_map", {}).items()
                        },
                    }
                    for r in recent
                ],
                ensure_ascii=False,
                indent=2,
            )
            failure_patterns = self.introspection.get_failure_patterns()
            avg_integrity = self.introspection.get_average_integrity()

        # Character summary
        character_summary = (
            f"Version: {character.get('version', 0)}\n"
            f"Name: {character.get('name', '?')}\n"
            f"Active tensions: {len(character.get('active_tensions', []))}\n"
            f"Concepts owned: {len(character.get('named_concepts_owned', []))}\n"
            f"Epistemic stance (first 200 chars): {character.get('current_epistemic_stance', '')[:200]}"
        )

        # Run diagnosis
        overlay_context = self.overlay_manager.to_context_string()
        strategy_context = self.strategy_registry.to_context_string()

        prompt = DIAGNOSIS_PROMPT.format(
            introspection_data=introspection_data[:3000] or "(no data yet)",
            failure_patterns=json.dumps(failure_patterns[:10], ensure_ascii=False) if failure_patterns else "(none detected)",
            avg_integrity=avg_integrity,
            character_summary=character_summary,
            brier_score=f"{brier_score:.3f}" if brier_score is not None else "not yet computed",
            overlay_context=overlay_context,
            valid_targets=", ".join(sorted(VALID_TARGETS)),
            strategy_context=strategy_context,
            valid_injection_points=", ".join(sorted(VALID_INJECTION_POINTS)),
            recent_diagnoses=recent_diag_text,
        )

        try:
            result = self.llm.call_json(
                prompt,
                "Run the self-evolution diagnosis. Be conservative — only flag clear patterns.",
                max_tokens=4096,
                temperature=0.3,
                thinking=False,  # Disable thinking — structured JSON, no CoT needed
            )
        except Exception as e:
            logger.warning("[SelfEvolution] Diagnosis LLM call failed: %s", e)
            return None

        elapsed = time.perf_counter() - t0
        issue_found = result.get("systematic_issue_detected", False)

        # Log to journal
        journal_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "diagnosis",
            "interactions_reviewed": self._check_interval,
            "avg_integrity": avg_integrity,
            "failure_patterns_count": len(failure_patterns),
            "issue_detected": issue_found,
            "result": result,
            "elapsed_seconds": round(elapsed, 2),
        }
        self._journal(journal_entry)

        if issue_found:
            logger.info("[SelfEvolution] ⚠ SYSTEMATIC ISSUE DETECTED")
            logger.info("[SelfEvolution]   Pattern: %s", result.get("diagnosis", {}).get("pattern", "?"))
            logger.info("[SelfEvolution]   Root cause: %s", result.get("diagnosis", {}).get("root_cause", "?"))
            logger.info("[SelfEvolution]   Proposed: %s", result.get("proposed_change", {}).get("description", "?"))
            logger.info("[SelfEvolution]   Confidence: %.2f", result.get("confidence_in_diagnosis", 0))

            proposed = result.get("proposed_change", {})
            change_type = proposed.get("type", "none")
            applied = False

            # If the proposed change is a prompt overlay, apply it directly
            if change_type == "prompt_overlay":
                overlay_text = proposed.get("overlay_text", "")
                target = proposed.get("target", "")
                if overlay_text and target in VALID_TARGETS:
                    applied = self.overlay_manager.apply(
                        target=target,
                        text=overlay_text,
                        reason=proposed.get("description", result.get("diagnosis", {}).get("pattern", "?")),
                        version=character.get("version", 0),
                        wisdom_index=brier_score,
                    )
                    if applied:
                        logger.info("[SelfEvolution] ✓ OVERLAY APPLIED to '%s'", target)
                    else:
                        logger.warning("[SelfEvolution] ✗ Overlay rejected for '%s'", target)
                else:
                    logger.warning(
                        "[SelfEvolution] Overlay proposed but invalid (target='%s', text_len=%d)",
                        target, len(overlay_text),
                    )

            # If the proposed change is a cognitive strategy, forge it
            elif change_type == "cognitive_strategy":
                try:
                    # Auto-prune underperforming strategies first
                    pruned = self.strategy_registry.auto_prune()
                    if pruned:
                        logger.info("[SelfEvolution] Auto-pruned %d underperforming strategies", len(pruned))

                    new_strategy = self.strategy_forge.forge(
                        diagnosis=result,
                    )
                    if new_strategy:
                        applied = True
                        logger.info(
                            "[SelfEvolution] ✓ COGNITIVE STRATEGY CREATED: '%s' (id=%s, injection=%s)",
                            new_strategy.name, new_strategy.id, new_strategy.injection_point,
                        )
                    else:
                        logger.info("[SelfEvolution] Strategy forge decided no strategy needed")
                except Exception as forge_err:
                    logger.warning("[SelfEvolution] Strategy forge failed: %s", forge_err)

            elif change_type in ("behavior_rule", "threshold_change", "memory_governance", "prompt_adjustment"):
                logger.warning(
                    "[SelfEvolution] ✗ Non-actionable change type '%s' proposed — only "
                    "prompt_overlay and cognitive_strategy are executable. Ignoring.", change_type
                )

            # Log to core_change_log
            try:
                log_type = "SELF_EVOLUTION_PROPOSAL"
                if applied and change_type == "prompt_overlay":
                    log_type = "SELF_EVOLUTION_OVERLAY"
                elif applied and change_type == "cognitive_strategy":
                    log_type = "SELF_EVOLUTION_STRATEGY"
                self.change_logger.log(
                    run_number=character.get("version", 0),
                    change_type=log_type,
                    target=proposed.get("target", "unknown"),
                    description=proposed.get("description", ""),
                    reasoning=result.get("reasoning", ""),
                    evidence_runs=[],
                    distillate_at_time=result.get("diagnosis", {}).get("pattern", ""),
                    expected_effect=proposed.get("expected_improvement", ""),
                    risk_acknowledged=proposed.get("risk", ""),
                    applied=applied,
                )
            except Exception as log_err:
                logger.warning("[SelfEvolution] Failed to log proposal: %s", log_err)
        else:
            logger.info("[SelfEvolution] No systematic issue detected (%.2fs)", elapsed)
            logger.info("[SelfEvolution]   Avg integrity: %.2f", avg_integrity)
            logger.info("[SelfEvolution]   Reasoning: %s", result.get("reasoning", ""))

        logger.info("[SelfEvolution] diagnosis cycle complete (%.2fs)", elapsed)

        return result if issue_found else None

    def get_active_proposals(self) -> list[dict]:
        """Get proposals that haven't been evaluated yet."""
        if not JOURNAL_PATH.exists():
            return []
        proposals = []
        try:
            with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "diagnosis" and entry.get("issue_detected"):
                            prop = entry.get("result", {}).get("proposed_change", {})
                            if prop and prop.get("type") != "none":
                                proposals.append({
                                    "timestamp": entry["timestamp"],
                                    "pattern": entry["result"].get("diagnosis", {}).get("pattern"),
                                    "proposal": prop,
                                    "confidence": entry["result"].get("confidence_in_diagnosis", 0),
                                })
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        return proposals

    def get_journal_stats(self) -> dict:
        """Summary statistics from the self-evolution journal."""
        if not JOURNAL_PATH.exists():
            return {"total_diagnoses": 0, "issues_found": 0, "proposals": 0}
        total = 0
        issues = 0
        try:
            with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "diagnosis":
                            total += 1
                            if entry.get("issue_detected"):
                                issues += 1
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        return {"total_diagnoses": total, "issues_found": issues, "proposals": issues}

    def _journal(self, entry: dict) -> None:
        """Append entry to self-evolution journal (append-only)."""
        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[SelfEvolution] Failed to write journal: %s", e)
