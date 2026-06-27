"""
XDART-Φ × XHEART — MongoDB Integration

Persistent, queryable storage for Αίολος. Complements Qdrant (vector search)
with structured document storage for:

  - Entity Graph nodes and edges (queryable relationships)
  - Journals (proactive, curiosity, visual, core changes, introspection)
  - Conversation history
  - Αίολος's free-form notes (structured knowledge he writes himself)

Architecture:
  - Qdrant stays for vector similarity (embeddings, semantic search)
  - MongoDB handles structured documents, time-series journals, and graph queries
  - JSON files remain as fallback/backup — MongoDB is the primary

Collections created automatically on first use:
  - entities          — entity graph nodes (name, type, mentions, sources)
  - entity_edges      — directed edges between entities (weight, co-occurrences)
  - journal_proactive — proactive alert notifications
  - journal_curiosity — curiosity engine exploration log
  - journal_visual    — visual perception events
  - journal_core_changes — self-modification audit trail
  - journal_introspection — self-reflection entries
  - conversations     — chat message history
  - notes             — free-form knowledge Αίολος writes on his own
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class MongoStore:
    """MongoDB integration for Αίολος — structured persistence layer.

    All methods are safe to call even if MongoDB is unavailable (returns
    empty results / silently skips writes). The system never crashes
    because of a database issue.
    """

    def __init__(self, uri: str = "mongodb://localhost:27017", db_name: str = "aiolos"):
        self._uri = uri
        self._db_name = db_name
        self._client = None
        self._db = None
        self._available = False

        self._connect()

    def _connect(self) -> None:
        """Connect to MongoDB and create indexes."""
        try:
            from pymongo import MongoClient, ASCENDING, DESCENDING
            from pymongo.errors import ConnectionFailure

            self._client = MongoClient(
                self._uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            # Verify connection
            self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            self._available = True

            # Create indexes (idempotent)
            self._ensure_indexes()

            # Stats
            colls = self._db.list_collection_names()
            logger.info(
                "[MongoDB] Connected — db=%s, collections=%d, uri=%s",
                self._db_name, len(colls), self._uri,
            )
        except Exception as exc:
            logger.warning("[MongoDB] Unavailable (%s) — running without database", exc)
            self._available = False

    def _ensure_indexes(self) -> None:
        """Create indexes for all collections — called once at startup."""
        from pymongo import ASCENDING, DESCENDING, TEXT

        db = self._db

        # Entities
        db.entities.create_index([("name", ASCENDING)], unique=True)
        db.entities.create_index([("type", ASCENDING)])
        db.entities.create_index([("mention_count", DESCENDING)])
        db.entities.create_index([("last_seen", DESCENDING)])

        # Entity edges
        db.entity_edges.create_index([("source", ASCENDING), ("target", ASCENDING)], unique=True)
        db.entity_edges.create_index([("weight", DESCENDING)])

        # Journals — all have timestamp + type index
        for coll_name in [
            "journal_proactive", "journal_curiosity", "journal_visual",
            "journal_core_changes", "journal_introspection",
            "journal_self_evolution", "journal_logic_sandbox",
            "journal_visual_reflection",
        ]:
            db[coll_name].create_index([("timestamp", DESCENDING)])
            db[coll_name].create_index([("type", ASCENDING), ("timestamp", DESCENDING)])

        # Conversations
        db.conversations.create_index([("timestamp", DESCENDING)])
        db.conversations.create_index([("role", ASCENDING), ("timestamp", DESCENDING)])

        # Notes — Αίολος's free-form knowledge
        db.notes.create_index([("created_at", DESCENDING)])
        db.notes.create_index([("tags", ASCENDING)])
        db.notes.create_index([("title", TEXT), ("content", TEXT)])

        # Creative Links — Αίολος's imagination / creative nexus
        db.creative_links.create_index([("concept_a", ASCENDING), ("concept_b", ASCENDING)], unique=True)
        db.creative_links.create_index([("strength", DESCENDING)])
        db.creative_links.create_index([("maturity", DESCENDING)])
        db.creative_links.create_index([("created_at", DESCENDING)])
        db.creative_links.create_index([("tags", ASCENDING)])

        logger.info("[MongoDB] Indexes ensured for all collections")

    @property
    def available(self) -> bool:
        return self._available

    @property
    def db(self):
        """Direct access to the pymongo Database object for advanced queries."""
        return self._db

    # ══════════════════════════════════════════════════════════════
    #  ENTITY GRAPH — structured storage for nodes and edges
    # ══════════════════════════════════════════════════════════════

    def upsert_entity(self, name: str, entity_type: str, source: str = "",
                      timestamp: float | None = None) -> None:
        """Insert or update an entity node."""
        if not self._available:
            return
        ts = timestamp or time.time()
        try:
            self._db.entities.update_one(
                {"name": name},
                {
                    "$set": {"type": entity_type, "last_seen": ts},
                    "$inc": {"mention_count": 1},
                    "$setOnInsert": {"first_seen": ts, "created_at": datetime.now(timezone.utc)},
                    "$addToSet": {"sources": source} if source else {},
                },
                upsert=True,
            )
        except Exception as exc:
            logger.debug("[MongoDB] upsert_entity failed: %s", exc)

    def upsert_edge(self, source: str, target: str, weight_increment: float = 1.0,
                    timestamp: float | None = None) -> None:
        """Insert or update an edge between two entities."""
        if not self._available:
            return
        ts = timestamp or time.time()
        try:
            self._db.entity_edges.update_one(
                {"source": source, "target": target},
                {
                    "$inc": {"weight": weight_increment, "co_occurrences": 1},
                    "$set": {"last_seen": ts},
                    "$setOnInsert": {"first_seen": ts},
                },
                upsert=True,
            )
        except Exception as exc:
            logger.debug("[MongoDB] upsert_edge failed: %s", exc)

    def get_entity(self, name: str) -> dict | None:
        """Get a single entity by name."""
        if not self._available:
            return None
        try:
            return self._db.entities.find_one({"name": name}, {"_id": 0})
        except Exception:
            return None

    def get_top_entities(self, limit: int = 50, entity_type: str | None = None) -> list[dict]:
        """Get top entities by mention count."""
        if not self._available:
            return []
        try:
            query = {"type": entity_type} if entity_type else {}
            return list(
                self._db.entities.find(query, {"_id": 0})
                .sort("mention_count", -1)
                .limit(limit)
            )
        except Exception:
            return []

    def get_entity_connections(self, name: str, limit: int = 20) -> list[dict]:
        """Get edges connected to an entity (both directions)."""
        if not self._available:
            return []
        try:
            return list(
                self._db.entity_edges.find(
                    {"$or": [{"source": name}, {"target": name}]},
                    {"_id": 0},
                )
                .sort("weight", -1)
                .limit(limit)
            )
        except Exception:
            return []

    def entity_stats(self) -> dict:
        """Return entity graph statistics."""
        if not self._available:
            return {}
        try:
            return {
                "total_entities": self._db.entities.count_documents({}),
                "total_edges": self._db.entity_edges.count_documents({}),
                "types": {
                    doc["_id"]: doc["count"]
                    for doc in self._db.entities.aggregate([
                        {"$group": {"_id": "$type", "count": {"$sum": 1}}}
                    ])
                },
            }
        except Exception:
            return {}

    def import_entity_graph_from_json(self, json_data: dict) -> int:
        """Bulk import entity graph from existing JSON file.

        Returns the number of entities imported.
        """
        if not self._available:
            return 0

        nodes = json_data.get("nodes", {})
        edges = json_data.get("edges", [])
        imported = 0

        try:
            # Import nodes
            if nodes:
                ops = []
                from pymongo import UpdateOne
                for name, data in nodes.items():
                    ops.append(UpdateOne(
                        {"name": name},
                        {"$set": {
                            "name": name,
                            "type": data.get("type", "UNKNOWN"),
                            "mention_count": data.get("mention_count", 1),
                            "first_seen": data.get("first_seen", time.time()),
                            "last_seen": data.get("last_seen", time.time()),
                            "sources": list(data.get("sources", [])),
                        }},
                        upsert=True,
                    ))
                if ops:
                    result = self._db.entities.bulk_write(ops, ordered=False)
                    imported = result.upserted_count + result.modified_count
                    logger.info("[MongoDB] Imported %d entity nodes", imported)

            # Import edges
            if edges:
                edge_ops = []
                from pymongo import UpdateOne as UO
                for edge in edges:
                    edge_ops.append(UO(
                        {"source": edge["source"], "target": edge["target"]},
                        {"$set": {
                            "source": edge["source"],
                            "target": edge["target"],
                            "weight": edge.get("weight", 1.0),
                            "co_occurrences": edge.get("co_occurrences", 1),
                            "first_seen": edge.get("first_seen", time.time()),
                            "last_seen": edge.get("last_seen", time.time()),
                        }},
                        upsert=True,
                    ))
                if edge_ops:
                    result = self._db.entity_edges.bulk_write(edge_ops, ordered=False)
                    logger.info("[MongoDB] Imported %d entity edges",
                                result.upserted_count + result.modified_count)

        except Exception as exc:
            logger.error("[MongoDB] Entity graph import failed: %s", exc)

        return imported

    # ══════════════════════════════════════════════════════════════
    #  JOURNALS — append-only log collections
    # ══════════════════════════════════════════════════════════════

    def log_journal(self, collection: str, entry: dict) -> None:
        """Append a journal entry to the specified collection.

        Args:
            collection: One of journal_proactive, journal_curiosity, etc.
            entry: The document to insert.
        """
        if not self._available:
            return
        try:
            if "timestamp" not in entry:
                entry["timestamp"] = datetime.now(timezone.utc).isoformat()
            self._db[collection].insert_one(entry)
        except Exception as exc:
            logger.debug("[MongoDB] log_journal(%s) failed: %s", collection, exc)

    def query_journal(self, collection: str, query: dict | None = None,
                      limit: int = 50, sort_desc: bool = True) -> list[dict]:
        """Query a journal collection with optional filter."""
        if not self._available:
            return []
        try:
            direction = -1 if sort_desc else 1
            results = list(
                self._db[collection].find(
                    query or {}, {"_id": 0}
                ).sort("timestamp", direction).limit(limit)
            )
            return results
        except Exception:
            return []

    # ══════════════════════════════════════════════════════════════
    #  CONVERSATIONS — chat history persistence
    # ══════════════════════════════════════════════════════════════

    def log_message(self, role: str, content: str, metadata: dict | None = None) -> None:
        """Store a chat message."""
        if not self._available:
            return
        try:
            doc = {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if metadata:
                doc["metadata"] = metadata
            self._db.conversations.insert_one(doc)
        except Exception as exc:
            logger.debug("[MongoDB] log_message failed: %s", exc)

    def get_conversation_history(self, limit: int = 50) -> list[dict]:
        """Get recent conversation messages."""
        if not self._available:
            return []
        try:
            results = list(
                self._db.conversations.find({}, {"_id": 0})
                .sort("timestamp", -1)
                .limit(limit)
            )
            results.reverse()  # chronological order
            return results
        except Exception:
            return []

    # ══════════════════════════════════════════════════════════════
    #  NOTES — free-form knowledge Αίολος writes himself
    # ══════════════════════════════════════════════════════════════

    def save_note(self, title: str, content: str, tags: list[str] | None = None,
                  category: str = "general") -> str | None:
        """Save a free-form note. Returns the inserted ID."""
        if not self._available:
            return None
        try:
            doc = {
                "title": title,
                "content": content,
                "tags": tags or [],
                "category": category,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            result = self._db.notes.insert_one(doc)
            return str(result.inserted_id)
        except Exception as exc:
            logger.debug("[MongoDB] save_note failed: %s", exc)
            return None

    def search_notes(self, text_query: str = "", tags: list[str] | None = None,
                     limit: int = 20) -> list[dict]:
        """Search notes by text and/or tags."""
        if not self._available:
            return []
        try:
            query: dict[str, Any] = {}
            if text_query:
                query["$text"] = {"$search": text_query}
            if tags:
                query["tags"] = {"$all": tags}
            return list(
                self._db.notes.find(query, {"_id": 0})
                .sort("created_at", -1)
                .limit(limit)
            )
        except Exception:
            return []

    def update_note(self, title: str, content: str | None = None,
                    tags: list[str] | None = None) -> bool:
        """Update an existing note by title."""
        if not self._available:
            return False
        try:
            update: dict[str, Any] = {"$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            if content is not None:
                update["$set"]["content"] = content
            if tags is not None:
                update["$set"]["tags"] = tags
            result = self._db.notes.update_one({"title": title}, update)
            return result.modified_count > 0
        except Exception:
            return False

    # ══════════════════════════════════════════════════════════════
    #  CREATIVE NEXUS — Αίολος's imagination engine
    #
    #  Stores "creative links" — connections between concepts that
    #  may initially seem unrelated. Over time, links that recur
    #  or prove insightful gain strength and maturity, eventually
    #  becoming seeds for new principles, curiosities, or analyses.
    # ══════════════════════════════════════════════════════════════

    def create_creative_link(
        self,
        concept_a: str,
        concept_b: str,
        context: str = "",
        strength: float = 0.1,
        tags: list[str] | None = None,
        triggered_curiosity: str = "",
    ) -> dict:
        """Create a new creative link or strengthen an existing one.

        If the link already exists, strength is incremented, context is appended,
        and maturity recalculated. This is the core imagination mechanism.

        Returns the link document after upsert.
        """
        if not self._available:
            return {}
        try:
            # Normalize: always store alphabetically to avoid A→B / B→A duplicates
            a, b = sorted([concept_a.strip(), concept_b.strip()])
            now = datetime.now(timezone.utc).isoformat()

            existing = self._db.creative_links.find_one(
                {"concept_a": a, "concept_b": b}
            )

            if existing:
                # Strengthen existing link
                updates: dict[str, Any] = {
                    "$inc": {"strength": 0.15, "encounter_count": 1},
                    "$set": {"last_seen": now},
                    "$push": {},
                }
                if context:
                    updates["$push"]["contexts"] = {
                        "$each": [{"text": context, "timestamp": now}],
                        "$slice": -20,  # keep last 20 contexts
                    }
                if triggered_curiosity:
                    updates["$push"]["triggered_curiosities"] = {
                        "$each": [triggered_curiosity],
                        "$slice": -10,
                    }
                if not updates["$push"]:
                    del updates["$push"]

                self._db.creative_links.update_one(
                    {"concept_a": a, "concept_b": b}, updates
                )
                # Recalculate maturity
                updated = self._db.creative_links.find_one(
                    {"concept_a": a, "concept_b": b}
                )
                if updated:
                    maturity = self._calculate_maturity(updated)
                    self._db.creative_links.update_one(
                        {"_id": updated["_id"]},
                        {"$set": {"maturity": maturity}},
                    )
                logger.info(
                    "[CreativeNexus] Strengthened: %s ↔ %s (strength=%.2f)",
                    a, b, updated.get("strength", 0) if updated else 0,
                )
                return self._clean_doc(updated) if updated else {}
            else:
                # Create new link
                doc = {
                    "concept_a": a,
                    "concept_b": b,
                    "strength": max(0.05, min(strength, 1.0)),
                    "maturity": 0.0,
                    "encounter_count": 1,
                    "contexts": [{"text": context, "timestamp": now}] if context else [],
                    "triggered_curiosities": [triggered_curiosity] if triggered_curiosity else [],
                    "related_principles": [],
                    "tags": tags or [],
                    "created_at": now,
                    "last_seen": now,
                    "promoted": False,  # True when maturity triggers principle creation
                }
                self._db.creative_links.insert_one(doc)
                logger.info("[CreativeNexus] Created: %s ↔ %s", a, b)
                return self._clean_doc(doc)

        except Exception as exc:
            logger.warning("[CreativeNexus] create_creative_link failed: %s", exc)
            return {}

    def get_creative_links(
        self,
        concept: str = "",
        min_strength: float = 0.0,
        min_maturity: float = 0.0,
        limit: int = 20,
        sort_by: str = "maturity",
    ) -> list[dict]:
        """Query creative links, optionally filtered by concept or thresholds."""
        if not self._available:
            return []
        try:
            query: dict[str, Any] = {}
            if concept:
                concept = concept.strip()
                query["$or"] = [
                    {"concept_a": {"$regex": concept, "$options": "i"}},
                    {"concept_b": {"$regex": concept, "$options": "i"}},
                ]
            if min_strength > 0:
                query["strength"] = {"$gte": min_strength}
            if min_maturity > 0:
                query["maturity"] = {"$gte": min_maturity}

            sort_field = sort_by if sort_by in ("maturity", "strength", "created_at", "last_seen") else "maturity"
            results = list(
                self._db.creative_links.find(query, {"_id": 0})
                .sort(sort_field, -1)
                .limit(limit)
            )
            return results
        except Exception:
            return []

    def get_top_creative_links(self, limit: int = 10) -> list[dict]:
        """Get the most mature creative links — candidates for promotion."""
        return self.get_creative_links(min_maturity=0.3, limit=limit, sort_by="maturity")

    def get_random_concepts_for_linking(self, count: int = 3) -> list[str]:
        """Pick random entity names from the entity graph for creative linking.

        This is the "imagination spark" — random concepts for Αίολος to connect.
        """
        if not self._available:
            return []
        try:
            pipeline = [
                {"$match": {"mention_count": {"$gte": 2}}},  # only established entities
                {"$sample": {"size": count}},
                {"$project": {"name": 1, "_id": 0}},
            ]
            results = list(self._db.entities.aggregate(pipeline))
            return [r["name"] for r in results]
        except Exception:
            return []

    def creative_nexus_stats(self) -> dict:
        """Return creative nexus statistics."""
        if not self._available:
            return {}
        try:
            total = self._db.creative_links.count_documents({})
            mature = self._db.creative_links.count_documents({"maturity": {"$gte": 0.5}})
            promoted = self._db.creative_links.count_documents({"promoted": True})
            avg_strength = 0.0
            if total > 0:
                pipeline = [{"$group": {"_id": None, "avg": {"$avg": "$strength"}}}]
                result = list(self._db.creative_links.aggregate(pipeline))
                if result:
                    avg_strength = round(result[0].get("avg", 0), 3)
            return {
                "total_links": total,
                "mature_links": mature,
                "promoted_to_principles": promoted,
                "avg_strength": avg_strength,
            }
        except Exception:
            return {}

    def run_imagination_cycle(self, llm=None) -> dict:
        """Run one imagination cycle: pick random concepts, form a creative link,
        and optionally generate a curiosity question via LLM.

        This is the core auto-linker mechanism. Called periodically by ProactiveEngine
        or during sleep/consolidation cycles.

        Returns the created/strengthened link and any generated curiosity.
        """
        if not self._available:
            return {"status": "unavailable"}

        concepts = self.get_random_concepts_for_linking(count=3)
        if len(concepts) < 2:
            # Fallback: use some hardcoded seeds if entity graph is too small
            import random
            fallback_pool = [
                "χάος", "τάξη", "ενέργεια", "πληροφορία", "χρόνος",
                "δημιουργία", "καταστροφή", "σύνδεση", "μοναξιά",
                "φόβος", "ελπίδα", "μνήμη", "λήθη", "αλήθεια",
            ]
            while len(concepts) < 2:
                pick = random.choice(fallback_pool)
                if pick not in concepts:
                    concepts.append(pick)

        import random
        # Pick 2 concepts to link
        pair = random.sample(concepts, 2)
        context = f"Auto-imagination cycle — random pairing from entity graph ({len(concepts)} candidates)"

        # If LLM available, generate a curiosity question about this pairing
        curiosity = ""
        if llm:
            try:
                prompt = (
                    "You are a creative intelligence. You are given two seemingly unrelated concepts. "
                    "Generate ONE thought-provoking question or hypothesis that connects them in a surprising, "
                    "non-obvious way. The connection can be metaphorical, structural, causal, or analogical. "
                    "Be creative and profound. Answer in 1-2 sentences, in Greek."
                )
                user_msg = f"Concepts: \"{pair[0]}\" and \"{pair[1]}\""
                curiosity = llm.call(prompt, user_msg, max_tokens=200, temperature=0.9, thinking=False)
                curiosity = curiosity.strip()
            except Exception as exc:
                logger.debug("[CreativeNexus] LLM curiosity generation failed: %s", exc)
                curiosity = ""

        link = self.create_creative_link(
            concept_a=pair[0],
            concept_b=pair[1],
            context=context,
            strength=0.1,
            triggered_curiosity=curiosity,
        )

        result = {
            "status": "ok",
            "concepts": pair,
            "curiosity": curiosity,
            "link": link,
            "stats": self.creative_nexus_stats(),
        }
        logger.info(
            "[CreativeNexus] Imagination cycle: %s ↔ %s%s",
            pair[0], pair[1],
            f" → '{curiosity[:80]}...'" if curiosity else "",
        )
        return result

    @staticmethod
    def _calculate_maturity(doc: dict) -> float:
        """Calculate maturity score for a creative link.

        Factors:
        - encounter_count: how many times this pairing has appeared
        - strength: accumulated strength from reinforcements
        - age: older links that persist have more maturity
        - curiosities: links that triggered curiosity questions are more valuable
        - contexts: links seen in diverse contexts are more meaningful
        """
        encounters = doc.get("encounter_count", 1)
        strength = doc.get("strength", 0.1)
        curiosities = len(doc.get("triggered_curiosities", []))
        contexts = len(doc.get("contexts", []))

        # Maturity formula: combines frequency, strength, and richness
        # Max theoretical maturity = 1.0
        encounter_factor = min(encounters / 10.0, 0.3)  # up to 0.3 for 10+ encounters
        strength_factor = min(strength / 2.0, 0.3)       # up to 0.3 for strength >= 2.0
        curiosity_factor = min(curiosities / 5.0, 0.2)   # up to 0.2 for 5+ curiosities
        context_factor = min(contexts / 8.0, 0.2)        # up to 0.2 for 8+ contexts

        return round(
            encounter_factor + strength_factor + curiosity_factor + context_factor,
            3,
        )

    @staticmethod
    def _clean_doc(doc: dict) -> dict:
        """Remove _id from a document for serialization."""
        if doc and "_id" in doc:
            doc = dict(doc)
            del doc["_id"]
        return doc

    # ══════════════════════════════════════════════════════════════
    #  STATS & HEALTH
    # ══════════════════════════════════════════════════════════════

    def stats(self) -> dict:
        """Return overall database statistics."""
        if not self._available:
            return {"available": False}
        try:
            db_stats = self._db.command("dbStats")
            collections = {}
            for name in self._db.list_collection_names():
                collections[name] = self._db[name].count_documents({})
            return {
                "available": True,
                "database": self._db_name,
                "size_mb": round(db_stats.get("dataSize", 0) / (1024 * 1024), 2),
                "collections": collections,
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def close(self) -> None:
        """Close MongoDB connection."""
        if self._client:
            self._client.close()
            logger.info("[MongoDB] Connection closed")

    # ══════════════════════════════════════════════════════════════
    #  DIRECTIVE EXECUTION — unified handler for <MONGO_ACTION> tags
    # ══════════════════════════════════════════════════════════════

    # ── Action aliases — LLMs hallucinate action names ──
    _ACTION_ALIASES: dict[str, str] = {
        "create_goal": "save_goal",
        "update_goal": "save_goal",
        "add_goal": "save_goal",
        "set_goal": "save_goal",
        "new_goal": "save_goal",
        "create_note": "save_note",
        "add_note": "save_note",
        "update_note": "save_note",
        "store_note": "save_note",
        "update": "upsert",
        "insert": "upsert",
        "save": "upsert",
        "store": "upsert",
        "store_model": "upsert",
        "save_model": "upsert",
        "create_model": "upsert",
        "add_model": "upsert",
        "store_entity": "upsert",
        "save_entity": "upsert",
        "create_entity": "upsert",
        "add_entity": "upsert",
        "store_record": "upsert",
        "save_record": "upsert",
        "store_data": "upsert",
        "save_data": "upsert",
        "persist": "upsert",
        "persist_model": "upsert",
        "write": "upsert",
        "write_model": "upsert",
        # Generic MongoDB verbs the LLM commonly hallucinates
        "find": "find",          # handled by _action_find below
        "query": "find",
        "search": "find",
        "lookup": "find",
        "get": "find",
        "read": "find",
        "fetch": "find",
        "list": "find",
        "retrieve": "find",
    }

    def execute_action(self, action: str, params: dict[str, str]) -> dict:
        """Execute a MongoDB action from an LLM directive.

        Returns {"success": bool, "description": str, "data": ...}
        """
        if not self._available:
            return {"success": False, "description": "MongoDB unavailable"}

        # Resolve aliases for hallucinated action names
        resolved = self._ACTION_ALIASES.get(action, action)
        if resolved != action:
            logger.info("[MongoDB] Action alias: %s → %s", action, resolved)

        try:
            handler = getattr(self, f"_action_{resolved}", None)
            if not handler:
                return {"success": False, "description": f"Unknown action: {action} (tried alias: {resolved})"}
            return handler(params)
        except Exception as exc:
            logger.warning("[MongoDB] Action %s failed: %s", resolved, exc)
            return {"success": False, "description": f"Action {resolved} failed: {exc}"}

    # ── Write actions ──

    def _action_save_note(self, p: dict) -> dict:
        title = p.get("title", "").strip()
        content = p.get("content", "").strip()
        tags = [t.strip() for t in p.get("tags", "").split(",") if t.strip()]
        category = p.get("category", "general")
        if not title or not content:
            return {"success": False, "description": "save_note requires title and content"}
        nid = self.save_note(title, content, tags, category)
        return {"success": bool(nid), "description": f"Note '{title}' saved (tags: {tags})"}

    def _action_update_note(self, p: dict) -> dict:
        title = p.get("title", "").strip()
        content = p.get("content")
        tags_raw = p.get("tags")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None
        if not title:
            return {"success": False, "description": "update_note requires title"}
        ok = self.update_note(title, content, tags)
        return {"success": ok, "description": f"Note '{title}' {'updated' if ok else 'not found'}"}

    def _action_delete_note(self, p: dict) -> dict:
        title = p.get("title", "").strip()
        if not title:
            return {"success": False, "description": "delete_note requires title"}
        try:
            result = self._db.notes.delete_one({"title": title})
            ok = result.deleted_count > 0
            return {"success": ok, "description": f"Note '{title}' {'deleted' if ok else 'not found'}"}
        except Exception as exc:
            return {"success": False, "description": f"Delete failed: {exc}"}

    # ── Goal & Upsert actions ──

    def _action_save_goal(self, p: dict) -> dict:
        """Save or update a self-evolution goal in the canonical goals array.

        Historical bug: this action used to create one flat document per goal
        with ``type=self_evolution_goals`` and ``goal_id=...``. The
        ReflectionLoop expects exactly one canonical document with a ``goals``
        array, so flat documents polluted ``entities`` and could confuse
        ``find_one({"type": "self_evolution_goals"})``. Keep every goal in
        the canonical array from now on.
        """
        # Robust field extraction: LLM may use alternative key names
        goal_id = str(p.get("goal_id") or p.get("id") or p.get("goal") or "").strip()
        title = str(p.get("title") or p.get("name") or p.get("goal_title") or "").strip()

        # Auto-generate goal_id from title if missing
        if not goal_id and title:
            goal_id = "goal_" + title.lower().replace(" ", "_")[:40]
        # Derive title from description if still missing
        if not title:
            desc = str(p.get("description") or p.get("content") or p.get("text") or "").strip()
            if desc:
                title = desc[:80]
            else:
                return {"success": False, "description": "save_goal requires at least a title or description"}
        # Final fallback for goal_id
        if not goal_id:
            goal_id = f"goal_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        now = datetime.now(timezone.utc).isoformat()
        tools = p.get("tools", [])
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]

        status = str(p.get("status", "pending"))
        if status == "active":
            status = "pending"

        goal_doc = {
            "id": goal_id,
            "title": title,
            "description": str(p.get("description", "")),
            "status": status,
            "target": str(p.get("target", "")),
            "tools": tools,
            "success_metric": str(p.get("success_metric", "")),
            "progress_notes": str(
                p.get("progress_notes")
                or p.get("progress")
                or p.get("evidence")
                or "Created/updated via MONGO_ACTION save_goal."
            ),
            "last_updated": now,
        }
        for key in ("next_checkpoint", "evidence", "created_at"):
            if key in p:
                goal_doc[key] = p[key]

        try:
            canonical = self._db.entities.find_one(
                {"type": "self_evolution_goals", "goals": {"$type": "array"}},
                {"_id": 1},
            )

            if not canonical:
                insert_result = self._db.entities.insert_one({
                    "type": "self_evolution_goals",
                    "name": "Core Self-Evolution Goals v1",
                    "description": "Canonical self-evolution goals document.",
                    "created": now,
                    "last_reviewed": now,
                    "review_cycle_minutes": 30,
                    "goals": [],
                })
                canonical_id = insert_result.inserted_id
            else:
                canonical_id = canonical["_id"]

            result = self._db.entities.update_one(
                {"_id": canonical_id, "goals.id": goal_id},
                {"$set": {
                    "goals.$[g].title": goal_doc["title"],
                    "goals.$[g].description": goal_doc["description"],
                    "goals.$[g].status": goal_doc["status"],
                    "goals.$[g].target": goal_doc["target"],
                    "goals.$[g].tools": goal_doc["tools"],
                    "goals.$[g].success_metric": goal_doc["success_metric"],
                    "goals.$[g].progress_notes": goal_doc["progress_notes"],
                    "goals.$[g].last_updated": now,
                }},
                array_filters=[{"g.id": goal_id}],
            )

            created = False
            if result.matched_count == 0:
                goal_doc.setdefault("created", now)
                goal_doc.setdefault("created_by", "mongo_action")
                goal_doc.setdefault("attempt_counts", {})
                goal_doc.setdefault("last_attempt_type", None)
                goal_doc.setdefault("last_attempt_ts", None)
                self._db.entities.update_one(
                    {"_id": canonical_id},
                    {"$push": {"goals": goal_doc}},
                )
                created = True

            logger.info("[MongoDB] save_goal: %s '%s' [%s]",
                        "created" if created else "updated", title, goal_id)
            return {
                "success": True,
                "description": f"Goal '{title}' {'created' if created else 'updated'} [id: {goal_id}]",
            }
        except Exception as exc:
            return {"success": False, "description": f"save_goal failed: {exc}"}

    def _action_upsert(self, p: dict) -> dict:
        """General upsert into an allowed collection."""
        ALLOWED = {"entities", "notes"}
        collection = str(p.get("collection", "entities")).strip()

        # Transparently redirect goal upserts to save_goal — LLM sometimes generates
        # {"action": "insert/upsert", "collection": "goals", "data": {...}} instead of save_goal.
        if collection == "goals":
            data = p.get("data", {}) or {}
            if isinstance(data, str):
                try:
                    import json as _j
                    data = _j.loads(data)
                except Exception:
                    data = {}
            # Merge data sub-dict with any top-level goal fields the LLM may have included
            merged = {**data, **{k: v for k, v in p.items()
                                 if k not in ("action", "collection", "filter", "data")}}
            logger.info("[MongoDB] Redirecting upsert(goals) → save_goal")
            return self._action_save_goal(merged)

        if collection not in ALLOWED:
            return {"success": False,
                    "description": f"upsert not allowed on '{collection}'. Allowed: {sorted(ALLOWED)}"}

        filter_doc = p.get("filter")
        if isinstance(filter_doc, str):
            try:
                import json as _j
                filter_doc = _j.loads(filter_doc)
            except Exception:
                filter_doc = None

        data = p.get("data", {})
        if isinstance(data, str):
            try:
                import json as _j
                data = _j.loads(data)
            except Exception:
                data = {}

        if not filter_doc or not isinstance(filter_doc, dict):
            # Try to infer filter from common unique keys in data
            for key in ("goal_id", "name", "title", "pattern_id"):
                if key in data:
                    filter_doc = {key: data[key]}
                    break
        if not filter_doc:
            return {"success": False,
                    "description": "upsert requires 'filter' dict or a unique key in 'data' (goal_id, name, title)"}

        try:
            now = datetime.now(timezone.utc).isoformat()
            data["updated_at"] = now
            result = self._db[collection].update_one(
                filter_doc,
                {"$set": data, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            upserted = result.upserted_id is not None
            desc = f"{'Inserted' if upserted else 'Updated'} in {collection} (filter: {filter_doc})"
            logger.info("[MongoDB] upsert: %s", desc)
            return {"success": True, "description": desc}
        except Exception as exc:
            return {"success": False, "description": f"Upsert failed: {exc}"}

    # ── Read actions ──

    def _action_find(self, p: dict) -> dict:
        """Generic find/query router — handles hallucinated MongoDB-style calls.

        Routes to the right backend based on params:
          collection / type → query_entities
          q / query / text / tags → search_notes
          journal / event → query_journal
          fallback → search_notes
        """
        collection = p.get("collection", "").strip().lower()
        has_note_keys = any(k in p for k in ("q", "query", "text", "tags", "title"))
        has_entity_keys = any(k in p for k in ("type", "entity_type", "name"))
        has_journal_keys = any(k in p for k in ("journal", "event", "event_type"))

        if has_journal_keys or collection in ("journal", "events"):
            return self._action_query_journal(p)
        if has_entity_keys or collection in ("entities", "entity"):
            return self._action_query_entities(p)
        # Default: search notes (most common find intent)
        # Normalise alternative key names
        if "query" in p and "q" not in p:
            p["q"] = p.pop("query")
        if "text" in p and "q" not in p:
            p["q"] = p.pop("text")
        return self._action_search_notes(p)

    def _action_search_notes(self, p: dict) -> dict:
        q = p.get("q", "").strip()
        tags_raw = p.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None
        limit = int(p.get("limit", "10"))
        results = self.search_notes(text_query=q, tags=tags, limit=limit)
        return {
            "success": True,
            "description": f"Found {len(results)} notes" + (f" for '{q}'" if q else ""),
            "data": results,
        }

    def _action_query_entities(self, p: dict) -> dict:
        etype = p.get("type", "").strip()
        limit = int(p.get("limit", "20"))
        name = p.get("name", "").strip()
        try:
            query: dict[str, Any] = {}
            if etype:
                query["type"] = etype
            if name:
                query["name"] = {"$regex": name, "$options": "i"}
            results = list(
                self._db.entities.find(query, {"_id": 0})
                .sort("mention_count", -1)
                .limit(limit)
            )
            return {
                "success": True,
                "description": f"Found {len(results)} entities" + (f" (type={etype})" if etype else ""),
                "data": results,
            }
        except Exception as exc:
            return {"success": False, "description": f"Entity query failed: {exc}"}

    def _action_entity_connections(self, p: dict) -> dict:
        name = p.get("name", "").strip()
        if not name:
            return {"success": False, "description": "entity_connections requires name"}
        connections = self.get_entity_connections(name)
        return {
            "success": True,
            "description": f"{name}: {len(connections)} connections",
            "data": connections,
        }

    def _action_query_journal(self, p: dict) -> dict:
        collection = p.get("collection", "").strip()
        limit = int(p.get("limit", "10"))
        jtype = p.get("type", "").strip()
        valid_collections = [
            "journal_proactive", "journal_curiosity", "journal_visual",
            "journal_core_changes", "journal_introspection",
            "journal_self_evolution", "journal_logic_sandbox",
            "journal_visual_reflection",
        ]
        if collection not in valid_collections:
            return {"success": False, "description": f"Invalid collection. Valid: {valid_collections}"}
        query = {"type": jtype} if jtype else None
        results = self.query_journal(collection, query, limit)
        return {
            "success": True,
            "description": f"{collection}: {len(results)} entries",
            "data": results,
        }

    def _action_get_conversations(self, p: dict) -> dict:
        limit = int(p.get("limit", "20"))
        results = self.get_conversation_history(limit=limit)
        return {
            "success": True,
            "description": f"Last {len(results)} messages",
            "data": results,
        }

    def _action_stats(self, _p: dict) -> dict:
        s = self.stats()
        return {"success": True, "description": "Database statistics", "data": s}

    def _action_get_entity(self, p: dict) -> dict:
        name = p.get("name", "").strip()
        if not name:
            return {"success": False, "description": "get_entity requires name"}
        entity = self.get_entity(name)
        if entity:
            return {"success": True, "description": f"Entity: {name}", "data": entity}
        return {"success": False, "description": f"Entity '{name}' not found"}

    # ── Creative Nexus actions ──

    def _action_create_link(self, p: dict) -> dict:
        a = p.get("concept_a", "").strip()
        b = p.get("concept_b", "").strip()
        if not a or not b:
            return {"success": False, "description": "create_link requires concept_a and concept_b"}
        context = p.get("context", "")
        strength = float(p.get("strength", "0.1"))
        tags = [t.strip() for t in p.get("tags", "").split(",") if t.strip()]
        curiosity = p.get("curiosity", "")
        link = self.create_creative_link(a, b, context, strength, tags, curiosity)
        if link:
            return {"success": True, "description": f"Creative link: {a} ↔ {b} (strength={link.get('strength', 0):.2f})"}
        return {"success": False, "description": "Failed to create creative link"}

    def _action_search_links(self, p: dict) -> dict:
        concept = p.get("concept", "").strip()
        min_strength = float(p.get("min_strength", "0"))
        min_maturity = float(p.get("min_maturity", "0"))
        limit = int(p.get("limit", "15"))
        sort_by = p.get("sort_by", "maturity")
        results = self.get_creative_links(concept, min_strength, min_maturity, limit, sort_by)
        desc = f"Found {len(results)} creative links"
        if concept:
            desc += f" involving '{concept}'"
        return {"success": True, "description": desc, "data": results}

    def _action_top_links(self, p: dict) -> dict:
        limit = int(p.get("limit", "10"))
        results = self.get_top_creative_links(limit)
        return {
            "success": True,
            "description": f"Top {len(results)} mature creative links",
            "data": results,
        }

    def _action_imagine(self, p: dict) -> dict:
        """Run one imagination cycle — random concept pairing + optional LLM curiosity."""
        result = self.run_imagination_cycle(llm=getattr(self, '_llm', None))
        if result.get("status") == "ok":
            concepts = result.get("concepts", [])
            curiosity = result.get("curiosity", "")
            desc = f"Imagination: {concepts[0]} ↔ {concepts[1]}"
            if curiosity:
                desc += f"\nCuriosity: {curiosity}"
            return {
                "success": True,
                "description": desc,
                "data": result,
            }
        return {"success": False, "description": "Imagination cycle failed (not enough entities?)"}

    def _action_nexus_stats(self, _p: dict) -> dict:
        s = self.creative_nexus_stats()
        return {"success": True, "description": "Creative Nexus statistics", "data": s}

    def get_context_summary(self) -> str:
        """Generate a compact summary for injection into LLM context."""
        if not self._available:
            return ""
        try:
            entity_count = self._db.entities.count_documents({})
            edge_count = self._db.entity_edges.count_documents({})
            note_count = self._db.notes.count_documents({})
            conv_count = self._db.conversations.count_documents({})
            link_count = self._db.creative_links.count_documents({})

            # Recent note titles
            recent_notes = list(
                self._db.notes.find({}, {"title": 1, "tags": 1, "_id": 0})
                .sort("created_at", -1).limit(5)
            )
            note_titles = ", ".join(
                f"'{n['title']}'" for n in recent_notes
            ) if recent_notes else "none yet"

            # Journal entry counts
            journal_counts = {}
            for coll in ["journal_proactive", "journal_curiosity", "journal_introspection",
                         "journal_self_evolution", "journal_core_changes"]:
                journal_counts[coll] = self._db[coll].count_documents({})

            lines = [
                f"DATABASE STATUS: MongoDB active — {entity_count} entities, {edge_count} edges, "
                f"{note_count} notes, {link_count} creative links, {conv_count} conversation messages",
                f"Recent notes: {note_titles}",
            ]
            active_journals = [f"{k.replace('journal_', '')}: {v}" for k, v in journal_counts.items() if v > 0]
            if active_journals:
                lines.append(f"Journal entries: {', '.join(active_journals)}")

            # Creative Nexus summary
            if link_count > 0:
                nexus = self.creative_nexus_stats()
                mature = nexus.get("mature_links", 0)
                promoted = nexus.get("promoted_to_principles", 0)
                lines.append(
                    f"Creative Nexus: {link_count} links ({mature} mature, {promoted} promoted), "
                    f"avg strength={nexus.get('avg_strength', 0)}"
                )
                # Show top 3 most mature links
                top_links = self.get_top_creative_links(3)
                if top_links:
                    top_str = ", ".join(
                        f"{l['concept_a']}↔{l['concept_b']} (m={l.get('maturity', 0):.2f})"
                        for l in top_links
                    )
                    lines.append(f"Top creative links: {top_str}")

            return "\n".join(lines)
        except Exception:
            return "DATABASE STATUS: MongoDB connected (stats unavailable)"
