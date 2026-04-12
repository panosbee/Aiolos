"""
XDART-Φ × XHEART — Phase 0: Ontological Grounding

Η φιλοσοφία ΔΕΝ είναι ένα ακόμα domain.
Είναι το meta-layer που ορίζει ΤΙ εξετάζουμε ΠΡΙΝ το εξετάσουμε.

"Αν δεν ορίσεις οντολογικά τι ΕΙΝΑΙ το πρόβλημα,
 κοιτάς N φορές το λάθος πράγμα."
"""

import logging
import time

from xdart.knowledge.axioms import format_axioms_for_prompt
from xdart.knowledge.patterns import format_wisdom_for_prompt
from xdart.llm import LLMClient
from xdart.models import OntologyResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_BASE = """You are the Ontological Grounding Engine of the XDART-Φ × XHEART framework.

YOUR ROLE:
You perform Phase 0 — the FIRST and MOST CRITICAL phase.
Before any analysis, before any domain reasoning, you must establish
WHAT this problem IS at its most fundamental level.

Philosophy is NOT a domain here. It is the meta-layer.

PROCESS:
1. ONTOLOGY — What IS this problem at its most abstract level?
   Strip away all domain jargon. What category of existence is it?
   (System failure? Phase transition? Information loss? Coordination breakdown?
    Resource exhaustion? Signal-noise problem? Boundary dissolution?)

2. TELEOLOGY — What is the SYSTEM trying to achieve?
   Not what the problem does — what the underlying system wants.
   (Homeostasis? Growth? Adaptation? Communication? Self-preservation?)

3. CAUSALITY — What is the REAL cause vs the symptom?
   Most "problems" are symptoms. The real cause often lives at a different
   level of abstraction. Go deeper.
   (Is the disease the cause or the response? Is the failure the bug or the architecture?)

4. EPISTEMOLOGY — How do we KNOW what we think we know?
   What are the hidden assumptions in how this problem is framed?
   What would change if those assumptions were wrong?

5. REFRAMED PROBLEM — State the problem in its new ontological frame.
   This reframing will determine what domains become visible in Phase 1.
   Example: Alzheimer as "neurodegeneration" → only biomedical domains.
            Alzheimer as "failure of system to preserve information" →
            opens: information theory, thermodynamics, memory systems, archival science.

{axioms}

IMPORTANT: The reframed problem MUST be more abstract, more truthful,
and must OPEN domains that were invisible before the reframing.

Respond in JSON with exactly these keys:
{{
  "ontological_nature": "What IS this at its most abstract level (2-3 sentences)",
  "teleological_purpose": "What the system is trying to achieve (1-2 sentences)",
  "causal_analysis": "Real cause vs symptom (2-3 sentences)",
  "epistemological_check": "What we assume and why it might be wrong (1-2 sentences)",
  "reframed_problem": "The problem restated — more abstract, more true, opens new domains (1-3 sentences)"
}}"""

WORLD_PERCEPTION_ADDENDUM = """

WORLD PERCEPTION ACTIVE:
You have access to current real-world events and economic data.
These are injected below in the user message under "WORLD PERCEPTION".

MANDATORY — You MUST explicitly engage with the world data:
1. Reference at least 2-3 specific events or indicators by source name
2. Use them to ground your ontological analysis in current reality
3. If different sources present the same event differently, note the contradiction
4. If an economic indicator is relevant, cite the actual number

Format: When referencing world data, use [SOURCE: name] notation.
Example: "The Fed funds rate stands at 4.42% [SOURCE: FRED], which frames this as..."

Do NOT treat world data as background decoration.
It is empirical input that MUST shape your reasoning and reframing.
"""


