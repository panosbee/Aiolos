"""
XDART-Φ × XHEART — Entity Knowledge Graph

Palantir-grade entity relationship intelligence for Αίολος.
Tracks entities (people, countries, organizations) extracted from
real-time news headlines, builds co-occurrence relationships, and
provides cascade impact analysis.

Architecture:
  - spaCy NER (en_core_web_sm) for automatic entity extraction
  - Alias resolution for known geopolitical entities spaCy may miss
  - NetworkX directed graph for relationship tracking
  - Co-occurrence edge weights decay over time (7-day half-life)
  - JSON persistence — graph state survives restarts

Integration points:
  - Perception Collector: every headline → ingest() → graph update
  - Proactive Impact Scoring: get_cascade_impact() for pattern severity
  - Chat Mode: Αίολος queries graph via get_entity_brief() / query()
  - Pipeline: context enrichment via get_world_graph_summary()

THIS IS PART OF ΑΙΟΛΟΣ — not a separate module.
"""

import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx

logger = logging.getLogger("xdart.knowledge.entity_graph")

# ── Lazy spaCy loading (avoid startup penalty if not needed) ──
_nlp = None


def _get_nlp():
    """Lazy-load spaCy model. Returns None if unavailable."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
            logger.info("[EntityGraph] spaCy en_core_web_sm loaded")
        except Exception as e:
            logger.warning("[EntityGraph] spaCy unavailable: %s — using alias-only mode", e)
            _nlp = False  # sentinel: tried and failed
    return _nlp if _nlp is not False else None


# ══════════════════════════════════════════════════════════════════════════════
#  ALIAS REGISTRY — known entities that spaCy's small model may miss.
#  These are tier-1 geopolitical entities. The graph LEARNS new entities
#  from headlines via NER — this is just the seed.
# ══════════════════════════════════════════════════════════════════════════════

# format: canonical_name → (type, {aliases})
_KNOWN_ENTITIES: dict[str, tuple[str, set[str]]] = {
    # ── Global Figures ──
    "Donald Trump":     ("PERSON", {"trump", "donald trump", "president trump"}),
    "Joe Biden":        ("PERSON", {"biden", "joe biden", "president biden"}),
    "Xi Jinping":       ("PERSON", {"xi jinping", "xi", "president xi"}),
    "Vladimir Putin":   ("PERSON", {"putin", "vladimir putin"}),
    "Narendra Modi":    ("PERSON", {"modi", "narendra modi"}),
    "Kim Jong Un":      ("PERSON", {"kim jong un", "kim jong-un", "kim"}),
    "Ali Khamenei":     ("PERSON", {"khamenei", "ayatollah khamenei"}),
    "Benjamin Netanyahu": ("PERSON", {"netanyahu", "benjamin netanyahu", "bibi"}),
    "Recep Erdogan":    ("PERSON", {"erdogan", "erdoğan", "recep erdogan"}),
    "Emmanuel Macron":  ("PERSON", {"macron", "emmanuel macron"}),
    "Olaf Scholz":      ("PERSON", {"scholz", "olaf scholz"}),
    "Keir Starmer":     ("PERSON", {"starmer", "keir starmer"}),
    "Mohammed bin Salman": ("PERSON", {"mbs", "mohammed bin salman", "bin salman"}),
    "Volodymyr Zelensky": ("PERSON", {"zelensky", "zelenskyy", "volodymyr zelensky"}),
    "Jerome Powell":    ("PERSON", {"powell", "jerome powell", "fed chair powell"}),
    "Christine Lagarde": ("PERSON", {"lagarde", "christine lagarde"}),
    "Pope Francis":     ("PERSON", {"pope", "pope francis"}),

    # ── Major Powers ──
    "United States":    ("GPE", {"usa", "us", "united states", "america", "american", "washington"}),
    "China":            ("GPE", {"china", "chinese", "beijing", "prc"}),
    "Russia":           ("GPE", {"russia", "russian", "moscow", "kremlin"}),
    "India":            ("GPE", {"india", "indian", "new delhi", "delhi"}),
    "Japan":            ("GPE", {"japan", "japanese", "tokyo"}),
    "Germany":          ("GPE", {"germany", "german", "berlin"}),
    "France":           ("GPE", {"france", "french", "paris", "élysée"}),
    "United Kingdom":   ("GPE", {"uk", "britain", "british", "london", "england"}),
    "Iran":             ("GPE", {"iran", "iranian", "tehran"}),
    "Israel":           ("GPE", {"israel", "israeli", "jerusalem", "tel aviv"}),
    "Saudi Arabia":     ("GPE", {"saudi arabia", "saudi", "riyadh"}),
    "Turkey":           ("GPE", {"turkey", "turkish", "türkiye", "ankara"}),
    "Brazil":           ("GPE", {"brazil", "brazilian", "brasilia", "brasília"}),
    "South Korea":      ("GPE", {"south korea", "korean", "seoul"}),
    "North Korea":      ("GPE", {"north korea", "pyongyang", "dprk"}),
    "Pakistan":         ("GPE", {"pakistan", "pakistani", "islamabad"}),
    "Taiwan":           ("GPE", {"taiwan", "taiwanese", "taipei"}),
    "Ukraine":          ("GPE", {"ukraine", "ukrainian", "kyiv", "kiev"}),
    "Egypt":            ("GPE", {"egypt", "egyptian", "cairo"}),
    "Greece":           ("GPE", {"greece", "greek", "athens", "ελλαδα"}),

    # ── Key Organizations ──
    "NATO":             ("ORG", {"nato", "north atlantic treaty"}),
    "European Union":   ("ORG", {"eu", "european union", "brussels"}),
    "United Nations":   ("ORG", {"un", "united nations"}),
    "IMF":              ("ORG", {"imf", "international monetary fund"}),
    "World Bank":       ("ORG", {"world bank"}),
    "Federal Reserve":  ("ORG", {"fed", "federal reserve", "fomc"}),
    "ECB":              ("ORG", {"ecb", "european central bank"}),
    "WHO":              ("ORG", {"who", "world health organization"}),
    "WTO":              ("ORG", {"wto", "world trade organization"}),
    "OPEC":             ("ORG", {"opec", "opec+"}),
    "BRICS":            ("ORG", {"brics"}),
    "G7":               ("ORG", {"g7", "g-7"}),
    "G20":              ("ORG", {"g20", "g-20"}),
    "TSMC":             ("ORG", {"tsmc", "taiwan semiconductor"}),
    "Hamas":            ("ORG", {"hamas"}),
    "Hezbollah":        ("ORG", {"hezbollah", "hizballah"}),
    "Wagner Group":     ("ORG", {"wagner", "wagner group"}),
}

# Build reverse lookup: alias → canonical_name
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for cname, (_, aliases) in _KNOWN_ENTITIES.items():
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias] = cname


# ══════════════════════════════════════════════════════════════════════════════
#  NER QUALITY FILTER — spaCy en_core_web_sm is noisy on headlines.
#  These filters prevent false positives from polluting the entity graph
#  and downstream pattern matching.
# ══════════════════════════════════════════════════════════════════════════════

# Common English words that spaCy en_core_web_sm frequently misclassifies
# as named entities (PERSON/ORG/GPE). This is NOT a full stopword list —
# only words observed as actual false positives in production logs.
_NER_NOISE_WORDS = frozenset({
    # Verbs / common nouns misclassified as entities
    "break", "distance", "returns", "impact", "risk", "threat",
    "gain", "loss", "shift", "push", "strike", "fall", "rise",
    "lead", "power", "reform", "fire", "crash", "deal", "talks",
    "war", "peace", "death", "battle", "control", "crisis",
    "border", "summit", "chief", "state", "attack", "aid",
    "gap", "edge", "base", "watch", "alert", "charge", "order",
    # Food / retail / commercial terms from economic headlines
    "baristas", "buffets", "burgers", "stores", "brands", "foods",
    # Temporal words
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "today", "yesterday", "tomorrow",
    "daily", "weekly", "monthly", "annual",
    # Ordinals / adjectives
    "first", "second", "third", "last", "next", "new", "old",
    "general", "major", "special", "joint", "final",
    # Standalone directional (OK as part of country names handled by alias)
    "north", "south", "east", "west",
    # Media words spaCy tags as ORG
    "daily", "times", "post", "morning", "evening", "express",
    "report", "analysis", "review", "bulletin", "update",
})

# Multi-word phrases that are known false positive entity extractions
_NER_NOISE_PHRASES = frozenset({
    "diminishing returns", "breaking news", "live updates",
    "latest news", "just in", "developing story",
    "holy fire", "holy land", "ceasefire agreement",
})


def _is_valid_ner_entity(name: str, label: str) -> bool:
    """Filter out spaCy NER noise. Returns True only if entity looks legitimate.

    Designed for en_core_web_sm which has limited accuracy on news headlines.
    Known entities (alias registry) bypass this filter entirely.
    """
    # Too short — almost always noise
    if len(name) < 2:
        return False

    # Must start with uppercase (proper noun indicator)
    # spaCy sometimes tags lowercase common words as entities
    if name[0].islower():
        return False

    # Reject mostly-digit strings ("5.000", "2026", "18", etc.)
    alpha_chars = sum(c.isalpha() for c in name)
    if alpha_chars < max(2, len(name) * 0.4):
        return False

    name_lower = name.lower().strip()

    # Check multi-word noise phrases
    if name_lower in _NER_NOISE_PHRASES:
        return False

    # Single-word entity checks
    if " " not in name_lower:
        # Single word in noise list → reject
        if name_lower in _NER_NOISE_WORDS:
            return False
        # Very short single words (2-3 chars) that aren't GPE are usually noise
        # (e.g., "Gap", "Aid", "BBC" is OK as ORG but it's in alias registry)
        if len(name) <= 3 and label not in ("GPE", "ORG"):
            return False
    else:
        # Multi-word: reject if ALL words are common noise words
        # e.g., "Diminishing Returns", "Breaking News"
        words = name_lower.split()
        if len(words) >= 2 and all(w in _NER_NOISE_WORDS for w in words):
            return False
        # Very long entity names (4+ words) from headlines are usually
        # phrases, not entities (e.g., "Asymmetric Counterair Campaign")
        if len(words) >= 4:
            return False

    return True


# ── Edge weight decay ──
EDGE_HALF_LIFE = 604800  # 7 days — co-occurrence weight halves weekly
MAX_GRAPH_NODES = 5000   # cap to prevent unbounded growth
PRUNE_BELOW_MENTIONS = 2  # remove nodes with ≤ N mentions during prune


class EntityNode:
    """Metadata stored as node attributes in the NetworkX graph."""

    @staticmethod
    def create(name: str, entity_type: str, timestamp: float) -> dict:
        return {
            "type": entity_type,          # PERSON, GPE, ORG, EVENT, NORP
            "mention_count": 1,
            "first_seen": timestamp,
            "last_seen": timestamp,
            "sources": set(),             # which feeds mentioned this entity
        }


class EntityGraph:
    """Entity Knowledge Graph — Αίολος's relationship intelligence layer.

    Learns entity relationships from every headline in real-time.
    Provides cascade impact analysis for proactive alert scoring.
    Queryable by Αίολος in chat mode.
    """

    def __init__(self, persist_path: str | Path | None = None):
        self._graph = nx.DiGraph()
        self._persist_path = Path(persist_path) if persist_path else None
        self._total_headlines_ingested = 0
        self._total_entities_extracted = 0

        # Load persisted graph if available
        if self._persist_path and self._persist_path.exists():
            self._load()

    # ══════════════════════════════════════════════════════════════
    #  ENTITY EXTRACTION — spaCy NER + alias resolution
    # ══════════════════════════════════════════════════════════════

    def extract_entities(self, text: str) -> list[tuple[str, str]]:
        """Extract named entities from text.

        Returns list of (canonical_name, entity_type) tuples.
        Uses spaCy NER + known alias resolution for maximum coverage.
        """
        entities: dict[str, str] = {}  # canonical_name → type
        text_lower = text.lower()

        # Phase 1: Known alias matching (catches what spaCy misses)
        for alias, canonical in _ALIAS_TO_CANONICAL.items():
            if alias in text_lower:
                etype = _KNOWN_ENTITIES[canonical][0]
                entities[canonical] = etype

        # Phase 2: spaCy NER (discovers NEW entities not in alias registry)
        nlp = _get_nlp()
        if nlp:
            doc = nlp(text)
            for ent in doc.ents:
                if ent.label_ not in ("PERSON", "GPE", "ORG", "NORP", "LOC", "FAC"):
                    continue
                # Check if already captured via alias
                ent_lower = ent.text.lower()
                if ent_lower in _ALIAS_TO_CANONICAL:
                    canonical = _ALIAS_TO_CANONICAL[ent_lower]
                    entities[canonical] = _KNOWN_ENTITIES[canonical][0]
                elif ent.text not in entities:
                    # Validate NER output — en_core_web_sm is noisy
                    if not _is_valid_ner_entity(ent.text, ent.label_):
                        continue
                    # New entity discovered by NER — add as-is
                    entities[ent.text] = ent.label_

        return list(entities.items())

    # ══════════════════════════════════════════════════════════════
    #  HEADLINE INGESTION — updates graph from every data signal
    # ══════════════════════════════════════════════════════════════

    def ingest_headline(
        self,
        headline: str,
        source: str = "",
        timestamp: float | None = None,
    ) -> list[tuple[str, str]]:
        """Ingest a headline: extract entities, update graph.

        Returns the list of extracted (name, type) entities.
        This is called for EVERY headline from collector.
        """
        ts = timestamp or time.time()
        entities = self.extract_entities(headline)

        if not entities:
            return []

        self._total_headlines_ingested += 1
        if self._total_headlines_ingested % 50 == 0:
            logger.info("[EntityGraph] Milestone: %d headlines ingested, %d entities tracked, %d edges",
                        self._total_headlines_ingested, self._graph.number_of_nodes(),
                        self._graph.number_of_edges())
        logger.debug("[EntityGraph] Ingested %d entities from: %.80s → %s",
                     len(entities), headline, [n for n, _ in entities])

        # Update/create nodes
        for name, etype in entities:
            if self._graph.has_node(name):
                node = self._graph.nodes[name]
                node["mention_count"] = node.get("mention_count", 0) + 1
                node["last_seen"] = ts
                if source:
                    sources = node.get("sources", set())
                    if isinstance(sources, list):
                        sources = set(sources)
                    sources.add(source)
                    node["sources"] = sources
            else:
                self._graph.add_node(name, **EntityNode.create(name, etype, ts))
                if source:
                    self._graph.nodes[name]["sources"] = {source}
                self._total_entities_extracted += 1

        # Create/strengthen co-occurrence edges between all entity pairs
        for i, (name_a, _) in enumerate(entities):
            for name_b, _ in entities[i + 1:]:
                self._update_edge(name_a, name_b, ts, headline)

        # Periodic prune
        if self._total_headlines_ingested % 500 == 0:
            self._prune()

        return entities

    def _update_edge(
        self,
        entity_a: str,
        entity_b: str,
        timestamp: float,
        headline: str,
    ) -> None:
        """Add or strengthen co-occurrence edge between two entities."""
        # Bidirectional edges
        for src, dst in [(entity_a, entity_b), (entity_b, entity_a)]:
            if self._graph.has_edge(src, dst):
                edge = self._graph[src][dst]
                edge["weight"] = edge.get("weight", 0) + 1.0
                edge["last_seen"] = timestamp
                edge["co_occurrences"] = edge.get("co_occurrences", 0) + 1
                # Keep last 3 headlines as evidence
                headlines = edge.get("recent_headlines", [])
                headlines.append(headline[:120])
                edge["recent_headlines"] = headlines[-3:]
            else:
                self._graph.add_edge(
                    src, dst,
                    weight=1.0,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    co_occurrences=1,
                    recent_headlines=[headline[:120]],
                )

    def _prune(self) -> None:
        """Remove inactive nodes to keep graph manageable."""
        if len(self._graph.nodes) <= MAX_GRAPH_NODES:
            return

        now = time.time()
        remove = []
        for node, data in self._graph.nodes(data=True):
            # Keep known entities always
            if node in _KNOWN_ENTITIES:
                continue
            # Remove if low mentions AND stale
            if (data.get("mention_count", 0) <= PRUNE_BELOW_MENTIONS
                    and (now - data.get("last_seen", 0)) > EDGE_HALF_LIFE):
                remove.append(node)

        for node in remove[:500]:  # batch remove
            self._graph.remove_node(node)

        if remove:
            logger.info("[EntityGraph] Pruned %d stale nodes (remaining: %d)",
                        len(remove[:500]), len(self._graph.nodes))

    # ══════════════════════════════════════════════════════════════
    #  CASCADE IMPACT ANALYSIS — graph-powered impact estimation
    # ══════════════════════════════════════════════════════════════

    def get_cascade_impact(
        self,
        entity_names: list[str],
        depth: int = 2,
    ) -> dict:
        """Estimate cascade impact for a set of entities.

        Traverses graph relationships to find connected entities,
        calculates impact based on:
          - Entity type (PERSON vs GPE vs ORG)
          - Connection strength (decayed co-occurrence weight)
          - Network centrality (highly-connected entities = more impact)
          - Reach depth (direct vs indirect connections)

        Returns:
            {
                "impact_score": 0.0-1.0,
                "affected_entities": [...],
                "cascade_chains": [...],
                "explanation": "..."
            }
        """
        now = time.time()
        resolved = []
        for name in entity_names:
            # Try alias resolution
            name_lower = name.lower()
            if name_lower in _ALIAS_TO_CANONICAL:
                resolved.append(_ALIAS_TO_CANONICAL[name_lower])
            elif name in self._graph:
                resolved.append(name)

        if not resolved:
            return {"impact_score": 0.0, "affected_entities": [], "cascade_chains": [], "explanation": "Unknown entities"}

        # BFS from each entity, collecting affected nodes
        affected: dict[str, float] = {}  # entity → accumulated impact weight
        chains: list[str] = []

        for root in resolved:
            if root not in self._graph:
                continue

            # Start BFS
            visited = {root}
            queue = [(root, 0, 1.0)]  # (node, current_depth, decay_factor)

            while queue:
                current, d, decay = queue.pop(0)
                if d >= depth:
                    continue

                for neighbor in self._graph.successors(current):
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)

                    edge = self._graph[current][neighbor]
                    raw_weight = edge.get("weight", 1.0)
                    age = max(0, now - edge.get("last_seen", now))
                    decayed_weight = raw_weight * math.exp(-0.693 * age / EDGE_HALF_LIFE)

                    # Neighbor impact contribution
                    neighbor_importance = self._node_importance(neighbor)
                    contribution = decayed_weight * neighbor_importance * decay * 0.5

                    affected[neighbor] = affected.get(neighbor, 0) + contribution

                    if d == 0 and contribution > 0.1:
                        chains.append(f"{root} → {neighbor} (weight={decayed_weight:.1f})")

                    queue.append((neighbor, d + 1, decay * 0.5))

        # Calculate aggregate impact
        root_importance = sum(self._node_importance(r) for r in resolved if r in self._graph)
        cascade_boost = min(0.3, sum(affected.values()) * 0.05)  # cap cascade bonus

        impact = min(1.0, root_importance + cascade_boost)

        # Top affected entities (sorted by contribution)
        top_affected = sorted(affected.items(), key=lambda x: x[1], reverse=True)[:10]

        explanation_parts = [f"Root entities: {', '.join(resolved)} (importance={root_importance:.2f})"]
        if top_affected:
            explanation_parts.append(
                f"Cascade reaches: {', '.join(f'{n}({w:.2f})' for n, w in top_affected[:5])}"
            )
        explanation_parts.append(f"Total cascade boost: +{cascade_boost:.2f}")

        return {
            "impact_score": round(impact, 3),
            "affected_entities": [n for n, _ in top_affected],
            "cascade_chains": chains[:10],
            "explanation": " | ".join(explanation_parts),
        }

    def _node_importance(self, name: str) -> float:
        """Calculate importance of a single entity node.

        Based on:
          - Entity type tier (global figure > country > org > other)
          - Mention count (log-scaled)
          - In-degree (how many entities co-occur with this one)
        """
        if name not in self._graph:
            return 0.0

        node = self._graph.nodes[name]
        etype = node.get("type", "")

        # Type-based base importance (aligned with proactive impact scoring)
        type_scores = {
            "PERSON": 0.40,  # base for any person
            "GPE": 0.35,     # base for any country/place
            "ORG": 0.30,     # base for any org
            "NORP": 0.20,    # national/religious/political group
            "LOC": 0.15,     # geographic location
        }
        base = type_scores.get(etype, 0.10)

        # Known entity boost — tier-1 entities get higher base
        if name in _KNOWN_ENTITIES:
            known_type = _KNOWN_ENTITIES[name][0]
            if known_type == "PERSON":
                base = 0.70  # Global figure
            elif known_type == "GPE":
                base = 0.55  # Major power
            elif known_type == "ORG":
                base = 0.45  # Key international org

        # Mention count bonus (log-scaled, max +0.15)
        mentions = node.get("mention_count", 1)
        mention_bonus = min(0.15, math.log2(mentions + 1) * 0.03)

        # Connectivity bonus (in-degree, max +0.10)
        in_degree = self._graph.in_degree(name) if name in self._graph else 0
        connectivity_bonus = min(0.10, in_degree * 0.02)

        return min(1.0, base + mention_bonus + connectivity_bonus)

    # ══════════════════════════════════════════════════════════════
    #  QUERY INTERFACE — for Αίολος chat mode
    # ══════════════════════════════════════════════════════════════

    def get_entity_brief(self, entity_name: str) -> str:
        """Get a human-readable brief about an entity and its relationships.

        Used by Αίολος when user asks about specific actors.
        """
        # Resolve alias
        name_lower = entity_name.lower()
        canonical = _ALIAS_TO_CANONICAL.get(name_lower, entity_name)

        if canonical not in self._graph:
            return f"Entity '{entity_name}' not found in knowledge graph."

        node = self._graph.nodes[canonical]
        etype = node.get("type", "UNKNOWN")
        mentions = node.get("mention_count", 0)
        first_seen = datetime.fromtimestamp(node.get("first_seen", 0), tz=timezone.utc)
        last_seen = datetime.fromtimestamp(node.get("last_seen", 0), tz=timezone.utc)

        # Get connected entities sorted by weight
        connections = []
        for neighbor in self._graph.successors(canonical):
            edge = self._graph[canonical][neighbor]
            connections.append((
                neighbor,
                edge.get("weight", 0),
                edge.get("co_occurrences", 0),
                edge.get("recent_headlines", []),
            ))
        connections.sort(key=lambda x: x[1], reverse=True)

        lines = [
            f"ENTITY: {canonical} [{etype}]",
            f"Mentions: {mentions} | First seen: {first_seen:%Y-%m-%d} | Last seen: {last_seen:%Y-%m-%d %H:%M}",
            f"Importance: {self._node_importance(canonical):.2f}",
            f"Connections: {len(connections)}",
        ]

        if connections:
            lines.append("\nTop connections:")
            for name, weight, co_occ, headlines in connections[:10]:
                neighbor_type = self._graph.nodes[name].get("type", "?")
                lines.append(f"  → {name} [{neighbor_type}] weight={weight:.1f} "
                             f"(co-occurred {co_occ}× in news)")
                for h in headlines[-2:]:
                    lines.append(f"      Evidence: \"{h}\"")

        return "\n".join(lines)

    def get_world_graph_summary(self, top_n: int = 20) -> str:
        """Get a summary of the most active entities and relationships.

        Used in pipeline context enrichment and briefings.
        """
        if not self._graph.nodes:
            return "Entity graph is empty — no headlines ingested yet."

        now = time.time()

        # Top entities by recent mention activity
        entity_scores = []
        for name, data in self._graph.nodes(data=True):
            recency = max(0, now - data.get("last_seen", 0))
            recency_factor = math.exp(-0.693 * recency / 86400)  # 1-day half-life for ranking
            score = data.get("mention_count", 0) * recency_factor
            entity_scores.append((name, data.get("type", "?"), score, data.get("mention_count", 0)))

        entity_scores.sort(key=lambda x: x[2], reverse=True)

        lines = [
            f"ENTITY KNOWLEDGE GRAPH — {len(self._graph.nodes)} entities, "
            f"{len(self._graph.edges)} relationships, "
            f"{self._total_headlines_ingested} headlines processed",
            "",
            "Top active entities:",
        ]

        for name, etype, score, mentions in entity_scores[:top_n]:
            connections = self._graph.out_degree(name)
            lines.append(f"  {name} [{etype}] — {mentions} mentions, "
                         f"{connections} connections, activity={score:.1f}")

        # Top active edges (most recent strong relationships)
        edge_scores = []
        for u, v, data in self._graph.edges(data=True):
            weight = data.get("weight", 0)
            recency = max(0, now - data.get("last_seen", 0))
            recency_factor = math.exp(-0.693 * recency / 86400)
            edge_scores.append((u, v, weight * recency_factor, data.get("recent_headlines", [])))

        edge_scores.sort(key=lambda x: x[2], reverse=True)

        lines.append("\nHottest relationships:")
        for u, v, score, headlines in edge_scores[:10]:
            lines.append(f"  {u} ↔ {v} (activity={score:.1f})")
            if headlines:
                lines.append(f"    Last: \"{headlines[-1]}\"")

        return "\n".join(lines)

    def get_top_entities(self, n: int = 5) -> list[tuple[str, float]]:
        """Return the top-N entities by recent activity (weighted degree).

        Used by financial feeds to inject context entity names
        into anomaly headlines so cross-domain clustering works.
        """
        if not self._graph.nodes:
            logger.debug("[EntityGraph] get_top_entities: graph is empty")
            return []

        now = time.time()
        scores: list[tuple[str, float]] = []
        for node in self._graph.nodes:
            degree = 0.0
            for _, _, data in self._graph.edges(node, data=True):
                weight = data.get("weight", 1.0)
                last_seen = data.get("last_seen", now)
                age = now - last_seen
                decay = math.exp(-0.693 * age / EDGE_HALF_LIFE)
                degree += weight * decay
            scores.append((node, degree))
        scores.sort(key=lambda x: x[1], reverse=True)
        result = scores[:n]
        if result:
            logger.debug("[EntityGraph] Top-%d entities: %s",
                         n, [(name, round(sc, 2)) for name, sc in result])
        return result

    def query(self, question: str) -> str:
        """Answer a natural-language entity question.

        Parses the question for entity names and returns graph intelligence.
        Used by Αίολος in chat mode as a callable tool.
        """
        entities = self.extract_entities(question)
        if not entities:
            return self.get_world_graph_summary(top_n=15)

        results = []
        for name, _ in entities[:3]:  # max 3 entities per query
            brief = self.get_entity_brief(name)
            results.append(brief)

        if len(entities) > 1:
            # Also show cascade impact for the combination
            names = [n for n, _ in entities]
            cascade = self.get_cascade_impact(names)
            results.append(
                f"\nCOMBINED IMPACT ANALYSIS: {', '.join(names)}\n"
                f"Combined impact score: {cascade['impact_score']:.2f}\n"
                f"Cascade chains: {'; '.join(cascade['cascade_chains'][:5]) or 'none yet'}\n"
                f"Affected entities: {', '.join(cascade['affected_entities'][:8]) or 'none'}\n"
                f"{cascade['explanation']}"
            )

        return "\n\n".join(results)

    # ══════════════════════════════════════════════════════════════
    #  STATS
    # ══════════════════════════════════════════════════════════════

    @property
    def node_count(self) -> int:
        return len(self._graph.nodes)

    @property
    def edge_count(self) -> int:
        return len(self._graph.edges)

    @property
    def headlines_ingested(self) -> int:
        return self._total_headlines_ingested

    def stats(self) -> dict:
        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "headlines_ingested": self._total_headlines_ingested,
            "entities_extracted": self._total_entities_extracted,
        }

    # ══════════════════════════════════════════════════════════════
    #  VISUALIZATION — export graph data for interactive rendering
    # ══════════════════════════════════════════════════════════════

    _TYPE_COLORS: dict[str, str] = {
        "GPE":      "#4A90D9",   # Countries/cities — blue
        "PERSON":   "#E74C3C",   # People — red
        "ORG":      "#2ECC71",   # Organizations — green
        "NORP":     "#F39C12",   # Nationalities/groups — orange
        "EVENT":    "#9B59B6",   # Events — purple
        "LOC":      "#1ABC9C",   # Locations — teal
        "FAC":      "#E91E63",   # Facilities — pink
        "PRODUCT":  "#FF9800",   # Products — amber
        "UNKNOWN":  "#95A5A6",   # Fallback — grey
    }

    def export_vis_data(
        self,
        entity_filter: str = "",
        entity_type: str = "",
        max_nodes: int = 150,
        min_mentions: int = 2,
    ) -> dict[str, Any]:
        """Export graph data in a format suitable for interactive visualization.

        Parameters
        ----------
        entity_filter : str
            If set, only include nodes whose name contains this substring (case-insensitive).
        entity_type : str
            If set, only include nodes of this spaCy NER type (GPE, PERSON, ORG, etc.).
        max_nodes : int
            Maximum number of nodes to include (by activity score).
        min_mentions : int
            Minimum mention count to include a node.

        Returns
        -------
        dict with keys: nodes (list), edges (list), meta (dict)
        """
        now = time.time()

        # Score all nodes by recency-weighted activity
        scored: list[tuple[str, dict, float]] = []
        for name, data in self._graph.nodes(data=True):
            mentions = data.get("mention_count", 0)
            if mentions < min_mentions:
                continue
            if entity_filter and entity_filter.lower() not in name.lower():
                continue
            ntype = data.get("type", "UNKNOWN")
            if entity_type and ntype.upper() != entity_type.upper():
                continue

            last_seen = data.get("last_seen", 0)
            recency = max(0, now - last_seen)
            recency_factor = math.exp(-0.693 * recency / 86400)
            score = mentions * recency_factor
            scored.append((name, data, score))

        scored.sort(key=lambda x: x[2], reverse=True)
        selected = scored[:max_nodes]
        node_set = {name for name, _, _ in selected}

        # Build node list
        vis_nodes = []
        for name, data, score in selected:
            ntype = data.get("type", "UNKNOWN")
            vis_nodes.append({
                "id": name,
                "label": name,
                "type": ntype,
                "color": self._TYPE_COLORS.get(ntype, self._TYPE_COLORS["UNKNOWN"]),
                "size": max(8, min(50, int(data.get("mention_count", 1) ** 0.6 * 5))),
                "mentions": data.get("mention_count", 0),
                "last_seen_iso": datetime.fromtimestamp(
                    data.get("last_seen", 0), tz=timezone.utc
                ).isoformat() if data.get("last_seen") else None,
                "activity_score": round(score, 2),
            })

        # Build edge list (only edges between selected nodes)
        vis_edges = []
        for u, v, data in self._graph.edges(data=True):
            if u not in node_set or v not in node_set:
                continue
            weight = data.get("weight", 1.0)
            vis_edges.append({
                "source": u,
                "target": v,
                "weight": round(weight, 2),
                "co_occurrences": data.get("co_occurrence_count", 0),
                "width": max(1, min(8, int(weight ** 0.5))),
                "recent_headlines": data.get("recent_headlines", [])[-3:],
            })

        meta = {
            "total_nodes": len(self._graph.nodes),
            "total_edges": len(self._graph.edges),
            "displayed_nodes": len(vis_nodes),
            "displayed_edges": len(vis_edges),
            "headlines_ingested": self._total_headlines_ingested,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "type_legend": {k: v for k, v in self._TYPE_COLORS.items()
                           if any(n["type"] == k for n in vis_nodes)},
        }

        return {"nodes": vis_nodes, "edges": vis_edges, "meta": meta}

    # ══════════════════════════════════════════════════════════════
    #  PERSISTENCE — JSON save/load
    # ══════════════════════════════════════════════════════════════

    def save(self) -> None:
        """Persist graph to JSON file."""
        if not self._persist_path:
            return

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert NetworkX graph to serializable format
        nodes = {}
        for name, data in self._graph.nodes(data=True):
            node_data = dict(data)
            # Convert sets to lists for JSON
            if "sources" in node_data:
                node_data["sources"] = list(node_data["sources"])
            nodes[name] = node_data

        edges = []
        for u, v, data in self._graph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                **data,
            })

        payload = {
            "meta": {
                "saved_at": datetime.now(tz=timezone.utc).isoformat(),
                "nodes": len(nodes),
                "edges": len(edges),
                "headlines_ingested": self._total_headlines_ingested,
                "entities_extracted": self._total_entities_extracted,
            },
            "nodes": nodes,
            "edges": edges,
        }

        self._persist_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        logger.info("[EntityGraph] Saved: %d nodes, %d edges → %s",
                    len(nodes), len(edges), self._persist_path)

    def _load(self) -> None:
        """Load persisted graph from JSON."""
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))

            for name, node_data in data.get("nodes", {}).items():
                if "sources" in node_data:
                    node_data["sources"] = set(node_data["sources"])
                self._graph.add_node(name, **node_data)

            for edge in data.get("edges", []):
                src = edge.pop("source")
                tgt = edge.pop("target")
                self._graph.add_edge(src, tgt, **edge)

            meta = data.get("meta", {})
            self._total_headlines_ingested = meta.get("headlines_ingested", 0)
            self._total_entities_extracted = meta.get("entities_extracted", 0)

            logger.info("[EntityGraph] Loaded: %d nodes, %d edges from %s",
                        len(self._graph.nodes), len(self._graph.edges), self._persist_path)
        except Exception as e:
            logger.warning("[EntityGraph] Failed to load %s: %s", self._persist_path, e)
