"""
XDART-Φ × XHEART — Temporal Reasoning Engine (P3)

Learns recurring temporal patterns from observed data:
  - Pre-event precursors: "3 days before FOMC, VIX spikes and gold rises"
  - Post-event sequences: "After sanctions announcement, military escalation within 5 days"
  - Periodic rhythms: "Monday mornings: spike in military signals"
  - Causal chains: "A → B → C with typical delays"

Uses PerceptionDB + GeopoliticalCalendar + PatternAccumulator history.
Generates actionable temporal intelligence injected into pipeline & chat.

«Ο χρόνος δεν περνάει — συσσωρεύεται.
 Κάθε γεγονός έχει ρίζες σε κάτι που ήρθε πριν.»

© Panos Skouras — Salimov MON IKE, 2026
"""

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("xdart.temporal")

# ── Constants ──
BASE_DIR = Path(__file__).parent.parent.parent

_PERSIST_PATH = BASE_DIR / "temporal_patterns.json"
_JOURNAL_PATH = BASE_DIR / "temporal_journal.jsonl"

# Minimum observations before a temporal pattern is considered learned
MIN_OBSERVATIONS = 3
# Similarity threshold for matching current signals to historical pre-event fingerprints
PRECURSOR_MATCH_THRESHOLD = 0.40
# Maximum age (days) for pattern observations to remain relevant
MAX_OBSERVATION_AGE_DAYS = 365
# How many days before an event to look for precursor signals
PRE_EVENT_WINDOW_DAYS = 7
# How many days after an event to look for aftermath signals
POST_EVENT_WINDOW_DAYS = 14
# Cooldown between digest generations (seconds)
DIGEST_COOLDOWN = 300
# Max patterns to store
MAX_PATTERNS = 200
# Max observations per pattern
MAX_OBSERVATIONS_PER_PATTERN = 50


# ══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ══════════════════════════════════════════════════════════════


@dataclass
class TemporalObservation:
    """A single observed instance of a temporal pattern."""
    __slots__ = (
        "timestamp", "event_name", "event_category", "window",
        "signal_domains", "signal_topics", "signal_entities",
        "signal_count", "headline_sample", "market_context",
    )
    timestamp: float                    # Unix epoch when observed
    event_name: str                     # Calendar event this relates to
    event_category: str                 # central_bank, election, summit, etc.
    window: str                         # "pre_3d", "pre_1d", "post_1d", "post_3d", etc.
    signal_domains: list[str]           # Domains active in this window
    signal_topics: list[str]            # Top topic keywords
    signal_entities: list[str]          # Top entities
    signal_count: int                   # How many signals observed
    headline_sample: list[str]          # Representative headlines (max 5)
    market_context: dict                # Market data snapshot if available

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event_name": self.event_name,
            "event_category": self.event_category,
            "window": self.window,
            "signal_domains": self.signal_domains,
            "signal_topics": self.signal_topics,
            "signal_entities": self.signal_entities,
            "signal_count": self.signal_count,
            "headline_sample": self.headline_sample,
            "market_context": self.market_context,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TemporalObservation":
        return cls(
            timestamp=d.get("timestamp", 0.0),
            event_name=d.get("event_name", ""),
            event_category=d.get("event_category", ""),
            window=d.get("window", ""),
            signal_domains=d.get("signal_domains", []),
            signal_topics=d.get("signal_topics", []),
            signal_entities=d.get("signal_entities", []),
            signal_count=d.get("signal_count", 0),
            headline_sample=d.get("headline_sample", []),
            market_context=d.get("market_context", {}),
        )


@dataclass
class RecurringPattern:
    """A learned recurring temporal pattern with multiple observations."""
    __slots__ = (
        "pattern_id", "pattern_type", "anchor_event", "anchor_category",
        "window", "description", "observations", "avg_signal_count",
        "typical_domains", "typical_topics", "typical_entities",
        "confidence", "last_matched", "times_predicted", "times_correct",
        "created_at",
    )
    pattern_id: str                     # Unique ID
    pattern_type: str                   # "pre_event", "post_event", "sequence", "periodic"
    anchor_event: str                   # Event name this pattern anchors to
    anchor_category: str                # Event category
    window: str                         # Temporal window (pre_3d, post_1d, etc.)
    description: str                    # Human-readable description
    observations: list[TemporalObservation]  # Historical instances
    avg_signal_count: float             # Average signals in window
    typical_domains: list[str]          # Most common domains
    typical_topics: list[str]           # Most common topics (top 10)
    typical_entities: list[str]         # Most common entities (top 10)
    confidence: float                   # 0.0-1.0, based on consistency across observations
    last_matched: float                 # Last time this pattern matched current data
    times_predicted: int                # How many times we surfaced this as a prediction
    times_correct: int                  # How many times the prediction was roughly right
    created_at: float                   # Creation timestamp

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "anchor_event": self.anchor_event,
            "anchor_category": self.anchor_category,
            "window": self.window,
            "description": self.description,
            "observations": [o.to_dict() for o in self.observations],
            "avg_signal_count": self.avg_signal_count,
            "typical_domains": self.typical_domains,
            "typical_topics": self.typical_topics,
            "typical_entities": self.typical_entities,
            "confidence": self.confidence,
            "last_matched": self.last_matched,
            "times_predicted": self.times_predicted,
            "times_correct": self.times_correct,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RecurringPattern":
        return cls(
            pattern_id=d.get("pattern_id", ""),
            pattern_type=d.get("pattern_type", ""),
            anchor_event=d.get("anchor_event", ""),
            anchor_category=d.get("anchor_category", ""),
            window=d.get("window", ""),
            description=d.get("description", ""),
            observations=[TemporalObservation.from_dict(o) for o in d.get("observations", [])],
            avg_signal_count=d.get("avg_signal_count", 0.0),
            typical_domains=d.get("typical_domains", []),
            typical_topics=d.get("typical_topics", []),
            typical_entities=d.get("typical_entities", []),
            confidence=d.get("confidence", 0.0),
            last_matched=d.get("last_matched", 0.0),
            times_predicted=d.get("times_predicted", 0),
            times_correct=d.get("times_correct", 0),
            created_at=d.get("created_at", 0.0),
        )

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    @property
    def is_mature(self) -> bool:
        """Has enough observations to be reliable."""
        return self.observation_count >= MIN_OBSERVATIONS

    @property
    def accuracy(self) -> float:
        """Prediction accuracy (0.0-1.0)."""
        if self.times_predicted == 0:
            return 0.0
        return self.times_correct / self.times_predicted


