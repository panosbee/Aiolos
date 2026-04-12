"""
XDART-Φ × XHEART — Data Models

Pydantic models for every phase output, internal state, and memory entry.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
import uuid


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Enums
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AnalogyStrength(str, Enum):
    STRONG = "STRONG"
    WEAK = "WEAK"
    NONE = "NONE"


class StrategyMode(str, Enum):
    GROUNDED = "GROUNDED"
    ADJACENT = "ADJACENT"
    PIONEER = "PIONEER"
    TARGETED = "TARGETED"


class LayerClassification(str, Enum):
    LAYER_1 = "Layer-1"
    LAYER_2 = "Layer-2"
    LAYER_3 = "Layer-3"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Client Profile — Who is the decision-maker?
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ClientProfile(BaseModel):
    """Describes who the analysis is FOR — not just a role, but decision scope."""
    role: str = Field(description="e.g. 'Prime Minister advisor', 'shipping company owner'")
    decisions_i_make: list[str] = Field(
        default_factory=list,
        description="What concrete decisions does this person take?"
    )
    resources_i_control: list[str] = Field(
        default_factory=list,
        description="Ministries, fleets, budgets, organizations, networks"
    )
    time_horizon: str = Field(
        default="",
        description="e.g. '72 hours', '6 months', 'next electoral cycle'"
    )
    risk_tolerance: str = Field(
        default="",
        description="e.g. 'cannot afford escalation', 'high risk appetite'"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Political, legal, operational constraints"
    )
    stakeholders: list[str] = Field(
        default_factory=list,
        description="Who they answer to, who they coordinate with"
    )

    def to_context_block(self) -> str:
        """Serialize to a text block for LLM prompt injection."""
        parts = [f"CLIENT ROLE: {self.role}"]
        if self.decisions_i_make:
            parts.append("DECISIONS THIS CLIENT MAKES: " + "; ".join(self.decisions_i_make))
        if self.resources_i_control:
            parts.append("RESOURCES UNDER CONTROL: " + "; ".join(self.resources_i_control))
        if self.time_horizon:
            parts.append(f"TIME HORIZON: {self.time_horizon}")
        if self.risk_tolerance:
            parts.append(f"RISK TOLERANCE: {self.risk_tolerance}")
        if self.constraints:
            parts.append("CONSTRAINTS: " + "; ".join(self.constraints))
        if self.stakeholders:
            parts.append("STAKEHOLDERS: " + "; ".join(self.stakeholders))
        return "\n".join(parts)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2.95 — Scenario-Action Mapping
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PlaybookAction(BaseModel):
    """A single concrete action within a playbook."""
    action: str = Field(description="What to do — verb + object + target")
    sequence: int = Field(description="Execution order (1 = first)")
    deadline: str = Field(description="When this must happen — '90 minutes', '24 hours', '1 week'")
    mechanism: str = Field(default="", description="How exactly — phone call, directive, deployment")
    depends_on: str = Field(default="", description="Which prior action must complete first")


class ScenarioPlaybook(BaseModel):
    """A per-scenario action plan tied to the client profile."""
    scenario_id: str
    scenario_name: str
    scenario_probability: float = Field(ge=0.0, le=1.0)
    actions: list[PlaybookAction] = Field(description="3-5 concrete actions in execution order")
    rationale: str = Field(default="", description="Why these actions for this scenario")


class RobustMove(BaseModel):
    """An action that appears across multiple scenario playbooks — do it regardless."""
    action: str = Field(description="The robust action")
    appears_in_scenarios: list[str] = Field(description="Which scenario names share this action")
    urgency: str = Field(description="'immediate', 'within 24h', 'within 1 week'")
    reasoning: str = Field(default="", description="Why this is robust across scenarios")


class ScenarioActionMappingResult(BaseModel):
    """Output of Phase 2.95 — connects scenarios to concrete client actions."""
    client_role: str = Field(description="Who this is addressed to")
    robust_moves: list[RobustMove] = Field(
        description="Actions that work across all/most scenarios — do these first"
    )
    scenario_playbooks: list[ScenarioPlaybook] = Field(
        description="Per-scenario contingency playbooks"
    )
    elapsed_seconds: float = 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Decision Triggers (replaces passive watch signals)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TriggerCondition(BaseModel):
    """An observable signal that is part of a trigger combination."""
    signal: str = Field(description="The observable event or indicator")
    check_method: str = Field(default="", description="How to detect this signal")
    confidence_weight: float = Field(default=1.0, ge=0.0, le=1.0)


class DecisionTrigger(BaseModel):
    """A combination of signals that activates a specific playbook."""
    trigger_id: str
    conditions: list[TriggerCondition] = Field(
        description="Signals that must co-occur to activate this trigger"
    )
    threshold: str = Field(
        default="all",
        description="'all' = all conditions needed, '2_of_3' = majority, etc."
    )
    activates_scenario: str = Field(description="Which scenario this trigger points to")
    activates_playbook: str = Field(description="Which playbook to execute")
    time_to_act: str = Field(default="", description="How quickly the client must respond")
    false_positive_risk: str = Field(default="", description="What could make this a false alarm")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 0 — Ontological Grounding
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class OntologyResult(BaseModel):
    original_problem: str
    ontological_nature: str = Field(description="What IS this at its most abstract level")
    teleological_purpose: str = Field(description="What is the system trying to achieve")
    causal_analysis: str = Field(description="Real cause vs symptom")
    epistemological_check: str = Field(description="How do we know what we think we know")
    reframed_problem: str = Field(description="The problem restated through the new ontological frame")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1 — XDART-Φ Cross-Domain Reasoning
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DomainAnalogy(BaseModel):
    domain: str
    core_mechanism: str = Field(description="Core failure/success mechanism in 1 sentence")
    analogy_strength: AnalogyStrength
    domain_distance: int = Field(ge=1, le=5, description="1=same field, 5=completely unrelated field")
    mechanistic_specificity: int = Field(ge=1, le=5, description="1=vague, 5=precise mechanism match")
    transfer_hypothesis: str = Field(description="What specific insight transfers to the target domain")


class CrossDomainResult(BaseModel):
    reframed_problem: str
    domains_analyzed: list[DomainAnalogy]
    strongest_analogy: DomainAnalogy
    layer_3_hypothesis: Optional[str] = Field(
        default=None,
        description="Layer-3 hypothesis if domain_distance>=4 AND specificity>=4"
    )
    layer: LayerClassification
    structural_formula: str = Field(description="f(D_source) ≅ g(D_target) expressed formally")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2 — Multiple Views
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ViewInsight(BaseModel):
    view_id: str
    view_name: str
    category: str = Field(description="A-F category")
    insight: str = Field(description="The insight produced by this viewing angle")
    reveals_hidden: str = Field(description="What this view reveals that others hide")


class ViewsResult(BaseModel):
    views_applied: list[ViewInsight]
    convergent_patterns: list[str] = Field(description="Patterns that multiple views agree on")
    divergent_insights: list[str] = Field(description="Unique insights from single views")
    dominant_pattern: str = Field(description="The strongest emergent pattern across all views")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3 — XHEART (Affective Distillation)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class XHEARTState(BaseModel):
    internal_question: str = Field(
        default="Τι νιώθω από όλα αυτά;",
        description="The internal question — always this"
    )
    internal_answer: str = Field(description="The raw felt-sense distillation — NEVER shown to user")
    thesis: str = Field(description="The core hypothesis/insight")
    antithesis: str = Field(description="The strongest reason it is wrong")
    synthesis: Optional[str] = Field(
        default=None,
        description="What survives the dialectical check. None if pure speculation"
    )
    is_layer_3: bool = Field(description="True only if synthesis survives")
    distillate_core: str = Field(description="The essence in one sentence — the ζωμός")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3.5 — Historical Resonance
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class HistoricalParallelAnalysis(BaseModel):
    event_name: str
    event_period: str = ""
    source: str = Field(default="", description="kb_condition_match | llm_recall | kb_vector")
    structural_match_score: float = Field(default=0.0, ge=0.0, le=1.0)
    structural_match_analysis: str = ""
    divergence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    divergence_analysis: str = ""
    historical_trajectory: str = ""
    key_decision_points: list[str] = Field(default_factory=list)
    what_contemporaries_missed: str = ""
    transfer_insights: list[str] = Field(default_factory=list)
    transfer_warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_reasoning: str = ""


class HistoricalVerdict(BaseModel):
    historical_consensus: str = ""
    what_analysis_missed: str = ""
    historical_warning: str = ""
    historical_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_reasoning: str = ""
    early_warning_signals: list[str] = Field(default_factory=list)
    pattern_beneath: str = ""
    strongest_parallel: str = ""
    strongest_parallel_reasoning: str = ""


class HistoricalResonanceResult(BaseModel):
    structural_conditions: list[str] = Field(default_factory=list)
    parallels_found: int = 0
    parallel_analyses: list[HistoricalParallelAnalysis] = Field(default_factory=list)
    verdict: HistoricalVerdict = Field(default_factory=HistoricalVerdict)
    elapsed_seconds: float = 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3.7 — Strategic Foresight
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DecisionPoint(BaseModel):
    decision: str
    deadline_description: str = ""
    cost_of_delay: str = ""


class RiskOpportunityItem(BaseModel):
    item: str
    probability: float = Field(default=0.5, ge=0.0, le=1.0)
    impact: float = Field(default=0.5, ge=0.0, le=1.0)
    time_horizon: str = ""
    mitigation_or_capture_strategy: str = ""


class WatchSignal(BaseModel):
    signal: str
    what_it_means_if_triggered: str = ""
    check_method: str = ""
    timeline: str = ""


class ConfidenceCalibration(BaseModel):
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_reasoning: str = ""
    what_could_prove_me_wrong: str = ""
    biggest_blind_spot: str = ""
    time_sensitivity: str = ""


class StrategicForesightResult(BaseModel):
    strategic_assessment: str = ""
    decision_points: list[DecisionPoint] = Field(default_factory=list)
    risk_opportunity_matrix: dict = Field(
        default_factory=lambda: {"risks": [], "opportunities": []}
    )
    what_to_watch: list[WatchSignal] = Field(default_factory=list)
    recommendations_by_role: dict = Field(default_factory=dict)
    historical_warning: str = ""
    confidence_calibration: ConfidenceCalibration = Field(
        default_factory=ConfidenceCalibration
    )
    elapsed_seconds: float = 0.0

    @field_validator("strategic_assessment", "historical_warning", mode="before")
    @classmethod
    def coerce_list_to_str(cls, v):
        """GPT sometimes returns a list of strings instead of a single string."""
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        return v


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Final Output
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FrameworkOutput(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    problem: str

    # Phase outputs
    phase0_ontology: OntologyResult
    phase1_xdart: CrossDomainResult
    phase2_views: ViewsResult
    phase3_xheart: XHEARTState

    # Prophet phases
    phase2_5_scenarios: Optional[ScenarioGenesisResult] = Field(
        default=None, description="Scenarios generated from views"
    )
    phase2_7_simulations: Optional[AllSimulationsResult] = Field(
        default=None, description="Forward-projected scenario simulations"
    )
    phase2_9_tribunal: Optional[ScenarioTribunalResult] = Field(
        default=None, description="Cross-scenario comparison and ranking"
    )
    prophetic_loop: Optional[PropheticLoopResult] = Field(
        default=None, description="Re-evaluation of past scenarios against new data"
    )

    # Post-XHEART intelligence layers
    phase3_5_historical: Optional[HistoricalResonanceResult] = Field(
        default=None, description="Historical parallel analysis (runs after XHEART)"
    )
    phase3_7_strategic: Optional[StrategicForesightResult] = Field(
        default=None, description="Strategic foresight synthesis (runs after history)"
    )
    phase3_9_bets: Optional[dict] = Field(
        default=None, description="Decision triggers — if/then rules linked to playbooks"
    )

    # Client context
    client_profile: Optional[ClientProfile] = Field(
        default=None, description="Who the analysis is for — decision scope and resources"
    )

    # Scenario-Action Mapping (Phase 2.95)
    phase2_95_actions: Optional[ScenarioActionMappingResult] = Field(
        default=None, description="Per-scenario playbooks + robust moves for the client"
    )

    # Final
    final_output: str = Field(description="Born from XHEART distillate — NOT a summary")
    falsifiability: str = Field(description="What would disprove this within 6 months")
    layer: LayerClassification
    memory_stored: bool = False

    # XHEART Expansion
    self_generated_layers: list[dict] = Field(
        default_factory=list,
        description="Self-generated layers from XHEART expansion (0 or 1 items)"
    )
    expansion_triggered: bool = Field(
        default=False,
        description="Whether XHEART detected a gap and ran a self-generated layer"
    )

    # Working Memory snapshot
    working_memory_snapshot: Optional[WorkingMemoryState] = Field(
        default=None, description="State of working memory at end of pipeline"
    )

    # Executive Intelligence Brief (Phase 3.95)
    executive_brief: Optional["ExecutiveBrief"] = Field(
        default=None,
        description="Condensed 1-2 page executive intelligence brief synthesized from all phases",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Executive Intelligence Brief
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ExecutiveBrief(BaseModel):
    """Condensed 1-2 page intelligence brief for decision-makers.

    Synthesized from ALL pipeline phases into a single narrative
    that answers: What is happening? What will happen? What to do? When?
    """
    situation: str = Field(description="Current state — what is ACTUALLY happening at structural level")
    key_judgments: list[str] = Field(
        default_factory=list,
        description="3-5 high-confidence analytical judgments (numbered)",
    )
    scenarios_ranked: str = Field(
        description="Most likely outcomes ranked — name, probability, one-line summary each",
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Prioritized actions — what to do, in order of urgency",
    )
    critical_timeline: str = Field(
        description="Key dates and decision windows — when to act",
    )
    risks_and_contingencies: str = Field(
        description="What could go wrong and fallback plans",
    )
    bottom_line: str = Field(
        description="One-paragraph executive summary — THE bottom line for the decision-maker",
    )
    confidence_statement: str = Field(
        default="",
        description="Overall confidence level with key caveats",
    )
    elapsed_seconds: float = 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Episodic Memory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EpisodicMemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    problem: str
    reframed_problem: str
    xheart_distillate: str = Field(description="The internal state — the experience, not the information")
    domain_tags: list[str] = Field(default_factory=list)
    layer_score: float = Field(ge=0.0, le=1.0)
    self_generated_layers: list[dict] = Field(
        default_factory=list,
        description="Self-generated layers from XHEART expansion"
    )
    expansion_triggered: bool = Field(
        default=False,
        description="Whether XHEART expansion ran for this entry"
    )


class RetrievedMemory(BaseModel):
    entry: EpisodicMemoryEntry
    similarity_score: float = Field(ge=0.0, le=1.0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2.5 — Scenario Genesis
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ScenarioCondition(BaseModel):
    description: str = Field(description="A condition that must hold for this scenario")
    currently_met: bool = Field(description="Whether this condition is currently observable")
    evidence: str = Field(description="Why we believe this condition is or isn't met")


class Scenario(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="Short memorable name for this scenario")
    source_view_id: str = Field(default="", description="Which view/angle spawned this scenario")
    source_perspective: str = Field(description="The perspective that generated this scenario")
    narrative: str = Field(description="What happens in this scenario — the story")
    trajectory: str = Field(description="The path from now to outcome — step by step")
    conditions: list[ScenarioCondition] = Field(
        default_factory=list,
        description="What must be true for this to unfold"
    )
    timeline: str = Field(description="Expected timeframe — weeks, months, years")
    predicted_outcome: str = Field(description="The end state if this scenario plays out")
    confidence: float = Field(ge=0.0, le=1.0, description="How confident in this trajectory")
    falsifiability: str = Field(description="What would disprove this scenario within 6 months")


class ScenarioGenesisResult(BaseModel):
    scenarios: list[Scenario] = Field(description="3-7 scenarios generated from views")
    generation_logic: str = Field(description="Why these scenarios and not others")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2.7 — Scenario Simulation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SimulationBreakpoint(BaseModel):
    at_step: str = Field(description="At which point in the trajectory this breaks")
    reason: str = Field(description="Why it breaks here")
    severity: str = Field(description="FATAL — kills the scenario | DEGRADING — weakens but continues | MINOR")


class ScenarioSimulationResult(BaseModel):
    scenario_id: str
    scenario_name: str
    forward_projection: str = Field(description="Step-by-step unfolding through time")
    stress_test_results: list[str] = Field(description="What happens when assumptions are stressed")
    breakpoints: list[SimulationBreakpoint] = Field(description="Where this scenario fails")
    robustness_score: float = Field(ge=0.0, le=1.0, description="How robust after stress testing")
    revised_confidence: float = Field(ge=0.0, le=1.0, description="Updated confidence post-simulation")
    simulation_insight: str = Field(description="Key insight from running this forward")


class AllSimulationsResult(BaseModel):
    simulations: list[ScenarioSimulationResult]
    simulation_summary: str = Field(description="Overall summary of what simulations revealed")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2.9 — Scenario Tribunal
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TribunalVerdict(BaseModel):
    scenario_id: str
    scenario_name: str
    feasibility_rank: int = Field(ge=1, description="1 = most feasible")
    evidence_strength: float = Field(ge=0.0, le=1.0)
    internal_consistency: float = Field(ge=0.0, le=1.0)
    final_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Why this ranking")


class ScenarioTribunalResult(BaseModel):
    verdicts: list[TribunalVerdict] = Field(description="All scenarios ranked")
    dominant_scenario: TribunalVerdict = Field(description="The most feasible/likely scenario")
    alternative_scenarios: list[TribunalVerdict] = Field(description="Viable alternatives")
    convergence_points: list[str] = Field(description="Where multiple scenarios agree — strongest signals")
    divergence_points: list[str] = Field(description="Where scenarios fundamentally disagree")
    tribunal_synthesis: str = Field(description="What the tribunal process itself revealed")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Prophetic Memory — Scenarios with outcomes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PropheticMemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    problem: str
    scenario: Scenario
    simulation: ScenarioSimulationResult
    tribunal_rank: int
    tribunal_score: float
    was_dominant: bool = Field(description="Was this the dominant scenario at time of creation")
    tracking_status: str = Field(
        default="active",
        description="active | tracking | confirmed | disconfirmed | expired"
    )
    reality_checks: list[dict] = Field(
        default_factory=list,
        description="Subsequent checks comparing prediction vs reality"
    )
    brier_score: float | None = Field(
        default=None,
        description="Brier score (0=perfect, 1=worst). Set when confirmed/disconfirmed."
    )


class RetrievedPropheticMemory(BaseModel):
    entry: PropheticMemoryEntry
    similarity_score: float = Field(ge=0.0, le=1.0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Human-like Memory Architecture
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SensoryImpression(BaseModel):
    """Αισθητηριακή μνήμη — raw impression before processing.
    Most are discarded. Only salient ones survive to working memory."""
    source: str = Field(description="perception | input | memory_echo | scenario_echo")
    content: str = Field(description="Raw impression — unprocessed")
    salience: float = Field(ge=0.0, le=1.0, description="How attention-grabbing this is")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkingMemoryItem(BaseModel):
    """Βραχύχρονη / εργαζόμενη μνήμη — active thought.
    Up to 12 slots. Extended capacity for richer analysis."""
    slot_id: int = Field(ge=0, le=14, description="Which working memory slot (0-14)")
    item_type: str = Field(description="scenario | insight | tension | echo | question")
    content: str = Field(description="The active thought")
    source: str = Field(description="Where this came from — phase name or memory retrieval")
    relevance: float = Field(ge=0.0, le=1.0)
    entered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkingMemoryState(BaseModel):
    """Snapshot of working memory at a point in the pipeline."""
    items: list[WorkingMemoryItem] = Field(default_factory=list, max_length=14)
    capacity: int = Field(default=12, description="Extended capacity for deeper analysis")
    focus: str = Field(default="", description="What is the current attentional focus")


class SemanticKnowledgeEntry(BaseModel):
    """Σημασιολογική μνήμη — general truths extracted from many experiences.
    NOT specific events — abstract patterns, rules, principles."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    knowledge: str = Field(description="The abstract truth or pattern")
    confidence: float = Field(ge=0.0, le=1.0, description="How confirmed by evidence")
    source_count: int = Field(default=1, description="How many experiences support this")
    first_learned: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_reinforced: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    domain_tags: list[str] = Field(default_factory=list)


