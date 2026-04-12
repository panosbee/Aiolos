"""
XDART-Φ — Phase 2.95: Scenario-Action Mapping

Sits between Tribunal (2.9) and XHEART (3).
Takes surviving scenarios + client profile → generates:
  1. Per-scenario playbooks (3-5 concrete actions per scenario)
  2. Robust moves (actions that appear across multiple scenarios)

The output is NOT generic advice. It is addressed to a SPECIFIC client
with SPECIFIC resources, constraints, and time horizons.
"""

import logging
import time
from typing import Any

from xdart.llm import LLMClient

logger = logging.getLogger(__name__)


SCENARIO_ACTION_PROMPT = """You are an operational advisor converting scenario intelligence into actionable playbooks.

You have:
- A set of surviving scenarios from a rigorous tribunal process
- The dominant scenario (most likely) and alternative scenarios
- A CLIENT PROFILE describing who will execute these actions

YOUR JOB: For each surviving scenario, produce a concrete playbook of 3-5 actions
that THIS SPECIFIC CLIENT can execute with THEIR SPECIFIC resources.

{client_context}

RULES:
1. SPECIFICITY: Every action must name the resource, the channel, the target.
   Not "engage diplomatically" but "call the French president via the direct line
   and propose joint naval observation within 48h."
2. SEQUENCE: Actions have execution order. Some depend on others completing first.
3. DEADLINES: Every action has a time window. "Within 90 minutes", "within 24h",
   "before the next NAVTEX cycle."
4. CLIENT-BOUND: Only recommend actions this client CAN ACTUALLY TAKE.
   A shipping CEO cannot call a foreign minister. A PM advisor cannot reposition tankers.
5. MECHANISM: HOW does the client do this? Phone call, written directive, press briefing,
   fleet repositioning, intelligence tasking?

AFTER generating per-scenario playbooks, identify ROBUST MOVES:
- Actions that appear (in substance, not wording) across 2+ scenario playbooks
- These are the "do regardless" actions — they help no matter what happens
- Rank them by urgency (immediate → 24h → 1 week)

Return JSON:
{{
  "client_role": "brief description of who this is for",
  "scenario_playbooks": [
    {{
      "scenario_id": "...",
      "scenario_name": "...",
      "scenario_probability": 0.65,
      "rationale": "Why these specific actions for this scenario",
      "actions": [
        {{
          "action": "Specific verb + object + target",
          "sequence": 1,
          "deadline": "Within 90 minutes",
          "mechanism": "Direct phone call to...",
          "depends_on": ""
        }}
      ]
    }}
  ],
  "robust_moves": [
    {{
      "action": "The action that works across scenarios",
      "appears_in_scenarios": ["Scenario A", "Scenario B"],
      "urgency": "immediate",
      "reasoning": "Why this is robust — what it hedges against"
    }}
  ]
}}

Generate playbooks ONLY for scenarios with tribunal score >= 0.3.
Robust moves must appear in at least 2 scenario playbooks.
Maximum 5 robust moves. Maximum 5 actions per scenario playbook."""


class ScenarioActionMappingPhase:
    """Phase 2.95: Converts surviving scenarios into client-specific action playbooks."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        tribunal_verdicts: list[dict],
        dominant_scenario_name: str,
        tribunal_synthesis: str,
        scenario_narratives: dict[str, str],
        client_context: str,
        world_context: str = "",
    ) -> dict:
        """Generate per-scenario playbooks + robust moves.

        Args:
            problem: Original problem statement.
            tribunal_verdicts: List of TribunalVerdict dicts (all scenarios that survived).
            dominant_scenario_name: Name of the dominant scenario.
            tribunal_synthesis: What the tribunal process revealed.
            scenario_narratives: Dict mapping scenario_name → full narrative text.
            client_context: Text block from ClientProfile.to_context_block().
            world_context: Current world data.

        Returns:
            Dict with scenario_playbooks, robust_moves, client_role, elapsed_seconds.
        """
        t0 = time.perf_counter()
        logger.info("[Phase 2.95] Scenario-Action Mapping start — %d scenarios, client=%s",
                     len(tribunal_verdicts), client_context[:80])

        # Build the scenario summary for the prompt
        scenario_parts = []
        for v in tribunal_verdicts:
            name = v.get("scenario_name", "?")
            score = v.get("final_score", 0)
            rank = v.get("feasibility_rank", 0)
            reasoning = v.get("reasoning", "")
            narrative = scenario_narratives.get(name, "")[:500]
            is_dominant = " [DOMINANT]" if name == dominant_scenario_name else ""
            scenario_parts.append(
                f"SCENARIO: {name}{is_dominant} (rank={rank}, score={score:.2f})\n"
                f"  Reasoning: {reasoning[:300]}\n"
                f"  Narrative: {narrative}\n"
            )

        user_prompt_parts = [
            f"PROBLEM: {problem}\n",
            f"TRIBUNAL SYNTHESIS: {tribunal_synthesis[:600]}\n",
            "SURVIVING SCENARIOS:\n" + "\n".join(scenario_parts),
        ]
        if world_context:
            user_prompt_parts.append(f"\nCURRENT WORLD CONTEXT:\n{world_context[:1500]}")

        user_prompt_parts.append(
            "\nGenerate concrete, sequenced, client-specific playbooks for each scenario. "
            "Then identify the robust moves that work across scenarios."
        )

        system_prompt = SCENARIO_ACTION_PROMPT.format(client_context=client_context)

        try:
            result = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt="\n".join(user_prompt_parts),
                temperature=0.3,
                max_tokens=12000,
            )
        except Exception as e:
            logger.warning("[Phase 2.95] LLM call failed: %s", e)
            result = {
                "client_role": "",
                "scenario_playbooks": [],
                "robust_moves": [],
                "error": str(e),
            }

        elapsed = time.perf_counter() - t0
        result["elapsed_seconds"] = round(elapsed, 2)

        playbooks = result.get("scenario_playbooks", [])
        robust = result.get("robust_moves", [])
        total_actions = sum(len(p.get("actions", [])) for p in playbooks)

        logger.info(
            "[Phase 2.95] complete (%.2fs): %d playbooks, %d total actions, %d robust moves",
            elapsed, len(playbooks), total_actions, len(robust),
        )
        for rm in robust:
            logger.info("[Phase 2.95] Robust move: %s (urgency=%s, in %d scenarios)",
                        rm.get("action", "?")[:80],
                        rm.get("urgency", "?"),
                        len(rm.get("appears_in_scenarios", [])))

        return result
