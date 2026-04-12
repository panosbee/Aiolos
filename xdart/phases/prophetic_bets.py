"""
XDART-Φ — Phase 3.9: Decision Triggers + Prophetic Bets

Converts pipeline output into TWO things:
  1. DECISION TRIGGERS — if/then rules that map observable signal combinations
     to specific scenario playbooks. The client watches for these combinations
     and knows EXACTLY what to do when they fire.
  2. PROPHETIC BETS — specific, date-bound, yes/no falsifiable predictions
     (retained for the Brier scoring loop).

Each decision trigger:
  - Names 2-4 observable signals that co-occur
  - Maps to a SPECIFIC scenario from the tribunal
  - Points to the matching playbook from Phase 2.95
  - Specifies how fast the client must act

Each bet:
  - SPECIFIC: Names actors, locations, mechanisms
  - DATED: At least 2 bets MUST have a deadline within 7-14 days (near-term).
           Remaining bets should have deadlines within 30-180 days (medium-term).
  - BINARY: Clearly yes/no when the deadline arrives
"""

import logging
import time
from datetime import datetime, timezone

from xdart.llm import LLMClient

logger = logging.getLogger(__name__)

DECISION_TRIGGERS_PROMPT = """You are a DECISION INTELLIGENCE system. You convert analysis into
operational decision triggers — if/then rules that tell a client EXACTLY when to act.

You have received:
- A distillate (core insight from deep analysis)
- Scenario intelligence (surviving scenarios from tribunal)
- Scenario-action playbooks (per-scenario action plans for this client)
- Strategic foresight (risk matrix, decision points)
- Historical resonance (what history says)
- Current world context (live data)

{client_context}

YOUR JOB: Produce TWO things.

PART 1 — DECISION TRIGGERS (3-6 triggers)
Each trigger is a COMBINATION of observable signals that, when they co-occur,
point to a specific scenario unfolding. When a trigger fires, the client
activates the corresponding playbook.

Rules:
- Each trigger has 2-4 signal CONDITIONS (not just one — single signals mean nothing)
- Each condition must be OBSERVABLE and CHECKABLE (NAVTEX broadcast, social media volume,
  shipping insurance quotes, diplomatic statements, military movement)
- Conditions combine via threshold: "all" means all must fire, "2_of_3" means majority
- Each trigger maps to ONE scenario and ONE playbook
- Include time_to_act: how fast the client must move once trigger fires
- Include false_positive_risk: what could make this look like a trigger but isn't

PART 2 — PROPHETIC BETS (4-6 bets, retained for accuracy scoring)
DEADLINE RULES (CRITICAL — follow exactly):
- At least 2 bets MUST have a deadline within 7-14 days from TODAY.
  These near-term bets test things that can be verified SOON (price moves,
  policy announcements, data releases, measurable shifts within 2 weeks).
- The remaining 2-4 bets should have deadlines within 30-180 days (medium-term).
- Every bet: specific, dated, binary, confidence-scored.
- Use TODAY'S DATE from the user prompt to calculate actual deadline dates.

Respond in JSON:
{{
  "decision_triggers": [
    {{
      "trigger_id": "TRIG-001",
      "conditions": [
        {{
          "signal": "Observable event/indicator",
          "check_method": "How to detect this",
          "confidence_weight": 0.8
        }}
      ],
      "threshold": "all" or "2_of_3",
      "activates_scenario": "Scenario Name",
      "activates_playbook": "Scenario Name",
      "time_to_act": "90 minutes / 24 hours / 1 week",
      "false_positive_risk": "What could make this a false alarm"
    }}
  ],
  "bets": [
    {{
      "bet_id": "BET-001",
      "statement": "By [DATE], [SPECIFIC OBSERVABLE EVENT] will have occurred.",
      "deadline": "YYYY-MM-DD",
      "confidence": 0.65,
      "mechanism": "Why — the causal chain",
      "evidence_base": "What supports this from the analysis",
      "novelty": "HIGH | MEDIUM | LOW",
      "tracking_signal": "Early indicator"
    }}
  ],
  "meta_prediction": "The ONE thing this analysis predicts that nobody else is saying",
  "prophet_confidence": 0.65,
  "prophet_reasoning": "Why this confidence level"
}}"""