class ProceduralPattern(BaseModel):
    """Σιωπηρή / διαδικαστική μνήμη — learned reasoning patterns.
    Applied automatically without explicit deliberation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pattern_name: str = Field(description="Name of this reasoning pattern")
    trigger_condition: str = Field(description="When to apply this automatically")
    action: str = Field(description="What to do when triggered")
    learned_from: str = Field(description="Which experiences taught this")
    success_rate: float = Field(ge=0.0, le=1.0, default=0.5)
    application_count: int = Field(default=0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Updated FrameworkOutput with Prophet fields
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PropheticLoopResult(BaseModel):
    """Result of the Prophetic Loop — re-reading past scenarios."""
    past_scenarios_reviewed: int = Field(default=0)
    still_tracking: list[str] = Field(default_factory=list, description="Scenario names still on track")
    disconfirmed: list[str] = Field(default_factory=list, description="Scenario names reality disproved")
    belief_updates: list[str] = Field(default_factory=list, description="How beliefs changed")
    loop_insight: str = Field(default="", description="What the loop itself revealed")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Quantum Scenario Engine Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class QuantumAmplitude(BaseModel):
    """Complex amplitude αᵢ = |αᵢ|·e^(iθᵢ) for a scenario in quantum superposition."""
    scenario_id: str
    scenario_name: str
    magnitude: float = Field(ge=0.0, description="|αᵢ| — amplitude magnitude")
    phase: float = Field(description="θᵢ — phase angle in radians [0, 2π)")
    mechanism_class: str = Field(description="Mechanism cluster from LLM classification")
    classical_score: float = Field(ge=0.0, le=1.0, description="Original tribunal final_score")

    @property
    def probability(self) -> float:
        """Born rule: P(Sᵢ) = |αᵢ|²"""
        return self.magnitude ** 2


class EntanglementLink(BaseModel):
    """Quantum entanglement between two scenarios via shared conditions."""
    scenario_a_id: str
    scenario_b_id: str
    shared_conditions: list[str] = Field(description="Conditions both scenarios depend on")
    strength: float = Field(ge=0.0, le=1.0, description="Jaccard similarity of condition sets")


class InterferencePattern(BaseModel):
    """Detected interference between scenario amplitudes within a mechanism class."""
    scenario_ids: list[str]
    scenario_names: list[str]
    pattern_type: str = Field(description="CONSTRUCTIVE or DESTRUCTIVE")
    mechanism_class: str
    classical_probability: float = Field(description="Σ|αᵢ|² — classical sum of individual probs")
    quantum_probability: float = Field(description="|Σαᵢ|² — quantum coherent sum")
    interference_delta: float = Field(description="quantum - classical (+ = constructive, - = destructive)")
    insight: str = Field(description="What this interference pattern reveals")


class QuantumScenarioState(BaseModel):
    """Full quantum state |Ψ⟩ = Σᵢ αᵢ|Sᵢ⟩ of the scenario space."""
    amplitudes: list[QuantumAmplitude]
    entanglement: list[EntanglementLink] = Field(default_factory=list)
    coherence: float = Field(ge=0.0, le=1.0, default=1.0, description="1.0=fully quantum, 0.0=classical")
    mechanism_classes: dict[str, list[str]] = Field(
        default_factory=dict,
        description="mechanism_class → [scenario_ids]",
    )
    timestamp: float = Field(default=0.0)


class QuantumCollapseResult(BaseModel):
    """Result of quantum measurement — wave function collapse along observer's question axis."""
    collapsed_probabilities: dict[str, float] = Field(description="scenario_id → quantum probability")
    quantum_dominant_id: str = Field(description="Scenario that won the quantum measurement")
    quantum_dominant_name: str
    quantum_dominant_probability: float
    classical_dominant_id: str = Field(description="Scenario that won in classical tribunal")
    classical_dominant_probability: float
    observer_shifted_dominant: bool = Field(
        description="True if quantum dominant differs from classical — observer effect detected"
    )
    interference_patterns: list[InterferencePattern] = Field(default_factory=list)
    hidden_signals: list[str] = Field(
        default_factory=list,
        description="Insights from destructive interference — what cancellation reveals",
    )
    entanglement_clusters: list[list[str]] = Field(
        default_factory=list,
        description="Groups of entangled scenario names",
    )
    measurement_basis: str = Field(default="", description="The measurement axis (from user's problem)")
    coherence_at_measurement: float = Field(default=1.0)
    quantum_vs_classical_deltas: dict[str, float] = Field(
        default_factory=dict,
        description="scenario_id → (quantum_P - classical_P)",
    )
    quantum_narrative: str = Field(default="", description="LLM synthesis of quantum analysis")
    elapsed_seconds: float = Field(default=0.0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2.92 — Bayesian-Fuzzy Reasoning Engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FuzzyEvidence(BaseModel):
    """Fuzzified indicator — qualitative data mapped to membership degrees."""
    variable: str = Field(description="Variable name (e.g., 'inspection_delay')")
    value: float = Field(ge=0.0, le=1.0, description="Raw indicator value [0,1]")
    memberships: dict[str, float] = Field(
        description="Fuzzy term → membership degree μ ∈ [0,1]"
    )
    dominant_term: str = Field(description="Fuzzy term with highest membership")
    dominant_membership: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, description="LLM confidence in the assessment")
    evidence_text: str = Field(default="", description="Cited evidence from context")
    reasoning: str = Field(default="", description="Why this value was assigned")


