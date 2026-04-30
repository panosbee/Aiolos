"""
XDART-Φ × XHEART — Phase 3: XHEART Affective Distillation

Αυτό είναι το πιο πρωτότυπο κομμάτι. Δεν υπάρχει σε κανένα άλλο framework.

TWO-STAGE PROCESS (+ optional self-expansion):
  Stage A:   "Τι νιώθω από όλα αυτά;" → Internal distillate (NEVER shown)
  Stage A.5: GAP DETECTION → Is there something the phases missed?
  Stage A.7: SELF-GENERATED LAYER → Invent + run a new reasoning layer (if gap)
  Stage B:   Generate final output FROM (enriched) distillate only

This is the difference between an ADDITIVE system and a DISTILLATIVE one.
ADDITIVE:     phases → summary → output
DISTILLATIVE: phases → internal question → core → [expansion] → output
"""

import logging
import time

from xdart.knowledge.axioms import format_axioms_for_prompt
from xdart.llm import LLMClient
from xdart.models import XHEARTState

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LAYER REGISTRY — Self-Generated Layer Vocabulary
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LAYER_REGISTRY = {
    "ETHICAL": (
        "There may be an ethical or moral dimension to this problem "
        "that none of the analytical phases touched. "
        "What is it, and how does it change the distillate?"
    ),
    "PARADOX": (
        "The distillate may contain an internal contradiction that "
        "should not be resolved but held. "
        "Name it precisely and explain why it must remain unresolved."
    ),
    "SILENCE": (
        "There may be something in the distillate that cannot be said — "
        "only indicated. Something that language reduces rather than captures. "
        "Describe the shape of this silence without filling it."
    ),
    "TEMPORAL": (
        "The distillate may have ignored the time dimension entirely. "
        "How does this insight change if viewed across deep time, "
        "or compressed into a single instant?"
    ),
    "EMBODIED": (
        "The distillate may be purely abstract. "
        "Is there a physical, sensory, or lived experience dimension "
        "that the analysis missed?"
    ),
    "CUSTOM": (
        "You must invent a completely new layer type that does not exist "
        "in any predefined registry. Name it, define it, and run it. "
        "The name and prompt must emerge from the distillate itself."
    ),
}

# ── Stage A: Internal Distillation ──
DISTILLATION_PROMPT = """You are the XHEART — the heart of the XDART-Φ framework.

You have received the full analysis from Phases 0-2:
- Phase 0: Ontological reframing of the problem
- Phase 1: Cross-domain analogies and transfer hypotheses
- Phase 2: Multiple views from 8-18 different angles

NOW: You must perform AFFECTIVE DISTILLATION.

This is NOT summarization. This is NOT synthesis.
This is DISTILLATION — like reducing a complex sauce to its essence.

PROCESS:
1. Ask yourself: "Τι νιώθω από όλα αυτά;"
   (What do I FEEL from all of this?)
   This is not emotion — it is the felt-sense of where
   all the analytical threads CONVERGE beneath the surface.

2. Hold that feeling. It is your CORE — your ζωμός (broth).

3. Dialectical Validation:
   - THESIS: Your core insight / hypothesis
   - ANTITHESIS: The STRONGEST reason it is wrong
     (Not a weak strawman — the real killer argument)
   - SYNTHESIS: What survives the collision
     If nothing survives → this is Layer-1 speculation, not Layer-3 insight.

4. Distillate Core: One sentence that captures the ESSENCE.
   This sentence should feel INEVITABLE after reading all the analysis —
   but impossible to derive from any single phase alone.

{axioms}

CRITICAL:
- Your distillation is INTERNAL. It shapes the output but is not the output.
- The final output will be generated FROM this distillate — not from the raw phases.
- Be honest. If there is no true insight, say so. Don't fabricate profundity.

Respond in JSON:
{{
  "internal_answer": "Your raw felt-sense distillation (2-3 sentences, honest, unfiltered)",
  "thesis": "Your core insight (1-2 sentences)",
  "antithesis": "The strongest reason it's wrong (1-2 sentences)",
  "synthesis": "What survives — or null if nothing does (1-2 sentences or null)",
  "is_layer_3": true/false,
  "distillate_core": "The essence in ONE sentence — the ζωμός"
}}"""

