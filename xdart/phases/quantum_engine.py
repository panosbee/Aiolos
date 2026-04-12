"""
XDART-Φ × XHEART — Phase 2.91: Quantum Scenario Engine

Εφαρμόζει 5 αρχές κβαντικής μηχανικής στα σενάρια:

1. ΥΠΕΡΘΕΣΗ (Superposition)
   |Ψ⟩ = Σᵢ αᵢ|Sᵢ⟩  — κάθε σενάριο υπάρχει ταυτόχρονα ως μιγαδικό πλάτος

2. ΣΥΜΒΟΛΗ (Interference)
   Σενάρια με ίδιο μηχανισμό: constructive interference → ενισχυμένο σήμα
   Σενάρια με αντίθετο μηχανισμό: destructive interference → αποκαλύπτεται δομή

3. ΚΒΑΝΤΙΚΗ ΔΙΕΜΠΛΟΚΗ (Entanglement)
   Shared conditions → correlated updates (μετράς ένα, ξέρεις αμέσως για τ' άλλο)

4. ΚΑΤΆΡΡΕΥΣΗ (Measurement / Collapse)
   Η ΕΡΩΤΗΣΗ ΤΟΥ ΧΡΗΣΤΗ = measurement basis → ο παρατηρητής ορίζει το αποτέλεσμα

5. ΑΠΟΣΥΝΟΧΗ (Decoherence)
   Real-world data κάνει quantum → classical σταδιακά

Μαθηματικές βάσεις:
  State vector:   |Ψ⟩ = Σᵢ αᵢ|Sᵢ⟩,  αᵢ ∈ ℂ,  Σ|αᵢ|² = 1
  Born rule:      P(Sᵢ) = |αᵢ|²
  Interference:   P(outcome) = |Σᵢ αᵢ·⟨Sᵢ|B⟩|²  ≠  Σᵢ |αᵢ|²·|⟨Sᵢ|B⟩|²
  Entanglement:   ρ(A,B) = Jaccard(conditions_A, conditions_B)
  Decoherence:    coherence(t) = c₀ · exp(-λ·t)
"""

import cmath
import logging
import math
import time
from typing import Any

from xdart.config import (
    QUANTUM_COHERENCE_INITIAL,
    QUANTUM_DECOHERENCE_RATE,
    QUANTUM_INTERFERENCE_THRESHOLD,
)
from xdart.llm import LLMClient
from xdart.models import (
    AllSimulationsResult,
    EntanglementLink,
    InterferencePattern,
    QuantumAmplitude,
    QuantumCollapseResult,
    QuantumScenarioState,
    Scenario,
    ScenarioTribunalResult,
)

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LLM Prompts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MECHANISM_CLASSIFICATION_PROMPT = """You are a Quantum Mechanism Analyzer for the XDART-Φ framework.

Given {n_scenarios} scenarios from a geopolitical/strategic analysis, your task is to:

1. CLASSIFY each scenario's UNDERLYING MECHANISM into clusters.
   Scenarios with the SAME mechanism type will constructively interfere
   (their signals amplify). Scenarios with OPPOSING mechanisms will
   destructively interfere (they cancel, revealing deeper structure).

2. IDENTIFY opposing pairs — mechanism classes that work in opposite directions.

Rules:
- A mechanism class is the STRUCTURAL DRIVER (not the topic surface).
  E.g., "supply disruption" and "demand collapse" are DIFFERENT mechanisms
  even if both affect the same market.
- Name the classes descriptively (2-5 words).
- Each scenario belongs to EXACTLY ONE class.
- Two classes are OPPOSING if they predict contradictory dynamics
  (e.g., "acceleration" vs "deceleration" of the same structural force).

SCENARIOS:
{scenarios_text}

Respond in JSON:
{{
  "mechanism_classes": {{
    "class_name": {{
      "description": "What this mechanism structurally does (1 sentence)",
      "scenario_ids": ["id1", "id2"],
      "direction": "AMPLIFYING|DAMPENING|TRANSFORMING|DESTABILIZING|STABILIZING"
    }}
  }},
  "opposing_pairs": [
    {{
      "class_a": "name1",
      "class_b": "name2",
      "opposition_axis": "What structural dimension they oppose on (1 sentence)"
    }}
  ]
}}"""