# ══════════════════════════════════════════════════════════════
#  SEQUENCE TRACKER — detects A → B chains
# ══════════════════════════════════════════════════════════════

@dataclass
class PendingSequence:
    """Tracks a potential A → B causal chain waiting for B."""
    __slots__ = (
        "sequence_id", "event_a_topics", "event_a_entities",
        "event_a_domains", "event_a_headline", "event_a_ts",
        "expected_b_topics", "expected_b_entities", "max_delay_days",
        "observed_b", "created_at",
    )
    sequence_id: str
    event_a_topics: set
    event_a_entities: set
    event_a_domains: set
    event_a_headline: str
    event_a_ts: float
    expected_b_topics: set       # What topics we expect in event B
    expected_b_entities: set     # What entities we expect in event B
    max_delay_days: int          # Max days to wait for B
    observed_b: bool             # Whether B was observed
    created_at: float


# ══════════════════════════════════════════════════════════════
#  LLM PROMPTS
# ══════════════════════════════════════════════════════════════

_TEMPORAL_ANALYSIS_PROMPT = """\
You are a temporal pattern analyst. Given these observations of what happened \
before/after a recurring event type, identify the RECURRING TEMPORAL PATTERN.

Event type: {event_name} ({category})
Window: {window}

Historical observations:
{observations}

Analyze:
1. What CONSISTENTLY happens in this time window relative to this event?
2. What domains/topics/entities are REPEATEDLY involved?
3. How confident are you that this is a genuine recurring pattern (vs coincidence)?

Return JSON:
{{
  "description": "One-line description of the recurring pattern",
  "key_signals": ["signal1", "signal2", "signal3"],
  "typical_sequence": "What typically happens first, then second, etc.",
  "confidence": 0.0-1.0,
  "reasoning": "Why you believe (or doubt) this is a genuine pattern"
}}"""


_PRECURSOR_CHECK_PROMPT = """\
You are a temporal intelligence analyst. An important event is approaching:

EVENT: {event_name} in {days_until} days ({category})

Historical pattern (learned from {obs_count} past occurrences):
  "{pattern_description}"
  Typical pre-event signals: {typical_signals}
  Typical domains: {typical_domains}
  Typical entities: {typical_entities}

Current signals (last {window_days} days):
{current_signals}

Does the current signal landscape match the historical pre-event pattern?
Are we seeing the SAME precursor signals that typically appear before this event?

Return JSON:
{{
  "match_score": 0.0-1.0,
  "matching_signals": ["signal1", "signal2"],
  "missing_signals": ["expected_signal_not_seen"],
  "novel_signals": ["signal_not_in_historical_pattern"],
  "assessment": "One paragraph: what does the temporal pattern tell us about what's coming?",
  "actionable_insight": "Specific actionable takeaway"
}}"""


_SEQUENCE_DETECTION_PROMPT = """\
You are a causal sequence analyst. A significant event just occurred:

EVENT A: {event_a}
Domains: {domains}
Key entities: {entities}

Based on historical patterns and geopolitical logic, what event B is LIKELY \
to follow within {max_days} days?

Think about:
- Retaliatory actions (sanctions → counter-sanctions)
- Market reactions (rate decision → currency moves → trade impacts)
- Escalation patterns (military posturing → diplomatic response → further escalation)
- Domestic political reactions to international events

Return JSON:
{{
  "expected_event_b": "Description of likely follow-on event",
  "expected_topics": ["topic1", "topic2"],
  "expected_entities": ["entity1", "entity2"],
  "expected_delay_days": 1-14,
  "confidence": 0.0-1.0,
  "reasoning": "Why this sequence is expected"
}}"""


# ══════════════════════════════════════════════════════════════
#  ENGINE
# ══════════════════════════════════════════════════════════════

