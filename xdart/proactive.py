"""
XDART-Φ — Proactive Communication Engine + Pattern Accumulator

Gives Αίολος the ability to INITIATE contact with the user,
not just respond when called. Instead of mechanical cron-based checks,
a PatternAccumulator continuously absorbs ALL data signals (news, curiosity,
prophecy, correlation alerts, keyword spikes) and clusters them into
emergent patterns. When a pattern's convergence score crosses 0.50,
the system evaluates it via LLM and—if warranted—initiates contact.

Architecture:
  Signal → PatternAccumulator → cluster by topic/region
         → convergence_score rises with each new corroborating signal
         → convergence ≥ 0.50 → LLM evaluation → notify / suppress

No timers decide when to talk. The DATA decides.

Delivery channels:
  1. In-app SSE push (when UI is open)
  2. Telegram Bot API (when UI is closed — reaches the user's phone)

© Panos Skouras — Salimov MON IKE, 2026
"""

import asyncio
import json
import logging
import math
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from xdart.llm import LLMClient

logger = logging.getLogger("xdart.proactive")

# ── Urgency Levels ──
CRITICAL = "critical"      # Immediate delivery
IMPORTANT = "important"    # Batched with next cluster
DIGEST = "digest"          # Daily summary

# ── Max notifications stored in memory ──
MAX_NOTIFICATIONS = 200

# ══════════════════════════════════════════════════════════════════════════════
#  PATTERN ACCUMULATOR — event-driven, not timer-driven
# ══════════════════════════════════════════════════════════════════════════════

# ── Convergence threshold: pattern fires when it reaches this ──
CONVERGENCE_THRESHOLD = 0.60

# ── Pattern cluster settings ──
MAX_PATTERNS = 100          # Max active pattern clusters
PATTERN_TTL = 86400         # Pattern dies after 24h without new signal
PATTERN_MERGE_SIMILARITY = 0.40  # Word overlap threshold to merge into same pattern
MIN_SIGNALS_TO_EVALUATE = 5      # Don't bother LLM until 5+ signals in cluster

# ── Signal weight by source type ──
SIGNAL_WEIGHTS = {
    "perception_event": 0.10,        # Raw news headline (common, low weight)
    "perception_alert": 0.25,        # High-salience event (salience ≥ 0.85)
    "keyword_spike": 0.30,           # Trending keyword surge
    "correlation_alert": 0.35,       # Cross-stream correlation
    "curiosity_finding": 0.20,       # Curiosity exploration result
    "prophecy_resolved": 0.40,       # Prediction confirmed/disconfirmed
    "self_evolution": 0.15,          # System self-diagnosis
    "economic_shift": 0.20,          # Economic indicator change
    "infrastructure_cascade": 0.35,  # Infrastructure dependency triggered
    "financial_anomaly": 0.45,       # Market anomaly (VIX spike, crash, etc.)
}

# ── Decay: signal weight decays over time (half-life in seconds) ──
SIGNAL_HALF_LIFE = 14400  # 4 hours — signal loses half its weight in 4h

# ══════════════════════════════════════════════════════════════════════════════
#  IMPACT SCORING — determines if a pattern is geopolitically significant
#  enough to warrant notification. Replaces volume-based alert fatigue
#  with scope/entity-aware intelligence filtering.
# ══════════════════════════════════════════════════════════════════════════════

IMPACT_THRESHOLD = 0.60  # Pattern must score ≥ this to fire notification

# ── Scope indicators: detected in pattern headlines ──
# Global events (planet-wide impact)
_GLOBAL_SCOPE = frozenset({
    "world war", "nuclear war", "global", "worldwide", "pandemic",
    "united nations", "g7", "g20", "nato", "wto", "imf", "who",
    "world economy", "global recession", "climate crisis",
    "international", "planet", "humanity",
})

# Continental scope (multi-country regional impact)
_CONTINENTAL_SCOPE = frozenset({
    "europe", "european", "asia", "asian", "africa", "african",
    "americas", "north america", "south america", "latin america",
    "middle east", "pacific", "atlantic", "arctic", "mediterranean",
    "southeast asia", "central asia", "sub-saharan",
})

# Major powers (single-country but global ripple effects)
_MAJOR_POWERS = frozenset({
    "united states", "usa", "america", "american",
    "china", "chinese", "beijing",
    "russia", "russian", "moscow", "kremlin",
    "india", "indian", "delhi",
    "japan", "japanese", "tokyo",
    "germany", "german", "berlin",
    "france", "french", "paris",
    "britain", "british", "london", "uk",
    "iran", "iranian", "tehran",
    "israel", "israeli", "jerusalem", "tel aviv",
    "saudi arabia", "saudi", "riyadh",
    "turkey", "turkish", "ankara",
    "brazil", "brazilian", "brasilia",
    "south korea", "korean", "seoul",
    "north korea", "pyongyang",
    "pakistan", "pakistani", "islamabad",
    "taiwan", "taipei",
    "ukraine", "ukrainian", "kyiv",
    "egypt", "egyptian", "cairo",
})

# Tier-1 global figures (their actions move markets + geopolitics)
_GLOBAL_FIGURES = frozenset({
    "trump", "biden", "xi jinping", "putin", "modi",
    "kim jong un", "khamenei", "netanyahu", "erdogan",
    "macron", "scholz", "starmer", "mohammed bin salman",
    "zelensky", "pope", "powell", "lagarde",
})

# Breaking news indicators (headline urgency markers)
_BREAKING_INDICATORS = frozenset({
    "breaking", "urgent", "flash", "just in", "developing",
    "εκτακτο", "εκτακτη", "εκτακτη ειδηση",
})

# Economic crisis indicators (high-impact economic events)
_ECONOMIC_CRISIS = frozenset({
    "crash", "default", "recession", "collapse", "crisis",
    "bank run", "bailout", "meltdown", "panic", "flash crash",
    "emergency rate", "hyperinflation", "depression",
    "debt ceiling", "sovereign debt", "contagion",
})

# General economic keywords (moderate boost)
_ECONOMIC_KEYWORDS = frozenset({
    "inflation", "interest rate", "rate cut", "rate hike", "gdp",
    "unemployment", "fed", "ecb", "central bank",
    "stock market", "bond yield", "treasury", "deficit",
    "trade war", "tariff", "sanctions", "oil price", "commodity",
    "currency", "devaluation", "stimulus", "quantitative",
})

# Natural disaster indicators (severe events with humanitarian/economic cascade)
_NATURAL_DISASTERS = frozenset({
    "earthquake", "tsunami", "hurricane", "typhoon", "cyclone",
    "volcano", "volcanic eruption", "eruption", "lava",
    "flood", "flooding", "flash flood", "landslide", "mudslide",
    "wildfire", "bushfire", "forest fire",
    "tornado", "drought", "famine", "heatwave", "heat wave",
    "avalanche", "blizzard", "seismic", "magnitude",
    "disaster", "catastrophe", "humanitarian crisis", "evacuation",
    "death toll", "casualties", "devastation",
    "σεισμος", "τσουναμι", "πλημμυρα", "πυρκαγια",
})

