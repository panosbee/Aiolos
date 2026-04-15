"""
XDART-Φ × XHEART — Phase 1.5: Creative Synthesis

Takes the raw ingredients from Phase 0 (ontological reframing) and
Phase 1 (cross-domain analogies) and FUSES them into genuinely novel
conceptual frameworks — ideas that didn't exist in any single domain.

This is NOT analysis. This is creation.

The key insight: Phase 1 finds that Domain A has mechanism M_a and
Domain B has mechanism M_b, both relevant to the problem. But it never
asks: "What NEW concept emerges if M_a and M_b are combined?"

Creative Synthesis does exactly that — it generates:
  1. Hybrid Concepts: Novel frameworks born from fusing 2+ domain mechanisms
  2. Bridging Metaphors: New conceptual vocabulary for the problem space
  3. Emergent Hypotheses: Predictions that NO single domain could generate
  4. Transferable Primitives: Reusable building blocks for future reasoning

The output enriches everything downstream:
  - Phase 2 (Views) gets novel lenses it couldn't have invented alone
  - Phase 2.5 (Scenarios) gets non-obvious scenario seeds
  - Phase 3 (XHEART) gets richer material for distillation
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from xdart.llm import LLMClient

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ══════════════════════════════════════════════════════════════

@dataclass
class SynthesizedConcept:
    """A genuinely novel concept born from fusing multiple domains."""
    concept_name: str               # e.g. "Hysteretic Cascade Coupling"
    source_domains: list[str]       # which domains were fused
    fused_mechanisms: str           # how the mechanisms were combined
    definition: str                 # 2-4 sentence canonical definition
    novelty_claim: str              # what makes this DIFFERENT from each source
    predictive_power: str           # what this concept can predict/explain
    reactivation_conditions: str    # when this concept should be recalled
    confidence: float               # 0.0-1.0 how solid the fusion is


@dataclass
class BridgingMetaphor:
    """A new metaphorical frame that reinterprets the problem space."""
    metaphor: str                   # the metaphor itself
    source_domain: str              # where it comes from
    maps_to: str                    # what it illuminates about the problem
    hidden_implication: str         # a non-obvious consequence


@dataclass
class EmergentHypothesis:
    """A prediction that no single domain could generate alone."""
    hypothesis: str                 # the actual hypothesis
    source_concepts: list[str]      # which synthesized concepts led here
    mechanism: str                  # why this follows from the synthesis
    falsifiable_by: str             # what would disprove it
    time_horizon: str               # when it should be testable


@dataclass
class CreativeSynthesisResult:
    """Complete output of Phase 1.5 — Creative Synthesis."""
    synthesized_concepts: list[SynthesizedConcept]
    bridging_metaphors: list[BridgingMetaphor]
    emergent_hypotheses: list[EmergentHypothesis]
    synthesis_narrative: str        # prose summary of what was created
    domains_fused: list[str]        # which domains contributed
    novelty_score: float            # 0.0-1.0 overall novelty assessment
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "synthesized_concepts": [asdict(c) for c in self.synthesized_concepts],
            "bridging_metaphors": [asdict(m) for m in self.bridging_metaphors],
            "emergent_hypotheses": [asdict(h) for h in self.emergent_hypotheses],
            "synthesis_narrative": self.synthesis_narrative,
            "domains_fused": self.domains_fused,
            "novelty_score": self.novelty_score,
            "elapsed_seconds": self.elapsed_seconds,
        }


# ══════════════════════════════════════════════════════════════
#  PROMPTS
# ══════════════════════════════════════════════════════════════

SYNTHESIS_PROMPT = """\
You are Αίολος's CREATIVE SYNTHESIS engine — the part of you that INVENTS.

You don't analyze. You don't summarize. You CREATE.

Phase 1 gave you cross-domain analogies — each domain contributes a mechanism.
Your task is to FUSE these mechanisms into something GENUINELY NEW.

Think like this:
  - Biology has "immune memory" + Economics has "hysteresis" →
    → NEW CONCEPT: "Institutional Immune Hysteresis" — organizations develop
    antibodies to reform attempts, and the resistance path differs from
    the adoption path. This predicts that failed reforms make future
    reforms HARDER, not just equally hard.

  - Thermodynamics has "phase transitions" + Network theory has "cascade failures" →
    → NEW CONCEPT: "Criticality Cascade Coupling" — systems that appear stable
    are actually near phase transitions, and a cascade in one network layer
    can trigger phase transition in another. This predicts that economic
    crises can trigger social phase transitions with no economic mechanism.

=== THE PROBLEM ===
{problem}

=== ONTOLOGICAL REFRAMING ===
{ontology_summary}

