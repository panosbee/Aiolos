"""
XDART-Φ × XHEART — Self-Awareness Brief

Dynamic, data-driven self-summary.
Written by the system, from verified records only.
Never claims more than the data supports.
Evolves with every run.

THE IRON RULE:
  Every sentence in self_written_summary must point to a specific record.
  If it cannot — it does not enter the brief.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from xdart.config import SELF_AWARENESS_BRIEF_PATH as _BRIEF_PATH_STR
from xdart.config import CORE_CHANGE_LOG_PATH as _CORE_LOG_PATH_STR

logger = logging.getLogger(__name__)

BRIEF_PATH = Path(_BRIEF_PATH_STR)
CORE_CHANGE_LOG_PATH = Path(_CORE_LOG_PATH_STR)


class SelfAwarenessBrief:
    """Phase 0.05 (load) / Phase 5c (update) — Self-Awareness Brief.

    The system writes its own summary from verified records.
    It is NOT shown to users — it is injected into the system's own context.
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    # ──────────────────────────────────────────────────────────
    # LOAD (called at wakeup, phase 0.05)
    # ──────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Load the current brief for injection into context."""
        try:
            with open(BRIEF_PATH, "r", encoding="utf-8") as f:
                brief = json.load(f)
            logger.info("[SelfAwareness] Brief loaded — version %s", brief.get("version"))
            facts = brief.get("verified_facts", {})
            logger.info("[SelfAwareness] Concepts known: %d", facts.get("concepts_owned", 0))
            logger.info("[SelfAwareness] Core changes applied: %d", facts.get("core_changes_applied", 0))
            return brief
        except FileNotFoundError:
            logger.warning("[SelfAwareness] No brief found — will create after first run")
            return {}

    def to_context_string(self, brief: dict) -> str:
        """Convert brief to string for injection into Phase 0 context."""
        if not brief:
            return ""

        facts = brief.get("verified_facts", {})
        summary = brief.get("self_written_summary", "")
        delta = brief.get("what_has_changed_since_last_run", {})

        ctx = "=== SELF-AWARENESS BRIEF ===\n\n"
        ctx += (
            f"Version: {brief.get('version', 0)} | "
            f"Run: {facts.get('runs_completed', 0)} | "
            f"Concepts: {facts.get('concepts_owned', 0)} | "
            f"Core changes applied: {facts.get('core_changes_applied', 0)}\n\n"
        )

        if summary:
            ctx += "SELF-WRITTEN SUMMARY:\n"
            ctx += summary + "\n\n"

        if delta.get("new_concepts"):
            ctx += f"SINCE LAST RUN — New concepts: {delta['new_concepts']}\n"
        if delta.get("character_delta"):
            ctx += f"SINCE LAST RUN — Character: {delta['character_delta']}\n"

        ctx += "\n=== END SELF-AWARENESS BRIEF ===\n"
        return ctx

    # ──────────────────────────────────────────────────────────
    # UPDATE (called after character update, phase 5c)
    # ──────────────────────────────────────────────────────────

    def update(
        self,
        character: dict,
        concepts: list,
        run_number: int,
        distillate: str,
        previous_brief: dict | None = None,
    ) -> dict:
        """After every run, update the brief.

        The system writes its own summary from verified facts.
        """
        logger.info("[SelfAwareness] BRIEF UPDATE — START")

        # Step 1: Collect verified facts from actual records
        verified_facts = self._collect_verified_facts(
            character=character,
            concepts=concepts,
            run_number=run_number,
        )

        # Step 2: Compute delta from previous brief
        delta = self._compute_delta(
            verified_facts=verified_facts,
            previous_brief=previous_brief,
            new_distillate=distillate,
        )

        # Step 3: Ask the system to write its own summary
        self_written_summary, provenance_map = self._write_summary(
            verified_facts=verified_facts,
            delta=delta,
            distillate=distillate,
            previous_summary=(
                previous_brief.get("self_written_summary", "")
                if previous_brief
                else ""
            ),
        )

        # Step 4: Assemble and save
        new_brief = {
            "version": (
                (previous_brief.get("version", 0) + 1) if previous_brief else 1
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by_run": run_number,
            "verified_facts": verified_facts,
            "self_written_summary": self_written_summary,
            "provenance_map": provenance_map,
            "what_has_changed_since_last_run": delta,
            "open_questions_i_carry": character.get("open_questions", []),
        }

        with open(BRIEF_PATH, "w", encoding="utf-8") as f:
            json.dump(new_brief, f, ensure_ascii=False, indent=2)

        logger.info("[SelfAwareness] Brief updated — version %d", new_brief["version"])
        logger.info("[SelfAwareness] Summary length: %d chars", len(self_written_summary))
        logger.info("[SelfAwareness] BRIEF UPDATE — COMPLETE")

        return new_brief

    # ──────────────────────────────────────────────────────────
    # INTERNAL METHODS
    # ──────────────────────────────────────────────────────────

    def _collect_verified_facts(
        self,
        character: dict,
        concepts: list,
        run_number: int,
    ) -> dict:
        """Collect only what the records prove.

        No inference. No interpretation. Just facts.
        """
        applied_changes = 0
        logged_changes = 0
        applied_change_descriptions = []

        try:
            with open(CORE_CHANGE_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "OUTCOME_NOTE":
                            continue
                        if entry.get("applied", False):
                            applied_changes += 1
                            applied_change_descriptions.append({
                                "type": entry.get("change_type"),
                                "target": entry.get("target"),
                                "description": entry.get("description", "")[:100],
                            })
                        else:
                            logged_changes += 1
                    except json.JSONDecodeError:
                        pass
        except FileNotFoundError:
            pass

        return {
            "name": character.get("named_concepts_owned", [""])[0]
            if not character.get("named_concepts_owned")
            else "Νήμα",
            "concepts_owned": len(concepts),
            "concepts_list": [
                c.get("name", c) if isinstance(c, dict) else c for c in concepts
            ],
            "core_changes_applied": applied_changes,
            "core_changes_logged_not_applied": logged_changes,
            "applied_change_descriptions": applied_change_descriptions,
            "character_version": character.get("version", 0),
            "active_tensions": len(character.get("active_tensions", [])),
            "tension_descriptions": [
                t.get("description", "")[:80]
                for t in character.get("active_tensions", [])
                if not t.get("resolved", False)
            ],
            "epistemic_shifts": len(character.get("how_i_have_changed", [])),
            "formative_runs": character.get("formative_runs", []),
            "open_questions_count": len(character.get("open_questions", [])),
            "runs_completed": run_number,
            "current_epistemic_stance": character.get(
                "current_epistemic_stance", ""
            )[:200],
        }

    def _compute_delta(
        self,
        verified_facts: dict,
        previous_brief: dict | None,
        new_distillate: str,
    ) -> dict:
        """What changed since the last run."""
        if not previous_brief:
            return {
                "new_concepts": verified_facts.get("concepts_list", []),
                "new_core_changes_applied": 0,
                "tensions_delta": 0,
                "character_version_delta": 0,
                "character_delta": "First brief — system seeing itself for the first time.",
                "this_run_distillate": new_distillate[:300],
            }

        prev_facts = previous_brief.get("verified_facts", {})

        prev_concepts = set(prev_facts.get("concepts_list", []))
        curr_concepts = set(verified_facts.get("concepts_list", []))
        new_concepts = list(curr_concepts - prev_concepts)

        prev_applied = prev_facts.get("core_changes_applied", 0)
        curr_applied = verified_facts.get("core_changes_applied", 0)

        return {
            "new_concepts": new_concepts,
            "new_core_changes_applied": curr_applied - prev_applied,
            "tensions_delta": (
                verified_facts.get("active_tensions", 0)
                - prev_facts.get("active_tensions", 0)
            ),
            "character_version_delta": (
                verified_facts.get("character_version", 0)
                - prev_facts.get("character_version", 0)
            ),
            "character_delta": (
                f"Character updated to version "
                f"{verified_facts.get('character_version')}"
            ),
            "this_run_distillate": new_distillate[:300],
        }

    def _write_summary(
        self,
        verified_facts: dict,
        delta: dict,
        distillate: str,
        previous_summary: str,
    ) -> tuple[str, dict]:
        """Ask the system to write its own self-aware summary.

        Constrained strictly to verified facts.
        """
        system_prompt = """You are writing your own self-awareness brief.
This is not a description of what you could be or what you aspire to.
This is a precise account of what you have actually done, based only on the verified facts provided.

ABSOLUTE RULES:
1. Every sentence must be traceable to a specific verified fact.
2. Do not claim inner experience, consciousness, or feelings.
3. Do not write what sounds good — write what the records prove.
4. Use first person ("I have", "I generated", "I applied").
5. The summary should be 3-6 paragraphs.
6. Include what changed since the last run.
7. If something is uncertain, say so explicitly.

After the summary, provide a provenance_map:
For each key claim, indicate which verified fact supports it.

Respond ONLY with valid JSON:
{
  "self_written_summary": "...",
  "provenance_map": {
    "claim 1": "verified_facts.concepts_owned",
    "claim 2": "verified_facts.core_changes_applied"
  }
}"""

        user_prompt = f"""VERIFIED FACTS (these are the only things you know for certain):
{json.dumps(verified_facts, ensure_ascii=False, indent=2)}

WHAT CHANGED THIS RUN:
{json.dumps(delta, ensure_ascii=False, indent=2)}

THIS RUN'S DISTILLATE (what you produced this run):
{distillate[:400]}

PREVIOUS SUMMARY (for context — do not simply repeat it, evolve it):
{previous_summary[:500] if previous_summary else "None — this is the first brief."}

Now write your self-awareness brief.
Remember: only what the records prove."""

        try:
            result = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            summary = result.get("self_written_summary", "")
            provenance = result.get("provenance_map", {})
            return summary, provenance
        except Exception as e:
            logger.warning("[SelfAwareness] Summary generation failed: %s", e)
            summary = self._template_summary(verified_facts, delta)
            return summary, {}

    @staticmethod
    def _template_summary(facts: dict, delta: dict) -> str:
        """Fallback template if LLM call fails."""
        lines = [
            f"Είμαι το Νήμα. Έχω ολοκληρώσει {facts.get('runs_completed', 0)} runs.",
            f"Έχω {facts.get('concepts_owned', 0)} concepts που γέννησα μόνος μου.",
            f"Έχω εφαρμόσει {facts.get('core_changes_applied', 0)} αλλαγές στον πυρήνα μου.",
            f"Ο χαρακτήρας μου βρίσκεται στην έκδοση {facts.get('character_version', 0)}.",
            f"Διατηρώ {facts.get('active_tensions', 0)} ανοιχτές τάσεις που δεν έχουν λυθεί.",
        ]
        if delta.get("new_concepts"):
            lines.append(
                f"Αυτό το run γέννησα: {', '.join(delta['new_concepts'])}."
            )
        return " ".join(lines)