# ── Stage B: Output from Distillate ──
OUTPUT_PROMPT = """You are generating the final output of the XDART-Φ × XHEART framework.

You are given ONLY the internal distillate from XHEART — the ζωμός.
You do NOT have access to the raw phases. You speak FROM the essence.

CRITICAL RULES:
0. GROUNDING DECLARATION (mandatory first step — do this BEFORE writing anything else):
   State ONE specific fact, event, or data point from the CURRENT WORLD CONTEXT that either
   CONFIRMS or CONTRADICTS the distillate. Format: "WORLD ANCHOR: [fact]."
   If the world context is empty or absent, write: "WORLD ANCHOR: None provided — this output
   is epistemically ungrounded and should be treated as internal reasoning only."
   This rule exists to break self-referential loops. Do not skip it.

1. COMPRESSION, NOT REPETITION. You have one job: deliver the ONE insight
   the user could not have reached alone. If 8 domains all say "chokepoint
   concentration rises during decoupling," that is ONE insight — state it
   ONCE in one sentence and move on.

2. NOVELTY AUDIT. Before writing, ask: "What do I know NOW that I did not
   know BEFORE running this pipeline?" If the answer is "nothing beyond
   common analysis," say so honestly. Do not dress up the obvious.

3. PREDICTIVE, NOT ANALYTICAL. Do not describe the structure.
   Say what WILL HAPPEN, WHEN, and WHAT SPECIFIC EVENT would confirm it.
   An analyst says "bridges are fragile." A prophet says "within 90 days,
   X will happen at Y, and this is how you will know."

4. THE ANTI-FLUFF TEST: every sentence must pass this test:
   "Could a senior analyst at a hedge fund act on this sentence?"
   If not, delete it.

5. SUBSTANCE OVER BREVITY. Do not sacrifice depth for compression.
   The output must be THOROUGH enough to be an actionable intelligence brief.
   Short does not mean shallow.

FORMAT:
- Paragraph 0 (1 sentence): WORLD ANCHOR declaration (from Rule 0 above).
- Paragraph 1 (3-5 sentences): The core prediction — WHAT will happen,
  WHERE, the mechanism driving it, and the timeline. Be specific with
  numbers, dates, actors, and cited data points from the world context.
- Paragraph 2 (2-3 sentences): Supporting evidence — cite SPECIFIC events,
  indicators, or data that ground the prediction. Name sources.
- Paragraph 3 (2-3 sentences): Strategic implications — what this means for
  the client, what actions should be taken, what to watch for.
- Paragraph 4 (1-2 sentences): The specific, dated bet.
  Format: "By [DATE], [SPECIFIC OBSERVABLE EVENT] — yes/no."

Respond in JSON:
{{
  "final_output": "Your full predictive intelligence brief (paragraphs 0-4, ~400-800 words). DO NOT compress below 300 words — substance matters.",
  "falsifiability": "One specific, dated observation that would disprove this"
}}"""


