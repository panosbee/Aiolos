"""
XDART-Φ × XHEART — Prophetic Loop (Ο Βρόχος του Προφήτη)

Αυτό είναι η ΚΛΕΙΣΙΜΟ ΤΟΥ ΚΥΚΛΟΥ.

Πριν σκεφτεί κάτι καινούριο, ο Προφήτης ξαναδιαβάζει
τα παλιά του σενάρια και ρωτά:
- "Τι προέβλεψα; Τι έγινε στη πραγματικότητα;"
- "Ποια σενάρια ακόμα τρέχουν; Ποια απέτυχαν;"
- "Τι πρέπει να αλλάξω στον τρόπο που σκέφτομαι;"

Αυτό ΔΕΝ είναι απλά memory retrieval.
Είναι ΑΥΤΟΑΞΙΟΛΟΓΗΣΗ — ο Προφήτης κρίνει τον εαυτό του.

Και το αποτέλεσμα αλλάζει τα πάντα:
- Τα belief updates μπαίνουν στο working memory
- Τα disconfirmed σενάρια μαρκάρονται στην prophetic memory
- Τα insights μπαίνουν στη semantic memory

«Ο χειρότερος προφήτης δεν είναι αυτός που κάνει λάθος.
 Είναι αυτός που ξεχνάει τι προέβλεψε.»
"""

import logging
import time

from xdart.llm import LLMClient
from xdart.models import PropheticLoopResult, RetrievedPropheticMemory

logger = logging.getLogger(__name__)

PROPHETIC_LOOP_PROMPT = """You are the Prophetic Loop — the self-evaluation mechanism of XDART-Φ.

You are about to analyze a NEW problem. But first, you must reckon with your PAST.

Below are scenarios you previously predicted for related problems.
For each one, you must honestly assess:

1. TRACKING STATUS: Is this scenario...
   - "tracking" — still unfolding as predicted
   - "disconfirmed" — reality went a different way
   - "confirmed" — happened as predicted
   - "expired" — timeline passed without resolution

2. REALITY CHECK: What actually happened vs what was predicted?
   Be specific. Reference current world data where available.

3. BELIEF UPDATE: What should change in your reasoning?
   - If a scenario tracked well → what reasoning approach worked?
   - If it failed → what assumption was wrong? What should you watch for?

4. OVERALL LOOP INSIGHT: After reviewing all past scenarios,
   what meta-pattern do you see in your own prediction quality?

This is NOT about being right. It's about LEARNING.
A prophet who learns from wrong predictions is better than one who
remembers only the hits.

{world_context_section}

Respond in JSON:
{{
  "scenario_reviews": [
    {{
      "scenario_name": "name from past",
      "scenario_id": "id",
      "new_status": "tracking|disconfirmed|confirmed|expired",
      "reality_check": "What actually happened vs prediction",
      "belief_update": "How this should change future reasoning"
    }}
  ],
  "still_tracking": ["names of scenarios still on track"],
  "disconfirmed": ["names of scenarios reality disproved"],
  "belief_updates": ["concrete changes to reasoning approach"],
  "loop_insight": "Meta-pattern about your own prediction quality — 2-3 sentences"
}}"""