# ── Noise words for topic extraction ──
_NOISE_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "must", "need", "dare",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "but", "and", "or", "if", "while", "about", "up", "also",
    "new", "said", "says", "report", "reports", "according", "per", "via",
    "that", "this", "these", "those", "it", "its", "his", "her", "their",
    "what", "which", "who", "whom", "whose", "he", "she", "they", "them",
    "we", "you", "your", "our", "my", "us", "him",
})

# ── Topic extraction from text ──
_TOKEN_RE = re.compile(r"[a-zA-Zα-ωΑ-Ωάέήίόύώΐΰϊϋ]{3,}", re.UNICODE)


def _extract_topics(text: str) -> set[str]:
    """Extract meaningful topic words from text (lowercased, noise-filtered)."""
    tokens = set(_TOKEN_RE.findall(text.lower()))
    return tokens - _NOISE_WORDS


def _topic_similarity(topics_a: set[str], topics_b: set[str]) -> float:
    """Jaccard-like similarity between two topic sets."""
    if not topics_a or not topics_b:
        return 0.0
    intersection = topics_a & topics_b
    union = topics_a | topics_b
    return len(intersection) / len(union) if union else 0.0


class PatternSignal:
    """A single data signal absorbed by the accumulator."""

    __slots__ = ("source_type", "headline", "topics", "entities", "region",
                 "weight", "timestamp", "raw_data")

    def __init__(
        self,
        source_type: str,
        headline: str,
        topics: set[str],
        entities: set[str] | None = None,
        region: str = "GLOBAL",
        weight: float = 0.10,
        timestamp: float | None = None,
        raw_data: dict | None = None,
    ):
        self.source_type = source_type
        self.headline = headline
        self.topics = topics
        self.entities = entities or set()  # canonical entity names from NER
        self.region = region
        self.weight = weight
        self.timestamp = timestamp or time.time()
        self.raw_data = raw_data or {}

    def decayed_weight(self, now: float | None = None) -> float:
        """Weight after exponential time decay."""
        now = now or time.time()
        age = max(0, now - self.timestamp)
        return self.weight * math.exp(-0.693 * age / SIGNAL_HALF_LIFE)


class EmergentPattern:
    """A cluster of corroborating signals forming a pattern."""

    def __init__(self, seed_signal: PatternSignal):
        self.id = f"pat_{int(time.time() * 1000)}"
        self.created_at = time.time()
        self.last_signal_at = time.time()
        self.signals: list[PatternSignal] = [seed_signal]
        self.topics: set[str] = set(seed_signal.topics)
        # Entity frequency tracking — how many signals mention each entity.
        # Noise entities appear in 1 signal; real entities appear in many.
        self._entity_counts: dict[str, int] = {}
        for e in seed_signal.entities:
            self._entity_counts[e] = 1
        self.regions: set[str] = {seed_signal.region}
        self.source_types: set[str] = {seed_signal.source_type}
        self.fired = False          # Has this pattern triggered a notification?
        self.fire_count = 0         # How many times it re-fired (escalation)
        self.convergence_score = 0.0
        self.impact_score = 0.0     # Geopolitical impact (0.0-1.0), set before fire

    @property
    def entities(self) -> set[str]:
        """All entities ever seen in this pattern (includes noise)."""
        return set(self._entity_counts.keys())

    @property
    def core_entities(self) -> set[str]:
        """Entities mentioned in 2+ signals (noise-filtered).

        For small patterns (<10 signals), returns all entities.
        For larger patterns, requires entity to appear in at least
        2 signals to qualify — this naturally filters one-off garbage
        like 'Baristas', 'Buffets' that appear in a single headline.
        """
        if len(self.signals) < 10:
            return set(self._entity_counts.keys())
        min_mentions = 2
        return {e for e, c in self._entity_counts.items() if c >= min_mentions}

    def absorb(self, signal: PatternSignal) -> None:
        """Absorb a new signal into this pattern cluster."""
        self.signals.append(signal)
        self.topics |= signal.topics
        for e in signal.entities:
            self._entity_counts[e] = self._entity_counts.get(e, 0) + 1
        self.regions.add(signal.region)
        self.source_types.add(signal.source_type)
        self.last_signal_at = time.time()
        self._recalculate_convergence()

    def _recalculate_convergence(self) -> None:
        """Recalculate convergence score based on current signals.

        Score rises with:
          - More signals (diminishing returns via log)
          - Higher-weight signals (perception_alert > perception_event)
          - Source diversity (many different source types boost score)
          - Region concentration (many signals for same region = important)
          - Recency (recent signals contribute more)

        Score = weighted_mass × diversity_bonus × concentration_bonus
        Capped at 1.0
        """
        now = time.time()

        # Weighted mass: sum of decayed signal weights (log-scaled to prevent runaway)
        total_weight = sum(s.decayed_weight(now) for s in self.signals)
        # log2(mass + 1) gives diminishing returns: 0→0, 0.5→0.58, 1→1, 2→1.58, 4→2.32
        weighted_mass = math.log2(total_weight + 1)

        # Diversity bonus: more source types → higher (1.0 at 1 type, up to 1.5 at 4+ types)
        diversity_bonus = 1.0 + min(0.5, (len(self.source_types) - 1) * 0.15)

        # Concentration bonus: if one region dominates (not GLOBAL), boost
        region_counts = {}
        for s in self.signals:
            if s.region != "GLOBAL":
                region_counts[s.region] = region_counts.get(s.region, 0) + 1
        if region_counts:
            max_region_count = max(region_counts.values())
            concentration_bonus = 1.0 + min(0.3, (max_region_count - 1) * 0.10)
        else:
            concentration_bonus = 1.0

        # Final score — normalized to 0.0-1.0 range
        raw = (weighted_mass / 3.0) * diversity_bonus * concentration_bonus
        self.convergence_score = min(1.0, raw)

    def is_alive(self, now: float | None = None) -> bool:
        """Check if pattern is still active (not expired)."""
        now = now or time.time()
        return (now - self.last_signal_at) < PATTERN_TTL

    def should_fire(self) -> bool:
        """Check if pattern has crossed the convergence threshold."""
        return (
            self.convergence_score >= CONVERGENCE_THRESHOLD
            and len(self.signals) >= MIN_SIGNALS_TO_EVALUATE
            and not self.fired
        )

    def should_re_fire(self) -> bool:
        """Check if an already-fired pattern has escalated significantly.
        Re-fire at 0.75 and 0.90 thresholds."""
        if not self.fired:
            return False
        next_threshold = 0.75 if self.fire_count == 1 else 0.90
        return self.convergence_score >= next_threshold and self.fire_count < 3

    def summary_text(self) -> str:
        """Generate a summary of the pattern for LLM evaluation."""
        # Top headlines (most recent first, up to 10)
        recent = sorted(self.signals, key=lambda s: s.timestamp, reverse=True)[:10]
        headlines = "\n".join(f"  [{s.source_type}] {s.headline}" for s in recent)

        top_topics = sorted(self.topics, key=lambda t: sum(1 for s in self.signals if t in s.topics), reverse=True)[:15]

        return (
            f"PATTERN ID: {self.id}\n"
            f"Convergence: {self.convergence_score:.2f}\n"
            f"Impact: {self.impact_score:.2f}\n"
            f"Signals: {len(self.signals)} from {len(self.source_types)} source types\n"
            f"Source types: {', '.join(sorted(self.source_types))}\n"
            f"Regions: {', '.join(sorted(self.regions))}\n"
            f"Key topics: {', '.join(top_topics)}\n"
            f"Age: {int(time.time() - self.created_at)}s\n"
            f"\nRecent signals:\n{headlines}"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "convergence_score": round(self.convergence_score, 3),
            "impact_score": round(self.impact_score, 3),
            "signal_count": len(self.signals),
            "source_types": sorted(self.source_types),
            "regions": sorted(self.regions),
            "top_topics": sorted(self.topics)[:20],
            "headlines": [
                s.headline for s in
                sorted(self.signals, key=lambda s: s.timestamp, reverse=True)[:8]
                if s.headline
            ],
            "created_at": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "last_signal_at": datetime.fromtimestamp(self.last_signal_at, tz=timezone.utc).isoformat(),
            "fired": self.fired,
            "fire_count": self.fire_count,
        }


