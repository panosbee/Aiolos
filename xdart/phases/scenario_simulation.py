"""
XDART-Φ × XHEART — Phase 2.7: Scenario Simulation (Προσομοίωση Σεναρίων)

Κάθε σενάριο δεν αρκεί να υπάρχει. Πρέπει να ΤΡΕΞΕΙ.

Forward-projection: πάρε το σενάριο και "παίξε το" βήμα-βήμα.
Stress-test: σπρώξε τις υποθέσεις — πού σπάει;
Breakpoints: πού ακριβώς αποτυγχάνει η τροχιά;

"Ένα σενάριο χωρίς simulation είναι ευχολόγιο."

Input:  Scenarios from Phase 2.5
Output: For each scenario — forward projection, stress tests, breakpoints, revised confidence
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from xdart.llm import LLMClient
from xdart.models import (
    AllSimulationsResult,
    Scenario,
    ScenarioSimulationResult,
    SimulationBreakpoint,
)

logger = logging.getLogger(__name__)

SIMULATION_PROMPT = """You are the Scenario Simulation Engine of XDART-Φ.

You are given ONE scenario. Your job: RUN IT FORWARD.

Not passively. Actively. As if you are a historian writing about the FUTURE.

PROCESS:
1. FORWARD PROJECTION:
   Start from NOW. Take the scenario's trajectory and unfold it step by step.
   At each step ask: "What happens NEXT, given this step?"
   Be specific — names, mechanisms, timelines. Not vague hand-waving.
   (4-8 steps from now to the predicted outcome)

2. STRESS TESTING:
   Take each assumption in the scenario and PUSH it:
   - "What if this condition DOESN'T hold?"
   - "What if the opposite happens?"
   - "What if the timeline is much shorter / much longer?"
   Report 3-5 stress test results.

3. BREAKPOINT ANALYSIS:
   Where EXACTLY does this scenario fail?
   - FATAL breakpoints: the scenario cannot recover
   - DEGRADING breakpoints: weakened but still possible
   - MINOR: a bump, keeps going
   At least 2 breakpoints per scenario.

4. ROBUSTNESS SCORE:
   After stress testing, how robust is this scenario? (0-1)
   0.0 = falls apart immediately
   0.5 = plausible but fragile
   1.0 = extremely robust (rare)

5. REVISED CONFIDENCE:
   Original confidence was {original_confidence:.2f}.
   After simulation, what is your revised confidence?
   Be honest — simulations usually LOWER confidence because they expose weaknesses.

6. SIMULATION INSIGHT:
   What did the simulation reveal that the original scenario MISSED?

{world_context_section}

{working_memory_section}

