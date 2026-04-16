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
from zoneinfo import ZoneInfo

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
    "economic_shift": 0.35,          # Economic indicator change (FRED, ECB, calendar)
    "infrastructure_cascade": 0.35,  # Infrastructure dependency triggered
    "financial_anomaly": 0.45,       # Market anomaly (VIX spike, crash, etc.)
}

# ── Decay: signal weight decays over time (half-life in seconds) ──
SIGNAL_HALF_LIFE = 14400  # 4 hours — signal loses half its weight in 4h

# ══════════════════════════════════════════════════════════════════════════════
#  IMPACT SCORING — determines if a pattern is strategically significant
#  enough to warrant notification. Assesses ALL domains equally:
#  geopolitical, economic, market, social, technology.
#  Cross-domain patterns (2+ domains) get a BONUS — that's where unique
#  insights live.
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
    # Cross-domain bridge terms (geo+econ coupling)
    "economic sanctions", "trade deficit", "debt crisis",
    "energy prices", "supply chain", "export ban", "import",
    "foreign investment", "capital flight", "sovereign debt",
    "credit rating", "downgrade", "austerity", "fiscal",
    "monetary policy", "rate decision", "basis points",
    "economic growth", "economic contraction", "stagflation",
    "dollar", "yuan", "euro ", "yen ", "ruble",
    "brent", "crude", "natural gas", "lng",
    "food prices", "wheat", "grain", "fertilizer",
    "supply disruption", "shipping", "freight",
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

# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-DOMAIN SIGNAL FUSION ENGINE (CDSFE)
#
#  The unique value of Aiolos is NOT single-domain analysis — it's the
#  COMBINATION of domains. A yield curve inversion alone is Bloomberg.
#  An ACLED spike alone is a think tank. But yield curve inversion +
#  ACLED spike + consumer sentiment drop + Hormuz chokepoint pressure
#  = a unique conclusion that nobody else can make.
#
#  5 domains, treated equally:
#    GEOPOLITICAL — conflict, diplomacy, alliances, power shifts
#    ECONOMIC     — macro indicators, monetary policy, trade, debt
#    MARKET       — asset prices, sentiment, flows, anomalies
#    SOCIAL       — protests, unrest, migration, humanitarian, public mood
#    TECHNOLOGY   — AI, cyber, infrastructure, energy transition, chips
#
#  Scoring:
#    1 domain   = routine observation (no bonus)
#    2 domains  = cross-domain correlation (+0.12)
#    3+ domains = high-value multi-domain insight (+0.20)
# ══════════════════════════════════════════════════════════════════════════════

# Domain classification keywords — used to tag each signal/pattern
_DOMAIN_KEYWORDS: dict[str, frozenset[str]] = {
    "GEOPOLITICAL": frozenset({
        "war", "invasion", "military", "troops", "missile", "airstrike",
        "ceasefire", "peace treaty", "nato", "coup", "assassination",
        "diplomatic", "embassy", "alliance", "territorial", "border",
        "occupation", "blockade", "proxy war", "arms deal", "nuclear",
        "sanction", "sanctions", "espionage", "intelligence",
        "conflict", "escalation", "de-escalation", "negotiations",
    }),
    "ECONOMIC": frozenset({
        "gdp", "inflation", "deflation", "recession", "rate cut", "rate hike",
        "central bank", "fed ", "ecb", "monetary policy", "fiscal",
        "trade deficit", "trade war", "tariff", "export", "import",
        "debt ceiling", "sovereign debt", "bond yield", "treasury",
        "quantitative", "stimulus", "austerity", "unemployment",
        "economic growth", "economic contraction", "cpi", "ppi",
        "budget", "deficit", "surplus", "credit rating", "downgrade",
        "interest rate", "basis points", "rate decision",
        "bailout", "default", "restructuring",
    }),
    "MARKET": frozenset({
        "stock market", "wall street", "dow", "nasdaq", "s&p",
        "crash", "flash crash", "vix", "volatility", "bear market",
        "bull market", "ipo", "earnings", "market cap", "index",
        "bitcoin", "crypto", "commodity", "oil price", "gold price",
        "brent", "crude", "natural gas", "wheat", "grain",
        "currency", "dollar", "euro ", "yuan", "yen ", "ruble",
        "devaluation", "capital flight", "market sentiment",
        "bond market", "credit spread", "yield curve",
        "investor", "trading", "liquidity",
    }),
    "SOCIAL": frozenset({
        "protest", "demonstration", "riot", "uprising", "revolution",
        "civil unrest", "mass protest", "strike", "labor",
        "refugee", "migration", "asylum", "displaced",
        "famine", "hunger", "food crisis", "water crisis",
        "pandemic", "epidemic", "outbreak", "public health",
        "inequality", "poverty", "cost of living",
        "election", "vote", "referendum", "democracy",
        "human rights", "civil liberties", "censorship",
        "humanitarian", "aid", "relief", "ngo",
    }),
    "TECHNOLOGY": frozenset({
        "cyber attack", "hack", "ransomware", "data breach",
        "artificial intelligence", "ai ", "machine learning",
        "semiconductor", "chip", "microchip", "foundry",
        "quantum", "quantum computing", "encryption",
        "space", "satellite", "launch", "orbit",
        "5g", "6g", "infrastructure", "subsea cable",
        "drone", "autonomous", "robotics",
        "tech war", "export control", "chip ban",
        "biotech", "gene", "crispr",
        "renewable", "solar", "nuclear energy", "fusion",
        "surveillance", "privacy", "regulation",
    }),
}