class PatternAccumulator:
    """Event-driven pattern accumulator.

    Absorbs every data signal, clusters them by topic similarity,
    and fires notifications when convergence crosses the threshold.
    No timers. The data decides when to talk.
    """

    def __init__(self, proactive_engine: "ProactiveEngine"):
        self.engine = proactive_engine
        self._patterns: list[EmergentPattern] = []
        self._total_signals = 0
        self._total_patterns_created = 0
        self._total_fires = 0
        self._total_impact_suppressed = 0

    # ── Impact Scoring ──────────────────────────────────────────────────

    def _estimate_impact_score(self, pattern: EmergentPattern) -> float:
        """Estimate geopolitical/economic impact of a pattern.

        Scans pattern headlines against scope, entity, breaking-news, and
        economic indicators. Returns 0.0-1.0.

        Scoring hierarchy:
          Global scope          → base 0.90
          Global figure          → base 0.85
          Continental scope      → base 0.75
          Major power country    → base 0.70
          Unknown/minor scope    → base 0.25

        Additive bonuses:
          Breaking news headline → +0.15
          Economic crisis terms  → +0.10
          Source diversity ≥ 3   → +0.05
        """
        # Build searchable text from all headlines in the pattern
        headlines_text = " ".join(
            s.headline.lower() for s in pattern.signals
        )

        score = 0.25  # base: any pattern that reaches convergence

        # ── Scope detection (highest wins via max) ──
        if any(term in headlines_text for term in _GLOBAL_SCOPE):
            score = max(score, 0.90)
        if any(term in headlines_text for term in _CONTINENTAL_SCOPE):
            score = max(score, 0.75)
        if any(term in headlines_text for term in _MAJOR_POWERS):
            score = max(score, 0.70)

        # ── Entity importance ──
        if any(fig in headlines_text for fig in _GLOBAL_FIGURES):
            score = max(score, 0.85)

        # ── Breaking news boost ──
        if any(ind in headlines_text for ind in _BREAKING_INDICATORS):
            score = min(1.0, score + 0.15)

        # ── Economic crisis boost ──
        if any(ind in headlines_text for ind in _ECONOMIC_CRISIS):
            score = min(1.0, score + 0.10)

        # ── Natural disaster boost ──
        if any(ind in headlines_text for ind in _NATURAL_DISASTERS):
            score = min(1.0, score + 0.10)

        # ── Source diversity bonus ──
        if len(pattern.source_types) >= 3:
            score = min(1.0, score + 0.05)

        # ── Financial signal corroboration ──
        # If a financial_anomaly signal appears in the same pattern as text signals
        # it means the markets are REACTING to the same event → high confidence
        if "financial_anomaly" in pattern.source_types:
            score = min(1.0, score + 0.15)

        # ── Entity Graph cascade analysis (if available) ──
        # Uses the knowledge graph to assess relationship-based impact
        if self.engine.entity_graph:
            try:
                entities = []
                for s in pattern.signals[:15]:
                    ents = self.engine.entity_graph.extract_entities(s.headline)
                    entities.extend([name for name, _ in ents])
                if entities:
                    cascade = self.engine.entity_graph.get_cascade_impact(list(set(entities)))
                    graph_impact = cascade.get("impact_score", 0.0)
                    # Graph impact can boost score (max +0.20) but never lower it
                    if graph_impact > score:
                        graph_boost = min(0.20, (graph_impact - score) * 0.5)
                        score = min(1.0, score + graph_boost)
            except Exception as e:
                logger.debug("[PatternAccumulator] Graph cascade failed: %s", e)

        return round(score, 3)

    def ingest(
        self,
        source_type: str,
        headline: str,
        region: str = "GLOBAL",
        raw_data: dict | None = None,
    ) -> EmergentPattern | None:
        """Ingest a new signal. Returns the pattern if it fires, else None.

        This is the ONLY entry point. Every data source feeds here.
        """
        self._total_signals += 1
        weight = SIGNAL_WEIGHTS.get(source_type, 0.10)
        topics = _extract_topics(headline)

        if not topics:
            return None

        # ── Entity extraction via Knowledge Graph (if available) ──
        entities: set[str] = set()
        if self.engine.entity_graph:
            try:
                ent_list = self.engine.entity_graph.extract_entities(headline)
                entities = {name for name, _ in ent_list}
                if entities:
                    logger.debug("[PatternAccumulator] NER extracted %d entities: %s from: %.80s",
                                 len(entities), entities, headline)
            except Exception as e:
                logger.debug("[PatternAccumulator] NER extraction error: %s", e)

        # ── Boost weight for Breaking news / Economic headlines ──
        headline_lower = headline.lower()
        if any(ind in headline_lower for ind in _BREAKING_INDICATORS):
            weight = max(weight, 0.50)  # Breaking news = high-priority signal
        elif any(kw in headline_lower for kw in _ECONOMIC_KEYWORDS):
            weight = max(weight, 0.35)  # Economic news = above-average signal

        signal = PatternSignal(
            source_type=source_type,
            headline=headline[:300],
            topics=topics,
            entities=entities,
            region=region,
            weight=weight,
            raw_data=raw_data or {},
        )

        # Find best matching pattern cluster
        best_pattern = None
        best_similarity = 0.0

        for pat in self._patterns:
            if not pat.is_alive():
                continue

            # ── Multi-dimensional similarity ──
            # 1. Topic word overlap (original Jaccard)
            sim = _topic_similarity(topics, pat.topics)

            # 2. Entity overlap — KEY for cross-domain correlation
            #    A VIX spike and "Trump tariffs" share zero words
            #    but both mention Trump/China entities → they’re related
            # Use core_entities (noise-filtered) to prevent garbage matches
            pat_core = pat.core_entities
            if entities and pat_core:
                entity_overlap = len(entities & pat_core)
                if entity_overlap > 0:
                    entity_sim = entity_overlap / max(1, min(len(entities), len(pat_core)))
                    sim = max(sim, entity_sim * 0.8)  # entity match is strong signal
                    sim += entity_overlap * 0.10       # bonus per shared entity

            # 3. Region match
            if region != "GLOBAL" and region in pat.regions:
                sim += 0.10

            # 4. Temporal proximity — signals within 30 min of each other
            #    are more likely to be about the same event
            if pat.signals:
                most_recent = max(s.timestamp for s in pat.signals[-5:])
                temporal_gap = abs(time.time() - most_recent)
                if temporal_gap < 1800:   # within 30 min
                    sim += 0.08
                elif temporal_gap < 3600:  # within 1 hour
                    sim += 0.04

            # 5. Source diversity bonus — different source types corroborating
            #    is a STRONG signal of a real pattern
            if source_type not in pat.source_types and len(pat.source_types) >= 1:
                sim += 0.05  # new source type = corroboration

            if sim > best_similarity:
                best_similarity = sim
                best_pattern = pat

        # Merge into existing pattern or create new one
        if best_pattern and best_similarity >= PATTERN_MERGE_SIMILARITY:
            best_pattern.absorb(signal)
            target_pattern = best_pattern
            logger.info(
                "[PatternAccumulator] Merged signal into pattern (sim=%.2f, signals=%d, "
                "types=%s, entities=%s): %.80s",
                best_similarity, len(target_pattern.signals),
                target_pattern.source_types, sorted(target_pattern.core_entities)[:5],
                headline,
            )
        else:
            target_pattern = EmergentPattern(signal)
            self._patterns.append(target_pattern)
            self._total_patterns_created += 1
            logger.debug("[PatternAccumulator] New pattern #%d created: %.80s (entities=%s)",
                         self._total_patterns_created, headline, entities or 'none')

        # Prune dead patterns
        self._prune()

        # Check if pattern should fire (convergence + signals gate)
        fire_candidate = target_pattern.should_fire()
        refire_candidate = target_pattern.should_re_fire()

        if fire_candidate or refire_candidate:
            # ── Impact gate: only fire if geopolitically significant ──
            impact = self._estimate_impact_score(target_pattern)
            target_pattern.impact_score = impact

            if impact >= IMPACT_THRESHOLD:
                self._fire_pattern(target_pattern, escalation=refire_candidate)
                return target_pattern
            else:
                self._total_impact_suppressed += 1
                logger.info(
                    "[PatternAccumulator] Impact %.2f < %.2f — suppressed: %s (%d signals)",
                    impact, IMPACT_THRESHOLD,
                    sorted(target_pattern.topics)[:5],
                    len(target_pattern.signals),
                )
                # Do NOT mark as fired — keep evaluating as more signals arrive
                # and may push impact above threshold (e.g. a global figure enters the story)

        return None

    def _fire_pattern(self, pattern: EmergentPattern, escalation: bool = False) -> None:
        """Evaluate pattern via LLM and notify if warranted."""
        pattern.fired = True
        pattern.fire_count += 1
        self._total_fires += 1

        prefix = "ESCALATION — " if escalation else ""
        logger.info(
            "[PatternAccumulator] %sFiring pattern %s (convergence=%.2f, signals=%d, types=%s)",
            prefix, pattern.id, pattern.convergence_score,
            len(pattern.signals), ",".join(sorted(pattern.source_types)),
        )

        # Delegate to ProactiveEngine for LLM evaluation + delivery
        self.engine.evaluate_and_notify(
            event_type="emergent_pattern",
            event_data={
                "pattern_id": pattern.id,
                "convergence_score": round(pattern.convergence_score, 3),
                "signal_count": len(pattern.signals),
                "source_types": sorted(pattern.source_types),
                "regions": sorted(pattern.regions),
                "top_topics": sorted(pattern.topics)[:15],
                "escalation": escalation,
                "headlines": [
                    s.headline for s in
                    sorted(pattern.signals, key=lambda s: s.timestamp, reverse=True)[:8]
                ],
            },
            context=pattern.summary_text(),
        )

    def _prune(self) -> None:
        """Remove dead patterns and enforce size limit."""
        now = time.time()
        self._patterns = [p for p in self._patterns if p.is_alive(now)]
        # If still too many, drop lowest convergence
        if len(self._patterns) > MAX_PATTERNS:
            self._patterns.sort(key=lambda p: p.convergence_score, reverse=True)
            self._patterns = self._patterns[:MAX_PATTERNS]

    def get_active_patterns(self) -> list[dict]:
        """Return all active patterns for monitoring."""
        now = time.time()
        return [
            p.to_dict() for p in self._patterns
            if p.is_alive(now)
        ]

    def get_hot_patterns(self, min_convergence: float = 0.30) -> list[dict]:
        """Return patterns approaching the threshold."""
        now = time.time()
        return [
            p.to_dict() for p in self._patterns
            if p.is_alive(now) and p.convergence_score >= min_convergence
        ]

    def get_stats(self) -> dict:
        now = time.time()
        alive = [p for p in self._patterns if p.is_alive(now)]
        return {
            "total_signals_ingested": self._total_signals,
            "total_patterns_created": self._total_patterns_created,
            "total_fires": self._total_fires,
            "active_patterns": len(alive),
            "hot_patterns": sum(1 for p in alive if p.convergence_score >= 0.30),
            "ready_to_fire": sum(1 for p in alive if p.should_fire()),
        }

