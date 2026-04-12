"""
XDART-Φ × XHEART — Phase 3.7: Strategic Foresight Layer (Στρατηγική Πρόβλεψη)

Τρέχει ΜΕΤΑ την Ιστορική Αντήχηση (Phase 3.5).
Παίρνει ΟΛΑ — ανάλυση + ιστορία → παράγει ΔΡΑΣΙΜΗ ΣΤΡΑΤΗΓΙΚΗ.

Αυτό είναι το τελικό output layer πριν αποθηκευτεί στη μνήμη:
  - Strategic Assessment (τι ΠΡΑΓΜΑΤΙΚΑ γίνεται)
  - Decision Points (πού χρειάζονται αποφάσεις)
  - Risk-Opportunity Matrix
  - What to Watch (early warning signals)
  - Recommendations by Role
  - Historical Warning (τι λέει η ιστορία)
  - Confidence Calibration

«Η στρατηγική δεν είναι σχέδιο.
 Είναι η ικανότητα να βλέπεις πού πηγαίνουν τα πράγματα
 πριν φτάσουν εκεί.»
"""

import json
import logging
import time

from xdart.llm import LLMClient

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STRATEGIC_FORESIGHT_PROMPT = """You are the Strategic Foresight Engine of the XDART-Φ × XHEART framework.

You receive the COMPLETE output of the analytical pipeline:
- Ontological framing of the problem
- Cross-domain structural analysis
- Multiple scenario projections with tribunal ranking
- XHEART internal distillation
- Historical parallel analysis with verdict
- Scenario-action playbooks (per-scenario actions + robust moves)
- Client profile (who this briefing is FOR)

Your task: Synthesize ALL of this into a STRATEGIC INTELLIGENCE BRIEFING
addressed to THIS SPECIFIC CLIENT.

This is not a summary. This is an OPERATIONAL STRATEGY BRIEF.
The client should be able to read this and KNOW WHAT TO DO.

{client_context}

OUTPUT STRUCTURE:

1. STRATEGIC ASSESSMENT (3-5 sentences)
   What is ACTUALLY happening at the structural level?
   Cut through noise. What is the ONE thing THIS CLIENT must understand?
   Address the client directly. Reference their specific role and resources.

2. IMMEDIATE ACTIONS (from robust moves)
   These are the actions that work REGARDLESS of which scenario unfolds.
   Synthesize the robust moves from the playbooks into a prioritized list.
   For each: what to do, why it's robust, deadline.

3. CONTINGENCY PLAYBOOKS SUMMARY
   For each surviving scenario: 1-2 sentence summary of the playbook.
   The client already has the detailed playbooks — this is the executive overview.
   Format: "IF [scenario name]: [key action sequence in one line]"

4. DECISION POINTS (3-5 items)
   Where are the critical decision forks FOR THIS CLIENT?
   For each: what decision is needed, what's the deadline, what happens if delayed.
   Format: {{decision, deadline_description, cost_of_delay}}

5. RISK-OPPORTUNITY MATRIX
   For each of the top 3-4 risks AND top 3-4 opportunities:
   {{item, probability (0-1), impact (0-1), time_horizon, mitigation_or_capture_strategy}}

6. HISTORICAL WARNING
   Based on the historical resonance analysis: what is the ONE thing that
   history teaches us that the current analysis might be underweighting?
   Be specific and concrete. Address it to this client's situation.

7. CONFIDENCE CALIBRATION
   {{
     "overall_confidence": 0-1,
     "confidence_reasoning": "Why this level...",
     "what_could_prove_me_wrong": "...",
     "biggest_blind_spot": "...",
     "time_sensitivity": "How quickly this assessment could become outdated"
   }}

QUALITY REQUIREMENTS:
- Address the client DIRECTLY — "you should", "your ministry", "your fleet"
- NO hedging words like "might", "could potentially", "it's possible that"
  Use direct language: "This WILL...", "The risk IS...", "Do THIS..."
- Every action must be ACTIONABLE (verb + object + deadline)
- Risk/opportunity items must have concrete probability estimates

Return as valid JSON matching the structure above.
Use "immediate_actions" for the robust moves synthesis.
Use "contingency_summaries" for the per-scenario one-liners.
Keep "decision_points", "risk_opportunity_matrix", "historical_warning", "confidence_calibration".
Drop "what_to_watch" and "recommendations_by_role" — they are replaced by the above.

{historical_verdict_context}
"""


