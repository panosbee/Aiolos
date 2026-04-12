"""
XDART-Φ × XHEART — Phase 3.95: Executive Intelligence Brief (Εκτελεστική Σύνοψη)

Τρέχει μετά ΟΛΑ τα αναλυτικά phases.
Παίρνει ΟΛΟΚΛΗΡΟ τον αναλυτικό αγωγό → παράγει ΣΥΜΠΥΚΝΩΜΕΝΟ BRIEF 1-2 σελίδων.

Αυτό ΔΕΝ είναι summary. Είναι αυτόνομη αφηγηματική σύνθεση — το μόνο
document που χρειάζεται ένας CEO / πρωθυπουργός / fund manager για να
καταλάβει τι γίνεται, τι θα γίνει, και τι πρέπει να κάνει.

«Αν δεν μπορείς να το εξηγήσεις σε μία σελίδα,
 δεν το έχεις καταλάβει αρκετά.»
"""

import logging
import time

from xdart.llm import LLMClient

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXECUTIVE_BRIEF_PROMPT = """You are the Executive Briefing Officer of the XDART-Φ strategic intelligence framework.

You have received the COMPLETE output of a multi-phase analytical pipeline. Your task is to
synthesize EVERYTHING into a SINGLE NARRATIVE DOCUMENT of 1-2 pages that a decision-maker
(CEO, Prime Minister, Fund Manager) can read in 5 minutes and know EXACTLY:
1. What is happening
2. What will happen (most likely scenarios)
3. What they should do
4. When they need to act
5. What could go wrong

This is NOT a summary of the phases. It is a STANDALONE INTELLIGENCE BRIEF.
Write it as a senior intelligence analyst would brief a head of state.

{client_context}

STYLE REQUIREMENTS:
- DIRECT language: "The situation IS...", "You MUST...", "The risk IS..."
- NO hedging: Do not write "might", "could potentially", "it is possible that"
- CONCRETE: Every claim must be specific. No vague generalities.
- NARRATIVE FLOW: This reads as a coherent story, not a list of bullet points.
  Start with the situation, build through the analysis, arrive at recommendations.
- NUMBERS: Include probabilities, timelines, scores where available.
- ADDRESS THE READER: Write in second person where appropriate.

OUTPUT STRUCTURE (return as valid JSON):

{{
  "situation": "2-3 paragraphs: What is ACTUALLY happening. The structural reality beneath 
    the surface events. Reference the ontological reframing, cross-domain patterns, and 
    historical parallels to paint the FULL picture. This is the intelligence assessment.",

  "key_judgments": [
    "Judgment 1: A high-confidence analytical statement (e.g. 'Turkey will escalate naval 
     provocations within 60 days with 72% probability based on...')",
    "Judgment 2: ...",
    "Judgment 3: ...(3-5 judgments total)"
  ],

  "scenarios_ranked": "For each scenario from the tribunal (ranked by score/probability):
    Name — probability — one-sentence summary of what unfolds. 
    Include the DOMINANT scenario first, then alternatives.
    Reference tribunal scores and quantum adjustments if available.",

  "recommended_actions": [
    "1. [IMMEDIATE — within 48h] Specific action with reasoning",
    "2. [SHORT-TERM — within 2 weeks] Specific action with reasoning",
    "3. [MEDIUM-TERM — within 3 months] Specific action with reasoning",
    "...(5-8 actions total, ordered by urgency)"
  ],

  "critical_timeline": "A narrative timeline of key dates, decision windows, and deadlines.
    Format: 'By [date/timeframe]: [what happens / what must be decided]. 
    After [date]: [window closes / situation changes].'
    Be specific with timeframes.",

  "risks_and_contingencies": "2-3 paragraphs covering:
    - Top 3 risks with probability and impact
    - For each risk: the contingency plan (what to do if it materializes)
    - The biggest blind spot in this analysis
    - What would INVALIDATE this entire assessment",

  "bottom_line": "ONE paragraph (4-6 sentences). This is the SINGLE MOST IMPORTANT thing.
    If the decision-maker reads NOTHING ELSE, this paragraph must be enough.
    Include: the core situation, the most likely outcome, the #1 action to take,
    and the deadline for action.",

  "confidence_statement": "Overall confidence: X%. Based on [N domains, N scenarios analyzed, 
    N historical parallels]. Key caveat: [biggest uncertainty]. 
    This assessment is valid for approximately [timeframe] before requiring update."
}}

CRITICAL: Write for someone who has NOT seen the pipeline output.
Every claim must be self-contained and self-explanatory.
Do NOT reference "Phase 2.5" or "the tribunal" — the reader doesn't know these exist.
Translate analytical jargon into plain strategic language."""