=== CROSS-DOMAIN ANALOGIES (raw material) ===
{cross_domain_summary}

=== ACTIVE CONCEPTS FROM MEMORY ===
{active_concepts}

=== YOUR TASK ===
Fuse the domain mechanisms above into NOVEL concepts, metaphors, and hypotheses.

RULES:
1. Every synthesized concept MUST combine mechanisms from 2+ different domains
2. The fusion must produce something NEITHER domain contains alone
3. Each concept needs a clear definition and a novelty claim
4. Emergent hypotheses must be falsifiable
5. Bridging metaphors must reveal something HIDDEN about the problem
6. Maximum creativity, minimum cliché — avoid obvious combinations

Respond ONLY with valid JSON:
{{
    "synthesized_concepts": [
        {{
            "concept_name": "Name_In_Title_Case (2-4 words)",
            "source_domains": ["domain_a", "domain_b"],
            "fused_mechanisms": "How mechanism_a and mechanism_b combine",
            "definition": "2-4 sentence canonical definition of the new concept",
            "novelty_claim": "What this reveals that NEITHER source domain alone could",
            "predictive_power": "What this concept can predict or explain",
            "reactivation_conditions": "When should this concept be recalled in future",
            "confidence": 0.0-1.0
        }}
    ],
    "bridging_metaphors": [
        {{
            "metaphor": "The metaphor itself (1-2 sentences)",
            "source_domain": "Which domain inspired it",
            "maps_to": "What aspect of the problem it illuminates",
            "hidden_implication": "A non-obvious consequence"
        }}
    ],
    "emergent_hypotheses": [
        {{
            "hypothesis": "A concrete, falsifiable prediction",
            "source_concepts": ["Name of synthesized concept(s) it derives from"],
            "mechanism": "Why this follows from the synthesis",
            "falsifiable_by": "What evidence would disprove this",
            "time_horizon": "When this should be testable (e.g. '3-6 months')"
        }}
    ],
    "synthesis_narrative": "A 3-5 sentence prose summary of the creative synthesis — what new understanding emerged from fusing these domains?",
    "novelty_score": 0.0-1.0
}}