# Source types that automatically indicate a domain
_SOURCE_TYPE_DOMAINS: dict[str, str] = {
    "economic_shift": "ECONOMIC",
    "financial_anomaly": "MARKET",
    "infrastructure_cascade": "TECHNOLOGY",
    "security_event": "GEOPOLITICAL",
    "perception_event": "GEOPOLITICAL",
    "social_disruption": "SOCIAL",
    "tech_disruption": "TECHNOLOGY",
    "curiosity_finding": "GENERAL",
    "prophecy_resolved": "GENERAL",
}


def _classify_signal_domain(headline: str, source_type: str) -> set[str]:
    """Classify a single signal into one or more domains."""
    domains: set[str] = set()
    text = headline.lower()

    # Source type gives a strong domain indicator
    if source_type in _SOURCE_TYPE_DOMAINS:
        domains.add(_SOURCE_TYPE_DOMAINS[source_type])

    # Keyword matching across all domains
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in text)
        if matches >= 1:
            domains.add(domain)

    return domains or {"GENERAL"}  # default fallback — non-matching signals are GENERAL, not GEOPOLITICAL


def _classify_pattern_domains(pattern: "EmergentPattern") -> set[str]:
    """Classify a pattern's domains based on ALL its signals.

    A pattern that contains signals from multiple domains is a
    cross-domain pattern — these are the most valuable insights.
    """
    domains: set[str] = set()
    for signal in pattern.signals:
        domains |= _classify_signal_domain(signal.headline, signal.source_type)
    return domains


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
        self._last_fire_ts = 0.0    # Timestamp of last fire (for cooldown)
        self.convergence_score = 0.0
        self.impact_score = 0.0     # Strategic impact (0.0-1.0), set before fire

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
        Re-fire at 0.75 and 0.90 thresholds, with 10-min minimum cooldown
        between fires to prevent alert flooding."""
        if not self.fired:
            return False
        # Enforce minimum 10-minute cooldown between fires
        if (time.time() - self._last_fire_ts) < 600:
            return False
        next_threshold = 0.75 if self.fire_count == 1 else 0.90
        return self.convergence_score >= next_threshold and self.fire_count < 3

    def summary_text(self) -> str:
        """Generate a summary of the pattern for LLM evaluation."""
        # Top headlines (most recent first, up to 10)
        recent = sorted(self.signals, key=lambda s: s.timestamp, reverse=True)[:10]
        headlines = "\n".join(f"  [{s.source_type}] {s.headline}" for s in recent)

        top_topics = sorted(self.topics, key=lambda t: sum(1 for s in self.signals if t in s.topics), reverse=True)[:15]

        # Cross-domain classification
        domains = _classify_pattern_domains(self)
        domain_str = ", ".join(sorted(domains))
        cross_domain_note = ""
        if len(domains) >= 2:
            cross_domain_note = (
                f"\n*** CROSS-DOMAIN PATTERN ({len(domains)} domains) ***\n"
                f"This pattern spans: {domain_str}\n"
                f"Cross-domain patterns are HIGH VALUE — the combination of domains\n"
                f"reveals insights that single-domain analysis cannot.\n"
            )

        return (
            f"PATTERN ID: {self.id}\n"
            f"Convergence: {self.convergence_score:.2f}\n"
            f"Impact: {self.impact_score:.2f}\n"
            f"Domains: {domain_str}\n"
            f"Signals: {len(self.signals)} from {len(self.source_types)} source types\n"
            f"Source types: {', '.join(sorted(self.source_types))}\n"
            f"Regions: {', '.join(sorted(self.regions))}\n"
            f"Key topics: {', '.join(top_topics)}\n"
            f"Age: {int(time.time() - self.created_at)}s\n"
            f"{cross_domain_note}"
            f"\nRecent signals:\n{headlines}"
        )

    def to_dict(self) -> dict:
        domains = _classify_pattern_domains(self)
        return {
            "id": self.id,
            "convergence_score": round(self.convergence_score, 3),
            "impact_score": round(self.impact_score, 3),
            "domains": sorted(domains),
            "cross_domain": len(domains) >= 2,
            "domain_count": len(domains),
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
        """Estimate strategic impact of a pattern across ALL domains.

        Scans pattern headlines against scope, entity, breaking-news,
        economic indicators, and cross-domain signals. Returns 0.0-1.0.

        Scoring hierarchy:
          Global scope          → base 0.90
          Global figure          → base 0.85
          Continental scope      → base 0.75
          Major power country    → base 0.70
          Economic pattern       → base 0.65  (financial signals are strategic)
          Unknown/minor scope    → base 0.25

        Additive bonuses:
          Breaking news headline → +0.15
          Economic crisis terms  → +0.15
          Cross-domain signals   → +0.15  (2+ domains in same pattern)
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

        # ── Economic pattern base score ──
        # Financial/economic signals are strategically significant on their own
        # even without country references (e.g. "yield curve inversion" is global)
        econ_count = sum(1 for kw in _ECONOMIC_KEYWORDS if kw in headlines_text)
        has_econ_source = bool(
            {"economic_shift", "financial_anomaly"} & pattern.source_types
        )
        if has_econ_source or econ_count >= 2:
            score = max(score, 0.65)

        # ── Breaking news boost ──
        if any(ind in headlines_text for ind in _BREAKING_INDICATORS):
            score = min(1.0, score + 0.15)

        # ── Economic crisis boost ──
        if any(ind in headlines_text for ind in _ECONOMIC_CRISIS):
            score = min(1.0, score + 0.15)

        # ── General economic content additive boost ──
        if econ_count >= 3:
            score = min(1.0, score + 0.10)
        elif econ_count >= 1:
            score = min(1.0, score + 0.05)

        # ── Cross-domain fusion bonus ──
        # Patterns spanning multiple domains are MORE valuable than single-domain
        pattern_domains = _classify_pattern_domains(pattern)
        if len(pattern_domains) >= 3:
            score = min(1.0, score + 0.20)  # 3+ domains = high-value insight
        elif len(pattern_domains) >= 2:
            score = min(1.0, score + 0.12)  # 2 domains = cross-domain correlation

        # ── Natural disaster boost ──
        if any(ind in headlines_text for ind in _NATURAL_DISASTERS):
            score = min(1.0, score + 0.10)

        # ── Source diversity bonus ──
        if len(pattern.source_types) >= 3:
            score = min(1.0, score + 0.05)

        # ── Financial signal corroboration ──
        if "financial_anomaly" in pattern.source_types:
            score = min(1.0, score + 0.15)

        # ── Entity Graph cascade analysis (if available) ──
        if self.engine.entity_graph:
            try:
                entities = []
                for s in pattern.signals[:15]:
                    ents = self.engine.entity_graph.extract_entities(s.headline)
                    entities.extend([name for name, _ in ents])
                if entities:
                    cascade = self.engine.entity_graph.get_cascade_impact(list(set(entities)))
                    graph_impact = cascade.get("impact_score", 0.0)
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
        elif any(kw in headline_lower for kw in _ECONOMIC_CRISIS):
            weight = max(weight, 0.45)  # Economic crisis terms = high-priority
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
            # ── Impact gate: only fire if strategically significant ──
            impact = self._estimate_impact_score(target_pattern)
            target_pattern.impact_score = impact

            if impact >= IMPACT_THRESHOLD:
                self._fire_pattern(target_pattern, escalation=refire_candidate)

                # High-impact cross-domain patterns warrant a conversation request
                domains = _classify_pattern_domains(target_pattern)
                if impact >= 0.90 and len(domains) >= 3:
                    try:
                        self.engine.request_conversation(
                            topic=f"Critical cross-domain pattern ({', '.join(sorted(domains))})",
                            reason=(
                                f"Pattern with {len(target_pattern.signals)} signals across "
                                f"{len(domains)} domains (impact={impact:.2f}). "
                                f"Key topics: {', '.join(sorted(target_pattern.topics)[:8])}"
                            ),
                            urgency=CRITICAL,
                            context_data={
                                "pattern_id": target_pattern.id,
                                "impact": impact,
                                "domains": sorted(domains),
                                "signal_count": len(target_pattern.signals),
                            },
                        )
                    except Exception as exc:
                        logger.warning("[PatternAccumulator] Conversation request failed: %s", exc)

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
        pattern._last_fire_ts = time.time()
        self._total_fires += 1

        domains = _classify_pattern_domains(pattern)
        prefix = "ESCALATION — " if escalation else ""
        cross = f"CROSS-DOMAIN({','.join(sorted(domains))}) " if len(domains) >= 2 else ""
        logger.info(
            "[PatternAccumulator] %s%sFiring pattern %s (convergence=%.2f, impact=%.2f, "
            "signals=%d, domains=%s, types=%s)",
            prefix, cross, pattern.id, pattern.convergence_score, pattern.impact_score,
            len(pattern.signals), ",".join(sorted(domains)),
            ",".join(sorted(pattern.source_types)),
        )

        # Delegate to ProactiveEngine for LLM evaluation + delivery
        self.engine.evaluate_and_notify(
            event_type="emergent_pattern",
            event_data={
                "pattern_id": pattern.id,
                "convergence_score": round(pattern.convergence_score, 3),
                "impact_score": round(pattern.impact_score, 3),
                "signal_count": len(pattern.signals),
                "domains": sorted(domains),
                "cross_domain": len(domains) >= 2,
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
        cross_domain = [p for p in alive if len(_classify_pattern_domains(p)) >= 2]
        return {
            "total_signals_ingested": self._total_signals,
            "total_patterns_created": self._total_patterns_created,
            "total_fires": self._total_fires,
            "total_impact_suppressed": self._total_impact_suppressed,
            "active_patterns": len(alive),
            "cross_domain_patterns": len(cross_domain),
            "hot_patterns": sum(1 for p in alive if p.convergence_score >= 0.30),
            "ready_to_fire": sum(1 for p in alive if p.should_fire()),
        }

# ── Decision prompt: should we bother the user? ──
IMPORTANCE_CLASSIFIER_PROMPT = """You are the INITIATIVE FILTER for an autonomous intelligence system called Αίολος.
Current date and time: {current_datetime}

Your job: decide whether a finding is important enough to INTERRUPT the user (Πάνος).

The user is a busy professional. He trusts the system to work autonomously.
He does NOT want noise. He DOES want to know about:
- Cross-domain insights: connections between geopolitics, economics, markets, technology, social unrest
- Financial/economic developments with strategic implications (rate decisions, market crashes, debt crises, trade wars)
- Geopolitical developments that change the strategic picture
- Confirmed or disconfirmed predictions (prophecies grounding in reality)
- Surprising discoveries that contradict current assumptions
- Emerging multi-domain patterns that require immediate attention or decision
- The COMBINATION of domains is what makes insights valuable — a single-domain observation
  is rarely worth interrupting the user. Cross-domain correlations ARE worth it.

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


# ══════════════════════════════════════════════════════════════
#  AUTONOMOUS PROPHECY PROMPT — structured scenario from pattern
# ══════════════════════════════════════════════════════════════

_AUTONOMOUS_PROPHECY_PROMPT = """You are the PROPHETIC ENGINE of Αίολος, an autonomous intelligence system.
Current date and time: {current_datetime}

You are given an emergent cross-domain pattern that Αίολος detected from
real-time data monitoring. Your task: decide whether this pattern warrants
a LONG-TERM SCENARIO (prophecy) and, if so, generate one.

A prophecy is warranted when:
  - The pattern implies consequences that will play out over WEEKS or MONTHS
  - The pattern connects multiple domains (e.g., economic → political → security)
  - There is enough signal to formulate a falsifiable prediction
  - The scenario would be USEFUL for strategic decision-making

A prophecy is NOT warranted when:
  - The pattern is a simple news event with no long-term implications
  - The outcome is already obvious / consensus
  - There is insufficient data to make a meaningful prediction

Respond ONLY with valid JSON:
{{
    "generate_prophecy": true|false,
    "reasoning": "Why this pattern does/doesn't warrant a prophecy",
    "scenario": {{
        "name": "Short memorable name (3-7 words)",
        "narrative": "What happens in this scenario — the story (200-400 words)",
        "trajectory": "Step-by-step path from now to outcome",
        "conditions": [
            {{"condition": "What must be true", "probability": 0.0-1.0, "evidence": "Supporting evidence"}}
        ],
        "timeline": "Expected timeframe (e.g., '3-6 months', '1-2 years')",
        "predicted_outcome": "The end state if this plays out",
        "confidence": 0.0-1.0,
        "falsifiability": "What would disprove this within 6 months"
    }}
}}

If generate_prophecy is false, set scenario to null.
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
        domains: list[str] | None = None,
    ):
        self.id = f"n_{int(time.time() * 1000)}"
        self.headline = headline
        self.summary = summary
        self.urgency = urgency
        self.source = source
        self.reason = reason
        self.raw_data = raw_data or {}
        self.domains = domains or []
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
            "domains": self.domains,
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
        self.prophetic_memory = None         # PropheticMemory — set by api.py after init

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
        now_str = datetime.now(ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d %H:%M Athens")
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

        # Extract domain classification from event data (set by PatternAccumulator)
        # or classify from headline as fallback
        notif_domains = event_data.get("domains", [])
        if not notif_domains:
            notif_domains = sorted(_classify_signal_domain(headline, event_type))

        notification = Notification(
            headline=headline,
            summary=summary,
            urgency=urgency,
            source=event_type,
            reason=reason,
            raw_data=event_data,
            domains=notif_domains,
        )

        self._notifications.append(notification)
        self._total_notified += 1
        self._log_notification(notification)

        # All evaluated alerts get full delivery — the LLM already decided
        # should_notify=true. Urgency controls Telegram only.
        self._deliver_immediate(notification)

        # ── AUTONOMOUS PROPHECY: if pattern meets prophecy thresholds ──
        convergence = event_data.get("convergence_score", 0)
        signal_count = len(event_data.get("headlines", []))
        # Use content-based domain classification (not raw source_type labels)
        # because most signals arrive as 'perception_alert' regardless of domain
        content_domains = event_data.get("domains", [])
        if (convergence >= self._PROPHECY_MIN_CONVERGENCE
                and signal_count >= self._PROPHECY_MIN_SIGNAL_COUNT
                and len(set(content_domains)) >= self._PROPHECY_MIN_CROSS_DOMAIN):
            try:
                self.generate_autonomous_prophecy(
                    pattern_data=event_data,
                    research_findings=research_findings,
                )
            except Exception as exc:
                logger.warning("[Proactive] Autonomous prophecy generation failed: %s", exc)

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
    #  PROACTIVE CONVERSATION STARTER
    #  When Αίολος discovers something that warrants a DIALOGUE
    #  (not just a one-way alert), he requests a conversation.
    # ══════════════════════════════════════════════════════════════

    # Cooldown: don't spam conversation requests
    _CONVERSATION_REQUEST_COOLDOWN = 3600  # 1 hour between requests (general)
    _VISUAL_ARRIVAL_COOLDOWN = 600         # 10 min between face-arrival requests

    def request_conversation(
        self,
        topic: str,
        reason: str,
        urgency: str = IMPORTANT,
        context_data: dict | None = None,
    ) -> Notification | None:
        """Request a new conversation with Panos.

        Unlike regular notifications (one-way alerts), this explicitly signals
        that Αίολος wants to DISCUSS something — it's a dialogue invitation.

        Triggers:
          - CuriosityEngine: exploration with priority > 0.95
          - PatternAccumulator: cross-domain pattern with impact > 0.90
          - Cross-system learning: breakthrough paper discovery
          - VisionIntegration: face arrival (uses shorter cooldown)

        Delivery:
          - Telegram: conversational message ("Πάνο, χρειάζομαι τη γνώμη σου...")
          - SSE: conversation_request event (UI shows dialogue bubble)
        """
        # Determine if this is a visual arrival (shorter cooldown)
        is_visual_arrival = (
            (context_data or {}).get("trigger") == "visual_perception_arrival"
        )
        cooldown = (
            self._VISUAL_ARRIVAL_COOLDOWN if is_visual_arrival
            else self._CONVERSATION_REQUEST_COOLDOWN
        )

        # Cooldown check — visual arrivals only check against other visual arrivals
        now_ts = datetime.now(timezone.utc).timestamp()
        recent_requests = [
            n for n in self._notifications
            if n.source == "conversation_request"
            and (now_ts - datetime.fromisoformat(n.created_at).timestamp()) < cooldown
            and (
                not is_visual_arrival
                or n.raw_data.get("trigger") == "visual_perception_arrival"
            )
        ]
        if recent_requests:
            logger.info("[Proactive] Conversation request cooldown (%ds) — skipping: %s",
                        cooldown, topic[:80])
            return None

        # Create a conversation-request notification
        conv_domains = (context_data or {}).get("domains", [])
        if not conv_domains:
            conv_domains = sorted(_classify_signal_domain(topic, "conversation_request"))
        notification = Notification(
            headline=f"💬 {topic}",
            summary=reason,
            urgency=urgency,
            source="conversation_request",
            reason=reason,
            raw_data=context_data or {},
            domains=conv_domains,
        )

        self._notifications.append(notification)
        self._total_notified += 1
        self._log_notification(notification)

        # SSE: push with conversation_request flag
        data = notification.to_dict()
        data["conversation_start"] = True
        data["conversation_request"] = True  # distinguishes from regular alerts
        dead_queues = []
        for q in self._sse_subscribers:
            try:
                q.put_nowait(data)
                notification.delivered_sse = True
            except asyncio.QueueFull:
                dead_queues.append(q)
        for q in dead_queues:
            self._sse_subscribers.remove(q)

        # Telegram: conversational tone, not alert tone
        self._send_conversation_request_telegram(notification, context_data)

        logger.info("[Proactive] 💬 CONVERSATION REQUESTED: %s", topic[:100])
        return notification

    def _send_conversation_request_telegram(
        self,
        notification: Notification,
        context_data: dict | None = None,
    ) -> bool:
        """Send a conversation request via Telegram with a dialogue-oriented format."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return False

        # Build a conversational message
        context_lines = []
        if context_data:
            if "priority" in context_data:
                context_lines.append(f"Priority: {context_data['priority']:.2f}")
            if "confidence" in context_data:
                context_lines.append(f"Confidence: {context_data['confidence']:.0%}")
            if "domains" in context_data:
                context_lines.append(f"Domains: {', '.join(context_data['domains'])}")
            if "key_finding" in context_data:
                context_lines.append(f"\n{context_data['key_finding'][:500]}")

        context_block = "\n".join(context_lines) if context_lines else ""

        text = (
            "💬 *Πάνο, χρειάζομαι τη γνώμη σου.*\n\n"
            f"*{notification.headline}*\n\n"
            f"{notification.summary[:800]}\n\n"
            f"{context_block}\n\n"
            "_Αυτό χρειάζεται συζήτηση, όχι απλά ειδοποίηση. "
            "Όταν μπορέσεις, άνοιξε chat._"
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
                    logger.info("[Proactive] Conversation request sent via Telegram: %s",
                                notification.headline[:60])
                    return True
                else:
                    logger.warning("[Proactive] Telegram conversation request failed (%d): %s",
                                   resp.status_code, resp.text[:200])
                    return False
        except Exception as exc:
            logger.warning("[Proactive] Telegram conversation request error: %s", exc)
            return False

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
            now_str = datetime.now(ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d %H:%M Athens")
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

        now_str = datetime.now(ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d %H:%M Athens")
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
    #  AUTONOMOUS PROPHECY GENERATION
    #  When a high-impact cross-domain pattern is detected, Αίολος
    #  generates a structured scenario and stores it in prophetic memory.
    #  The scenario is marked "autonomous_proposed" and requires
    #  Panos's approval before entering active tracking.
    # ══════════════════════════════════════════════════════════════

    # Thresholds for autonomous prophecy generation
    _PROPHECY_MIN_CONVERGENCE = 0.70       # Pattern must be well-converged
    _PROPHECY_MIN_SIGNAL_COUNT = 4         # Corroborated by 4+ signals
    _PROPHECY_MIN_CROSS_DOMAIN = 2         # Must span 2+ source types
    _PROPHECY_COOLDOWN = 7200              # 2 hours between prophecy generations

    def generate_autonomous_prophecy(
        self,
        pattern_data: dict,
        research_findings: str = "",
    ) -> dict | None:
        """Generate an autonomous long-term scenario from a detected pattern.

        Called by evaluate_and_notify when a pattern meets the prophecy thresholds.
        The scenario is stored in prophetic memory as 'autonomous_proposed'
        and Panos is notified via request_conversation().

        Args:
            pattern_data: The emergent pattern data (from PatternAccumulator)
            research_findings: Auto-research synthesis (if available)

        Returns:
            Dict with scenario info if generated, None if skipped/failed
        """
        if not self.prophetic_memory:
            logger.debug("[Proactive/Prophecy] No prophetic_memory attached — skipping")
            return None

        # Cooldown: don't spam prophecies
        recent_prophecies = [
            n for n in self._notifications
            if n.source == "autonomous_prophecy"
            and (datetime.now(timezone.utc).timestamp()
                 - datetime.fromisoformat(n.created_at).timestamp())
            < self._PROPHECY_COOLDOWN
        ]
        if recent_prophecies:
            logger.info("[Proactive/Prophecy] Cooldown active — skipping")
            return None

        # Build context for the LLM
        headlines = pattern_data.get("headlines", [])
        source_types = pattern_data.get("source_types", [])
        regions = pattern_data.get("regions", [])
        convergence = pattern_data.get("convergence_score", 0)
        impact = pattern_data.get("impact_score", 0)

        pattern_summary = (
            f"EMERGENT PATTERN (convergence={convergence:.2f}, impact={impact:.2f}):\n"
            f"Sources: {', '.join(source_types)}\n"
            f"Regions: {', '.join(set(regions))}\n"
            f"Key signals:\n" +
            "\n".join(f"  - {h}" for h in headlines[:8])
        )

        if research_findings:
            pattern_summary += f"\n\nRESEARCH FINDINGS:\n{research_findings[:2000]}"

        # Ask LLM to generate a structured scenario
        now_str = datetime.now(ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d %H:%M Athens")
        try:
            result = self.llm.call_json(
                _AUTONOMOUS_PROPHECY_PROMPT.format(current_datetime=now_str),
                pattern_summary,
                max_tokens=2000,
                temperature=0.4,
            )
        except Exception as exc:
            logger.warning("[Proactive/Prophecy] LLM generation failed: %s", exc)
            return None

        if not result.get("generate_prophecy", False):
            logger.info("[Proactive/Prophecy] LLM decided no prophecy needed: %s",
                        result.get("reasoning", ""))
            return None

        scenario_data = result.get("scenario", {})
        if not scenario_data.get("name") or not scenario_data.get("narrative"):
            logger.warning("[Proactive/Prophecy] Invalid scenario data from LLM")
            return None

        # Build a Scenario model
        from xdart.models import Scenario, ScenarioCondition

        conditions = []
        for c in scenario_data.get("conditions", []):
            if isinstance(c, dict):
                # Normalise field names — LLM may use 'condition' instead of 'description'
                desc = c.get("description") or c.get("condition") or c.get("name", "")
                currently_met = c.get("currently_met", c.get("met", c.get("probability", 0.5) > 0.5 if "probability" in c else False))
                evidence = c.get("evidence", "pattern-derived")
                conditions.append(ScenarioCondition(
                    description=str(desc),
                    currently_met=bool(currently_met),
                    evidence=str(evidence),
                ))
            elif isinstance(c, str):
                conditions.append(ScenarioCondition(description=c, currently_met=False, evidence="pattern-derived"))

        scenario = Scenario(
            name=scenario_data.get("name", "Autonomous Prophecy"),
            source_view_id="proactive_engine",
            source_perspective="autonomous_pattern_detection",
            narrative=scenario_data.get("narrative", ""),
            trajectory=scenario_data.get("trajectory", ""),
            conditions=conditions,
            timeline=scenario_data.get("timeline", "3-6 months"),
            predicted_outcome=scenario_data.get("predicted_outcome", ""),
            confidence=min(1.0, max(0.0, float(scenario_data.get("confidence", 0.5)))),
            falsifiability=scenario_data.get("falsifiability", ""),
        )

        # Store in prophetic memory as autonomous_proposed
        problem = (
            f"[Autonomous detection] {' | '.join(headlines[:3])}"
            if headlines else "Autonomous pattern detection"
        )
        entry = self.prophetic_memory.store_autonomous_prophecy(
            problem=problem,
            scenario=scenario,
            source="proactive_engine",
        )

        # Notify Panos via conversation request
        self.request_conversation(
            topic=f"Αυτόνομη πρόβλεψη: {scenario.name}",
            reason=(
                f"Ανίχνευσα ένα cross-domain pattern (convergence={convergence:.2f}) "
                f"και δημιούργησα μια αυτόνομη πρόβλεψη:\n\n"
                f"**{scenario.name}**\n"
                f"{scenario.narrative[:500]}\n\n"
                f"→ Predicted outcome: {scenario.predicted_outcome}\n"
                f"→ Timeline: {scenario.timeline}\n"
                f"→ Confidence: {scenario.confidence:.0%}\n\n"
                f"Χρειάζομαι την έγκρισή σου για να αρχίσω active tracking."
            ),
            urgency=IMPORTANT,
            context_data={
                "type": "autonomous_prophecy",
                "entry_id": entry.id,
                "scenario_name": scenario.name,
                "confidence": scenario.confidence,
                "convergence": convergence,
                "signal_count": len(headlines),
                "domains": source_types,
            },
        )

        logger.info(
            "[Proactive/Prophecy] AUTONOMOUS PROPHECY generated: %s (id=%s, confidence=%.2f)",
            scenario.name, entry.id[:8], scenario.confidence,
        )

        # Also create a notification for the log
        notification = Notification(
            headline=f"🔮 {scenario.name}",
            summary=f"Autonomous prophecy: {scenario.narrative[:300]}",
            urgency=IMPORTANT,
            source="autonomous_prophecy",
            reason=f"Cross-domain pattern (convergence={convergence:.2f}, {len(headlines)} signals)",
            raw_data={"entry_id": entry.id, "scenario_name": scenario.name},
            domains=source_types if isinstance(source_types, list) else list(source_types),
        )
        self._notifications.append(notification)
        self._log_notification(notification)

        return {
            "entry_id": entry.id,
            "scenario_name": scenario.name,
            "confidence": scenario.confidence,
            "timeline": scenario.timeline,
            "status": "autonomous_proposed",
        }

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
            now_str = datetime.now(ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d %H:%M Athens")
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
