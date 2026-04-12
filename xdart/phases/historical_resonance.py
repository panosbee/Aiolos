"""
XDART-Φ × XHEART — Phase 3.5: Historical Resonance Engine (Ιστορική Αντήχηση)

Τρέχει ΜΕΤΑ το XHEART (Phase 3).
Παίρνει ΟΛΟ το pipeline context — distillate, scenarios, tribunal, world data —
και ψάχνει ΙΣΤΟΡΙΚΑ ΠΑΡΑΛΛΗΛΑ.

Δεν χρησιμοποιεί ιστορία για framing (αυτό θα δημιουργούσε anchoring bias).
Χρησιμοποιεί ιστορία για VALIDATION — μετά που η ανάλυση έχει ολοκληρωθεί:
  "Τώρα που βλέπουμε τι λέει η ανάλυση, τι λέει η ΙΣΤΟΡΙΑ;"

Τρεις μέθοδοι αναζήτησης:
  1. Vector search στο Historical KB
  2. Structured condition matching
  3. LLM free-recall (ρωτά το LLM για παραλλήλα που δεν υπάρχουν στο KB)

Για κάθε παράλληλο: deep analysis —
  structural_match | divergence | what_happened | transfer_to_present | confidence

Τελικό: Historical Verdict — τι διδάσκει η ιστορία που η ανάλυση δεν είδε.

«Ο σοφός δεν προβλέπει — αναγνωρίζει μοτίβα.
 Η ιστορία δεν επαναλαμβάνεται, αλλά ομοιοκαταληκτεί.»  — Mark Twain (adapted)
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from xdart.knowledge.historical_kb import (
    HISTORICAL_EVENTS,
    format_event_for_prompt,
    search_by_conditions,
)
from xdart.llm import LLMClient

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONDITION_EXTRACTION_PROMPT = """You are a structural analyst. Given the full analysis context below,
extract 5-8 ABSTRACT STRUCTURAL CONDITIONS that characterize the current situation.

These are NOT specific facts — they are STRUCTURAL PATTERNS.
Good examples: "alliance_cascade", "deterrence_ambiguity", "hidden_leverage", "legitimacy_erosion"
Bad examples: "Trump is president", "oil price is $80", "inflation is 3%"

Think: What structural dynamics make this situation dangerous/important/unique?
What conditions, if present historically, would tell us something about possible trajectories?

Return JSON:
{{
  "conditions": ["condition_1", "condition_2", ...],
  "reasoning": "Brief explanation of why these conditions matter structurally"
}}"""

PARALLEL_DISCOVERY_PROMPT = """You are a historical analyst with deep knowledge of world history.

Given the following structural conditions extracted from a current analysis:
{conditions}

And the following analysis context:
{context_summary}

Identify 3-5 HISTORICAL PARALLELS that share structural similarities.
These should be real historical events/periods where similar structural conditions existed.

CRITICAL RULES:
- Focus on STRUCTURAL similarity, not surface similarity
- Include at least one parallel from before 1900
- Include at least one parallel that is NON-OBVIOUS (not the first thing everyone would think of)
- DO NOT include events already in the provided knowledge base list

Knowledge base already contains: {kb_event_names}

Return JSON:
{{
  "parallels": [
    {{
      "event": "Name of historical event/period",
      "period": "Date range",
      "structural_match": "Which structural conditions match and how",
      "relevance": "Why this parallel matters for the current analysis"
    }}
  ]
}}"""

DEEP_ANALYSIS_PROMPT = """You are a historical-structural analyst. You have been given:

1. A CURRENT SITUATION analysis (from the XDART-Φ pipeline):
{current_context}

2. A HISTORICAL PARALLEL:
{historical_event}

Your task: Perform a DEEP structural comparison. This is not casual pattern-matching.
This is rigorous structural analysis:

ANALYZE:
A) STRUCTURAL MATCH: What specific structural conditions are shared? Be precise.
   Rate the structural similarity on 0-1 scale with justification.