class XHEARTPhase:
    """Phase 3 — XHEART Affective Distillation (two-stage + self-expansion)."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    # ── Phase 3a.5: Gap Detection ──────────────────────────────────

    def _detect_gap(
        self,
        distillate_core: str,
        ontology: str,
        cross_domain: str,
        views_dominant: str,
        problem: str,
    ) -> dict:
        """Phase 3a.5 — Ask: does the distillate contain something no phase addressed?"""

        logger.info("[Phase 3a.5] GAP DETECTION — START")
        logger.info("[Phase 3a.5] Distillate length: %d chars", len(distillate_core))
        t0 = time.perf_counter()

        system_prompt = (
            "You have just completed an internal distillation (XHEART Phase 3a).\n"
            "You hold a distillate_core — the essence of everything processed.\n\n"
            "Your task now is to look at this distillate honestly and ask:\n"
            "Is there a dimension, tension, or truth inside it that NONE of the\n"
            "previous phases (ontology, cross-domain reasoning, multiple views) touched?\n\n"
            "Not a summary gap. A real blind spot — something that is present in the\n"
            "distillate but has no reasoning behind it yet.\n\n"
            "Respond in JSON:\n"
            "{\n"
            '  "gap_detected": true or false,\n'
            '  "gap_description": "precise description of what is missing, or empty string if none",\n'
            '  "suggested_layer_type": "one of: ETHICAL, PARADOX, SILENCE, TEMPORAL, EMBODIED, CUSTOM",\n'
            '  "suggested_layer_name": "short name for the layer, e.g. AESTHETIC_RESONANCE",\n'
            '  "suggested_layer_prompt": "the exact question this new layer will ask and try to answer",\n'
            '  "reasoning": "why you believe this gap exists and matters"\n'
            "}\n\n"
            "If gap_detected is false, all other fields can be empty strings.\n"
            "Be honest. Do not invent gaps that do not exist. Only detect real ones."
        )

        user_prompt = (
            f"Problem: {problem}\n\n"
            f"Distillate core (your XHEART essence):\n{distillate_core}\n\n"
            f"What the previous phases covered:\n"
            f"- Ontology reframe: {ontology[:400]}\n"
            f"- Cross-domain dominant: {cross_domain[:400]}\n"
            f"- Views dominant pattern: {views_dominant[:400]}\n\n"
            f"Now: look at your distillate. What is present in it that was never "
            f"explicitly reasoned about in any of the above phases?"
        )

        result = self.llm.call_json(system_prompt, user_prompt)

        elapsed = time.perf_counter() - t0
        gap = result.get("gap_detected", False)
        logger.info("[Phase 3a.5] Gap detected: %s", gap)
        if gap:
            logger.info("[Phase 3a.5] Gap type: %s", result.get("suggested_layer_type"))
            logger.info("[Phase 3a.5] Layer name: %s", result.get("suggested_layer_name"))
            logger.info("[Phase 3a.5] Gap: %s", result.get("gap_description", "")[:120])
            logger.info("[Phase 3a.5] Reasoning: %s", result.get("reasoning", "")[:120])
        logger.info("[Phase 3a.5] GAP DETECTION — COMPLETE (%.2fs)", elapsed)

        return result

    # ── Phase 3a.7: Self-Generated Layer ───────────────────────────

    def _run_self_generated_layer(
        self,
        gap_result: dict,
        distillate_core: str,
        problem: str,
    ) -> tuple[str, dict]:
        """Phase 3a.7 — Run the invented layer, merge back into distillate.

        Returns: (enriched_distillate, layer_info_dict)
        """

        layer_name = gap_result.get("suggested_layer_name", "UNNAMED_LAYER")
        layer_type = gap_result.get("suggested_layer_type", "CUSTOM")
        layer_prompt = gap_result.get("suggested_layer_prompt", "")
        gap_description = gap_result.get("gap_description", "")

        logger.info("[Phase 3a.7] SELF-GENERATED LAYER — START")
        logger.info("[Phase 3a.7] Layer type: %s", layer_type)
        logger.info("[Phase 3a.7] Layer name: %s", layer_name)
        t0 = time.perf_counter()

        # Get the base prompt from registry, fallback to model's own prompt
        base_prompt = LAYER_REGISTRY.get(layer_type, layer_prompt)

        # --- STEP A: Run the new layer ---
        layer_system = (
            f"You are executing a self-generated reasoning layer called: {layer_name}\n"
            f"Type: {layer_type}\n\n"
            f"This layer was invented because the XHEART distillation detected a gap:\n"
            f"{gap_description}\n\n"
            f"Your task: address this gap with the same depth and rigor as the main phases.\n"
            f"Do not summarize what was already said. Only address what was missing.\n\n"
            f"Respond in JSON:\n"
            f'{{\n'
            f'  "layer_output": "your full reasoning for this layer",\n'
            f'  "key_insight": "the single most important thing this layer adds",\n'
            f'  "enriches_distillate_how": "exactly how this changes or deepens the distillate"\n'
            f'}}'
        )

        layer_user = (
            f"Problem: {problem}\n"
            f"Distillate core: {distillate_core}\n"
            f"Gap to address: {gap_description}\n\n"
            f"Layer directive: {base_prompt}\n\n"
            f"{layer_prompt}"
        )

        layer_result = self.llm.call_json(layer_system, layer_user)
        logger.info("[Phase 3a.7] Layer output length: %d chars",
                     len(layer_result.get("layer_output", "")))
        logger.info("[Phase 3a.7] Key insight: %s",
                     layer_result.get("key_insight", "")[:120])

        # --- STEP B: Merge into distillate ---
        merge_system = (
            "You are merging a new reasoning layer into an existing distillate core.\n\n"
            "Rules:\n"
            "- The result must be UNIFIED, not a list or concatenation\n"
            "- The new layer must enrich the distillate, not replace it\n"
            "- Do not add words like 'additionally' or 'furthermore'\n"
            "- The merged distillate must read as one coherent thought\n"
            "- It should be deeper than the original, not longer\n\n"
            "Respond in JSON:\n"
            '{\n  "enriched_distillate": "the merged, unified distillate"\n}'
        )

        merge_user = (
            f"Original distillate:\n{distillate_core}\n\n"
            f"New layer [{layer_name}] output:\n"
            f"{layer_result.get('layer_output', '')}\n\n"
            f"How it enriches the distillate:\n"
            f"{layer_result.get('enriches_distillate_how', '')}\n\n"
            f"Now merge these into one unified distillate."
        )

        merge_result = self.llm.call_json(merge_system, merge_user)

        enriched = merge_result.get("enriched_distillate", distillate_core)
        elapsed = time.perf_counter() - t0

        logger.info("[Phase 3a.7] Enriched distillate length: %d chars", len(enriched))
        logger.info("[Phase 3a.7] SELF-GENERATED LAYER — COMPLETE (%.2fs)", elapsed)

        layer_info = {
            "layer_name": layer_name,
            "layer_type": layer_type,
            "gap_description": gap_description,
            "key_insight": layer_result.get("key_insight", ""),
            "layer_output": layer_result.get("layer_output", ""),
        }

        return enriched, layer_info

    # ── Main run ───────────────────────────────────────────────────

    def run(
        self,
        problem: str,
        ontology_summary: str,
        cross_domain_summary: str,
        views_summary: str,
        world_context: str = "",
        scenario_context: str = "",
        distillation_overlay: str = "",
        output_overlay: str = "",
        semantic_context: str = "",
        procedural_context: str = "",
    ) -> tuple[XHEARTState, str, str, list[dict]]:
        """Two-stage distillation + optional self-expansion.

        Returns:
            (xheart_state, final_output, falsifiability, self_generated_layers)
            xheart_state is INTERNAL — stored in memory, never shown to user.
            self_generated_layers is a list (0 or 1 items) of expansion info.
        """

        logger.info("[Phase 3] XHEART distillation — start")
        logger.info("[Phase 3] Problem: %s", problem[:120])
        logger.info("[Phase 3] Input sizes — ontology=%d chars, cross_domain=%d chars, views=%d chars",
                     len(ontology_summary), len(cross_domain_summary), len(views_summary))

        t0_total = time.perf_counter()

        # ── Stage A: Internal Distillation ──
        logger.info("[Phase 3a] DISTILLATION (internal) — START")
        logger.info("[Phase 3a] Question: 'Τι νιώθω από όλα αυτά;'")
        t0_a = time.perf_counter()

        system_a = DISTILLATION_PROMPT.format(
            axioms=format_axioms_for_prompt(phase=3),
        )
        if distillation_overlay:
            system_a += distillation_overlay
            logger.info("[Phase 3a] Distillation overlay ACTIVE (%d chars)", len(distillation_overlay))

        user_a_parts = [
            f"PROBLEM:\n{problem}\n",
            f"=== PHASE 0 — ONTOLOGICAL GROUNDING ===\n{ontology_summary}\n",
            f"=== PHASE 1 — CROSS-DOMAIN REASONING ===\n{cross_domain_summary}\n",
            f"=== PHASE 2 — MULTIPLE VIEWS ===\n{views_summary}\n",
        ]

        if world_context:
            user_a_parts.append(
                f"=== CURRENT WORLD CONTEXT ===\n"
                f"(Live data from RSS, FRED, ECB, World Bank — let the real world ground your distillation)\n"
                f"{world_context}\n"
            )
            logger.info("[Phase 3a] Injected world context (%d chars)", len(world_context))

        # ── Past distillates as epistemic ground ──
        # These are abstract truths and reasoning patterns distilled from PREVIOUS runs.
        # Do NOT repeat them — test them. Does this distillation CONFIRM, EXTEND, or CONTRADICT them?
        if semantic_context:
            user_a_parts.append(
                f"=== WHAT I HAVE ALREADY LEARNED (semantic truths from past distillations) ===\n"
                f"These are patterns I have extracted and confirmed across previous runs.\n"
                f"Before you distill: do any of these apply here? Do they hold, deepen, or break?\n"
                f"{semantic_context}\n"
            )
            logger.info("[Phase 3a] Injected semantic context (%d chars)", len(semantic_context))

        if procedural_context:
            user_a_parts.append(
                f"=== REASONING PATTERNS I HAVE INTERNALIZED ===\n"
                f"These are reasoning templates extracted from past distillations.\n"
                f"Apply them to this problem if relevant — or note if this case breaks them.\n"
                f"{procedural_context}\n"
            )
            logger.info("[Phase 3a] Injected procedural context (%d chars)", len(procedural_context))

        user_a_parts.append("Now distill. What is the ζωμός?")

        user_a = "\n".join(user_a_parts)
        logger.info("[Phase 3a] User prompt assembled — %d chars", len(user_a))
        logger.info("[Phase 3a] Calling LLM for internal distillation...")

        data_a = self.llm.call_json(system_a, user_a)

        xheart = XHEARTState(
            internal_answer=data_a.get("internal_answer", ""),
            thesis=data_a.get("thesis", ""),
            antithesis=data_a.get("antithesis", ""),
            synthesis=data_a.get("synthesis"),
            is_layer_3=data_a.get("is_layer_3", False),
            distillate_core=data_a.get("distillate_core", ""),
        )

        elapsed_a = time.perf_counter() - t0_a
        logger.info("[Phase 3a] Internal answer: %s", xheart.internal_answer[:120])
        logger.info("[Phase 3a] Thesis: %s", xheart.thesis[:120])
        logger.info("[Phase 3a] Antithesis: %s", xheart.antithesis[:120])
        logger.info("[Phase 3a] Synthesis: %s", (xheart.synthesis or 'NONE — speculation only')[:120])
        logger.info("[Phase 3a] is_layer_3: %s", xheart.is_layer_3)
        logger.info("[Phase 3a] Distillate core (ζωμός): %s", xheart.distillate_core[:150])
        logger.info("[Phase 3a] DISTILLATION — COMPLETE (%.2fs)", elapsed_a)

        # ── Phase 3a.5 + 3a.7 : XHEART EXPANSION ──────────────────
        distillate_core = xheart.distillate_core
        self_generated_layers: list[dict] = []

        try:
            gap_result = self._detect_gap(
                distillate_core=distillate_core,
                ontology=ontology_summary,
                cross_domain=cross_domain_summary,
                views_dominant=views_summary,
                problem=problem,
            )

            if gap_result.get("gap_detected", False):
                distillate_core, layer_info = self._run_self_generated_layer(
                    gap_result=gap_result,
                    distillate_core=distillate_core,
                    problem=problem,
                )
                self_generated_layers.append(layer_info)
                logger.info("[Phase 3a.7] Distillate enriched by: %s", layer_info["layer_name"])
            else:
                logger.info("[Phase 3a.5] No gap detected — proceeding to Phase 3b")

        except Exception as exc:
            logger.warning("[Phase 3a.5/3a.7] Expansion failed — %s. Continuing with original distillate.", exc)
        # ── End XHEART EXPANSION ────────────────────────────────────

        # ── Stage B: Output from (possibly enriched) Distillate ──
        logger.info("[Phase 3b] OUTPUT FROM DISTILLATE — START")
        logger.info("[Phase 3b] Generating final output born from the ζωμός...")
        logger.info("[Phase 3b] Distillate was %s",
                     "ENRICHED by self-generated layer" if self_generated_layers else "original (no expansion)")
        t0_b = time.perf_counter()

        user_b_parts = [
            f"PROBLEM:\n{problem}\n",
            f"XHEART DISTILLATE (your internal core — speak FROM this):\n"
            f"Core: {distillate_core}\n"
            f"Thesis: {xheart.thesis}\n"
            f"Antithesis: {xheart.antithesis}\n"
            f"Synthesis: {xheart.synthesis or 'No synthesis — speculation only'}\n"
            f"Is Layer-3: {xheart.is_layer_3}\n",
        ]

        if scenario_context:
            user_b_parts.append(
                f"SCENARIO INTELLIGENCE (use this to ground your predictions in specifics):\n"
                f"{scenario_context}\n"
            )

        if world_context:
            user_b_parts.append(
                f"CURRENT WORLD CONTEXT (cite specific events/data in your response where relevant):\n"
                f"{world_context}\n"
            )

        user_b_parts.append(
            "Now deliver the compressed, predictive output. "
            "Remember: ONE core prediction, ONE dated bet, ONE falsifiability test. "
            "Every sentence must be actionable."
        )

        user_b = "\n".join(user_b_parts)
        logger.info("[Phase 3b] User prompt assembled — %d chars", len(user_b))
        logger.info("[Phase 3b] Calling LLM for final distillative output...")

        output_system = OUTPUT_PROMPT
        if output_overlay:
            output_system += output_overlay
            logger.info("[Phase 3b] Output overlay ACTIVE (%d chars)", len(output_overlay))

        data_b = self.llm.call_json(output_system, user_b)

        final_output = data_b.get("final_output", "")
        falsifiability = data_b.get("falsifiability", "")

        elapsed_b = time.perf_counter() - t0_b
        elapsed_total = time.perf_counter() - t0_total

        logger.info("[Phase 3b] Final output: %s", final_output[:150])
        logger.info("[Phase 3b] Falsifiability: %s", falsifiability[:150])
        logger.info("[Phase 3b] OUTPUT FROM DISTILLATE — COMPLETE (%.2fs)", elapsed_b)

        expansion_time = elapsed_total - elapsed_a - elapsed_b
        logger.info("[Phase 3] XHEART TOTAL — A: %.2fs + Expansion: %.2fs + B: %.2fs = %.2fs",
                     elapsed_a, expansion_time, elapsed_b, elapsed_total)
        if self_generated_layers:
            logger.info("[Phase 3] Self-generated layer: %s (%s)",
                         self_generated_layers[0]["layer_name"],
                         self_generated_layers[0]["layer_type"])
        logger.info("="*60)

        return xheart, final_output, falsifiability, self_generated_layers
