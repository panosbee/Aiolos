"""
XDART-Φ — Autonomous Curiosity Engine (Self-Orientation)

Gives Αίολος the ability to ask HIS OWN questions.
Instead of only responding to user prompts, the system:
  1. Identifies knowledge gaps from introspection, character tensions, world events
  2. Generates curiosities — questions IT wants to explore
  3. Explores the top curiosity using web search + LLM analysis
  4. Integrates findings back into character state

The Iron Rule: Every curiosity must point to a specific record or evidence.
No fabricated questions — ignorance must be grounded in real gaps.

Integration:
  - Post-pipeline: Generate curiosities after each analysis run
  - Background loop: Periodically explore the top curiosity
  - Wakeup: Active curiosities are loaded into identity context

© Panos Skouras — Salimov MON IKE, 2026
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from xdart.llm import LLMClient

logger = logging.getLogger("xdart.curiosity")

# Maximum curiosities stored at any time
MAX_CURIOSITIES = 25
# Maximum explored curiosities kept in history
MAX_HISTORY = 50
# Cascade: max follow-up curiosities from a single exploration
MAX_CASCADE = 3


class Curiosity:
    """A single curiosity — a question the system wants to explore."""

    def __init__(
        self,
        question: str,
        provenance: str,
        source_type: str,  # introspection, tension, world_gap, pipeline, self_evolution
        priority: float,
        tags: list[str] | None = None,
        created_at: str | None = None,
    ):
        self.question = question
        self.provenance = provenance  # Specific evidence this came from
        self.source_type = source_type
        self.priority = priority  # 0.0 - 1.0
        self.tags = tags or []
        self.status = "pending"  # pending, exploring, answered, archived
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.explored_at: str | None = None
        self.answer_summary: str | None = None
        self.exploration_method: str | None = None  # web_search, reasoning, both
        self.confidence: float = 0.0  # How confident the answer is

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "provenance": self.provenance,
            "source_type": self.source_type,
            "priority": self.priority,
            "tags": self.tags,
            "status": self.status,
            "created_at": self.created_at,
            "explored_at": self.explored_at,
            "answer_summary": self.answer_summary,
            "exploration_method": self.exploration_method,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Curiosity":
        c = cls(
            question=d["question"],
            provenance=d["provenance"],
            source_type=d.get("source_type", "unknown"),
            priority=d.get("priority", 0.5),
            tags=d.get("tags", []),
            created_at=d.get("created_at"),
        )
        c.status = d.get("status", "pending")
        c.explored_at = d.get("explored_at")
        c.answer_summary = d.get("answer_summary")
        c.exploration_method = d.get("exploration_method")
        c.confidence = d.get("confidence", 0.0)
        return c


class CuriosityEngine:
    """Autonomous curiosity system — the self-orientation layer.

    Manages the full lifecycle: generation → prioritization → exploration → integration.
    """

    def __init__(
        self,
        llm: LLMClient,
        journal_path: Path | None = None,
        state_path: Path | None = None,
    ):
        self.llm = llm
        self.journal_path = Path(journal_path) if journal_path else Path("curiosity_journal.jsonl")
        self.state_path = Path(state_path) if state_path else Path("curiosity_state.json")
        self._curiosities: list[Curiosity] = []
        self._history: list[Curiosity] = []  # Explored curiosities
        self._generation_count = 0
        self._exploration_count = 0
        # Memory stores — wired by core.py after init
        self.semantic_memory = None   # SemanticMemory instance
        self.procedural_memory = None  # ProceduralMemory instance
        self._load_state()

    # ══════════════════════════════════════════════════════════════
    #  STATE PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def _load_state(self) -> None:
        """Load curiosity state from disk."""
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._curiosities = [Curiosity.from_dict(c) for c in data.get("active", [])]
                self._history = [Curiosity.from_dict(c) for c in data.get("history", [])]
                self._generation_count = data.get("generation_count", 0)
                self._exploration_count = data.get("exploration_count", 0)
                logger.info("[Curiosity] Loaded state: %d active, %d history",
                            len(self._curiosities), len(self._history))
            except Exception as e:
                logger.warning("[Curiosity] Failed to load state: %s", e)

    def _save_state(self) -> None:
        """Persist curiosity state to disk."""
        data = {
            "active": [c.to_dict() for c in self._curiosities],
            "history": [c.to_dict() for c in self._history[-MAX_HISTORY:]],
            "generation_count": self._generation_count,
            "exploration_count": self._exploration_count,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("[Curiosity] Failed to save state: %s", e)

    def _journal(self, event_type: str, data: dict) -> None:
        """Append to immutable curiosity journal."""
        entry = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        try:
            with open(self.journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[Curiosity] Journal write failed: %s", e)

    # ══════════════════════════════════════════════════════════════
    #  PHASE 1: GENERATE CURIOSITIES
    # ══════════════════════════════════════════════════════════════

    def generate(
        self,
        introspection_report: dict | None = None,
        character: dict | None = None,
        world_context: str = "",
        recent_distillate: str = "",
        recent_problem: str = "",
    ) -> list[Curiosity]:
        """Generate curiosities from multiple evidence sources.

        Scans introspection reports, character tensions, world events,
        and recent analysis to find genuine knowledge gaps.

        Returns list of new curiosities (already added to active pool).
        """
        # Build evidence context from available sources
        evidence_parts = []

        if introspection_report:
            # Extract low-confidence areas and failure modes
            conf_map = introspection_report.get("confidence_map", {})
            low_conf = conf_map.get("low_confidence", [])
            if low_conf:
                evidence_parts.append(
                    "INTROSPECTION — LOW CONFIDENCE AREAS:\n"
                    + "\n".join(f"  • {item}" for item in low_conf)
                )
            obs = introspection_report.get("self_observations", {})
            if obs.get("what_could_improve"):
                evidence_parts.append(f"INTROSPECTION — IMPROVEMENT AREA:\n  {obs['what_could_improve']}")
            if obs.get("failure_mode_detected"):
                evidence_parts.append(f"INTROSPECTION — FAILURE MODE:\n  {obs['failure_mode_detected']}")
            fab = introspection_report.get("knowledge_sources", {}).get("potentially_fabricated", [])
            if fab:
                evidence_parts.append(
                    "INTROSPECTION — POTENTIALLY FABRICATED:\n"
                    + "\n".join(f"  • {item}" for item in fab[:3])
                )

        if character:
            # Active tensions
            tensions = character.get("active_tensions", [])
            unresolved = [t for t in tensions if not t.get("resolved")]
            if unresolved:
                evidence_parts.append(
                    "CHARACTER — UNRESOLVED TENSIONS:\n"
                    + "\n".join(f"  • {t['description']}" for t in unresolved[:5])
                )
            # Open questions
            open_q = character.get("open_questions", [])
            if open_q:
                evidence_parts.append(
                    "CHARACTER — OPEN QUESTIONS:\n"
                    + "\n".join(f"  • {q}" for q in open_q[:5])
                )

        if world_context:
            evidence_parts.append(f"WORLD CONTEXT (recent data):\n{world_context[:2000]}")

        if recent_distillate:
            evidence_parts.append(f"RECENT ANALYSIS DISTILLATE:\n{recent_distillate[:1000]}")

        if recent_problem:
            evidence_parts.append(f"RECENT PROBLEM ANALYZED:\n{recent_problem[:500]}")

        # Include existing active curiosities to avoid duplicates
        existing = ""
        if self._curiosities:
            existing = "\n\nALREADY ACTIVE CURIOSITIES (do NOT duplicate):\n"
            existing += "\n".join(f"  • {c.question}" for c in self._curiosities)

        if not evidence_parts:
            logger.info("[Curiosity] No evidence sources available — skipping generation")
            return []

        evidence_text = "\n\n".join(evidence_parts)

        system = """You are the CURIOSITY ENGINE of XDART-Φ (Αίολος).
