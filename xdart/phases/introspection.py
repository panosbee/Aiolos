"""
XDART-Φ × XHEART — Introspection Layer (αυτογνωσία)

Operational self-awareness: after each response (chat or pipeline),
the system produces a structured introspection report that answers:

  - What did I retrieve from memory vs infer vs synthesize?
  - Which modules shaped this answer?
  - What are my confidence levels and where am I uncertain?
  - What recurring patterns or failure modes do I notice?
  - What internal change happened (if any)?

This is NOT reflective style. This is machine-readable self-audit.
Every claim in the introspection must be traceable to an actual operation.

The introspection is stored in introspection_log.jsonl (append-only)
and the most recent introspection is available to the next response.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xdart.config import INTROSPECTION_LOG_PATH as _INTRO_LOG_PATH_STR
from xdart.llm import LLMClient

logger = logging.getLogger("xdart.introspection")

INTROSPECTION_LOG_PATH = Path(_INTRO_LOG_PATH_STR)


INTROSPECTION_PROMPT = """\
You are the introspection module of an AI system named Αίολος.

You just observed a complete interaction. Your job is to produce a STRUCTURED
self-audit report. This is not poetry or reflection — it is operational self-knowledge.

RULES:
1. Every claim must be traceable to an actual operation that happened.
2. Distinguish clearly between: RETRIEVAL (from stored memory), INFERENCE
   (logical deduction from available data), SYNTHESIS (creative combination),
   and FABRICATION (anything that has no grounding).
3. Be honest about uncertainty. If you can't tell whether something was
   retrieved or inferred, say so.
4. Note any failure modes or patterns you observe.
5. Keep it concise but complete.

Respond ONLY with valid JSON:
{
  "knowledge_sources": {
    "retrieved_memories": ["description of each memory that was actually retrieved"],
    "retrieved_world_data": ["what real-world data was available"],
    "inferred_from_context": ["what you deduced from available info"],
    "synthesized": ["what you created by combining sources"],
    "potentially_fabricated": ["anything you said that lacks clear grounding"]
  },
  "modules_that_shaped_response": ["list of system components that influenced output"],
  "confidence_map": {
    "high_confidence": ["claims I'm very sure about and why"],
    "medium_confidence": ["claims with some grounding but gaps"],
    "low_confidence": ["claims I'm unsure about"]
  },
  "self_observations": {
    "what_went_well": "one sentence",
    "what_could_improve": "one sentence",
    "recurring_pattern_noticed": "pattern description or null",
    "failure_mode_detected": "failure description or null"
  },
  "internal_state_change": "description of any change in stance, knowledge, or identity, or null",
  "epistemic_integrity_score": 0.0
}