Respond in JSON:
{{
  "forward_projection": "Step-by-step unfolding (4-8 steps, each 1-2 sentences)",
  "stress_test_results": ["result 1", "result 2", "result 3"],
  "breakpoints": [
    {{"at_step": "which step", "reason": "why it breaks", "severity": "FATAL|DEGRADING|MINOR"}}
  ],
  "robustness_score": 0.0-1.0,
  "revised_confidence": 0.0-1.0,
  "simulation_insight": "Key insight from running this forward — 1-2 sentences"
}}"""


class ScenarioSimulationPhase:
    """Phase 2.7 — Scenario Simulation.

    Forward-projects each scenario, stress-tests assumptions, finds breakpoints.
    Runs scenarios in parallel for speed.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def _simulate_single(
        self,
        scenario: Scenario,
        problem: str,
        world_context: str = "",
        working_memory_context: str = "",
        overlay_text: str = "",
    ) -> ScenarioSimulationResult:
        """Simulate a single scenario."""

        logger.info("[Phase 2.7] Simulating: %s (confidence=%.2f)",
                     scenario.name, scenario.confidence)
        t0 = time.perf_counter()

        world_section = ""
        if world_context:
            world_section = (
                f"CURRENT WORLD CONTEXT (use this to ground your simulation):\n"
                f"{world_context}\n"
            )

        wm_section = ""
        if working_memory_context:
            wm_section = (
                f"WORKING MEMORY (active thoughts — let these inform the simulation):\n"
                f"{working_memory_context}\n"
            )

        system = SIMULATION_PROMPT.format(
            original_confidence=scenario.confidence,
            world_context_section=world_section,
            working_memory_section=wm_section,
        )
        if overlay_text:
            system += overlay_text

        conditions_text = "\n".join(
            f"  - {c.description} (currently {'MET' if c.currently_met else 'NOT MET'}: {c.evidence})"
            for c in scenario.conditions
        )

        user = (
            f"PROBLEM: {problem}\n\n"
            f"SCENARIO TO SIMULATE:\n"
            f"  Name: {scenario.name}\n"
            f"  Perspective: {scenario.source_perspective}\n"
            f"  Narrative: {scenario.narrative}\n"
            f"  Trajectory: {scenario.trajectory}\n"
            f"  Conditions:\n{conditions_text}\n"
            f"  Timeline: {scenario.timeline}\n"
            f"  Predicted outcome: {scenario.predicted_outcome}\n"
            f"  Original confidence: {scenario.confidence:.2f}\n\n"
            f"Run this scenario forward. Be rigorous. Where does it break?"
        )

        data = self.llm.call_json(system, user, max_tokens=4096)

        breakpoints = []
        for bp in data.get("breakpoints", []):
            breakpoints.append(SimulationBreakpoint(
                at_step=bp.get("at_step", ""),
                reason=bp.get("reason", ""),
                severity=bp.get("severity", "MINOR"),
            ))

        result = ScenarioSimulationResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            forward_projection=data.get("forward_projection", ""),
            stress_test_results=data.get("stress_test_results", []),
            breakpoints=breakpoints,
            robustness_score=max(0.0, min(1.0, data.get("robustness_score", 0.5))),
            revised_confidence=max(0.0, min(1.0, data.get("revised_confidence", scenario.confidence))),
            simulation_insight=data.get("simulation_insight", ""),
        )

        elapsed = time.perf_counter() - t0
        logger.info("[Phase 2.7] %s — robustness=%.2f, confidence: %.2f→%.2f, breakpoints=%d (%.2fs)",
                     scenario.name, result.robustness_score,
                     scenario.confidence, result.revised_confidence,
                     len(breakpoints), elapsed)

        return result

    def run(
        self,
        problem: str,
        scenarios: list[Scenario],
        world_context: str = "",
        working_memory_context: str = "",
        overlay_text: str = "",
    ) -> AllSimulationsResult:
        """Simulate all scenarios (parallel where possible)."""

        logger.info("=" * 60)
        logger.info("[Phase 2.7] SCENARIO SIMULATION — START (%d scenarios)", len(scenarios))
        t0 = time.perf_counter()

        # Guard: no scenarios → return empty result immediately
        if not scenarios:
            logger.warning("[Phase 2.7] No scenarios to simulate — returning empty result")
            logger.info("=" * 60)
            return AllSimulationsResult(
                simulations=[],
                simulation_summary="No scenarios were generated — simulation skipped.",
            )

        simulations: list[ScenarioSimulationResult] = []

        # Run simulations in parallel (max 4 concurrent)
        max_workers = min(4, len(scenarios))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for scenario in scenarios:
                future = executor.submit(
                    self._simulate_single,
                    scenario, problem, world_context, working_memory_context, overlay_text,
                )
                futures[future] = scenario.name

            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    simulations.append(result)
                except Exception as exc:
                    logger.warning("[Phase 2.7] Simulation failed for %s: %s", name, exc)

        # Generate overall summary
        summary_parts = []
        for sim in simulations:
            fatal_count = sum(1 for bp in sim.breakpoints if bp.severity == "FATAL")
            summary_parts.append(
                f"{sim.scenario_name}: robustness={sim.robustness_score:.2f}, "
                f"confidence={sim.revised_confidence:.2f}, "
                f"fatal_breakpoints={fatal_count}"
            )
        simulation_summary = " | ".join(summary_parts)

        elapsed = time.perf_counter() - t0
        logger.info("[Phase 2.7] SCENARIO SIMULATION — COMPLETE (%.2fs)", elapsed)
        logger.info("[Phase 2.7] Summary: %s", simulation_summary)
        logger.info("=" * 60)

        return AllSimulationsResult(
            simulations=simulations,
            simulation_summary=simulation_summary,
        )
