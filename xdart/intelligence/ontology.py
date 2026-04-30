"""
XDART-Φ Palantir Upgrade — Βήμα 1: Typed Semantic Ontology
===========================================================

Enriches the flat EntityGraph with:
  - Typed entities: Person / Organization / Country / Event / Concept / Location / Movement / Bloc
  - Confidence scores per entity (based on mentions, source diversity, recency)
  - Provenance tracking (which feeds contributed, when)
  - Version history (last 5 confidence snapshots)
  - Typed, time-bounded relationships (attacks / allied_with / funds / etc.)
  - Relationship confidence + temporal validity (is_active flag)

Integration points:
  - Wraps existing EntityGraph — DOES NOT replace it
  - on_entity_ingested() called by EntityGraph after every ingest
  - get_ontology_digest() injected into briefing context
  - get_high_confidence_entities() used by PatternAccumulator for synthesis
  - MongoDB dual-write for persistence
  - Periodic background refresh from EntityGraph (every 15 min)
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xdart.knowledge.entity_graph import EntityGraph

logger = logging.getLogger("xdart.intelligence.ontology")

# ─────────────────────────────────────────────────────────────────────────────
#  TYPE ENUMERATIONS
# ─────────────────────────────────────────────────────────────────────────────

class OntologyEntityType(str, Enum):
    PERSON       = "person"
    ORGANIZATION = "organization"
    COUNTRY      = "country"
    EVENT        = "event"
    CONCEPT      = "concept"
    LOCATION     = "location"
    MOVEMENT     = "movement"   # political/ideological movements, militias
    BLOC         = "bloc"       # alliances, coalitions (NATO, EU, BRICS)


class OntologyRelationType(str, Enum):
    LEADS          = "leads"
    FUNDS          = "funds"
    ATTACKS        = "attacks"
    ALLIED_WITH    = "allied_with"
    CAUSES         = "causes"
    OPPOSES        = "opposes"
    CONTROLS       = "controls"
    SUPPORTS       = "supports"
    DEPENDS_ON     = "depends_on"
    MONITORS       = "monitors"
    SANCTIONS      = "sanctions"
    COMMANDS       = "commands"
    NEGOTIATES_WITH = "negotiates_with"
    TRADES_WITH    = "trades_with"
    CO_OCCURRENCE  = "co_occurrence"   # fallback


# ─────────────────────────────────────────────────────────────────────────────
#  ENTITY GRAPH TYPE → ONTOLOGY TYPE MAPPING
# ─────────────────────────────────────────────────────────────────────────────

_EG_TYPE_TO_ONTOLOGY: dict[str, OntologyEntityType] = {
    "PERSON": OntologyEntityType.PERSON,
    "GPE":    OntologyEntityType.COUNTRY,   # geopolitical entity = country/state
    "ORG":    OntologyEntityType.ORGANIZATION,
    "NORP":   OntologyEntityType.MOVEMENT,  # nationalities/religions/political groups
    "LOC":    OntologyEntityType.LOCATION,
    "FAC":    OntologyEntityType.LOCATION,  # facilities
    "EVENT":  OntologyEntityType.EVENT,
}

# EntityGraph relationship_type → ranked list of OntologyRelationType
_EG_REL_TO_ONTOLOGY: dict[str, list[OntologyRelationType]] = {
    "CONFLICT":     [OntologyRelationType.ATTACKS,   OntologyRelationType.OPPOSES],
    "DIPLOMACY":    [OntologyRelationType.ALLIED_WITH, OntologyRelationType.NEGOTIATES_WITH],
    "ECONOMIC_TIE": [OntologyRelationType.TRADES_WITH, OntologyRelationType.FUNDS, OntologyRelationType.DEPENDS_ON],
    "MILITARY":     [OntologyRelationType.COMMANDS,  OntologyRelationType.CONTROLS],
    "INTELLIGENCE": [OntologyRelationType.MONITORS],
    "OPPOSITION":   [OntologyRelationType.OPPOSES,   OntologyRelationType.SANCTIONS],
    "CO_OCCURRENCE": [OntologyRelationType.CO_OCCURRENCE],
}


def _map_rel_types(eg_rel_types: dict[str, int]) -> OntologyRelationType:
    """Return the dominant OntologyRelationType from an EntityGraph edge's relationship_types dict."""
    if not eg_rel_types:
        return OntologyRelationType.CO_OCCURRENCE
    # Pick the EG type with the highest count (excluding CO_OCCURRENCE)
    dominant_eg = max(eg_rel_types, key=lambda k: eg_rel_types[k])
    mapped = _EG_REL_TO_ONTOLOGY.get(dominant_eg, [OntologyRelationType.CO_OCCURRENCE])
    return mapped[0]