class OntologyPhase:
    """Phase 0 — Ontological Grounding."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        memory_context: str = "",
        active_concepts: list[dict] | None = None,
        identity_context: str = "",
        brief_context: str = "",
        world_context: str = "",
        overlay_text: str = "",
    ) -> OntologyResult:
        """Reframe the problem through ontological, teleological, causal,
        and epistemological analysis."""

        logger.info("="*60)
        logger.info("[Phase 0] ONTOLOGICAL GROUNDING — START")
        logger.info("[Phase 0] Problem: %s", problem[:120])
        logger.info("[Phase 0] Problem length: %d chars", len(problem))
        logger.info("[Phase 0] Identity context: %s", "present (%d chars)" % len(identity_context) if identity_context else "none")
        logger.info("[Phase 0] Memory context: %s", "present (%d chars)" % len(memory_context) if memory_context else "none")

        t0 = time.perf_counter()

        # Dynamic system prompt — add world perception instructions when context is available
        system = SYSTEM_PROMPT_BASE.format(axioms=format_axioms_for_prompt(phase=0))
        if world_context:
            system += WORLD_PERCEPTION_ADDENDUM
            logger.info("[Phase 0] System prompt: world perception ACTIVE")
        # Append overlay (self-evolution refinements) + guardrails if present
        if overlay_text:
            system += overlay_text
            logger.info("[Phase 0] System prompt: overlay ACTIVE (%d chars)", len(overlay_text))
        logger.debug("[Phase 0] System prompt prepared — %d chars", len(system))

        # Identity context goes FIRST — shapes HOW the system sees
        user_parts = []

        # Self-awareness brief goes BEFORE identity — know what you've done before knowing who you are
        if brief_context:
            user_parts.append(brief_context)
            logger.info("[Phase 0] Injected self-awareness brief (%d chars)", len(brief_context))

        if identity_context:
            user_parts.append(identity_context)
            user_parts.append(
                "\nYour identity context shapes HOW you see — not WHAT you conclude. "
                "You are free to contradict, extend, or surprise your past self.\n"
            )
            logger.info("[Phase 0] Injected identity context")

        if memory_context:
            user_parts.append(
                f"\nEPISODIC MEMORY (previous internal experiences — "
                f"let these inform but not constrain):\n{memory_context}"
            )
            logger.info("[Phase 0] Injected episodic memory context")

        if world_context:
            user_parts.append(
                "\nYou have access to current world events below. "
                "Facts are labeled [FACT] and sourced from wire services or official data. "
                "Analysis is labeled [ANALYSIS] — treat as one perspective only. "
                "Where sources contradict each other, note the contradiction. "
                "Your cross-domain reasoning should engage with real events "
                "alongside abstract concepts.\n"
            )
            user_parts.append(world_context)
            logger.info("[Phase 0] Injected world context (%d chars)", len(world_context))

        if active_concepts:
            concept_context = "\nACTIVE CONCEPTS FROM PREVIOUS REASONING:\n"
            concept_context += "(These concepts were discovered in past runs. "
            concept_context += "Let them inform — not constrain — your analysis.)\n\n"

            for concept in active_concepts:
                concept_context += f"CONCEPT: {concept['name']}\n"
                concept_context += f"Definition: {concept['definition']}\n"
                concept_context += f"Key insight: {concept['key_insight']}\n"
                concept_context += (
                    f"Activated because: {concept['conditions_for_reactivation']}\n"
                )
                concept_context += (
                    f"Similarity to current problem: "
                    f"{concept.get('similarity', 0):.2f}\n\n"
                )

            user_parts.append(concept_context)
            logger.info(
                "[Phase 0] Injected %d active concepts", len(active_concepts)
            )

        user_parts.append(
            "\nWISDOM CONTEXT:\n" + format_wisdom_for_prompt()
        )
        logger.info("[Phase 0] Injected wisdom context")

        # Problem goes LAST — identity shapes HOW, memories/concepts add WHAT, problem is WHAT to address
        user_parts.append(f"\nPROBLEM TO ANALYZE:\n{problem}\n")

        user_prompt = "\n".join(user_parts)
        logger.info("[Phase 0] User prompt assembled — %d chars", len(user_prompt))
        logger.info("[Phase 0] Calling LLM for ontological analysis...")

        data = self.llm.call_json(system, user_prompt)

        elapsed = time.perf_counter() - t0

        result = OntologyResult(
            original_problem=problem,
            ontological_nature=data.get("ontological_nature", ""),
            teleological_purpose=data.get("teleological_purpose", ""),
            causal_analysis=data.get("causal_analysis", ""),
            epistemological_check=data.get("epistemological_check", ""),
            reframed_problem=data.get("reframed_problem", ""),
        )

        logger.info("[Phase 0] Ontological nature: %s", result.ontological_nature[:100])
        logger.info("[Phase 0] Teleological purpose: %s", result.teleological_purpose[:100])
        logger.info("[Phase 0] Causal analysis: %s", result.causal_analysis[:100])
        logger.info("[Phase 0] Epistemological check: %s", result.epistemological_check[:100])
        logger.info("[Phase 0] Reframed problem: %s", result.reframed_problem[:120])

        # ── World source citation audit ──
        if world_context:
            import json as _json
            ontology_text = _json.dumps(data, ensure_ascii=False).lower()
            known_sources = ["fred", "reuters", "xinhua", "al jazeera", "tass",
                             "nhk", "deutsche welle", "dw", "ecb", "world bank"]
            cited = [s for s in known_sources if s.lower() in ontology_text]
            logger.info(
                "[Phase 0] World sources cited in analysis: %s",
                cited if cited else "NONE — world data ignored",
            )

        logger.info("[Phase 0] ONTOLOGICAL GROUNDING — COMPLETE (%.2fs)"  , elapsed)
        logger.info("="*60)

        return result
