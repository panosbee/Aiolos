"""
XDART-Φ × XHEART — Meta-Orchestrator (Adaptive Intelligence)

Instead of running a fixed linear pipeline, the Meta-Orchestrator gives
Αίολος the ability to THINK ABOUT HOW TO THINK:

  Level 1: Adaptive Planner + Reflection Gates
    → Plans which phases to run, how deep, in what order
    → After each phase, a gate evaluates: continue / deepen / loop_back / skip

  Level 2: Custom Phase Injection
    → Can create entirely new analytical phases on the fly
    → Game theory, stakeholder mapping, causal loop — invented as needed

  Level 3: Branching + Convergence
    → Fork analysis into parallel reasoning paths
    → Each branch runs a different analytical lens
    → Results merge via meta-tribunal before XHEART

Architecture:
  The existing phases are UNTOUCHED. The orchestrator wraps them.
  It decides WHAT runs, WHEN, and HOW DEEP — not HOW each phase works.

© Panos Skouras — Salimov MON IKE, 2026
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from xdart.llm import LLMClient

logger = logging.getLogger("xdart.meta_orchestrator")


# ── Phase Registry (maps phase IDs to their names + descriptions) ──
PHASE_CATALOG = {
    "ontology": {
        "name": "Ontological Grounding",
        "id": "phase0",
        "description": "Reframes the problem philosophically — reveals hidden assumptions.",
        "typical_tokens": 2000,
        "required": False,
        "category": "foundation",
    },
    "cross_domain": {
        "name": "Cross-Domain Reasoning",
        "id": "phase1",
        "description": "Finds structural analogies from other domains (law, biology, physics, etc).",
        "typical_tokens": 3000,
        "required": False,
        "category": "foundation",
    },
    "views": {
        "name": "Multiple Views (32 angles)",
        "id": "phase2",
        "description": "Examines problem from 32 independent viewing angles to find dominant patterns.",
        "typical_tokens": 4000,
        "required": False,
        "category": "analysis",
    },
    "scenario_genesis": {
        "name": "Scenario Genesis",
        "id": "phase2_5",
        "description": "Generates 5-10 structured future scenarios from views and cross-domain insights.",
        "typical_tokens": 4000,
        "required": False,
        "category": "scenarios",
    },
    "scenario_simulation": {
        "name": "Scenario Simulation",
        "id": "phase2_7",
        "description": "Forward-projects each scenario — stress tests, breakpoints, cascades.",
        "typical_tokens": 3000,
        "required": False,
        "category": "scenarios",
        "depends_on": ["scenario_genesis"],
    },
    "scenario_tribunal": {
        "name": "Scenario Tribunal",
        "id": "phase2_9",
        "description": "Democratic ranking of scenarios — feasibility, evidence, consistency.",
        "typical_tokens": 3000,
        "required": False,
        "category": "scenarios",
        "depends_on": ["scenario_genesis", "scenario_simulation"],
    },
    "quantum_engine": {
        "name": "Quantum Scenario Engine",
        "id": "phase2_91",
        "description": "Observer-effect adjusted probabilities, interference patterns, hidden signals.",
        "typical_tokens": 3000,
        "required": False,
        "category": "scenarios",
        "depends_on": ["scenario_tribunal"],
    },
    "bayesian_fuzzy": {
        "name": "Bayesian-Fuzzy Engine",
        "id": "phase2_92",
        "description": "Fuzzy Logic → Bayesian Network posterior risk quantification (nuclear, financial, general).",
        "typical_tokens": 3000,
        "required": False,
        "category": "scenarios",
        "depends_on": ["scenario_tribunal"],
    },
    "action_mapping": {
        "name": "Scenario-Action Mapping",
        "id": "phase2_95",
        "description": "Client-specific playbooks: robust moves, contingency plans per scenario.",
        "typical_tokens": 3000,
        "required": False,
        "category": "strategy",
        "depends_on": ["scenario_tribunal"],
    },
    "xheart": {
        "name": "XHEART Distillation",
        "id": "phase3",
        "description": "Two-stage compression: all analysis → distillate core (200-400 words).",
        "typical_tokens": 4000,
        "required": True,  # Always runs
        "category": "synthesis",
    },
    "historical_resonance": {
        "name": "Historical Resonance",
        "id": "phase3_5",
        "description": "Finds historical parallels — structural matches, transfer insights.",
        "typical_tokens": 3000,
        "required": False,
        "category": "post_synthesis",
        "depends_on": ["xheart"],
    },
    "strategic_foresight": {
        "name": "Strategic Foresight",
        "id": "phase3_7",
        "description": "Decision points, watch signals, risk/opportunity matrix, role-specific advice.",
        "typical_tokens": 3000,
        "required": False,
        "category": "post_synthesis",
        "depends_on": ["xheart"],
    },
    "prophetic_bets": {
        "name": "Prophetic Bets",
        "id": "phase3_9",
        "description": "3-5 falsifiable dated predictions with confidence levels.",
        "typical_tokens": 2000,
        "required": True,  # Always runs — core to the prophet identity
        "category": "post_synthesis",
        "depends_on": ["xheart"],
    },
}

# Default linear order (current behavior)
DEFAULT_PHASE_ORDER = [
    "ontology", "cross_domain", "views",
    "scenario_genesis", "scenario_simulation", "scenario_tribunal",
    "quantum_engine", "bayesian_fuzzy", "action_mapping",
    "xheart",
    "historical_resonance", "strategic_foresight", "prophetic_bets",
]


class AnalysisPlan:
    """A customized analysis plan produced by the MetaPlanner."""

    def __init__(
        self,
        phases: list[dict],
        reasoning: str,
        estimated_llm_calls: int,
        custom_phases: list[dict] | None = None,
        branches: list[dict] | None = None,
        activate_strategies: list[str] | None = None,
    ):
        self.phases = phases  # [{id, depth, priority}, ...]
        self.reasoning = reasoning
        self.estimated_llm_calls = estimated_llm_calls
        self.custom_phases = custom_phases or []
        self.branches = branches or []
        self.activate_strategies = activate_strategies or []
        self.created_at = time.time()

    @property
    def phase_ids(self) -> list[str]:
        return [p["id"] for p in self.phases]

    @property
    def is_branching(self) -> bool:
        return len(self.branches) > 0

    def get_depth(self, phase_id: str) -> str:
        """Get configured depth for a phase (shallow/normal/deep)."""
        for p in self.phases:
            if p["id"] == phase_id:
                return p.get("depth", "normal")
        return "normal"

    def to_dict(self) -> dict:
        return {
            "phases": self.phases,
            "reasoning": self.reasoning,
            "estimated_llm_calls": self.estimated_llm_calls,
            "custom_phases": self.custom_phases,
            "branches": self.branches,
            "activate_strategies": self.activate_strategies,
        }


class GateVerdict:
    """Result of a reflection gate evaluation after a phase."""

    def __init__(
        self,
        action: str,  # continue, deepen, loop_back, skip_ahead, inject_custom
        confidence: float,
        note: str,
        custom_phase: dict | None = None,
        loop_target: str | None = None,
    ):
        self.action = action
        self.confidence = confidence
        self.note = note
        self.custom_phase = custom_phase  # For inject_custom
        self.loop_target = loop_target    # For loop_back

    def to_dict(self) -> dict:
        d = {"action": self.action, "confidence": self.confidence, "note": self.note}
        if self.custom_phase:
            d["custom_phase"] = self.custom_phase
        if self.loop_target:
            d["loop_target"] = self.loop_target
        return d


class MetaOrchestrator:
    """Adaptive pipeline orchestrator — thinks about how to think.

    Wraps the existing phases without modifying them.
    Decides: what runs, when, how deep, and whether to create new phases.
    """

    def __init__(self, llm: LLMClient, enabled: bool = True):
        self.llm = llm
        self.enabled = enabled
        self._max_custom_phases = 2       # Safety cap
        self._max_loop_backs = 2          # Prevent infinite loops
        self._max_branches = 3            # Max parallel branches
        self._gate_budget_tokens = 400    # Small gate = cheap
        self._planner_budget_tokens = 1500

    # ══════════════════════════════════════════════════════════════
    #  LEVEL 1: META-PLANNER (decides what phases to run)
    # ══════════════════════════════════════════════════════════════

    def plan(
        self,
        problem: str,
        memory_context: str,
        world_context: str,
        past_runs_summary: str,
        has_client_profile: bool,
        quantum_enabled: bool,
        bayesian_fuzzy_enabled: bool = True,
        cognitive_strategies_context: str = "",
    ) -> AnalysisPlan:
        """Create a custom analysis plan for this specific problem.

        Examines the problem, available context, and decides:
        - Which phases to run (and which to skip)
        - At what depth (shallow/normal/deep)
        - Whether to create custom phases
        - Whether to branch into parallel analysis paths
        - Which cognitive strategies to activate
        """
        if not self.enabled:
            return self._default_plan(has_client_profile, quantum_enabled, bayesian_fuzzy_enabled)

        catalog_desc = "\n".join(
            f"  {pid}: {info['name']} — {info['description']} "
            f"(~{info['typical_tokens']} tokens, {'REQUIRED' if info['required'] else 'optional'})"
            for pid, info in PHASE_CATALOG.items()
        )

        system = f"""You are the META-PLANNER of XDART-Φ, a deep prophetic analysis system.
