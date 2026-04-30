"""
XDART-Φ × XHEART — Trending Keyword Spike Detection

Ported from WorldMonitor trending-keywords.ts logic.

Every RSS headline is tokenized. Per-term frequency tracked over:
  - 2-hour rolling window (current activity)
  - 7-day baseline (hourly refresh)

Spike fires when ALL conditions met:
  - Absolute count > MIN_SPIKE_COUNT (5)
  - Current > baseline × SPIKE_MULTIPLIER (3×)
  - ≥ MIN_SOURCES unique RSS sources
  - Cooldown elapsed (COOLDOWN_SECONDS since last spike for same term)

Compound terms preserved: world leaders, CVE-IDs, threat actor designators.
Blocklist suppresses common noise.
Registry capped at MAX_TERMS with LRU eviction.
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger("xdart.perception.keyword_spikes")

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

MIN_SPIKE_COUNT = 60           # only truly dominant keywords (was 10)
MIN_SPIKE_COUNT_ZERO_BASELINE = 60  # same floor when no baseline exists
SPIKE_MULTIPLIER = 5.0         # current must exceed baseline × this (was 3×)
MIN_SOURCES = 3                # from at least N unique RSS feeds (was 2)
COOLDOWN_SECONDS = 3600        # 60 min cooldown per term (was 30 min)
WINDOW_SECONDS = 7200          # 2-hour rolling window
BASELINE_SECONDS = 604800      # 7-day baseline
BASELINE_REFRESH_SECONDS = 3600  # re-compute baseline every hour
MAX_TERMS = 10000              # LRU cap on tracked terms
MAX_SPIKES_PER_CYCLE = 25      # cap spikes per ingest call to prevent explosion

# Minimum baseline rate (mentions/hour). Prevents spurious spikes when the
# system is new or a term has no history. With 50+ feeds scanning every cycle,
# common geopolitical terms naturally appear ~1-5 times/hour. A floor of 0.5
# means a term must hit 5× this baseline (= 5 in 2h) to spike — not 840×.
_MIN_BASELINE_RATE = 0.5

# ─────────────────────────────────────────────────────────────────────
# Compound Terms (preserved during tokenization)
# ─────────────────────────────────────────────────────────────────────

COMPOUND_TERMS = [
    "xi jinping", "kim jong un", "joe biden", "donald trump",
    "vladimir putin", "benjamin netanyahu", "narendra modi",
    "mohammed bin salman", "recep erdogan", "olaf scholz",
    "emmanuel macron", "keir starmer",
    "north korea", "south korea", "south china sea",
    "united states", "united nations", "european union",
    "hong kong", "abu dhabi", "saudi arabia",
    "artificial intelligence", "machine learning",
    "supply chain", "rate cut", "rate hike",
    "cease fire", "ceasefire", "no fly zone",
    "iron dome", "strait of hormuz", "suez canal",
    "taiwan strait", "black sea", "baltic sea",
]

# Pattern to extract CVE identifiers
CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)

# APT/FIN threat actor designators
THREAT_ACTOR_PATTERN = re.compile(r"\b(APT|FIN|UNC)\d{1,4}\b", re.IGNORECASE)

# ─────────────────────────────────────────────────────────────────────
# Blocklist — suppress noise terms
# ─────────────────────────────────────────────────────────────────────

BLOCKLIST = frozenset({
    # Determiners, pronouns, prepositions, conjunctions
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "up", "about", "into", "over",
    "after", "is", "are", "was", "were", "be", "has", "had", "have",
    "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "this", "that", "these", "those",
    "it", "its", "he", "she", "they", "we", "his", "her", "their",
    "our", "my", "your", "new", "says", "said", "also", "more",
    "than", "just", "now", "not", "no", "all", "some", "any",
    "been", "being", "get", "got", "set", "one", "two", "three",
    "who", "what", "when", "where", "how", "why", "which",
    # Common verbs & adverbs that are never geopolitically meaningful
    "out", "end", "back", "make", "time", "take", "come", "see",
    "look", "find", "give", "tell", "work", "call", "try", "ask",
    "need", "feel", "become", "leave", "put", "mean", "keep", "let",
    "begin", "show", "hear", "play", "run", "move", "live", "believe",
    "hold", "bring", "happen", "write", "provide", "sit", "stand",
    "lose", "pay", "meet", "include", "continue", "start", "still",
    "much", "even", "here", "there", "then", "only", "very", "often",
    "well", "way", "long", "too", "most", "such", "use", "used",
    "first", "last", "next", "same", "few", "many", "each", "every",
    "both", "own", "other", "another", "going", "really", "big",
    "high", "right", "left", "old", "great", "good", "bad", "little",
    "year", "years", "day", "days", "week", "month", "today",
    "people", "world", "part", "number", "fact", "thing", "point",
    "case", "group", "percent", "place", "area", "country",
    # News filler words
    "report", "reports", "news", "update", "updates", "via", "per",
    "reuters", "associated press", "afp", "according", "sources",
    "official", "officials", "government", "minister", "president",
    "says", "said", "told", "added", "noted", "statement",
    "latest", "breaking", "developing", "ahead", "amid", "despite",
    # Common English words that trigger false spikes
    "through", "under", "before", "after", "during", "since", "near",
    "across", "against", "between", "within",
    "free", "open", "close", "second", "third", "four", "five",
    "major", "further", "massive", "inside", "outside",
    "help", "home", "page", "video", "using", "becomes", "leaves",
    "others", "know", "join", "asks", "seeks", "warns", "urges",
    "claims", "hits", "fires", "continues", "announces", "releases",
    "proposes", "threatens", "becomes", "match", "talk", "door",
    "must", "former", "annual", "modern", "brief", "list",
    "request", "updated", "progress", "situation", "commitment",
    "data", "system", "systems", "programs", "services", "company",
    "center", "department", "director", "officer", "agency", "member",
    "operation", "phase", "base", "post", "race", "earth", "plant",
    "language", "analysis", "access", "school", "media", "business",
    "financial", "support", "meeting", "close", "sites",
})


# ─────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────

@dataclass
class TermOccurrence:
    """Single occurrence of a term."""
    timestamp: float
    source: str


@dataclass
class TermRecord:
    """Tracked term with rolling window and baseline."""
    occurrences: list[TermOccurrence] = field(default_factory=list)
    baseline_rate: float = 0.0         # avg hourly rate over 7 days
    baseline_computed_at: float = 0.0
    last_spike_at: float = 0.0


@dataclass
class SpikeEvent:
    """Detected keyword spike."""
    term: str
    current_count: int
    baseline_rate: float
    surge_ratio: float
    unique_sources: int
    detected_at: float


# ─────────────────────────────────────────────────────────────────────
# Tokenizer
# ─────────────────────────────────────────────────────────────────────

def tokenize_headline(headline: str) -> list[str]:
    """Tokenize headline, preserving compound terms, CVEs, threat actors.

    Returns lowercase token list with blocklist filtered out.
    """
    text = headline.lower().strip()
    tokens: list[str] = []

    # Extract CVE identifiers
    for match in CVE_PATTERN.finditer(text):
        tokens.append(match.group(0).upper())
    text = CVE_PATTERN.sub("", text)

    # Extract threat actor designators
    for match in THREAT_ACTOR_PATTERN.finditer(text):
        tokens.append(match.group(0).upper())
    text = THREAT_ACTOR_PATTERN.sub("", text)

    # Extract compound terms (greedy longest-first)
    sorted_compounds = sorted(COMPOUND_TERMS, key=len, reverse=True)
    for compound in sorted_compounds:
        if compound in text:
            tokens.append(compound)
            text = text.replace(compound, " ")

    # Split remaining into individual words (alphanumeric, min 4 chars to suppress noise)
    words = re.findall(r"[a-z0-9]{4,}", text)
    for w in words:
        if w not in BLOCKLIST:
            tokens.append(w)

    return tokens


# ─────────────────────────────────────────────────────────────────────
# Spike Detector
# ─────────────────────────────────────────────────────────────────────

class KeywordSpikeDetector:
    """Tracks keyword frequencies and detects spikes.

    Thread-safe for single-writer (collector) pattern.
    """

    def __init__(self):
        self._registry: OrderedDict[str, TermRecord] = OrderedDict()
        self._spike_history: list[SpikeEvent] = []

    def ingest_headline(
        self,
        headline: str,
        source_name: str,
        timestamp: float | None = None,
    ) -> list[SpikeEvent]:
        """Ingest a headline, update term frequencies, check for spikes.

        Returns list of newly detected spikes (usually empty).
        """
        ts = timestamp or time.time()
        tokens = tokenize_headline(headline)
        new_spikes: list[SpikeEvent] = []

        for token in tokens:
            record = self._get_or_create(token)
            record.occurrences.append(TermOccurrence(timestamp=ts, source=source_name))

            # Prune old occurrences (keep 7-day window for baseline)
            cutoff = ts - BASELINE_SECONDS
            record.occurrences = [
                o for o in record.occurrences if o.timestamp > cutoff
            ]

            # Refresh baseline if stale
            if ts - record.baseline_computed_at > BASELINE_REFRESH_SECONDS:
                self._refresh_baseline(record, ts)

            # Check spike conditions (cap per call to prevent explosion)
            if len(new_spikes) >= MAX_SPIKES_PER_CYCLE:
                break
            spike = self._check_spike(token, record, ts)
            if spike:
                new_spikes.append(spike)
                record.last_spike_at = ts

        return new_spikes

    def get_recent_spikes(self, max_age_seconds: float = 3600) -> list[SpikeEvent]:
        """Get spikes from the last N seconds."""
        cutoff = time.time() - max_age_seconds
        return [s for s in self._spike_history if s.detected_at > cutoff]

    def get_trending_terms(self, top_n: int = 20) -> list[dict]:
        """Get top-N terms by current 2-hour window count."""
        now = time.time()
        cutoff = now - WINDOW_SECONDS
        term_counts: list[tuple[str, int, int]] = []

        for term, record in self._registry.items():
            window_occs = [o for o in record.occurrences if o.timestamp > cutoff]
            if window_occs:
                count = len(window_occs)
                sources = len({o.source for o in window_occs})
                term_counts.append((term, count, sources))

        term_counts.sort(key=lambda x: x[1], reverse=True)

        return [
            {"term": t, "count": c, "sources": s}
            for t, c, s in term_counts[:top_n]
        ]

    def get_trend_dashboard(self, top_n: int = 15) -> str:
        """Generate a compact trend dashboard string for LLM context injection.

        Shows top trending keywords with direction, momentum, and recent spikes.
        Returns a formatted string ready for direct injection into context.
        """
        now = time.time()
        window_cutoff = now - WINDOW_SECONDS
        day_cutoff = now - 86400  # 24h lookback for direction

        # Calculate current window counts + 24h baseline for direction
        trend_data: list[tuple[str, int, int, float, float]] = []  # term, count_2h, sources, baseline_rate, surge

        for term, record in self._registry.items():
            window_occs = [o for o in record.occurrences if o.timestamp > window_cutoff]
            if not window_occs:
                continue
            count_2h = len(window_occs)
            sources_2h = len({o.source for o in window_occs})

            # 24h baseline (hourly rate)
            day_occs = [o for o in record.occurrences if o.timestamp > day_cutoff]
            baseline_rate = len(day_occs) / 24.0 if day_occs else 0.0
            # 2h rate
            rate_2h = count_2h / (WINDOW_SECONDS / 3600)
            surge = rate_2h / max(baseline_rate, _MIN_BASELINE_RATE)

            trend_data.append((term, count_2h, sources_2h, baseline_rate, surge))

        if not trend_data:
            return ""

        # Sort by current count
        trend_data.sort(key=lambda x: x[1], reverse=True)

        lines = [f"KEYWORD TREND DASHBOARD (top {min(top_n, len(trend_data))} terms, 2h window):"]

        for term, count, sources, baseline, surge in trend_data[:top_n]:
            # Direction arrow based on surge ratio
            if surge >= 3.0:
                arrow = "⬆⬆"  # surging
            elif surge >= 1.5:
                arrow = "⬆"   # rising
            elif surge >= 0.8:
                arrow = "→"   # stable
            elif surge >= 0.3:
                arrow = "⬇"   # declining
            else:
                arrow = "⬇⬇"  # dropping fast

            lines.append(
                f"  {arrow} {term}: {count} mentions ({sources} sources) "
                f"[{surge:.1f}× baseline]"
            )

        # Recent spikes (last 2h)
        recent_spikes = self.get_recent_spikes(max_age_seconds=7200)
        if recent_spikes:
            lines.append(f"\nRECENT SPIKES ({len(recent_spikes)} in last 2h):")
            for spike in recent_spikes[-5:]:
                lines.append(
                    f"  🔺 '{spike.term}' — {spike.current_count} mentions, "
                    f"{spike.surge_ratio}× surge from {spike.unique_sources} sources"
                )

        return "\n".join(lines)

    @property
    def registry_size(self) -> int:
        return len(self._registry)

    # ── Internal ──

    def _get_or_create(self, term: str) -> TermRecord:
        """Get or create a term record with LRU eviction."""
        if term in self._registry:
            self._registry.move_to_end(term)
            return self._registry[term]

        # Evict oldest if at capacity
        while len(self._registry) >= MAX_TERMS:
            self._registry.popitem(last=False)

        record = TermRecord()
        self._registry[term] = record
        return record

    def _refresh_baseline(self, record: TermRecord, now: float):
        """Compute 7-day baseline as average hourly rate.

        Uses a minimum baseline floor to prevent spurious spikes when the
        system is new or when a term has very sparse history.  Common news
        terms naturally appear ~1-5 times per hour across 50+ RSS feeds,
        so a floor of 0.5/hour (= 1.0 per 2-hour window) prevents every
        single term from registering as a 840× spike on first appearance.
        """
        baseline_cutoff = now - BASELINE_SECONDS
        baseline_occs = [
            o for o in record.occurrences if o.timestamp > baseline_cutoff
        ]
        hours = BASELINE_SECONDS / 3600
        computed_rate = len(baseline_occs) / hours if hours > 0 else 0.0
        # Minimum baseline floor: 0.5 mentions/hour across all feeds.
        # This means a term must have >5× normal background noise to spike.
        record.baseline_rate = max(computed_rate, _MIN_BASELINE_RATE)
        record.baseline_computed_at = now

    def _check_spike(
        self, term: str, record: TermRecord, now: float,
    ) -> SpikeEvent | None:
        """Check if term meets all spike conditions."""
        # Cooldown check
        if now - record.last_spike_at < COOLDOWN_SECONDS:
            return None

        # 2-hour window occurrences
        window_cutoff = now - WINDOW_SECONDS
        window_occs = [o for o in record.occurrences if o.timestamp > window_cutoff]
        current_count = len(window_occs)

        # Convert baseline (hourly) to 2-hour equivalent
        baseline_2h = record.baseline_rate * (WINDOW_SECONDS / 3600)

        # Condition 1: absolute count
        if current_count < MIN_SPIKE_COUNT:
            return None

        # Condition 2: surge ratio (baseline always ≥ _MIN_BASELINE_RATE, never zero)
        surge_ratio = current_count / baseline_2h if baseline_2h > 0 else float(current_count)

        if surge_ratio < SPIKE_MULTIPLIER:
            return None

        # Condition 3: source diversity
        unique_sources = len({o.source for o in window_occs})
        if unique_sources < MIN_SOURCES:
            return None

        # All conditions met → spike!
        spike = SpikeEvent(
            term=term,
            current_count=current_count,
            baseline_rate=record.baseline_rate,
            surge_ratio=round(surge_ratio, 1),
            unique_sources=unique_sources,
            detected_at=now,
        )
        self._spike_history.append(spike)

        # Prune old spike history (keep 24h)
        history_cutoff = now - 86400
        self._spike_history = [
            s for s in self._spike_history if s.detected_at > history_cutoff
        ]

        logger.info(
            "[KeywordSpike] SPIKE: '%s' — %d mentions from %d sources (%.1f× baseline)",
            term, current_count, unique_sources, surge_ratio,
        )

        return spike