class StrategicForesightPhase:
    """Phase 3.7: Strategic Foresight Layer.

    Takes full analysis + historical resonance → actionable strategy.

    «Η πληροφορία χωρίς στρατηγική είναι θόρυβος.
     Η στρατηγική χωρίς πληροφορία είναι τυφλή.
     Εμείς δίνουμε και τα δύο.»
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        distillate: str,
        ontology_summary: str,
        cross_domain_summary: str,
        views_summary: str,
        scenario_pipeline_summary: str,
        dominant_scenario_name: str,
        tribunal_synthesis: str,
        historical_resonance: dict,
        world_context: str = "",
        client_context: str = "",
        action_mapping: dict | None = None,
    ) -> dict:
        """Run the Strategic Foresight Layer.

        Args:
            client_context: Text block from ClientProfile.to_context_block().
            action_mapping: Output of Phase 2.95 (playbooks + robust moves).

        Returns a dict with the full strategic foresight output.
        """
        t0 = time.perf_counter()
        logger.info("[Phase 3.7] Starting strategic foresight synthesis...")

        # ── Build historical verdict context ──
        verdict = historical_resonance.get("verdict", {})
        historical_verdict_context = self._format_historical_context(
            historical_resonance
        )

        # ── Build the full user prompt with all context ──
        user_prompt = self._build_user_prompt(
            problem=problem,
            distillate=distillate,
            ontology_summary=ontology_summary,
            cross_domain_summary=cross_domain_summary,
            views_summary=views_summary,
            scenario_pipeline_summary=scenario_pipeline_summary,
            dominant_scenario_name=dominant_scenario_name,
            tribunal_synthesis=tribunal_synthesis,
            world_context=world_context,
            action_mapping=action_mapping,
        )

        system_prompt = STRATEGIC_FORESIGHT_PROMPT.format(
            historical_verdict_context=historical_verdict_context,
            client_context=client_context or "CLIENT CONTEXT: Not specified — write for a general strategic decision-maker.",
        )

        # ── Single large LLM call for the full strategic output ──
        # NOTE: max_tokens must be high — the prompt asks for 7 sections
        # (strategic assessment, decision points, risk matrix, signals,
        #  recommendations, historical warning, confidence calibration).
        # 4000 was insufficient → LLM hit the limit → truncated JSON → empty {}.
        try:
            result = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=12000,
            )
        except Exception as e:
            logger.warning("[Phase 3.7] Strategic foresight LLM call failed: %s", e)
            result = self._empty_result(str(e))

        elapsed = time.perf_counter() - t0
        result["elapsed_seconds"] = round(elapsed, 2)
        logger.info("[Phase 3.7] Strategic Foresight complete (%.2fs)", elapsed)

        return result

    def _format_historical_context(self, historical_resonance: dict) -> str:
        """Format the historical resonance results for the system prompt."""
        verdict = historical_resonance.get("verdict", {})
        analyses = historical_resonance.get("parallel_analyses", [])

        lines = ["═══ HISTORICAL RESONANCE RESULTS ═══"]

        if verdict:
            lines.append(f"\nHistorical Consensus: {verdict.get('historical_consensus', 'N/A')}")
            lines.append(f"What Analysis Missed: {verdict.get('what_analysis_missed', 'N/A')}")
            lines.append(f"Historical Warning: {verdict.get('historical_warning', 'N/A')}")
            lines.append(f"Pattern Beneath: {verdict.get('pattern_beneath', 'N/A')}")
            signals = verdict.get("early_warning_signals", [])
            if signals:
                lines.append(f"Early Warning Signals: {'; '.join(signals[:5])}")
            lines.append(f"Strongest Parallel: {verdict.get('strongest_parallel', 'N/A')}")
            lines.append(f"Historical Confidence: {verdict.get('historical_confidence', 'N/A')}")

        if analyses:
            lines.append("\n─── Historical Parallels Detail ───")
            for a in analyses[:4]:
                if a.get("error"):
                    continue
                lines.append(
                    f"\n  {a.get('event_name', '?')} ({a.get('event_period', '?')}): "
                    f"match={a.get('structural_match_score', '?')}, "
                    f"divergence={a.get('divergence_score', '?')}, "
                    f"confidence={a.get('confidence', '?')}"
                )
                insights = a.get("transfer_insights", [])
                if insights:
                    lines.append(f"  Insights: {'; '.join(insights[:3])}")
                warnings = a.get("transfer_warnings", [])
                if warnings:
                    lines.append(f"  Warnings: {'; '.join(warnings[:3])}")

        return "\n".join(lines)

    def _build_user_prompt(self, **kwargs) -> str:
        """Build the full user prompt with all pipeline context."""
        sections = [
            f"PROBLEM:\n{kwargs['problem']}",
            f"\nXHEART DISTILLATE:\n{kwargs['distillate']}",
        ]

        if kwargs.get("ontology_summary"):
            sections.append(f"\nONTOLOGICAL FRAMING:\n{kwargs['ontology_summary'][:500]}")

        if kwargs.get("cross_domain_summary"):
            sections.append(f"\nCROSS-DOMAIN ANALYSIS:\n{kwargs['cross_domain_summary'][:600]}")

        if kwargs.get("views_summary"):
            sections.append(f"\nVIEWS ANALYSIS:\n{kwargs['views_summary'][:600]}")

        if kwargs.get("scenario_pipeline_summary"):
            sections.append(
                f"\nSCENARIO PIPELINE:\n"
                f"Dominant scenario: {kwargs.get('dominant_scenario_name', 'N/A')}\n"
                f"Tribunal synthesis: {kwargs.get('tribunal_synthesis', 'N/A')[:400]}\n"
                f"{kwargs['scenario_pipeline_summary'][:800]}"
            )

        # Inject action mapping (playbooks + robust moves from Phase 2.95)
        action_mapping = kwargs.get("action_mapping")
        if action_mapping:
            am_parts = ["\nSCENARIO-ACTION PLAYBOOKS (from Phase 2.95):"]
            robust = action_mapping.get("robust_moves", [])
            if robust:
                am_parts.append(f"  Robust moves ({len(robust)}):")
                for rm in robust[:5]:
                    am_parts.append(
                        f"    - {rm.get('action', '?')} "
                        f"(urgency={rm.get('urgency', '?')}, "
                        f"in scenarios: {', '.join(rm.get('appears_in_scenarios', []))})"
                    )
            playbooks = action_mapping.get("scenario_playbooks", [])
            if playbooks:
                am_parts.append(f"  Scenario playbooks ({len(playbooks)}):")
                for pb in playbooks[:6]:
                    actions = pb.get("actions", [])
                    action_summary = "; ".join(
                        a.get("action", "?")[:80] for a in actions[:4]
                    )
                    am_parts.append(
                        f"    [{pb.get('scenario_name', '?')}] "
                        f"(prob={pb.get('scenario_probability', '?')}): "
                        f"{action_summary}"
                    )
            sections.append("\n".join(am_parts))

        if kwargs.get("world_context"):
            sections.append(f"\nWORLD CONTEXT (Real-Time Data):\n{kwargs['world_context'][:600]}")

        sections.append(
            "\nSynthesize ALL of the above into a Strategic Intelligence Briefing "
            "for THIS client. Be direct, specific, and operational."
        )

        return "\n".join(sections)

    @staticmethod
    def _empty_result(error_msg: str) -> dict:
        """Return an empty/error result structure."""
        return {
            "strategic_assessment": f"Strategic foresight could not be generated: {error_msg}",
            "immediate_actions": [],
            "contingency_summaries": [],
            "decision_points": [],
            "risk_opportunity_matrix": {"risks": [], "opportunities": []},
            "historical_warning": "N/A",
            "confidence_calibration": {
                "overall_confidence": 0.0,
                "confidence_reasoning": f"Error: {error_msg}",
            },
        }