B) CRITICAL DIVERGENCES: What is DIFFERENT? This is equally important.
   What conditions exist now that didn't then, or vice versa?
   Rate divergence severity on 0-1 scale.

C) WHAT HAPPENED HISTORICALLY: Given those structural conditions, what trajectory
   did the historical situation follow? What were the key decision points?
   What did contemporaries fail to see?

D) TRANSFER TO PRESENT: Given the structural match AND the divergences,
   what specific insights transfer to the current situation?
   What does history suggest about likely trajectories?
   What would the historical actors wish they had known?

E) CONFIDENCE: On 0-1 scale, how much should we weight this parallel?
   A parallel with strong structural match but also strong divergences
   should have moderate confidence.

Return JSON:
{{
  "event_name": "...",
  "structural_match_score": 0.0-1.0,
  "structural_match_analysis": "Detailed analysis...",
  "divergence_score": 0.0-1.0,
  "divergence_analysis": "What's different and why it matters...",
  "historical_trajectory": "What actually happened...",
  "key_decision_points": ["point1", "point2", ...],
  "what_contemporaries_missed": "...",
  "transfer_insights": ["insight1", "insight2", ...],
  "transfer_warnings": ["warning1", "warning2", ...],
  "confidence": 0.0-1.0,
  "confidence_reasoning": "Why this confidence level..."
}}"""

HISTORICAL_VERDICT_PROMPT = """You are the Historical Resonance Engine performing final synthesis.

The XDART-Φ pipeline has completed its analysis of:
PROBLEM: {problem}
XHEART DISTILLATE: {distillate}
DOMINANT SCENARIO: {dominant_scenario}

Historical analysis has found these parallels:
{parallels_summary}

Now synthesize:

1. HISTORICAL CONSENSUS: What do the parallels collectively suggest?
   Where do multiple historical examples point in the same direction?

2. HISTORICAL WARNING: What did the CURRENT analysis MISS that history teaches?
   This is the most critical output. Be specific and actionable.

3. HISTORICAL CONFIDENCE: How much should we trust the historical parallels?
   Are they genuine structural matches or surface-level analogies?

4. WHAT HISTORY SAYS TO WATCH: Based on the parallels, what are the
   EARLY WARNING SIGNALS that would tell us which historical trajectory
   we're on? These should be checkable within 1-6 months.

5. THE PATTERN BENEATH: What is the DEEPEST structural pattern that
   connects ALL the parallels? This is the meta-lesson.

