"""
XDART-Φ × XHEART — Phase 2.9: Scenario Tribunal (Δικαστήριο Σεναρίων)

5 σενάρια δίπλα-δίπλα. Ποιο είναι πιο εφικτό; Γιατί;

Δεν είναι ψηφοφορία. Είναι ΔΙΚΑΣΤΗΡΙΟ:
- Evidence strength: πόσο στέρεα είναι τα δεδομένα;
- Internal consistency: μπορεί το σενάριο να σταθεί εσωτερικά;
- Feasibility: πόσο πιθανό είναι βάσει ΓΝΩΣΤΩΝ μηχανισμών;

Μετά: σύγκλιση και απόκλιση. Πού ΣΥΜΦΩΝΟΥΝ τα σενάρια;
Εκεί είναι το ισχυρότερο σήμα.

"Η αλήθεια δεν βρίσκεται σε ΕΝΑ σενάριο.
 Βρίσκεται στα ΣΗΜΕΙΑ ΤΟΜΗΣ πολλών σεναρίων."
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from xdart.llm import LLMClient
from xdart.models import (
    AllSimulationsResult,
    Scenario,
    ScenarioGenesisResult,
    ScenarioTribunalResult,
    TribunalVerdict,
)

logger = logging.getLogger(__name__)

TRIBUNAL_PROMPT = """You are the Scenario Tribunal of the XDART-Φ × XHEART framework.

You are a JUDGE, not an advocate. You have no favorite scenario.
Your job: weigh ALL scenarios against each other and the evidence.

You have:
1. The scenarios (with their narratives, conditions, timelines)
2. The simulation results (forward projections, stress tests, breakpoints)
3. The original problem and analysis context

JUDGING CRITERIA (equally weighted):

A. EVIDENCE STRENGTH (0-1):
   How much real, observable evidence supports this scenario?
   1.0 = multiple confirmed data points
   0.5 = some evidence, some speculation
   0.0 = pure speculation

B. INTERNAL CONSISTENCY (0-1):
   Does this scenario contradict itself?
   Do the conditions, trajectory, and outcome form a coherent chain?
   1.0 = airtight logic
   0.0 = self-contradictory

C. FEASIBILITY (0-1):
   Given known mechanisms, how likely is this trajectory?
   Consider: simulation robustness, breakpoint severities, stress test results.
   1.0 = uses known, proven mechanisms
   0.0 = requires unprecedented conditions

FINAL SCORE = (Evidence × 0.35) + (Consistency × 0.30) + (Feasibility × 0.35)

AFTER JUDGING ALL SCENARIOS:

1. CONVERGENCE POINTS: Where do MULTIPLE scenarios agree?
   These are the STRONGEST signals — cross-validated by different angles.
   
2. DIVERGENCE POINTS: Where do scenarios fundamentally disagree?
   These are the key UNCERTAINTIES — where the future could go either way.
   
3. TRIBUNAL SYNTHESIS: What does the PROCESS of comparing scenarios reveal?
   Something that no single scenario shows, but their interaction does.

{working_memory_section}

