"""
XDART-Φ — Cognitive Pool (Γνωστικό Pool)

The CognitivePool is Αίολος's multi-tier memory system, mirroring human cognition:

  SENSORY (ms)          → PerceptionCollector real-time signals
  WORKING (sec-min)     → Current chat context + active LLM input
  SHORT-TERM (min-hrs)  → CognitivePool items from last hours (the "reservoir")
  EPISODIC (hrs-days)   → Items recalled ≥3 times → promoted to Qdrant
  LONG-TERM (days-yrs)  → Qdrant vector DB (semantic/episodic/procedural/prophetic)
  PERMANENT (forever)   → Character, preferences, principles, identity

KEY DYNAMIC (like human thought):
  • While chatting (WORKING), scan the reservoir (SHORT-TERM) for relevant items
  • If something is recalled 3+ times → auto-promote to EPISODIC (Qdrant)
  • If something is never recalled → decay → eventual removal
  • Chat ALWAYS has priority — background LLM calls skip when user is waiting

Architecture:
  ┌─────────────────────────────────────────────────────────────┐
  │                    COGNITIVE POOL                            │
  │                                                              │
  │  Tier 1: WORKING — current chat context (always loaded)     │
  │  Tier 2: SHORT-TERM — items from last 6h (the reservoir)    │
  │  Tier 3: EPISODIC — items recalled ≥3 times (promoted)      │
  │  Tier 4: LONG-TERM — Qdrant vectors (search by similarity)  │
  │  Tier 5: PERMANENT — character, preferences (always loaded) │
  └─────────────────────────────────────────────────────────────┘

© Panos Skouras — Salimov MON IKE, 2026
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("xdart.cognitive_pool")

# ── Constants ────────────────────────────────────────────────────────────────
_POOL_STATE_PATH = Path("cognitive_pool_state.json")
_MAX_POOL_ITEMS = 500       # Max items in pool (rolling window)
_MAX_BREAKING_PER_HOUR = 6  # Max BREAKING notifications per hour (prevent flood)
_HOLD_TTL_SECONDS = 86400   # 24h — items older than this without recall are discarded
_BREAKING_COOLDOWN = 300    # 5 min minimum between breaking notifications

# ── Urgency levels ────────────────────────────────────────────────────────────
BREAKING = "breaking"       # Immediate notification + pool entry (nuclear war, market crash)
HIGH = "high"               # Pool with notification bias (sanctions escalation, coup)
MEDIUM = "medium"           # Pool only, recall if relevant (gas price rise, election)
LOW = "low"                 # Pool only, low recall priority (routine diplomacy)
BACKGROUND = "background"   # Pool only, recall only on exact entity match

# ── Domain keywords for context-aware recall ──────────────────────────────────
_RECALL_DOMAIN_BRIDGES = {
    "natural gas": {"ECONOMIC", "MARKET", "GEOPOLITICAL"},
    "oil": {"ECONOMIC", "MARKET", "GEOPOLITICAL"},
    "φυσικό αέριο": {"ECONOMIC", "MARKET", "GEOPOLITICAL"},
    "πετρέλαιο": {"ECONOMIC", "MARKET", "GEOPOLITICAL"},
    "ενέργεια": {"ECONOMIC", "MARKET", "GEOPOLITICAL"},
    "energy": {"ECONOMIC", "MARKET", "GEOPOLITICAL"},
    "πόλεμος": {"GEOPOLITICAL"},
    "war": {"GEOPOLITICAL"},
    "κρίση": {"GEOPOLITICAL", "ECONOMIC", "MARKET"},
    "crisis": {"GEOPOLITICAL", "ECONOMIC", "MARKET"},
    "πληθωρισμός": {"ECONOMIC", "MARKET"},
    "inflation": {"ECONOMIC", "MARKET"},
    "αγορά": {"MARKET", "ECONOMIC"},
    "market": {"MARKET", "ECONOMIC"},
    "AI": {"TECHNOLOGY"},
    "τεχνητή νοημοσύνη": {"TECHNOLOGY"},
    "sanctions": {"GEOPOLITICAL", "ECONOMIC"},
    "κυρώσεις": {"GEOPOLITICAL", "ECONOMIC"},
}


class CognitiveItem:
    """A single item in Αίολος's cognitive pool."""

    __slots__ = (
        "id", "arrived_at", "headline", "summary", "entities",
        "domains", "urgency", "source_type", "raw_data",
        "recalled_count", "last_recalled_at", "notified",
        "brevity", "sentiment", "confidence",
    )

    def __init__(
        self,
        *,
        id: str,
        arrived_at: str,
        headline: str,
        summary: str = "",
        entities: set[str] | None = None,
        domains: list[str] | None = None,
        urgency: str = MEDIUM,
        source_type: str = "unknown",
        raw_data: dict[str, Any] | None = None,
        brevity: str = "",
        sentiment: str = "neutral",
        confidence: float = 0.5,
    ):
        self.id = id
        self.arrived_at = arrived_at
        self.headline = headline[:200]
        self.summary = summary[:500]
        self.entities = entities or set()
        self.domains = domains or []
        self.urgency = urgency
        self.source_type = source_type
        self.raw_data = raw_data or {}
        self.brevity = brevity or headline[:120]
        self.sentiment = sentiment
        self.confidence = confidence
        self.recalled_count = 0
        self.last_recalled_at: str = ""
        self.notified = False  # Has this been sent as notification?

    @property
    def age_seconds(self) -> float:
        """Age in seconds since arrival."""
        try:
            ts = datetime.fromisoformat(self.arrived_at).timestamp()
            return time.time() - ts
        except Exception:
            return 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "arrived_at": self.arrived_at,
            "headline": self.headline,
            "summary": self.summary[:300],
            "entities": sorted(self.entities)[:20],
            "domains": self.domains,
            "urgency": self.urgency,
            "source_type": self.source_type,
            "brevity": self.brevity,
            "sentiment": self.sentiment,
            "confidence": self.confidence,
            "recalled_count": self.recalled_count,
            "notified": self.notified,
        }

    def recall(self) -> None:
        """Mark as recalled — boosts its priority for future context searches."""
        self.recalled_count += 1
        self.last_recalled_at = datetime.now(timezone.utc).isoformat()