MEASUREMENT_PROMPT = """You are the Quantum Measurement Operator for XDART-Φ.

THE OBSERVER'S QUESTION (defines the measurement basis):
{problem}

SCENARIOS IN SUPERPOSITION (with quantum amplitudes):
{scenarios_text}

INTERFERENCE PATTERNS DETECTED:
{interference_text}

ENTANGLEMENT CLUSTERS:
{entanglement_text}

YOUR TASKS:

1. PROJECTION COEFFICIENTS — For each scenario, rate how directly it addresses
   the CORE CONCERN of the observer's question (0.0 to 1.0).
   This is ⟨Sᵢ|B⟩ — the projection of the scenario onto the measurement basis.
   - 1.0 = the scenario's mechanism directly answers what the observer asks
   - 0.5 = tangentially related
   - 0.1 = barely touches the question's core concern

2. HIDDEN SIGNALS — What does the interference pattern reveal?
   - Constructive interference: what AMPLIFIED signal should the observer pay attention to?
   - Destructive interference: what CANCELLATION reveals about deeper structure?
   - What would be INVISIBLE in classical analysis but emerges from quantum?

3. MEASUREMENT BASIS — Describe in 1 sentence WHAT ASPECT of reality this
   question is measuring. The same scenarios, measured from a different angle,
   would give different results.

4. QUANTUM NARRATIVE — A synthesis (3-5 sentences) capturing what the quantum
   analysis reveals that classical scenario ranking CANNOT. Focus on:
   - Observer-dependent reality (how the question shapes the answer)
   - Interference insights (amplified/canceled signals)
   - Entanglement implications (what correlates with what)

Respond in JSON:
{{
  "projections": {{
    "scenario_id_1": 0.85,
    "scenario_id_2": 0.40
  }},
  "hidden_signals": [
    "Signal: ...",
    "Signal: ..."
  ],
  "measurement_basis": "This question measures the X dimension of reality",
  "quantum_narrative": "The quantum analysis reveals..."
}}"""