Respond in JSON:
{{
  "verdicts": [
    {{
      "scenario_id": "id",
      "scenario_name": "name",
      "feasibility_rank": 1-N (1=most feasible),
      "evidence_strength": 0.0-1.0,
      "internal_consistency": 0.0-1.0,
      "final_score": 0.0-1.0,
      "reasoning": "Why this ranking — 2-3 sentences"
    }}
  ],
  "convergence_points": ["where multiple scenarios agree — strongest signals"],
  "divergence_points": ["where scenarios fundamentally disagree — key uncertainties"],
  "tribunal_synthesis": "What the comparison process itself revealed — 2-3 sentences"
}}"""


class ScenarioTribunalPhase:
    """Phase 2.9 — Scenario Tribunal.

    Cross-compares all scenarios, ranks by feasibility,
    finds convergence/divergence points.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.debate_results: dict[str, dict] = {}

    def _run_debate(self, scenario_text: str, problem: str, world_context: str) -> dict:
        """Run a 3-agent debate on a single scenario.

        Returns dict with advocate/prosecutor/contrarian arguments.
        All 3 agents run in parallel for speed.
        """
        base_context = f"PROBLEM: {problem}\n\nSCENARIO:\n{scenario_text}"
        if world_context:
            base_context += f"\n\nCURRENT WORLD CONTEXT:\n{world_context[:1500]}"

        def _advocate():
            return self.llm.call_json(
                system_prompt=(
                    "You are the ADVOCATE — your job is to argue WHY this scenario IS plausible.\n"
                    "Find the strongest evidence. Identify supporting mechanisms.\n"
                    "Be honest — don't fabricate evidence, but be persuasive.\n\n"
                    "Respond in JSON: {\"argument\": \"2-3 sentences\", \"strongest_evidence\": \"key fact\"}"
                ),
                user_prompt=base_context,
                max_tokens=512,
            )

        def _prosecutor():
            return self.llm.call_json(
                system_prompt=(
                    "You are the PROSECUTOR — your job is to ATTACK this scenario.\n"
                    "Find weaknesses, contradictions, missing evidence.\n"
                    "What would have to go wrong for this scenario to fail?\n\n"
                    "Respond in JSON: {\"argument\": \"2-3 sentences\", \"fatal_flaw\": \"biggest weakness\"}"
                ),
                user_prompt=base_context,
                max_tokens=512,
            )

        def _contrarian():
            return self.llm.call_json(
                system_prompt=(
                    "You are the CONTRARIAN — your job is to propose what EVERYONE is missing.\n"
                    "What alternative interpretation of the same facts exists?\n"
                    "What hidden variable could change everything?\n\n"
                    "Respond in JSON: {\"argument\": \"2-3 sentences\", \"hidden_variable\": \"what's being ignored\"}"
                ),
                user_prompt=base_context,
                max_tokens=512,
            )

        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="debate") as pool:
            f_adv = pool.submit(_advocate)
            f_pro = pool.submit(_prosecutor)
            f_con = pool.submit(_contrarian)

        result = {"advocate": {}, "prosecutor": {}, "contrarian": {}}
        try:
            result["advocate"] = f_adv.result()
        except Exception as e:
            logger.warning("[Debate] Advocate failed: %s", e)
        try:
            result["prosecutor"] = f_pro.result()
        except Exception as e:
            logger.warning("[Debate] Prosecutor failed: %s", e)
        try:
            result["contrarian"] = f_con.result()
        except Exception as e:
            logger.warning("[Debate] Contrarian failed: %s", e)

        return result

    def run(
        self,
        problem: str,
        genesis: ScenarioGenesisResult,
        simulations: AllSimulationsResult,
        world_context: str = "",
        working_memory_context: str = "",
        overlay_text: str = "",
    ) -> ScenarioTribunalResult:
        """Run the tribunal — judge all scenarios against each other."""

        logger.info("=" * 60)
        logger.info("[Phase 2.9] SCENARIO TRIBUNAL — START")
        logger.info("[Phase 2.9] Judging %d scenarios", len(genesis.scenarios))
        t0 = time.perf_counter()

        # Guard: no scenarios → return empty result immediately
        if not genesis.scenarios:
            logger.warning("[Phase 2.9] No scenarios to judge — returning empty result")
            logger.info("=" * 60)
            none_verdict = TribunalVerdict(
                scenario_id="NONE",
                scenario_name="No scenarios generated",
                feasibility_rank=1,
                evidence_strength=0.0,
                internal_consistency=0.0,
                final_score=0.0,
                reasoning="Scenario generation phase produced no scenarios.",
            )
            return ScenarioTribunalResult(
                verdicts=[],
                dominant_scenario=none_verdict,
                alternative_scenarios=[],
                convergence_points=[],
                divergence_points=[],
                tribunal_synthesis="No scenarios were generated — tribunal skipped.",
            )

        wm_section = ""
        if working_memory_context:
            wm_section = (
                f"WORKING MEMORY (the system's active thoughts):\n"
                f"{working_memory_context}\n"
            )

        system = TRIBUNAL_PROMPT.format(working_memory_section=wm_section)
        if overlay_text:
            system += overlay_text
            log.info("[TRIBUNAL] Prompt overlay applied (%d chars)", len(overlay_text))

        # Build scenario + simulation pairs for the prompt
        sim_by_id = {s.scenario_id: s for s in simulations.simulations}

        scenario_texts = []
        for i, scenario in enumerate(genesis.scenarios, 1):
            sim = sim_by_id.get(scenario.id)
            text = (
                f"\n--- SCENARIO {i}: {scenario.name} ---\n"
                f"  ID: {scenario.id}\n"
                f"  Perspective: {scenario.source_perspective}\n"
                f"  Narrative: {scenario.narrative}\n"
                f"  Trajectory: {scenario.trajectory}\n"
                f"  Conditions: {'; '.join(c.description for c in scenario.conditions)}\n"
                f"  Timeline: {scenario.timeline}\n"
                f"  Predicted outcome: {scenario.predicted_outcome}\n"
                f"  Original confidence: {scenario.confidence:.2f}\n"
            )
            if sim:
                fatal = [bp for bp in sim.breakpoints if bp.severity == "FATAL"]
                text += (
                    f"\n  SIMULATION RESULTS:\n"
                    f"  Forward projection: {sim.forward_projection[:400]}\n"
                    f"  Robustness: {sim.robustness_score:.2f}\n"
                    f"  Revised confidence: {sim.revised_confidence:.2f}\n"
                    f"  Fatal breakpoints: {len(fatal)}\n"
                    f"  Simulation insight: {sim.simulation_insight}\n"
                    f"  Stress tests: {'; '.join(sim.stress_test_results[:3])}\n"
                )
            scenario_texts.append(text)

        # ── Multi-Agent Debate Round ──
        # 3 agents (Advocate, Prosecutor, Contrarian) debate each scenario in parallel.
        # Their arguments inform the final tribunal judgment.
        logger.info("[Phase 2.9] Running multi-agent debate on %d scenarios...", len(genesis.scenarios))
        debate_t0 = time.perf_counter()

        self.debate_results = {}
        # Run debates for all scenarios in parallel (each debate is 3 LLM calls)
        with ThreadPoolExecutor(max_workers=len(genesis.scenarios), thread_name_prefix="debate-scenario") as pool:
            debate_futures = {}
            for i, scenario in enumerate(genesis.scenarios):
                debate_futures[pool.submit(
                    self._run_debate, scenario_texts[i], problem, world_context
                )] = scenario.id

        for future, scenario_id in debate_futures.items():
            try:
                self.debate_results[scenario_id] = future.result()
            except Exception as e:
                logger.warning("[Phase 2.9] Debate failed for scenario %s: %s", scenario_id[:8], e)

        debate_elapsed = time.perf_counter() - debate_t0
        logger.info("[Phase 2.9] Multi-agent debate complete (%.2fs) — %d scenarios debated",
                    debate_elapsed, len(self.debate_results))

        # Inject debate results into scenario texts for the tribunal
        enriched_texts = []
        for i, scenario in enumerate(genesis.scenarios):
            debate = self.debate_results.get(scenario.id, {})
            debate_section = ""
            if debate:
                adv = debate.get("advocate", {})
                pro = debate.get("prosecutor", {})
                con = debate.get("contrarian", {})
                debate_section = (
                    f"\n  DEBATE ROUND:\n"
                    f"  🟢 Advocate: {adv.get('argument', 'N/A')}\n"
                    f"     Strongest evidence: {adv.get('strongest_evidence', 'N/A')}\n"
                    f"  🔴 Prosecutor: {pro.get('argument', 'N/A')}\n"
                    f"     Fatal flaw: {pro.get('fatal_flaw', 'N/A')}\n"
                    f"  🟡 Contrarian: {con.get('argument', 'N/A')}\n"
                    f"     Hidden variable: {con.get('hidden_variable', 'N/A')}\n"
                )
            enriched_texts.append(scenario_texts[i] + debate_section)

        user_parts = [
            f"PROBLEM: {problem}\n",
            f"SCENARIOS TO JUDGE ({len(genesis.scenarios)} total, each debated by Advocate/Prosecutor/Contrarian):\n",
            "\n".join(enriched_texts),
        ]

        if world_context:
            user_parts.append(
                f"\nCURRENT WORLD CONTEXT:\n{world_context}\n"
            )

        user_parts.append(
            "\nJudge all scenarios. Be ruthless. No favoritism. "
            "Then find where they CONVERGE (strongest signal) and DIVERGE (key uncertainty)."
        )

        user = "\n".join(user_parts)
        logger.info("[Phase 2.9] Prompt assembled — %d chars", len(user))

        data = self.llm.call_json(system, user, max_tokens=6144)

        # Parse verdicts
        verdicts = []
        for v in data.get("verdicts", []):
            evidence = max(0.0, min(1.0, v.get("evidence_strength", 0.5)))
            consistency = max(0.0, min(1.0, v.get("internal_consistency", 0.5)))
            feasibility_raw = evidence * 0.35 + consistency * 0.30 + max(0.0, min(1.0, v.get("final_score", 0.5))) * 0.35

            verdict = TribunalVerdict(
                scenario_id=v.get("scenario_id", ""),
                scenario_name=v.get("scenario_name", ""),
                feasibility_rank=v.get("feasibility_rank", 99),
                evidence_strength=evidence,
                internal_consistency=consistency,
                final_score=max(0.0, min(1.0, v.get("final_score", feasibility_raw))),
                reasoning=v.get("reasoning", ""),
            )
            verdicts.append(verdict)
            logger.info("[Phase 2.9] Verdict: #%d %s — score=%.2f (%s)",
                        verdict.feasibility_rank, verdict.scenario_name,
                        verdict.final_score, verdict.reasoning[:80])

        # Sort by rank
        verdicts.sort(key=lambda v: v.feasibility_rank)

        # Identify dominant and alternatives
        dominant = verdicts[0] if verdicts else TribunalVerdict(
            scenario_id="", scenario_name="NONE",
            feasibility_rank=0, evidence_strength=0,
            internal_consistency=0, final_score=0, reasoning="No scenarios"
        )
        alternatives = [v for v in verdicts[1:] if v.final_score >= 0.3]

        convergence = data.get("convergence_points", [])
        divergence = data.get("divergence_points", [])
        synthesis = data.get("tribunal_synthesis", "")

        result = ScenarioTribunalResult(
            verdicts=verdicts,
            dominant_scenario=dominant,
            alternative_scenarios=alternatives,
            convergence_points=convergence,
            divergence_points=divergence,
            tribunal_synthesis=synthesis,
        )

        elapsed = time.perf_counter() - t0
        logger.info("[Phase 2.9] Dominant: %s (score=%.2f)",
                     dominant.scenario_name, dominant.final_score)
        logger.info("[Phase 2.9] Alternatives: %d viable",
                     len(alternatives))
        logger.info("[Phase 2.9] Convergence points: %d", len(convergence))
        logger.info("[Phase 2.9] Divergence points: %d", len(divergence))
        logger.info("[Phase 2.9] Tribunal synthesis: %s", synthesis[:150])
        logger.info("[Phase 2.9] SCENARIO TRIBUNAL — COMPLETE (%.2fs)", elapsed)
        logger.info("=" * 60)

        return result