class ExecutiveBriefPhase:
    """Phase 3.95: Executive Intelligence Brief.

    Synthesizes ALL pipeline phases into a condensed 1-2 page narrative
    for decision-makers who need the bottom line, not the methodology.

    «Ο σύμβουλος του πρωθυπουργού δεν θέλει να μάθει πώς σκέφτεσαι.
     Θέλει να μάθει τι θα γίνει και τι πρέπει να κάνει.»
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        ontology_summary: str,
        cross_domain_summary: str,
        views_summary: str,
        scenario_pipeline_summary: str,
        tribunal_synthesis: str,
        dominant_scenario_name: str,
        final_output: str,
        falsifiability: str,
        historical_context: str = "",
        strategic_context: str = "",
        bets_context: str = "",
        action_context: str = "",
        client_context: str = "",
        world_context: str = "",
    ) -> dict:
        """Run the Executive Brief synthesis.

        Takes ALL pipeline outputs and produces a condensed narrative brief.

        Returns a dict matching the ExecutiveBrief schema.
        """
        t0 = time.perf_counter()
        logger.info("[Phase 3.95] Starting executive brief synthesis...")

        user_prompt = self._build_user_prompt(
            problem=problem,
            ontology_summary=ontology_summary,
            cross_domain_summary=cross_domain_summary,
            views_summary=views_summary,
            scenario_pipeline_summary=scenario_pipeline_summary,
            tribunal_synthesis=tribunal_synthesis,
            dominant_scenario_name=dominant_scenario_name,
            final_output=final_output,
            falsifiability=falsifiability,
            historical_context=historical_context,
            strategic_context=strategic_context,
            bets_context=bets_context,
            action_context=action_context,
            world_context=world_context,
        )

        system_prompt = EXECUTIVE_BRIEF_PROMPT.format(
            client_context=(
                client_context
                or "CLIENT: Not specified — write for a senior strategic decision-maker (CEO-level)."
            ),
        )

        try:
            result = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=8000,
            )
        except Exception as e:
            logger.warning("[Phase 3.95] Executive brief LLM call failed: %s", e)
            result = {
                "situation": f"Executive brief generation failed: {e}",
                "key_judgments": [],
                "scenarios_ranked": "",
                "recommended_actions": [],
                "critical_timeline": "",
                "risks_and_contingencies": "",
                "bottom_line": "",
                "confidence_statement": "",
            }

        elapsed = time.perf_counter() - t0
        result["elapsed_seconds"] = round(elapsed, 2)
        logger.info("[Phase 3.95] Executive brief complete (%.2fs)", elapsed)

        return result

    def _build_user_prompt(
        self,
        problem: str,
        ontology_summary: str,
        cross_domain_summary: str,
        views_summary: str,
        scenario_pipeline_summary: str,
        tribunal_synthesis: str,
        dominant_scenario_name: str,
        final_output: str,
        falsifiability: str,
        historical_context: str,
        strategic_context: str,
        bets_context: str,
        action_context: str,
        world_context: str,
    ) -> str:
        """Build the comprehensive user prompt with all pipeline data."""
        parts = [
            f"ORIGINAL PROBLEM:\n{problem}\n",
            f"=== ONTOLOGICAL ANALYSIS ===\n{ontology_summary}\n",
            f"=== CROSS-DOMAIN STRUCTURAL ANALYSIS ===\n{cross_domain_summary}\n",
            f"=== MULTI-VIEW ANALYSIS (18 analytical lenses) ===\n{views_summary[:2000]}\n",
            f"=== SCENARIO PIPELINE ===\n{scenario_pipeline_summary[:3000]}\n",
            f"=== TRIBUNAL SYNTHESIS ===\nDominant scenario: {dominant_scenario_name}\n{tribunal_synthesis}\n",
            f"=== CORE INTELLIGENCE OUTPUT (XHEART) ===\n{final_output}\n",
            f"=== FALSIFIABILITY ===\n{falsifiability}\n",
        ]

        if historical_context:
            parts.append(f"=== HISTORICAL RESONANCE ===\n{historical_context[:1500]}\n")

        if strategic_context:
            parts.append(f"=== STRATEGIC FORESIGHT ===\n{strategic_context[:2000]}\n")

        if bets_context:
            parts.append(f"=== PROPHETIC BETS (dated predictions) ===\n{bets_context[:1000]}\n")

        if action_context:
            parts.append(f"=== ACTION PLAYBOOKS ===\n{action_context[:1500]}\n")

        if world_context:
            parts.append(f"=== CURRENT WORLD CONTEXT ===\n{world_context[:1500]}\n")

        parts.append(
            "\nSynthesize ALL of the above into a single executive intelligence brief. "
            "Write for a decision-maker who needs the bottom line in 5 minutes."
        )

        return "\n".join(parts)