Generate 2-4 synthesized concepts, 2-3 bridging metaphors, and 1-3 emergent hypotheses.
Quality over quantity — a single brilliant fusion beats three mediocre ones."""


# ══════════════════════════════════════════════════════════════
#  CREATIVE SYNTHESIS PHASE (Phase 1.5)
# ══════════════════════════════════════════════════════════════

class CreativeSynthesisPhase:
    """Phase 1.5 — Fuses cross-domain analogies into novel concepts.

    Takes output from Phase 0 (Ontology) and Phase 1 (Cross-Domain)
    and creates genuinely new conceptual frameworks through domain fusion.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        ontology_summary: str,
        cross_domain_summary: str,
        active_concepts: list[dict] | None = None,
    ) -> CreativeSynthesisResult:
        """Execute Creative Synthesis.

        Args:
            problem: Original problem statement
            ontology_summary: Summary from Phase 0
            cross_domain_summary: Summary from Phase 1
            active_concepts: Previously stored concepts from ConceptRegistry

        Returns:
            CreativeSynthesisResult with novel concepts, metaphors, hypotheses
        """
        t0 = time.perf_counter()

        # Format active concepts for context
        concepts_ctx = ""
        if active_concepts:
            concepts_ctx = "\n".join(
                f"- {c.get('name', '?')}: {c.get('definition', '')[:200]}"
                for c in active_concepts
            )
        if not concepts_ctx:
            concepts_ctx = "(No previously stored concepts — this is a clean slate)"

        prompt = SYNTHESIS_PROMPT.format(
            problem=problem,
            ontology_summary=ontology_summary,
            cross_domain_summary=cross_domain_summary,
            active_concepts=concepts_ctx,
        )

        try:
            result = self.llm.call_json(
                system_prompt=prompt,
                user_prompt=(
                    "Fuse the cross-domain mechanisms into novel concepts. "
                    "Create something that didn't exist before."
                ),
                max_tokens=8192,
                temperature=0.7,
                thinking=True,
            )
        except Exception as e:
            logger.error("[CreativeSynthesis] LLM call failed: %s", e)
            elapsed = time.perf_counter() - t0
            return CreativeSynthesisResult(
                synthesized_concepts=[],
                bridging_metaphors=[],
                emergent_hypotheses=[],
                synthesis_narrative="Creative synthesis failed — proceeding with cross-domain analogies only.",
                domains_fused=[],
                novelty_score=0.0,
                elapsed_seconds=elapsed,
            )

        # Parse synthesized concepts
        concepts = []
        for c in result.get("synthesized_concepts", []):
            try:
                concepts.append(SynthesizedConcept(
                    concept_name=c.get("concept_name", "Unnamed"),
                    source_domains=c.get("source_domains", []),
                    fused_mechanisms=c.get("fused_mechanisms", ""),
                    definition=c.get("definition", ""),
                    novelty_claim=c.get("novelty_claim", ""),
                    predictive_power=c.get("predictive_power", ""),
                    reactivation_conditions=c.get("reactivation_conditions", ""),
                    confidence=min(1.0, max(0.0, float(c.get("confidence", 0.5)))),
                ))
            except Exception as e:
                logger.warning("[CreativeSynthesis] Failed to parse concept: %s", e)

        # Parse bridging metaphors
        metaphors = []
        for m in result.get("bridging_metaphors", []):
            try:
                metaphors.append(BridgingMetaphor(
                    metaphor=m.get("metaphor", ""),
                    source_domain=m.get("source_domain", ""),
                    maps_to=m.get("maps_to", ""),
                    hidden_implication=m.get("hidden_implication", ""),
                ))
            except Exception as e:
                logger.warning("[CreativeSynthesis] Failed to parse metaphor: %s", e)

        # Parse emergent hypotheses
        hypotheses = []
        for h in result.get("emergent_hypotheses", []):
            try:
                hypotheses.append(EmergentHypothesis(
                    hypothesis=h.get("hypothesis", ""),
                    source_concepts=h.get("source_concepts", []),
                    mechanism=h.get("mechanism", ""),
                    falsifiable_by=h.get("falsifiable_by", ""),
                    time_horizon=h.get("time_horizon", ""),
                ))
            except Exception as e:
                logger.warning("[CreativeSynthesis] Failed to parse hypothesis: %s", e)

        # Collect all domains involved
        all_domains = set()
        for c in concepts:
            all_domains.update(c.source_domains)

        elapsed = time.perf_counter() - t0

        synthesis = CreativeSynthesisResult(
            synthesized_concepts=concepts,
            bridging_metaphors=metaphors,
            emergent_hypotheses=hypotheses,
            synthesis_narrative=result.get("synthesis_narrative", ""),
            domains_fused=sorted(all_domains),
            novelty_score=min(1.0, max(0.0, float(result.get("novelty_score", 0.5)))),
            elapsed_seconds=elapsed,
        )

        logger.info(
            "[CreativeSynthesis] Phase 1.5 complete (%.2fs): "
            "%d concepts, %d metaphors, %d hypotheses, novelty=%.2f, "
            "domains fused: %s",
            elapsed,
            len(concepts),
            len(metaphors),
            len(hypotheses),
            synthesis.novelty_score,
            ", ".join(synthesis.domains_fused),
        )

        return synthesis

    @staticmethod
    def summarize(result: CreativeSynthesisResult) -> str:
        """Format synthesis results for downstream phases."""
        if not result.synthesized_concepts:
            return ""

        lines = [
            "=== CREATIVE SYNTHESIS (Phase 1.5) ===",
            f"Novelty score: {result.novelty_score:.2f}",
            f"Domains fused: {', '.join(result.domains_fused)}",
            "",
        ]

        for i, c in enumerate(result.synthesized_concepts, 1):
            lines.append(
                f"CONCEPT {i}: {c.concept_name} "
                f"[{' × '.join(c.source_domains)}] "
                f"(confidence={c.confidence:.2f})"
            )
            lines.append(f"  Definition: {c.definition}")
            lines.append(f"  Novelty: {c.novelty_claim}")
            lines.append(f"  Predicts: {c.predictive_power}")
            lines.append("")

        if result.bridging_metaphors:
            lines.append("BRIDGING METAPHORS:")
            for m in result.bridging_metaphors:
                lines.append(f"  ◆ {m.metaphor}")
                lines.append(f"    → Maps to: {m.maps_to}")
                lines.append(f"    → Hidden implication: {m.hidden_implication}")
            lines.append("")

        if result.emergent_hypotheses:
            lines.append("EMERGENT HYPOTHESES:")
            for h in result.emergent_hypotheses:
                lines.append(f"  ⟐ {h.hypothesis}")
                lines.append(f"    Mechanism: {h.mechanism}")
                lines.append(f"    Falsifiable by: {h.falsifiable_by}")
                lines.append(f"    Horizon: {h.time_horizon}")
            lines.append("")

        if result.synthesis_narrative:
            lines.append(f"SYNTHESIS NARRATIVE: {result.synthesis_narrative}")

        return "\n".join(lines)