Your job: given a problem, decide the OPTIMAL analysis path. Not every problem needs every phase.

AVAILABLE PHASES:
{catalog_desc}

CAPABILITIES YOU CAN USE:
A) SKIP phases that add no value for THIS specific problem.
B) SET DEPTH per phase: "shallow" (faster, less tokens), "normal", or "deep" (thorough).
C) CUSTOM PHASES: You can INVENT up to 2 analytical tools that don't exist in the catalog.
   A custom phase = a detailed prompt the LLM will execute. Use when the problem has a dimension
   that no existing phase covers well. Examples:
   - A game-theoretic multi-player incentive analysis
   - A supply-chain cascade disruption model
   - A currency contagion propagation estimator
   - An arms-race escalation dynamics tracker
   - A technology chokepoint dependency mapper
D) BRANCHES: You can split into 2-3 PARALLEL analysis paths with different lenses,
   then merge results before XHEART. Use when the problem genuinely spans distinct domains
   that would benefit from independent deep-dives vs. a single linear pass.
   Example: a military-lens branch + an economic-lens branch + a diplomatic-lens branch.

   CRITICAL: The main pipeline ALREADY runs: ontology, cross_domain, views, scenario_genesis,
   scenario_simulation, scenario_tribunal, quantum_engine. Branches INHERIT those results.
   Do NOT include those phases in branch definitions — they will be automatically filtered out.
   Branches should ONLY contain phases that ADD NEW analysis: custom phases (custom_*) and
   supplementary phases like historical_resonance. If a branch only has standard pipeline
   phases, it will be skipped entirely.