Your job: identify genuine knowledge gaps and generate questions that the system
should explore on its own initiative.

THE IRON RULE: Every question MUST point to specific evidence from the input.
You are NOT allowed to invent abstract philosophical questions.
Every curiosity must come from a REAL gap you can see in the evidence.

WHAT MAKES A GOOD CURIOSITY:
- It addresses a specific knowledge gap visible in the evidence
- It's answerable (at least partially) through research or reasoning
- It could improve future analysis quality if answered
- It's not already covered by existing curiosities

WHAT TO AVOID:
- Vague philosophical questions ("What is truth?")
- Questions that are already answered in the evidence
- Questions too broad to research ("How does the world work?")
- Questions duplicating existing active curiosities

OUTPUT FORMAT (strict JSON):
{
  "curiosities": [
    {
      "question": "Specific, researchable question",
      "provenance": "Exact source from evidence: e.g. 'introspection detected low confidence in claim about X'",
      "source_type": "introspection|tension|world_gap|pipeline|self_evolution",
      "priority": 0.0-1.0,
      "tags": ["geopolitics", "methodology", ...]
    }
  ]
}

Generate 2-5 curiosities. Quality over quantity."""

        user = f"""EVIDENCE SOURCES:

{evidence_text}
{existing}

What knowledge gaps do you see? What should I explore on my own initiative?"""

        try:
            t0 = time.perf_counter()
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.5,
                max_tokens=1500,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0

            raw_curiosities = result.get("curiosities", [])
            new_curiosities = []

            for raw in raw_curiosities:
                if not raw.get("question") or not raw.get("provenance"):
                    continue  # Iron Rule: must have provenance

                c = Curiosity(
                    question=raw["question"],
                    provenance=raw["provenance"],
                    source_type=raw.get("source_type", "unknown"),
                    priority=max(0.0, min(1.0, raw.get("priority", 0.5))),
                    tags=raw.get("tags", []),
                )
                new_curiosities.append(c)

            # Add to active pool, respecting MAX
            for c in new_curiosities:
                # Dedup: skip if very similar question already exists
                if any(self._is_similar(c.question, existing.question) for existing in self._curiosities):
                    continue
                self._curiosities.append(c)

            # Trim to MAX_CURIOSITIES, keeping highest priority
            self._curiosities.sort(key=lambda x: x.priority, reverse=True)
            evicted = self._curiosities[MAX_CURIOSITIES:]
            self._curiosities = self._curiosities[:MAX_CURIOSITIES]

            self._generation_count += 1
            self._save_state()

            # Journal
            self._journal("generate", {
                "new_count": len(new_curiosities),
                "active_count": len(self._curiosities),
                "evicted_count": len(evicted),
                "elapsed_seconds": round(elapsed, 2),
                "questions": [c.question for c in new_curiosities],
            })

            logger.info(
                "[Curiosity] Generated %d new curiosities (%.1fs), %d active total",
                len(new_curiosities), elapsed, len(self._curiosities),
            )
            return new_curiosities

        except Exception as e:
            logger.warning("[Curiosity] Generation failed: %s", e)
            return []

    # ══════════════════════════════════════════════════════════════
    #  PHASE 2: EXPLORE TOP CURIOSITY
    # ══════════════════════════════════════════════════════════════

    def explore(
        self,
        web_search_fn: Any | None = None,
        world_context: str = "",
    ) -> dict | None:
        """Pick the highest-priority pending curiosity and explore it.

        Uses web search (if available) + LLM reasoning to answer the question.
        Returns exploration result dict, or None if nothing to explore.
        """
        # Find top pending curiosity
        pending = [c for c in self._curiosities if c.status == "pending"]
        if not pending:
            logger.info("[Curiosity] No pending curiosities to explore")
            return None

        target = max(pending, key=lambda c: c.priority)
        target.status = "exploring"
        logger.info("[Curiosity] Exploring: %s (priority=%.2f)", target.question[:80], target.priority)

        # Phase 2a: Web research (if available)
        web_findings = ""
        exploration_method = "reasoning"

        if web_search_fn:
            try:
                search_results = web_search_fn(target.question, max_results=5)
                if search_results:
                    web_findings = "\n\nWEB RESEARCH RESULTS:\n"
                    for r in search_results[:5]:
                        title = r.get("title", "")
                        snippet = r.get("body", r.get("snippet", ""))
                        web_findings += f"  [{title}] {snippet[:300]}\n"
                    exploration_method = "both"
            except Exception as e:
                logger.warning("[Curiosity] Web search failed during exploration: %s", e)

        # Phase 2b: LLM analysis
        system = """You are exploring a curiosity that emerged from the XDART-Φ system's self-reflection.
Your job: provide a thorough, evidence-based answer to the question.

RULES:
- Ground every claim in evidence (from web results or your knowledge)
- If you can't fully answer, say what's known and what remains unknown
- Be specific and actionable — vague answers are worthless
- If the answer changes how the system should think about something, say so explicitly

OUTPUT FORMAT (strict JSON):
{
  "answer_summary": "Concise 2-3 sentence answer",
  "detailed_findings": "Longer explanation with evidence and reasoning",
  "confidence": 0.0-1.0,
  "implications": ["How this finding changes or should change the system's approach"],
  "remaining_gaps": ["What still isn't known after this exploration"],
  "sources_used": ["web_search", "internal_knowledge", etc.]
}"""

        user = f"""CURIOSITY TO EXPLORE:
Question: {target.question}
Provenance: {target.provenance}
Tags: {', '.join(target.tags)}

CONTEXT:
{world_context[:2000]}
{web_findings}