class TemporalReasoningEngine:
    """Learns and applies recurring temporal patterns from observed data.

    Integrates with:
      - GeopoliticalCalendar: knows what events are coming
      - PatternAccumulator: knows what signals are active
      - PerceptionDB: historical signal data
      - LLM: for pattern analysis and precursor matching

    Lifecycle:
      1. After each calendar event, record_event_window() captures
         what signals appeared in the pre/post windows.
      2. When enough observations accumulate (≥3), learn_pattern()
         uses LLM to extract the recurring pattern.
      3. Before upcoming events, check_precursors() compares
         current signals to historical pre-event fingerprints.
      4. get_temporal_digest() formats insights for pipeline injection.
    """

    def __init__(self, llm: Any = None, calendar: Any = None):
        self.llm = llm
        self.calendar = calendar           # GeopoliticalCalendar instance
        self.perception_db: Any = None      # PerceptionDB — wired later
        self.entity_graph: Any = None       # EntityGraph — wired later
        self.market_collector: Any = None   # MarketDataCollector — wired later
        self._patterns: list[RecurringPattern] = []
        self._pending_sequences: list[PendingSequence] = []
        self._last_digest_ts: float = 0.0
        self._last_learning_ts: float = 0.0
        self._cached_digest: str = ""
        self._total_observations = 0
        self._total_patterns_learned = 0
        self._total_precursor_checks = 0
        self._total_sequences_detected = 0
        self._state_dirty = False
        self._load_state()
        logger.info(
            "[Temporal] Engine initialized — %d patterns, %d pending sequences",
            len(self._patterns), len(self._pending_sequences),
        )

    # ══════════════════════════════════════════════════════════════
    #  OBSERVATION RECORDING
    # ══════════════════════════════════════════════════════════════

    def record_event_window(
        self,
        event_name: str,
        event_category: str,
        event_date: datetime,
        window: str = "pre_3d",
    ) -> TemporalObservation | None:
        """Record what signals appeared in a time window around an event.

        Called periodically by the background loop when calendar events
        are within observation range.

        Args:
            event_name: Name of the calendar event (e.g., "FOMC Decision")
            event_category: Category (central_bank, election, etc.)
            event_date: The event's date
            window: Time window ("pre_7d", "pre_3d", "pre_1d", "post_1d", "post_3d")

        Returns:
            TemporalObservation if data was available, None otherwise.
        """
        if not self.perception_db:
            return None

        # Parse window to hours
        hours_back = self._window_to_hours(window, event_date)
        if hours_back is None:
            return None

        try:
            # Get signals from perception DB for this window
            events = self.perception_db.get_recent_events(
                hours_back=hours_back,
                max_events=200,
            )
            if not events:
                return None

            # Filter to signals within the actual window
            window_start, window_end = self._window_boundaries(window, event_date)
            filtered = []
            for ev in events:
                try:
                    collected = datetime.fromisoformat(ev.get("collected_at", ""))
                    if collected.tzinfo is None:
                        collected = collected.replace(tzinfo=timezone.utc)
                    if window_start <= collected <= window_end:
                        filtered.append(ev)
                except (ValueError, TypeError):
                    continue

            if len(filtered) < 3:
                return None

            # Extract features
            domains = {}
            topics = {}
            entities = {}
            headlines = []

            for ev in filtered:
                domain = (ev.get("domain") or "MULTI").upper()
                domains[domain] = domains.get(domain, 0) + 1
                headline = ev.get("headline", "")
                if headline:
                    headlines.append(headline)
                    # Extract topics from headline
                    for word in _extract_simple_topics(headline):
                        topics[word] = topics.get(word, 0) + 1
                # Extract entities if entity graph available
                if self.entity_graph and headline:
                    try:
                        ents = self.entity_graph.extract_entities(headline)
                        for name, _ in ents:
                            entities[name] = entities.get(name, 0) + 1
                    except Exception:
                        pass

            # Get market context if available
            market_ctx = {}
            if self.market_collector:
                try:
                    snapshot = self.market_collector.poll()
                    if snapshot and snapshot.data:
                        for ticker, data_point in snapshot.data.items():
                            market_ctx[ticker] = {
                                "price": data_point.get("price"),
                                "change_pct": data_point.get("change_pct"),
                            }
                except Exception:
                    pass

            # Sort by frequency
            top_domains = sorted(domains, key=domains.get, reverse=True)[:5]
            top_topics = sorted(topics, key=topics.get, reverse=True)[:15]
            top_entities = sorted(entities, key=entities.get, reverse=True)[:10]
            sample_headlines = headlines[:5]

            obs = TemporalObservation(
                timestamp=time.time(),
                event_name=event_name,
                event_category=event_category,
                window=window,
                signal_domains=top_domains,
                signal_topics=top_topics,
                signal_entities=top_entities,
                signal_count=len(filtered),
                headline_sample=sample_headlines,
                market_context=market_ctx,
            )

            # File under existing pattern or create new slot
            self._add_observation(obs)
            self._total_observations += 1
            self._state_dirty = True
            self._journal_log("observation", {
                "event_name": event_name,
                "event_category": event_category,
                "window": window,
                "signal_count": len(filtered),
                "top_domains": top_domains,
                "top_entities": top_entities[:5],
            })

            logger.info(
                "[Temporal] Recorded observation: %s/%s — %d signals, "
                "domains=%s, entities=%s",
                event_name, window, len(filtered),
                top_domains[:3], top_entities[:3],
            )

            # Auto-learn if we have enough observations
            pattern_key = self._pattern_key(event_name, event_category, window)
            matching = [p for p in self._patterns if p.pattern_id == pattern_key]
            if matching and matching[0].observation_count >= MIN_OBSERVATIONS:
                if not matching[0].description or time.time() - self._last_learning_ts > 3600:
                    self._learn_pattern(matching[0])

            return obs

        except Exception as exc:
            logger.warning("[Temporal] record_event_window failed: %s", exc)
            return None

    def _add_observation(self, obs: TemporalObservation) -> None:
        """Add observation to the matching pattern, creating one if needed."""
        pattern_key = self._pattern_key(obs.event_name, obs.event_category, obs.window)

        # Find existing pattern
        target = None
        for p in self._patterns:
            if p.pattern_id == pattern_key:
                target = p
                break

        if target is None:
            # Create new pattern slot
            target = RecurringPattern(
                pattern_id=pattern_key,
                pattern_type="pre_event" if obs.window.startswith("pre") else "post_event",
                anchor_event=obs.event_name,
                anchor_category=obs.event_category,
                window=obs.window,
                description="",
                observations=[],
                avg_signal_count=0.0,
                typical_domains=[],
                typical_topics=[],
                typical_entities=[],
                confidence=0.0,
                last_matched=0.0,
                times_predicted=0,
                times_correct=0,
                created_at=time.time(),
            )
            self._patterns.append(target)
            # Enforce max patterns
            if len(self._patterns) > MAX_PATTERNS:
                # Remove oldest low-confidence patterns
                self._patterns.sort(key=lambda p: (p.confidence, p.created_at))
                self._patterns = self._patterns[-MAX_PATTERNS:]

        # Add observation
        target.observations.append(obs)
        # Enforce max observations per pattern
        if len(target.observations) > MAX_OBSERVATIONS_PER_PATTERN:
            target.observations = target.observations[-MAX_OBSERVATIONS_PER_PATTERN:]

        # Update aggregates
        self._recompute_aggregates(target)

    def _recompute_aggregates(self, pattern: RecurringPattern) -> None:
        """Recompute typical domains/topics/entities from all observations."""
        if not pattern.observations:
            return

        domain_freq: dict[str, int] = {}
        topic_freq: dict[str, int] = {}
        entity_freq: dict[str, int] = {}
        total_signals = 0

        for obs in pattern.observations:
            total_signals += obs.signal_count
            for d in obs.signal_domains:
                domain_freq[d] = domain_freq.get(d, 0) + 1
            for t in obs.signal_topics:
                topic_freq[t] = topic_freq.get(t, 0) + 1
            for e in obs.signal_entities:
                entity_freq[e] = entity_freq.get(e, 0) + 1

        n = len(pattern.observations)
        pattern.avg_signal_count = total_signals / n if n else 0
        pattern.typical_domains = sorted(domain_freq, key=domain_freq.get, reverse=True)[:5]
        pattern.typical_topics = sorted(topic_freq, key=topic_freq.get, reverse=True)[:10]
        pattern.typical_entities = sorted(entity_freq, key=entity_freq.get, reverse=True)[:10]

        # Confidence = consistency across observations
        # If the same domains/topics appear in most observations, high confidence
        if n >= MIN_OBSERVATIONS:
            # Domain consistency: what fraction of obs share the top domain?
            top_domain = pattern.typical_domains[0] if pattern.typical_domains else ""
            domain_consistency = sum(
                1 for o in pattern.observations if top_domain in o.signal_domains
            ) / n if top_domain else 0.0

            # Topic consistency: average Jaccard between consecutive observations
            topic_sets = [set(o.signal_topics[:8]) for o in pattern.observations]
            jaccard_sum = 0.0
            pairs = 0
            for i in range(len(topic_sets) - 1):
                a, b = topic_sets[i], topic_sets[i + 1]
                if a or b:
                    jaccard_sum += len(a & b) / max(1, len(a | b))
                    pairs += 1
            topic_consistency = jaccard_sum / max(1, pairs)

            pattern.confidence = round(
                0.4 * domain_consistency + 0.4 * topic_consistency + 0.2 * min(1.0, n / 10),
                3,
            )
        else:
            pattern.confidence = round(0.1 * n, 3)

    # ══════════════════════════════════════════════════════════════
    #  PATTERN LEARNING (LLM-assisted)
    # ══════════════════════════════════════════════════════════════

    def _learn_pattern(self, pattern: RecurringPattern) -> None:
        """Use LLM to analyze observations and extract recurring pattern description."""
        if not self.llm:
            return
        if not pattern.observations:
            return

        self._last_learning_ts = time.time()

        # Format observations for LLM
        obs_lines = []
        for i, obs in enumerate(pattern.observations[-8:], 1):
            dt = datetime.fromtimestamp(obs.timestamp, tz=timezone.utc)
            obs_lines.append(
                f"  Observation {i} ({dt.strftime('%Y-%m-%d')}):\n"
                f"    Signals: {obs.signal_count}\n"
                f"    Domains: {', '.join(obs.signal_domains)}\n"
                f"    Topics: {', '.join(obs.signal_topics[:8])}\n"
                f"    Entities: {', '.join(obs.signal_entities[:5])}\n"
                f"    Headlines: {'; '.join(obs.headline_sample[:3])}"
            )

        prompt = _TEMPORAL_ANALYSIS_PROMPT.format(
            event_name=pattern.anchor_event,
            category=pattern.anchor_category,
            window=pattern.window,
            observations="\n".join(obs_lines),
        )

        try:
            result = self.llm.call_json(
                system_prompt="You are a temporal pattern analyst. Return valid JSON only.",
                user_prompt=prompt,
                temperature=0.3,
                max_tokens=1000,
            )
            if result:
                pattern.description = result.get("description", pattern.description)
                llm_confidence = result.get("confidence", pattern.confidence)
                # Blend LLM confidence with statistical confidence
                pattern.confidence = round(
                    0.5 * pattern.confidence + 0.5 * llm_confidence, 3
                )
                self._total_patterns_learned += 1
                self._state_dirty = True

                logger.info(
                    "[Temporal] Learned pattern: %s — '%s' (conf=%.2f, obs=%d)",
                    pattern.pattern_id, pattern.description[:60],
                    pattern.confidence, pattern.observation_count,
                )
                self._journal_log("pattern_learned", {
                    "pattern_id": pattern.pattern_id,
                    "description": pattern.description,
                    "confidence": pattern.confidence,
                    "observation_count": pattern.observation_count,
                })
        except Exception as exc:
            logger.warning("[Temporal] Pattern learning failed: %s", exc)

    # ══════════════════════════════════════════════════════════════
    #  PRECURSOR DETECTION
    # ══════════════════════════════════════════════════════════════

    def check_precursors(self) -> list[dict]:
        """Check if current signals match historical pre-event patterns.

        Called periodically. Looks at upcoming calendar events, finds
        mature pre-event patterns, and compares to current signal landscape.

        Returns list of precursor alerts with match scores.
        """
        if not self.calendar:
            return []

        alerts = []
        upcoming = self.calendar.get_upcoming_events(days_ahead=PRE_EVENT_WINDOW_DAYS)

        for event in upcoming:
            event_name = event.get("name", "")
            event_category = event.get("category", "")
            days_until = event.get("days_until", 999)

            # Find mature pre-event patterns for this event type
            for pattern in self._patterns:
                if not pattern.is_mature:
                    continue
                if pattern.pattern_type != "pre_event":
                    continue
                # Match by event name similarity (handles "FOMC Decision" vs "FOMC Decision + Projections")
                if not self._event_name_matches(pattern.anchor_event, event_name):
                    continue

                # Current signal snapshot
                current_signals = self._get_current_signal_snapshot()
                if not current_signals:
                    continue

                # Compare current signals to historical pattern
                match_score = self._compute_precursor_match(pattern, current_signals)

                if match_score >= PRECURSOR_MATCH_THRESHOLD:
                    pattern.last_matched = time.time()
                    pattern.times_predicted += 1
                    self._state_dirty = True
                    self._total_precursor_checks += 1

                    alert = {
                        "event_name": event_name,
                        "days_until": days_until,
                        "pattern_id": pattern.pattern_id,
                        "pattern_description": pattern.description,
                        "match_score": round(match_score, 3),
                        "pattern_confidence": pattern.confidence,
                        "observation_count": pattern.observation_count,
                        "typical_domains": pattern.typical_domains,
                        "typical_topics": pattern.typical_topics[:8],
                        "typical_entities": pattern.typical_entities[:5],
                        "accuracy": pattern.accuracy,
                    }
                    alerts.append(alert)

                    logger.info(
                        "[Temporal] PRECURSOR MATCH: %s in %dd — pattern '%s' "
                        "match=%.2f, conf=%.2f (%d obs)",
                        event_name, days_until, pattern.description[:50],
                        match_score, pattern.confidence, pattern.observation_count,
                    )
                    self._journal_log("precursor_match", alert)

        return alerts

    def _compute_precursor_match(
        self, pattern: RecurringPattern, current: dict,
    ) -> float:
        """Compare current signal landscape to a learned pattern."""
        score = 0.0

        # Domain overlap
        current_domains = set(current.get("domains", []))
        pattern_domains = set(pattern.typical_domains)
        if current_domains and pattern_domains:
            domain_overlap = len(current_domains & pattern_domains) / max(1, len(pattern_domains))
            score += 0.35 * domain_overlap

        # Topic overlap
        current_topics = set(current.get("topics", []))
        pattern_topics = set(pattern.typical_topics)
        if current_topics and pattern_topics:
            topic_overlap = len(current_topics & pattern_topics) / max(1, len(pattern_topics))
            score += 0.35 * topic_overlap

        # Entity overlap
        current_entities = set(current.get("entities", []))
        pattern_entities = set(pattern.typical_entities)
        if current_entities and pattern_entities:
            entity_overlap = len(current_entities & pattern_entities) / max(1, len(pattern_entities))
            score += 0.20 * entity_overlap

        # Signal volume similarity
        current_count = current.get("signal_count", 0)
        if pattern.avg_signal_count > 0 and current_count > 0:
            volume_ratio = min(current_count, pattern.avg_signal_count) / max(
                current_count, pattern.avg_signal_count
            )
            score += 0.10 * volume_ratio

        return score

    def _get_current_signal_snapshot(self) -> dict | None:
        """Get a summary of recent signals for precursor matching."""
        if not self.perception_db:
            return None

        try:
            events = self.perception_db.get_recent_events(
                hours_back=72,  # Last 3 days
                max_events=150,
            )
            if not events:
                return None

            domains = {}
            topics = {}
            entities = {}

            for ev in events:
                domain = (ev.get("domain") or "MULTI").upper()
                domains[domain] = domains.get(domain, 0) + 1
                headline = ev.get("headline", "")
                for word in _extract_simple_topics(headline):
                    topics[word] = topics.get(word, 0) + 1
                if self.entity_graph and headline:
                    try:
                        ents = self.entity_graph.extract_entities(headline)
                        for name, _ in ents:
                            entities[name] = entities.get(name, 0) + 1
                    except Exception:
                        pass

            return {
                "domains": sorted(domains, key=domains.get, reverse=True)[:5],
                "topics": sorted(topics, key=topics.get, reverse=True)[:15],
                "entities": sorted(entities, key=entities.get, reverse=True)[:10],
                "signal_count": len(events),
            }
        except Exception as exc:
            logger.debug("[Temporal] Signal snapshot failed: %s", exc)
            return None

    # ══════════════════════════════════════════════════════════════
    #  SEQUENCE DETECTION (A → B chains)
    # ══════════════════════════════════════════════════════════════

    def start_sequence_watch(
        self,
        event_a_headline: str,
        event_a_topics: set,
        event_a_entities: set,
        event_a_domains: set,
        expected_b_topics: set | None = None,
        expected_b_entities: set | None = None,
        max_delay_days: int = 7,
    ) -> str | None:
        """Start watching for a follow-on event B after event A.

        If expected_b is None, uses LLM to predict what B might be.
        Returns sequence_id if created.
        """
        now = time.time()
        seq_id = f"seq_{int(now * 1000)}"

        # If no expected B, use LLM to predict
        if expected_b_topics is None and self.llm:
            try:
                result = self.llm.call_json(
                    system_prompt="You are a causal sequence analyst. Return valid JSON only.",
                    user_prompt=_SEQUENCE_DETECTION_PROMPT.format(
                        event_a=event_a_headline,
                        domains=", ".join(sorted(event_a_domains)),
                        entities=", ".join(sorted(event_a_entities)[:5]),
                        max_days=max_delay_days,
                    ),
                    temperature=0.4,
                    max_tokens=800,
                )
                if result:
                    expected_b_topics = set(result.get("expected_topics", []))
                    expected_b_entities = set(result.get("expected_entities", []))
                    max_delay_days = min(14, result.get("expected_delay_days", 7))
                    logger.info(
                        "[Temporal] Sequence predicted: '%s' → '%s' (within %dd)",
                        event_a_headline[:50],
                        result.get("expected_event_b", "?")[:50],
                        max_delay_days,
                    )
            except Exception as exc:
                logger.debug("[Temporal] Sequence prediction failed: %s", exc)
                return None

        if not expected_b_topics:
            return None

        seq = PendingSequence(
            sequence_id=seq_id,
            event_a_topics=event_a_topics,
            event_a_entities=event_a_entities,
            event_a_domains=event_a_domains,
            event_a_headline=event_a_headline,
            event_a_ts=now,
            expected_b_topics=expected_b_topics,
            expected_b_entities=expected_b_entities or set(),
            max_delay_days=max_delay_days,
            observed_b=False,
            created_at=now,
        )
        self._pending_sequences.append(seq)
        self._total_sequences_detected += 1
        self._state_dirty = True

        # Prune expired sequences
        self._prune_sequences()

        self._journal_log("sequence_started", {
            "sequence_id": seq_id,
            "event_a": event_a_headline[:80],
            "expected_b_topics": sorted(expected_b_topics)[:5],
            "max_delay_days": max_delay_days,
        })

        return seq_id

    def check_sequence_signal(
        self,
        headline: str,
        topics: set,
        entities: set,
    ) -> list[dict]:
        """Check if a new signal matches any pending sequence's event B.

        Called from PatternAccumulator.ingest() for each new signal.
        Returns list of matched sequences.
        """
        matches = []
        now = time.time()

        for seq in self._pending_sequences:
            if seq.observed_b:
                continue
            # Check expiry
            age_days = (now - seq.event_a_ts) / 86400
            if age_days > seq.max_delay_days:
                continue

            # Topic match
            topic_overlap = len(topics & seq.expected_b_topics) if seq.expected_b_topics else 0
            entity_overlap = len(entities & seq.expected_b_entities) if seq.expected_b_entities else 0

            if topic_overlap >= 2 or entity_overlap >= 1:
                seq.observed_b = True
                self._state_dirty = True
                delay_hours = (now - seq.event_a_ts) / 3600

                match_info = {
                    "sequence_id": seq.sequence_id,
                    "event_a": seq.event_a_headline[:80],
                    "event_b": headline[:80],
                    "delay_hours": round(delay_hours, 1),
                    "topic_overlap": topic_overlap,
                    "entity_overlap": entity_overlap,
                }
                matches.append(match_info)

                logger.info(
                    "[Temporal] SEQUENCE COMPLETED: '%s' → '%s' (%.1fh delay)",
                    seq.event_a_headline[:40], headline[:40], delay_hours,
                )
                self._journal_log("sequence_completed", match_info)

        return matches

    def _prune_sequences(self) -> None:
        """Remove expired or completed sequences."""
        now = time.time()
        before = len(self._pending_sequences)
        self._pending_sequences = [
            s for s in self._pending_sequences
            if not s.observed_b and (now - s.event_a_ts) / 86400 <= s.max_delay_days + 1
        ]
        pruned = before - len(self._pending_sequences)
        if pruned:
            logger.debug("[Temporal] Pruned %d expired/completed sequences", pruned)

    # ══════════════════════════════════════════════════════════════
    #  BACKGROUND LOOP — periodic observation & checking
    # ══════════════════════════════════════════════════════════════

    def periodic_check(self) -> dict:
        """Run periodic temporal checks. Called by background loop.

        1. Record observations for events in observation windows
        2. Check precursors for upcoming events
        3. Save state if dirty

        Returns summary dict.
        """
        results = {
            "observations_recorded": 0,
            "precursor_alerts": [],
            "sequences_active": len(self._pending_sequences),
        }

        # 1. Record observations for events near now
        if self.calendar:
            self._record_nearby_event_windows(results)

        # 2. Check precursors
        precursors = self.check_precursors()
        results["precursor_alerts"] = precursors

        # 3. Prune expired sequences
        self._prune_sequences()
        results["sequences_active"] = len(self._pending_sequences)

        # 4. Save if dirty
        if self._state_dirty:
            self._save_state()
            self._state_dirty = False

        return results

    def _record_nearby_event_windows(self, results: dict) -> None:
        """Record observations for events currently in observation windows."""
        if not self.calendar:
            return

        now = datetime.now(timezone.utc)
        windows_to_check = [
            ("pre_7d", 7, 4),    # 7 days before → record if 4-7 days away
            ("pre_3d", 3, 1),    # 3 days before → record if 1-3 days away
            ("pre_1d", 1, 0),    # 1 day before → record if 0-1 days away
            ("post_1d", -1, -2), # 1 day after → record if 1-2 days past
            ("post_3d", -3, -4), # 3 days after → record if 3-4 days past
        ]

        # Check events within 14 days
        upcoming = self.calendar.get_upcoming_events(days_ahead=14)
        # Also need recently past events for post-event windows
        all_events = self.calendar._curated_events + self.calendar._dynamic_events

        for ev in all_events:
            try:
                ev_date = datetime.strptime(ev["date"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, KeyError):
                continue

            days_diff = (ev_date - now).total_seconds() / 86400

            for window_name, window_start_days, window_end_days in windows_to_check:
                # Check if the event is in the right range for this window
                if window_end_days <= days_diff <= window_start_days:
                    # Check if we already recorded this observation recently
                    pattern_key = self._pattern_key(
                        ev.get("name", ""), ev.get("category", ""), window_name,
                    )
                    already_recorded = False
                    for p in self._patterns:
                        if p.pattern_id == pattern_key and p.observations:
                            last_obs = p.observations[-1]
                            if time.time() - last_obs.timestamp < 86400:  # Within 24h
                                already_recorded = True
                                break

                    if not already_recorded:
                        obs = self.record_event_window(
                            event_name=ev.get("name", ""),
                            event_category=ev.get("category", ""),
                            event_date=ev_date,
                            window=window_name,
                        )
                        if obs:
                            results["observations_recorded"] += 1

    # ══════════════════════════════════════════════════════════════
    #  DIGEST — for pipeline/chat context injection
    # ══════════════════════════════════════════════════════════════

    def get_temporal_digest(self) -> str:
        """Generate temporal intelligence digest for LLM context injection.

        Format:
          TEMPORAL INTELLIGENCE (learned from N observations):
          ⏰ PRE-EVENT ALERT: FOMC in 3d — historical pattern: VIX rises, gold spikes...
          🔗 ACTIVE SEQUENCE: sanctions → military escalation expected within 5d...
          📊 PATTERN: Before ECB decisions, EUR/USD volatility increases...
        """
        now = time.time()
        if now - self._last_digest_ts < DIGEST_COOLDOWN and self._cached_digest:
            return self._cached_digest

        lines = []

        # 1. Precursor alerts (most actionable)
        precursors = self.check_precursors()
        if precursors:
            for alert in precursors[:3]:
                desc = alert.get("pattern_description", "recurring pattern detected")
                lines.append(
                    f"⏰ PRE-EVENT ALERT: {alert['event_name']} in {alert['days_until']}d — "
                    f"historical pattern (conf={alert['pattern_confidence']:.0%}, "
                    f"{alert['observation_count']} obs): {desc}"
                )
                if alert.get("typical_entities"):
                    lines.append(
                        f"   Watch entities: {', '.join(alert['typical_entities'][:5])}"
                    )

        # 2. Active sequences
        active_seqs = [
            s for s in self._pending_sequences
            if not s.observed_b and (now - s.event_a_ts) / 86400 <= s.max_delay_days
        ]
        for seq in active_seqs[:3]:
            hours_elapsed = (now - seq.event_a_ts) / 3600
            hours_remaining = (seq.max_delay_days * 24) - hours_elapsed
            lines.append(
                f"🔗 SEQUENCE WATCH: '{seq.event_a_headline[:60]}' → "
                f"expected follow-on within {hours_remaining:.0f}h "
                f"(topics: {', '.join(sorted(seq.expected_b_topics)[:4])})"
            )

        # 3. Mature patterns summary (background knowledge)
        mature = [p for p in self._patterns if p.is_mature and p.description]
        if mature:
            top_patterns = sorted(mature, key=lambda p: p.confidence, reverse=True)[:3]
            for p in top_patterns:
                if p.pattern_id not in {a.get("pattern_id") for a in precursors}:
                    lines.append(
                        f"📊 LEARNED PATTERN ({p.anchor_event}/{p.window}, "
                        f"conf={p.confidence:.0%}): {p.description}"
                    )

        if not lines:
            self._cached_digest = ""
            self._last_digest_ts = now
            return ""

        header = f"TEMPORAL INTELLIGENCE ({self._total_observations} observations, " \
                 f"{len(mature)} learned patterns) ==="
        digest = f"=== {header}\n" + "\n".join(lines) + "\n"

        self._cached_digest = digest
        self._last_digest_ts = now
        return digest

    # ══════════════════════════════════════════════════════════════
    #  STATS & API
    # ══════════════════════════════════════════════════════════════

    def stats(self) -> dict:
        """Return engine statistics."""
        mature = [p for p in self._patterns if p.is_mature]
        return {
            "total_patterns": len(self._patterns),
            "mature_patterns": len(mature),
            "total_observations": self._total_observations,
            "total_patterns_learned": self._total_patterns_learned,
            "total_precursor_checks": self._total_precursor_checks,
            "total_sequences_detected": self._total_sequences_detected,
            "active_sequences": len([
                s for s in self._pending_sequences
                if not s.observed_b
            ]),
            "top_patterns": [
                {
                    "id": p.pattern_id,
                    "event": p.anchor_event,
                    "window": p.window,
                    "description": p.description,
                    "confidence": p.confidence,
                    "observations": p.observation_count,
                    "accuracy": p.accuracy,
                }
                for p in sorted(mature, key=lambda x: x.confidence, reverse=True)[:10]
            ],
        }

    def get_all_patterns(self) -> list[dict]:
        """Return all patterns as dicts."""
        return [p.to_dict() for p in self._patterns]

    # ══════════════════════════════════════════════════════════════
    #  PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def _save_state(self) -> None:
        """Persist patterns and sequences to disk."""
        try:
            state = {
                "version": 1,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "total_observations": self._total_observations,
                "total_patterns_learned": self._total_patterns_learned,
                "total_precursor_checks": self._total_precursor_checks,
                "total_sequences_detected": self._total_sequences_detected,
                "patterns": [p.to_dict() for p in self._patterns],
                "pending_sequences": [
                    {
                        "sequence_id": s.sequence_id,
                        "event_a_topics": sorted(s.event_a_topics),
                        "event_a_entities": sorted(s.event_a_entities),
                        "event_a_domains": sorted(s.event_a_domains),
                        "event_a_headline": s.event_a_headline,
                        "event_a_ts": s.event_a_ts,
                        "expected_b_topics": sorted(s.expected_b_topics),
                        "expected_b_entities": sorted(s.expected_b_entities),
                        "max_delay_days": s.max_delay_days,
                        "observed_b": s.observed_b,
                        "created_at": s.created_at,
                    }
                    for s in self._pending_sequences
                    if not s.observed_b
                ],
            }
            _PERSIST_PATH.write_text(
                json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            logger.info(
                "[Temporal] State saved — %d patterns, %d sequences",
                len(self._patterns), len(self._pending_sequences),
            )
        except Exception as exc:
            logger.warning("[Temporal] Save failed: %s", exc)

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        if not _PERSIST_PATH.exists():
            return

        try:
            data = json.loads(_PERSIST_PATH.read_text(encoding="utf-8"))
            self._total_observations = data.get("total_observations", 0)
            self._total_patterns_learned = data.get("total_patterns_learned", 0)
            self._total_precursor_checks = data.get("total_precursor_checks", 0)
            self._total_sequences_detected = data.get("total_sequences_detected", 0)

            for pd in data.get("patterns", []):
                try:
                    self._patterns.append(RecurringPattern.from_dict(pd))
                except Exception:
                    continue

            for sd in data.get("pending_sequences", []):
                try:
                    self._pending_sequences.append(PendingSequence(
                        sequence_id=sd["sequence_id"],
                        event_a_topics=set(sd.get("event_a_topics", [])),
                        event_a_entities=set(sd.get("event_a_entities", [])),
                        event_a_domains=set(sd.get("event_a_domains", [])),
                        event_a_headline=sd.get("event_a_headline", ""),
                        event_a_ts=sd.get("event_a_ts", 0),
                        expected_b_topics=set(sd.get("expected_b_topics", [])),
                        expected_b_entities=set(sd.get("expected_b_entities", [])),
                        max_delay_days=sd.get("max_delay_days", 7),
                        observed_b=sd.get("observed_b", False),
                        created_at=sd.get("created_at", 0),
                    ))
                except Exception:
                    continue

            logger.info(
                "[Temporal] Loaded state — %d patterns (%d mature), %d sequences",
                len(self._patterns),
                sum(1 for p in self._patterns if p.is_mature),
                len(self._pending_sequences),
            )
        except Exception as exc:
            logger.warning("[Temporal] Load failed (starting fresh): %s", exc)

    def _journal_log(self, event_type: str, data: dict) -> None:
        """Append event to JSONL journal."""
        try:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                **data,
            }
            with open(_JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _pattern_key(event_name: str, category: str, window: str) -> str:
        """Generate a unique key for a pattern based on event+category+window."""
        # Normalize event name (strip year-specific suffixes)
        base = event_name.lower().strip()
        # Remove "2025", "2026", "+ projections", etc. for grouping
        for suffix in ("+ projections", "+ outlook", "2025", "2026", "2027"):
            base = base.replace(suffix, "").strip()
        return f"{base}__{category}__{window}"

    @staticmethod
    def _event_name_matches(pattern_event: str, calendar_event: str) -> bool:
        """Check if a pattern's anchor event matches a calendar event name."""
        a = pattern_event.lower().strip()
        b = calendar_event.lower().strip()
        # Strip qualifiers
        for q in ("+ projections", "+ outlook", "2025", "2026", "2027"):
            a = a.replace(q, "").strip()
            b = b.replace(q, "").strip()
        return a == b or a in b or b in a

    @staticmethod
    def _window_to_hours(window: str, event_date: datetime) -> int | None:
        """Convert window name to hours_back for PerceptionDB query."""
        now = datetime.now(timezone.utc)
        mapping = {
            "pre_7d": 7 * 24,
            "pre_3d": 3 * 24,
            "pre_1d": 24,
            "post_1d": 24,
            "post_3d": 3 * 24,
            "post_7d": 7 * 24,
        }
        return mapping.get(window)

    @staticmethod
    def _window_boundaries(
        window: str, event_date: datetime,
    ) -> tuple[datetime, datetime]:
        """Get (start, end) datetime boundaries for a window."""
        if window == "pre_7d":
            return event_date - timedelta(days=7), event_date - timedelta(days=3)
        elif window == "pre_3d":
            return event_date - timedelta(days=3), event_date - timedelta(days=1)
        elif window == "pre_1d":
            return event_date - timedelta(days=1), event_date
        elif window == "post_1d":
            return event_date, event_date + timedelta(days=1)
        elif window == "post_3d":
            return event_date + timedelta(days=1), event_date + timedelta(days=3)
        elif window == "post_7d":
            return event_date + timedelta(days=3), event_date + timedelta(days=7)
        else:
            return event_date - timedelta(days=3), event_date


# ── Utility ──

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "but", "and", "or", "if", "up", "out",
    "about", "it", "its", "this", "that", "these", "those", "he", "she",
    "his", "her", "they", "their", "we", "our", "you", "your", "says",
    "said", "new", "also", "over", "us", "my", "what", "which", "who",
    "whom", "while", "—", "–", "s", "t", "re", "ve", "d", "ll", "m",
})


def _extract_simple_topics(headline: str) -> list[str]:
    """Extract meaningful topic words from a headline (no NLP, just filtering)."""
    import re
    words = re.findall(r"[a-zA-Z]{3,}", headline.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2][:20]