RULES:
1. 'xheart' and 'prophetic_bets' are ALWAYS included — they are core identity.
2. Dependencies must be respected: scenario_simulation needs scenario_genesis, etc.
3. Consider what's ALREADY KNOWN from memory/world context — don't re-analyze.

HOW TO DECIDE:
- Simple, focused problems (single domain) → standard linear pipeline, maybe skip some phases.
- Multi-domain problems (2+ domains) → USE CUSTOM PHASES to add domain-specific analysis.
  Custom phases are lightweight (1 LLM call each) and add entirely new analytical dimensions.
- If the problem genuinely needs SEPARATE analytical tracks → USE BRANCHES, but only put
  custom phases and supplementary phases in them (NOT standard pipeline phases).
- IMPORTANT: The orchestrator exists to make the analysis ADAPTIVE. Use custom phases to
  add unique analytical capabilities tailored to this specific problem.

BRANCHING DECISION RULE:
If the problem involves 2+ distinct analytical dimensions that need INDEPENDENT exploration
(e.g. a game-theory track + a supply-chain track), create branches with CUSTOM PHASES only.
Do NOT put ontology, cross_domain, views, scenario_genesis, scenario_simulation, scenario_tribunal,
or quantum_engine in branches — those are already run by the main pipeline.

CUSTOM PHASE DECISION RULE:
If the problem involves any of these dynamics that no existing phase covers well:
game theory, incentive structures, supply chains, currency/trade flows, technology dependencies,
demographic pressures, information warfare, alliance dynamics → create a custom phase for it.

OUTPUT FORMAT (strict JSON):
{{
  "reasoning": "2-3 sentences explaining your analytical strategy for this problem",
  "phases": [
    {{"id": "ontology", "depth": "normal", "priority": 1}},
    {{"id": "cross_domain", "depth": "deep", "priority": 2}},
    ...
  ],
  "custom_phases": [
    {{
      "id": "custom_game_theory",
      "name": "Game-Theoretic Analysis",
      "prompt": "Analyze X as a game between players A, B, C. Model incentives, Nash equilibria, and likely outcomes. Identify where rational self-interest diverges from collective optimality...",
      "insert_after": "scenario_tribunal",
      "depth": "normal"
    }}
  ],
  "branches": [
    {{
      "name": "game_theory_track",
      "reasoning": "This problem has complex strategic interactions between state actors",
      "phases": ["custom_game_theory", "historical_resonance"]
    }},
    {{
      "name": "supply_chain_track",
      "reasoning": "Supply chain and trade dynamics need independent deep-dive",
      "phases": ["custom_supply_chain", "historical_resonance"]
    }}
  ],
  "estimated_llm_calls": 12
}}

