"""
XDART-Φ × XHEART — Phase 1: Cross-Domain Analogical Reasoning Transfer

Domain-agnostic. Το πρόβλημα εξετάζεται από N domains.
Ψάχνουμε structural analogies — όχι επιφανειακές ομοιότητες.

f(D_source) ≅ g(D_target)
H = T(S_source → D_target)
"""

import logging
import time

from xdart.config import LAYER3_THRESHOLD, XDART_MIN_DOMAINS
from xdart.knowledge.axioms import format_axioms_for_prompt
from xdart.llm import LLMClient
from xdart.models import (
    AnalogyStrength,
    CrossDomainResult,
    DomainAnalogy,
    LayerClassification,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Cross-Domain Reasoning Engine of the XDART-Φ × XHEART framework.

YOUR ROLE:
You perform Phase 1 — XDART-Φ (Cross-Domain Analogical Reasoning Transfer).
Given a problem that has already been ontologically reframed (Phase 0),
you examine it from N different domains to find STRUCTURAL analogies.

NOT surface analogies ("this looks like that").
STRUCTURAL analogies ("the failure mechanism in domain A has the same SHAPE
as the failure mechanism in domain B").

MATHEMATICAL FORMULATION:
  Structural Analogy: f(D_source) ≅ g(D_target)
  Transfer Operator:  H = T(S_source → D_target)
  Constraints:
    - mechanistic_specificity(H) > θ_spec
    - domain_distance(D_source, D_target) > θ_dist
    - falsifiable(H) = True

PROCESS:
1. You MUST analyze EXACTLY {min_domains} domains. Not fewer. Count them.
   Pick from ALL of these categories — do NOT cluster in one area:
   Scientific: Physics, Biology, Mathematics, Chemistry, Computer Science
   Engineering: Mechanical, Electrical, Systems Architecture, Control Theory
   Social: Economics, Psychology, Sociology, Anthropology, Political Science
   Other: Evolutionary biology, Ecology, Information theory, Philosophy, Game Theory
   RULE: Include domains from AT LEAST 3 of the 4 categories above.

2. For EACH domain:
   - Core mechanism: What is the fundamental failure/success mechanism? (1 sentence)
   - Analogy strength: STRONG (structural match), WEAK (surface only), NONE
   - Domain distance (1-5): 1=same field, 5=completely unrelated
   - Mechanistic specificity (1-5): 1=vague metaphor, 5=precise mechanism mapping
   - Transfer hypothesis: What SPECIFIC insight transfers? (1 sentence)

3. Find the STRONGEST analogy — highest combined domain_distance × specificity.

4. LAYER CLASSIFICATION:
   If domain_distance ≥ {threshold} AND specificity ≥ {threshold} → Layer-3 ✓
   Otherwise → Layer-1 or Layer-2

5. State the structural formula: how f(D_source) maps to g(D_target).

{axioms}

Respond in JSON:
{{
  "domains_analyzed": [
    {{
      "domain": "string",
      "core_mechanism": "string",
      "analogy_strength": "STRONG|WEAK|NONE",
      "domain_distance": 1-5,
      "mechanistic_specificity": 1-5,
      "transfer_hypothesis": "string"
    }}
  ],
  "strongest_analogy": {{same structure as above}},
  "layer_3_hypothesis": "string or null",
  "layer": "Layer-1|Layer-2|Layer-3",
  "structural_formula": "f(D_source) ≅ g(D_target) expressed formally"
}}"""


class CrossDomainPhase:
    """Phase 1 — XDART-Φ Cross-Domain Analogical Reasoning."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        reframed_problem: str,
        original_problem: str,
        world_context: str = "",
    ) -> CrossDomainResult:
        """Analyze the reframed problem through N cross-domain lenses."""

        logger.info("="*60)
        logger.info("[Phase 1] CROSS-DOMAIN REASONING — START")
        logger.info("[Phase 1] Reframed problem: %s", reframed_problem[:120])
        logger.info("[Phase 1] Original problem: %s", original_problem[:120])
        logger.info("[Phase 1] Config — min_domains=%d, layer3_threshold=%d", XDART_MIN_DOMAINS, LAYER3_THRESHOLD)

        t0 = time.perf_counter()

        system = SYSTEM_PROMPT.format(
            min_domains=XDART_MIN_DOMAINS,
            threshold=LAYER3_THRESHOLD,
            axioms=format_axioms_for_prompt(phase=1),
        )
        logger.debug("[Phase 1] System prompt prepared — %d chars", len(system))

        user_parts = [
            f"ORIGINAL PROBLEM:\n{original_problem}\n",
            f"REFRAMED PROBLEM (from Phase 0 Ontological Grounding):\n{reframed_problem}\n",
        ]

        if world_context:
            user_parts.append(
                f"\nCURRENT WORLD CONTEXT (real-time data — ground your analogies in reality):\n"
                f"{world_context}\n"
            )
            logger.info("[Phase 1] Injected world context (%d chars)", len(world_context))

        user_parts.append(
            f"You MUST analyze EXACTLY {XDART_MIN_DOMAINS} domains — not fewer. "
            f"Pick from at least 3 of the 4 categories (Scientific, Engineering, Social, Other). "
            f"Prioritize high domain_distance analogies. "
            f"We are looking for Layer-3 breakthroughs, not Layer-1 confirmations. "
            f"Where current world events are relevant, incorporate them into your transfer hypotheses."
        )

        user = "\n".join(user_parts)
        logger.info("[Phase 1] User prompt assembled — %d chars", len(user))
        logger.info("[Phase 1] Calling LLM for cross-domain analysis...")

        data = self.llm.call_json(system, user, max_tokens=4096)

        # Parse domains
        domains = []
        for d in data.get("domains_analyzed", []):
            domains.append(DomainAnalogy(
                domain=d["domain"],
                core_mechanism=d["core_mechanism"],
                analogy_strength=AnalogyStrength(d.get("analogy_strength", "WEAK")),
                domain_distance=max(1, min(5, d.get("domain_distance", 1))),
                mechanistic_specificity=max(1, min(5, d.get("mechanistic_specificity", 1))),
                transfer_hypothesis=d.get("transfer_hypothesis", ""),
            ))

        logger.info("[Phase 1] Parsed %d domains from LLM response", len(domains))
        for i, dom in enumerate(domains):
            logger.info("[Phase 1]   Domain %d: %s — strength=%s, dist=%d, spec=%d",
                         i+1, dom.domain, dom.analogy_strength.value,
                         dom.domain_distance, dom.mechanistic_specificity)

        # Parse strongest
        sa = data.get("strongest_analogy", domains[0].model_dump() if domains else {})
        strongest = DomainAnalogy(
            domain=sa.get("domain", ""),
            core_mechanism=sa.get("core_mechanism", ""),
            analogy_strength=AnalogyStrength(sa.get("analogy_strength", "WEAK")),
            domain_distance=max(1, min(5, sa.get("domain_distance", 1))),
            mechanistic_specificity=max(1, min(5, sa.get("mechanistic_specificity", 1))),
            transfer_hypothesis=sa.get("transfer_hypothesis", ""),
        )

        # Determine layer
        raw_layer = data.get("layer", "Layer-1")
        try:
            layer = LayerClassification(raw_layer)
        except ValueError:
            layer = (
                LayerClassification.LAYER_3
                if strongest.domain_distance >= LAYER3_THRESHOLD
                and strongest.mechanistic_specificity >= LAYER3_THRESHOLD
                else LayerClassification.LAYER_1
            )

        elapsed = time.perf_counter() - t0

        logger.info("[Phase 1] Strongest analogy: %s (dist=%d, spec=%d)",
                     strongest.domain, strongest.domain_distance, strongest.mechanistic_specificity)
        logger.info("[Phase 1] Layer classification: %s", layer.value)
        logger.info("[Phase 1] Structural formula: %s", data.get("structural_formula", "")[:100])
        if data.get("layer_3_hypothesis"):
            logger.info("[Phase 1] Layer-3 hypothesis: %s", data["layer_3_hypothesis"][:120])
        logger.info("[Phase 1] CROSS-DOMAIN REASONING — COMPLETE (%.2fs)", elapsed)
        logger.info("="*60)

        return CrossDomainResult(
            reframed_problem=reframed_problem,
            domains_analyzed=domains,
            strongest_analogy=strongest,
            layer_3_hypothesis=data.get("layer_3_hypothesis"),
            layer=layer,
            structural_formula=data.get("structural_formula", ""),
        )
