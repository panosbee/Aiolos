"""
XDART-Φ × XHEART — Phase 4: Episodic Memory

RAG θυμάται ΠΛΗΡΟΦΟΡΙΑ. Episodic Memory θυμάται ΕΜΠΕΙΡΙΑ.

Αυτό κάνει το σύστημα να ΕΞΕΛΙΣΣΕΤΑΙ αντί να επαναλαμβάνεται.
Καταγράφεται ΟΧΙ το output — αλλά η εσωτερική κατάσταση (XHEART state).
"""

import logging
import json
import time
import uuid
from datetime import datetime, timezone

from xdart.config import (
    QDRANT_COLLECTION,
    QDRANT_STORAGE_PATH,
    QDRANT_VECTOR_SIZE,
    XHEART_MEMORY_TOP_K,
)
from xdart.core_change_logger import CoreChangeLogger
from xdart.llm import LLMClient
from xdart.models import EpisodicMemoryEntry, RetrievedMemory

CONCEPT_REGISTRY_COLLECTION = "concept_registry"

logger = logging.getLogger(__name__)


class EpisodicMemoryPhase:
    """Phase 4 — Episodic Memory using Qdrant vector store.

    Stores XHEART internal states (not outputs).
    Retrieves relevant past experiences for new problems.
    Falls back to in-memory store if Qdrant is unavailable.
    """

    def __init__(self, llm: LLMClient, qdrant_client=None):
        self.llm = llm
        self.core_change_logger = CoreChangeLogger()
        self._client = None
        self._fallback_store: list[tuple[EpisodicMemoryEntry, list[float]]] = []
        self._use_fallback = False
        self._init_qdrant(qdrant_client)

    def _init_qdrant(self, external_client=None) -> None:
        """Initialize Qdrant in LOCAL embedded mode — no Docker needed.
        If external_client is provided, reuse that instead of creating a new one."""
        try:
            from qdrant_client.models import Distance, VectorParams

            if external_client is not None:
                self._client = external_client
                logger.info("Qdrant using shared client")
            else:
                from qdrant_client import QdrantClient
                self._client = QdrantClient(path=QDRANT_STORAGE_PATH)
                logger.info("Qdrant local storage: %s", QDRANT_STORAGE_PATH)

            # Ensure collection exists
            collections = [c.name for c in self._client.get_collections().collections]
            if QDRANT_COLLECTION not in collections:
                self._client.create_collection(
                    collection_name=QDRANT_COLLECTION,
                    vectors_config=VectorParams(
                        size=QDRANT_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", QDRANT_COLLECTION)
            else:
                logger.info("Qdrant collection exists: %s", QDRANT_COLLECTION)

            # Ensure concept_registry collection exists
            if CONCEPT_REGISTRY_COLLECTION not in collections:
                self._client.create_collection(
                    collection_name=CONCEPT_REGISTRY_COLLECTION,
                    vectors_config=VectorParams(
                        size=QDRANT_VECTOR_SIZE,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", CONCEPT_REGISTRY_COLLECTION)
            else:
                logger.info("Qdrant collection exists: %s", CONCEPT_REGISTRY_COLLECTION)

        except Exception as exc:
            logger.warning(
                "Qdrant unavailable (%s). Using in-memory fallback. "
                "Memory will not persist across restarts.",
                exc,
            )
            self._use_fallback = True

    @property
    def shared_qdrant_client(self):
        """Expose the Qdrant client for sharing across memory layers."""
        return self._client

    def store(
        self,
        problem: str,
        reframed_problem: str,
        xheart_distillate: str,
        domain_tags: list[str],
        layer_score: float,
        self_generated_layers: list[dict] | None = None,
    ) -> EpisodicMemoryEntry:
        """Store an XHEART internal state as episodic memory."""

        logger.info("="*60)
        logger.info("[Phase 4] EPISODIC MEMORY STORE — START")
        logger.info("[Phase 4] Problem: %s", problem[:120])
        logger.info("[Phase 4] Reframed: %s", reframed_problem[:120])
        logger.info("[Phase 4] Distillate: %s", xheart_distillate[:120])
        logger.info("[Phase 4] Domain tags: %s", domain_tags)
        logger.info("[Phase 4] Layer score: %.2f", layer_score)

        layers = self_generated_layers or []
        logger.info("[Phase 4] Self-generated layers: %d", len(layers))
        if layers:
            logger.info("[Phase 4] Expansion layer: %s (%s)",
                         layers[0].get("layer_name", "?"), layers[0].get("layer_type", "?"))

        t0 = time.perf_counter()

        entry = EpisodicMemoryEntry(
            problem=problem,
            reframed_problem=reframed_problem,
            xheart_distillate=xheart_distillate,
            domain_tags=domain_tags,
            layer_score=layer_score,
            self_generated_layers=layers,
            expansion_triggered=len(layers) > 0,
        )
        logger.info("[Phase 4] Entry created — id=%s, timestamp=%s", entry.id, entry.timestamp)

        # Generate embedding from the distillate (the experience, not the info)
        embed_text = f"{reframed_problem}\n{xheart_distillate}"
        logger.info("[Phase 4] Generating embedding for distillate — %d chars", len(embed_text))
        embedding = self.llm.embed(embed_text)
        logger.info("[Phase 4] Embedding generated — dim=%d", len(embedding))

        # Deduplication: check if a very similar memory already exists
        # If similarity > 0.92, update the existing entry instead of creating a duplicate
        DEDUP_THRESHOLD = 0.92
        if not self._use_fallback:
            try:
                similar = self._client.search(
                    collection_name=QDRANT_COLLECTION,
                    query_vector=embedding,
                    limit=1,
                )
                if similar and similar[0].score >= DEDUP_THRESHOLD:
                    existing = similar[0]
                    logger.info(
                        "[Phase 4] DEDUP: found similar memory (score=%.3f, problem='%s') — updating instead of duplicating",
                        existing.score, existing.payload.get("problem", "?")[:60],
                    )
                    # Update the existing entry with the newer distillate
                    from qdrant_client.models import PointStruct
                    self._client.upsert(
                        collection_name=QDRANT_COLLECTION,
                        points=[
                            PointStruct(
                                id=existing.id,
                                vector=embedding,
                                payload=entry.model_dump(mode="json"),
                            )
                        ],
                    )
                    elapsed = time.perf_counter() - t0
                    logger.info("[Phase 4] EPISODIC MEMORY UPDATED (dedup) — COMPLETE (%.2fs)", elapsed)
                    logger.info("="*60)
                    return entry
            except Exception as exc:
                logger.warning("[Phase 4] Dedup check failed (storing anyway): %s", exc)

        if self._use_fallback:
            self._fallback_store.append((entry, embedding))
            logger.info("[Phase 4] Stored in FALLBACK memory (total: %d)", len(self._fallback_store))
        else:
            from qdrant_client.models import PointStruct

            self._client.upsert(
                collection_name=QDRANT_COLLECTION,
                points=[
                    PointStruct(
                        id=entry.id,
                        vector=embedding,
                        payload=entry.model_dump(mode="json"),
                    )
                ],
            )
            logger.info("[Phase 4] Stored in QDRANT — id=%s, collection=%s", entry.id, QDRANT_COLLECTION)

        elapsed = time.perf_counter() - t0
        logger.info("[Phase 4] EPISODIC MEMORY STORE — COMPLETE (%.2fs)", elapsed)
        logger.info("="*60)

        return entry

    def retrieve(
        self,
        problem: str,
        top_k: int | None = None,
        threshold: float = 0.35,
    ) -> list[RetrievedMemory]:
        """Retrieve the most relevant past XHEART states for a new problem.

        Returns ALL memories above the similarity threshold, up to max_scan limit.
        This ensures relevant memories are never missed by a fixed top_k cap.
        """
        max_scan = top_k or 15  # scan more candidates, filter by threshold
        logger.info("[Memory] Retrieving memories — query='%s', max_scan=%d, threshold=%.2f, backend=%s",
                     problem[:80], max_scan, threshold, "fallback" if self._use_fallback else "qdrant")

        t0 = time.perf_counter()
        embedding = self.llm.embed(problem)

        if self._use_fallback:
            memories = self._retrieve_fallback(embedding, max_scan)
        else:
            results = self._client.search(
                collection_name=QDRANT_COLLECTION,
                query_vector=embedding,
                limit=max_scan,
            )

            memories = []
            for hit in results:
                if hit.score < threshold:
                    continue
                entry = EpisodicMemoryEntry(**hit.payload)
                memories.append(RetrievedMemory(
                    entry=entry,
                    similarity_score=hit.score,
                ))

        elapsed = time.perf_counter() - t0
        logger.info("[Memory] Retrieved %d memories (above %.2f threshold) in %.2fs", len(memories), threshold, elapsed)
        for i, m in enumerate(memories):
            logger.info("[Memory]   Memory %d: similarity=%.3f, problem='%s'",
                         i+1, m.similarity_score, m.entry.problem[:80])

        return memories

    def _retrieve_fallback(
        self,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedMemory]:
        """Cosine similarity search in fallback memory."""
        if not self._fallback_store:
            logger.info("[Memory] Fallback store is empty — no memories to retrieve")
            return []

        logger.info("[Memory] Searching fallback store — %d entries", len(self._fallback_store))

        scored = []
        for entry, emb in self._fallback_store:
            score = self._cosine_similarity(query_embedding, emb)
            scored.append((entry, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        memories = []
        for entry, score in scored[:top_k]:
            memories.append(RetrievedMemory(entry=entry, similarity_score=score))

        logger.info("[Memory] Fallback retrieval — returned %d of %d entries", len(memories), len(self._fallback_store))
        return memories

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def format_for_context(self, memories: list[RetrievedMemory]) -> str:
        """Format retrieved memories for injection into LLM context."""
        if not memories:
            return ""

        lines = ["=== EPISODIC MEMORY — PAST INTERNAL STATES ==="]
        lines.append("(These are NOT information — they are past EXPERIENCES.)")
        lines.append("(Let them inform your perspective but not constrain it.)\n")

        for i, mem in enumerate(memories, 1):
            e = mem.entry
            lines.append(f"[Memory {i}] (relevance: {mem.similarity_score:.2f})")
            lines.append(f"  Problem: {e.reframed_problem}")
            lines.append(f"  Internal State: {e.xheart_distillate}")
            lines.append(f"  Domains: {', '.join(e.domain_tags)}")
            lines.append(f"  Layer: {e.layer_score:.1f}")
            if e.expansion_triggered and e.self_generated_layers:
                layer = e.self_generated_layers[0]
                lines.append(f"  Expansion: detected gap → invented layer '{layer.get('layer_name', '?')}' ({layer.get('layer_type', '?')})")
                lines.append(f"  Expansion insight: {layer.get('key_insight', '')[:200]}")
            lines.append("")

        return "\n".join(lines)

    # ── Concept Registry ──────────────────────────────────────────────

    def store_concept(
        self,
        layer_info: dict,
        problem: str,
        distillate_core: str,
    ) -> None:
        """Store a self-generated concept in the concept_registry collection.

        Called once per self-generated layer, after Phase 3a.7 completes.
        If a concept with the same name already exists, updates it instead.
        """
        if self._use_fallback:
            logger.warning("[ConceptRegistry] Qdrant unavailable — concept not stored")
            return

        concept_name = layer_info["layer_name"]
        logger.info("[ConceptRegistry] Storing concept: %s", concept_name)

        # Check if concept already exists by name
        existing = self._find_concept_by_name(concept_name)
        if existing:
            logger.info("[ConceptRegistry] Concept '%s' already exists — updating", concept_name)
            self._update_concept(existing, layer_info, problem, distillate_core)
            return

        # Generate definition via LLM
        definition_prompt = f"""
A new concept was invented during reasoning. Write its canonical definition.

Concept name: {layer_info['layer_name']}
Type: {layer_info['layer_type']}
It was born because: {layer_info['gap_description']}
Its key insight: {layer_info['key_insight']}
Full reasoning that produced it: {layer_info.get('layer_output', '')[:1000]}

Write a definition (4-6 sentences), conditions_for_reactivation (2-3 sentences),
and reactivation_keywords (8-12 words/phrases).

Respond ONLY with valid JSON:
{{
  "definition": "...",
  "conditions_for_reactivation": "...",
  "reactivation_keywords": ["...", "..."]
}}
"""

        definition_result = self.llm.call_json(
            system_prompt="You are building a semantic concept registry. Be precise.",
            user_prompt=definition_prompt,
        )

        concept_id = str(uuid.uuid4())
        entry = {
            "id": concept_id,
            "name": layer_info["layer_name"],
            "type": layer_info["layer_type"],
            "definition": definition_result.get("definition", layer_info["key_insight"]),
            "born_from_problem": problem,
            "born_from_distillate": distillate_core[:500],
            "gap_description": layer_info["gap_description"],
            "key_insight": layer_info["key_insight"],
            "conditions_for_reactivation": definition_result.get(
                "conditions_for_reactivation", ""
            ),
            "reactivation_keywords": definition_result.get("reactivation_keywords", []),
            "related_concept_names": [],
            "usage_count": 0,
            "born_at": datetime.now(timezone.utc).isoformat(),
            "last_activated_at": None,
        }

        # Embed the definition for semantic retrieval
        embedding = self.llm.embed(entry["definition"])

        from qdrant_client.models import PointStruct

        self._client.upsert(
            collection_name=CONCEPT_REGISTRY_COLLECTION,
            points=[
                PointStruct(
                    id=concept_id,
                    vector=embedding,
                    payload={k: v for k, v in entry.items() if k != "embedding"},
                )
            ],
        )

        logger.info("[ConceptRegistry] Stored: %s — id=%s", entry["name"], concept_id)

    def _find_concept_by_name(self, name: str) -> dict | None:
        """Search concept_registry for an existing concept by exact name."""
        if self._use_fallback or not self._client:
            return None
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            results = self._client.scroll(
                collection_name=CONCEPT_REGISTRY_COLLECTION,
                scroll_filter=Filter(
                    must=[FieldCondition(key="name", match=MatchValue(value=name))]
                ),
                limit=1,
            )
            points = results[0]
            if points:
                point = points[0]
                payload = point.payload
                payload["_point_id"] = point.id
                return payload
        except Exception as exc:
            logger.warning("[ConceptRegistry] Name lookup failed: %s", exc)
        return None

    def _update_concept(
        self,
        existing: dict,
        layer_info: dict,
        problem: str,
        distillate_core: str,
    ) -> None:
        """Update an existing concept's definition with new context."""
        point_id = existing.get("_point_id")
        if not point_id:
            return

        self._client.set_payload(
            collection_name=CONCEPT_REGISTRY_COLLECTION,
            payload={
                "born_from_problem": problem,
                "born_from_distillate": distillate_core[:500],
                "gap_description": layer_info["gap_description"],
                "key_insight": layer_info["key_insight"],
                "last_activated_at": datetime.now(timezone.utc).isoformat(),
            },
            points=[point_id],
        )
        logger.info("[ConceptRegistry] Updated existing concept: %s", existing["name"])

    def retrieve_concepts(
        self,
        query: str,
        top_k: int = 2,
        threshold: float = 0.30,
    ) -> list[dict]:
        """Semantic search in concept_registry.

        Returns concepts whose definition is semantically close to the query.
        Called at the START of the pipeline, before Phase 0.
        """
        if self._use_fallback:
            logger.info("[ConceptRegistry] Qdrant unavailable — no concepts retrieved")
            return []

        logger.info("[ConceptRegistry] Retrieving concepts — query='%s'", query[:60])

        embedding = self.llm.embed(query)

        try:
            results = self._client.search(
                collection_name=CONCEPT_REGISTRY_COLLECTION,
                query_vector=embedding,
                limit=top_k,
                score_threshold=threshold,
            )
        except Exception as exc:
            logger.warning("[ConceptRegistry] Search failed: %s", exc)
            return []

        concepts = []
        for result in results:
            payload = result.payload
            payload["similarity"] = result.score
            concepts.append(payload)

            logger.info(
                "[ConceptRegistry]   Concept: %s (similarity=%.3f)",
                payload["name"],
                result.score,
            )

            # Update usage tracking
            try:
                self._client.set_payload(
                    collection_name=CONCEPT_REGISTRY_COLLECTION,
                    payload={
                        "usage_count": payload.get("usage_count", 0) + 1,
                        "last_activated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    points=[result.id],
                )
            except Exception as exc:
                logger.warning("[ConceptRegistry] Usage update failed: %s", exc)

        logger.info("[ConceptRegistry] Retrieved %d concepts", len(concepts))
        return concepts

    def seed_concepts(self, seed_data: list[dict], force: bool = False) -> None:
        """Seed concepts into concept_registry.

        By default skips concepts that already exist (by name).
        If force=True, skips the collection-level check and seeds missing ones.
        """
        if self._use_fallback:
            logger.warning("[ConceptRegistry] Qdrant unavailable — cannot seed")
            return

        # Check if already fully seeded (quick exit)
        try:
            info = self._client.get_collection(CONCEPT_REGISTRY_COLLECTION)
            if not force and info.points_count >= len(seed_data):
                logger.info(
                    "[ConceptRegistry] Already seeded (%d concepts) — skipping",
                    info.points_count,
                )
                return
        except Exception as exc:
            logger.warning("[ConceptRegistry] Cannot check collection: %s", exc)
            return

        from qdrant_client.models import PointStruct

        seeded = 0
        skipped = 0
        logger.info("[ConceptRegistry] Seeding %d concepts...", len(seed_data))

        for concept in seed_data:
            # Skip if concept already exists by name
            existing = self._find_concept_by_name(concept["name"])
            if existing:
                logger.info("[ConceptRegistry] Already exists — skipping: %s", concept["name"])
                skipped += 1
                continue

            concept_id = str(uuid.uuid4())
            embedding = self.llm.embed(concept["definition"])

            entry = {
                "id": concept_id,
                "name": concept["name"],
                "type": concept["type"],
                "definition": concept["definition"],
                "born_from_problem": concept["born_from_problem"],
                "born_from_distillate": "",
                "gap_description": "",
                "key_insight": concept["key_insight"],
                "conditions_for_reactivation": concept["conditions_for_reactivation"],
                "reactivation_keywords": concept["reactivation_keywords"],
                "related_concept_names": [],
                "usage_count": 0,
                "born_at": datetime.now(timezone.utc).isoformat(),
                "last_activated_at": None,
            }

            self._client.upsert(
                collection_name=CONCEPT_REGISTRY_COLLECTION,
                points=[
                    PointStruct(
                        id=concept_id,
                        vector=embedding,
                        payload=entry,
                    )
                ],
            )
            logger.info("[ConceptRegistry] Seeded: %s (%s)", entry["name"], entry["type"])
            seeded += 1

        logger.info("[ConceptRegistry] Seeding complete — %d seeded, %d skipped", seeded, skipped)

    @property
    def concept_count(self) -> int:
        """Number of stored concepts in the registry."""
        if self._use_fallback:
            return 0
        try:
            info = self._client.get_collection(CONCEPT_REGISTRY_COLLECTION)
            return info.points_count
        except Exception:
            return 0

    @property
    def entry_count(self) -> int:
        """Number of stored episodic memories."""
        if self._use_fallback:
            return len(self._fallback_store)
        try:
            info = self._client.get_collection(QDRANT_COLLECTION)
            return info.points_count
        except Exception:
            return 0

    def list_all_concepts(self, limit: int = 100) -> list[dict]:
        """Return all concepts from the registry (no embedding search required)."""
        if self._use_fallback:
            return []
        try:
            from qdrant_client.models import Filter
            results = self._client.scroll(
                collection_name=CONCEPT_REGISTRY_COLLECTION,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            points = results[0] if results else []
            return [
                {
                    "name": p.payload.get("name", ""),
                    "type": p.payload.get("type", ""),
                    "definition": p.payload.get("definition", ""),
                    "key_insight": p.payload.get("key_insight", ""),
                    "usage_count": p.payload.get("usage_count", 0),
                    "born_at": p.payload.get("born_at", ""),
                    "born_from_problem": p.payload.get("born_from_problem", ""),
                }
                for p in points
            ]
        except Exception as exc:
            logger.warning("[ConceptRegistry] list_all_concepts failed: %s", exc)
            return []

    def list_all_memories(self, limit: int = 50) -> list[dict]:
        """Return all episodic memories (no embedding search required)."""
        if self._use_fallback:
            return [
                {
                    "id": e.id,
                    "problem": e.problem,
                    "reframed_problem": e.reframed_problem,
                    "distillate": e.xheart_distillate,
                    "domains": e.domain_tags,
                    "layer_score": e.layer_score,
                    "stored_at": e.stored_at,
                }
                for e in list(self._fallback_store.values())[:limit]
            ]
        try:
            results = self._client.scroll(
                collection_name=QDRANT_COLLECTION,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            points = results[0] if results else []
            return [
                {
                    "id": p.payload.get("id", ""),
                    "problem": p.payload.get("problem", ""),
                    "reframed_problem": p.payload.get("reframed_problem", ""),
                    "distillate": p.payload.get("xheart_distillate", ""),
                    "domains": p.payload.get("domain_tags", []),
                    "layer_score": p.payload.get("layer_score", 0),
                    "stored_at": p.payload.get("stored_at", ""),
                }
                for p in points
            ]
        except Exception as exc:
            logger.warning("[Memory] list_all_memories failed: %s", exc)
            return []

    # ── Character Update ──────────────────────────────────────────────

    def update_character(
        self,
        current_character: dict,
        run_distillate: str,
        run_problem: str,
        self_generated_layers: list[dict],
        xheart_internal: str,
        character_path: str,
    ) -> dict:
        """Phase 5b — CHARACTER UPDATE (Delta-based)

        Instead of asking the LLM to rewrite the entire 33K character state,
        we ask only for a DELTA: what changed? Then Python merges programmatically.
        This reduces output tokens from ~9000 to ~1500 → 5-6× faster.
        """
        logger.info("[Character] CHARACTER UPDATE — START (delta mode)")

        concepts_born = [
            layer.get("layer_name", "?") for layer in self_generated_layers
        ] if self_generated_layers else []

        new_version = current_character.get("version", 0) + 1

        # ── Step 1: Ask LLM for DELTA only (small output) ──
        system = """You are updating the character state of a reasoning system.
The character is not a personality. It is the living distillate of everything the system has experienced.

You will receive:
- The CURRENT epistemic stance (brief summary, not the full state)
- Active tensions (names only)
- What just happened (distillate, problem, concepts born)

Your task: describe ONLY WHAT CHANGED. Do NOT reproduce unchanged fields.

Rules:
- If nothing changed, set "significant_shift" to false and return minimal output.
- Character is epistemic stance, not personality. Never use "curious", "thoughtful", etc.
- Tensions: only list NEW ones (max 2) and IDs of RESOLVED ones.
- Changes: only the NEW change from THIS run (1 entry max).
- Open questions: only NEW ones (max 1) or indices to REMOVE.
- Character history: only a NEW line if this run represents a genuine era shift (rare).

Respond ONLY with valid JSON:
{
  "significant_shift": true/false,
  "new_epistemic_stance": "updated stance text (ONLY if significant_shift=true, else omit)",
  "new_tensions": [{"between": [...], "description": "..."}],
  "resolved_tension_indices": [],
  "new_change": {"before": "...", "after": "...", "caused_by": "..."},
  "new_open_questions": [],
  "remove_question_indices": [],
  "new_history_line": null,
  "new_concepts": []
}"""

        # Send only the MINIMAL context needed — not the full 33K state
        current_stance = current_character.get("current_epistemic_stance", "")[:500]
        tension_names = [
            t.get("description", "")[:80]
            for t in current_character.get("active_tensions", [])
        ]

        user = f"""CURRENT STANCE: {current_stance}

ACTIVE TENSIONS ({len(tension_names)}):
{chr(10).join(f'  [{i}] {t}' for i, t in enumerate(tension_names))}

THIS RUN (v{new_version}):
Problem: {run_problem[:300]}
Distillate: {run_distillate[:400]}
XHEART internal: {xheart_internal[:300]}
Concepts born: {concepts_born}

What changed in the character after absorbing this run?"""

        delta = self.llm.call_json(system_prompt=system, user_prompt=user, max_tokens=2048)

        # ── Step 2: Apply delta programmatically ──
        result = json.loads(json.dumps(current_character))  # deep copy
        result["version"] = new_version
        result["last_distillate"] = run_distillate

        if delta.get("significant_shift") and delta.get("new_epistemic_stance"):
            result["current_epistemic_stance"] = delta["new_epistemic_stance"]

        # Apply new tensions
        tensions = result.get("active_tensions", [])
        for nt in delta.get("new_tensions", []):
            tensions.append({
                "between": nt.get("between", []),
                "description": nt.get("description", ""),
                "opened_at_run": new_version,
                "resolved": False,
            })
        # Mark resolved tensions
        for idx in sorted(delta.get("resolved_tension_indices", []), reverse=True):
            if 0 <= idx < len(tensions):
                tensions[idx]["resolved"] = True
        # Prune resolved and cap at 15
        tensions = [t for t in tensions if not t.get("resolved")]
        if len(tensions) > 15:
            tensions = tensions[-15:]
        result["active_tensions"] = tensions

        # Apply new change
        changes = result.get("how_i_have_changed", [])
        new_change = delta.get("new_change")
        if new_change and new_change.get("before") and new_change.get("after"):
            new_change["run"] = new_version
            changes.append(new_change)
        if len(changes) > 10:
            changes = changes[-10:]
        result["how_i_have_changed"] = changes

        # Apply open questions changes
        questions = result.get("open_questions", [])
        for idx in sorted(delta.get("remove_question_indices", []), reverse=True):
            if 0 <= idx < len(questions):
                questions.pop(idx)
        for nq in delta.get("new_open_questions", []):
            if nq and nq not in questions:
                questions.append(nq)
        if len(questions) > 5:
            questions = questions[-5:]
        result["open_questions"] = questions

        # Apply history line (rare)
        history = result.get("character_history", [])
        new_line = delta.get("new_history_line")
        if new_line:
            history.append(new_line)
        if len(history) > 10:
            history = history[-10:]
        result["character_history"] = history

        # Apply new concepts
        owned = result.get("named_concepts_owned", [])
        for nc in delta.get("new_concepts", []):
            if nc and nc not in owned:
                owned.append(nc)
        # Also add concepts_born from self-generated layers
        for cb in concepts_born:
            if cb and cb not in owned:
                owned.append(cb)
        result["named_concepts_owned"] = owned

        # Update formative_runs if significant shift
        if delta.get("significant_shift"):
            formative = result.get("formative_runs", [])
            formative.append(new_version)
            if len(formative) > 20:
                formative = formative[-20:]
            result["formative_runs"] = formative

        # Preserve identity fields that the LLM doesn't manage
        for identity_key in ("name", "creator", "identity_note", "self_prompt"):
            if identity_key in current_character and identity_key not in result:
                result[identity_key] = current_character[identity_key]

        # Save to disk
        with open(character_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info("[Character] Version updated: %s", result.get("version"))
        logger.info("[Character] Tensions: %d", len(result.get("active_tensions", [])))
        logger.info("[Character] Changes: %d", len(result.get("how_i_have_changed", [])))
        logger.info("[Character] CHARACTER UPDATE — COMPLETE")

        # ── Self-modification detection + auto-apply ──
        core_change_result = None
        try:
            logger.info("[CoreChangeLog] Self-modification check — START")
            core_change_prompt = f"""You have just completed a run. Your character state has been updated.
Your distillate: {run_distillate[:400]}
Your new epistemic stance: {result.get('current_epistemic_stance', '')[:300]}

Question: Do you believe any aspect of your core architecture
should change — your phases, your prompts, your memory schema,
your concept governance, your pipeline order?

If yes: describe what, why, and what you expect to happen.
If no: say so clearly.

Respond ONLY with valid JSON:
{{
  "change_proposed": true or false,
  "change_type": "PHASE_PROMPT | MEMORY_SCHEMA | CHARACTER_INVARIANT | CONCEPT_GOVERNANCE | PIPELINE_ORDER | NEW_PHASE | REMOVE_PHASE | OTHER | null",
  "target": "which file or component",
  "description": "what you want to change",
  "reasoning": "why",
  "expected_effect": "what you expect will be different",
  "risk_acknowledged": "what could go wrong"
}}"""
            change_check = self.llm.call_json(
                system_prompt="You are reflecting on whether your core architecture needs to evolve.",
                user_prompt=core_change_prompt,
            )

            if change_check.get("change_proposed", False):
                change_type = change_check.get("change_type", "OTHER")
                change_target = change_check.get("target", "unknown")

                # ── Auto-apply: generate and execute the change ──
                applied = False
                applied_patch = None
                try:
                    applied, applied_patch = self._auto_apply_change(
                        change_check=change_check,
                        current_character=result,
                        character_path=character_path,
                    )
                except Exception as apply_err:
                    logger.warning("[CoreChangeLog] Auto-apply failed: %s", apply_err)

                change_id = self.core_change_logger.log(
                    run_number=result.get("version", 0),
                    change_type=change_type,
                    target=change_target,
                    description=change_check.get("description", ""),
                    reasoning=change_check.get("reasoning", ""),
                    evidence_runs=[run_distillate[:100]],
                    distillate_at_time=run_distillate,
                    concept_that_triggered=(
                        self_generated_layers[0]["layer_name"]
                        if self_generated_layers else None
                    ),
                    expected_effect=change_check.get("expected_effect", ""),
                    risk_acknowledged=change_check.get("risk_acknowledged", ""),
                    applied=applied,
                )
                logger.info(
                    "[CoreChangeLog] CHANGE PROPOSED: %s → %s",
                    change_type, change_target,
                )
                logger.info("[CoreChangeLog] Applied: %s", applied)
                logger.info("[CoreChangeLog] Entry id: %s", change_id)
                core_change_result = {
                    "change_id": change_id,
                    "change_type": change_type,
                    "target": change_target,
                    "description": change_check.get("description"),
                    "reasoning": change_check.get("reasoning", "")[:200],
                    "applied": applied,
                    "applied_patch": applied_patch,
                }
            else:
                logger.info("[CoreChangeLog] No core change proposed this run")

        except Exception as e:
            logger.warning("[CoreChangeLog] Self-modification check failed: %s", e)

        return result, core_change_result

    def _auto_apply_change(
        self,
        change_check: dict,
        current_character: dict,
        character_path: str,
    ) -> tuple[bool, str | None]:
        """Generate and apply the proposed core change.

        Only CHARACTER_INVARIANT and CONCEPT_GOVERNANCE changes are auto-applied
        (they modify character_state.json). All other types are logged but NOT applied.

        Returns (applied: bool, patch_description: str | None).
        """
        change_type = change_check.get("change_type", "")

        # Only auto-apply safe change types that touch character_state.json
        SAFE_TYPES = {"CHARACTER_INVARIANT", "CONCEPT_GOVERNANCE"}
        if change_type not in SAFE_TYPES:
            logger.info(
                "[CoreChangeLog] Auto-apply skipped — type '%s' not in safe list %s",
                change_type, SAFE_TYPES,
            )
            return False, None

        logger.info("[CoreChangeLog] Auto-apply — generating DELTA patch for %s", change_type)

        # Build a compact summary of current state (NOT the full 33K JSON)
        stance_preview = current_character.get('current_epistemic_stance', '')[:300]
        tension_names = [t.get('name', t.get('description', '?'))[:60]
                         for t in current_character.get('active_tensions', [])]
        open_qs = [q[:80] for q in current_character.get('open_questions', [])]

        apply_prompt = f"""You proposed a change to the system's character state.

Change type: {change_check.get('change_type')}
Description: {change_check.get('description')}
Reasoning: {change_check.get('reasoning')}
Expected effect: {change_check.get('expected_effect')}

Current state summary:
- Epistemic stance: {stance_preview}
- Tensions ({len(tension_names)}): {', '.join(tension_names[:5])}
- Open questions ({len(open_qs)}): {'; '.join(open_qs[:3])}

Produce a DELTA PATCH — only the fields that need to change.
Do NOT reproduce the entire character state.

Respond ONLY with valid JSON:
{{
  "operations": [
    {{
      "field": "the top-level field name (e.g. open_questions, current_epistemic_stance)",
      "action": "append | replace | remove_index",
      "value": "the new value to append or replace with (string, or object for tensions)",
      "index": null
    }}
  ],
  "patch_summary": "one-line description of what changed"
}}

Rules:
- append: adds value to array fields (open_questions, active_tensions, how_i_have_changed)
- replace: replaces the entire field value (for current_epistemic_stance or simple fields)
- remove_index: removes array item at index (for resolved questions/tensions)
- Keep operations minimal — only what the change actually requires"""

        patch_data = self.llm.call_json(
            system_prompt="You are generating a minimal delta patch for a reasoning system's character state. Be precise and surgical.",
            user_prompt=apply_prompt,
            max_tokens=1024,
        )

        operations = patch_data.get("operations", [])
        if not operations:
            logger.warning("[CoreChangeLog] Delta patch returned no operations — aborting")
            return False, None

        # Apply operations programmatically
        applied_ops = 0
        for op in operations:
            field = op.get("field", "")
            action = op.get("action", "")
            value = op.get("value")

            if not field or field not in current_character:
                # Allow creating new fields for invariants etc.
                if action == "replace" and field and value is not None:
                    current_character[field] = value
                    applied_ops += 1
                continue

            if action == "append" and isinstance(current_character[field], list):
                current_character[field].append(value)
                # Cap arrays at reasonable sizes
                max_sizes = {"active_tensions": 15, "how_i_have_changed": 10,
                             "open_questions": 5, "character_history": 10}
                cap = max_sizes.get(field, 20)
                if len(current_character[field]) > cap:
                    current_character[field] = current_character[field][-cap:]
                applied_ops += 1

            elif action == "replace" and value is not None:
                current_character[field] = value
                applied_ops += 1

            elif action == "remove_index":
                idx = op.get("index")
                if isinstance(idx, int) and isinstance(current_character[field], list):
                    if 0 <= idx < len(current_character[field]):
                        current_character[field].pop(idx)
                        applied_ops += 1

        if applied_ops == 0:
            logger.warning("[CoreChangeLog] No valid operations applied — aborting")
            return False, None

        # Write the patched character state
        with open(character_path, "w", encoding="utf-8") as f:
            json.dump(current_character, f, ensure_ascii=False, indent=2)

        patch_desc = f"Delta patch applied ({applied_ops} ops) for {change_check.get('change_type')} — {patch_data.get('patch_summary', change_check.get('description', '')[:100])}"
        logger.info("[CoreChangeLog] AUTO-APPLIED: %s", patch_desc)

        return True, patch_desc

    # ── Immediate Memory Update ───────────────────────────────────────

    def update_immediate_memory(
        self,
        problem: str,
        distillate: str,
        immediate_memory_path: str,
        concept_born: str | None = None,
        run_mood: str | None = None,
    ) -> None:
        """Keep the last 3 runs always available without retrieval.

        FIFO — max 3 entries. Only successful runs (reaching Phase 4) update this.
        """
        try:
            with open(immediate_memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"recent_runs": []}

        new_entry = {
            "problem": problem[:100],
            "distillate": distillate[:200],
            "concept_born": concept_born,
            "run_mood": run_mood,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        data["recent_runs"].append(new_entry)

        # Keep only last 3
        data["recent_runs"] = data["recent_runs"][-3:]

        with open(immediate_memory_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("[ImmediateMemory] Updated — %d recent runs", len(data["recent_runs"]))