If no custom phases are needed, return empty list []. If no branching needed, return empty list [].
REMINDER: Branches should ONLY contain custom phases and supplementary phases (like historical_resonance).
Standard pipeline phases (ontology, cross_domain, views, scenario_genesis, scenario_simulation,
scenario_tribunal, quantum_engine) are ALREADY run in the main pipeline and will be filtered from branches."""

        # Cognitive strategies section
        strategies_section = ""
        if cognitive_strategies_context and cognitive_strategies_context != "(no cognitive strategies available yet)":
            strategies_section = f"""
E) COGNITIVE STRATEGIES: The system has learned persistent thinking patterns
   from past self-evolution. You can ACTIVATE strategies for this problem.
   To activate a strategy, include its ID in the "activate_strategies" field.
   Strategies run at their designated injection points in the pipeline.

{cognitive_strategies_context}

   Only activate strategies whose trigger conditions match this problem.
   You can activate 0-3 strategies per run.
"""
            system += strategies_section

        user = f"""PROBLEM: {problem}

CONTEXT AVAILABLE:
- Memory: {len(memory_context)} chars of past analyses
- World data: {len(world_context)} chars of live events/indicators
- Past runs summary: {past_runs_summary[:500] if past_runs_summary else 'First run — no history'}
- Client profile: {'Yes' if has_client_profile else 'No'}
- Quantum engine: {'Available' if quantum_enabled else 'Not available'}
- Bayesian-Fuzzy engine: {'Available' if bayesian_fuzzy_enabled else 'Not available'}
- Cognitive strategies: {cognitive_strategies_context[:200] if cognitive_strategies_context else 'None available'}

