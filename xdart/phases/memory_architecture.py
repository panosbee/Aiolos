"""
XDART-Φ × XHEART — Human-Like Memory Architecture

Πέντε στρώματα μνήμης, όπως ο ανθρώπινος εγκέφαλος:

1. ΑΙΣΘΗΤΗΡΙΑΚΗ (Sensory Buffer)
   Κρατά εντυπώσεις για δευτερόλεπτα. Σχεδόν όλα χάνονται αμέσως.
   Μόνο τα salient (εντυπωσιακά) περνάνε στο working memory.

2. ΒΡΑΧΥΧΡΟΝΗ / ΕΡΓΑΖΟΜΕΝΗ (Working Memory)
   7±2 θέσεις. Εδώ γίνεται η ενεργός σκέψη.
   Τα σενάρια, τα insights, οι εντάσεις ζουν ΕΔΩ κατά τη διάρκεια ενός run.
   Snapshot αποθηκεύεται για το επόμενο run.

3. ΜΑΚΡΟΧΡΟΝΙΑ — ΕΠΕΙΣΟΔΙΑΚΗ (Episodic Memory)
   Ήδη υπάρχει στο Qdrant. Θυμάται ΕΜΠΕΙΡΙΕΣ, όχι πληροφορίες.

4. ΜΑΚΡΟΧΡΟΝΙΑ — ΣΗΜΑΣΙΟΛΟΓΙΚΗ (Semantic Memory)
   Γενικές αλήθειες εξαγμένες από πολλές εμπειρίες.
   Μοτίβα, κανόνες, αρχές. ΟΧΙ συγκεκριμένα γεγονότα.

5. ΣΙΩΠΗΡΗ / ΔΙΑΔΙΚΑΣΤΙΚΗ (Procedural Memory)
   Μαθημένα μοτίβα σκέψης που εφαρμόζονται αυτόματα.
   Σαν την ποδηλασία — δεν τα σκέφτεσαι, απλά τα κάνεις.

+ ΠΡΟΦΗΤΙΚΗ ΜΝΗΜΗ (Prophetic Memory)
   Σενάρια με προβλέψεις και outcomes. Ξεχωριστό Qdrant collection.
   Σε μελλοντικά runs ξαναδιαβάζονται: "Αυτό πόσο κόντεψε;"

«Ο νους δεν αποθηκεύει — αποτυπώνει. Και κάθε αποτύπωμα αλλάζει
 τον τρόπο που βλέπεις το επόμενο πράγμα.»
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from xdart.config import QDRANT_STORAGE_PATH, QDRANT_VECTOR_SIZE
from xdart.llm import LLMClient
from xdart.models import (
    PropheticMemoryEntry,
    ProceduralPattern,
    RetrievedPropheticMemory,
    ScenarioSimulationResult,
    Scenario,
    SemanticKnowledgeEntry,
    SensoryImpression,
    WorkingMemoryItem,
    WorkingMemoryState,
)

logger = logging.getLogger(__name__)

PROPHETIC_COLLECTION = "prophetic_scenarios"
SEMANTIC_COLLECTION = "semantic_knowledge"
PROCEDURAL_COLLECTION = "procedural_patterns"

# Working memory capacity — expanded from human 7±2 for AI agent
WORKING_MEMORY_CAPACITY = 12


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. SENSORY BUFFER — raw impressions, mostly discarded
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SensoryBuffer:
    """Αισθητηριακή μνήμη — κρατά εντυπώσεις για δευτερόλεπτα.

    Τα πάντα περνάνε από εδώ. Μόνο τα salient φτάνουν στο working memory.
    Uses embedding similarity to current problem for intelligent filtering.
    """

    def __init__(self, llm: LLMClient = None, salience_threshold: float = 0.4):
        self.buffer: list[SensoryImpression] = []
        self.salience_threshold = salience_threshold
        self.llm = llm
        self._problem_embedding: list[float] | None = None
        self._problem_embedding_en: list[float] | None = None  # English translation for cross-lang

    def intake(self, source: str, content: str, salience: float) -> SensoryImpression:
        """Register a raw impression. Returns the impression regardless of salience."""
        impression = SensoryImpression(
            source=source,
            content=content,
            salience=max(0.0, min(1.0, salience)),
        )
        self.buffer.append(impression)
        logger.debug("[SensoryBuffer] Intake: %s (salience=%.2f) — %s",
                     source, salience, content[:60])
        return impression

    def filter_salient(self) -> list[SensoryImpression]:
        """Return impressions above the salience threshold.

        Uses adaptive threshold: when the buffer is large, raises the threshold
        to keep a manageable number of events (target: ~200 max).
        Fallback: if ZERO events pass, return top-10 by salience.
        """
        # Adaptive threshold: scale up when buffer is very large
        threshold = self.salience_threshold
        if len(self.buffer) > 500:
            # Target ~200 events max. Compute the salience at the 200th percentile
            sorted_saliences = sorted([i.salience for i in self.buffer], reverse=True)
            target_count = min(200, len(sorted_saliences))
            adaptive_threshold = sorted_saliences[target_count - 1] if target_count > 0 else threshold
            threshold = max(threshold, adaptive_threshold)
            logger.info("[SensoryBuffer] Adaptive threshold: %.3f (buffer=%d, target=%d)",
                        threshold, len(self.buffer), target_count)

        salient = [i for i in self.buffer if i.salience >= threshold]
        discarded = len(self.buffer) - len(salient)

        if not salient and self.buffer:
            # Fallback: top-10 by salience to prevent 0/N blackout
            ranked = sorted(self.buffer, key=lambda x: x.salience, reverse=True)
            salient = ranked[:10]
            logger.warning(
                "[SensoryBuffer] 0 events passed threshold=%.2f — FALLBACK: top-%d by salience (max=%.3f)",
                threshold, len(salient),
                salient[0].salience if salient else 0,
            )
        else:
            logger.info("[SensoryBuffer] Filtered: %d salient, %d discarded (threshold=%.2f)",
                        len(salient), discarded, threshold)
        return salient

    def clear(self):
        """Clear the buffer — called after filtering."""
        self.buffer.clear()

    def set_problem_focus(self, problem: str):
        """Pre-compute embedding of the current problem for intelligent filtering.

        Generates two embeddings: original language + English translation.
        This ensures cross-language similarity works when the user asks in
        non-English but world events are in English.
        """
        if self.llm:
            self._problem_embedding = self.llm.embed(problem)
            logger.info("[SensoryBuffer] Problem embedding cached for smart filtering")

            # Detect non-ASCII (likely non-English) and create English embedding
            non_ascii_ratio = sum(1 for c in problem if ord(c) > 127) / max(len(problem), 1)
            if non_ascii_ratio > 0.3:
                try:
                    english_version = self.llm.call(
                        system_prompt="Translate the following to English. Return ONLY the translation, nothing else.",
                        user_prompt=problem,
                        max_tokens=200,
                    )
                    self._problem_embedding_en = self.llm.embed(english_version.strip())
                    logger.info("[SensoryBuffer] English embedding cached — cross-lang filtering enabled")
                except Exception as exc:
                    logger.warning("[SensoryBuffer] English translation failed: %s", exc)
                    self._problem_embedding_en = None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def intake_world_events(self, events: list[dict]) -> list[SensoryImpression]:
        """Process perception events through sensory buffer.

        If a problem embedding is available, uses cosine similarity to compute
        actual relevance instead of relying on the source's raw salience_score.
        Batch-embeds in chunks of 500 for large event sets.
        """
        # Build headline strings
        headlines = []
        for event in events:
            h = f"[{event.get('source_name', '?')}] {event.get('headline', '')}"
            headlines.append(h)

        # Batch-embed headlines for intelligent filtering
        # Chunk into batches of 500 to stay within API limits
        embeddings = None
        if self.llm and self._problem_embedding:
            try:
                BATCH_SIZE = 500
                if len(headlines) <= BATCH_SIZE:
                    embeddings = self.llm.embed_batch(headlines)
                else:
                    embeddings = []
                    for start in range(0, len(headlines), BATCH_SIZE):
                        chunk = headlines[start:start + BATCH_SIZE]
                        chunk_embeddings = self.llm.embed_batch(chunk)
                        embeddings.extend(chunk_embeddings)
                    logger.info("[SensoryBuffer] Batch-embedded %d events in %d chunks",
                                len(headlines), (len(headlines) + BATCH_SIZE - 1) // BATCH_SIZE)
            except Exception as exc:
                logger.warning("[SensoryBuffer] Batch embed failed, falling back: %s", exc)
                embeddings = None

        impressions = []
        for i, event in enumerate(events):
            if embeddings and self._problem_embedding:
                sim = self._cosine_similarity(self._problem_embedding, embeddings[i])
                # Cross-language boost: use English embedding if available
                if self._problem_embedding_en:
                    sim_en = self._cosine_similarity(self._problem_embedding_en, embeddings[i])
                    sim = max(sim, sim_en)
                salience = sim
            else:
                salience = event.get("salience_score", 0.3)

            impression = self.intake(
                source="perception",
                content=headlines[i],
                salience=salience,
            )
            impressions.append(impression)
        return impressions

    def intake_memories(self, memories: list, problem: str) -> list[SensoryImpression]:
        """Process retrieved episodic memories through sensory buffer.
        Higher similarity = higher salience."""
        impressions = []
        for mem in memories:
            salience = mem.similarity_score * 0.9  # high similarity → high salience
            impression = self.intake(
                source="memory_echo",
                content=f"Past experience: {mem.entry.xheart_distillate[:200]}",
                salience=salience,
            )
            impressions.append(impression)
        return impressions

    def intake_past_scenarios(self, scenarios: list, problem: str) -> list[SensoryImpression]:
        """Process retrieved prophetic memories through sensory buffer."""
        impressions = []
        for s in scenarios:
            salience = s.similarity_score * 0.85
            impression = self.intake(
                source="scenario_echo",
                content=(
                    f"Past prediction [{s.entry.tracking_status}]: "
                    f"{s.entry.scenario.name} — {s.entry.scenario.predicted_outcome[:150]}"
                ),
                salience=salience,
            )
            impressions.append(impression)
        return impressions


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. WORKING MEMORY — active thought space (7±2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WorkingMemory:
    """Βραχύχρονη / εργαζόμενη μνήμη — 7±2 θέσεις.

    Εδώ γίνεται η ενεργός σκέψη. Τα items ανταγωνίζονται για θέση.
    Αν η μνήμη είναι γεμάτη, το λιγότερο relevant φεύγει.

    Αυτό αλλάζει τη ΣΚΕΨΗ: κάθε στάδιο του pipeline βλέπει
    τι κρατάει ήδη το working memory και σκέφτεται βάσει αυτού.
    """

    def __init__(self, capacity: int = WORKING_MEMORY_CAPACITY):
        self.capacity = capacity
        self.items: list[WorkingMemoryItem] = []
        self.focus: str = ""
        self._next_slot = 0

    # Priority boost by item type — learned patterns and memories should
    # resist eviction by raw perception events
    TYPE_PRIORITY_BOOST = {
        "procedural_echo": 0.20,  # learned reasoning patterns — highest priority
        "semantic_echo": 0.15,    # consolidated truths
        "echo": 0.10,             # memory/scenario echoes from past runs
        "insight": 0.05,          # classified world events
        "question": 0.0,
        "scenario": 0.0,
        "tension": 0.0,
    }

    def push(self, item_type: str, content: str, source: str, relevance: float) -> WorkingMemoryItem:
        """Push an item into working memory. If full, evict the least relevant.

        Items from learned memory types (procedural, semantic, echoes) receive
        a priority boost so they resist eviction by raw perception events.
        """
        item = WorkingMemoryItem(
            slot_id=self._next_slot % (self.capacity + 2),  # 0 to capacity+1
            item_type=item_type,
            content=content,
            source=source,
            relevance=relevance,
        )
        self._next_slot += 1

        # Effective relevance includes type-based priority boost
        effective_relevance = relevance + self.TYPE_PRIORITY_BOOST.get(item_type, 0.0)

        if len(self.items) >= self.capacity:
            # Evict least relevant (with priority boost applied)
            self.items.sort(key=lambda x: x.relevance + self.TYPE_PRIORITY_BOOST.get(x.item_type, 0.0))
            min_effective = self.items[0].relevance + self.TYPE_PRIORITY_BOOST.get(self.items[0].item_type, 0.0)
            if min_effective >= effective_relevance:
                # New item is weaker than everything in memory — don't evict
                logger.debug("[WorkingMemory] Rejected (relevance=%.2f ≤ min %.2f): %s",
                             effective_relevance, min_effective, content[:60])
                return item
            evicted = self.items.pop(0)
            logger.info("[WorkingMemory] Evicted (relevance=%.2f, type=%s): %s",
                         evicted.relevance, evicted.item_type, evicted.content[:60])

        self.items.append(item)
        logger.debug("[WorkingMemory] Pushed [%s] (relevance=%.2f): %s",
                     item_type, relevance, content[:60])
        return item

    def absorb_from_sensory(self, salient_impressions: list[SensoryImpression]) -> int:
        """Absorb salient impressions from sensory buffer into working memory.
        Returns number of items absorbed."""
        # Sort by salience — most salient get in first
        sorted_impressions = sorted(salient_impressions, key=lambda x: x.salience, reverse=True)
        absorbed = 0

        for imp in sorted_impressions:
            self.push(
                item_type="echo" if imp.source in ("memory_echo", "scenario_echo") else "insight",
                content=imp.content,
                source=imp.source,
                relevance=imp.salience,
            )
            absorbed += 1

        logger.info("[WorkingMemory] Absorbed %d items from sensory buffer", absorbed)
        return absorbed

    def set_focus(self, focus: str):
        """Set attentional focus — what the system is thinking about."""
        self.focus = focus
        logger.info("[WorkingMemory] Focus set: %s", focus[:80])

    def get_state(self) -> WorkingMemoryState:
        """Get a snapshot of current working memory."""
        return WorkingMemoryState(
            items=list(self.items),
            capacity=self.capacity,
            focus=self.focus,
        )

    def format_for_context(self) -> str:
        """Format working memory for injection into LLM context.
        This is what the system 'has in mind' at any moment."""
        if not self.items:
            return ""

        lines = ["=== WORKING MEMORY (Εργαζόμενη Μνήμη) ==="]
        lines.append(f"Active focus: {self.focus}")
        lines.append(f"Slots used: {len(self.items)}/{self.capacity}")
        lines.append("(These are the thoughts actively held in mind NOW.)\n")

        # Sort by relevance — most relevant first
        for item in sorted(self.items, key=lambda x: x.relevance, reverse=True):
            marker = {
                "scenario": "📊",
                "insight": "💡",
                "tension": "⚡",
                "echo": "🔮",
                "question": "❓",
            }.get(item.item_type, "•")
            lines.append(f"  {marker} [{item.item_type}] (relevance: {item.relevance:.2f})")
            lines.append(f"    {item.content[:300]}")
            lines.append(f"    from: {item.source}\n")

        return "\n".join(lines)

    def clear(self):
        """Clear working memory — fresh start."""
        self.items.clear()
        self.focus = ""
        self._next_slot = 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. EPISODIC MEMORY — already exists (phases/memory.py)
#    No changes needed — it already stores EXPERIENCES.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. SEMANTIC MEMORY — general truths from accumulated experience
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SemanticMemory:
    """Σημασιολογική μνήμη — αφηρημένες αλήθειες, μοτίβα, αρχές.

    Δεν θυμάται ΠΟΤΕ ή ΠΟΥ κάτι έγινε.
    Θυμάται ΤΙ ΙΣΧΥΕΙ γενικά.

    "Τα συστήματα αποτυχαίνουν στις συνδέσεις, όχι στα εξαρτήματα."
    — Αυτό δεν είναι εμπειρία. Είναι σημασιολογική γνώση.
    """

    def __init__(self, llm: LLMClient, qdrant_client=None):
        self.llm = llm
        self._client = None
        self._use_fallback = False
        self._fallback_store: list[tuple[SemanticKnowledgeEntry, list[float]]] = []
        self._init_qdrant(qdrant_client)

    def _init_qdrant(self, external_client=None):
        try:
            from qdrant_client.models import Distance, VectorParams

            if external_client is not None:
                self._client = external_client
            else:
                from qdrant_client import QdrantClient
                self._client = QdrantClient(path=QDRANT_STORAGE_PATH)

            collections = [c.name for c in self._client.get_collections().collections]

            if SEMANTIC_COLLECTION not in collections:
                self._client.create_collection(
                    collection_name=SEMANTIC_COLLECTION,
                    vectors_config=VectorParams(
                        size=QDRANT_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", SEMANTIC_COLLECTION)
            else:
                logger.info("Qdrant collection exists: %s", SEMANTIC_COLLECTION)
        except Exception as exc:
            logger.warning("Semantic memory Qdrant init failed: %s", exc)
            self._use_fallback = True

    def extract_and_store(
        self,
        problem: str,
        distillate: str,
        scenarios_summary: str,
        tribunal_synthesis: str,
    ) -> list[SemanticKnowledgeEntry]:
        """After a complete run, extract general truths and store them.
        This is consolidation — like sleeping on it."""

        logger.info("[SemanticMemory] Extracting general truths from run...")

        system = (
            "You are the semantic memory consolidation process.\n"
            "From a completed reasoning run, extract 1-3 GENERAL TRUTHS.\n"
            "Not specific predictions. Not events. ABSTRACT PATTERNS.\n\n"
            "A good semantic memory entry looks like:\n"
            "- 'Systems under pressure fail at coupling points, not at individual components'\n"
            "- 'When multiple actors lack shared understanding of what happened, speed kills'\n"
            "- 'Diplomatic response time is a risk variable, not a safety guarantee'\n\n"
            "A BAD entry is specific:\n"
            "- 'China might invade Taiwan in 2026' ← This is a SCENARIO, not knowledge\n\n"
            "Respond in JSON:\n"
            "{\n"
            '  "truths": [\n'
            '    {"knowledge": "the abstract truth", "confidence": 0.0-1.0, "domain_tags": ["tag1"]}\n'
            "  ]\n"
            "}"
        )

        user = (
            f"Problem analyzed: {problem}\n"
            f"Distillate: {distillate}\n"
            f"Scenarios summary: {scenarios_summary[:800]}\n"
            f"Tribunal synthesis: {tribunal_synthesis[:400]}\n\n"
            "Extract the general truths. Only truths you're confident about."
        )

        data = self.llm.call_json(system, user)
        entries = []

        for truth in data.get("truths", []):
            entry = SemanticKnowledgeEntry(
                knowledge=truth["knowledge"],
                confidence=truth.get("confidence", 0.5),
                domain_tags=truth.get("domain_tags", []),
            )
            embedding = self.llm.embed(entry.knowledge)

            # Check for duplicates — if similar knowledge exists, reinforce instead
            existing = self._find_similar(embedding, threshold=0.85)
            if existing:
                self._reinforce(existing, entry)
                logger.info("[SemanticMemory] Reinforced existing: %s", existing.knowledge[:80])
            else:
                self._store(entry, embedding)
                entries.append(entry)
                logger.info("[SemanticMemory] New truth: %s", entry.knowledge[:80])

        logger.info("[SemanticMemory] Stored %d new, reinforced existing", len(entries))
        return entries

    def retrieve(self, query: str, top_k: int = 3, threshold: float = 0.35) -> list[SemanticKnowledgeEntry]:
        """Retrieve relevant semantic knowledge for a given problem."""
        if self._use_fallback:
            return []

        embedding = self.llm.embed(query)
        try:
            results = self._client.search(
                collection_name=SEMANTIC_COLLECTION,
                query_vector=embedding,
                limit=top_k,
                score_threshold=threshold,
            )
            entries = []
            for hit in results:
                entry = SemanticKnowledgeEntry(**hit.payload)
                entries.append(entry)
                logger.info("[SemanticMemory] Retrieved (%.2f): %s",
                           hit.score, entry.knowledge[:80])
            return entries
        except Exception as exc:
            logger.warning("[SemanticMemory] Retrieve failed: %s", exc)
            return []

    def format_for_context(self, entries: list[SemanticKnowledgeEntry]) -> str:
        """Format for injection into LLM context."""
        if not entries:
            return ""

        lines = ["=== SEMANTIC MEMORY (Γενικές Αλήθειες) ==="]
        lines.append("(Patterns learned from past experience — not specific events.)\n")
        for i, e in enumerate(entries, 1):
            lines.append(f"  [{i}] (confidence: {e.confidence:.2f}, confirmed {e.source_count}x)")
            lines.append(f"      {e.knowledge}")
            lines.append("")
        return "\n".join(lines)

    def _store(self, entry: SemanticKnowledgeEntry, embedding: list[float]):
        if self._use_fallback:
            self._fallback_store.append((entry, embedding))
            return

        from qdrant_client.models import PointStruct
        self._client.upsert(
            collection_name=SEMANTIC_COLLECTION,
            points=[PointStruct(
                id=entry.id,
                vector=embedding,
                payload=entry.model_dump(mode="json"),
            )],
        )

    def _find_similar(self, embedding: list[float], threshold: float = 0.85):
        """Find if similar knowledge already exists."""
        if self._use_fallback:
            return None
        try:
            results = self._client.search(
                collection_name=SEMANTIC_COLLECTION,
                query_vector=embedding,
                limit=1,
                score_threshold=threshold,
            )
            if results:
                return SemanticKnowledgeEntry(**results[0].payload)
        except Exception:
            pass
        return None

    def _reinforce(self, existing: SemanticKnowledgeEntry, new: SemanticKnowledgeEntry):
        """Reinforce an existing semantic memory — increase confidence and count."""
        if self._use_fallback:
            return
        try:
            new_confidence = min(1.0, existing.confidence * 0.7 + new.confidence * 0.3 + 0.05)
            self._client.set_payload(
                collection_name=SEMANTIC_COLLECTION,
                payload={
                    "confidence": new_confidence,
                    "source_count": existing.source_count + 1,
                    "last_reinforced": datetime.now(timezone.utc).isoformat(),
                },
                points=[existing.id],
            )
        except Exception as exc:
            logger.warning("[SemanticMemory] Reinforce failed: %s", exc)

    def store_truth(self, knowledge: str, confidence: float, source: str = "manual") -> bool:
        """Store a single truth directly. Used by consolidation loop.

        Returns True if stored as new, False if reinforced existing.
        """
        entry = SemanticKnowledgeEntry(
            knowledge=knowledge,
            confidence=confidence,
            domain_tags=[source],
        )
        embedding = self.llm.embed(entry.knowledge)
        existing = self._find_similar(embedding, threshold=0.85)
        if existing:
            self._reinforce(existing, entry)
            return False
        self._store(entry, embedding)
        return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. PROCEDURAL MEMORY — learned reasoning patterns
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ProceduralMemory:
    """Σιωπηρή / διαδικαστική μνήμη — αυτόματα μοτίβα σκέψης.

    Σαν την ποδηλασία: δεν τα σκέφτεσαι, απλά τα κάνεις.

    Παράδειγμα:
    "Όταν βλέπω barrier failures σε πολλαπλά μέτωπα, αυτόματα
     ελέγχω αν υπάρχει synchronization risk πριν δώσω πρόβλεψη."

    Αυτά μαθαίνονται αυτόματα μετά από αρκετά runs.
    """

    def __init__(self, llm: LLMClient, qdrant_client=None):
        self.llm = llm
        self._client = None
        self._use_fallback = False
        self._fallback_store: list[ProceduralPattern] = []
        self._init_qdrant(qdrant_client)

    def _init_qdrant(self, external_client=None):
        try:
            from qdrant_client.models import Distance, VectorParams

            if external_client is not None:
                self._client = external_client
            else:
                from qdrant_client import QdrantClient
                self._client = QdrantClient(path=QDRANT_STORAGE_PATH)

            collections = [c.name for c in self._client.get_collections().collections]

            if PROCEDURAL_COLLECTION not in collections:
                self._client.create_collection(
                    collection_name=PROCEDURAL_COLLECTION,
                    vectors_config=VectorParams(
                        size=QDRANT_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", PROCEDURAL_COLLECTION)
            else:
                logger.info("Qdrant collection exists: %s", PROCEDURAL_COLLECTION)
        except Exception as exc:
            logger.warning("Procedural memory Qdrant init failed: %s", exc)
            self._use_fallback = True

    def extract_and_store(
        self,
        problem: str,
        distillate: str,
        scenarios_summary: str,
        was_accurate: bool | None = None,
    ) -> list[ProceduralPattern]:
        """After a run, extract reasoning patterns that worked."""

        logger.info("[ProceduralMemory] Extracting reasoning patterns...")

        system = (
            "You are the procedural memory consolidation process.\n"
            "From a completed reasoning run, extract 0-2 REASONING PATTERNS.\n"
            "These are not facts. They are PROCEDURES — how-to-think rules.\n\n"
            "A good procedural pattern:\n"
            '  trigger: "When multiple crises are happening simultaneously"\n'
            '  action: "Check coupling mechanisms between them before assessing severity of any single one"\n\n'
            "A BAD pattern (too vague or too specific):\n"
            '  trigger: "When thinking about anything" → too vague\n'
            '  trigger: "When thinking about Taiwan and China in 2026" → too specific\n\n'
            "Only extract patterns that seem GENERALIZABLE across future problems.\n"
            "If nothing generalizable emerged, return empty list.\n\n"
            "Respond in JSON:\n"
            "{\n"
            '  "patterns": [\n'
            "    {\n"
            '      "pattern_name": "SHORT_NAME",\n'
            '      "trigger_condition": "when to apply this",\n'
            '      "action": "what to do",\n'
            '      "learned_from": "which aspect of this run taught this"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        user = (
            f"Problem: {problem}\n"
            f"Distillate: {distillate}\n"
            f"Scenarios summary: {scenarios_summary[:600]}\n"
        )

        data = self.llm.call_json(system, user)
        patterns = []

        for p in data.get("patterns", []):
            pattern = ProceduralPattern(
                pattern_name=p["pattern_name"],
                trigger_condition=p["trigger_condition"],
                action=p["action"],
                learned_from=p.get("learned_from", problem[:100]),
            )
            self._store(pattern)
            patterns.append(pattern)
            logger.info("[ProceduralMemory] Learned: %s", pattern.pattern_name)

        return patterns

    def retrieve_applicable(self, problem: str, top_k: int = 3) -> list[ProceduralPattern]:
        """Find procedural patterns that might apply to this problem."""
        if self._use_fallback:
            return self._fallback_store[:top_k]

        embedding = self.llm.embed(problem)
        try:
            results = self._client.search(
                collection_name=PROCEDURAL_COLLECTION,
                query_vector=embedding,
                limit=top_k,
                score_threshold=0.30,
            )
            patterns = []
            for hit in results:
                pattern = ProceduralPattern(**hit.payload)
                pattern.application_count += 1
                patterns.append(pattern)
                logger.info("[ProceduralMemory] Applicable: %s (score=%.2f)",
                           pattern.pattern_name, hit.score)
            return patterns
        except Exception as exc:
            logger.warning("[ProceduralMemory] Retrieve failed: %s", exc)
            return []

    def format_for_context(self, patterns: list[ProceduralPattern]) -> str:
        """Format applicable patterns for LLM context."""
        if not patterns:
            return ""

        lines = ["=== PROCEDURAL MEMORY (Αυτόματα Μοτίβα Σκέψης) ==="]
        lines.append("(These reasoning habits apply automatically. Follow them.)\n")
        for p in patterns:
            lines.append(f"  PATTERN: {p.pattern_name}")
            lines.append(f"    WHEN: {p.trigger_condition}")
            lines.append(f"    DO: {p.action}")
            lines.append(f"    (applied {p.application_count}x, success_rate: {p.success_rate:.0%})\n")
        return "\n".join(lines)

    def _store(self, pattern: ProceduralPattern):
        if self._use_fallback:
            self._fallback_store.append(pattern)
            return

        embedding = self.llm.embed(f"{pattern.trigger_condition} {pattern.action}")
        from qdrant_client.models import PointStruct
        self._client.upsert(
            collection_name=PROCEDURAL_COLLECTION,
            points=[PointStruct(
                id=pattern.id,
                vector=embedding,
                payload=pattern.model_dump(mode="json"),
            )],
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROPHETIC MEMORY — scenarios with predictions & tracking
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PropheticMemory:
    """Η μνήμη του Προφήτη.

    Αποθηκεύει σενάρια, προβλέψεις, αποτελέσματα.
    Σε μελλοντικά runs τα ξαναδιαβάζει και ρωτά:
    "Αυτό πόσο κόντεψε; Τι πήγε στραβά; Τι πρέπει να αλλάξω;"
    """

    def __init__(self, llm: LLMClient, qdrant_client=None):
        self.llm = llm
        self._client = None
        self._use_fallback = False
        self._fallback_store: list[tuple[PropheticMemoryEntry, list[float]]] = []
        self._init_qdrant(qdrant_client)

    def _init_qdrant(self, external_client=None):
        try:
            from qdrant_client.models import Distance, VectorParams

            if external_client is not None:
                self._client = external_client
            else:
                from qdrant_client import QdrantClient
                self._client = QdrantClient(path=QDRANT_STORAGE_PATH)

            collections = [c.name for c in self._client.get_collections().collections]

            if PROPHETIC_COLLECTION not in collections:
                self._client.create_collection(
                    collection_name=PROPHETIC_COLLECTION,
                    vectors_config=VectorParams(
                        size=QDRANT_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", PROPHETIC_COLLECTION)
            else:
                logger.info("Qdrant collection exists: %s", PROPHETIC_COLLECTION)
        except Exception as exc:
            logger.warning("Prophetic memory Qdrant init failed: %s", exc)
            self._use_fallback = True

    def store_scenarios(
        self,
        problem: str,
        scenarios: list[Scenario],
        simulations: list[ScenarioSimulationResult],
        verdicts: list,
    ) -> list[PropheticMemoryEntry]:
        """Store all scenarios from a run as prophetic memory entries."""

        logger.info("[PropheticMemory] Storing %d scenarios...", len(scenarios))
        entries = []

        # Build lookup dicts
        sim_by_id = {s.scenario_id: s for s in simulations}
        verdict_by_id = {v.scenario_id: v for v in verdicts}

        for scenario in scenarios:
            sim = sim_by_id.get(scenario.id)
            verdict = verdict_by_id.get(scenario.id)

            if not sim:
                # Create minimal simulation result if missing
                sim = ScenarioSimulationResult(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    forward_projection="No simulation run",
                    stress_test_results=[],
                    breakpoints=[],
                    robustness_score=0.5,
                    revised_confidence=scenario.confidence,
                    simulation_insight="",
                )

            entry = PropheticMemoryEntry(
                problem=problem,
                scenario=scenario,
                simulation=sim,
                tribunal_rank=verdict.feasibility_rank if verdict else 99,
                tribunal_score=verdict.final_score if verdict else 0.0,
                was_dominant=verdict.feasibility_rank == 1 if verdict else False,
            )

            embed_text = (
                f"{scenario.name}: {scenario.narrative} → {scenario.predicted_outcome}"
            )
            embedding = self.llm.embed(embed_text)

            if self._use_fallback:
                self._fallback_store.append((entry, embedding))
            else:
                from qdrant_client.models import PointStruct
                self._client.upsert(
                    collection_name=PROPHETIC_COLLECTION,
                    points=[PointStruct(
                        id=entry.id,
                        vector=embedding,
                        payload=entry.model_dump(mode="json"),
                    )],
                )

            entries.append(entry)
            logger.info("[PropheticMemory] Stored: %s (rank=%d, score=%.2f)",
                        scenario.name, entry.tribunal_rank, entry.tribunal_score)

        return entries

    def store_autonomous_prophecy(
        self,
        problem: str,
        scenario: "Scenario",
        source: str = "proactive_engine",
        confidence_override: float | None = None,
    ) -> PropheticMemoryEntry:
        """Store a single autonomous prophecy — born from proactive analysis, not from the pipeline.

        These scenarios have no tribunal/simulation data. They are lighter-weight
        predictions that Αίολος generates autonomously from detected patterns.

        Args:
            problem: What pattern/question triggered this prediction
            scenario: The generated Scenario object
            source: Origin identifier (proactive_engine, curiosity, cross_system, etc.)
            confidence_override: Override the scenario's confidence if needed

        Returns:
            The stored PropheticMemoryEntry
        """
        # Create minimal simulation result (no real simulation was run)
        sim = ScenarioSimulationResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            forward_projection=f"[Autonomous prophecy — no simulation] {scenario.trajectory}",
            stress_test_results=[],
            breakpoints=[],
            robustness_score=confidence_override or scenario.confidence,
            revised_confidence=confidence_override or scenario.confidence,
            simulation_insight=f"Autonomous prophecy from {source}",
        )

        entry = PropheticMemoryEntry(
            problem=problem,
            scenario=scenario,
            simulation=sim,
            tribunal_rank=0,  # 0 = no tribunal (autonomous)
            tribunal_score=confidence_override or scenario.confidence,
            was_dominant=False,
            tracking_status="autonomous_proposed",  # Distinct from pipeline "active"
        )

        embed_text = (
            f"[AUTONOMOUS] {scenario.name}: {scenario.narrative} → {scenario.predicted_outcome}"
        )
        embedding = self.llm.embed(embed_text)

        if self._use_fallback:
            self._fallback_store.append((entry, embedding))
        else:
            from qdrant_client.models import PointStruct
            self._client.upsert(
                collection_name=PROPHETIC_COLLECTION,
                points=[PointStruct(
                    id=entry.id,
                    vector=embedding,
                    payload=entry.model_dump(mode="json"),
                )],
            )

        logger.info(
            "[PropheticMemory] AUTONOMOUS prophecy stored: %s (source=%s, confidence=%.2f)",
            scenario.name, source, entry.tribunal_score,
        )
        return entry

    def approve_autonomous_prophecy(self, entry_id: str) -> bool:
        """Promote an autonomous prophecy from 'autonomous_proposed' to 'active' tracking.

        Returns True if successful.
        """
        if self._use_fallback:
            for entry, _ in self._fallback_store:
                if entry.id == entry_id and entry.tracking_status == "autonomous_proposed":
                    entry.tracking_status = "active"
                    return True
            return False

        try:
            self._client.set_payload(
                collection_name=PROPHETIC_COLLECTION,
                payload={"tracking_status": "active"},
                points=[entry_id],
            )
            logger.info("[PropheticMemory] Autonomous prophecy %s → active", entry_id[:8])
            return True
        except Exception as exc:
            logger.warning("[PropheticMemory] Autonomous approve failed: %s", exc)
            return False

    def reject_autonomous_prophecy(self, entry_id: str, reason: str = "") -> bool:
        """Reject an autonomous prophecy — set status to 'rejected'.

        Returns True if successful.
        """
        if self._use_fallback:
            for entry, _ in self._fallback_store:
                if entry.id == entry_id and entry.tracking_status == "autonomous_proposed":
                    entry.tracking_status = "rejected"
                    return True
            return False

        try:
            self._client.set_payload(
                collection_name=PROPHETIC_COLLECTION,
                payload={
                    "tracking_status": "rejected",
                    "reality_checks": [{"action": "rejected", "reason": reason,
                                        "timestamp": datetime.now(timezone.utc).isoformat()}],
                },
                points=[entry_id],
            )
            logger.info("[PropheticMemory] Autonomous prophecy %s → rejected: %s", entry_id[:8], reason)
            return True
        except Exception as exc:
            logger.warning("[PropheticMemory] Autonomous reject failed: %s", exc)
            return False

    def list_autonomous_pending(self) -> list[dict]:
        """List all autonomous prophecies awaiting approval."""
        all_entries = self.list_all(limit=200)
        return [e for e in all_entries if e.get("tracking_status") == "autonomous_proposed"]

    def retrieve(
        self,
        query: str,
        top_k: int = 15,
        threshold: float = 0.35,
        only_active: bool = True,
    ) -> list[RetrievedPropheticMemory]:
        """Retrieve relevant past scenarios for a new problem.

        Returns ALL scenarios above the similarity threshold, up to top_k.
        """
        logger.info("[PropheticMemory] Retrieving — query='%s', max_scan=%d, threshold=%.2f", query[:60], top_k, threshold)
        embedding = self.llm.embed(query)

        if self._use_fallback:
            scored = []
            for entry, emb in self._fallback_store:
                if only_active and entry.tracking_status not in ("active", "tracking"):
                    continue
                score = self._cosine_similarity(embedding, emb)
                if score >= threshold:
                    scored.append((entry, score))
            scored.sort(key=lambda x: x[1], reverse=True)
            return [
                RetrievedPropheticMemory(entry=e, similarity_score=s)
                for e, s in scored[:top_k]
            ]

        try:
            results = self._client.search(
                collection_name=PROPHETIC_COLLECTION,
                query_vector=embedding,
                limit=top_k * 2,  # retrieve extra to filter by status
            )

            memories = []
            for hit in results:
                if hit.score < threshold:
                    continue
                entry = PropheticMemoryEntry(**hit.payload)
                if only_active and entry.tracking_status not in ("active", "tracking"):
                    continue
                memories.append(RetrievedPropheticMemory(
                    entry=entry,
                    similarity_score=hit.score,
                ))
                if len(memories) >= top_k:
                    break

            logger.info("[PropheticMemory] Retrieved %d scenarios (above %.2f threshold)", len(memories), threshold)
            return memories

        except Exception as exc:
            logger.warning("[PropheticMemory] Retrieve failed: %s", exc)
            return []

    def update_tracking_status(self, entry_id: str, new_status: str, reality_check: dict):
        """Update a scenario's tracking status after reality comparison.

        When status is 'confirmed' or 'disconfirmed', computes Brier score.
        Brier score = (forecast_probability - outcome)^2
          - 0.0 = perfect prediction
          - 1.0 = worst possible prediction
        """
        if self._use_fallback:
            return

        payload_update = {
            "tracking_status": new_status,
            "reality_checks": [reality_check],
        }

        # Compute Brier score for resolved predictions
        if new_status in ("confirmed", "disconfirmed"):
            outcome = 1.0 if new_status == "confirmed" else 0.0
            # Use tribunal_score as the forecast probability
            try:
                point = self._client.retrieve(
                    collection_name=PROPHETIC_COLLECTION,
                    ids=[entry_id],
                    with_payload=True,
                )
                if point:
                    forecast_prob = point[0].payload.get("tribunal_score", 0.5)
                    brier = (forecast_prob - outcome) ** 2
                    payload_update["brier_score"] = round(brier, 4)
                    logger.info("[PropheticMemory] Brier score for %s: %.4f (forecast=%.2f, outcome=%s)",
                                entry_id[:8], brier, forecast_prob, new_status)
            except Exception as exc:
                logger.warning("[PropheticMemory] Brier score computation failed: %s", exc)

        try:
            self._client.set_payload(
                collection_name=PROPHETIC_COLLECTION,
                payload=payload_update,
                points=[entry_id],
            )
            logger.info("[PropheticMemory] Updated %s → %s", entry_id[:8], new_status)
        except Exception as exc:
            logger.warning("[PropheticMemory] Status update failed: %s", exc)

    def compute_accuracy_stats(self) -> dict:
        """Compute aggregate prediction accuracy stats across all resolved prophecies."""
        all_entries = self.list_all(limit=500)

        resolved = [e for e in all_entries if e.get("tracking_status") in ("confirmed", "disconfirmed")]
        if not resolved:
            return {
                "total_prophecies": len(all_entries),
                "resolved": 0,
                "active": len([e for e in all_entries if e.get("tracking_status") in ("active", "tracking")]),
                "expired": len([e for e in all_entries if e.get("tracking_status") == "expired"]),
                "avg_brier_score": None,
                "accuracy_rating": "insufficient_data",
            }

        brier_scores = [e["brier_score"] for e in resolved if e.get("brier_score") is not None]
        confirmed = len([e for e in resolved if e.get("tracking_status") == "confirmed"])
        disconfirmed = len([e for e in resolved if e.get("tracking_status") == "disconfirmed"])

        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

        # Rating scale: 0.0-0.1 = excellent, 0.1-0.25 = good, 0.25-0.5 = fair, 0.5+ = poor
        rating = "insufficient_data"
        if avg_brier is not None:
            if avg_brier < 0.1:
                rating = "excellent"
            elif avg_brier < 0.25:
                rating = "good"
            elif avg_brier < 0.5:
                rating = "fair"
            else:
                rating = "poor"

        return {
            "total_prophecies": len(all_entries),
            "resolved": len(resolved),
            "confirmed": confirmed,
            "disconfirmed": disconfirmed,
            "active": len([e for e in all_entries if e.get("tracking_status") in ("active", "tracking")]),
            "expired": len([e for e in all_entries if e.get("tracking_status") == "expired"]),
            "avg_brier_score": round(avg_brier, 4) if avg_brier is not None else None,
            "accuracy_rating": rating,
            "confirmation_rate": round(confirmed / len(resolved), 2) if resolved else None,
        }

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @property
    def entry_count(self) -> int:
        if self._use_fallback:
            return len(self._fallback_store)
        try:
            info = self._client.get_collection(PROPHETIC_COLLECTION)
            return info.points_count
        except Exception:
            return 0

    def list_all(self, limit: int = 100) -> list[dict]:
        """Return all stored prophecies as plain dicts, newest first."""
        if self._use_fallback:
            entries = [e.model_dump(mode="json") for e, _ in self._fallback_store]
            entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return entries[:limit]

        try:
            from qdrant_client.models import ScrollRequest  # noqa: F811
            results, _next = self._client.scroll(
                collection_name=PROPHETIC_COLLECTION,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            entries = [hit.payload for hit in results]
            entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return entries[:limit]
        except Exception as exc:
            logger.warning("[PropheticMemory] list_all failed: %s", exc)
            return []