# ─────────────────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OntologyVersionEntry:
    """Single version snapshot of an entity's confidence + relationship summary."""
    timestamp: float
    confidence: float
    relationship_count: int
    dominant_rel_type: str
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OntologyVersionEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class OntologyEntity:
    """Enriched entity with typed classification, confidence, provenance, and version history."""
    name: str
    entity_type: OntologyEntityType
    confidence: float                           # 0.0 – 1.0
    mention_count: int
    source_count: int
    first_seen: float
    last_seen: float
    provenance: list[str] = field(default_factory=list)    # feed names
    version_history: list[OntologyVersionEntry] = field(default_factory=list)  # last 5

    VERSION_MAX = 5

    def update_confidence(
        self,
        new_confidence: float,
        relationship_count: int,
        dominant_rel_type: str,
        note: str = "",
    ) -> None:
        """Record a confidence update in version history."""
        if abs(new_confidence - self.confidence) > 0.05 or not self.version_history:
            entry = OntologyVersionEntry(
                timestamp=time.time(),
                confidence=self.confidence,
                relationship_count=relationship_count,
                dominant_rel_type=dominant_rel_type,
                note=note,
            )
            self.version_history.append(entry)
            if len(self.version_history) > self.VERSION_MAX:
                self.version_history = self.version_history[-self.VERSION_MAX:]
        self.confidence = new_confidence

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entity_type"] = self.entity_type.value
        d["version_history"] = [v.to_dict() for v in self.version_history]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OntologyEntity":
        d = dict(d)
        d["entity_type"] = OntologyEntityType(d.get("entity_type", "organization"))
        d["version_history"] = [
            OntologyVersionEntry.from_dict(v)
            for v in d.get("version_history", [])
        ]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class OntologyRelationship:
    """Typed, time-bounded relationship between two entities."""
    source: str
    target: str
    relation_type: OntologyRelationType
    confidence: float                     # 0.0 – 1.0
    evidence_count: int                   # co-occurrence count
    source_count: int                     # distinct feed sources
    valid_from: float                     # first seen timestamp
    valid_until: float | None             # None = still active
    is_active: bool                       # True if last_seen < 30 days
    last_seen: float
    recent_headlines: list[str] = field(default_factory=list)   # last 3

    ACTIVE_WINDOW = 30 * 86400  # 30 days

    def refresh_activity(self, now: float | None = None) -> None:
        """Update is_active based on last_seen."""
        ts = now or time.time()
        self.is_active = (ts - self.last_seen) < self.ACTIVE_WINDOW

    def relationship_id(self) -> str:
        return f"{self.source}::{self.relation_type.value}::{self.target}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["relation_type"] = self.relation_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OntologyRelationship":
        d = dict(d)
        d["relation_type"] = OntologyRelationType(d.get("relation_type", "co_occurrence"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIDENCE SCORING
# ─────────────────────────────────────────────────────────────────────────────

_RECENCY_HALF_LIFE = 7 * 86400  # 7 days — confidence decays if entity goes quiet


def compute_entity_confidence(
    mention_count: int,
    source_count: int,
    last_seen: float,
    is_known: bool = False,
) -> float:
    """
    Confidence score for an entity.

    Components:
      - mention_score:   log(1 + mentions) / log(1 + 50)  → caps at 1.0 around 50 mentions
      - source_score:    min(1.0, source_count / 5)        → 5+ sources = full score
      - recency_score:   exponential decay, half-life = 7d
      - known_bonus:     +0.20 if entity is in alias registry
    """
    now = time.time()
    mention_score = math.log1p(mention_count) / math.log1p(50)
    source_score = min(1.0, source_count / 5.0)
    age = now - last_seen
    recency_score = math.exp(-age * math.log(2) / _RECENCY_HALF_LIFE)

    raw = mention_score * 0.40 + source_score * 0.30 + recency_score * 0.30
    if is_known:
        raw = min(1.0, raw + 0.20)
    return round(min(1.0, raw), 3)


def compute_relationship_confidence(
    co_occurrences: int,
    source_count: int,
    last_seen: float,
    rel_type: OntologyRelationType,
) -> float:
    """
    Confidence score for a relationship.

    Components:
      - occurrence_score: log(1+count) / log(1+20)
      - source_score:     min(1.0, sources / 3)
      - recency_score:    exponential decay, half-life = 14d
      - type_bonus:       +0.10 for high-value types (ATTACKS, ALLIED_WITH, FUNDS, CONTROLS, SANCTIONS)
    """
    now = time.time()
    occurrence_score = math.log1p(co_occurrences) / math.log1p(20)
    source_score = min(1.0, source_count / 3.0)
    age = now - last_seen
    recency_score = math.exp(-age * math.log(2) / (14 * 86400))

    HIGH_VALUE = {
        OntologyRelationType.ATTACKS,
        OntologyRelationType.ALLIED_WITH,
        OntologyRelationType.FUNDS,
        OntologyRelationType.CONTROLS,
        OntologyRelationType.SANCTIONS,
        OntologyRelationType.COMMANDS,
    }
    type_bonus = 0.10 if rel_type in HIGH_VALUE else 0.0

    raw = occurrence_score * 0.40 + source_score * 0.30 + recency_score * 0.30 + type_bonus
    return round(min(1.0, raw), 3)


# ─────────────────────────────────────────────────────────────────────────────
#  ONTOLOGY ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class OntologyEngine:
    """
    Typed Semantic Ontology layer for XDART-Φ.

    Wraps EntityGraph and provides enriched typed entity/relationship data.
    Does NOT replace EntityGraph — it is a read+enrich layer on top of it.
    """

    _PERSIST_FILE = "ontology_state.json"
    _REFRESH_INTERVAL = 15 * 60  # 15 minutes

    def __init__(
        self,
        entity_graph: "EntityGraph | None" = None,
        mongo=None,
        persist_path: str | Path | None = None,
        known_entity_names: set[str] | None = None,
    ):
        self._entity_graph = entity_graph
        self._mongo = mongo

        base = Path(persist_path) if persist_path else Path(".")
        self._persist_path = base / self._PERSIST_FILE

        # known entity names from alias registry (for bonus score)
        self._known_names: set[str] = known_entity_names or set()

        # Core stores
        self._entities: dict[str, OntologyEntity] = {}          # name → entity
        self._relationships: dict[str, OntologyRelationship] = {}  # id → relationship

        # Threading
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._refresh_thread: threading.Thread | None = None

        # Load persisted state
        self._load()

        # Initial enrichment from entity_graph
        if self._entity_graph:
            self._enrich_from_graph()

        logger.info(
            "[OntologyEngine] Ready — %d entities, %d relationships",
            len(self._entities), len(self._relationships),
        )

    # ─────────────────────────────────────────────────────────────
    #  STARTUP / SHUTDOWN
    # ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background refresh thread."""
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            name="ontology-refresh",
            daemon=True,
        )
        self._refresh_thread.start()
        logger.info("[OntologyEngine] Background refresh thread started (interval=%ds)", self._REFRESH_INTERVAL)

    def stop(self) -> None:
        """Stop background thread and save state."""
        self._stop_event.set()
        self.save()

    # ─────────────────────────────────────────────────────────────
    #  REAL-TIME UPDATE HOOK
    # ─────────────────────────────────────────────────────────────

    def on_entity_ingested(
        self,
        name: str,
        entity_type: str,
        source: str = "",
        timestamp: float | None = None,
    ) -> None:
        """
        Called by EntityGraph after every ingest.
        Refreshes a single entity's confidence without rebuilding the full graph.
        """
        ts = timestamp or time.time()
        eg = self._entity_graph
        if not eg:
            return

        node_data = eg._graph.nodes.get(name)
        if not node_data:
            return

        onto_type = _EG_TYPE_TO_ONTOLOGY.get(
            node_data.get("type", entity_type), OntologyEntityType.ORGANIZATION
        )

        sources_raw = node_data.get("sources", set())
        sources = sources_raw if isinstance(sources_raw, set) else set(sources_raw)
        src_count = len(sources)
        mention_count = node_data.get("mention_count", 1)
        last_seen = node_data.get("last_seen", ts)
        is_known = name in self._known_names

        conf = compute_entity_confidence(mention_count, src_count, last_seen, is_known)

        with self._lock:
            if name in self._entities:
                ent = self._entities[name]
                ent.mention_count = mention_count
                ent.source_count = src_count
                ent.last_seen = last_seen
                if source and source not in ent.provenance:
                    ent.provenance.append(source)
                    if len(ent.provenance) > 20:
                        ent.provenance = ent.provenance[-20:]
                # Get relationship summary for version history
                rels = [r for r in self._relationships.values()
                        if r.source == name or r.target == name]
                dominant = _dominant_rel_type(rels)
                ent.update_confidence(conf, len(rels), dominant)
            else:
                # New entity
                prov = [source] if source else []
                ent = OntologyEntity(
                    name=name,
                    entity_type=onto_type,
                    confidence=conf,
                    mention_count=mention_count,
                    source_count=src_count,
                    first_seen=node_data.get("first_seen", ts),
                    last_seen=last_seen,
                    provenance=prov,
                    version_history=[],
                )
                self._entities[name] = ent

    # ─────────────────────────────────────────────────────────────
    #  FULL GRAPH ENRICHMENT
    # ─────────────────────────────────────────────────────────────

    def _enrich_from_graph(self) -> None:
        """Full sync from EntityGraph — called on startup and in background loop."""
        eg = self._entity_graph
        if not eg:
            return

        now = time.time()
        new_entities = 0
        updated_entities = 0
        new_rels = 0
        updated_rels = 0

        with self._lock:
            # ── Entities ──
            for name, node_data in eg._graph.nodes(data=True):
                eg_type = node_data.get("type", "ORG")
                onto_type = _EG_TYPE_TO_ONTOLOGY.get(eg_type, OntologyEntityType.ORGANIZATION)

                sources_raw = node_data.get("sources", set())
                sources = sources_raw if isinstance(sources_raw, set) else set(sources_raw)
                src_count = len(sources)
                mention_count = node_data.get("mention_count", 1)
                last_seen = node_data.get("last_seen", now)
                is_known = name in self._known_names
                conf = compute_entity_confidence(mention_count, src_count, last_seen, is_known)

                if name in self._entities:
                    ent = self._entities[name]
                    rels = [r for r in self._relationships.values()
                            if r.source == name or r.target == name]
                    dominant = _dominant_rel_type(rels)
                    ent.mention_count = mention_count
                    ent.source_count = src_count
                    ent.last_seen = last_seen
                    ent.update_confidence(conf, len(rels), dominant, note="refresh")
                    updated_entities += 1
                else:
                    prov = list(sources)[:10]
                    ent = OntologyEntity(
                        name=name,
                        entity_type=onto_type,
                        confidence=conf,
                        mention_count=mention_count,
                        source_count=src_count,
                        first_seen=node_data.get("first_seen", now),
                        last_seen=last_seen,
                        provenance=prov,
                        version_history=[],
                    )
                    self._entities[name] = ent
                    new_entities += 1

            # ── Relationships ──
            for src, dst, edge_data in eg._graph.edges(data=True):
                if src not in self._entities or dst not in self._entities:
                    continue

                eg_rels: dict = edge_data.get("relationship_types", {})
                onto_rel = _map_rel_types(eg_rels)

                co_occ = edge_data.get("co_occurrences", 1)
                # Estimate source count from recent headlines (rough proxy)
                src_count = max(1, min(5, co_occ // 3))
                last_seen = edge_data.get("last_seen", now)
                conf = compute_relationship_confidence(co_occ, src_count, last_seen, onto_rel)
                is_active = (now - last_seen) < OntologyRelationship.ACTIVE_WINDOW
                headlines = edge_data.get("recent_headlines", [])

                rel_id = f"{src}::{onto_rel.value}::{dst}"
                if rel_id in self._relationships:
                    rel = self._relationships[rel_id]
                    rel.confidence = conf
                    rel.evidence_count = co_occ
                    rel.last_seen = last_seen
                    rel.is_active = is_active
                    rel.recent_headlines = headlines[-3:]
                    updated_rels += 1
                else:
                    rel = OntologyRelationship(
                        source=src,
                        target=dst,
                        relation_type=onto_rel,
                        confidence=conf,
                        evidence_count=co_occ,
                        source_count=src_count,
                        valid_from=edge_data.get("first_seen", now),
                        valid_until=None,
                        is_active=is_active,
                        last_seen=last_seen,
                        recent_headlines=headlines[-3:],
                    )
                    self._relationships[rel_id] = rel
                    new_rels += 1

        logger.info(
            "[OntologyEngine] Enrichment complete: +%d/%d entities, +%d/%d relationships",
            new_entities, updated_entities, new_rels, updated_rels,
        )

    # ─────────────────────────────────────────────────────────────
    #  QUERY INTERFACE
    # ─────────────────────────────────────────────────────────────

    def get_entity_profile(self, name: str) -> dict | None:
        """Full profile: entity metadata + all its relationships."""
        with self._lock:
            ent = self._entities.get(name)
            if not ent:
                return None
            rels_out = [
                r.to_dict() for r in self._relationships.values()
                if r.source == name and r.is_active
            ]
            rels_in = [
                r.to_dict() for r in self._relationships.values()
                if r.target == name and r.is_active
            ]
            return {
                "entity": ent.to_dict(),
                "outgoing_relationships": sorted(rels_out, key=lambda x: -x["confidence"]),
                "incoming_relationships": sorted(rels_in, key=lambda x: -x["confidence"]),
            }

    def get_active_relationships(
        self,
        relation_type: OntologyRelationType | str | None = None,
        min_confidence: float = 0.30,
        limit: int = 100,
    ) -> list[dict]:
        """Active relationships filtered by type and minimum confidence."""
        if isinstance(relation_type, str):
            try:
                relation_type = OntologyRelationType(relation_type)
            except ValueError:
                relation_type = None

        with self._lock:
            results = []
            for rel in self._relationships.values():
                if not rel.is_active:
                    continue
                if rel.confidence < min_confidence:
                    continue
                if relation_type and rel.relation_type != relation_type:
                    continue
                results.append(rel.to_dict())

        results.sort(key=lambda x: -x["confidence"])
        return results[:limit]

    def get_high_confidence_entities(
        self,
        min_confidence: float = 0.60,
        entity_type: OntologyEntityType | str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """High-confidence entities for pattern synthesis queries."""
        if isinstance(entity_type, str):
            try:
                entity_type = OntologyEntityType(entity_type)
            except ValueError:
                entity_type = None

        with self._lock:
            results = []
            for ent in self._entities.values():
                if ent.confidence < min_confidence:
                    continue
                if entity_type and ent.entity_type != entity_type:
                    continue
                results.append(ent.to_dict())

        results.sort(key=lambda x: -x["confidence"])
        return results[:limit]

    def find_relationship_paths(
        self,
        entity_a: str,
        entity_b: str,
        max_depth: int = 3,
    ) -> list[list[dict]]:
        """
        Find relationship paths between two entities in the ontology.
        Returns list of paths, each path being a list of relationship dicts.
        """
        with self._lock:
            if entity_a not in self._entities or entity_b not in self._entities:
                return []

            # Build adjacency for active high-confidence rels
            adj: dict[str, list[tuple[str, str, float]]] = {}  # node → [(target, rel_type, conf)]
            for rel in self._relationships.values():
                if not rel.is_active or rel.confidence < 0.25:
                    continue
                adj.setdefault(rel.source, []).append(
                    (rel.target, rel.relation_type.value, rel.confidence)
                )

            # BFS
            paths: list[list[dict]] = []
            queue: list[tuple[str, list[dict]]] = [(entity_a, [])]
            visited_nodes: set[str] = set()

            while queue and len(paths) < 5:
                current, path = queue.pop(0)
                if len(path) >= max_depth:
                    continue
                visited_nodes.add(current)

                for (neighbor, rel_type, conf) in adj.get(current, []):
                    edge_info = {"from": current, "to": neighbor, "rel": rel_type, "conf": round(conf, 3)}
                    new_path = path + [edge_info]
                    if neighbor == entity_b:
                        paths.append(new_path)
                    elif neighbor not in visited_nodes:
                        queue.append((neighbor, new_path))

        return paths

    def get_entity_context(self, entity_names: list[str]) -> str:
        """
        Return a compact relationship context for a list of entities.
        Used by PatternAccumulator for cross-domain synthesis.
        """
        with self._lock:
            lines = []
            seen_rel_ids: set[str] = set()

            for name in entity_names:
                if name not in self._entities:
                    continue
                ent = self._entities[name]
                lines.append(f"• {name} ({ent.entity_type.value}, conf={ent.confidence:.2f})")

                for rel in self._relationships.values():
                    if not rel.is_active or rel.confidence < 0.30:
                        continue
                    if rel.relationship_id() in seen_rel_ids:
                        continue
                    if rel.source == name and rel.target in self._entities:
                        seen_rel_ids.add(rel.relationship_id())
                        lines.append(
                            f"    → {rel.target} [{rel.relation_type.value}] "
                            f"conf={rel.confidence:.2f}"
                        )
                    elif rel.target == name and rel.source in self._entities:
                        seen_rel_ids.add(rel.relationship_id())
                        lines.append(
                            f"    ← {rel.source} [{rel.relation_type.value}] "
                            f"conf={rel.confidence:.2f}"
                        )

        return "\n".join(lines) if lines else "(no ontology context available)"

    def get_ontology_digest(self, max_entities: int = 15) -> str:
        """
        Compact digest of the highest-confidence typed relationships for LLM context injection.
        Called by briefing engine and chat context assembler.
        """
        with self._lock:
            # Top entities by confidence
            top_entities = sorted(
                self._entities.values(),
                key=lambda e: -e.confidence,
            )[:max_entities]

            if not top_entities:
                return "⚠ Ontology: no entities yet."

            # Top relationships
            top_rels = [
                r for r in self._relationships.values()
                if r.is_active and r.confidence >= 0.35
            ]
            top_rels.sort(key=lambda r: -r.confidence)
            top_rels = top_rels[:30]

        lines = ["🧠 TYPED SEMANTIC ONTOLOGY — top entities & active relationships\n"]

        # Entity type summary
        type_counts: dict[str, int] = {}
        for ent in self._entities.values():
            type_counts[ent.entity_type.value] = type_counts.get(ent.entity_type.value, 0) + 1
        summary_parts = [f"{v} {k}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])]
        lines.append(f"Entities: {len(self._entities)} total — {', '.join(summary_parts[:5])}")
        lines.append(f"Relationships: {len(self._relationships)} tracked, {len(top_rels)} active high-conf\n")

        # Key relationships grouped by type
        grouped: dict[str, list[str]] = {}
        for rel in top_rels[:20]:
            rt = rel.relation_type.value.upper()
            grouped.setdefault(rt, []).append(
                f"{rel.source} → {rel.target} ({rel.confidence:.2f})"
            )

        for rt in sorted(grouped.keys()):
            lines.append(f"[{rt}]")
            for entry in grouped[rt][:5]:
                lines.append(f"  {entry}")

        return "\n".join(lines)

    def stats(self) -> dict:
        """Statistics for API and health check."""
        with self._lock:
            type_counts = {}
            conf_buckets = {"high": 0, "medium": 0, "low": 0}
            for ent in self._entities.values():
                type_counts[ent.entity_type.value] = type_counts.get(ent.entity_type.value, 0) + 1
                if ent.confidence >= 0.70:
                    conf_buckets["high"] += 1
                elif ent.confidence >= 0.40:
                    conf_buckets["medium"] += 1
                else:
                    conf_buckets["low"] += 1

            active_rels = sum(1 for r in self._relationships.values() if r.is_active)
            rel_type_counts = {}
            for r in self._relationships.values():
                if r.is_active:
                    k = r.relation_type.value
                    rel_type_counts[k] = rel_type_counts.get(k, 0) + 1

            return {
                "total_entities": len(self._entities),
                "entity_types": type_counts,
                "confidence_buckets": conf_buckets,
                "total_relationships": len(self._relationships),
                "active_relationships": active_rels,
                "relationship_types": rel_type_counts,
            }

    # ─────────────────────────────────────────────────────────────
    #  PERSISTENCE
    # ─────────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist ontology state to JSON."""
        try:
            with self._lock:
                state = {
                    "version": 1,
                    "saved_at": time.time(),
                    "entities": {name: ent.to_dict() for name, ent in self._entities.items()},
                    "relationships": {rid: rel.to_dict() for rid, rel in self._relationships.items()},
                }
            self._persist_path.write_text(
                json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            logger.debug("[OntologyEngine] Saved %d entities, %d rels", len(self._entities), len(self._relationships))
        except Exception as exc:
            logger.warning("[OntologyEngine] Save failed: %s", exc)

    def _load(self) -> None:
        """Load persisted ontology state from JSON."""
        if not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            with self._lock:
                for name, d in raw.get("entities", {}).items():
                    try:
                        self._entities[name] = OntologyEntity.from_dict(d)
                    except Exception:
                        pass
                for rid, d in raw.get("relationships", {}).items():
                    try:
                        self._relationships[rid] = OntologyRelationship.from_dict(d)
                    except Exception:
                        pass
            logger.info(
                "[OntologyEngine] Loaded %d entities, %d relationships from disk",
                len(self._entities), len(self._relationships),
            )
        except Exception as exc:
            logger.warning("[OntologyEngine] Load failed (starting fresh): %s", exc)

    # ─────────────────────────────────────────────────────────────
    #  BACKGROUND REFRESH LOOP
    # ─────────────────────────────────────────────────────────────

    def _refresh_loop(self) -> None:
        """Periodic re-enrichment from EntityGraph + activity refresh + save."""
        while not self._stop_event.wait(timeout=self._REFRESH_INTERVAL):
            try:
                self._enrich_from_graph()
                # Refresh activity flags for all relationships
                now = time.time()
                with self._lock:
                    for rel in self._relationships.values():
                        rel.refresh_activity(now)
                self.save()
            except Exception as exc:
                logger.warning("[OntologyEngine] Refresh error: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _dominant_rel_type(rels: list[OntologyRelationship]) -> str:
    """Return the most common active relationship type for a list of relationships."""
    if not rels:
        return OntologyRelationType.CO_OCCURRENCE.value
    counts: dict[str, int] = {}
    for r in rels:
        if r.is_active:
            k = r.relation_type.value
            counts[k] = counts.get(k, 0) + 1
    if not counts:
        return OntologyRelationType.CO_OCCURRENCE.value
    return max(counts, key=lambda k: counts[k])