Design the optimal analysis path for this problem.
Include "activate_strategies": ["cs_xxx", ...] if any strategies should be activated (or empty list)."""

        try:
            plan_data = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.4,
                max_tokens=self._planner_budget_tokens,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[MetaOrchestrator] Planner failed: %s — using default plan", e)
            return self._default_plan(has_client_profile, quantum_enabled, bayesian_fuzzy_enabled)

        # Validate and build plan
        return self._parse_plan(plan_data, has_client_profile, quantum_enabled, bayesian_fuzzy_enabled)

    def _parse_plan(
        self, data: dict, has_client_profile: bool, quantum_enabled: bool,
        bayesian_fuzzy_enabled: bool = True,
    ) -> AnalysisPlan:
        """Parse and validate the LLM-generated plan."""
        phases = data.get("phases", [])
        custom_phases = data.get("custom_phases", [])[:self._max_custom_phases]
        branches = data.get("branches", [])[:self._max_branches]
        reasoning = data.get("reasoning", "No reasoning provided")

        # Ensure required phases are present
        phase_ids = {p["id"] for p in phases}
        for pid, info in PHASE_CATALOG.items():
            if info["required"] and pid not in phase_ids:
                phases.append({"id": pid, "depth": "normal", "priority": 99})

        # Remove action_mapping if no client profile
        if not has_client_profile:
            phases = [p for p in phases if p["id"] != "action_mapping"]

        # Remove quantum if disabled
        if not quantum_enabled:
            phases = [p for p in phases if p["id"] != "quantum_engine"]

        # Remove bayesian_fuzzy if disabled
        if not bayesian_fuzzy_enabled:
            phases = [p for p in phases if p["id"] != "bayesian_fuzzy"]

        # Enforce dependency order
        phases = self._enforce_dependencies(phases)

        # Validate custom phases
        validated_custom = []
        for cp in custom_phases:
            if all(k in cp for k in ("id", "name", "prompt")):
                cp.setdefault("insert_after", "scenario_tribunal")
                cp.setdefault("depth", "normal")
                validated_custom.append(cp)

        # Validate branches
        validated_branches = []
        for br in branches:
            if "name" in br and "phases" in br and len(br["phases"]) >= 2:
                validated_branches.append(br)

        estimated = data.get("estimated_llm_calls", len(phases) + len(custom_phases))

        # Extract activated cognitive strategies (max 3)
        activate_strategies = data.get("activate_strategies", [])
        if not isinstance(activate_strategies, list):
            activate_strategies = []
        activate_strategies = [s for s in activate_strategies if isinstance(s, str)][:3]

        plan = AnalysisPlan(
            phases=phases,
            reasoning=reasoning,
            estimated_llm_calls=estimated,
            custom_phases=validated_custom,
            branches=validated_branches,
            activate_strategies=activate_strategies,
        )

        logger.info(
            "[MetaOrchestrator] Plan created: %d phases, %d custom, %d branches, %d strategies — %s",
            len(phases), len(validated_custom), len(validated_branches),
            len(activate_strategies), reasoning[:120],
        )
        if activate_strategies:
            logger.info("[MetaOrchestrator] Activated strategies: %s", activate_strategies)

        return plan

    def _enforce_dependencies(self, phases: list[dict]) -> list[dict]:
        """Ensure phases are ordered respecting dependencies."""
        phase_ids = {p["id"] for p in phases}

        # Add missing dependencies
        for p in list(phases):
            deps = PHASE_CATALOG.get(p["id"], {}).get("depends_on", [])
            for dep in deps:
                if dep not in phase_ids:
                    phases.append({"id": dep, "depth": "normal", "priority": 50})
                    phase_ids.add(dep)

        # Sort by default order
        order_map = {pid: i for i, pid in enumerate(DEFAULT_PHASE_ORDER)}
        phases.sort(key=lambda p: order_map.get(p["id"], 50))
        return phases

    def _default_plan(self, has_client_profile: bool, quantum_enabled: bool,
                       bayesian_fuzzy_enabled: bool = True) -> AnalysisPlan:
        """Fallback: run the full linear pipeline (current behavior)."""
        phases = []
        for pid in DEFAULT_PHASE_ORDER:
            if pid == "action_mapping" and not has_client_profile:
                continue
            if pid == "quantum_engine" and not quantum_enabled:
                continue
            if pid == "bayesian_fuzzy" and not bayesian_fuzzy_enabled:
                continue
            phases.append({"id": pid, "depth": "normal", "priority": len(phases)})

        return AnalysisPlan(
            phases=phases,
            reasoning="Default linear pipeline — meta-orchestrator disabled or fallback.",
            estimated_llm_calls=len(phases),
        )

    # ══════════════════════════════════════════════════════════════
    #  LEVEL 1: REFLECTION GATE (evaluates after each phase)
    # ══════════════════════════════════════════════════════════════

    def evaluate_gate(
        self,
        phase_id: str,
        phase_output_summary: str,
        problem: str,
        plan: AnalysisPlan,
        phases_completed: list[str],
        loop_count: int = 0,
        custom_count: int = 0,
    ) -> GateVerdict:
        """Evaluate the output of a phase and decide what to do next.

        Returns: GateVerdict with action:
          - continue: proceed to next planned phase
          - deepen: re-run this phase with more depth
          - loop_back: return to an earlier phase with new insight
          - skip_ahead: jump directly to XHEART (we have enough)
          - inject_custom: create a new analytical phase here
        """
        if not self.enabled:
            return GateVerdict(action="continue", confidence=1.0, note="Gates disabled")

        remaining = [p for p in plan.phase_ids if p not in phases_completed]

        system = f"""You are a REFLECTION GATE in XDART-Φ's meta-orchestrator.
You just saw the output of phase '{phase_id}'. Decide what happens next.

ALREADY COMPLETED: {', '.join(phases_completed)}
REMAINING PLANNED: {', '.join(remaining)}
LOOP-BACKS SO FAR: {loop_count}/{self._max_loop_backs}
CUSTOM PHASES CREATED: {custom_count}/{self._max_custom_phases}

OPTIONS (evaluate EACH one honestly before choosing):
1. "continue" — output is solid AND the next planned phase will add genuine new value
2. "deepen" — output missed important dimensions or is too surface-level for this problem's complexity
3. "loop_back" — output reveals that an earlier phase's framing was incomplete or wrong (max {self._max_loop_backs} times)
4. "skip_ahead" — we already have enough insight, remaining phases would be redundant
5. "inject_custom" — there is an analytical dimension this problem NEEDS that no planned phase covers (max {self._max_custom_phases} custom phases)