class QuantumScenarioEngine:
    """
    Phase 2.91 — Quantum Scenario Engine.

    Transforms the classical scenario ranking (Phase 2.9 Tribunal)
    into a quantum superposition and collapses it along the observer's
    question axis. The collapse produces probabilities that can DIFFER
    from classical ranking due to interference between scenario amplitudes.

    Mathematical formulation:

      |Ψ⟩ = Σᵢ αᵢ|Sᵢ⟩

    where αᵢ = √(score_i / Σ scores) · e^(iθᵢ)

    Interference within mechanism class k:
      P_quantum_k = |Σ_{i∈k} αᵢ·βᵢ|²
      P_classical_k = Σ_{i∈k} |αᵢ·βᵢ|²
      δ_k = P_quantum_k − P_classical_k   (+ constructive, − destructive)

    Final probability blended by coherence:
      P_final_i = c·P_quantum_i + (1−c)·P_classical_i
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        scenarios: list[Scenario],
        tribunal: ScenarioTribunalResult,
        simulations: AllSimulationsResult,
        world_context: str = "",
    ) -> QuantumCollapseResult:
        """
        Full quantum pipeline:
        1. Build quantum state |Ψ⟩ (amplitudes + entanglement + phases)
        2. Compute interference patterns (constructive / destructive)
        3. Measure along observer's question axis (collapse)
        4. Return quantum-adjusted probabilities + insights
        """
        logger.info("=" * 60)
        logger.info("[Quantum 2.91] QUANTUM SCENARIO ENGINE — START")
        logger.info("[Quantum 2.91] Scenarios in superposition: %d", len(scenarios))
        t0 = time.perf_counter()

        if len(scenarios) < 2:
            logger.info("[Quantum 2.91] <2 scenarios — quantum effects negligible, passthrough")
            return self._classical_passthrough(scenarios, tribunal, time.perf_counter() - t0)

        # ── Step 1: Build Quantum State ──
        state = self._build_quantum_state(scenarios, tribunal, simulations)
        logger.info("[Quantum 2.91] State built — %d amplitudes, %d entanglement links, %d mechanism classes",
                     len(state.amplitudes), len(state.entanglement), len(state.mechanism_classes))
        for amp in state.amplitudes:
            logger.info("[Quantum 2.91]   |%s⟩: |α|=%.4f, θ=%.2f rad, class=%s, P_classical=%.3f",
                         amp.scenario_name[:30], amp.magnitude, amp.phase,
                         amp.mechanism_class, amp.classical_score)

        # ── Step 2: Compute Interference ──
        interference_patterns = self._compute_interference(state)
        for ip in interference_patterns:
            logger.info("[Quantum 2.91]   %s interference in '%s': δ=%+.4f (%s)",
                         ip.pattern_type, ip.mechanism_class,
                         ip.interference_delta, ip.insight[:80])

        # ── Step 3: Measure (Collapse) ──
        collapse = self._measure(state, problem, interference_patterns, world_context)

        elapsed = time.perf_counter() - t0
        collapse.elapsed_seconds = elapsed

        logger.info("[Quantum 2.91] COLLAPSE RESULT:")
        logger.info("[Quantum 2.91]   Quantum dominant: %s (P=%.3f)",
                     collapse.quantum_dominant_name, collapse.quantum_dominant_probability)
        logger.info("[Quantum 2.91]   Classical dominant: %s (P=%.3f)",
                     tribunal.dominant_scenario.scenario_name, collapse.classical_dominant_probability)
        if collapse.observer_shifted_dominant:
            logger.info("[Quantum 2.91]   *** OBSERVER EFFECT: quantum dominant DIFFERS from classical! ***")
        for sid, delta in collapse.quantum_vs_classical_deltas.items():
            if abs(delta) > 0.01:
                name = next((a.scenario_name for a in state.amplitudes if a.scenario_id == sid), sid[:8])
                logger.info("[Quantum 2.91]   Δ(%s) = %+.4f", name[:25], delta)
        logger.info("[Quantum 2.91] Hidden signals: %d", len(collapse.hidden_signals))
        logger.info("[Quantum 2.91] QUANTUM SCENARIO ENGINE — COMPLETE (%.2fs)", elapsed)
        logger.info("=" * 60)

        return collapse

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 1: Build Quantum State
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_quantum_state(
        self,
        scenarios: list[Scenario],
        tribunal: ScenarioTribunalResult,
        simulations: AllSimulationsResult,
    ) -> QuantumScenarioState:
        """
        Build |Ψ⟩ from tribunal-scored scenarios.

        1. Classify mechanisms via LLM → mechanism classes
        2. Compute magnitudes from tribunal scores (Born rule inverse)
        3. Assign phases from mechanism clustering
        4. Build entanglement graph from shared conditions
        5. Normalize to unit vector: Σ|αᵢ|² = 1
        """
        # Build score lookup from tribunal
        score_by_id: dict[str, float] = {}
        for v in tribunal.verdicts:
            score_by_id[v.scenario_id] = max(v.final_score, 0.01)

        # ── LLM: Classify mechanisms ──
        mechanism_data = self._classify_mechanisms(scenarios)
        mechanism_classes: dict[str, list[str]] = {}  # class → [scenario_ids]
        scenario_to_class: dict[str, str] = {}
        opposing_pairs: list[dict] = mechanism_data.get("opposing_pairs", [])

        for class_name, class_info in mechanism_data.get("mechanism_classes", {}).items():
            sids = class_info.get("scenario_ids", [])
            mechanism_classes[class_name] = sids
            for sid in sids:
                scenario_to_class[sid] = class_name

        # Assign any unclassified scenarios to "Unclassified" class
        for sc in scenarios:
            if sc.id not in scenario_to_class:
                scenario_to_class[sc.id] = "Unclassified"
                mechanism_classes.setdefault("Unclassified", []).append(sc.id)

        # ── Compute magnitudes ──
        raw_magnitudes = {}
        for sc in scenarios:
            score = score_by_id.get(sc.id, sc.confidence)
            raw_magnitudes[sc.id] = math.sqrt(max(score, 0.01))

        # Normalize: Σ|αᵢ|² = 1
        norm_factor = math.sqrt(sum(m ** 2 for m in raw_magnitudes.values()))
        if norm_factor < 1e-10:
            norm_factor = 1.0

        # ── Assign phases ──
        phases = self._assign_phases(
            scenarios, mechanism_classes, scenario_to_class, opposing_pairs
        )

        # ── Build amplitudes ──
        amplitudes = []
        for sc in scenarios:
            mag = raw_magnitudes[sc.id] / norm_factor
            phase = phases.get(sc.id, 0.0)
            amplitudes.append(QuantumAmplitude(
                scenario_id=sc.id,
                scenario_name=sc.name,
                magnitude=mag,
                phase=phase,
                mechanism_class=scenario_to_class.get(sc.id, "Unclassified"),
                classical_score=score_by_id.get(sc.id, sc.confidence),
            ))

        # ── Build entanglement graph ──
        entanglement = self._build_entanglement_graph(scenarios)

        return QuantumScenarioState(
            amplitudes=amplitudes,
            entanglement=entanglement,
            coherence=QUANTUM_COHERENCE_INITIAL,
            mechanism_classes=mechanism_classes,
            timestamp=time.time(),
        )

    def _classify_mechanisms(self, scenarios: list[Scenario]) -> dict[str, Any]:
        """LLM call: classify scenario mechanisms into clusters."""
        scenarios_text = ""
        for sc in scenarios:
            conditions_str = "; ".join(c.description for c in sc.conditions[:4])
            scenarios_text += (
                f"ID: {sc.id}\n"
                f"  Name: {sc.name}\n"
                f"  Mechanism: {sc.narrative[:200]}\n"
                f"  Trajectory: {sc.trajectory[:150]}\n"
                f"  Conditions: {conditions_str}\n"
                f"  Outcome: {sc.predicted_outcome[:150]}\n\n"
            )

        system = MECHANISM_CLASSIFICATION_PROMPT.format(
            n_scenarios=len(scenarios),
            scenarios_text=scenarios_text,
        )

        user = (
            f"Classify these {len(scenarios)} scenarios into mechanism clusters. "
            f"Remember: the classification is about STRUCTURAL MECHANISMS, not surface topics. "
            f"Two scenarios about the same topic can be in DIFFERENT classes if their "
            f"underlying drivers differ."
        )

        logger.info("[Quantum 2.91] LLM call: mechanism classification (%d scenarios)", len(scenarios))
        data = self.llm.call_json(system, user, max_tokens=2048, thinking=False)
        logger.info("[Quantum 2.91] Mechanism classes: %s",
                     list(data.get("mechanism_classes", {}).keys()))
        return data

    def _assign_phases(
        self,
        scenarios: list[Scenario],
        mechanism_classes: dict[str, list[str]],
        scenario_to_class: dict[str, str],
        opposing_pairs: list[dict],
    ) -> dict[str, float]:
        """
        Assign phase angles θᵢ to each scenario based on mechanism clustering.

        Same mechanism class → similar phases → constructive interference
        Opposing classes → phases ~π apart → destructive interference
        Different (non-opposing) classes → evenly spaced around 2π
        """
        phases: dict[str, float] = {}
        class_names = list(mechanism_classes.keys())
        n_classes = max(len(class_names), 1)

        # Build opposition map: if A opposes B, their base phases differ by π
        opposing_map: dict[str, str] = {}
        for pair in opposing_pairs:
            a, b = pair.get("class_a", ""), pair.get("class_b", "")
            if a and b:
                opposing_map[a] = b
                opposing_map[b] = a

        # Assign base phases to each class
        class_base_phases: dict[str, float] = {}
        assigned_classes: set[str] = set()

        for i, cn in enumerate(class_names):
            if cn in assigned_classes:
                continue
            base = (2 * math.pi * i) / n_classes
            class_base_phases[cn] = base
            assigned_classes.add(cn)

            # If this class has an opposing counterpart, place it at base + π
            opp = opposing_map.get(cn)
            if opp and opp in class_names and opp not in assigned_classes:
                class_base_phases[opp] = (base + math.pi) % (2 * math.pi)
                assigned_classes.add(opp)

        # Assign individual scenario phases within their class
        # Small spread within class: ±π/12 (15°)
        for sc in scenarios:
            cn = scenario_to_class.get(sc.id, "Unclassified")
            base = class_base_phases.get(cn, 0.0)
            # Deterministic perturbation from scenario id
            hash_val = hash(sc.id) % 10000
            perturbation = (hash_val / 10000.0 - 0.5) * (math.pi / 6)
            phases[sc.id] = (base + perturbation) % (2 * math.pi)

        return phases

    def _build_entanglement_graph(self, scenarios: list[Scenario]) -> list[EntanglementLink]:
        """
        Build entanglement from shared conditions (Jaccard similarity).

        Scenarios sharing conditions are quantum-entangled:
        observing one's condition updates the other instantly.
        """
        links = []
        for i, sa in enumerate(scenarios):
            conds_a = {c.description.lower().strip() for c in sa.conditions}
            if not conds_a:
                continue
            for j, sb in enumerate(scenarios):
                if j <= i:
                    continue
                conds_b = {c.description.lower().strip() for c in sb.conditions}
                if not conds_b:
                    continue

                intersection = conds_a & conds_b
                union = conds_a | conds_b
                if not union:
                    continue
                jaccard = len(intersection) / len(union)
                if jaccard > 0.0:
                    links.append(EntanglementLink(
                        scenario_a_id=sa.id,
                        scenario_b_id=sb.id,
                        shared_conditions=list(intersection),
                        strength=jaccard,
                    ))
                    logger.debug("[Quantum 2.91] Entanglement: %s ↔ %s (strength=%.2f, shared=%d)",
                                  sa.name[:20], sb.name[:20], jaccard, len(intersection))

        return links

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 2: Compute Interference
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _compute_interference(
        self,
        state: QuantumScenarioState,
    ) -> list[InterferencePattern]:
        """
        Compute interference patterns between scenario amplitudes.

        Group by mechanism class. Within each class:
          coherent_sum = Σ αᵢ     (complex addition — phases matter!)
          P_quantum = |coherent_sum|²
          P_classical = Σ |αᵢ|²
          δ = P_quantum - P_classical

        δ > 0 → constructive interference (aligned mechanisms amplify)
        δ < 0 → destructive interference (opposing phases cancel)
        δ = 0 → no interference (random phases, pure noise)
        """
        patterns = []

        for class_name, scenario_ids in state.mechanism_classes.items():
            if len(scenario_ids) < 2:
                continue

            # Get amplitudes for this class
            class_amps = [a for a in state.amplitudes if a.scenario_id in scenario_ids]
            if len(class_amps) < 2:
                continue

            # Compute coherent sum (complex addition)
            coherent_sum = complex(0, 0)
            classical_sum = 0.0
            names = []

            for amp in class_amps:
                alpha = amp.magnitude * cmath.exp(1j * amp.phase)
                coherent_sum += alpha
                classical_sum += amp.magnitude ** 2
                names.append(amp.scenario_name)

            quantum_prob = abs(coherent_sum) ** 2
            delta = quantum_prob - classical_sum

            if abs(delta) < QUANTUM_INTERFERENCE_THRESHOLD:
                continue

            pattern_type = "CONSTRUCTIVE" if delta > 0 else "DESTRUCTIVE"

            if pattern_type == "CONSTRUCTIVE":
                insight = (
                    f"Scenarios {', '.join(n[:20] for n in names)} share a '{class_name}' mechanism — "
                    f"their combined signal is {quantum_prob/max(classical_sum, 0.001):.1f}x stronger "
                    f"than the sum of parts. This structural convergence amplifies confidence."
                )
            else:
                insight = (
                    f"Within '{class_name}', scenario phases partially cancel. "
                    f"The reduction from {classical_sum:.3f} to {quantum_prob:.3f} reveals "
                    f"internal tension in this mechanism class — the underlying driver "
                    f"may be less stable than individual scenarios suggest."
                )

            patterns.append(InterferencePattern(
                scenario_ids=[a.scenario_id for a in class_amps],
                scenario_names=names,
                pattern_type=pattern_type,
                mechanism_class=class_name,
                classical_probability=classical_sum,
                quantum_probability=quantum_prob,
                interference_delta=delta,
                insight=insight,
            ))

        return patterns

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 3: Measure (Collapse)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _measure(
        self,
        state: QuantumScenarioState,
        problem: str,
        interference_patterns: list[InterferencePattern],
        world_context: str = "",
    ) -> QuantumCollapseResult:
        """
        Collapse |Ψ⟩ along measurement basis defined by the observer's problem.

        1. LLM assigns projection coefficients βᵢ = ⟨Sᵢ|B⟩
        2. Compute quantum probabilities WITH interference:
           Group by mechanism class k:
             A'_k = Σ_{i∈k} αᵢ·βᵢ    (coherent sum of projected amplitudes)
             P_quantum_k = |A'_k|²
           Redistribute to individual scenarios proportionally.
        3. Blend with classical by coherence: P = c·P_quantum + (1-c)·P_classical
        4. LLM generates hidden signals + quantum narrative
        """
        # ── LLM: Get projections + narrative ──
        measurement_data = self._llm_measurement(
            state, problem, interference_patterns, world_context
        )

        projections = measurement_data.get("projections", {})
        hidden_signals = measurement_data.get("hidden_signals", [])
        measurement_basis = measurement_data.get("measurement_basis", "")
        quantum_narrative = measurement_data.get("quantum_narrative", "")

        # Default projections for any missing scenario
        for amp in state.amplitudes:
            if amp.scenario_id not in projections:
                projections[amp.scenario_id] = 0.5

        coherence = state.coherence

        # ── Compute quantum probabilities with interference ──
        # Per mechanism class: coherent sum of projected amplitudes
        quantum_probs: dict[str, float] = {}
        classical_probs: dict[str, float] = {}

        for class_name, scenario_ids in state.mechanism_classes.items():
            class_amps = [a for a in state.amplitudes if a.scenario_id in scenario_ids]
            if not class_amps:
                continue

            # Coherent sum: A'_k = Σ αᵢ·βᵢ
            coherent_sum = complex(0, 0)
            individual_mags: dict[str, float] = {}

            for amp in class_amps:
                beta = max(projections.get(amp.scenario_id, 0.5), 0.01)
                alpha = amp.magnitude * cmath.exp(1j * amp.phase)
                projected = alpha * beta
                coherent_sum += projected
                individual_mags[amp.scenario_id] = abs(projected)

            # Quantum probability for this class
            p_quantum_class = abs(coherent_sum) ** 2

            # Distribute class probability to individual scenarios by magnitude share
            total_mag = sum(individual_mags.values())
            if total_mag < 1e-10:
                total_mag = 1.0

            for amp in class_amps:
                share = individual_mags.get(amp.scenario_id, 0.0) / total_mag
                quantum_probs[amp.scenario_id] = p_quantum_class * share

                # Classical: |αᵢ·βᵢ|² (no interference)
                beta = max(projections.get(amp.scenario_id, 0.5), 0.01)
                classical_probs[amp.scenario_id] = (amp.magnitude * beta) ** 2

        # ── Blend by coherence ──
        blended_probs: dict[str, float] = {}
        for sid in quantum_probs:
            pq = quantum_probs.get(sid, 0.0)
            pc = classical_probs.get(sid, 0.0)
            blended_probs[sid] = coherence * pq + (1.0 - coherence) * pc

        # ── Normalize ──
        total = sum(blended_probs.values())
        if total > 1e-10:
            for sid in blended_probs:
                blended_probs[sid] /= total
        else:
            # Fallback: equal distribution
            n = len(blended_probs)
            for sid in blended_probs:
                blended_probs[sid] = 1.0 / max(n, 1)

        # Also normalize classical for comparison
        class_total = sum(classical_probs.values())
        if class_total > 1e-10:
            for sid in classical_probs:
                classical_probs[sid] /= class_total

        # ── Find dominants ──
        quantum_dominant_id = max(blended_probs, key=blended_probs.get) if blended_probs else ""
        classical_dominant_id = max(classical_probs, key=classical_probs.get) if classical_probs else ""

        quantum_dominant_name = ""
        for amp in state.amplitudes:
            if amp.scenario_id == quantum_dominant_id:
                quantum_dominant_name = amp.scenario_name
                break

        # ── Compute deltas ──
        deltas = {}
        for sid in blended_probs:
            deltas[sid] = blended_probs[sid] - classical_probs.get(sid, 0.0)

        # ── Build entanglement clusters ──
        entanglement_clusters = self._build_entanglement_clusters(state)

        return QuantumCollapseResult(
            collapsed_probabilities=blended_probs,
            quantum_dominant_id=quantum_dominant_id,
            quantum_dominant_name=quantum_dominant_name,
            quantum_dominant_probability=blended_probs.get(quantum_dominant_id, 0.0),
            classical_dominant_id=classical_dominant_id,
            classical_dominant_probability=classical_probs.get(classical_dominant_id, 0.0),
            observer_shifted_dominant=(quantum_dominant_id != classical_dominant_id),
            interference_patterns=interference_patterns,
            hidden_signals=hidden_signals,
            entanglement_clusters=entanglement_clusters,
            measurement_basis=measurement_basis,
            coherence_at_measurement=coherence,
            quantum_vs_classical_deltas=deltas,
            quantum_narrative=quantum_narrative,
        )

    def _llm_measurement(
        self,
        state: QuantumScenarioState,
        problem: str,
        interference_patterns: list[InterferencePattern],
        world_context: str = "",
    ) -> dict[str, Any]:
        """LLM call: measure projection coefficients + generate narrative."""
        # Format scenarios
        scenarios_text = ""
        for amp in state.amplitudes:
            scenarios_text += (
                f"  [{amp.scenario_id[:8]}] {amp.scenario_name}\n"
                f"    |α| = {amp.magnitude:.4f}, θ = {amp.phase:.2f} rad, "
                f"    P_classical = {amp.classical_score:.3f}\n"
                f"    Mechanism class: {amp.mechanism_class}\n\n"
            )

        # Format interference
        interference_text = ""
        if interference_patterns:
            for ip in interference_patterns:
                interference_text += (
                    f"  {ip.pattern_type} in '{ip.mechanism_class}': "
                    f"δ = {ip.interference_delta:+.4f}\n"
                    f"    Scenarios: {', '.join(n[:25] for n in ip.scenario_names)}\n"
                    f"    Classical P = {ip.classical_probability:.4f} → "
                    f"Quantum P = {ip.quantum_probability:.4f}\n\n"
                )
        else:
            interference_text = "  No significant interference detected.\n"

        # Format entanglement
        entanglement_text = ""
        clusters = self._build_entanglement_clusters(state)
        if clusters:
            for i, cluster in enumerate(clusters):
                entanglement_text += f"  Cluster {i+1}: {', '.join(cluster)}\n"
        else:
            entanglement_text = "  No entanglement detected.\n"

        system = MEASUREMENT_PROMPT.format(
            problem=problem,
            scenarios_text=scenarios_text,
            interference_text=interference_text,
            entanglement_text=entanglement_text,
        )

        user = (
            f"Measure this quantum scenario state.\n"
            f"Observer's question: {problem[:500]}\n\n"
        )
        if world_context:
            user += f"Current world context (ground your projections):\n{world_context[:800]}\n"

        logger.info("[Quantum 2.91] LLM call: quantum measurement (projections + narrative)")
        data = self.llm.call_json(system, user, max_tokens=2048, thinking=False)
        return data

    def _build_entanglement_clusters(
        self,
        state: QuantumScenarioState,
    ) -> list[list[str]]:
        """Build connected components from entanglement graph → scenario name clusters."""
        if not state.entanglement:
            return []

        # Union-Find
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Initialize
        all_ids = {a.scenario_id for a in state.amplitudes}
        for sid in all_ids:
            parent[sid] = sid

        # Build from entanglement links (threshold: strength > 0.1)
        for link in state.entanglement:
            if link.strength > 0.1:
                union(link.scenario_a_id, link.scenario_b_id)

        # Group by root
        clusters_by_root: dict[str, list[str]] = {}
        name_lookup = {a.scenario_id: a.scenario_name for a in state.amplitudes}
        for sid in all_ids:
            root = find(sid)
            clusters_by_root.setdefault(root, []).append(name_lookup.get(sid, sid[:8]))

        # Only return clusters with 2+ members
        return [names for names in clusters_by_root.values() if len(names) >= 2]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Decoherence (called between runs)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def decohere(
        self,
        state: QuantumScenarioState,
        elapsed_hours: float,
        confirmed_conditions: list[str] | None = None,
        denied_conditions: list[str] | None = None,
    ) -> QuantumScenarioState:
        """
        Apply decoherence: quantum → classical over time.

        coherence *= exp(-λ·t)

        Confirmed/denied conditions accelerate decoherence for entangled scenarios
        and adjust their magnitudes (entanglement update).
        """
        # Time-based decoherence
        decay = math.exp(-QUANTUM_DECOHERENCE_RATE * elapsed_hours)
        new_coherence = state.coherence * decay

        # Build mutable amplitude list
        new_amplitudes = [
            QuantumAmplitude(
                scenario_id=a.scenario_id,
                scenario_name=a.scenario_name,
                magnitude=a.magnitude,
                phase=a.phase,
                mechanism_class=a.mechanism_class,
                classical_score=a.classical_score,
            )
            for a in state.amplitudes
        ]

        # Entanglement update: confirmed/denied conditions affect entangled scenarios
        confirmed_set = {c.lower().strip() for c in (confirmed_conditions or [])}
        denied_set = {c.lower().strip() for c in (denied_conditions or [])}

        if confirmed_set or denied_set:
            for link in state.entanglement:
                shared_lower = {c.lower().strip() for c in link.shared_conditions}
                confirmed_overlap = shared_lower & confirmed_set
                denied_overlap = shared_lower & denied_set

                if confirmed_overlap or denied_overlap:
                    # Find both entangled amplitudes
                    for amp in new_amplitudes:
                        if amp.scenario_id in (link.scenario_a_id, link.scenario_b_id):
                            if confirmed_overlap:
                                # Confirmed shared condition → boost magnitude
                                boost = 1.0 + 0.1 * len(confirmed_overlap) * link.strength
                                amp.magnitude = min(amp.magnitude * boost, 1.0)
                            if denied_overlap:
                                # Denied shared condition → reduce magnitude
                                reduction = 1.0 - 0.15 * len(denied_overlap) * link.strength
                                amp.magnitude = max(amp.magnitude * reduction, 0.01)

                    # Accelerate decoherence for observed entanglements
                    new_coherence *= 0.9

            # Re-normalize after entanglement updates
            norm = math.sqrt(sum(a.magnitude ** 2 for a in new_amplitudes))
            if norm > 1e-10:
                for amp in new_amplitudes:
                    amp.magnitude /= norm

        logger.info(
            "[Quantum] Decoherence applied: %.2fh elapsed, coherence %.4f → %.4f, "
            "%d confirmed, %d denied conditions",
            elapsed_hours, state.coherence, new_coherence,
            len(confirmed_set), len(denied_set),
        )

        return QuantumScenarioState(
            amplitudes=new_amplitudes,
            entanglement=state.entanglement,
            coherence=max(new_coherence, 0.0),
            mechanism_classes=state.mechanism_classes,
            timestamp=time.time(),
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Classical Passthrough (< 2 scenarios)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _classical_passthrough(
        self,
        scenarios: list[Scenario],
        tribunal: ScenarioTribunalResult,
        elapsed: float,
    ) -> QuantumCollapseResult:
        """When <2 scenarios, quantum effects are meaningless — pass through classical."""
        probs = {}
        for v in tribunal.verdicts:
            probs[v.scenario_id] = v.final_score

        total = sum(probs.values())
        if total > 0:
            for sid in probs:
                probs[sid] /= total

        dominant = tribunal.dominant_scenario

        return QuantumCollapseResult(
            collapsed_probabilities=probs,
            quantum_dominant_id=dominant.scenario_id,
            quantum_dominant_name=dominant.scenario_name,
            quantum_dominant_probability=probs.get(dominant.scenario_id, 1.0),
            classical_dominant_id=dominant.scenario_id,
            classical_dominant_probability=probs.get(dominant.scenario_id, 1.0),
            observer_shifted_dominant=False,
            interference_patterns=[],
            hidden_signals=[],
            entanglement_clusters=[],
            measurement_basis="Single scenario — no quantum measurement needed",
            coherence_at_measurement=0.0,
            quantum_vs_classical_deltas={},
            quantum_narrative="Insufficient scenarios for quantum superposition.",
            elapsed_seconds=elapsed,
        )