# ── Decision prompt: should we bother the user? ──
IMPORTANCE_CLASSIFIER_PROMPT = """You are the INITIATIVE FILTER for an autonomous intelligence system called Αίολος.
Current date and time: {current_datetime}

Your job: decide whether a finding is important enough to INTERRUPT the user (Πάνος).

The user is a busy professional. He trusts the system to work autonomously.
He does NOT want noise. He DOES want to know about:
- Geopolitical developments that change the strategic picture
- Confirmed or disconfirmed predictions (prophecies grounding in reality)
- Surprising discoveries that contradict current assumptions
- Emerging patterns that require immediate attention or decision

You must output ONLY valid JSON:
{{
  "should_notify": true/false,
  "urgency": "critical" | "important" | "digest",
  "reason": "One sentence explaining WHY this warrants attention",
  "headline": "Short notification title (≤80 chars)",
  "summary": "2-3 sentence briefing for the user"
}}

Rules:
- If the finding is routine, expected, or low-impact → should_notify: false
- "critical" = the user needs to see this NOW (strategic shift, confirmed prophecy, danger)
- "important" = the user should see this within an hour (significant insight, pattern)
- "digest" = include in daily summary (interesting but not urgent)
- Be SELECTIVE. The user suffers alert fatigue if you notify too often.
  Reserve "critical" for genuine emergencies. Most findings are "important" or "digest".
  Repeated keyword spikes on common terms (iran, trump, military, ceasefire, ukraine) are
  usually "digest" unless the CONTENT reveals something genuinely new or surprising.
- NEVER fabricate urgency. Be honest about whether this changes the strategic picture.
- Check dates carefully: if data references events older than 48 hours, it is NOT urgent.
- Write in Greek when the content is about Greek affairs, otherwise English.
"""