class PropheticBetsPhase:
    """Phase 3.9 — Decision Triggers + Prophetic Bets."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        distillate: str,
        scenario_summary: str,
        tribunal_synthesis: str,
        strategic_foresight: dict | None = None,
        historical_resonance: dict | None = None,
        world_context: str = "",
        client_context: str = "",
        action_mapping: dict | None = None,
    ) -> dict:
        """Generate decision triggers + prophetic bets.

        Args:
            client_context: Text block from ClientProfile.to_context_block().
            action_mapping: Output of Phase 2.95 (playbooks + robust moves).

        Returns dict with 'decision_triggers', 'bets', 'meta_prediction'.
        """
        logger.info("[Phase 3.9] Decision Triggers + Bets — start")
        t0 = time.perf_counter()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        parts = [
            f"TODAY'S DATE: {today}\n",
            f"PROBLEM: {problem}\n",
            f"DISTILLATE (core insight): {distillate[:600]}\n",
            f"SCENARIO INTELLIGENCE:\n{scenario_summary[:800]}\n",
            f"TRIBUNAL SYNTHESIS: {tribunal_synthesis[:500]}\n",
        ]

        # Inject playbook information so triggers can reference them
        if action_mapping:
            playbooks = action_mapping.get("scenario_playbooks", [])
            if playbooks:
                pb_parts = ["AVAILABLE PLAYBOOKS (from Phase 2.95):"]
                for pb in playbooks:
                    actions_txt = "; ".join(
                        a.get("action", "?")[:60] for a in pb.get("actions", [])[:4]
                    )
                    pb_parts.append(
                        f"  [{pb.get('scenario_name', '?')}] "
                        f"(prob={pb.get('scenario_probability', '?')}): {actions_txt}"
                    )
                parts.append("\n".join(pb_parts) + "\n")

        if strategic_foresight:
            sf_assessment = strategic_foresight.get("strategic_assessment", "")[:400]
            sf_decisions = strategic_foresight.get("decision_points", [])
            parts.append(f"STRATEGIC ASSESSMENT: {sf_assessment}\n")
            if sf_decisions:
                decisions_txt = "; ".join(
                    (d.get("decision", d) if isinstance(d, dict) else str(d))
                    for d in sf_decisions[:5]
                )
                parts.append(f"DECISION POINTS: {decisions_txt[:500]}\n")

        if historical_resonance:
            hist_warning = historical_resonance.get("verdict", {}).get("historical_warning", "")
            if hist_warning:
                parts.append(f"HISTORICAL WARNING: {hist_warning[:400]}\n")

        if world_context:
            parts.append(f"CURRENT WORLD CONTEXT (sample):\n{world_context[:1500]}\n")

        parts.append(
            "\nGenerate decision triggers (signal combinations → scenario → playbook) "
            "AND 3-5 falsifiable bets. The triggers are the client's decision tree. "
            "The bets are the system's accountability."
        )

        user_prompt = "\n".join(parts)

        system_prompt = DECISION_TRIGGERS_PROMPT.format(
            client_context=client_context or "CLIENT CONTEXT: Not specified — write for a general strategic decision-maker.",
        )

        result = self.llm.call_json(
            system_prompt,
            user_prompt,
            max_tokens=10000,
        )

        elapsed = time.perf_counter() - t0

        triggers = result.get("decision_triggers", [])
        bets = result.get("bets", [])
        meta = result.get("meta_prediction", "")

        logger.info("[Phase 3.9] Generated %d triggers, %d bets in %.2fs",
                     len(triggers), len(bets), elapsed)
        for i, trig in enumerate(triggers):
            n_conds = len(trig.get("conditions", []))
            logger.info("[Phase 3.9] Trigger %d: %d conditions → %s (act in %s)",
                        i + 1, n_conds,
                        trig.get("activates_scenario", "?")[:60],
                        trig.get("time_to_act", "?"))
        for i, bet in enumerate(bets):
            logger.info(
                "[Phase 3.9] Bet %d: %s (confidence=%.2f, deadline=%s)",
                i + 1, bet.get("statement", "?")[:80],
                bet.get("confidence", 0), bet.get("deadline", "?"),
            )
        logger.info("[Phase 3.9] complete (%.2fs)", elapsed)

        result["elapsed_seconds"] = elapsed
        return result