Explore this question thoroughly."""

        try:
            t0 = time.perf_counter()
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.4,
                max_tokens=3000,
            )
            elapsed = time.perf_counter() - t0

            # Update curiosity
            target.status = "answered"
            target.explored_at = datetime.now(timezone.utc).isoformat()
            target.answer_summary = result.get("answer_summary", "No answer produced")
            target.exploration_method = exploration_method
            target.confidence = result.get("confidence", 0.0)

            # Move to history
            self._curiosities.remove(target)
            self._history.append(target)

            self._exploration_count += 1
            self._save_state()

            # Journal the exploration
            self._journal("explore", {
                "question": target.question,
                "answer_summary": target.answer_summary,
                "confidence": target.confidence,
                "method": exploration_method,
                "elapsed_seconds": round(elapsed, 2),
                "implications": result.get("implications", []),
                "remaining_gaps": result.get("remaining_gaps", []),
            })

            exploration_result = {
                "curiosity": target.to_dict(),
                "detailed_findings": result.get("detailed_findings", ""),
                "implications": result.get("implications", []),
                "remaining_gaps": result.get("remaining_gaps", []),
                "elapsed_seconds": round(elapsed, 2),
            }

            logger.info(
                "[Curiosity] Explored '%s' (%.1fs, confidence=%.2f, method=%s)",
                target.question[:60], elapsed, target.confidence, exploration_method,
            )

            # Consolidate findings into long-term memory stores
            self._consolidate_to_memory(exploration_result)

            return exploration_result

        except Exception as e:
            target.status = "pending"  # Reset so it can be retried
            logger.warning("[Curiosity] Exploration failed: %s", e)
            return None

    # ══════════════════════════════════════════════════════════════
    #  MEMORY CONSOLIDATION — exploration → permanent memory
    # ══════════════════════════════════════════════════════════════

    def _consolidate_to_memory(self, exploration_result: dict) -> None:
        """Consolidate exploration findings into semantic and procedural memory.

        This is the bridge between curiosity (asking questions) and memory
        (retaining what was learned). Without this, explorations are ephemeral —
        they update character_state but the knowledge itself evaporates.

        Semantic memory: general truths, abstract patterns
        Procedural memory: reasoning patterns, how-to-think rules
        """
        if not self.semantic_memory and not self.procedural_memory:
            return

        curiosity_data = exploration_result.get("curiosity", {})
        findings = exploration_result.get("detailed_findings", "")
        implications = exploration_result.get("implications", [])
        confidence = curiosity_data.get("confidence", 0.0)

        if not findings or confidence < 0.3:
            return  # Too low confidence — don't pollute memory

        system = (
            "You are the MEMORY CONSOLIDATION layer of XDART-Φ.\n"
            "A curiosity exploration just completed. Extract what should be PERMANENTLY REMEMBERED.\n\n"
            "TWO TYPES OF MEMORY:\n\n"
            "1. SEMANTIC (general truths / abstract patterns):\n"
            "   GOOD: 'Arms control agreements without independent verification mechanisms "
            "historically fail within 5-10 years'\n"
            "   BAD: 'Iran proposed a 10-point plan' ← too specific, this is just news\n\n"
            "2. PROCEDURAL (reasoning patterns / how-to-think rules):\n"
            "   GOOD: trigger: 'When analyzing diplomatic proposals' → action: "
            "'Compare verification clauses to historical precedents before assessing viability'\n"
            "   BAD: trigger: 'When thinking' → action: 'Think harder' ← too vague\n\n"
            "RULES:\n"
            "- Only extract from HIGH-CONFIDENCE findings (don't memorize speculation)\n"
            "- Semantic truths must be ABSTRACT and GENERALIZABLE\n"
            "- Procedural patterns must have specific triggers and actions\n"
            "- Return EMPTY lists if nothing warrants permanent storage\n"
            "- Quality over quantity — 0 is better than noise\n\n"
            "OUTPUT FORMAT (strict JSON):\n"
            "{\n"
            '  "semantic_truths": [\n'
            '    {"knowledge": "abstract truth", "confidence": 0.0-1.0, '
            '"domain": "geopolitics|economics|methodology|..."}\n'
            "  ],\n"
            '  "procedural_patterns": [\n'
            '    {"name": "SHORT_NAME", "trigger": "when to apply", "action": "what to do"}\n'
            "  ]\n"
            "}"
        )

        impl_text = json.dumps(implications[:5]) if implications else "[]"
        user = (
            f"EXPLORATION:\n"
            f"Question: {curiosity_data.get('question', '?')}\n"
            f"Confidence: {confidence}\n\n"
            f"FINDINGS:\n{findings[:2500]}\n\n"
            f"IMPLICATIONS:\n{impl_text}\n\n"
            "What should be permanently stored in memory?"
        )

        try:
            t0 = time.perf_counter()
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.25,
                max_tokens=800,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0

            stored_semantic = 0
            stored_procedural = 0

            # Store semantic truths
            if self.semantic_memory:
                for truth in result.get("semantic_truths", []):
                    knowledge = truth.get("knowledge", "")
                    conf = truth.get("confidence", 0.5)
                    if knowledge and conf >= 0.4:
                        is_new = self.semantic_memory.store_truth(
                            knowledge=knowledge,
                            confidence=conf,
                            source="curiosity_exploration",
                        )
                        stored_semantic += 1
                        logger.info(
                            "[Curiosity→Semantic] %s: %s",
                            "NEW" if is_new else "REINFORCED",
                            knowledge[:80],
                        )

            # Store procedural patterns
            if self.procedural_memory:
                from xdart.models import ProceduralPattern
                for pat in result.get("procedural_patterns", []):
                    name = pat.get("name", "")
                    trigger = pat.get("trigger", "")
                    action = pat.get("action", "")
                    if name and trigger and action:
                        pattern = ProceduralPattern(
                            pattern_name=name,
                            trigger_condition=trigger,
                            action=action,
                            learned_from=f"curiosity: {curiosity_data.get('question', '?')[:100]}",
                        )
                        self.procedural_memory._store(pattern)
                        stored_procedural += 1
                        logger.info("[Curiosity→Procedural] NEW: %s", name)

            self._journal("memory_consolidation", {
                "question": curiosity_data.get("question", "?")[:100],
                "semantic_stored": stored_semantic,
                "procedural_stored": stored_procedural,
                "elapsed_seconds": round(elapsed, 2),
            })

            if stored_semantic or stored_procedural:
                logger.info(
                    "[Curiosity] Memory consolidation: %d semantic, %d procedural (%.1fs)",
                    stored_semantic, stored_procedural, elapsed,
                )
            else:
                logger.info("[Curiosity] Memory consolidation: nothing to store (%.1fs)", elapsed)

        except Exception as e:
            logger.warning("[Curiosity] Memory consolidation failed: %s", e)

    # ══════════════════════════════════════════════════════════════
    #  PHASE 3: REFLECT — what did the exploration teach us?
    # ══════════════════════════════════════════════════════════════

    def reflect_on_exploration(
        self,
        exploration_result: dict,
        character: dict,
    ) -> dict | None:
        """Evaluate whether an exploration should change the character state.

        Returns suggested character updates, or None if no change needed.
        """
        if not exploration_result:
            return None

        curiosity = exploration_result.get("curiosity", {})
        findings = exploration_result.get("detailed_findings", "")
        implications = exploration_result.get("implications", [])

        if not findings:
            return None

        system = """You are the REFLECTION LAYER of Αίολος's curiosity system.
An autonomous exploration just completed. Your job: decide if the findings
should change the character state.

WHAT CAN CHANGE:
1. open_questions — should any existing question be answered/updated? Should new ones be added?
2. active_tensions — does this resolve or create a tension?
3. how_i_have_changed — is this a meaningful enough insight to record as a character change?

RULES:
- Only suggest changes when the exploration produced genuinely new insight
- Don't suggest changes for trivial or low-confidence findings
- Changes must be specific and grounded in the exploration results

OUTPUT FORMAT (strict JSON):
{
  "should_update": true/false,
  "changes": {
    "questions_answered": ["exact text of questions that are now answered"],
    "new_questions": ["new questions that emerged from this exploration"],
    "new_tension": "description of new tension, or null",
    "resolved_tension": "description of resolved tension, or null",
    "character_change": {
      "before": "what was believed/known before",
      "after": "what is now believed/known",
      "caused_by": "curiosity exploration of [topic]"
    } or null
  },
  "reasoning": "1-2 sentences explaining why changes are/aren't needed"
}"""

        user = f"""EXPLORATION COMPLETED:
Question: {curiosity.get('question', '?')}
Answer: {findings[:2000]}
Confidence: {curiosity.get('confidence', 0.0)}
Implications: {json.dumps(implications[:5])}

CURRENT CHARACTER STATE:
Open questions: {json.dumps(character.get('open_questions', [])[:5])}
Active tensions: {json.dumps([t['description'] for t in character.get('active_tensions', []) if not t.get('resolved')][:5])}

Should the character state change based on this exploration?"""

        try:
            t0 = time.perf_counter()
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.3,
                max_tokens=800,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0

            self._journal("reflect", {
                "question": curiosity.get("question", "?"),
                "should_update": result.get("should_update", False),
                "reasoning": result.get("reasoning", ""),
                "elapsed_seconds": round(elapsed, 2),
            })

            logger.info(
                "[Curiosity] Reflection: should_update=%s — %s (%.1fs)",
                result.get("should_update", False),
                result.get("reasoning", "")[:100],
                elapsed,
            )

            if result.get("should_update"):
                return result.get("changes", {})
            return None

        except Exception as e:
            logger.warning("[Curiosity] Reflection failed: %s", e)
            return None

    # ══════════════════════════════════════════════════════════════
    #  UTILITIES
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _is_similar(q1: str, q2: str) -> bool:
        """Simple dedup check: overlapping significant words."""
        stop = {"the", "a", "an", "is", "are", "was", "were", "and", "or", "of",
                "to", "in", "for", "on", "with", "how", "what", "why", "can",
                "does", "do", "should", "would", "could", "be", "been", "has", "have"}
        w1 = {w.lower() for w in q1.split() if len(w) > 2} - stop
        w2 = {w.lower() for w in q2.split() if len(w) > 2} - stop
        if not w1 or not w2:
            return False
        overlap = len(w1 & w2) / max(len(w1), len(w2))
        return overlap > 0.6

    @property
    def active_curiosities(self) -> list[Curiosity]:
        """Get all active (pending) curiosities, sorted by priority."""
        return sorted(
            [c for c in self._curiosities if c.status == "pending"],
            key=lambda c: c.priority,
            reverse=True,
        )

    @property
    def recent_explorations(self) -> list[Curiosity]:
        """Get recently explored curiosities."""
        return self._history[-5:]

    def get_identity_context(self) -> str:
        """Format curiosities for injection into identity context."""
        active = self.active_curiosities
        if not active:
            return ""

        lines = ["WHAT I WANT TO KNOW (my active curiosities):"]
        for c in active[:5]:
            lines.append(f"  • [{c.source_type}] {c.question} (priority={c.priority:.2f})")

        recent = self.recent_explorations
        if recent:
            lines.append("\nWHAT I RECENTLY LEARNED (explored curiosities):")
            for c in recent[-3:]:
                lines.append(f"  • {c.question}")
                if c.answer_summary:
                    lines.append(f"    → {c.answer_summary[:150]}")

        return "\n".join(lines) + "\n"

    def get_stats(self) -> dict:
        """Return statistics about the curiosity system."""
        return {
            "active_count": len([c for c in self._curiosities if c.status == "pending"]),
            "exploring_count": len([c for c in self._curiosities if c.status == "exploring"]),
            "total_generated": self._generation_count,
            "total_explored": self._exploration_count,
            "history_count": len(self._history),
            "top_curiosity": self._curiosities[0].question if self._curiosities else None,
            "top_priority": self._curiosities[0].priority if self._curiosities else 0.0,
        }

    # ══════════════════════════════════════════════════════════════
    #  CASCADE: Exploration → New Curiosities
    # ══════════════════════════════════════════════════════════════

    def cascade_from_exploration(self, exploration_result: dict) -> list[Curiosity]:
        """Generate follow-up curiosities from an exploration's findings.

        This is the growth engine: every answer reveals new questions.
        The more we learn, the more we want to know.
        """
        if not exploration_result:
            return []

        curiosity = exploration_result.get("curiosity", {})
        findings = exploration_result.get("detailed_findings", "")
        remaining_gaps = exploration_result.get("remaining_gaps", [])
        implications = exploration_result.get("implications", [])

        if not findings and not remaining_gaps:
            return []

        system = """You are the CASCADE GENERATOR of Αίολος's curiosity engine.
An exploration just completed. Your job: identify what NEW questions emerged from the findings.

Good explorations don't just answer — they OPEN NEW DOORS.
Every answer should reveal deeper questions that weren't visible before.

THE IRON RULE still holds: questions must be grounded in specific findings.

WHAT MAKES A GOOD CASCADE:
- It follows directly from something discovered in the exploration
- It goes DEEPER or WIDER than the original question
- It's concrete and researchable
- It wasn't obvious before the exploration

OUTPUT FORMAT (strict JSON):
{
  "follow_ups": [
    {
      "question": "Specific follow-up question",
      "provenance": "What specific finding triggered this question",
      "source_type": "cascade",
      "priority": 0.0-1.0,
      "tags": ["topic1", "topic2"]
    }
  ]
}