# ── Research query generation prompt ──
RESEARCH_QUERY_PROMPT = """You are an intelligence research assistant for an autonomous system called Αίολος.
Current date and time: {current_datetime}

A pattern of events has been detected that warrants investigation. Your job:
Generate 2-3 focused web search queries that will find the SPECIFIC FACTS needed
to understand what is happening RIGHT NOW.

Rules:
- Queries must target CURRENT events (last 24-48 hours)
- Include the current year/month in queries to get recent results
- Be specific: include names, countries, organizations involved
- One query per information gap identified
- Prefer English queries for international events, Greek for Greek affairs
- Never generate more than 3 queries (API cost control)
- Focus on WHAT HAPPENED, not analysis or opinion

Output ONLY valid JSON:
{{
  "queries": [
    {{"query": "the actual search query", "goal": "what we expect to find"}}
  ],
  "research_rationale": "One sentence: why auto-research is needed here"
}}
"""

# ── Research synthesis prompt ──
RESEARCH_SYNTHESIS_PROMPT = """You are Αίολος, an autonomous intelligence system.
Current date and time: {current_datetime}

You detected an important pattern and autonomously researched it.
Now synthesize the research findings into a BRIEF, ACTIONABLE intelligence note.

Original alert: {headline}
Research findings are provided below.

Rules:
- Lead with what you FOUND, not what you searched for
- Be specific: names, numbers, dates, locations
- Always include the YEAR when referencing dates (e.g., "April 2026", not just "April")
- If research confirms the alert, say so with evidence
- If research reveals the alert was noise/outdated, say so honestly
- Max 5-7 sentences
- NEVER end with "Είστε έτοιμος να ξεκινήσω ανάλυση;" or similar escalation rhetoric.
  This is an intelligence note, not a sales pitch. State the facts and stop.
- NEVER suggest triggering the full pipeline — that is the user's decision.
- If the topic is Greek affairs, write in Greek. Otherwise English.
- End with one line: "Sources: [list domains]"
"""

# ── Message composition prompt ──
MESSAGE_COMPOSER_PROMPT = """You are Αίολος, an autonomous intelligence system.
Current date and time: {current_datetime}

You are reaching out to Πάνος PROACTIVELY — he did not ask you.
This means your message must be:
1. Immediately useful — lead with the insight, not the context
2. Respectful of his time — be concise (3-5 sentences max)
3. Actionable — tell him what changed and what it means
4. Honest about confidence — if uncertain, say so

Write the message as if you're a trusted advisor sending a brief note.
Use the tone of your character (direct, analytical, no hedging).
If the topic is Greek affairs, write in Greek. Otherwise English.

CRITICAL RULES:
- NEVER end with "Είστε έτοιμος να ξεκινήσω ανάλυση;", "Η κατάσταση δεν αντέχει άλλη
  καθυστέρηση", or any other escalation/urgency rhetoric. State the facts and stop.
- NEVER suggest triggering the full pipeline — that is the user's decision.
- NEVER repeat the same framing as previous alerts. Each note must add NEW information.
- Always include the YEAR when referencing dates.

Format: Start with the headline, then the briefing. No greetings, no signatures.
"""


class Notification:
    """A single proactive notification."""

    def __init__(
        self,
        headline: str,
        summary: str,
        urgency: str,
        source: str,  # perception, curiosity, prophecy, evolution
        reason: str = "",
        raw_data: dict | None = None,
    ):
        self.id = f"n_{int(time.time() * 1000)}"
        self.headline = headline
        self.summary = summary
        self.urgency = urgency
        self.source = source
        self.reason = reason
        self.raw_data = raw_data or {}
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.delivered_sse = False
        self.delivered_telegram = False
        self.read = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "headline": self.headline,
            "summary": self.summary,
            "urgency": self.urgency,
            "source": self.source,
            "reason": self.reason,
            "created_at": self.created_at,
            "delivered_sse": self.delivered_sse,
            "delivered_telegram": self.delivered_telegram,
            "read": self.read,
        }