class CognitivePool:
    """Αίολος's central cognitive buffer — where ALL information flows first.

    This is the ARCHITECTURAL FIX for the linear pipeline problem.
    Instead of "signal → evaluate → notify → forget", we have:
    "signal → pool → Αίολος decides → BREAKING / HOLD / DISCARD / RECALL"
    """

    def __init__(self, mongo=None):
        self._mongo = mongo
        self._items: deque[CognitiveItem] = deque(maxlen=_MAX_POOL_ITEMS)

        # Breaking notification tracking
        self._breaking_timestamps: list[float] = []  # Last hour timestamps
        self._last_breaking_ts: float = 0.0

        # Entity index: entity → list of item ids (for fast context recall)
        self._entity_index: dict[str, deque[str]] = {}

        # Domain index: domain → list of item ids
        self._domain_index: dict[str, deque[str]] = {}

        # Stats
        self._total_ingested = 0
        self._total_breaking = 0
        self._total_held = 0
        self._total_discarded = 0
        self._total_recalled = 0

        self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        """Restore pool from disk (items are held but not all metadata persists)."""
        if not _POOL_STATE_PATH.exists():
            return
        try:
            data = json.loads(_POOL_STATE_PATH.read_text(encoding="utf-8"))
            for item_data in data.get("items", []):
                if not item_data.get("id"):
                    continue
                try:
                    arrived_at = datetime.fromisoformat(item_data["arrived_at"])
                    age_seconds = (datetime.now(timezone.utc) - arrived_at).total_seconds()
                    if age_seconds > _HOLD_TTL_SECONDS:
                        continue  # Expired
                except Exception:
                    continue
                item = CognitiveItem(
                    id=item_data["id"],
                    arrived_at=item_data["arrived_at"],
                    headline=item_data.get("headline", ""),
                    summary=item_data.get("summary", ""),
                    entities=set(item_data.get("entities", [])),
                    domains=item_data.get("domains", []),
                    urgency=item_data.get("urgency", MEDIUM),
                    source_type=item_data.get("source_type", "unknown"),
                    raw_data=item_data.get("raw_data", {}),
                    brevity=item_data.get("brevity", ""),
                    sentiment=item_data.get("sentiment", "neutral"),
                    confidence=item_data.get("confidence", 0.5),
                )
                item.recalled_count = item_data.get("recalled_count", 0)
                item.notified = item_data.get("notified", False)
                self._items.append(item)
                self._index_item(item)
            logger.info(
                "[CognitivePool] Loaded %d items from disk",
                len(self._items),
            )
        except Exception as exc:
            logger.warning("[CognitivePool] State load failed: %s", exc)

    def _save_state(self) -> None:
        """Persist pool to disk."""
        try:
            data = {
                "items": [item.to_dict() for item in list(self._items)[-200:]],
                "stats": {
                    "total_ingested": self._total_ingested,
                    "total_breaking": self._total_breaking,
                    "total_held": self._total_held,
                    "total_discarded": self._total_discarded,
                    "total_recalled": self._total_recalled,
                    "pool_size": len(self._items),
                },
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            _POOL_STATE_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[CognitivePool] State save failed: %s", exc)

    # ── Indexing ──────────────────────────────────────────────────────────────

    def _index_item(self, item: CognitiveItem) -> None:
        """Add item to entity and domain indices for fast recall."""
        for entity in item.entities:
            entity_lower = entity.lower().strip()
            if entity_lower:
                if entity_lower not in self._entity_index:
                    self._entity_index[entity_lower] = deque(maxlen=100)
                self._entity_index[entity_lower].append(item.id)

        for domain in item.domains:
            if domain not in self._domain_index:
                self._domain_index[domain] = deque(maxlen=100)
            self._domain_index[domain].append(item.id)

    # ── Ingestion — THE MAIN ENTRY POINT ──────────────────────────────────────

    def ingest(
        self,
        *,
        headline: str,
        summary: str = "",
        entities: set[str] | None = None,
        domains: list[str] | None = None,
        source_type: str = "unknown",
        event_data: dict[str, Any] | None = None,
        convergence_score: float = 0.0,
        impact_score: float = 0.0,
    ) -> CognitiveItem:
        """Ingest information into the cognitive pool.

        Returns the created CognitiveItem. The caller should then use
        the item's properties to decide what to do with it.

        Returns:
            CognitiveItem with urgency already auto-classified.
        """
        self._total_ingested += 1
        self._prune_expired()

        now = datetime.now(timezone.utc).isoformat()
        item_id = f"cog_{int(time.time() * 1000)}"

        entities = entities or set()
        domains = domains or []

        # Auto-classify urgency based on convergence + impact
        urgency = self._classify_urgency(
            convergence_score=convergence_score,
            impact_score=impact_score,
            headline=headline,
            domains=domains,
        )

        # Generate brevity (one-line digest)
        brevity = self._generate_brevity(headline, summary)

        item = CognitiveItem(
            id=item_id,
            arrived_at=now,
            headline=headline,
            summary=summary,
            entities=entities,
            domains=domains,
            urgency=urgency,
            source_type=source_type,
            raw_data=event_data or {},
            brevity=brevity,
            sentiment=self._classify_sentiment(headline, summary),
            confidence=min(1.0, max(0.1, convergence_score + impact_score) / 2),
        )

        self._items.append(item)
        self._index_item(item)
        self._save_state()

        logger.info(
            "[CognitivePool] Ingested %s [%s] → %s (entities=%s)",
            item.id[:16], urgency.upper(), brevity[:80],
            ", ".join(sorted(entities)[:5]) if entities else "none",
        )
        return item

    # ── Decision Engine — Αίολος decides what to do ───────────────────────────

    def decide(self, item: CognitiveItem) -> dict[str, Any]:
        """Αίολος makes an autonomous decision about one pool item.

        Returns:
            {
              "action": "BREAKING" | "HOLD" | "ENRICH" | "DISCARD",
              "reason": str,
              "should_notify": bool,
              "urgency_override": str | None,
            }
        """
        # ── BREAKING gate ─────────────────────────────────────────────────────
        # Truly extreme events break through immediately
        if item.urgency == BREAKING:
            # Rate-limit: max N breaking per hour
            now = time.time()
            self._breaking_timestamps = [
                t for t in self._breaking_timestamps
                if now - t < 3600
            ]
            if len(self._breaking_timestamps) < _MAX_BREAKING_PER_HOUR:
                if now - self._last_breaking_ts >= _BREAKING_COOLDOWN:
                    self._breaking_timestamps.append(now)
                    self._last_breaking_ts = now
                    self._total_breaking += 1
                    item.notified = True
                    self._save_state()
                    return {
                        "action": "BREAKING",
                        "reason": f"Maximum urgency: {item.brevity[:60]}",
                        "should_notify": True,
                        "urgency_override": "critical",
                    }
                else:
                    return {
                        "action": "HOLD",
                        "reason": f"Breaking cooldown active ({_BREAKING_COOLDOWN}s), held for next window",
                        "should_notify": False,
                        "urgency_override": None,
                    }

        # ── HIGH urgency — notify if not recently done ────────────────────────
        if item.urgency == HIGH:
            if self._should_hold_for_batching(item):
                self._total_held += 1
                return {
                    "action": "HOLD",
                    "reason": f"Held for batching — will notify in next batch or on recall",
                    "should_notify": False,
                    "urgency_override": None,
                }
            self._total_breaking += 1
            item.notified = True
            self._save_state()
            return {
                "action": "BREAKING",
                "reason": "High urgency, not duplicative",
                "should_notify": True,
                "urgency_override": "important",
            }

        # ── MEDIUM / LOW / BACKGROUND — hold in pool ──────────────────────────
        self._total_held += 1
        self._save_state()
        return {
            "action": "HOLD",
            "reason": f"Standard priority ({item.urgency}) — held in pool for context recall",
            "should_notify": False,
            "urgency_override": None,
        }

    # ── Context-Aware Recall ─────────────────────────────────────────────────

    def recall_relevant(
        self,
        *,
        query: str,
        max_items: int = 5,
        max_age_hours: int = 48,
    ) -> list[dict]:
        """Recall held pool items relevant to a user query or chat context.

        This is THE method that breaks the linear pipeline:
        when the user asks about natural gas, Αίολος scans the pool
        for held items about energy prices and surfaces them.

        Args:
            query: What the user is asking about
            max_items: Max items to recall
            max_age_hours: Only recall items younger than this

        Returns:
            List of relevant CognitiveItem dicts, sorted by relevance
        """
        self._prune_expired()
        query_lower = query.lower()
        now = time.time()
        max_age_seconds = max_age_hours * 3600

        candidates: list[tuple[CognitiveItem, float]] = []

        for item in self._items:
            # Age filter
            if item.age_seconds > max_age_seconds:
                continue

            # Already recalled recently? Boost it
            recency_boost = 0.0
            try:
                if item.last_recalled_at:
                    last_ts = datetime.fromisoformat(item.last_recalled_at).timestamp()
                    if now - last_ts < 300:  # 5 min
                        recency_boost = 0.3
            except Exception:
                pass

            relevance = self._compute_relevance(item, query_lower)
            if relevance >= 0.15:
                candidates.append((item, relevance + recency_boost))

        # Sort by relevance (descending), then by recency
        candidates.sort(key=lambda x: (-x[1], -x[0].age_seconds if x[0].age_seconds else 0))

        results: list[dict] = []
        for item, relevance in candidates[:max_items]:
            item.recall()
            self._total_recalled += 1
            results.append({
                **item.to_dict(),
                "relevance_score": round(relevance, 3),
                "age_hours": round(item.age_seconds / 3600, 1),
            })

        if results:
            self._save_state()
            logger.info(
                "[CognitivePool] Recalled %d items for query '%s'",
                len(results), query[:60],
            )

        return results

    def get_context_for_chat(self, query: str) -> str:
        """Get a formatted context block for injection into chat.

        When the user asks something, this method scans the pool for
        relevant held items and returns a formatted string that can be
        injected into the LLM context so Αίολος can reference them.
        """
        items = self.recall_relevant(query=query, max_items=5)
        if not items:
            return ""

        now = time.time()
        lines = ["▸ ΓΝΩΣΤΙΚΟ POOL — Σχετικές πληροφορίες που κρατούσα:"]
        for item in items:
            age_h = item["age_hours"]
            age_str = f"{age_h:.1f}h" if age_h >= 1 else f"{int(age_h * 60)}m"
            urgency_mark = "⚡" if item["urgency"] in (BREAKING, HIGH) else "📎"
            lines.append(
                f"  {urgency_mark} [{age_str}] {item['brevity']} "
                f"(source: {item['source_type']}, domains: {', '.join(item['domains'][:3])})"
            )
        lines.append("")
        return "\n".join(lines)

    def get_context_for_wakeup(self) -> str:
        """Get pool digest for injection into wakeup/chat context.

        Gives Αίολος awareness of what's in the cognitive pool.
        """
        if not self._items:
            return ""

        recent = list(self._items)[-30:]
        breaking_items = [i for i in recent if i.urgency == BREAKING]
        high_items = [i for i in recent if i.urgency == HIGH]
        held_items = [i for i in recent if i.urgency not in (BREAKING, HIGH) and not i.notified]

        lines = ["▸ ΓΝΩΣΤΙΚΟ POOL — Αυτόνομη ενημερότητα Αίολου:"]

        if breaking_items:
            lines.append(f"  ⚡ BREAKING ({len(breaking_items)}):")
            for item in breaking_items[-3:]:
                lines.append(f"    • {item.brevity}")
        if held_items:
            lines.append(f"  📎 HELD for recall ({len(held_items)}):")
            for item in held_items[-5:]:
                age_m = int(item.age_seconds / 60)
                lines.append(f"    • [{age_m}m] {item.brevity}")

        lines.append(f"  📊 Total pool: {len(self._items)} items, {self._total_recalled} recalled")
        lines.append("")
        return "\n".join(lines)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _classify_urgency(
        self,
        convergence_score: float,
        impact_score: float,
        headline: str,
        domains: list[str],
    ) -> str:
        """Auto-classify urgency from signals."""
        headline_lower = headline.lower()

        # Nuclear war / existential threats → BREAKING
        extreme_terms = {
            "nuclear war", "nuclear strike", "world war", "asteroid",
            "extinction", "pandemic outbreak", "market crash -50%",
            "sovereign default cascade", "nato article 5",
            "πυρηνικός πόλεμος", "παγκόσμιος πόλεμος",
        }
        if any(term in headline_lower for term in extreme_terms):
            return BREAKING

        # Combined extreme convergence + impact → BREAKING
        if convergence_score >= 0.85 and impact_score >= 0.90:
            return BREAKING

        # High convergence + impact + cross-domain → HIGH
        if convergence_score >= 0.70 and impact_score >= 0.75:
            return HIGH
        if len(domains) >= 3 and impact_score >= 0.70:
            return HIGH

        # Significant impact → MEDIUM
        if impact_score >= 0.60:
            return MEDIUM

        # Standard patterns → LOW
        if convergence_score >= 0.50:
            return LOW

        # Everything else → BACKGROUND
        return BACKGROUND

    def _generate_brevity(self, headline: str, summary: str) -> str:
        """Generate a one-line digest for quick scanning."""
        text = headline or summary or ""
        # Take first sentence or first 120 chars
        first_sentence = text.split(".")[0].strip()
        if len(first_sentence) > 120:
            first_sentence = first_sentence[:117] + "..."
        return first_sentence or text[:120]

    def _classify_sentiment(self, headline: str, summary: str) -> str:
        """Quick sentiment classification from text."""
        text = (headline + " " + summary).lower()
        negative_words = {
            "crisis", "crash", "war", "disaster", "collapse", "attack",
            "κρίση", "πόλεμος", "καταστροφή", "επίθεση",
        }
        positive_words = {
            "growth", "recovery", "peace", "agreement", "innovation",
            "ανάπτυξη", "ειρήνη", "συμφωνία",
        }
        neg_count = sum(1 for w in negative_words if w in text)
        pos_count = sum(1 for w in positive_words if w in text)
        if neg_count > pos_count:
            return "negative"
        if pos_count > neg_count:
            return "positive"
        return "neutral"

    def _compute_relevance(self, item: CognitiveItem, query_lower: str) -> float:
        """Compute relevance score between an item and a user query."""
        score = 0.0

        # Entity match (strongest signal)
        for entity in item.entities:
            if entity.lower() in query_lower or query_lower in entity.lower():
                score += 0.35

        # Domain match via recall bridges
        matched_domains = set()
        for keyword, domains in _RECALL_DOMAIN_BRIDGES.items():
            if keyword in query_lower:
                matched_domains.update(domains)
        for domain in item.domains:
            if domain in matched_domains:
                score += 0.20
                break

        # Headline keyword overlap
        headline_lower = item.headline.lower()
        query_words = set(query_lower.split())
        if query_words:
            headline_words = set(headline_lower.split())
            overlap = len(query_words & headline_words)
            if overlap > 0:
                score += min(0.25, overlap * 0.08)

        # Urgency bonus (more urgent items are more relevant)
        urgency_bonus = {
            BREAKING: 0.15,
            HIGH: 0.10,
            MEDIUM: 0.05,
            LOW: 0.02,
            BACKGROUND: 0.0,
        }
        score += urgency_bonus.get(item.urgency, 0.0)

        # Recency bonus (fresher items are more relevant)
        age_hours = item.age_seconds / 3600
        if age_hours < 1:
            score += 0.10
        elif age_hours < 6:
            score += 0.05
        elif age_hours < 24:
            score += 0.02

        # Previous recall bonus
        if item.recalled_count > 0:
            score += min(0.10, item.recalled_count * 0.05)

        return round(min(1.0, score), 3)

    def _should_hold_for_batching(self, item: CognitiveItem) -> bool:
        """Decide if a HIGH urgency item should be held for batching."""
        # Check if we've had 3+ similar items in the last 15 minutes
        recent_similar = 0
        for existing in list(self._items)[-20:]:
            if existing.age_seconds > 900:  # 15 min
                continue
            if existing.urgency in (BREAKING, HIGH):
                entity_overlap = bool(existing.entities & item.entities)
                domain_overlap = bool(set(existing.domains) & set(item.domains))
                if entity_overlap or domain_overlap:
                    recent_similar += 1

        return recent_similar >= 3

    def _prune_expired(self) -> None:
        """Remove items older than HOLD_TTL that haven't been recalled."""
        pruned = 0
        for item in list(self._items):
            if item.age_seconds > _HOLD_TTL_SECONDS and item.recalled_count == 0:
                self._items.remove(item)
                pruned += 1
        if pruned:
            logger.debug("[CognitivePool] Pruned %d expired items", pruned)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        now = time.time()
        recent_breaking = sum(
            1 for t in self._breaking_timestamps
            if now - t < 3600
        )
        return {
            "pool_size": len(self._items),
            "total_ingested": self._total_ingested,
            "total_breaking": self._total_breaking,
            "total_held": self._total_held,
            "total_discarded": self._total_discarded,
            "total_recalled": self._total_recalled,
            "breaking_last_hour": recent_breaking,
            "breaking_remaining_quota": max(0, _MAX_BREAKING_PER_HOUR - recent_breaking),
            "entity_index_size": len(self._entity_index),
            "domain_index_size": len(self._domain_index),
            "oldest_item_age_hours": round(
                min(
                    (item.age_seconds / 3600)
                    for item in self._items
                ) if self._items else 0,
                1,
            ),
        }