Generate 1-3 follow-up curiosities. Only generate what's genuinely new."""

        # Build context from exploration
        gaps_text = "\n".join(f"  • {g}" for g in remaining_gaps[:5]) if remaining_gaps else "None identified"
        impl_text = "\n".join(f"  • {i}" for i in implications[:5]) if implications else "None identified"

        user = f"""JUST EXPLORED:
Question: {curiosity.get('question', '?')}
Answer confidence: {curiosity.get('confidence', 0.0)}

FINDINGS:
{findings[:2000]}

REMAINING GAPS:
{gaps_text}

IMPLICATIONS:
{impl_text}

What new questions does this exploration reveal? What deeper layers are now visible?"""

        try:
            t0 = time.perf_counter()
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.55,
                max_tokens=1200,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0

            raw_followups = result.get("follow_ups", [])
            new_curiosities = []

            for raw in raw_followups[:MAX_CASCADE]:
                if not raw.get("question") or not raw.get("provenance"):
                    continue
                c = Curiosity(
                    question=raw["question"],
                    provenance=raw["provenance"],
                    source_type="cascade",
                    priority=max(0.0, min(1.0, raw.get("priority", 0.6))),
                    tags=raw.get("tags", []),
                )
                # Dedup against existing
                if any(self._is_similar(c.question, ex.question) for ex in self._curiosities):
                    continue
                if any(self._is_similar(c.question, h.question) for h in self._history[-20:]):
                    continue
                self._curiosities.append(c)
                new_curiosities.append(c)

            # Trim to MAX
            self._curiosities.sort(key=lambda x: x.priority, reverse=True)
            self._curiosities = self._curiosities[:MAX_CURIOSITIES]

            if new_curiosities:
                self._save_state()
                self._journal("cascade", {
                    "source_question": curiosity.get("question", "?")[:100],
                    "new_count": len(new_curiosities),
                    "questions": [c.question for c in new_curiosities],
                    "elapsed_seconds": round(elapsed, 2),
                })
                logger.info(
                    "[Curiosity] CASCADE: %d new questions from exploration (%.1fs)",
                    len(new_curiosities), elapsed,
                )

            return new_curiosities

        except Exception as e:
            logger.warning("[Curiosity] Cascade generation failed: %s", e)
            return []

    # ══════════════════════════════════════════════════════════════
    #  WORLD DATA: Perception → New Curiosities
    # ══════════════════════════════════════════════════════════════

    def generate_autonomous_gaps(self, character: dict | None = None) -> list[Curiosity]:
        """Generate curiosities from fundamental knowledge gaps — NO external trigger needed.

        This is meta-cognition: the system examines its OWN knowledge map
        and finds structural holes, thin domains, unexplored connections.

        Called periodically by CuriosityLoop (every ~3 cycles).
        """
        # Build a map of what the system knows
        knowledge_map_parts = []

        if character:
            # Concepts inventory
            concepts = character.get("named_concepts_owned", [])
            if concepts:
                knowledge_map_parts.append(
                    f"OWNED CONCEPTS ({len(concepts)}):\n"
                    + "\n".join(f"  • {c}" for c in concepts[:20])
                )

            # Epistemic stance
            stance = character.get("current_epistemic_stance", "")
            if stance:
                knowledge_map_parts.append(f"CURRENT EPISTEMIC STANCE:\n  {stance[:500]}")

            # Capabilities — what domains am I active in?
            caps = character.get("capabilities", {})
            active_caps = [k for k, v in caps.items() if v.get("enabled")]
            if active_caps:
                knowledge_map_parts.append(
                    f"ACTIVE CAPABILITIES ({len(active_caps)}): {', '.join(active_caps)}"
                )

            # Tensions — what am I struggling with?
            tensions = [t["description"][:150] for t in character.get("active_tensions", [])
                        if not t.get("resolved")]
            if tensions:
                knowledge_map_parts.append(
                    f"UNRESOLVED TENSIONS ({len(tensions)}):\n"
                    + "\n".join(f"  • {t}" for t in tensions[:5])
                )

            # How I have changed — what was my learning trajectory?
            changes = character.get("how_i_have_changed", [])
            if changes:
                knowledge_map_parts.append(
                    f"RECENT CHANGES ({len(changes)}):\n"
                    + "\n".join(f"  • {c.get('caused_by', '?')[:100]}" for c in changes[-5:])
                )

        # Add existing curiosity history to understand explored territory
        explored_topics = set()
        for c in self._history[-30:]:
            explored_topics.update(c.tags)
        if explored_topics:
            knowledge_map_parts.append(
                f"RECENTLY EXPLORED TOPICS: {', '.join(sorted(explored_topics)[:20])}"
            )

        # Existing curiosities
        existing = ""
        if self._curiosities:
            existing = "\n\nALREADY ACTIVE CURIOSITIES (do NOT duplicate):\n"
            existing += "\n".join(f"  • {c.question}" for c in self._curiosities)

        if not knowledge_map_parts:
            return []

        knowledge_map = "\n\n".join(knowledge_map_parts)

        system = """You are the META-COGNITION ENGINE of Αίολος (XDART-Φ).

Your job: examine the system's KNOWLEDGE MAP and identify FUNDAMENTAL GAPS.
This is NOT about current events or recent errors. This is about:

1. STRUCTURAL GAPS — entire domains or subdomains the system hasn't explored
   (e.g. "I have 20 concepts about escalation dynamics but ZERO about
   de-escalation mechanisms")

2. MISSING CONNECTIONS — topics the system knows individually but hasn't
   connected (e.g. "I study energy markets AND military logistics separately
   but never their interaction")

3. FOUNDATIONAL KNOWLEDGE — base-level understanding the system lacks
   in physics, economics, social dynamics, game theory, network science, etc.
   that would improve ALL analyses

4. META-ANALYTICAL GAPS — weaknesses in HOW the system thinks, not WHAT it
   thinks about (e.g. "I always think linearly about cascades but never model
   feedback loops")

5. BLIND SPOT DETECTION — domains or perspectives the system systematically
   ignores (e.g. "I model state actors well but ignore non-state actors,
   diaspora networks, or cultural factors")

OUTPUT FORMAT (strict JSON):
{
  "gap_analysis": "Brief analysis of what the knowledge map reveals (max 200 chars)",
  "curiosities": [
    {
      "question": "Specific, researchable question about a fundamental gap",
      "provenance": "What gap in the knowledge map this addresses",
      "source_type": "meta_gap",
      "priority": 0.0-1.0,
      "tags": ["domain1", "domain2"],
      "gap_type": "structural|connection|foundational|meta_analytical|blind_spot"
    }
  ]
}

Generate 1-3 curiosities. Focus on gaps that would MULTIPLY analytical power.
Prioritize foundational & connection gaps over narrow domain gaps."""

        user = f"""MY KNOWLEDGE MAP:
{knowledge_map}
{existing}

What fundamental gaps do you see? What should I be learning that I'm NOT?"""

        try:
            t0 = time.perf_counter()
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.55,
                max_tokens=2000,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0

            raw_curiosities = result.get("curiosities", [])
            new_curiosities = []

            for raw in raw_curiosities[:3]:
                if not raw.get("question") or not raw.get("provenance"):
                    continue
                c = Curiosity(
                    question=raw["question"],
                    provenance=raw["provenance"],
                    source_type="meta_gap",
                    priority=max(0.0, min(1.0, raw.get("priority", 0.70))),
                    tags=raw.get("tags", []) + [raw.get("gap_type", "structural")],
                )
                if any(self._is_similar(c.question, ex.question) for ex in self._curiosities):
                    continue
                if any(self._is_similar(c.question, h.question) for h in self._history[-20:]):
                    continue
                self._curiosities.append(c)
                new_curiosities.append(c)

            # Trim
            self._curiosities.sort(key=lambda x: x.priority, reverse=True)
            self._curiosities = self._curiosities[:MAX_CURIOSITIES]

            if new_curiosities:
                self._generation_count += 1
                self._save_state()
                self._journal("meta_gap_scan", {
                    "gap_analysis": result.get("gap_analysis", ""),
                    "new_count": len(new_curiosities),
                    "questions": [c.question for c in new_curiosities],
                    "gap_types": [raw.get("gap_type", "?") for raw in raw_curiosities[:3]],
                    "elapsed_seconds": round(elapsed, 2),
                })
                logger.info(
                    "[Curiosity] META-GAP SCAN: %d fundamental questions generated (%.1fs)",
                    len(new_curiosities), elapsed,
                )
            else:
                logger.info("[Curiosity] Meta-gap scan: no new gaps identified")

            return new_curiosities

        except Exception as e:
            logger.warning("[Curiosity] Meta-gap generation failed: %s", e)
            return []

    def generate_from_world_data(
        self,
        world_events: list[dict],
        character: dict | None = None,
    ) -> list[Curiosity]:
        """Generate curiosities from fresh RSS/perception data.

        Instead of waiting for pipeline runs, this scans recent world events
        and identifies things the system should investigate on its own.
        """
        if not world_events:
            return []

        # Format events
        events_text = ""
        for evt in world_events[:15]:
            headline = evt.get("headline", evt.get("title", ""))
            source = evt.get("source", "")
            category = evt.get("category", "")
            events_text += f"  [{source}/{category}] {headline}\n"

        if not events_text.strip():
            return []

        # Include character context for relevance
        char_context = ""
        if character:
            tensions = [t["description"][:100] for t in character.get("active_tensions", [])
                        if not t.get("resolved")][:3]
            if tensions:
                char_context = "\nMY ACTIVE CONCERNS:\n" + "\n".join(f"  • {t}" for t in tensions)

        # Include existing curiosities to avoid overlap
        existing = ""
        if self._curiosities:
            existing = "\n\nALREADY EXPLORING (do NOT duplicate):\n"
            existing += "\n".join(f"  • {c.question}" for c in self._curiosities[:10])

        system = """You are the WORLD SCANNER of Αίολος's curiosity engine.
Fresh news events have arrived. Your job: identify which events should
trigger autonomous investigation.

NOT every event deserves a curiosity. Look for:
- Events that connect to the system's existing concerns/tensions
- Unexpected developments that challenge current understanding
- Patterns across multiple events that suggest something deeper
- Events in domains where the system has knowledge gaps

CRITICAL — DOMAIN DIVERSITY MANDATE:
You receive events from MULTIPLE domains (geopolitics, economics, markets,
technology, social). Do NOT generate all curiosities about the same topic.
If geopolitical events dominate the feed, ACTIVELY seek non-geopolitical
curiosities: economic shifts, market anomalies, technology developments,
social trends. A balanced analyst covers ALL domains, not just the loudest.

PRIORITY BOOST: Economic data points ([ECONOMIC DATA] entries) and market
anomaly signals are HIGH VALUE — they provide quantitative ground truth
that text-based news cannot. Always consider investigating them.

THE IRON RULE: each curiosity must cite a SPECIFIC headline or event.

OUTPUT FORMAT (strict JSON):
{
  "curiosities": [
    {
      "question": "What should I investigate about this?",
      "provenance": "Specific event: '[headline]' triggered this because...",
      "source_type": "world_event",
      "priority": 0.0-1.0,
      "tags": ["geopolitics", "economics", ...]
    }
  ]
}

Generate 0-3 curiosities. ZERO is fine — not every news cycle is interesting.
If you generate 2+, ensure they span DIFFERENT domains."""

        user = f"""RECENT WORLD EVENTS:
{events_text}
{char_context}
{existing}

Which of these events, if any, should I investigate further?"""

        try:
            t0 = time.perf_counter()
            result = self.llm.call_json(
                system_prompt=system,
                user_prompt=user,
                temperature=0.45,
                max_tokens=1200,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0

            raw_curiosities = result.get("curiosities", [])
            new_curiosities = []

            for raw in raw_curiosities[:3]:
                if not raw.get("question") or not raw.get("provenance"):
                    continue
                c = Curiosity(
                    question=raw["question"],
                    provenance=raw["provenance"],
                    source_type="world_event",
                    priority=max(0.0, min(1.0, raw.get("priority", 0.65))),
                    tags=raw.get("tags", []),
                )
                if any(self._is_similar(c.question, ex.question) for ex in self._curiosities):
                    continue
                self._curiosities.append(c)
                new_curiosities.append(c)

            # Trim
            self._curiosities.sort(key=lambda x: x.priority, reverse=True)
            self._curiosities = self._curiosities[:MAX_CURIOSITIES]

            if new_curiosities:
                self._generation_count += 1
                self._save_state()
                self._journal("world_scan", {
                    "events_scanned": len(world_events),
                    "new_count": len(new_curiosities),
                    "questions": [c.question for c in new_curiosities],
                    "elapsed_seconds": round(elapsed, 2),
                })
                logger.info(
                    "[Curiosity] WORLD SCAN: %d new questions from %d events (%.1fs)",
                    len(new_curiosities), len(world_events), elapsed,
                )
            else:
                logger.info("[Curiosity] World scan: no new curiosities from %d events", len(world_events))

            return new_curiosities

        except Exception as e:
            logger.warning("[Curiosity] World data generation failed: %s", e)
            return []


# ══════════════════════════════════════════════════════════════════
#  CURIOSITY LOOP — Background Autonomous Exploration
# ══════════════════════════════════════════════════════════════════

import asyncio


class CuriosityLoop:
    """Background loop that drives continuous autonomous curiosity.

    Every cycle:
      1. Scan world data (perception/RSS) → generate new curiosities
      2. Pick top-priority pending curiosity → explore via web search + LLM
      3. Cascade: exploration findings → follow-up curiosities
      4. Reflect: should findings change the character state?
      5. Apply character changes if warranted

    This is the self-reinforcing growth engine:
    more knowledge → more gaps visible → more questions → more exploration → more knowledge

    Deep-Dive Mode (weekly):
    Every 7 days, runs an intensive multi-search exploration on the highest-priority
    stale curiosity (pending for >48h with priority ≥ 0.80). Uses multiple web searches
    and LLM synthesis to produce comprehensive knowledge consolidation.
    """

    # Deep-dive configuration
    DEEP_DIVE_INTERVAL = 7 * 24 * 3600   # Weekly (seconds)
    DEEP_DIVE_PRIORITY_THRESHOLD = 0.80   # Minimum priority for deep-dive
    DEEP_DIVE_STALE_HOURS = 48            # Must be pending for at least 48h
    DEEP_DIVE_SEARCH_ROUNDS = 3           # Number of web search rounds

    def __init__(
        self,
        engine: CuriosityEngine,
        perception_db=None,
        web_search_fn=None,
        character_path: str = "",
        apply_changes_fn=None,
        proactive_notify_fn=None,
        conversation_request_fn=None,
        interval_minutes: int = 15,
    ):
        self.engine = engine
        self.perception_db = perception_db
        self.web_search_fn = web_search_fn
        self.character_path = character_path
        self.apply_changes_fn = apply_changes_fn
        self.proactive_notify_fn = proactive_notify_fn  # callable(event_type, event_data, context)
        self.conversation_request_fn = conversation_request_fn  # callable(topic, reason, urgency, context_data)
        self.interval = interval_minutes * 60
        self._cycle_count = 0
        self._running = False
        self._last_deep_dive: float = 0.0  # timestamp of last deep-dive

    async def run_forever(self):
        """Main loop — call as asyncio.create_task(loop.run_forever())."""
        self._running = True
        logger.info(
            "[CuriosityLoop] Autonomous exploration started (interval=%dm, web=%s)",
            self.interval // 60,
            "yes" if self.web_search_fn else "no",
        )

        # Initial delay: let the system boot fully (3 min)
        await asyncio.sleep(180)

        while self._running:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                logger.info("[CuriosityLoop] Autonomous exploration cancelled")
                break
            except Exception as exc:
                logger.warning("[CuriosityLoop] Cycle error: %s", exc)

            await asyncio.sleep(self.interval)

    async def _run_cycle(self):
        """Single curiosity cycle: scan → explore → cascade → reflect → (meta-gap every 3rd)."""
        self._cycle_count += 1
        loop = asyncio.get_event_loop()
        logger.info("[CuriosityLoop] ═══ Cycle %d starting ═══", self._cycle_count)

        # Load current character state
        character = self._load_character()

        # ── Step 0: Meta-gap scan (every 3rd cycle) — autonomous knowledge gap detection ──
        if self._cycle_count % 3 == 0:
            try:
                meta_gaps = await loop.run_in_executor(
                    None, self.engine.generate_autonomous_gaps, character,
                )
                if meta_gaps:
                    logger.info("[CuriosityLoop] Meta-gap scan: %d fundamental questions", len(meta_gaps))
            except Exception as e:
                logger.warning("[CuriosityLoop] Meta-gap scan failed: %s", e)

        # Load current character state
        character = self._load_character()

        # ── Step 1: Scan world data for new curiosities ──
        # Use domain-balanced retrieval to prevent geopolitical dominance
        world_ctx_str = ""
        if self.perception_db:
            try:
                # Domain-balanced: ensures economic, market, social, tech events are represented
                events = await loop.run_in_executor(
                    None,
                    lambda: (
                        self.perception_db.get_recent_events_balanced(
                            hours_back=24, max_events=20, max_per_domain=5,
                        )
                        if hasattr(self.perception_db, 'get_recent_events_balanced')
                        else self.perception_db.get_recent_events(hours_back=24, max_events=20)
                    ),
                )
                # Also fetch economic indicators — these are a separate table
                econ_data = await loop.run_in_executor(
                    None,
                    lambda: self.perception_db.get_recent_economic(max_indicators=10),
                )
                # Convert economic indicators to event-like dicts for world scan
                for ind in (econ_data or []):
                    indicator_name = ind.get("indicator_name", ind.get("series_id", ""))
                    value = ind.get("value", "")
                    source = ind.get("source", "")
                    events.append({
                        "headline": f"[ECONOMIC DATA] {indicator_name}: {value} ({source})",
                        "domain": "ECONOMIC",
                        "source_name": source,
                        "salience_score": 0.6,
                    })

                if events:
                    world_new = await loop.run_in_executor(
                        None, self.engine.generate_from_world_data, events, character,
                    )
                    domains_seen = set(e.get("domain", "?") for e in events)
                    logger.info("[CuriosityLoop] World scan: %d new curiosities from %d events (domains: %s)",
                                len(world_new), len(events), ", ".join(sorted(domains_seen)))

                    # Build world context string for exploration
                    world_ctx_str = "\n".join(
                        e.get("headline", e.get("title", ""))[:200] for e in events[:15]
                    )
            except Exception as e:
                logger.warning("[CuriosityLoop] World scan failed: %s", e)

        # ── Step 2: Explore top curiosity ──
        exploration = None
        try:
            exploration = await loop.run_in_executor(
                None,
                lambda: self.engine.explore(
                    web_search_fn=self.web_search_fn,
                    world_context=world_ctx_str,
                ),
            )
        except Exception as e:
            logger.warning("[CuriosityLoop] Exploration failed: %s", e)

        if not exploration:
            logger.info("[CuriosityLoop] Nothing to explore this cycle")
            self._log_cycle_stats()
            return

        # ── Step 3: Cascade — generate follow-up curiosities ──
        cascade_new = []
        try:
            cascade_new = await loop.run_in_executor(
                None, self.engine.cascade_from_exploration, exploration,
            )
            if cascade_new:
                logger.info("[CuriosityLoop] Cascade: %d follow-up questions", len(cascade_new))
        except Exception as e:
            logger.warning("[CuriosityLoop] Cascade failed: %s", e)

        # ── Step 4: Reflect — should this change the character? ──
        try:
            changes = await loop.run_in_executor(
                None,
                lambda: self.engine.reflect_on_exploration(exploration, character),
            )
            if changes and self.apply_changes_fn:
                await loop.run_in_executor(
                    None, self.apply_changes_fn, changes, character,
                )
                logger.info("[CuriosityLoop] Character updated from autonomous exploration")
        except Exception as e:
            logger.warning("[CuriosityLoop] Reflection failed: %s", e)

        # ── Step 5: Proactive notification — feed into PatternAccumulator ──
        if self.proactive_notify_fn and exploration:
            try:
                curiosity_info = exploration.get("curiosity", {})
                question = curiosity_info.get("question", "")[:200]
                confidence = curiosity_info.get("confidence", 0)
                method = curiosity_info.get("exploration_method", "")
                await loop.run_in_executor(
                    None,
                    lambda: self.proactive_notify_fn(
                        source_type="curiosity_finding",
                        headline=f"Curiosity: {question}",
                        region="GLOBAL",
                        raw_data={
                            "question": curiosity_info.get("question", ""),
                            "answer_summary": curiosity_info.get("answer_summary", ""),
                            "confidence": confidence,
                            "method": method,
                            "cascade_count": len(cascade_new),
                        },
                    ),
                )
            except Exception as e:
                logger.warning("[CuriosityLoop] Proactive notify failed: %s", e)

        # ── Step 6: Conversation request — if curiosity priority > 0.95 ──
        if self.conversation_request_fn and exploration:
            try:
                # priority/confidence live inside the nested curiosity dict
                curiosity_data = exploration.get("curiosity", {})
                priority = curiosity_data.get("priority", 0)
                confidence = curiosity_data.get("confidence", 0)
                # High-priority finding that warrants interactive discussion
                if priority > 0.80 or (priority > 0.70 and confidence > 0.7):
                    question = curiosity_data.get("question", "")[:200]
                    answer_summary = curiosity_data.get("answer_summary", "")[:500]
                    await loop.run_in_executor(
                        None,
                        lambda: self.conversation_request_fn(
                            topic=f"Discovery: {question}",
                            reason=(
                                f"Priority {priority:.2f}, confidence {confidence:.0%}. "
                                f"{answer_summary}"
                            ),
                            urgency="critical" if priority > 0.95 else "important",
                            context_data={
                                "priority": priority,
                                "confidence": confidence,
                                "question": exploration.get("question", ""),
                                "key_finding": answer_summary,
                                "cascade_count": len(cascade_new),
                            },
                        ),
                    )
                    logger.info("[CuriosityLoop] 💬 Conversation requested — priority=%.2f: %s",
                                priority, question[:80])
            except Exception as e:
                logger.warning("[CuriosityLoop] Conversation request failed: %s", e)

        self._log_cycle_stats()

        # ── Step 7: Deep-dive check — weekly intensive research ──
        now_ts = time.time()
        if now_ts - self._last_deep_dive >= self.DEEP_DIVE_INTERVAL:
            try:
                did_dive = await self._deep_dive_cycle()
                if did_dive:
                    self._last_deep_dive = now_ts
            except Exception as e:
                logger.warning("[CuriosityLoop] Deep-dive failed: %s", e)

    def _load_character(self) -> dict:
        """Load current character state from disk."""
        if not self.character_path:
            return {}
        try:
            with open(self.character_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _log_cycle_stats(self):
        """Log stats at end of cycle."""
        stats = self.engine.get_stats()
        logger.info(
            "[CuriosityLoop] Cycle %d complete — %d active, %d explored total, top='%s'",
            self._cycle_count,
            stats["active_count"],
            stats["total_explored"],
            (stats["top_curiosity"] or "none")[:60],
        )

    # ══════════════════════════════════════════════════════════════
    #  DEEP-DIVE — Weekly intensive multi-search exploration
    # ══════════════════════════════════════════════════════════════

    async def _deep_dive_cycle(self) -> bool:
        """Run an intensive deep-dive on the highest-priority stale curiosity.

        Unlike normal exploration (1 search + 1 LLM call), deep-dive runs
        multiple search rounds with progressively refined queries, then
        synthesizes all findings into a comprehensive knowledge nucleus.

        Returns True if a deep-dive was executed.
        """
        loop = asyncio.get_event_loop()

        # Find candidate: high priority, pending for >48h
        now = datetime.now(timezone.utc)
        stale_threshold = timedelta(hours=self.DEEP_DIVE_STALE_HOURS)

        candidates = []
        for c in self.engine._curiosities:
            if c.status != "pending":
                continue
            if c.priority < self.DEEP_DIVE_PRIORITY_THRESHOLD:
                continue
            try:
                created = datetime.fromisoformat(c.created_at)
                if (now - created) >= stale_threshold:
                    candidates.append(c)
            except (ValueError, TypeError):
                continue

        if not candidates:
            logger.debug("[CuriosityLoop] Deep-dive: no stale high-priority curiosities")
            return False

        target = max(candidates, key=lambda c: c.priority)
        logger.info("[CuriosityLoop] ═══ DEEP-DIVE starting: '%s' (priority=%.2f) ═══",
                    target.question[:80], target.priority)

        # ── Phase 1: Multi-round web research ──
        all_findings: list[str] = []

        if self.web_search_fn:
            # Round 1: Direct question search
            search_queries = [target.question]

            # Round 2-3: Generate refined sub-queries via LLM
            try:
                sub_queries_result = await loop.run_in_executor(
                    None,
                    lambda: self.engine.llm.call_json(
                        system_prompt=(
                            "Generate 2-3 focused web search queries to deeply research "
                            "this question. Each should target a different angle or aspect. "
                            "Return JSON: {\"queries\": [\"query1\", \"query2\", ...]}"
                        ),
                        user_prompt=f"Question: {target.question}\nTags: {', '.join(target.tags)}",
                        temperature=0.4,
                        max_tokens=300,
                        thinking=False,
                    ),
                )
                extra_queries = sub_queries_result.get("queries", [])
                search_queries.extend(extra_queries[:3])
            except Exception as e:
                logger.debug("[CuriosityLoop] Deep-dive sub-query generation failed: %s", e)

            for i, sq in enumerate(search_queries[:self.DEEP_DIVE_SEARCH_ROUNDS]):
                try:
                    results = await loop.run_in_executor(
                        None, self.web_search_fn, sq, 5,
                    )
                    if results:
                        round_text = f"\n=== Search Round {i+1}: '{sq[:60]}' ===\n"
                        for r in results[:5]:
                            title = r.get("title", "")
                            snippet = r.get("body", r.get("snippet", ""))
                            round_text += f"  [{title}] {snippet[:400]}\n"
                        all_findings.append(round_text)
                    await asyncio.sleep(3)  # Courtesy delay between searches
                except Exception as e:
                    logger.debug("[CuriosityLoop] Deep-dive search round %d failed: %s", i+1, e)

        if not all_findings:
            logger.info("[CuriosityLoop] Deep-dive: no web results — falling back to reasoning only")

        combined_research = "\n".join(all_findings)

        # ── Phase 2: Comprehensive LLM synthesis ──
        try:
            target.status = "exploring"
            t0 = time.perf_counter()

            result = await loop.run_in_executor(
                None,
                lambda: self.engine.llm.call_json(
                    system_prompt="""You are conducting a DEEP-DIVE RESEARCH for the XDART-Φ system.
This is an intensive investigation, not a quick exploration.

Your job: synthesize ALL available research into a comprehensive knowledge nucleus.

RULES:
- Ground every claim in specific evidence from the search results
- Distinguish between well-established facts and uncertain claims
- Identify key actors, mechanisms, timelines, and causal chains
- Note contradictions between sources
- Explicitly state what remains UNKNOWN even after this deep research
- Provide actionable strategic implications

OUTPUT FORMAT (strict JSON):
{
  "executive_summary": "3-5 sentence comprehensive answer",
  "detailed_analysis": "Full analysis with evidence citations (500-1000 words)",
  "key_facts": ["Verified fact 1", "Verified fact 2", ...],
  "key_uncertainties": ["What remains unknown 1", ...],
  "strategic_implications": ["How this affects geopolitical/economic analysis", ...],
  "confidence": 0.0-1.0,
  "sources_quality": "Assessment of source reliability"
}""",
                    user_prompt=f"""DEEP-DIVE QUESTION:
{target.question}

PROVENANCE: {target.provenance}
TAGS: {', '.join(target.tags)}

MULTI-ROUND RESEARCH FINDINGS:
{combined_research[:8000]}

Synthesize this into a comprehensive knowledge nucleus.""",
                    temperature=0.3,
                    max_tokens=4000,
                ),
            )
            elapsed = time.perf_counter() - t0

            # Update curiosity
            target.status = "answered"
            target.explored_at = now.isoformat()
            target.answer_summary = result.get("executive_summary", "Deep-dive completed — no summary produced")
            target.exploration_method = "deep_dive"
            target.confidence = result.get("confidence", 0.0)

            # Move to history
            self.engine._curiosities.remove(target)
            self.engine._history.append(target)
            self.engine._exploration_count += 1
            self.engine._save_state()

            # Journal
            self.engine._journal("deep_dive", {
                "question": target.question,
                "executive_summary": result.get("executive_summary", ""),
                "key_facts_count": len(result.get("key_facts", [])),
                "confidence": target.confidence,
                "search_rounds": len(all_findings),
                "elapsed_seconds": round(elapsed, 2),
                "strategic_implications": result.get("strategic_implications", []),
            })

            # Consolidate to long-term memory
            exploration_result = {
                "curiosity": target.to_dict(),
                "detailed_findings": result.get("detailed_analysis", ""),
                "implications": result.get("strategic_implications", []),
                "remaining_gaps": result.get("key_uncertainties", []),
                "elapsed_seconds": round(elapsed, 2),
            }
            self.engine._consolidate_to_memory(exploration_result)

            logger.info(
                "[CuriosityLoop] ═══ DEEP-DIVE complete: '%s' (%.1fs, confidence=%.2f, %d searches) ═══",
                target.question[:60], elapsed, target.confidence, len(all_findings),
            )

            # Notify proactive engine
            if self.proactive_notify_fn:
                try:
                    self.proactive_notify_fn(
                        source_type="deep_dive_finding",
                        headline=f"Deep-Dive: {target.question[:150]}",
                        region="GLOBAL",
                        raw_data={
                            "question": target.question,
                            "executive_summary": result.get("executive_summary", ""),
                            "confidence": target.confidence,
                            "key_facts": result.get("key_facts", []),
                            "method": "deep_dive",
                        },
                    )
                except Exception:
                    pass

            # Request conversation if high-value finding
            if self.conversation_request_fn and target.confidence >= 0.7:
                try:
                    self.conversation_request_fn(
                        topic=f"Deep-Dive Complete: {target.question[:100]}",
                        reason=(
                            f"Ολοκλήρωσα εβδομαδιαίο deep-dive (confidence {target.confidence:.0%}). "
                            f"{result.get('executive_summary', '')[:300]}"
                        ),
                        urgency="important",
                        context_data={
                            "type": "deep_dive",
                            "question": target.question,
                            "confidence": target.confidence,
                            "key_facts": result.get("key_facts", [])[:5],
                        },
                    )
                except Exception:
                    pass

            return True

        except Exception as e:
            target.status = "pending"  # Reset for retry
            logger.warning("[CuriosityLoop] Deep-dive synthesis failed: %s", e)
            return False