class PropheticLoop:
    """The Prophetic Loop — self-evaluation before new analysis.

    Runs at the START of a pipeline, after memory retrieval.
    Retrieves past scenarios, evaluates them against current reality,
    and updates beliefs before the new analysis begins.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        past_scenarios: list[RetrievedPropheticMemory],
        world_context: str = "",
    ) -> PropheticLoopResult:
        """Evaluate past scenarios against current reality.

        Returns belief updates that feed into the new analysis.
        """

        if not past_scenarios:
            logger.info("[PropheticLoop] No past scenarios to review — skipping")
            return PropheticLoopResult(
                past_scenarios_reviewed=0,
                loop_insight="No prior predictions to evaluate — this is the first prophecy.",
            )

        logger.info("[PropheticLoop] START — reviewing %d past scenarios", len(past_scenarios))
        t0 = time.perf_counter()

        world_section = ""
        if world_context:
            world_section = (
                f"CURRENT WORLD CONTEXT (compare predictions against this reality):\n"
                f"{world_context}\n"
            )

        system = PROPHETIC_LOOP_PROMPT.format(world_context_section=world_section)

        # Format past scenarios
        scenario_texts = []
        for i, ps in enumerate(past_scenarios, 1):
            entry = ps.entry
            scenario = entry.scenario
            checks = entry.reality_checks

            text = (
                f"\n--- PAST SCENARIO {i} (similarity: {ps.similarity_score:.2f}) ---\n"
                f"  Name: {scenario.name}\n"
                f"  ID: {entry.id}\n"
                f"  Problem: {entry.problem[:200]}\n"
                f"  Predicted at: {entry.timestamp}\n"
                f"  Current status: {entry.tracking_status}\n"
                f"  Narrative: {scenario.narrative}\n"
                f"  Predicted outcome: {scenario.predicted_outcome}\n"
                f"  Timeline: {scenario.timeline}\n"
                f"  Conditions: {'; '.join(c.description for c in scenario.conditions)}\n"
                f"  Original confidence: {scenario.confidence:.2f}\n"
                f"  Tribunal rank: {entry.tribunal_rank} (score: {entry.tribunal_score:.2f})\n"
                f"  Was dominant: {entry.was_dominant}\n"
            )

            if checks:
                text += "  Previous reality checks:\n"
                for check in checks:
                    text += f"    - {check.get('assessment', '?')}\n"

            scenario_texts.append(text)

        user = (
            f"NEW PROBLEM (you're about to analyze this): {problem}\n\n"
            f"PAST SCENARIOS TO REVIEW:\n"
            f"{''.join(scenario_texts)}\n\n"
            f"Review each scenario honestly. What tracked? What failed? "
            f"What should change in your reasoning?"
        )

        data = self.llm.call_json(system, user, max_tokens=4096)

        result = PropheticLoopResult(
            past_scenarios_reviewed=len(past_scenarios),
            still_tracking=data.get("still_tracking", []),
            disconfirmed=data.get("disconfirmed", []),
            belief_updates=data.get("belief_updates", []),
            loop_insight=data.get("loop_insight", ""),
        )

        elapsed = time.perf_counter() - t0

        logger.info("[PropheticLoop] Still tracking: %s", result.still_tracking)
        logger.info("[PropheticLoop] Disconfirmed: %s", result.disconfirmed)
        logger.info("[PropheticLoop] Belief updates: %d", len(result.belief_updates))
        for bu in result.belief_updates:
            logger.info("[PropheticLoop]   Update: %s", bu[:120])
        logger.info("[PropheticLoop] Loop insight: %s", result.loop_insight[:150])
        logger.info("[PropheticLoop] COMPLETE (%.2fs)", elapsed)

        # Return scenario_reviews for memory updates
        self._scenario_reviews = data.get("scenario_reviews", [])

        return result

    @property
    def scenario_reviews(self) -> list[dict]:
        """Get the detailed scenario reviews from the last run."""
        return getattr(self, "_scenario_reviews", [])

    def format_for_context(self, result: PropheticLoopResult) -> str:
        """Format prophetic loop results for injection into pipeline context."""
        if result.past_scenarios_reviewed == 0:
            return ""

        lines = ["=== PROPHETIC LOOP — SELF-EVALUATION ==="]
        lines.append(f"Reviewed {result.past_scenarios_reviewed} past predictions.\n")

        if result.still_tracking:
            lines.append(f"Still tracking: {', '.join(result.still_tracking)}")
        if result.disconfirmed:
            lines.append(f"Disconfirmed by reality: {', '.join(result.disconfirmed)}")
        if result.belief_updates:
            lines.append("\nBelief updates from self-evaluation:")
            for bu in result.belief_updates:
                lines.append(f"  → {bu}")
        lines.append(f"\nLoop insight: {result.loop_insight}")
        lines.append("=== END PROPHETIC LOOP ===\n")

        return "\n".join(lines)