Return JSON:
{{
  "historical_consensus": "...",
  "what_analysis_missed": "...",
  "historical_warning": "...",
  "historical_confidence": 0.0-1.0,
  "confidence_reasoning": "...",
  "early_warning_signals": ["signal1", "signal2", ...],
  "pattern_beneath": "...",
  "strongest_parallel": "Name of the most relevant parallel",
  "strongest_parallel_reasoning": "Why this one matters most"
}}"""


class HistoricalResonancePhase:
    """Phase 3.5: Historical Resonance Engine.

    Runs AFTER XHEART. Takes the full pipeline context and finds
    historical parallels, then performs deep structural analysis.

    «Η ιστορία δεν σου λέει τι θα γίνει.
     Σου λέει τι έχασε η ανάλυσή σου.»
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        problem: str,
        distillate: str,
        ontology_summary: str,
        cross_domain_summary: str,
        scenario_pipeline_summary: str,
        dominant_scenario_name: str,
        tribunal_synthesis: str,
        world_context: str = "",
        working_memory_context: str = "",
    ) -> dict:
        """Run the Historical Resonance Engine.

        Returns a dict with all resonance results (parsed into a
        HistoricalResonanceResult by the caller / models layer).
        """
        t0 = time.perf_counter()

        # ── Build context summary that gets passed to all sub-prompts ──
        context_summary = self._build_context_summary(
            problem=problem,
            distillate=distillate,
            ontology_summary=ontology_summary,
            cross_domain_summary=cross_domain_summary,
            scenario_pipeline_summary=scenario_pipeline_summary,
            dominant_scenario_name=dominant_scenario_name,
            tribunal_synthesis=tribunal_synthesis,
            world_context=world_context,
            working_memory_context=working_memory_context,
        )

        # ── Step 1: Extract structural conditions ──
        logger.info("[Phase 3.5] Step 1: Extracting structural conditions...")
        conditions = self._extract_conditions(context_summary)
        logger.info("[Phase 3.5] Extracted %d conditions: %s",
                     len(conditions), conditions)

        # ── Step 2: Find parallels (3 methods in parallel) ──
        logger.info("[Phase 3.5] Step 2: Searching for historical parallels (3 methods)...")
        parallels = self._find_parallels(conditions, context_summary)
        logger.info("[Phase 3.5] Found %d historical parallels", len(parallels))

        # ── Step 3: Deep analysis per parallel (parallel LLM calls) ──
        logger.info("[Phase 3.5] Step 3: Deep analysis of %d parallels...", len(parallels))
        analyses = self._analyze_parallels(parallels, context_summary)
        logger.info("[Phase 3.5] Completed %d deep analyses", len(analyses))

        # ── Step 4: Historical Verdict ──
        logger.info("[Phase 3.5] Step 4: Synthesizing historical verdict...")
        verdict = self._synthesize_verdict(
            problem=problem,
            distillate=distillate,
            dominant_scenario_name=dominant_scenario_name,
            analyses=analyses,
        )

        elapsed = time.perf_counter() - t0
        logger.info("[Phase 3.5] Historical Resonance complete (%.2fs)", elapsed)

        return {
            "structural_conditions": conditions,
            "parallels_found": len(parallels),
            "parallel_analyses": analyses,
            "verdict": verdict,
            "elapsed_seconds": round(elapsed, 2),
        }

    def _build_context_summary(self, **kwargs) -> str:
        """Build a compact context string for sub-prompts."""
        parts = [
            f"PROBLEM: {kwargs['problem']}",
            f"\nXHEART DISTILLATE: {kwargs['distillate']}",
        ]
        if kwargs.get("ontology_summary"):
            parts.append(f"\nONTOLOGICAL FRAMING:\n{kwargs['ontology_summary'][:600]}")
        if kwargs.get("cross_domain_summary"):
            parts.append(f"\nCROSS-DOMAIN ANALYSIS:\n{kwargs['cross_domain_summary'][:600]}")
        if kwargs.get("scenario_pipeline_summary"):
            parts.append(f"\nSCENARIO PIPELINE:\n{kwargs['scenario_pipeline_summary'][:800]}")
        if kwargs.get("tribunal_synthesis"):
            parts.append(f"\nTRIBUNAL SYNTHESIS: {kwargs['tribunal_synthesis'][:400]}")
        if kwargs.get("world_context"):
            parts.append(f"\nWORLD CONTEXT:\n{kwargs['world_context'][:600]}")
        if kwargs.get("working_memory_context"):
            parts.append(f"\nWORKING MEMORY:\n{kwargs['working_memory_context'][:400]}")
        return "\n".join(parts)

    def _extract_conditions(self, context_summary: str) -> list[str]:
        """Step 1: Extract abstract structural conditions from the analysis."""
        result = self.llm.call_json(
            system_prompt=CONDITION_EXTRACTION_PROMPT,
            user_prompt=context_summary,
            temperature=0.3,
        )
        conditions = result.get("conditions", [])
        if not conditions:
            logger.warning("[Phase 3.5] No conditions extracted — using fallback")
            conditions = ["structural_change", "uncertainty", "multi_actor_dynamics"]
        return conditions[:8]

    def _find_parallels(self, conditions: list[str], context_summary: str) -> list[dict]:
        """Step 2: Find parallels via 3 methods simultaneously."""
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="hist-search") as pool:
            f_kb_match = pool.submit(self._search_kb_conditions, conditions)
            f_llm_recall = pool.submit(self._search_llm_recall, conditions, context_summary)
            f_kb_vector = pool.submit(self._search_kb_vector, context_summary)

        # Merge results, deduplicate by event name
        all_parallels: dict[str, dict] = {}

        # Method 1: Structured condition matching from KB
        kb_matches = f_kb_match.result()
        for event in kb_matches[:5]:
            key = event["id"]
            all_parallels[key] = {
                "source": "kb_condition_match",
                "event": event["event"],
                "period": event["period"],
                "category": event.get("category", ""),
                "match_count": event.get("_match_count", 0),
                "matched_conditions": event.get("_matched_conditions", []),
                "full_event": event,
            }
            logger.info("[Phase 3.5] KB condition match: %s (%d conditions)",
                        event["event"], event.get("_match_count", 0))

        # Method 2: LLM free-recall (novel parallels not in KB)
        try:
            llm_parallels = f_llm_recall.result()
            for p in llm_parallels[:3]:
                key = p.get("event", "").lower().replace(" ", "_")[:40]
                if key not in all_parallels:
                    all_parallels[key] = {
                        "source": "llm_recall",
                        "event": p.get("event", "Unknown"),
                        "period": p.get("period", "Unknown"),
                        "category": "",
                        "structural_match": p.get("structural_match", ""),
                        "relevance": p.get("relevance", ""),
                        "full_event": None,
                    }
                    logger.info("[Phase 3.5] LLM recall: %s", p.get("event", ""))
        except Exception as e:
            logger.warning("[Phase 3.5] LLM recall failed: %s", e)

        # Method 3: Vector similarity from KB
        try:
            vector_matches = f_kb_vector.result()
            for event in vector_matches[:3]:
                key = event["id"]
                if key not in all_parallels:
                    all_parallels[key] = {
                        "source": "kb_vector",
                        "event": event["event"],
                        "period": event["period"],
                        "category": event.get("category", ""),
                        "full_event": event,
                    }
                    logger.info("[Phase 3.5] KB vector match: %s", event["event"])
        except Exception as e:
            logger.warning("[Phase 3.5] KB vector search failed: %s", e)

        # Limit to top 5 parallels for deep analysis
        parallels = list(all_parallels.values())[:5]
        if not parallels:
            logger.warning("[Phase 3.5] No parallels found — returning empty")
        return parallels

    def _search_kb_conditions(self, conditions: list[str]) -> list[dict]:
        """Search KB by structural condition matching."""
        return search_by_conditions(conditions, min_match=2)

    def _search_llm_recall(self, conditions: list[str], context_summary: str) -> list[dict]:
        """Ask LLM to recall historical parallels beyond the KB."""
        kb_names = [e["event"] for e in HISTORICAL_EVENTS]
        prompt = PARALLEL_DISCOVERY_PROMPT.format(
            conditions=", ".join(conditions),
            context_summary=context_summary[:1500],
            kb_event_names=", ".join(kb_names),
        )
        result = self.llm.call_json(
            system_prompt=prompt,
            user_prompt="Find the most structurally relevant historical parallels.",
            temperature=0.5,
        )
        return result.get("parallels", [])

    def _search_kb_vector(self, context_summary: str) -> list[dict]:
        """Search KB by vector similarity using batch embeddings (single API call)."""
        try:
            query_embedding = self.llm.embed(context_summary[:2000])
        except Exception as e:
            logger.warning("[Phase 3.5] Embedding failed: %s", e)
            return []

        # Batch-embed all KB events in one API call instead of 21 individual calls
        event_texts = [format_event_for_prompt(event, include_full=False)
                       for event in HISTORICAL_EVENTS]
        try:
            event_embeddings = self.llm.embed_batch(event_texts)
        except Exception as e:
            logger.warning("[Phase 3.5] Batch embedding of KB events failed: %s", e)
            return []

        scored = []
        for i, event in enumerate(HISTORICAL_EVENTS):
            similarity = self._cosine_similarity(query_embedding, event_embeddings[i])
            scored.append((similarity, event))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [event for _, event in scored[:5]]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _analyze_parallels(self, parallels: list[dict], context_summary: str) -> list[dict]:
        """Step 3: Deep analysis of each parallel (parallel LLM calls)."""
        if not parallels:
            return []

        def _analyze_one(parallel: dict) -> dict:
            """Run deep analysis on a single parallel."""
            # Build the historical event description
            if parallel.get("full_event"):
                event_text = format_event_for_prompt(parallel["full_event"], include_full=True)
            else:
                event_text = (
                    f"Event: {parallel.get('event', 'Unknown')}\n"
                    f"Period: {parallel.get('period', 'Unknown')}\n"
                    f"Structural match: {parallel.get('structural_match', 'N/A')}\n"
                    f"Relevance: {parallel.get('relevance', 'N/A')}"
                )

            prompt = DEEP_ANALYSIS_PROMPT.format(
                current_context=context_summary[:2000],
                historical_event=event_text,
            )

            try:
                analysis = self.llm.call_json(
                    system_prompt=prompt,
                    user_prompt="Perform deep structural comparison.",
                    temperature=0.3,
                )
                analysis["source"] = parallel.get("source", "unknown")
                analysis["event_period"] = parallel.get("period", "")
                return analysis
            except Exception as e:
                logger.warning("[Phase 3.5] Deep analysis failed for %s: %s",
                               parallel.get("event", "?"), e)
                return {
                    "event_name": parallel.get("event", "Unknown"),
                    "error": str(e),
                    "confidence": 0.0,
                }

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="hist-analyze") as pool:
            analyses = list(pool.map(_analyze_one, parallels))

        # Sort by confidence (descending)
        analyses.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return analyses

    def _synthesize_verdict(
        self,
        problem: str,
        distillate: str,
        dominant_scenario_name: str,
        analyses: list[dict],
    ) -> dict:
        """Step 4: Synthesize the historical verdict."""
        if not analyses:
            return {
                "historical_consensus": "No historical parallels found.",
                "what_analysis_missed": "Cannot determine without parallels.",
                "historical_warning": "N/A",
                "historical_confidence": 0.0,
                "early_warning_signals": [],
                "pattern_beneath": "Insufficient data.",
            }

        # Build parallels summary for verdict prompt
        parallels_lines = []
        for a in analyses:
            if a.get("error"):
                continue
            parallels_lines.append(
                f"─── {a.get('event_name', '?')} ({a.get('event_period', '?')}) ───\n"
                f"  Structural match: {a.get('structural_match_score', '?')}/1.0\n"
                f"  Match: {a.get('structural_match_analysis', 'N/A')[:200]}\n"
                f"  Divergence: {a.get('divergence_score', '?')}/1.0 — {a.get('divergence_analysis', '')[:200]}\n"
                f"  Key insights: {', '.join(a.get('transfer_insights', [])[:3])}\n"
                f"  Warnings: {', '.join(a.get('transfer_warnings', [])[:3])}\n"
                f"  Confidence: {a.get('confidence', '?')}/1.0"
            )

        parallels_summary = "\n\n".join(parallels_lines) if parallels_lines else "No valid analyses."

        prompt = HISTORICAL_VERDICT_PROMPT.format(
            problem=problem,
            distillate=distillate[:500],
            dominant_scenario=dominant_scenario_name,
            parallels_summary=parallels_summary,
        )

        try:
            verdict = self.llm.call_json(
                system_prompt=prompt,
                user_prompt="Synthesize the historical verdict.",
                temperature=0.3,
            )
            return verdict
        except Exception as e:
            logger.warning("[Phase 3.5] Verdict synthesis failed: %s", e)
            return {
                "historical_consensus": "Synthesis failed.",
                "what_analysis_missed": str(e),
                "historical_warning": "Error in synthesis.",
                "historical_confidence": 0.0,
                "early_warning_signals": [],
                "pattern_beneath": "Error.",
            }