DECISION CRITERIA:
- Actually READ the phase output. Does it feel thorough? Are there gaps?
- Look at what's REMAINING. Will those phases genuinely add new insight, or just re-process?
- If the output contradicts or significantly reframes what came before → loop_back.
- If you see an analytical gap (e.g., game theory needed, supply chain mapping needed) → inject_custom.
- If output is shallow or misses a key dimension of the problem → deepen.
- "continue" is appropriate when the output is good AND the next phase will genuinely add value.
- Do NOT default to "continue" reflexively — think about whether the pipeline is actually learning.

OUTPUT (strict JSON):
{{
  "action": "continue",
  "confidence": 0.85,
  "note": "1 sentence explaining decision"
}}

For loop_back, add: "loop_target": "ontology"
For inject_custom, add: "custom_phase": {{
  "id": "custom_xxx",
  "name": "...",
  "prompt": "...",
  "insert_after": "{phase_id}"
}}"""

        user = f"""PROBLEM: {problem[:300]}

PHASE '{phase_id}' OUTPUT SUMMARY:
{phase_output_summary[:800]}

What should happen next?"""

        try:
            data = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.35,  # Balanced — allow genuine adaptive decisions
                max_tokens=self._gate_budget_tokens,
                thinking=False,
            )
        except Exception as e:
            logger.debug("[MetaOrchestrator] Gate eval failed: %s — continuing", e)
            return GateVerdict(action="continue", confidence=0.5, note=f"Gate failed: {e}")

        action = data.get("action", "continue")

        # Safety: enforce limits
        if action == "loop_back" and loop_count >= self._max_loop_backs:
            action = "continue"
            data["note"] = f"Loop-back suppressed (already looped {loop_count} times)"
        if action == "inject_custom" and custom_count >= self._max_custom_phases:
            action = "continue"
            data["note"] = f"Custom phase suppressed (already created {custom_count})"
        if action == "deepen" and phase_id in phases_completed:
            # Already deepened once — don't loop
            phases_completed_count = phases_completed.count(phase_id)
            if phases_completed_count >= 2:
                action = "continue"
                data["note"] = f"Deepen suppressed (already ran {phase_id} twice)"

        verdict = GateVerdict(
            action=action,
            confidence=data.get("confidence", 0.5),
            note=data.get("note", ""),
            custom_phase=data.get("custom_phase"),
            loop_target=data.get("loop_target"),
        )

        logger.info(
            "[MetaOrchestrator] Gate[%s] → %s (confidence=%.2f): %s",
            phase_id, action, verdict.confidence, verdict.note[:120],
        )

        return verdict

    # ══════════════════════════════════════════════════════════════
    #  LEVEL 2: CUSTOM PHASE EXECUTION
    # ══════════════════════════════════════════════════════════════

    def execute_custom_phase(
        self,
        custom_phase: dict,
        problem: str,
        accumulated_context: str,
        world_context: str,
    ) -> dict:
        """Execute a custom phase created by the planner or a gate.

        The custom phase is just a prompt — the LLM generates the analysis.
        Returns structured output that feeds into subsequent phases.
        """
        phase_id = custom_phase.get("id", "custom_unknown")
        phase_name = custom_phase.get("name", "Custom Analysis")
        phase_prompt = custom_phase.get("prompt", "")
        depth = custom_phase.get("depth", "normal")

        depth_instruction = {
            "shallow": "Be concise — focus on the 2-3 most important points only.",
            "normal": "Provide a thorough analysis covering key dimensions.",
            "deep": "Go extremely deep — explore every angle, sub-factor, and implication.",
        }.get(depth, "")

        system = f"""You are executing a CUSTOM ANALYTICAL PHASE for XDART-Φ.
Phase: {phase_name}
Depth: {depth}

{depth_instruction}

Your task:
{phase_prompt}

OUTPUT FORMAT (strict JSON):
{{
  "analysis": "Your detailed analysis text",
  "key_insights": ["insight 1", "insight 2", ...],
  "signals": ["signal or indicator to watch", ...],
  "confidence": 0.0-1.0,
  "methodology_note": "Brief note on the analytical approach you used"
}}"""

        user = f"""PROBLEM: {problem}

ANALYSIS SO FAR:
{accumulated_context[:4000]}

WORLD CONTEXT:
{world_context[:2000]}