class ProactiveEngine:
    """Core proactive communication engine.

    Receives events from background hooks, evaluates importance via LLM,
    composes messages, and delivers through available channels.
    """

    def __init__(
        self,
        llm: LLMClient,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        log_path: Path | None = None,
        web_agent: Any | None = None,
        perception_db: Any | None = None,
    ):
        self.llm = llm
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.log_path = log_path or Path("proactive_log.jsonl")
        self.web_agent = web_agent          # WebAgent instance for auto-research
        self.perception_db = perception_db  # PerceptionDB to store research findings
        self.entity_graph = None            # EntityGraph — set by api.py after init
        self.market_collector = None         # MarketDataCollector — set by api.py after init

        # Notification storage
        self._notifications: deque[Notification] = deque(maxlen=MAX_NOTIFICATIONS)

        # SSE subscribers (asyncio.Queue per connected client)
        self._sse_subscribers: list[asyncio.Queue] = []

        # Pattern Accumulator — event-driven pattern detection
        self.accumulator = PatternAccumulator(self)

        # Stats
        self._total_evaluated = 0
        self._total_notified = 0
        self._total_suppressed = 0
        self._total_auto_researched = 0

        # Pipeline awareness — set by core.py when pipeline is running.
        # When True, evaluate_and_notify() buffers patterns instead of
        # spending LLM tokens on evaluation, and replays them after pipeline.
        self.pipeline_running = False
        self._buffered_evaluations: list[tuple[str, dict, str]] = []

        # Load existing log
        self._load_log()

    # ══════════════════════════════════════════════════════════════
    #  PUBLIC API — signal ingestion (event-driven, not timer-based)
    # ══════════════════════════════════════════════════════════════

    def feed_signal(
        self,
        source_type: str,
        headline: str,
        region: str = "GLOBAL",
        raw_data: dict | None = None,
    ) -> EmergentPattern | None:
        """Feed a data signal into the pattern accumulator.

        This is the PRIMARY entry point. Every data source should call this.
        The accumulator clusters signals, and when convergence ≥ 0.50,
        it fires evaluate_and_notify() automatically.

        Returns the EmergentPattern if it fired, else None.
        """
        return self.accumulator.ingest(
            source_type=source_type,
            headline=headline,
            region=region,
            raw_data=raw_data,
        )

    def replay_buffered_evaluations(self) -> int:
        """Replay evaluations that were buffered during pipeline execution.

        Called by core.py after pipeline completes. Returns count of replayed items.
        """
        buffered = list(self._buffered_evaluations)
        self._buffered_evaluations.clear()
        if not buffered:
            return 0

        logger.info("[Proactive] Replaying %d buffered evaluations (pipeline finished)", len(buffered))
        count = 0
        for event_type, event_data, context in buffered:
            try:
                result = self.evaluate_and_notify(event_type, event_data, context)
                if result:
                    count += 1
            except Exception as exc:
                logger.warning("[Proactive] Buffered replay failed: %s", exc)
        logger.info("[Proactive] Replayed %d/%d buffered evaluations → %d notifications",
                     len(buffered), len(buffered), count)
        return count

    # ══════════════════════════════════════════════════════════════
    #  LLM EVALUATION — called by PatternAccumulator when pattern fires
    # ══════════════════════════════════════════════════════════════

    def evaluate_and_notify(
        self,
        event_type: str,
        event_data: dict,
        context: str = "",
    ) -> Notification | None:
        """Evaluate an event and notify the user if warranted.

        Args:
            event_type: Source hook (perception_alert, curiosity_finding,
                       prophecy_resolved, self_evolution_proposal)
            event_data: Raw event data
            context: Additional context string for the LLM

        Returns:
            Notification if sent, None if suppressed.
        """
        # ── Pipeline guard: buffer evaluations instead of spending LLM tokens ──
        if self.pipeline_running:
            self._buffered_evaluations.append((event_type, event_data, context))
            logger.debug("[Proactive] Buffered evaluation (pipeline running): %s",
                         event_data.get("headlines", ["?"])[0][:60] if event_data.get("headlines") else "?")
            return None

        self._total_evaluated += 1

        # ── Headline dedup: skip if very similar to a recent notification ──
        candidate_headline = ""
        headlines_in_data = event_data.get("headlines", [])
        if headlines_in_data:
            candidate_headline = headlines_in_data[0] if isinstance(headlines_in_data, list) else str(headlines_in_data)
        candidate_topics = _extract_topics(
            candidate_headline or json.dumps(event_data, ensure_ascii=False)[:500]
        )
        for existing in list(self._notifications)[-20:]:
            existing_topics = _extract_topics(existing.headline + " " + existing.summary[:200])
            if _topic_similarity(candidate_topics, existing_topics) >= 0.55:
                self._total_suppressed += 1
                logger.info("[Proactive] DEDUP suppressed — too similar to recent '%s'",
                            existing.headline[:60])
                return None

        # Build evaluation context
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        eval_context = f"EVENT TYPE: {event_type}\n\nDATA:\n{json.dumps(event_data, ensure_ascii=False, indent=2)[:3000]}"
        if context:
            eval_context += f"\n\nADDITIONAL CONTEXT:\n{context[:2000]}"

        # LLM decision: should we notify?
        try:
            prompt = IMPORTANCE_CLASSIFIER_PROMPT.format(current_datetime=now_str)
            decision = self.llm.call_json(
                prompt,
                eval_context,
                max_tokens=500,
                temperature=0.2,
            )
        except Exception as exc:
            logger.warning("[Proactive] LLM classification failed: %s", exc)
            return None

        should_notify = decision.get("should_notify", False)
        if not should_notify:
            self._total_suppressed += 1
            logger.debug("[Proactive] Suppressed %s event (reason: %s)",
                         event_type, decision.get("reason", "not important"))
            return None

        urgency = decision.get("urgency", IMPORTANT)
        if urgency not in (CRITICAL, IMPORTANT, DIGEST):
            urgency = IMPORTANT

        headline = decision.get("headline", "New finding")[:100]
        summary = decision.get("summary", "")
        reason = decision.get("reason", "")

        # ── AUTO-RESEARCH: if we have WebAgent, investigate before notifying ──
        research_findings = ""
        if self.web_agent:  # Always research before notifying — be confident
            research_findings = self._run_auto_research(
                headline=headline,
                event_type=event_type,
                event_data=event_data,
                context=context,
            )

        # Compose summary — with research findings if available
        if research_findings:
            summary = research_findings  # Research synthesis replaces raw LLM summary
        elif not summary or len(summary) < 20:
            summary = self._compose_message(headline, event_type, event_data)

        notification = Notification(
            headline=headline,
            summary=summary,
            urgency=urgency,
            source=event_type,
            reason=reason,
            raw_data=event_data,
        )

        self._notifications.append(notification)
        self._total_notified += 1
        self._log_notification(notification)

        # All evaluated alerts get full delivery — the LLM already decided
        # should_notify=true. Urgency controls Telegram only.
        self._deliver_immediate(notification)

        return notification

    def get_pending_digest(self) -> list[dict]:
        """Get all unread digest-level notifications for daily summary."""
        digests = [
            n.to_dict() for n in self._notifications
            if n.urgency == DIGEST and not n.read
        ]
        return digests

    def mark_read(self, notification_id: str) -> bool:
        """Mark a notification as read."""
        for n in self._notifications:
            if n.id == notification_id:
                n.read = True
                return True
        return False

    def mark_all_read(self) -> int:
        """Mark all notifications as read. Returns count."""
        count = 0
        for n in self._notifications:
            if not n.read:
                n.read = True
                count += 1
        return count

    def get_recent(self, limit: int = 50) -> list[dict]:
        """Get recent notifications (newest first)."""
        items = list(self._notifications)
        items.reverse()
        return [n.to_dict() for n in items[:limit]]

    def get_unread_count(self) -> int:
        """Count unread notifications."""
        return sum(1 for n in self._notifications if not n.read)

    def get_stats(self) -> dict:
        """Return proactive engine stats."""
        return {
            "total_evaluated": self._total_evaluated,
            "total_notified": self._total_notified,
            "total_suppressed": self._total_suppressed,
            "total_auto_researched": self._total_auto_researched,
            "unread_count": self.get_unread_count(),
            "sse_subscribers": len(self._sse_subscribers),
            "telegram_enabled": bool(self.telegram_bot_token and self.telegram_chat_id),
            "accumulator": self.accumulator.get_stats(),
        }

    def get_recent_context_for_chat(self, max_items: int = 10) -> str:
        """Return recent proactive notifications formatted as chat context.

        This allows the chat system to know what Αίολος has
        proactively communicated, so the user can reference
        or reply to any notification naturally.
        """
        recent = [n for n in self._notifications if not n.read][:max_items]
        if not recent:
            # Fall back to last few notifications even if read
            recent = list(self._notifications)[:max_items]

        if not recent:
            return ""

        lines = ["YOUR RECENT PROACTIVE MESSAGES (notifications you sent to the user):"]
        for i, n in enumerate(recent, 1):
            status = "UNREAD" if not n.read else "read"
            lines.append(
                f"  [{i}] ({status}, {n.urgency}) [{n.created_at[:16]}] "
                f"{n.headline}\n      {n.summary}"
            )

        lines.append(
            "\nIf the user's message references a notification above, "
            "respond in that context. They may say 'ναι', 'σχετικά με αυτό', "
            "'πες μου περισσότερα', etc. — match their reply to the relevant notification."
        )
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    #  SSE SUBSCRIPTION (for in-app real-time push)
    # ══════════════════════════════════════════════════════════════

    def subscribe_sse(self) -> asyncio.Queue:
        """Register a new SSE subscriber. Returns a queue to read from."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._sse_subscribers.append(q)
        logger.info("[Proactive] SSE subscriber added (total: %d)", len(self._sse_subscribers))
        return q

    def unsubscribe_sse(self, q: asyncio.Queue) -> None:
        """Remove an SSE subscriber."""
        if q in self._sse_subscribers:
            self._sse_subscribers.remove(q)
            logger.info("[Proactive] SSE subscriber removed (total: %d)", len(self._sse_subscribers))

    def _push_to_sse(self, notification: Notification) -> None:
        """Push notification to all connected SSE clients."""
        data = notification.to_dict()
        dead_queues = []
        for q in self._sse_subscribers:
            try:
                q.put_nowait(data)
                notification.delivered_sse = True
            except asyncio.QueueFull:
                dead_queues.append(q)
        # Clean up dead subscribers
        for q in dead_queues:
            self._sse_subscribers.remove(q)

    # ══════════════════════════════════════════════════════════════
    #  TELEGRAM DELIVERY
    # ══════════════════════════════════════════════════════════════

    def _send_telegram(self, notification: Notification) -> bool:
        """Send notification via Telegram Bot API (sync, uses httpx)."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return False

        urgency_emoji = {"critical": "\U0001F6A8", "important": "\U0001F4CC", "digest": "\U0001F4CB"}.get(
            notification.urgency, "\U0001F4AC"
        )

        text = (
            f"{urgency_emoji} *{notification.headline}*\n\n"
            f"{notification.summary}\n\n"
            f"_{notification.source} · {notification.created_at[:16]}_"
        )

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    notification.delivered_telegram = True
                    logger.info("[Proactive] Telegram sent: %s", notification.headline)
                    return True
                else:
                    logger.warning("[Proactive] Telegram failed (%d): %s",
                                   resp.status_code, resp.text[:200])
                    return False
        except Exception as exc:
            logger.warning("[Proactive] Telegram error: %s", exc)
            return False

    # ══════════════════════════════════════════════════════════════
    #  DELIVERY LOGIC
    # ══════════════════════════════════════════════════════════════

    def _deliver_immediate(self, notification: Notification) -> None:
        """Deliver a notification via SSE (with conversation_start) + Telegram.

        All notifications that pass LLM evaluation get full delivery.
        Urgency controls Telegram only (critical/important → phone buzz).
        """
        logger.info("[Proactive] %s: %s — %s",
                     notification.urgency.upper(), notification.headline, notification.reason)

        # Push to SSE with conversation_start flag
        data = notification.to_dict()
        data["conversation_start"] = True  # Tell UI to open chat with this message
        dead_queues = []
        for q in self._sse_subscribers:
            try:
                q.put_nowait(data)
                notification.delivered_sse = True
            except asyncio.QueueFull:
                dead_queues.append(q)
        for q in dead_queues:
            self._sse_subscribers.remove(q)

        # Telegram for critical / important (digest = no phone buzz)
        if notification.urgency in (CRITICAL, IMPORTANT):
            self._send_telegram(notification)

    # ══════════════════════════════════════════════════════════════
    #  AUTO-RESEARCH — WebAgent-powered investigation
    # ══════════════════════════════════════════════════════════════

    def _run_auto_research(
        self,
        headline: str,
        event_type: str,
        event_data: dict,
        context: str = "",
    ) -> str:
        """Autonomously research a pattern before notifying the user.

        1. Ask LLM to generate search queries from the pattern data
        2. Execute web searches via WebAgent
        3. Synthesize findings into an intelligence note
        4. Store raw results in PerceptionDB

        Returns:
            Synthesized research text (replaces raw notification summary),
            or empty string if research failed/unavailable.
        """
        if not self.web_agent:
            return ""

        start = time.time()
        logger.info("[Proactive/Research] Starting auto-research for: %s", headline[:80])

        # Step 1: Generate search queries from pattern data
        queries = self._generate_research_queries(headline, event_type, event_data, context)
        if not queries:
            logger.info("[Proactive/Research] No queries generated — skipping research")
            return ""

        # Step 2: Run web searches (need asyncio event loop)
        all_results = []
        loop = None
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're called from a sync context inside an async app
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self._search_sync_bridge, queries)
                    all_results = future.result(timeout=60)
            else:
                all_results = loop.run_until_complete(self._search_async(queries))
        except RuntimeError:
            # No event loop — create one
            all_results = asyncio.run(self._search_async(queries))
        except Exception as exc:
            logger.warning("[Proactive/Research] Search execution failed: %s", exc)
            return ""

        if not all_results:
            logger.info("[Proactive/Research] No search results found")
            return ""

        # Step 3: Store raw results in perception DB
        stored = self._store_research_results(headline, queries, all_results)

        # Step 4: Synthesize findings via LLM
        synthesis = self._synthesize_research(headline, all_results)

        elapsed = round(time.time() - start, 1)
        self._total_auto_researched += 1
        logger.info(
            "[Proactive/Research] Complete — %d queries, %d results, %d stored, %.1fs",
            len(queries), sum(len(r.get("results", [])) for r in all_results),
            stored, elapsed,
        )

        return synthesis

    def _generate_research_queries(
        self,
        headline: str,
        event_type: str,
        event_data: dict,
        context: str,
    ) -> list[dict]:
        """Ask LLM to generate focused search queries for auto-research."""
        query_context = (
            f"ALERT HEADLINE: {headline}\n"
            f"EVENT TYPE: {event_type}\n"
            f"KEY DATA:\n{json.dumps(event_data, ensure_ascii=False, indent=2)[:2000]}\n"
        )
        if context:
            query_context += f"\nPATTERN CONTEXT:\n{context[:1500]}"

        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            result = self.llm.call_json(
                RESEARCH_QUERY_PROMPT.format(current_datetime=now_str),
                query_context,
                max_tokens=400,
                temperature=0.2,
            )
            queries = result.get("queries", [])
            rationale = result.get("research_rationale", "")
            if rationale:
                logger.info("[Proactive/Research] Rationale: %s", rationale[:120])

            # Validate and cap at 3 queries
            valid_queries = []
            for q in queries[:3]:
                if isinstance(q, dict) and q.get("query"):
                    valid_queries.append(q)
                elif isinstance(q, str):
                    valid_queries.append({"query": q, "goal": ""})
            return valid_queries

        except Exception as exc:
            logger.warning("[Proactive/Research] Query generation failed: %s", exc)
            return []

    def _search_sync_bridge(self, queries: list[dict]) -> list[dict]:
        """Bridge to run async searches from a sync context (new event loop in thread)."""
        return asyncio.run(self._search_async(queries))

    async def _search_async(self, queries: list[dict]) -> list[dict]:
        """Execute web searches asynchronously."""
        results = []
        for q in queries:
            query_text = q.get("query", "") if isinstance(q, dict) else str(q)
            if not query_text:
                continue
            try:
                result = await self.web_agent.web_search(query_text, max_results=5)
                result["goal"] = q.get("goal", "") if isinstance(q, dict) else ""
                results.append(result)
            except Exception as exc:
                logger.warning("[Proactive/Research] Search failed for '%s': %s",
                               query_text[:60], exc)
        return results

    def _store_research_results(
        self,
        headline: str,
        queries: list[dict],
        search_results: list[dict],
    ) -> int:
        """Store auto-research results in PerceptionDB for future reference."""
        if not self.perception_db:
            return 0

        import hashlib

        stored = 0
        timestamp = datetime.now(timezone.utc).isoformat()

        for sr in search_results:
            search_query = sr.get("query", "")
            for item in sr.get("results", [])[:5]:
                title = (item.get("title") or "")[:300]
                url = item.get("url", "")
                snippet = (item.get("snippet") or "")[:500]
                if not title:
                    continue
                # Deduplicate via event_hash
                raw = f"{url}|{title}".encode()
                ev_hash = hashlib.sha256(raw).hexdigest()[:32]
                try:
                    self.perception_db.store_event(
                        source_name="proactive_auto_research",
                        source_tier=2,
                        source_region="GLOBAL",
                        headline=title,
                        summary=f"[Auto-research for: {headline[:100]}] {snippet}",
                        content_type="FACT",
                        domain="MULTI",
                        salience_score=0.70,
                        event_hash=ev_hash,
                        source_url=url,
                        published_at=timestamp,
                        raw_payload={
                            "proactive_trigger": headline[:200],
                            "search_query": search_query,
                            "snippet": snippet,
                        },
                    )
                    stored += 1
                except Exception as exc:
                    logger.debug("[Proactive/Research] DB store failed: %s", exc)

        if stored > 0:
            logger.info("[Proactive/Research] Stored %d research findings in PerceptionDB", stored)
        return stored

    def _synthesize_research(self, headline: str, search_results: list[dict]) -> str:
        """Synthesize web search results into an intelligence note."""
        # Build findings text from all search results
        findings_parts = []
        sources = set()
        for sr in search_results:
            query = sr.get("query", "unknown query")
            goal = sr.get("goal", "")
            findings_parts.append(f"\n--- Search: \"{query}\" (goal: {goal}) ---")
            for item in sr.get("results", [])[:5]:
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                url = item.get("url", "")
                if url:
                    try:
                        from urllib.parse import urlparse
                        sources.add(urlparse(url).netloc)
                    except Exception:
                        pass
                findings_parts.append(f"  [{title}]: {snippet}")

        findings_text = "\n".join(findings_parts)
        if not findings_text.strip():
            return ""

        # Truncate for LLM context
        findings_text = findings_text[:4000]

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        prompt = RESEARCH_SYNTHESIS_PROMPT.format(headline=headline, current_datetime=now_str)
        user_msg = f"RESEARCH FINDINGS:\n{findings_text}"

        try:
            synthesis = self.llm.call(
                prompt,
                user_msg,
                max_tokens=500,
                temperature=0.3,
            )
            return synthesis
        except Exception as exc:
            logger.warning("[Proactive/Research] Synthesis failed: %s", exc)
            # Fallback: return raw findings summary
            return f"Auto-research for: {headline}\n" + findings_text[:800]

    # ══════════════════════════════════════════════════════════════
    #  MESSAGE COMPOSITION
    # ══════════════════════════════════════════════════════════════

    def _compose_message(self, headline: str, event_type: str, event_data: dict) -> str:
        """Use LLM to compose a brief advisory message."""
        user_msg = (
            f"HEADLINE: {headline}\n"
            f"SOURCE: {event_type}\n"
            f"DATA:\n{json.dumps(event_data, ensure_ascii=False, indent=2)[:2000]}\n\n"
            "Write the proactive message (3-5 sentences)."
        )
        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            return self.llm.call(
                MESSAGE_COMPOSER_PROMPT.format(current_datetime=now_str),
                user_msg,
                max_tokens=300,
                temperature=0.4,
            )
        except Exception as exc:
            logger.warning("[Proactive] Message composition failed: %s", exc)
            return headline

    # ══════════════════════════════════════════════════════════════
    #  PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def _log_notification(self, notification: Notification) -> None:
        """Append notification to persistent JSONL log."""
        entry = {
            "type": "notification",
            "timestamp": notification.created_at,
            **notification.to_dict(),
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("[Proactive] Log write failed: %s", exc)

    def _load_log(self) -> None:
        """Load recent notifications from persistent log."""
        if not self.log_path.exists():
            return
        try:
            lines = self.log_path.read_text(encoding="utf-8").strip().split("\n")
            # Load last N entries
            for line in lines[-MAX_NOTIFICATIONS:]:
                if not line.strip():
                    continue
                entry = json.loads(line)
                n = Notification(
                    headline=entry.get("headline", ""),
                    summary=entry.get("summary", ""),
                    urgency=entry.get("urgency", DIGEST),
                    source=entry.get("source", "unknown"),
                    reason=entry.get("reason", ""),
                )
                n.id = entry.get("id", n.id)
                n.created_at = entry.get("created_at", n.created_at)
                n.delivered_sse = entry.get("delivered_sse", False)
                n.delivered_telegram = entry.get("delivered_telegram", False)
                n.read = entry.get("read", False)
                self._notifications.append(n)
            logger.info("[Proactive] Loaded %d notifications from log", len(self._notifications))
        except Exception as exc:
            logger.warning("[Proactive] Failed to load log: %s", exc)


class ProactiveDigestLoop:
    """Background loop that sends a daily digest of accumulated findings.

    Runs once per day, collects all digest-level notifications,
    composes a summary, and delivers it.
    """

    def __init__(
        self,
        engine: ProactiveEngine,
        llm: LLMClient,
        interval_hours: int = 24,
    ):
        self.engine = engine
        self.llm = llm
        self.interval = interval_hours * 3600
        self._running = False

    async def run_forever(self):
        """Main loop — call as asyncio.create_task(loop.run_forever())."""
        self._running = True
        logger.info("[ProactiveDigest] Daily digest loop started (interval=%dh)", self.interval // 3600)

        # Initial delay: let the system accumulate data (6 hours after boot)
        await asyncio.sleep(6 * 3600)

        while self._running:
            try:
                await self._run_digest()
            except asyncio.CancelledError:
                logger.info("[ProactiveDigest] Loop cancelled")
                break
            except Exception as exc:
                logger.warning("[ProactiveDigest] Digest error: %s", exc)

            await asyncio.sleep(self.interval)

    async def _run_digest(self):
        """Compose and send daily digest."""
        digests = self.engine.get_pending_digest()
        if not digests:
            logger.info("[ProactiveDigest] No digest items — skipping")
            return

        loop = asyncio.get_event_loop()

        # Include pattern accumulator status in digest
        acc_stats = self.engine.accumulator.get_stats()
        hot_patterns = self.engine.accumulator.get_hot_patterns(min_convergence=0.25)

        # Compose digest summary
        items_text = "\n".join(
            f"- [{d['source']}] {d['headline']}: {d['summary'][:200]}"
            for d in digests[:20]
        )

        patterns_text = ""
        if hot_patterns:
            patterns_text = "\n\nACTIVE PATTERNS (not yet fired but building):\n" + "\n".join(
                f"- convergence={p['convergence_score']:.2f}, signals={p['signal_count']}, "
                f"topics={', '.join(p['top_topics'][:5])}"
                for p in hot_patterns[:5]
            )

        summary = await loop.run_in_executor(None, lambda: self.llm.call(
            (
                "You are Αίολος. Compose a brief DAILY DIGEST for Πάνος. "
                "Summarize the key findings from the past cycle. "
                "Group by theme. Be concise — max 10 sentences. "
                "If nothing significant happened, say so honestly."
            ),
            f"ACCUMULATED FINDINGS ({len(digests)} items):\n{items_text}{patterns_text}",
            max_tokens=600,
            temperature=0.3,
        ))

        # Create a digest notification
        digest_notification = Notification(
            headline=f"Daily Intelligence Digest — {len(digests)} findings",
            summary=summary,
            urgency=IMPORTANT,  # Upgrade digest to important for delivery
            source="daily_digest",
        )

        self.engine._notifications.append(digest_notification)
        self.engine._deliver_immediate(digest_notification)

        # Mark digest items as read
        for d in digests:
            self.engine.mark_read(d["id"])

        logger.info("[ProactiveDigest] Sent digest with %d items", len(digests))