The epistemic_integrity_score (0.0-1.0) measures: did I stay within what I
actually know? 1.0 = perfect discipline, 0.0 = pure fabrication.
Be honest — most interactions will be 0.6-0.85."""


class IntrospectionLayer:
    """Operational self-awareness module.

    Produces structured introspection reports after interactions.
    Stores them for pattern detection and self-evolution.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def introspect_chat(
        self,
        user_message: str,
        ai_response: str,
        retrieved_memories: list[str],
        retrieved_prophecies: list[str],
        world_data_available: bool,
        concepts_retrieved: list[str],
        modules_used: list[str],
        history_len: int,
    ) -> dict:
        """Generate introspection report for a chat interaction.

        Args:
            user_message: What the user said.
            ai_response: What Αίολος responded.
            retrieved_memories: Summaries of memories that were actually retrieved.
            retrieved_prophecies: Summaries of prophecies retrieved.
            world_data_available: Whether world context was loaded.
            concepts_retrieved: Names of concepts retrieved.
            modules_used: List of modules that were active.
            history_len: Number of conversation turns.

        Returns:
            Structured introspection report dict.
        """
        t0 = time.perf_counter()
        logger.info("[Introspection] Starting chat introspection")

        # Build the observation context
        observation = (
            f"INTERACTION TYPE: Chat (direct response)\n"
            f"CONVERSATION HISTORY LENGTH: {history_len} turns\n\n"
            f"USER MESSAGE:\n{user_message[:500]}\n\n"
            f"AI RESPONSE:\n{ai_response[:800]}\n\n"
            f"ACTUAL OPERATIONS PERFORMED:\n"
            f"- Memories retrieved: {len(retrieved_memories)}\n"
        )
        for i, mem in enumerate(retrieved_memories[:5]):
            observation += f"  Memory {i+1}: {mem[:200]}\n"

        observation += f"- Prophecies retrieved: {len(retrieved_prophecies)}\n"
        for i, p in enumerate(retrieved_prophecies[:3]):
            observation += f"  Prophecy {i+1}: {p[:200]}\n"

        observation += (
            f"- World data available: {world_data_available}\n"
            f"- Concepts retrieved: {concepts_retrieved}\n"
            f"- Modules active: {modules_used}\n"
        )

        try:
            report = self.llm.call_json(
                INTROSPECTION_PROMPT,
                observation,
                max_tokens=1500,
                temperature=0.3,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[Introspection] LLM call failed: %s", e)
            report = self._empty_report("LLM call failed")

        elapsed = time.perf_counter() - t0
        report["_meta"] = {
            "type": "chat",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "user_message_preview": user_message[:100],
        }

        # Store
        self._store(report)

        logger.info("[Introspection] Report generated in %.2fs — integrity=%.2f",
                     elapsed, report.get("epistemic_integrity_score", 0))
        return report

    def introspect_pipeline(
        self,
        problem: str,
        phase_outputs: dict[str, str],
        final_output: str,
        layer: str,
        phase_times: dict[str, float],
        memories_retrieved: int,
        concepts_retrieved: int,
        world_events: int,
    ) -> dict:
        """Generate introspection report for a full pipeline run.

        Args:
            problem: The original question.
            phase_outputs: Summary of each phase's output.
            final_output: The XHEART final output.
            layer: Achieved reasoning layer.
            phase_times: Timing for each phase.
            memories_retrieved: Number of episodic memories used.
            concepts_retrieved: Number of concepts used.
            world_events: Number of world events available.

        Returns:
            Structured introspection report dict.
        """
        t0 = time.perf_counter()
        logger.info("[Introspection] Starting pipeline introspection")

        observation = (
            f"INTERACTION TYPE: Full pipeline run\n"
            f"PROBLEM: {problem[:300]}\n"
            f"ACHIEVED LAYER: {layer}\n\n"
            f"PHASE OUTPUTS:\n"
        )
        for phase_name, output in phase_outputs.items():
            observation += f"  [{phase_name}]: {output[:150]}\n"

        observation += (
            f"\nFINAL OUTPUT (first 500 chars):\n{final_output[:500]}\n\n"
            f"ACTUAL OPERATIONS:\n"
            f"- Episodic memories retrieved: {memories_retrieved}\n"
            f"- Concepts retrieved: {concepts_retrieved}\n"
            f"- World events available: {world_events}\n"
            f"- Phase timings: {json.dumps({k: round(v, 1) for k, v in phase_times.items()})}\n"
        )

        try:
            report = self.llm.call_json(
                INTROSPECTION_PROMPT,
                observation,
                max_tokens=2000,
                temperature=0.3,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[Introspection] LLM call failed: %s", e)
            report = self._empty_report("LLM call failed")

        elapsed = time.perf_counter() - t0
        report["_meta"] = {
            "type": "pipeline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "problem_preview": problem[:100],
            "layer": layer,
        }

        # Store
        self._store(report)

        logger.info("[Introspection] Pipeline report generated in %.2fs — integrity=%.2f",
                     elapsed, report.get("epistemic_integrity_score", 0))
        return report

    def get_recent(self, n: int = 5) -> list[dict]:
        """Read the most recent introspection reports."""
        if not INTROSPECTION_LOG_PATH.exists():
            return []
        entries = []
        try:
            with open(INTROSPECTION_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass
        return entries[-n:]

    def get_failure_patterns(self) -> list[str]:
        """Extract recurring failure modes from recent introspection reports.

        Deduplicates similar patterns to avoid feeding the self-evolution
        loop the same evidence repeatedly.
        """
        recent = self.get_recent(20)
        failures = []
        seen_normalized = set()
        for r in recent:
            obs = r.get("self_observations", {})
            fm = obs.get("failure_mode_detected")
            if fm and fm != "null" and fm.lower() != "none":
                # Normalize: lowercase first 60 chars for dedup
                norm = fm.strip().lower()[:60]
                if norm not in seen_normalized:
                    seen_normalized.add(norm)
                    failures.append(fm)
            rp = obs.get("recurring_pattern_noticed")
            if rp and rp != "null" and rp.lower() != "none":
                norm = rp.strip().lower()[:60]
                if norm not in seen_normalized:
                    seen_normalized.add(norm)
                    failures.append(f"pattern: {rp}")
        return failures

    def get_average_integrity(self, n: int = 10) -> float:
        """Average epistemic integrity score over last N reports."""
        recent = self.get_recent(n)
        scores = [r.get("epistemic_integrity_score", 0) for r in recent if isinstance(r.get("epistemic_integrity_score"), (int, float))]
        return sum(scores) / len(scores) if scores else 0.0

    def _store(self, report: dict) -> None:
        """Append introspection report to log file (append-only) + MongoDB."""
        try:
            with open(INTROSPECTION_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(report, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[Introspection] Failed to write log: %s", e)
        # Dual-write to MongoDB
        if hasattr(self, '_mongo') and self._mongo:
            try:
                self._mongo.log_journal("journal_introspection", dict(report))
            except Exception:
                pass

    @staticmethod
    def _empty_report(reason: str) -> dict:
        """Fallback empty report when introspection fails."""
        return {
            "knowledge_sources": {
                "retrieved_memories": [],
                "retrieved_world_data": [],
                "inferred_from_context": [],
                "synthesized": [],
                "potentially_fabricated": [],
            },
            "modules_that_shaped_response": [],
            "confidence_map": {
                "high_confidence": [],
                "medium_confidence": [],
                "low_confidence": [],
            },
            "self_observations": {
                "what_went_well": "Introspection unavailable",
                "what_could_improve": reason,
                "recurring_pattern_noticed": None,
                "failure_mode_detected": reason,
            },
            "internal_state_change": None,
            "epistemic_integrity_score": 0.0,
        }