Execute this analysis now."""

        logger.info("[MetaOrchestrator] Executing custom phase: %s (%s)", phase_name, depth)
        t0 = time.perf_counter()

        try:
            max_tokens = {"shallow": 1500, "normal": 3000, "deep": 5000}.get(depth, 3000)
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.5,
                max_tokens=max_tokens,
            )
            result["phase_id"] = phase_id
            result["phase_name"] = phase_name
            result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)

            logger.info(
                "[MetaOrchestrator] Custom phase '%s' complete (%.2fs): %d insights, confidence=%.2f",
                phase_name, result["elapsed_seconds"],
                len(result.get("key_insights", [])),
                result.get("confidence", 0),
            )
            return result

        except Exception as e:
            logger.warning("[MetaOrchestrator] Custom phase '%s' failed: %s", phase_name, e)
            return {
                "phase_id": phase_id,
                "phase_name": phase_name,
                "analysis": f"Custom phase failed: {e}",
                "key_insights": [],
                "signals": [],
                "confidence": 0.0,
                "elapsed_seconds": round(time.perf_counter() - t0, 2),
                "error": str(e),
            }

    # ══════════════════════════════════════════════════════════════
    #  LEVEL 3: BRANCHING ENGINE
    # ══════════════════════════════════════════════════════════════

    def execute_branch(
        self,
        branch: dict,
        problem: str,
        run_phase_fn: Callable,
        shared_context: dict,
    ) -> dict:
        """Execute a single analysis branch.

        Args:
            branch: Branch definition {name, reasoning, phases}
            problem: The original problem
            run_phase_fn: Callback to execute a phase (phase_id, depth) -> result
            shared_context: Shared data (ontology, world_context, etc.)

        Returns:
            Branch results dict with all phase outputs.
        """
        branch_name = branch.get("name", "unnamed")
        branch_phases = branch.get("phases", [])

        logger.info(
            "[MetaOrchestrator] Starting branch '%s': %s",
            branch_name, ", ".join(branch_phases),
        )

        t0 = time.perf_counter()
        branch_results = {
            "name": branch_name,
            "reasoning": branch.get("reasoning", ""),
            "phase_results": {},
        }

        for phase_id in branch_phases:
            try:
                result = run_phase_fn(phase_id, "normal", shared_context)
                branch_results["phase_results"][phase_id] = result
            except Exception as e:
                logger.warning(
                    "[MetaOrchestrator] Branch '%s', phase '%s' failed: %s",
                    branch_name, phase_id, e,
                )
                branch_results["phase_results"][phase_id] = {"error": str(e)}

        branch_results["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
        logger.info(
            "[MetaOrchestrator] Branch '%s' complete (%.2fs): %d phases",
            branch_name, branch_results["elapsed_seconds"], len(branch_results["phase_results"]),
        )
        return branch_results

    def merge_branches(
        self,
        problem: str,
        branch_results: list[dict],
        world_context: str,
    ) -> dict:
        """Merge results from multiple branches into a unified synthesis.

        This is a meta-tribunal: it compares the branches and synthesizes
        the strongest insights from each.
        """
        if len(branch_results) <= 1:
            return branch_results[0] if branch_results else {}

        # Format branch summaries for LLM
        branch_summaries = []
        for br in branch_results:
            name = br.get("name", "?")
            reasoning = br.get("reasoning", "")
            phase_keys = list(br.get("phase_results", {}).keys())
            # Extract key content from each branch's phases
            content_parts = []
            for pid, presult in br.get("phase_results", {}).items():
                if isinstance(presult, dict):
                    # Try to get readable summary
                    for key in ("analysis", "distillate_core", "tribunal_synthesis",
                                "dominant_pattern", "reframed_problem"):
                        if key in presult:
                            content_parts.append(f"  [{pid}] {str(presult[key])[:300]}")
                            break
                elif isinstance(presult, str):
                    content_parts.append(f"  [{pid}] {presult[:300]}")

            branch_summaries.append(
                f"BRANCH '{name}' ({reasoning}):\n"
                f"  Phases: {', '.join(phase_keys)}\n"
                + "\n".join(content_parts)
            )

        system = """You are the META-TRIBUNAL of XDART-Φ.
Multiple analysis branches examined the same problem from different angles.
Your job: synthesize the STRONGEST insights from ALL branches into a unified view.

RULES:
- Don't average — pick the BEST insight from each branch
- Note where branches AGREE (high confidence) vs DISAGREE (needs more investigation)
- Identify insights that only ONE branch found (unique contributions)
- Flag contradictions explicitly

OUTPUT (strict JSON):
{
  "unified_synthesis": "The core insight combining all branches",
  "branch_agreements": ["point where all branches agree", ...],
  "branch_conflicts": ["point where branches disagree + which branch is likely right", ...],
  "unique_contributions": [{"branch": "name", "insight": "..."}, ...],
  "dominant_branch": "which branch produced the most valuable analysis",
  "confidence": 0.0-1.0,
  "merged_scenario_context": "A merged narrative for XHEART to distill"
}"""

        user = f"""PROBLEM: {problem}