class BayesianNodeState(BaseModel):
    """State of a single node in the Bayesian network after evidence update."""
    node_name: str = Field(description="e.g., 'proliferation_risk', 'systemic_risk'")
    prior_distribution: dict[str, float] = Field(description="state → prior probability")
    posterior_distribution: dict[str, float] = Field(description="state → posterior probability")
    dominant_state: str = Field(description="State with highest posterior probability")
    dominant_probability: float = Field(ge=0.0, le=1.0)
    entropy: float = Field(ge=0.0, description="Shannon entropy — higher = more uncertain")
    kl_divergence: float = Field(ge=0.0, description="KL(posterior ‖ prior) — information gain")


class RiskPosterior(BaseModel):
    """Posterior risk assessment for a single latent variable."""
    risk_variable: str
    posterior: dict[str, float] = Field(description="state → posterior probability")
    dominant_level: str
    dominant_probability: float = Field(ge=0.0, le=1.0)
    prior_shift: dict[str, float] = Field(
        default_factory=dict,
        description="state → (posterior − prior) shift"
    )


class BayesianFuzzyResult(BaseModel):
    """Output of Phase 2.92 — Bayesian-Fuzzy risk assessment."""
    domain: str = Field(description="Detected domain template (nuclear_proliferation | financial_stress)")
    domain_description: str = Field(default="")
    fuzzy_evidence: list[FuzzyEvidence] = Field(default_factory=list)
    bayesian_nodes: list[BayesianNodeState] = Field(default_factory=list)
    risk_posteriors: list[RiskPosterior] = Field(default_factory=list)
    risk_assessment: str = Field(default="", description="Human-readable risk statement")
    dominant_risk_level: str = Field(default="medium", description="low|medium|high|critical")
    causal_chain: str = Field(default="", description="Dominant causal pathway explanation")
    key_drivers: list[str] = Field(default_factory=list, description="Most influential indicators")
    uncertainty_map: dict = Field(default_factory=dict, description="Where posteriors are wide")
    strategic_implications: list[str] = Field(default_factory=list)
    calibration_assessment: str = Field(default="")
    recommended_evidence: list[str] = Field(
        default_factory=list,
        description="What additional data would narrow uncertainty"
    )
    risk_narrative: str = Field(default="", description="Synthesis for prophetic memory")
    cross_indicator_tensions: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