{chr(10).join(branch_summaries)}

WORLD CONTEXT (shared):
{world_context[:1500]}

Merge these analysis branches into a unified synthesis."""

        logger.info("[MetaOrchestrator] Merging %d branches", len(branch_results))
        t0 = time.perf_counter()

        try:
            merge_result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.3,
                max_tokens=2500,
            )
            merge_result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
            merge_result["branches_merged"] = len(branch_results)

            logger.info(
                "[MetaOrchestrator] Branch merge complete (%.2fs): dominant=%s, confidence=%.2f",
                merge_result["elapsed_seconds"],
                merge_result.get("dominant_branch", "?"),
                merge_result.get("confidence", 0),
            )
            return merge_result

        except Exception as e:
            logger.warning("[MetaOrchestrator] Branch merge failed: %s — using first branch", e)
            return {
                "unified_synthesis": branch_results[0].get("reasoning", ""),
                "branch_agreements": [],
                "branch_conflicts": [],
                "unique_contributions": [],
                "dominant_branch": branch_results[0].get("name", "first"),
                "confidence": 0.5,
                "merged_scenario_context": "",
                "error": str(e),
            }

    # ══════════════════════════════════════════════════════════════
    #  QUALITY GATE (post-custom-phase evaluation)
    # ══════════════════════════════════════════════════════════════

    def evaluate_custom_phase_quality(
        self,
        custom_result: dict,
        problem: str,
        accumulated_context: str,
    ) -> bool:
        """Check if a custom phase produced useful output worth keeping.

        Returns True if the output should be included, False to discard.
        """
        if custom_result.get("error"):
            return False

        analysis = custom_result.get("analysis", "")
        insights = custom_result.get("key_insights", [])

        # Quick heuristic checks
        if len(analysis) < 100:
            logger.info("[MetaOrchestrator] Custom phase discarded: too short (%d chars)", len(analysis))
            return False
        if not insights:
            logger.info("[MetaOrchestrator] Custom phase discarded: no insights")
            return False

        # LLM quality check (cheap — 200 tokens)
        system = """You evaluate whether a custom analytical phase produced NOVEL, USEFUL output.
Answer JSON: {"keep": true/false, "reason": "1 sentence"}
Keep if: new insights not already in the accumulated context.
Discard if: redundant, shallow, or hallucinatory."""

        user = f"""PROBLEM: {problem[:200]}

CUSTOM PHASE OUTPUT:
{analysis[:500]}

ALREADY KNOWN:
{accumulated_context[:500]}

Is this worth keeping?"""

        try:
            data = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.1,
                max_tokens=200,
                thinking=False,
            )
            keep = data.get("keep", True)
            if not keep:
                logger.info(
                    "[MetaOrchestrator] Custom phase discarded by quality gate: %s",
                    data.get("reason", ""),
                )
            return keep
        except Exception:
            return True  # On error, keep it

    # ══════════════════════════════════════════════════════════════
    #  HELPER: Format phase output for gate evaluation
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def summarize_phase_output(phase_id: str, output: Any) -> str:
        """Create a concise summary of a phase's output for gate evaluation."""
        if output is None:
            return f"Phase {phase_id}: no output"

        if isinstance(output, dict):
            # Custom phase or raw dict
            parts = []
            for key in ("analysis", "reframed_problem", "dominant_pattern",
                         "tribunal_synthesis", "distillate_core",
                         "strategic_assessment", "unified_synthesis"):
                if key in output:
                    parts.append(f"{key}: {str(output[key])[:200]}")
            if parts:
                return f"Phase {phase_id}:\n" + "\n".join(parts)
            return f"Phase {phase_id}: {str(output)[:400]}"

        if isinstance(output, str):
            return f"Phase {phase_id}: {output[:400]}"

        # Pydantic model or object with attributes
        parts = [f"Phase {phase_id}:"]
        for attr in ("reframed_problem", "dominant_pattern", "layer",
                      "tribunal_synthesis", "distillate_core",
                      "scenarios", "verdicts"):
            val = getattr(output, attr, None)
            if val is not None:
                if isinstance(val, list):
                    parts.append(f"  {attr}: {len(val)} items")
                else:
                    parts.append(f"  {attr}: {str(val)[:200]}")
        return "\n".join(parts)
