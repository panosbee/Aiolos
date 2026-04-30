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
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
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
# ── Runaway pattern caps ──
# Prevents one topic (e.g., Iran) from absorbing all signals into a single blob
PATTERN_SIGNAL_CAP = 60     # After this many signals, start a new pattern for low-overlap signals
PATTERN_SPLIT_ENTITY_OVERLAP = 0.20  # New signal with < this entity overlap → force new pattern

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
    "cross_pattern_synthesis": 0.50, # Deep fusion compound insight (highest value)
    "temporal_precursor": 0.45,      # Temporal pattern precursor match (pre-event alert)
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
    "infrastructure_cascade": "ECONOMIC",
    "security_event": "GEOPOLITICAL",
    "perception_event": "GEOPOLITICAL",
    "perception_alert": "GEOPOLITICAL",       # multimodal OSINT (airspace, satellite)
    "social_disruption": "SOCIAL",
    "tech_disruption": "TECHNOLOGY",
    "curiosity_finding": "GENERAL",
    "prophecy_resolved": "GENERAL",
}

# ══════════════════════════════════════════════════════════════════════════════
#  META-THEME REGISTRY — Thematic bridges that transcend entity co-occurrence.
#
#  The EntityGraph connects patterns that share ENTITIES (Iran → OPEC → Oil).
#  But the user's insight was: Musk/AI job loss + Iran/fuel/food costs share
#  NO entities — they connect through THEMES (resource scarcity, systemic pressure).
#
#  Meta-themes are the ABSTRACT layer above domains. A pattern about AI killing
#  jobs and a pattern about war raising food prices both point to the same
#  meta-theme: "convergent pressure on population sustainability".
#
#  Each meta-theme has:
#    - keywords: words that indicate the theme in pattern topics/headlines
#    - weight: how strategically significant this theme is (0.0-1.0)
# ══════════════════════════════════════════════════════════════════════════════

_META_THEMES: dict[str, dict] = {
    "resource_scarcity": {
        "keywords": frozenset({
            "food", "fuel", "energy", "oil", "water", "shortage", "scarcity",
            "inflation", "cost", "price", "expensive", "famine", "hunger",
            "fertilizer", "grain", "wheat", "rice", "gas", "electricity",
            "supply", "demand", "rationing", "stockpile", "reserve",
        }),
        "weight": 0.85,
    },
    "systemic_collapse": {
        "keywords": frozenset({
            "collapse", "crisis", "crash", "recession", "depression",
            "breakdown", "failure", "meltdown", "contagion", "default",
            "bankruptcy", "insolvency", "cascade", "systemic", "fragility",
            "bubble", "unsustainable", "implosion",
        }),
        "weight": 0.90,
    },
    "power_restructuring": {
        "keywords": frozenset({
            "election", "coup", "regime", "power", "governance", "political",
            "authoritarian", "democracy", "dictatorship", "succession",
            "impeachment", "overthrow", "legitimacy", "mandate", "sovereignty",
            "hegemony", "multipolar", "unipolar", "alliance", "bloc",
        }),
        "weight": 0.75,
    },
    "technological_disruption": {
        "keywords": frozenset({
            "ai", "artificial", "intelligence", "automation", "robot",
            "job", "employment", "workforce", "labor", "unemployment",
            "disruption", "technology", "replacement", "obsolete",
            "ubi", "basic income", "machine", "algorithm", "chatbot",
            "autonomous", "driverless", "chip", "semiconductor",
        }),
        "weight": 0.80,
    },
    "population_pressure": {
        "keywords": frozenset({
            "population", "migration", "refugee", "demographic", "birth",
            "death", "aging", "fertility", "displacement", "exodus",
            "urbanization", "overcrowding", "carrying capacity",
            "depopulation", "immigration", "asylum", "border",
        }),
        "weight": 0.80,
    },
    "military_escalation": {
        "keywords": frozenset({
            "war", "military", "weapon", "nuclear", "missile", "army",
            "conflict", "invasion", "escalation", "ceasefire", "troop",
            "airstrike", "bombardment", "conscription", "mobilization",
            "nato", "defense", "offensive", "frontline", "casualties",
        }),
        "weight": 0.90,
    },
    "financial_contagion": {
        "keywords": frozenset({
            "market", "stock", "bond", "currency", "bank", "debt",
            "default", "contagion", "bailout", "liquidity", "credit",
            "interest", "yield", "spread", "volatility", "panic",
            "sell-off", "crash", "derivative", "leverage", "exposure",
        }),
        "weight": 0.85,
    },
    "supply_chain_fragility": {
        "keywords": frozenset({
            "supply chain", "shipping", "port", "trade", "embargo",
            "sanction", "chokepoint", "strait", "canal", "logistics",
            "freight", "container", "bottleneck", "disruption",
            "reshoring", "decoupling", "dependency", "blockade",
        }),
        "weight": 0.80,
    },
    "social_instability": {
        "keywords": frozenset({
            "protest", "riot", "unrest", "inequality", "unemployment",
            "poverty", "crime", "polarization", "radicalization",
            "civil", "disobedience", "strike", "demonstration",
            "looting", "martial law", "curfew", "discontent",
        }),
        "weight": 0.85,
    },
    "information_warfare": {
        "keywords": frozenset({
            "propaganda", "disinformation", "cyber", "hack", "influence",
            "media", "narrative", "fake", "manipulation", "psyop",
            "censorship", "surveillance", "deepfake", "troll",
            "bot", "campaign", "interference", "leak",
        }),
        "weight": 0.75,
    },
    "climate_energy_transition": {
        "keywords": frozenset({
            "climate", "carbon", "emission", "renewable", "solar",
            "wind", "fossil", "coal", "transition", "green",
            "paris agreement", "cop", "net zero", "methane",
            "drought", "flood", "wildfire", "extreme weather",
            "heatwave", "glacier", "sea level",
        }),
        "weight": 0.70,
    },
    "health_biological_risk": {
        "keywords": frozenset({
            "pandemic", "epidemic", "virus", "outbreak", "vaccine",
            "mutation", "variant", "quarantine", "lockdown", "bioweapon",
            "pathogen", "contagious", "who", "cdc", "mortality",
            "hospital", "healthcare", "pharmaceutical",
        }),
        "weight": 0.85,
    },
}

# ── Known Thematic Bridges ──
# These are KNOWN cross-theme connections that produce high-value insights
# when detected simultaneously. Each bridge has a narrative template.
# Format: (theme_a, theme_b) → bridge description
_THEME_BRIDGES: dict[tuple[str, str], str] = {
    ("technological_disruption", "resource_scarcity"):
        "AI/automation eliminates jobs while resource costs rise → "
        "double pressure on population sustainability",
    ("technological_disruption", "social_instability"):
        "Technological displacement fuels social unrest — "
        "unemployed populations become politically volatile",
    ("military_escalation", "resource_scarcity"):
        "War disrupts supply chains (fuel, food, fertilizer) → "
        "civilian resource crisis compounds military pressure",
    ("military_escalation", "financial_contagion"):
        "Conflict triggers capital flight and market panic → "
        "war costs + market losses create fiscal crisis",
    ("resource_scarcity", "social_instability"):
        "Rising costs of living drive civil unrest — "
        "bread riots have toppled more regimes than armies",
    ("resource_scarcity", "population_pressure"):
        "Insufficient resources + demographic pressure → "
        "migration waves, carrying capacity debates, policy extremes",
    ("systemic_collapse", "financial_contagion"):
        "Institutional failure triggers cascading financial defaults → "
        "trust evaporates, liquidity freezes, contagion accelerates",
    ("power_restructuring", "military_escalation"):
        "Power transitions increase conflict risk — "
        "Thucydides trap: rising power vs established order",
    ("information_warfare", "social_instability"):
        "Disinformation amplifies social tensions — "
        "manufactured narratives accelerate polarization",
    ("supply_chain_fragility", "resource_scarcity"):
        "Supply chain disruptions create artificial scarcity → "
        "chokepoint warfare affects civilian resource access",
    ("climate_energy_transition", "resource_scarcity"):
        "Climate events destroy crops/infrastructure while transition costs rise → "
        "energy poverty + food insecurity converge",
    ("health_biological_risk", "social_instability"):
        "Pandemic response creates economic damage + civil liberties tension → "
        "public health vs economic survival dilemma",
    ("technological_disruption", "power_restructuring"):
        "AI concentrates power in tech-capable states/actors → "
        "digital divide becomes geopolitical divide",
    ("military_escalation", "supply_chain_fragility"):
        "War zones overlap with trade routes → "
        "kinetic conflict causes global supply disruption",
    ("financial_contagion", "social_instability"):
        "Market crash destroys savings, triggers unemployment → "
        "economic pain converts to political radicalization",
    ("technological_disruption", "military_escalation"):
        "AI/autonomous weapons change warfare calculus → "
        "lower barrier to conflict, asymmetric advantage",
    ("resource_scarcity", "financial_contagion"):
        "Commodity price spikes trigger inflation + rate hikes → "
        "debt servicing becomes impossible for vulnerable economies",
    ("population_pressure", "social_instability"):
        "Demographic shifts + migration pressure fuel nativist movements → "
        "political instability in receiving and origin countries",
}


def _compute_theme_fingerprint(pattern: "EmergentPattern") -> dict[str, float]:
    """Compute meta-theme fingerprint for a pattern.

    Returns dict of theme_name → match_strength (0.0-1.0).
    Scans all pattern topics and headlines for meta-theme keywords.
    """
    # Gather all text from the pattern
    all_topics = pattern.topics
    all_text_tokens: set[str] = set()
    for signal in pattern.signals:
        all_text_tokens |= set(signal.headline.lower().split())
    combined = all_topics | all_text_tokens

    fingerprint: dict[str, float] = {}
    for theme_name, theme_data in _META_THEMES.items():
        keywords = theme_data["keywords"]
        matches = combined & keywords
        if not matches:
            continue
        # Strength = fraction of theme keywords present, capped at 1.0
        # More matching keywords = stronger theme signal
        raw_strength = len(matches) / min(8, len(keywords))  # normalize against 8
        strength = min(1.0, raw_strength)
        if strength >= 0.10:  # minimum threshold
            fingerprint[theme_name] = round(strength, 3)

    return fingerprint


def _find_thematic_bridge(
    fp_a: dict[str, float],
    fp_b: dict[str, float],
) -> list[dict]:
    """Find thematic bridges between two pattern fingerprints.

    Returns list of bridge dicts with theme pair + narrative.
    Requires both patterns to have at least one meta-theme.
    """
    bridges: list[dict] = []

    for theme_a, strength_a in fp_a.items():
        for theme_b, strength_b in fp_b.items():
            if theme_a == theme_b:
                # Same meta-theme in both patterns = CONVERGENT pressure
                bridges.append({
                    "type": "convergent",
                    "theme": theme_a,
                    "strength": round((strength_a + strength_b) / 2, 3),
                    "narrative": f"Both patterns converge on {theme_a.replace('_', ' ')} "
                                 f"from different domains — amplifying the signal",
                })
            else:
                # Different themes — check known bridges
                key = tuple(sorted([theme_a, theme_b]))
                if key in _THEME_BRIDGES:
                    bridges.append({
                        "type": "bridge",
                        "themes": [theme_a, theme_b],
                        "strength": round(
                            (strength_a + strength_b) / 2
                            * _META_THEMES[theme_a]["weight"]
                            * _META_THEMES[theme_b]["weight"],
                            3
                        ),
                        "narrative": _THEME_BRIDGES[key],
                    })

    # Sort by strength descending
    bridges.sort(key=lambda b: b["strength"], reverse=True)
    return bridges


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

    def summary_text(self, entity_graph=None) -> str:
        """Generate a summary of the pattern for LLM evaluation.

        When entity_graph is provided, includes structural relationship context
        (entity neighborhoods + connection evidence) for deeper reasoning.
        """
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

        # Entity graph structural context (when available)
        graph_context = ""
        if entity_graph and self.core_entities:
            try:
                core_list = sorted(self.core_entities)[:8]
                neighborhood = entity_graph.get_entity_neighborhood(core_list, max_neighbors=4)
                if neighborhood:
                    nbr_lines = []
                    for entity, neighbors in neighborhood.items():
                        if neighbors:
                            conns = ", ".join(
                                f"{n['entity']}({n['relationship']}, str={n['strength']})"
                                for n in neighbors[:3]
                            )
                            nbr_lines.append(f"  {entity}: {conns}")
                    if nbr_lines:
                        graph_context = (
                            "\n\nENTITY GRAPH CONTEXT (real-world connections from data):\n"
                            + "\n".join(nbr_lines) + "\n"
                            "Use these connections to understand HOW the entities relate "
                            "beyond what the headlines explicitly state.\n"
                        )
            except Exception:
                pass  # Graph context is bonus, never blocks

        return (
            f"PATTERN ID: {self.id}\n"
            f"Convergence: {self.convergence_score:.2f}\n"
            f"Impact: {self.impact_score:.2f}\n"
            f"Domains: {domain_str}\n"
            f"Signals: {len(self.signals)} from {len(self.source_types)} source types\n"
            f"Source types: {', '.join(sorted(self.source_types))}\n"
            f"Regions: {', '.join(sorted(self.regions))}\n"
            f"Core entities: {', '.join(sorted(self.core_entities)[:10])}\n"
            f"Key topics: {', '.join(top_topics)}\n"
            f"Age: {int(time.time() - self.created_at)}s\n"
            f"{cross_domain_note}"
            f"{graph_context}"
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


# ══════════════════════════════════════════════════════════════════════════════
#  COMPOUND ALERT CHAINS — Second-Order Pattern Detection (P4)
#  Detects when COMBINATIONS of patterns form escalation sequences.
#  This is what separates Palantir from a news aggregator.
# ══════════════════════════════════════════════════════════════════════════════

# Compound escalation rules: when pattern A + pattern B co-occur within
# a time window, fire a COMPOUND alert at elevated weight.
# Each rule: { "name", "requires" (set of source_type combos), "window_sec",
#              "compound_type", "weight", "description" }
_COMPOUND_RULES = [
    {
        "name": "conflict_risk_compound",
        "requires": {"security_event", "financial_anomaly"},
        "window_sec": 7200,    # 2 hours
        "compound_type": "CONFLICT_RISK",
        "weight": 0.70,
        "description": "Military activity coinciding with market panic — potential conflict escalation",
    },
    {
        "name": "instability_compound",
        "requires": {"economic_shift", "security_event"},
        "window_sec": 14400,   # 4 hours
        "compound_type": "INSTABILITY",
        "weight": 0.65,
        "description": "Economic disruption + security event — instability pattern",
    },
    {
        "name": "hybrid_warfare_compound",
        "requires": {"cyber_threat", "security_event"},
        "window_sec": 10800,   # 3 hours
        "compound_type": "HYBRID_WARFARE",
        "weight": 0.75,
        "description": "Cyber attack coinciding with kinetic security event — hybrid warfare signature",
    },
    {
        "name": "supply_chain_compound",
        "requires": {"perception_alert", "financial_anomaly"},
        "requires_keywords": {"chokepoint", "shipping", "maritime", "suez", "strait", "oil", "energy"},
        "window_sec": 14400,   # 4 hours
        "compound_type": "SUPPLY_CHAIN_DISRUPTION",
        "weight": 0.65,
        "description": "Maritime/supply disruption with market impact",
    },
    {
        "name": "sanctions_escalation_compound",
        "requires": {"sanctions_match", "economic_shift"},
        "window_sec": 86400,   # 24 hours (sanctions effects are slower)
        "compound_type": "SANCTIONS_ESCALATION",
        "weight": 0.60,
        "description": "Sanctions match plus economic shift — policy escalation",
    },
    {
        "name": "multi_domain_crisis_compound",
        "min_domain_count": 3,  # Instead of specific types, require 3+ domains
        "window_sec": 7200,    # 2 hours
        "compound_type": "MULTI_DOMAIN_CRISIS",
        "weight": 0.80,
        "description": "3+ domains showing simultaneous stress — systemic crisis pattern",
    },
    {
        "name": "airspace_conflict_compound",
        "requires": {"security_event"},
        "requires_keywords": {"airspace", "void", "military", "no-fly", "aircraft", "fighter"},
        "window_sec": 7200,
        "compound_type": "AIRSPACE_CONFLICT",
        "weight": 0.70,
        "description": "Airspace anomaly + security event — active conflict zone indicator",
    },
    {
        "name": "calendar_convergence_compound",
        "requires": {"calendar_proximity", "financial_anomaly"},
        "window_sec": 86400,
        "compound_type": "CALENDAR_CONVERGENCE",
        "weight": 0.55,
        "description": "Scheduled event approaching with pre-event market movement",
    },
]

# Cooldown between same compound type fires
_COMPOUND_COOLDOWN = 3600  # 1 hour


class CompoundAlertEngine:
    """Second-order pattern detection — patterns on patterns.

    Maintains a sliding window of recent pattern fires.
    Checks if combinations of fires match known escalation templates.
    Auto-fires compound alerts at elevated weight.
    """

    def __init__(self):
        self._recent_fires: list[dict] = []    # {source_type, headline, ts, domains, region}
        self._compound_fires: list[dict] = []   # Fired compound alerts
        self._cooldowns: dict[str, float] = {}   # compound_type → last_fire_ts
        self._total_compounds = 0
        self._window_size = 86400  # 24h sliding window

    def record_fire(
        self,
        source_types: set[str],
        headline: str,
        region: str,
        domains: list[str] | None = None,
    ):
        """Record a pattern fire for compound analysis.

        Called whenever PatternAccumulator fires a pattern.
        """
        now = time.time()
        self._recent_fires.append({
            "source_types": list(source_types),
            "headline": headline,
            "region": region,
            "domains": domains or [],
            "ts": now,
        })

        # Prune old fires outside window
        cutoff = now - self._window_size
        self._recent_fires = [f for f in self._recent_fires if f["ts"] > cutoff]

    def check_compounds(self) -> list[dict]:
        """Check all compound rules against recent fires.

        Returns list of compound alert dicts for PatternAccumulator/ProactiveEngine.
        """
        now = time.time()
        alerts = []

        for rule in _COMPOUND_RULES:
            compound_type = rule["compound_type"]

            # Cooldown check
            last_fire = self._cooldowns.get(compound_type, 0)
            if now - last_fire < _COMPOUND_COOLDOWN:
                continue

            window = rule["window_sec"]
            recent_in_window = [
                f for f in self._recent_fires
                if now - f["ts"] < window
            ]

            if not recent_in_window:
                continue

            triggered = False

            # Rule type 1: requires specific source_types
            if "requires" in rule:
                required = rule["requires"]
                all_types_in_window = set()
                for fire in recent_in_window:
                    all_types_in_window.update(fire["source_types"])

                if required.issubset(all_types_in_window):
                    # Additional keyword check if specified
                    if "requires_keywords" in rule:
                        all_headlines = " ".join(f["headline"].lower() for f in recent_in_window)
                        keyword_match = any(
                            kw in all_headlines
                            for kw in rule["requires_keywords"]
                        )
                        triggered = keyword_match
                    else:
                        triggered = True

            # Rule type 2: requires N domains
            if "min_domain_count" in rule and not triggered:
                all_domains = set()
                for fire in recent_in_window:
                    all_domains.update(fire["domains"])
                if len(all_domains) >= rule["min_domain_count"]:
                    triggered = True

            if triggered:
                # Build compound headline from constituent fires
                constituent_headlines = [
                    f["headline"][:80] for f in recent_in_window[-5:]
                ]
                regions = list(set(
                    f["region"] for f in recent_in_window if f["region"] != "GLOBAL"
                ))

                alert = {
                    "type": "compound_alert",
                    "compound_type": compound_type,
                    "headline": (
                        f"COMPOUND ALERT [{compound_type}]: {rule['description']}"
                    ),
                    "constituent_count": len(recent_in_window),
                    "constituents": constituent_headlines,
                    "region": regions[0] if regions else "GLOBAL",
                    "domain": "MULTI",
                    "weight": rule["weight"],
                    "salience": rule["weight"],
                    "ts": now,
                }
                alerts.append(alert)
                self._compound_fires.append(alert)
                self._cooldowns[compound_type] = now
                self._total_compounds += 1

                logger.info("[CompoundAlert] FIRED: %s (%d constituents, weight=%.2f)",
                            compound_type, len(recent_in_window), rule["weight"])

        # Trim compound fire history
        self._compound_fires = self._compound_fires[-100:]

        return alerts

    def get_compound_digest(self) -> str:
        """Formatted compound alert intelligence for Live Digest injection."""
        if not self._compound_fires:
            return ""

        now = time.time()
        recent = [
            c for c in self._compound_fires
            if now - c["ts"] < 86400  # Last 24h
        ]
        if not recent:
            return ""

        lines = ["▸ COMPOUND ALERT CHAINS (second-order pattern detection)"]
        for c in recent[-5:]:
            age_h = (now - c["ts"]) / 3600
            lines.append(
                f"  ⚡ [{c['compound_type']}] {c['constituent_count']} correlated signals "
                f"(weight={c['weight']:.2f}, {age_h:.1f}h ago)"
            )
            for i, constituent in enumerate(c["constituents"][:3]):
                lines.append(f"    └ {constituent}")

        lines.append("")
        return "\n".join(lines)

    def stats(self) -> dict:
        now = time.time()
        return {
            "recent_fires_in_window": len(self._recent_fires),
            "total_compounds_fired": self._total_compounds,
            "active_compounds_24h": len([
                c for c in self._compound_fires
                if now - c["ts"] < 86400
            ]),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  HYPOTHESIS ENGINE — P2 "αν X τότε Y" Persistent Conditional Tracking
# ══════════════════════════════════════════════════════════════════════════════
#
#  Unlike prophecies (LLM-generated long-term scenarios), hypotheses are
#  lightweight conditional rules continuously checked against incoming signals:
#    "IF Iran closes Strait of Hormuz THEN oil spikes above $100 within 14 days"
#
#  Lifecycle: active → trigger_detected → confirmed | disconfirmed | expired
#
#  Sources:
#    - Autonomous: generated from fired patterns and cross-pattern synthesis
#    - User-initiated: explicit "watch for X → Y" requests
#    - Pipeline: generated during deep analysis runs
#
#  Every signal that enters feed_signal() is checked against active hypotheses.
#  When enough evidence accumulates, LLM verifies confirmation/disconfirmation.
# ══════════════════════════════════════════════════════════════════════════════


class Hypothesis:
    """A persistent conditional prediction: 'If X then Y within Z'."""

    __slots__ = (
        "id", "created_at", "source", "hypothesis_text",
        "trigger_condition", "expected_outcome",
        "trigger_keywords", "outcome_keywords",
        "trigger_entities", "outcome_entities",
        "timeframe_days", "deadline", "confidence",
        "status", "domains",
        "trigger_evidence", "outcome_evidence",
        "trigger_confidence", "outcome_confidence",
        "resolution_reason", "pattern_id",
    )

    def __init__(
        self,
        *,
        id: str,
        created_at: str,
        source: str,
        hypothesis_text: str,
        trigger_condition: str,
        expected_outcome: str,
        trigger_keywords: set,
        outcome_keywords: set,
        trigger_entities: set | None = None,
        outcome_entities: set | None = None,
        timeframe_days: int = 30,
        deadline: float = 0.0,
        confidence: float = 0.5,
        status: str = "active",
        domains: list | None = None,
        trigger_evidence: list | None = None,
        outcome_evidence: list | None = None,
        trigger_confidence: float = 0.0,
        outcome_confidence: float = 0.0,
        resolution_reason: str = "",
        pattern_id: str = "",
    ):
        self.id = id
        self.created_at = created_at
        self.source = source
        self.hypothesis_text = hypothesis_text
        self.trigger_condition = trigger_condition
        self.expected_outcome = expected_outcome
        self.trigger_keywords = trigger_keywords or set()
        self.outcome_keywords = outcome_keywords or set()
        self.trigger_entities = trigger_entities or set()
        self.outcome_entities = outcome_entities or set()
        self.timeframe_days = timeframe_days
        self.deadline = deadline or (time.time() + timeframe_days * 86400)
        self.confidence = confidence
        self.status = status
        self.domains = domains or []
        self.trigger_evidence = trigger_evidence or []
        self.outcome_evidence = outcome_evidence or []
        self.trigger_confidence = trigger_confidence
        self.outcome_confidence = outcome_confidence
        self.resolution_reason = resolution_reason
        self.pattern_id = pattern_id


class HypothesisEngine:
    """Persistent 'if X then Y' hypothesis tracking and verification.

    Αίολος generates hypotheses from pattern analysis and continuously
    monitors incoming signals for evidence of trigger conditions and
    expected outcomes. When evidence accumulates, LLM judges whether
    the hypothesis is confirmed or disconfirmed.
    """

    _MAX_ACTIVE = 50                       # Max simultaneous active hypotheses
    _TRIGGER_EVIDENCE_MIN = 2              # Min trigger signals before LLM check
    _OUTCOME_EVIDENCE_MIN = 2              # Min outcome signals before LLM check
    _LLM_VERIFICATION_COOLDOWN = 3600      # 1h between LLM checks per hypothesis
    _AUTO_GEN_MIN_CONVERGENCE = 0.55       # Min pattern convergence for auto-gen
    _AUTO_GEN_COOLDOWN = 1800              # 30min between auto-generations
    _PERSIST_PATH = Path("hypothesis_state.json")
    _JOURNAL_PATH = Path("hypothesis_journal.jsonl")

    def __init__(self, engine: "ProactiveEngine"):
        self.engine = engine
        self._hypotheses: list[Hypothesis] = []
        self._last_verification: dict[str, float] = {}   # hyp_id → last LLM check ts
        self._last_auto_gen_ts: float = 0.0
        self._total_created = 0
        self._total_confirmed = 0
        self._total_disconfirmed = 0
        self._total_expired = 0
        self._total_signals_checked = 0
        self._load_state()

    # ────────────────────────────────────────────────────────────
    #  Creation
    # ────────────────────────────────────────────────────────────

    def _prune_stale_hypotheses(self) -> list["Hypothesis"]:
        """Prune the bottom 10% of active hypotheses when at capacity.

        Score = confidence × recency_factor where recency_factor decays
        linearly from 1.0 → 0.0 over 30 days.  Lowest-scoring hypotheses
        are marked expired and removed first.
        """
        active = self._active_hypotheses()
        prune_count = max(1, len(active) // 10)  # 10% of current cap
        now_ts = time.time()

        def _score(h: "Hypothesis") -> float:
            try:
                created_ts = datetime.fromisoformat(h.created_at.replace("Z", "+00:00")).timestamp()
            except Exception:
                created_ts = now_ts
            age_days = (now_ts - created_ts) / 86400.0
            recency = max(0.0, 1.0 - age_days / 30.0)
            return h.confidence * recency

        sorted_hyps = sorted(active, key=_score)
        pruned: list["Hypothesis"] = []
        for hyp in sorted_hyps[:prune_count]:
            hyp.status = "expired"
            hyp.resolved_at = datetime.now(timezone.utc).isoformat()
            pruned.append(hyp)
            self._total_expired += 1
            self._journal_log("pruned_stale", hyp)

        if pruned:
            logger.info(
                "[HypothesisEngine] Pruned %d stale hypotheses (lowest confidence×recency)",
                len(pruned),
            )
            self._save_state()

        return pruned

    def create_hypothesis(
        self,
        hypothesis_text: str,
        trigger_condition: str,
        expected_outcome: str,
        trigger_keywords: set[str],
        outcome_keywords: set[str],
        trigger_entities: set[str] | None = None,
        outcome_entities: set[str] | None = None,
        timeframe_days: int = 30,
        confidence: float = 0.5,
        source: str = "autonomous",
        domains: list[str] | None = None,
        pattern_id: str = "",
    ) -> Hypothesis | None:
        """Create a new hypothesis for continuous monitoring.

        Returns the Hypothesis if created, None if rejected (max active reached
        or duplicate detected).
        """
        # Cap check — attempt pruning before hard rejection
        active = self._active_hypotheses()
        if len(active) >= self._MAX_ACTIVE:
            pruned = self._prune_stale_hypotheses()
            active = self._active_hypotheses()
            if len(active) >= self._MAX_ACTIVE:
                logger.warning(
                    "[HypothesisEngine] Max active hypotheses (%d) after pruning %d — rejecting",
                    self._MAX_ACTIVE, len(pruned),
                )
                return None

        # Duplicate check — skip if we already track very similar hypothesis
        hyp_lower = hypothesis_text.lower()
        for existing in active:
            existing_lower = existing.hypothesis_text.lower()
            # Simple Jaccard on words — catches near-duplicates
            words_new = set(hyp_lower.split())
            words_old = set(existing_lower.split())
            if words_new and words_old:
                overlap = len(words_new & words_old) / len(words_new | words_old)
                if overlap >= 0.70:
                    logger.info("[HypothesisEngine] Duplicate skipped (overlap=%.2f): %.60s",
                                overlap, hypothesis_text)
                    return None

        hyp = Hypothesis(
            id=f"hyp_{int(time.time() * 1000)}",
            created_at=datetime.now(timezone.utc).isoformat(),
            source=source,
            hypothesis_text=hypothesis_text,
            trigger_condition=trigger_condition,
            expected_outcome=expected_outcome,
            trigger_keywords={kw.lower() for kw in trigger_keywords} if trigger_keywords else set(),
            outcome_keywords={kw.lower() for kw in outcome_keywords} if outcome_keywords else set(),
            trigger_entities=trigger_entities or set(),
            outcome_entities=outcome_entities or set(),
            timeframe_days=timeframe_days,
            confidence=confidence,
            domains=domains or [],
            pattern_id=pattern_id,
        )
        self._hypotheses.append(hyp)
        self._total_created += 1
        self._journal_log("created", hyp)
        self._save_state()

        logger.info(
            "[HypothesisEngine] CREATED [%s] '%s' (conf=%.2f, %dd, src=%s)",
            hyp.id, hypothesis_text[:80], confidence, timeframe_days, source,
        )
        return hyp

    # ────────────────────────────────────────────────────────────
    #  Signal Checking — called for EVERY incoming signal
    # ────────────────────────────────────────────────────────────

    def check_signal(
        self,
        headline: str,
        entities: set[str],
        source_type: str,
        region: str,
    ) -> list[dict]:
        """Check a signal against all active hypotheses.

        Called from PatternAccumulator.ingest() for every incoming data event.
        Uses keyword/entity matching as a fast first-pass filter, then
        accumulates evidence for LLM verification.

        Returns list of hypothesis state-change events (trigger_detected,
        confirmed, disconfirmed, expired).
        """
        self._total_signals_checked += 1
        events: list[dict] = []
        state_dirty = False
        now = time.time()
        headline_lower = headline.lower()

        for hyp in self._active_hypotheses():
            # ── Expiry check ──
            if now > hyp.deadline:
                self._expire(hyp)
                events.append({"type": "expired", "hypothesis_id": hyp.id})
                continue

            changed = False

            # ── Trigger condition matching ──
            trigger_kw_hits = sum(1 for kw in hyp.trigger_keywords if kw in headline_lower)
            trigger_entity_hit = bool(hyp.trigger_entities & entities) if hyp.trigger_entities else False

            if trigger_kw_hits > 0 or trigger_entity_hit:
                evidence = {
                    "headline": headline[:200],
                    "entities": sorted(entities)[:10],
                    "source_type": source_type,
                    "region": region,
                    "keyword_hits": trigger_kw_hits,
                    "entity_hit": trigger_entity_hit,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                hyp.trigger_evidence.append(evidence)
                hyp.trigger_evidence = hyp.trigger_evidence[-20:]  # Rolling window

                # Confidence boost — diminishing returns
                boost = 0.15 / (1 + len(hyp.trigger_evidence) * 0.1)
                hyp.trigger_confidence = min(1.0, hyp.trigger_confidence + boost)
                changed = True

                # Transition: active → trigger_detected
                if hyp.status == "active" and hyp.trigger_confidence >= 0.50:
                    hyp.status = "trigger_detected"
                    events.append({
                        "type": "trigger_detected",
                        "hypothesis_id": hyp.id,
                        "hypothesis_text": hyp.hypothesis_text,
                    })
                    self._journal_log("trigger_detected", hyp)
                    logger.info("[HypothesisEngine] TRIGGER DETECTED [%s]: '%s'",
                                hyp.id, hyp.hypothesis_text[:80])

            # ── Outcome matching ──
            outcome_kw_hits = sum(1 for kw in hyp.outcome_keywords if kw in headline_lower)
            outcome_entity_hit = bool(hyp.outcome_entities & entities) if hyp.outcome_entities else False

            if outcome_kw_hits > 0 or outcome_entity_hit:
                evidence = {
                    "headline": headline[:200],
                    "entities": sorted(entities)[:10],
                    "source_type": source_type,
                    "region": region,
                    "keyword_hits": outcome_kw_hits,
                    "entity_hit": outcome_entity_hit,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                hyp.outcome_evidence.append(evidence)
                hyp.outcome_evidence = hyp.outcome_evidence[-20:]

                boost = 0.15 / (1 + len(hyp.outcome_evidence) * 0.1)
                hyp.outcome_confidence = min(1.0, hyp.outcome_confidence + boost)
                changed = True

            # ── LLM Verification gate ──
            if (changed
                    and hyp.trigger_confidence >= 0.40
                    and hyp.outcome_confidence >= 0.40
                    and len(hyp.trigger_evidence) >= self._TRIGGER_EVIDENCE_MIN
                    and len(hyp.outcome_evidence) >= self._OUTCOME_EVIDENCE_MIN):
                last_check = self._last_verification.get(hyp.id, 0)
                if now - last_check >= self._LLM_VERIFICATION_COOLDOWN:
                    verdict = self._llm_verify(hyp)
                    if verdict:
                        events.append(verdict)

            if changed:
                state_dirty = True

        # Persist if evidence was added or state transitions occurred
        if state_dirty or events:
            self._save_state()

        return events

    # ────────────────────────────────────────────────────────────
    #  LLM Verification
    # ────────────────────────────────────────────────────────────

    def _llm_verify(self, hyp: Hypothesis) -> dict | None:
        """Ask LLM to judge whether hypothesis is confirmed or disconfirmed."""
        self._last_verification[hyp.id] = time.time()

        trigger_lines = "\n".join(
            f"  - [{e['ts'][:10]}] {e['headline']}" for e in hyp.trigger_evidence[-5:]
        )
        outcome_lines = "\n".join(
            f"  - [{e['ts'][:10]}] {e['headline']}" for e in hyp.outcome_evidence[-5:]
        )

        user_msg = (
            f"HYPOTHESIS: {hyp.hypothesis_text}\n\n"
            f"TRIGGER CONDITION: {hyp.trigger_condition}\n"
            f"EXPECTED OUTCOME: {hyp.expected_outcome}\n"
            f"TIMEFRAME: {hyp.timeframe_days} days (deadline: {datetime.fromtimestamp(hyp.deadline, tz=timezone.utc).strftime('%Y-%m-%d')})\n"
            f"INITIAL CONFIDENCE: {hyp.confidence:.2f}\n\n"
            f"TRIGGER EVIDENCE ({len(hyp.trigger_evidence)} signals, confidence={hyp.trigger_confidence:.2f}):\n"
            f"{trigger_lines}\n\n"
            f"OUTCOME EVIDENCE ({len(hyp.outcome_evidence)} signals, confidence={hyp.outcome_confidence:.2f}):\n"
            f"{outcome_lines}\n"
        )

        try:
            result = self.engine.llm.call_json(
                _HYPOTHESIS_VERIFICATION_PROMPT,
                user_msg,
                max_tokens=2000,
                temperature=0.2,
            )
        except Exception as exc:
            logger.warning("[HypothesisEngine] LLM verification failed for %s: %s",
                           hyp.id, exc)
            return None

        judgment = (result.get("judgment") or "insufficient").lower()
        reasoning = result.get("reasoning", "")
        final_conf = result.get("final_confidence", hyp.confidence)

        if judgment == "confirmed":
            hyp.status = "confirmed"
            hyp.resolution_reason = reasoning
            hyp.confidence = final_conf
            self._total_confirmed += 1
            self._journal_log("confirmed", hyp)
            self._save_state()

            # Deliver notification (fire-and-forget via dedicated pool)
            self.engine._eval_pool.submit(
                self.engine.evaluate_and_notify,
                "hypothesis_confirmed",
                {
                    "hypothesis_id": hyp.id,
                    "hypothesis": hyp.hypothesis_text,
                    "confidence": hyp.confidence,
                    "domains": hyp.domains,
                    "trigger_evidence_count": len(hyp.trigger_evidence),
                    "outcome_evidence_count": len(hyp.outcome_evidence),
                    "convergence_score": (hyp.trigger_confidence + hyp.outcome_confidence) / 2,
                },
                (
                    f"HYPOTHESIS CONFIRMED: {hyp.hypothesis_text}\n\n"
                    f"Trigger evidence:\n{trigger_lines}\n\n"
                    f"Outcome evidence:\n{outcome_lines}\n\n"
                    f"LLM reasoning: {reasoning}"
                ),
            )
            logger.info("[HypothesisEngine] CONFIRMED [%s]: '%s' (conf=%.2f)",
                        hyp.id, hyp.hypothesis_text[:80], final_conf)
            return {"type": "confirmed", "hypothesis_id": hyp.id}

        elif judgment == "disconfirmed":
            hyp.status = "disconfirmed"
            hyp.resolution_reason = reasoning
            hyp.confidence = final_conf
            self._total_disconfirmed += 1
            self._journal_log("disconfirmed", hyp)
            self._save_state()

            logger.info("[HypothesisEngine] DISCONFIRMED [%s]: '%s' — %s",
                        hyp.id, hyp.hypothesis_text[:80], reasoning[:300])
            return {"type": "disconfirmed", "hypothesis_id": hyp.id}

        # "insufficient" — continue monitoring
        return None

    # ────────────────────────────────────────────────────────────
    #  Auto-Generation from Patterns and Synthesis
    # ────────────────────────────────────────────────────────────

    def generate_from_pattern(self, pattern: "EmergentPattern") -> Hypothesis | None:
        """Auto-generate a testable hypothesis from a fired pattern.

        Only generates if pattern convergence is high enough and cooldown
        has elapsed. Uses LLM to formulate the if-then conditional.
        """
        if pattern.convergence_score < self._AUTO_GEN_MIN_CONVERGENCE:
            return None

        now = time.time()
        if now - self._last_auto_gen_ts < self._AUTO_GEN_COOLDOWN:
            return None

        recent = sorted(pattern.signals, key=lambda s: s.timestamp, reverse=True)[:5]
        headlines_text = "\n".join(f"  - {s.headline[:120]}" for s in recent)
        domains = sorted(_classify_pattern_domains(pattern))

        user_msg = (
            f"PATTERN DOMAINS: {', '.join(domains)}\n"
            f"CORE ENTITIES: {', '.join(sorted(pattern.core_entities)[:8])}\n"
            f"CONVERGENCE: {pattern.convergence_score:.2f}\n"
            f"IMPACT: {pattern.impact_score:.2f}\n"
            f"SIGNALS: {len(pattern.signals)}\n"
            f"SOURCE TYPES: {', '.join(sorted(pattern.source_types))}\n\n"
            f"RECENT HEADLINES:\n{headlines_text}\n"
        )

        try:
            result = self.engine.llm.call_json(
                _HYPOTHESIS_GENERATION_PROMPT,
                user_msg,
                max_tokens=600,
                temperature=0.3,
            )
        except Exception as exc:
            logger.debug("[HypothesisEngine] Pattern hypothesis generation failed: %s", exc)
            return None

        if not result.get("generate_hypothesis", False):
            return None

        self._last_auto_gen_ts = now
        return self.create_hypothesis(
            hypothesis_text=result.get("hypothesis", ""),
            trigger_condition=result.get("trigger_condition", ""),
            expected_outcome=result.get("expected_outcome", ""),
            trigger_keywords=set(result.get("trigger_keywords", [])),
            outcome_keywords=set(result.get("outcome_keywords", [])),
            trigger_entities=set(result.get("trigger_entities", [])),
            outcome_entities=set(result.get("outcome_entities", [])),
            timeframe_days=result.get("timeframe_days", 30),
            confidence=result.get("confidence", 0.5),
            source="pattern",
            domains=domains,
            pattern_id=pattern.id,
        )

    def generate_from_synthesis(self, synthesis: dict) -> Hypothesis | None:
        """Auto-generate hypothesis from cross-pattern synthesis insight.

        Synthesis insights connect two patterns — the causal chain and
        second-order effects are rich material for if-then hypotheses.
        """
        insight = synthesis.get("compound_insight", "")
        if not insight:
            return None

        now = time.time()
        if now - self._last_auto_gen_ts < self._AUTO_GEN_COOLDOWN:
            return None

        causal = synthesis.get("causal_chain", "")
        effects = synthesis.get("second_order_effects", [])

        user_msg = (
            f"COMPOUND INSIGHT: {insight}\n"
            f"CAUSAL CHAIN: {causal}\n"
            f"SECOND ORDER EFFECTS: {'; '.join(effects[:3])}\n"
            f"DOMAINS: {', '.join(synthesis.get('domains', []))}\n"
            f"ENTITIES: {', '.join(synthesis.get('core_entities', [])[:8])}\n"
            f"CONFIDENCE: {synthesis.get('confidence', 0):.2f}\n"
        )

        try:
            result = self.engine.llm.call_json(
                _HYPOTHESIS_GENERATION_PROMPT,
                user_msg,
                max_tokens=600,
                temperature=0.3,
            )
        except Exception as exc:
            logger.debug("[HypothesisEngine] Synthesis hypothesis generation failed: %s", exc)
            return None

        if not result.get("generate_hypothesis", False):
            return None

        self._last_auto_gen_ts = now
        return self.create_hypothesis(
            hypothesis_text=result.get("hypothesis", ""),
            trigger_condition=result.get("trigger_condition", ""),
            expected_outcome=result.get("expected_outcome", ""),
            trigger_keywords=set(result.get("trigger_keywords", [])),
            outcome_keywords=set(result.get("outcome_keywords", [])),
            trigger_entities=set(result.get("trigger_entities", [])),
            outcome_entities=set(result.get("outcome_entities", [])),
            timeframe_days=result.get("timeframe_days", 30),
            confidence=result.get("confidence", 0.5),
            source="synthesis",
            domains=synthesis.get("domains", []),
        )

    # ────────────────────────────────────────────────────────────
    #  Digest — formatted intelligence for pipeline/chat injection
    # ────────────────────────────────────────────────────────────

    def get_digest(self) -> str:
        """Return formatted hypothesis intelligence digest.

        Injected into pipeline context and chat context so Αίολος
        is aware of what hypotheses are being tracked and their status.
        """
        active = self._active_hypotheses()
        if not active:
            return ""

        lines = [
            "▸ PERSISTENT HYPOTHESES ('if X then Y' conditional monitoring)",
        ]
        for h in sorted(active, key=lambda x: x.confidence, reverse=True)[:8]:
            status_icon = "🔍" if h.status == "active" else "⚡"
            trigger_pct = f"{h.trigger_confidence * 100:.0f}%"
            outcome_pct = f"{h.outcome_confidence * 100:.0f}%"
            days_left = max(0, int((h.deadline - time.time()) / 86400))
            lines.append(
                f"  {status_icon} [{','.join(h.domains[:2])}] {h.hypothesis_text[:100]}"
            )
            lines.append(
                f"    Trigger: {trigger_pct} ({len(h.trigger_evidence)} signals) | "
                f"Outcome: {outcome_pct} ({len(h.outcome_evidence)} signals) | "
                f"Conf: {h.confidence:.2f} | {days_left}d left"
            )

        # Track record
        confirmed = sum(1 for h in self._hypotheses if h.status == "confirmed")
        disconfirmed = sum(1 for h in self._hypotheses if h.status == "disconfirmed")
        if confirmed or disconfirmed:
            accuracy = confirmed / (confirmed + disconfirmed)
            lines.append(
                f"  📊 Track record: {confirmed} confirmed, "
                f"{disconfirmed} disconfirmed ({accuracy * 100:.0f}% accuracy)"
            )

        lines.append("")
        return "\n".join(lines)

    def get_all_hypotheses(self, status_filter: str | None = None) -> list[dict]:
        """Return all hypotheses as dicts, optionally filtered by status."""
        hyps = self._hypotheses
        if status_filter:
            hyps = [h for h in hyps if h.status == status_filter]
        return [self._hyp_to_dict(h) for h in hyps]

    # ────────────────────────────────────────────────────────────
    #  Stats
    # ────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        active = self._active_hypotheses()
        total_resolved = self._total_confirmed + self._total_disconfirmed
        return {
            "active": len(active),
            "trigger_detected": sum(1 for h in active if h.status == "trigger_detected"),
            "total_created": self._total_created,
            "confirmed": self._total_confirmed,
            "disconfirmed": self._total_disconfirmed,
            "expired": self._total_expired,
            "accuracy": (
                self._total_confirmed / max(1, total_resolved)
            ),
            "total_signals_checked": self._total_signals_checked,
        }

    # ────────────────────────────────────────────────────────────
    #  Internal helpers
    # ────────────────────────────────────────────────────────────

    def _active_hypotheses(self) -> list[Hypothesis]:
        return [h for h in self._hypotheses if h.status in ("active", "trigger_detected")]

    def _expire(self, hyp: Hypothesis) -> None:
        hyp.status = "expired"
        hyp.resolution_reason = "Deadline passed without sufficient evidence"
        self._total_expired += 1
        self._journal_log("expired", hyp)
        logger.info("[HypothesisEngine] EXPIRED [%s]: '%s'", hyp.id, hyp.hypothesis_text[:80])

    def _journal_log(self, event: str, hyp: Hypothesis) -> None:
        try:
            entry = {
                "event": event,
                "hypothesis_id": hyp.id,
                "hypothesis": hyp.hypothesis_text,
                "confidence": hyp.confidence,
                "status": hyp.status,
                "trigger_evidence_count": len(hyp.trigger_evidence),
                "outcome_evidence_count": len(hyp.outcome_evidence),
                "trigger_confidence": round(hyp.trigger_confidence, 3),
                "outcome_confidence": round(hyp.outcome_confidence, 3),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with open(self._JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # Dual-write to MongoDB
            if hasattr(self.engine, "_mongo") and self.engine._mongo:
                self.engine._mongo.log_journal("hypotheses", entry)
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {
                "hypotheses": [self._hyp_to_dict(h) for h in self._hypotheses[-200:]],
                "stats": {
                    "total_created": self._total_created,
                    "total_confirmed": self._total_confirmed,
                    "total_disconfirmed": self._total_disconfirmed,
                    "total_expired": self._total_expired,
                },
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            self._PERSIST_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[HypothesisEngine] State save failed: %s", exc)

    def _load_state(self) -> None:
        if not self._PERSIST_PATH.exists():
            return
        try:
            data = json.loads(self._PERSIST_PATH.read_text(encoding="utf-8"))
            for hd in data.get("hypotheses", []):
                self._hypotheses.append(self._dict_to_hyp(hd))
            stats = data.get("stats", {})
            self._total_created = stats.get("total_created", 0)
            self._total_confirmed = stats.get("total_confirmed", 0)
            self._total_disconfirmed = stats.get("total_disconfirmed", 0)
            self._total_expired = stats.get("total_expired", 0)
            logger.info(
                "[HypothesisEngine] Loaded %d hypotheses (%d active)",
                len(self._hypotheses), len(self._active_hypotheses()),
            )
        except Exception as exc:
            logger.warning("[HypothesisEngine] State load failed: %s", exc)

    @staticmethod
    def _hyp_to_dict(h: Hypothesis) -> dict:
        return {
            "id": h.id,
            "created_at": h.created_at,
            "source": h.source,
            "hypothesis_text": h.hypothesis_text,
            "trigger_condition": h.trigger_condition,
            "expected_outcome": h.expected_outcome,
            "trigger_keywords": sorted(h.trigger_keywords),
            "outcome_keywords": sorted(h.outcome_keywords),
            "trigger_entities": sorted(h.trigger_entities),
            "outcome_entities": sorted(h.outcome_entities),
            "timeframe_days": h.timeframe_days,
            "deadline": h.deadline,
            "confidence": h.confidence,
            "status": h.status,
            "domains": h.domains,
            "trigger_evidence": h.trigger_evidence[-10:],
            "outcome_evidence": h.outcome_evidence[-10:],
            "trigger_confidence": round(h.trigger_confidence, 3),
            "outcome_confidence": round(h.outcome_confidence, 3),
            "resolution_reason": h.resolution_reason,
            "pattern_id": h.pattern_id,
        }

    @staticmethod
    def _dict_to_hyp(d: dict) -> Hypothesis:
        return Hypothesis(
            id=d["id"],
            created_at=d["created_at"],
            source=d["source"],
            hypothesis_text=d["hypothesis_text"],
            trigger_condition=d["trigger_condition"],
            expected_outcome=d["expected_outcome"],
            trigger_keywords=set(d.get("trigger_keywords", [])),
            outcome_keywords=set(d.get("outcome_keywords", [])),
            trigger_entities=set(d.get("trigger_entities", [])),
            outcome_entities=set(d.get("outcome_entities", [])),
            timeframe_days=d.get("timeframe_days", 30),
            deadline=d["deadline"],
            confidence=d["confidence"],
            status=d["status"],
            domains=d.get("domains", []),
            trigger_evidence=d.get("trigger_evidence", []),
            outcome_evidence=d.get("outcome_evidence", []),
            trigger_confidence=d.get("trigger_confidence", 0.0),
            outcome_confidence=d.get("outcome_confidence", 0.0),
            resolution_reason=d.get("resolution_reason", ""),
            pattern_id=d.get("pattern_id", ""),
        )


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

    def _fission_pattern(self, parent: EmergentPattern) -> EmergentPattern | None:
        """Split an oversaturated pattern into a focused child pattern.

        When a parent pattern accumulates 20+ signals it may be covering
        multiple distinct sub-themes.  Fission creates a child pattern seeded
        with the 10 most-recent signals and the 3 most-frequently-mentioned
        entities.  The parent retains its full signal history.

        Returns the child EmergentPattern, or None if fission is not worthwhile
        (e.g. child would have the same entities as parent → no real split).
        """
        if len(parent.signals) < 20:
            return None

        # Take the 10 most recent signals as the child's nucleus
        recent_signals = sorted(parent.signals, key=lambda s: s.timestamp, reverse=True)[:10]

        # Narrow entity set: top 3 by mention count in the RECENT signals
        entity_freq: dict[str, int] = {}
        for s in recent_signals:
            for e in s.entities:
                entity_freq[e] = entity_freq.get(e, 0) + 1
        top_entities = {e for e, _ in sorted(entity_freq.items(), key=lambda x: -x[1])[:3]}

        # Abort if child entities are identical to parent core (no useful split)
        if top_entities and top_entities == parent.core_entities:
            return None

        # Build child using the most recent signal as seed
        child = EmergentPattern(recent_signals[0])
        for s in recent_signals[1:]:
            child.signals.append(s)
            child.topics |= s.topics
            for e in s.entities:
                child._entity_counts[e] = child._entity_counts.get(e, 0) + 1
            child.regions.add(s.region)
            child.source_types.add(s.source_type)
        child._recalculate_convergence()

        logger.info(
            "[PatternAccumulator] FISSION: %s → %s (parent=%d signals, child=%d signals, entities=%s)",
            parent.id, child.id, len(parent.signals), len(child.signals),
            sorted(top_entities)[:3],
        )
        return child

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

        # ── Hypothesis Engine: check signal against active hypotheses ──
        if self.engine.hypothesis_engine:
            try:
                self.engine.hypothesis_engine.check_signal(
                    headline=headline,
                    entities=entities,
                    source_type=source_type,
                    region=region,
                )
            except Exception as e:
                logger.debug("[PatternAccumulator] Hypothesis check error: %s", e)

        # ── Temporal Reasoning: check signal against pending A→B sequences ──
        if hasattr(self.engine, "_temporal_engine") and self.engine._temporal_engine:
            try:
                seq_matches = self.engine._temporal_engine.check_sequence_signal(
                    headline=headline,
                    topics=topics,
                    entities=entities,
                )
                for m in seq_matches:
                    logger.info(
                        "[PatternAccumulator] Temporal sequence completed: "
                        "%s → %s (%.1fh)",
                        m.get("event_a", "?")[:40],
                        m.get("event_b", "?")[:40],
                        m.get("delay_hours", 0),
                    )
            except Exception as e:
                logger.debug("[PatternAccumulator] Temporal sequence check error: %s", e)

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
            # ── Runaway cap: if pattern is very large AND entity overlap is low,
            # force a new pattern rather than merging everything into one blob.
            # This preserves granularity (e.g., Iran-diplomatic vs Iran-economic).
            if len(best_pattern.signals) >= PATTERN_SIGNAL_CAP:
                pat_core = best_pattern.core_entities
                if pat_core and entities:
                    entity_overlap_ratio = len(entities & pat_core) / max(1, min(len(entities), len(pat_core)))
                else:
                    entity_overlap_ratio = 1.0  # no entities → allow merge
                if entity_overlap_ratio < PATTERN_SPLIT_ENTITY_OVERLAP:
                    # Low entity overlap on an already-large pattern → start fresh
                    cap_signals = len(best_pattern.signals)
                    best_pattern = None
                    logger.debug("[PatternAccumulator] Cap+split: pattern at %d signals, "
                                 "entity_overlap=%.2f < %.2f — forcing new pattern for: %.60s",
                                 cap_signals, entity_overlap_ratio,
                                 PATTERN_SPLIT_ENTITY_OVERLAP, headline)
            if best_pattern is not None:
                best_pattern.absorb(signal)
                target_pattern = best_pattern
                logger.info(
                    "[PatternAccumulator] Merged signal into pattern (sim=%.2f, signals=%d, "
                    "types=%s, entities=%s): %.80s",
                    best_similarity, len(target_pattern.signals),
                    target_pattern.source_types, sorted(target_pattern.core_entities)[:5],
                    headline,
                )
                # Fission: split oversaturated pattern into focused child
                if len(target_pattern.signals) >= 20:
                    child = self._fission_pattern(target_pattern)
                    if child is not None:
                        self._patterns.append(child)
                        self._total_patterns_created += 1
            else:
                target_pattern = EmergentPattern(signal)
                self._patterns.append(target_pattern)
                self._total_patterns_created += 1
                logger.debug("[PatternAccumulator] Split new pattern #%d: %.80s",
                             self._total_patterns_created, headline)
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

        # ── Deep Pattern Fusion: periodically synthesize cross-pattern insights ──
        # This is self-throttled (15-min cooldown) so calling on every ingest is safe.
        # Every 50 signals, attempt synthesis regardless of fire status.
        if self._total_signals % 50 == 0:
            try:
                self.synthesize_cross_patterns()
            except Exception as exc:
                logger.warning("[PatternAccumulator] Cross-pattern synthesis error: %s", exc)

        return None

    def _fire_pattern(self, pattern: EmergentPattern, escalation: bool = False) -> None:
        """Evaluate pattern via LLM and notify if warranted.

        Also persists the fired pattern to MongoDB for narrative continuity —
        new patterns are checked against historical ones to detect continuations.
        """
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

        # ── Pattern Memory: persist to MongoDB ──
        pattern_record = {
            "pattern_id": pattern.id,
            "convergence_score": round(pattern.convergence_score, 3),
            "impact_score": round(pattern.impact_score, 3),
            "signal_count": len(pattern.signals),
            "domains": sorted(domains),
            "cross_domain": len(domains) >= 2,
            "source_types": sorted(pattern.source_types),
            "regions": sorted(pattern.regions),
            "top_topics": sorted(pattern.topics)[:20],
            "core_entities": sorted(pattern.core_entities)[:15],
            "headlines": [
                s.headline for s in
                sorted(pattern.signals, key=lambda s: s.timestamp, reverse=True)[:10]
            ],
            "fired_at": datetime.now(timezone.utc).isoformat(),
            "escalation": escalation,
            "fire_count": pattern.fire_count,
        }

        # Check for continuation of historical patterns
        continuation_of = self._check_pattern_continuation(pattern)
        if continuation_of:
            pattern_record["continuation_of"] = continuation_of
            logger.info(
                "[PatternAccumulator] Pattern %s is continuation of: %s",
                pattern.id, continuation_of,
            )

        if self.engine._mongo:
            try:
                self.engine._mongo.log_journal("pattern_memory", pattern_record)
                logger.info("[PatternAccumulator] Pattern %s persisted to MongoDB", pattern.id)
            except Exception as e:
                logger.debug("[PatternAccumulator] Pattern persistence failed: %s", e)

        # Delegate to ProactiveEngine for LLM evaluation + delivery
        event_data = {
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
        }
        if continuation_of:
            event_data["continuation_of"] = continuation_of

        # ── Record fire for Compound Alert Chain analysis ──
        try:
            self.engine.compound_alerts.record_fire(
                source_types=pattern.source_types,
                headline=event_data["headlines"][0] if event_data["headlines"] else pattern.id,
                region=sorted(pattern.regions)[0] if pattern.regions else "GLOBAL",
                domains=sorted(domains),
            )
            # Check for compound alerts
            compounds = self.engine.compound_alerts.check_compounds()
            for compound in compounds:
                logger.info("[PatternAccumulator] Compound alert fired: %s", compound["compound_type"])
                self.engine._eval_pool.submit(
                    self.engine.evaluate_and_notify,
                    "compound_alert",
                    compound,
                    f"Compound escalation: {compound['headline']}\nConstituents: {'; '.join(compound.get('constituents', []))}",
                )
        except Exception as exc:
            logger.debug("[PatternAccumulator] Compound alert check failed: %s", exc)

        # Submit to dedicated pool — don't block the Uvicorn thread that
        # called on_alert → feed_signal → _fire_pattern. This keeps HTTP
        # request handling responsive while LLM evaluation runs in background.
        context_text = pattern.summary_text(entity_graph=self.engine.entity_graph)
        self.engine._eval_pool.submit(
            self.engine.evaluate_and_notify,
            "emergent_pattern",
            event_data,
            context_text,
        )

        # ── Hypothesis Engine: auto-generate testable hypothesis from pattern ──
        if self.engine.hypothesis_engine:
            try:
                hyp = self.engine.hypothesis_engine.generate_from_pattern(pattern)
                if hyp:
                    logger.info("[PatternAccumulator] Hypothesis generated from pattern %s: %s",
                                pattern.id, hyp.hypothesis_text[:80])
            except Exception as exc:
                logger.debug("[PatternAccumulator] Hypothesis generation failed: %s", exc)

        # ── Temporal Reasoning: start sequence watch for high-impact patterns ──
        if (
            hasattr(self.engine, "_temporal_engine")
            and self.engine._temporal_engine
            and pattern.impact_score >= 0.65
        ):
            try:
                self.engine._temporal_engine.start_sequence_watch(
                    event_a_headline=event_data["headlines"][0] if event_data["headlines"] else pattern.id,
                    event_a_topics=pattern.topics,
                    event_a_entities=pattern.core_entities,
                    event_a_domains=domains,
                )
            except Exception as exc:
                logger.debug("[PatternAccumulator] Temporal sequence watch failed: %s", exc)

        # ── Dark Whisper Resonance: every fired pattern checks dormant dark signals ──
        # Coupling the two intelligence layers: a pattern that fires is also a
        # potential reactivation trigger for parked MAYBE dark whispers.  The
        # check runs in a daemon thread (non-blocking) and is a no-op when
        # DARKWEB_ENABLED=false (engine is None).
        if (
            hasattr(self.engine, "_darkwhisper_engine")
            and self.engine._darkwhisper_engine
        ):
            try:
                self.engine._darkwhisper_engine.trigger_resonance_check(
                    pattern_topics=pattern.topics,
                    pattern_entities=pattern.core_entities,
                    pattern_headlines=event_data["headlines"],
                )
            except Exception as exc:
                logger.debug("[PatternAccumulator] Dark whisper resonance check failed: %s", exc)

    def _check_pattern_continuation(self, pattern: EmergentPattern) -> list[str]:
        """Check if this pattern is a continuation of a previously fired pattern.

        Looks at MongoDB pattern_memory for patterns with overlapping entities/topics.
        Returns list of related pattern IDs, or empty list.
        """
        if not self.engine._mongo:
            return []

        try:
            # Get recent pattern memory (last 7 days)
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            recent_patterns = list(
                self.engine._mongo.db.pattern_memory.find(
                    {"fired_at": {"$gte": cutoff}},
                    {"pattern_id": 1, "core_entities": 1, "top_topics": 1, "_id": 0},
                ).sort("fired_at", -1).limit(50)
            )

            if not recent_patterns:
                return []

            current_entities = pattern.core_entities
            current_topics = pattern.topics

            related = []
            for past in recent_patterns:
                past_entities = set(past.get("core_entities", []))
                past_topics = set(past.get("top_topics", []))

                # Entity overlap check
                entity_overlap = len(current_entities & past_entities) if current_entities and past_entities else 0
                topic_overlap = len(current_topics & past_topics) if current_topics and past_topics else 0

                if entity_overlap >= 2 or topic_overlap >= 3:
                    related.append(past.get("pattern_id", "?"))

            return related[:3]  # max 3 continuations

        except Exception as e:
            logger.debug("[PatternAccumulator] Continuation check failed: %s", e)
            return []

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
        stats = {
            "total_signals_ingested": self._total_signals,
            "total_patterns_created": self._total_patterns_created,
            "total_fires": self._total_fires,
            "total_impact_suppressed": self._total_impact_suppressed,
            "active_patterns": len(alive),
            "cross_domain_patterns": len(cross_domain),
            "hot_patterns": sum(1 for p in alive if p.convergence_score >= 0.30),
            "ready_to_fire": sum(1 for p in alive if p.should_fire()),
        }
        # Include deep fusion stats if available
        if hasattr(self, "_fusion_total_synthesized"):
            stats["deep_fusion"] = self.get_fusion_stats()
        return stats

    def get_active_patterns_context(self, top_n: int = 8) -> str:
        """Generate a compact context string showing active converging patterns.

        This is injected into Αίολος's LLM context so he can see WHAT IS
        BUILDING — not just what already fired. This is the intelligence edge:
        seeing patterns before they reach threshold.

        Returns empty string if no interesting patterns.
        """
        now = time.time()
        alive = [p for p in self._patterns if p.is_alive(now) and p.convergence_score >= 0.15]
        if not alive:
            return ""

        # Sort by convergence (highest first)
        alive.sort(key=lambda p: p.convergence_score, reverse=True)

        lines = [
            f"ACTIVE PATTERN CLUSTERS ({len(alive)} alive, showing top {min(top_n, len(alive))}):",
            "These are patterns BUILDING from multiple data signals — not yet fired.",
            "Cross-domain patterns (2+ domains) are HIGH VALUE.",
            "",
        ]

        for i, pat in enumerate(alive[:top_n], 1):
            domains = _classify_pattern_domains(pat)
            domain_str = "+".join(sorted(domains))
            cross_tag = " ★CROSS-DOMAIN" if len(domains) >= 2 else ""

            # Status based on convergence
            if pat.convergence_score >= CONVERGENCE_THRESHOLD:
                status = "🔴 READY TO FIRE"
            elif pat.convergence_score >= 0.40:
                status = "🟡 BUILDING"
            else:
                status = "🟢 EMERGING"

            # Core entities (noise-filtered)
            core_ents = sorted(pat.core_entities)[:5]
            ents_str = ", ".join(core_ents) if core_ents else "none"

            # Top topics
            top_topics = sorted(
                pat.topics,
                key=lambda t: sum(1 for s in pat.signals if t in s.topics),
                reverse=True,
            )[:6]

            # Recent headlines (last 3)
            recent = sorted(pat.signals, key=lambda s: s.timestamp, reverse=True)[:3]

            lines.append(
                f"  [{i}] {status} convergence={pat.convergence_score:.2f} "
                f"| {len(pat.signals)} signals | {domain_str}{cross_tag}"
            )
            lines.append(f"      Entities: {ents_str}")
            lines.append(f"      Topics: {', '.join(top_topics)}")
            for s in recent:
                lines.append(f"      → [{s.source_type}] {s.headline[:100]}")
            lines.append("")

        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════════════
    #  DEEP PATTERN FUSION — Cross-Pattern Synthesis Engine
    #
    #  The unique value of this system is not detecting INDIVIDUAL patterns —
    #  it's finding CONNECTIONS BETWEEN patterns that no single-domain analyst
    #  would see. This method examines all active patterns pairwise, uses the
    #  EntityGraph to find hidden connections, and synthesizes compound insights
    #  via LLM that transcend what any individual pattern reveals.
    #
    #  Example: Pattern A = "Iran naval activity in Hormuz"
    #           Pattern B = "Oil futures volatility + VIX spike"
    #           EntityGraph path: Iran → OPEC → Oil → Energy Markets
    #           Synthesis: "Iran's Hormuz posturing is creating a supply-risk
    #                       premium that's propagating through energy derivatives
    #                       into broad market volatility — this is a geopolitical
    #                       transmission mechanism, not organic market fear."
    # ══════════════════════════════════════════════════════════════════════════

    # Minimum convergence for a pattern to participate in cross-pattern synthesis
    _FUSION_MIN_CONVERGENCE = 0.35
    # Minimum number of active qualifying patterns to attempt synthesis
    _FUSION_MIN_PATTERNS = 2
    # Cooldown between synthesis runs (seconds)
    _FUSION_COOLDOWN = 900  # 15 minutes
    # Max pattern pairs to evaluate per synthesis cycle (LLM budget control)
    _FUSION_MAX_PAIRS = 6
    # Dedup: track recent synthesis hashes to avoid repeating the same insight
    _FUSION_DEDUP_WINDOW = 20

    def __init_fusion_state(self) -> None:
        """Lazy initialization of fusion state — called on first synthesis."""
        if not hasattr(self, "_fusion_last_run"):
            self._fusion_last_run: float = 0.0
            self._fusion_total_synthesized: int = 0
            self._fusion_recent_hashes: deque = deque(maxlen=self._FUSION_DEDUP_WINDOW)

    def synthesize_cross_patterns(self) -> list[dict]:
        """Run one cycle of cross-pattern synthesis.

        Examines all active patterns above convergence threshold.
        Finds pairs via TWO complementary methods:
          1. Entity Graph Paths — structural connections through shared entities
          2. Thematic Bridges — meta-theme connections WITHOUT shared entities
             (e.g., AI/job loss + Iran/fuel = convergent pressure on population)

        Returns list of synthesis results (each may generate a notification).
        Called periodically from the background loop.
        """
        self.__init_fusion_state()

        now = time.time()
        if (now - self._fusion_last_run) < self._FUSION_COOLDOWN:
            return []
        self._fusion_last_run = now

        # Gather qualifying active patterns
        alive = [
            p for p in self._patterns
            if p.is_alive(now) and p.convergence_score >= self._FUSION_MIN_CONVERGENCE
        ]

        if len(alive) < self._FUSION_MIN_PATTERNS:
            return []

        entity_graph = self.engine.entity_graph

        logger.info(
            "[DeepFusion] Starting synthesis cycle — %d qualifying patterns",
            len(alive),
        )

        # Classify domains AND compute theme fingerprints for each pattern
        pattern_domains: dict[str, set[str]] = {}
        pattern_themes: dict[str, dict[str, float]] = {}
        for p in alive:
            pattern_domains[p.id] = _classify_pattern_domains(p)
            pattern_themes[p.id] = _compute_theme_fingerprint(p)

        # Generate candidate pairs via TWO methods
        candidates: list[tuple[EmergentPattern, EmergentPattern, list[dict], list[dict]]] = []
        # Each candidate: (pat_a, pat_b, entity_graph_paths, thematic_bridges)

        for i, pat_a in enumerate(alive):
            if len(candidates) >= self._FUSION_MAX_PAIRS:
                break
            for pat_b in alive[i + 1:]:
                if len(candidates) >= self._FUSION_MAX_PAIRS:
                    break

                domains_a = pattern_domains[pat_a.id]
                domains_b = pattern_domains[pat_b.id]

                # Require different primary domains (cross-domain connection)
                if domains_a == domains_b:
                    continue

                # Dedup check
                pair_key = "~".join(sorted([pat_a.id, pat_b.id]))
                if pair_key in self._fusion_recent_hashes:
                    continue

                # Method 1: Entity graph paths (structural connection)
                graph_paths: list[dict] = []
                if entity_graph:
                    graph_paths = entity_graph.find_connecting_paths(
                        pat_a.core_entities,
                        pat_b.core_entities,
                        max_depth=3,
                        max_paths=3,
                    )

                # Method 2: Thematic bridges (semantic connection)
                fp_a = pattern_themes.get(pat_a.id, {})
                fp_b = pattern_themes.get(pat_b.id, {})
                thematic_bridges = _find_thematic_bridge(fp_a, fp_b)

                # Need at least ONE connection method
                if not graph_paths and not thematic_bridges:
                    continue

                candidates.append((pat_a, pat_b, graph_paths, thematic_bridges))

                # Log the connection type for debugging
                conn_types = []
                if graph_paths:
                    conn_types.append(f"{len(graph_paths)} graph paths")
                if thematic_bridges:
                    bridge_names = [
                        b.get("theme", "+".join(b.get("themes", [])))
                        for b in thematic_bridges[:2]
                    ]
                    conn_types.append(f"themes: {','.join(bridge_names)}")

                logger.info(
                    "[DeepFusion] Candidate pair: %s(%s) ↔ %s(%s) via %s",
                    ",".join(sorted(pat_a.core_entities)[:3]),
                    "+".join(sorted(domains_a)),
                    ",".join(sorted(pat_b.core_entities)[:3]),
                    "+".join(sorted(domains_b)),
                    " + ".join(conn_types),
                )

        if not candidates:
            logger.debug("[DeepFusion] No cross-domain pattern pairs found")
            return []

        # Synthesize each candidate pair via LLM
        results: list[dict] = []
        for pat_a, pat_b, paths, bridges in candidates:
            try:
                synthesis = self._synthesize_pair(pat_a, pat_b, paths, bridges)
                if synthesis:
                    pair_key = "~".join(sorted([pat_a.id, pat_b.id]))
                    self._fusion_recent_hashes.append(pair_key)
                    self._fusion_total_synthesized += 1
                    results.append(synthesis)
            except Exception as exc:
                logger.warning("[DeepFusion] Synthesis failed for pair: %s", exc)

        # ── Macro Pattern Synthesis: N-pattern theme clustering ──
        macro_results = self._synthesize_macro_patterns(alive, pattern_themes, pattern_domains)
        results.extend(macro_results)

        if results:
            logger.info(
                "[DeepFusion] Synthesis cycle complete — %d insights generated "
                "(total lifetime: %d)",
                len(results), self._fusion_total_synthesized,
            )

        return results

    def _synthesize_pair(
        self,
        pat_a: EmergentPattern,
        pat_b: EmergentPattern,
        graph_paths: list[dict],
        thematic_bridges: list[dict] | None = None,
    ) -> dict | None:
        """Synthesize a compound insight from two connected patterns.

        Uses LLM to analyze what the COMBINATION of patterns reveals
        that neither individually shows. Includes both entity graph paths
        AND thematic bridges as structural evidence.

        Returns synthesis dict or None if LLM judges no novel insight.
        """
        thematic_bridges = thematic_bridges or []
        domains_a = sorted(_classify_pattern_domains(pat_a))
        domains_b = sorted(_classify_pattern_domains(pat_b))
        all_domains = sorted(set(domains_a) | set(domains_b))

        # Build entity neighborhood context for deeper structural understanding
        all_core_entities = sorted((pat_a.core_entities | pat_b.core_entities))[:12]
        neighborhood_ctx = ""
        if self.engine.entity_graph:
            neighborhood = self.engine.entity_graph.get_entity_neighborhood(
                all_core_entities, max_neighbors=5,
            )
            if neighborhood:
                nbr_lines = []
                for entity, neighbors in neighborhood.items():
                    if neighbors:
                        conns = ", ".join(
                            f"{n['entity']}({n['relationship']}, w={n['strength']})"
                            for n in neighbors[:4]
                        )
                        nbr_lines.append(f"  {entity} → {conns}")
                if nbr_lines:
                    neighborhood_ctx = (
                        "\n\nENTITY GRAPH NEIGHBORHOOD:\n"
                        + "\n".join(nbr_lines)
                    )

        # Build graph path descriptions
        path_descriptions = []
        for p in graph_paths:
            if p.get("shared_entities"):
                path_descriptions.append(
                    f"  SHARED entities: {', '.join(p['shared_entities'])}"
                )
            else:
                chain = " → ".join(p["path"])
                edge_details = []
                for edge in p.get("path_edges", []):
                    evidence = edge.get("evidence", [])
                    ev_str = f" [{evidence[0][:60]}]" if evidence else ""
                    edge_details.append(
                        f"    {edge['from']} →({edge['rel']}, w={edge['weight']}) {edge['to']}{ev_str}"
                    )
                path_descriptions.append(
                    f"  PATH: {chain} (total_weight={p['total_weight']}, depth={p['depth']})\n"
                    + "\n".join(edge_details)
                )

        paths_text = "\n".join(path_descriptions) if path_descriptions else "No direct entity graph path"

        # Build thematic bridge descriptions
        bridge_text = ""
        if thematic_bridges:
            bridge_lines = ["THEMATIC BRIDGES (meta-theme connections beyond entity overlap):"]
            for b in thematic_bridges[:4]:
                if b["type"] == "convergent":
                    bridge_lines.append(
                        f"  ★ CONVERGENT THEME: {b['theme'].replace('_', ' ').upper()} "
                        f"(strength={b['strength']}) — {b['narrative']}"
                    )
                else:
                    themes_str = " + ".join(
                        t.replace("_", " ").upper() for t in b.get("themes", [])
                    )
                    bridge_lines.append(
                        f"  ★ BRIDGE: {themes_str} (strength={b['strength']})"
                        f"\n    → {b['narrative']}"
                    )
            bridge_text = "\n" + "\n".join(bridge_lines)

        # Recent headlines from each pattern
        recent_a = sorted(pat_a.signals, key=lambda s: s.timestamp, reverse=True)[:6]
        recent_b = sorted(pat_b.signals, key=lambda s: s.timestamp, reverse=True)[:6]

        headlines_a = "\n".join(f"  [{s.source_type}] {s.headline[:120]}" for s in recent_a)
        headlines_b = "\n".join(f"  [{s.source_type}] {s.headline[:120]}" for s in recent_b)

        prompt_context = (
            f"PATTERN A — Domains: {', '.join(domains_a)}\n"
            f"Convergence: {pat_a.convergence_score:.2f} | Signals: {len(pat_a.signals)}\n"
            f"Core entities: {', '.join(sorted(pat_a.core_entities)[:8])}\n"
            f"Key topics: {', '.join(sorted(pat_a.topics)[:10])}\n"
            f"Recent signals:\n{headlines_a}\n\n"
            f"PATTERN B — Domains: {', '.join(domains_b)}\n"
            f"Convergence: {pat_b.convergence_score:.2f} | Signals: {len(pat_b.signals)}\n"
            f"Core entities: {', '.join(sorted(pat_b.core_entities)[:8])}\n"
            f"Key topics: {', '.join(sorted(pat_b.topics)[:10])}\n"
            f"Recent signals:\n{headlines_b}\n\n"
            f"ENTITY GRAPH CONNECTIONS (how these patterns link through real entities):\n{paths_text}"
            f"{bridge_text}"
            f"{neighborhood_ctx}"
        )

        try:
            result = self.engine.llm.call_json(
                _CROSS_PATTERN_SYNTHESIS_PROMPT,
                prompt_context,
                max_tokens=1200,
                temperature=0.4,
            )
        except Exception as exc:
            logger.warning("[DeepFusion] LLM synthesis call failed: %s", exc)
            return None

        # LLM may judge no novel compound insight exists
        if not result.get("has_compound_insight", False):
            logger.debug(
                "[DeepFusion] No compound insight for %s ↔ %s: %s",
                pat_a.id, pat_b.id, result.get("reason", "?"),
            )
            return None

        synthesis = {
            "type": "cross_pattern_synthesis",
            "pattern_a_id": pat_a.id,
            "pattern_b_id": pat_b.id,
            "domains": all_domains,
            "domain_count": len(all_domains),
            "headline": result.get("headline", "Cross-domain pattern detected")[:120],
            "compound_insight": result.get("compound_insight", ""),
            "causal_chain": result.get("causal_chain", ""),
            "second_order_effects": result.get("second_order_effects", []),
            "confidence": result.get("confidence", 0.5),
            "graph_paths": [
                {"path": p["path"], "weight": p["total_weight"]}
                for p in graph_paths
            ],
            "thematic_bridges": [
                {"themes": b.get("themes", [b.get("theme", "?")]),
                 "type": b["type"], "strength": b["strength"]}
                for b in thematic_bridges[:3]
            ],
            "connection_type": (
                "entity+theme" if graph_paths and thematic_bridges
                else "entity" if graph_paths
                else "thematic"
            ),
            "combined_convergence": round(
                (pat_a.convergence_score + pat_b.convergence_score) / 2, 3
            ),
            "combined_signals": len(pat_a.signals) + len(pat_b.signals),
            "core_entities": all_core_entities,
            "synthesized_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "[DeepFusion] COMPOUND INSIGHT: %s | Domains: %s | Confidence: %.2f | "
            "Patterns: %s(%d signals) + %s(%d signals)",
            synthesis["headline"],
            "+".join(all_domains),
            synthesis["confidence"],
            pat_a.id, len(pat_a.signals),
            pat_b.id, len(pat_b.signals),
        )

        # Persist to MongoDB
        if self.engine._mongo:
            try:
                self.engine._mongo.log_journal("pattern_synthesis", synthesis)
            except Exception:
                pass

        # Fire notification if confidence is sufficient
        if synthesis["confidence"] >= 0.6:
            self._fire_synthesis(synthesis)

        return synthesis

    def _fire_synthesis(self, synthesis: dict) -> None:
        """Deliver a compound insight as a high-priority notification.

        Compound insights are cross-domain by definition — they represent
        the system's highest-value output.
        """
        event_data = {
            "pattern_ids": [synthesis["pattern_a_id"], synthesis["pattern_b_id"]],
            "domains": synthesis["domains"],
            "cross_domain": True,
            "domain_count": synthesis["domain_count"],
            "compound_insight": synthesis["compound_insight"],
            "causal_chain": synthesis["causal_chain"],
            "second_order_effects": synthesis["second_order_effects"],
            "confidence": synthesis["confidence"],
            "graph_paths": synthesis["graph_paths"],
            "combined_convergence": synthesis["combined_convergence"],
            "combined_signals": synthesis["combined_signals"],
            "core_entities": synthesis["core_entities"],
            "headlines": [],  # populated from compound insight
            "convergence_score": synthesis["combined_convergence"],
        }

        context = (
            f"CROSS-PATTERN SYNTHESIS — {synthesis['domain_count']} domains\n\n"
            f"COMPOUND INSIGHT:\n{synthesis['compound_insight']}\n\n"
            f"CAUSAL CHAIN:\n{synthesis['causal_chain']}\n\n"
            f"SECOND-ORDER EFFECTS:\n"
            + "\n".join(f"  - {e}" for e in synthesis.get("second_order_effects", []))
            + f"\n\nGRAPH CONNECTIONS:\n"
            + "\n".join(
                f"  {' → '.join(p['path'])} (weight={p['weight']})"
                for p in synthesis["graph_paths"]
            )
        )

        self.engine._eval_pool.submit(
            self.engine.evaluate_and_notify,
            "cross_pattern_synthesis",
            event_data,
            context,
        )

        # ── Hypothesis Engine: auto-generate from synthesis insight ──
        if self.engine.hypothesis_engine:
            try:
                hyp = self.engine.hypothesis_engine.generate_from_synthesis(synthesis)
                if hyp:
                    logger.info("[DeepFusion] Hypothesis generated from synthesis: %s",
                                hyp.hypothesis_text[:80])
            except Exception as exc:
                logger.debug("[DeepFusion] Hypothesis generation from synthesis failed: %s", exc)

    def get_fusion_stats(self) -> dict:
        """Return deep fusion statistics."""
        self.__init_fusion_state()
        return {
            "total_synthesized": self._fusion_total_synthesized,
            "macro_patterns": len(getattr(self, "_macro_pattern_history", [])),
            "recent_hashes": len(self._fusion_recent_hashes),
            "last_run": datetime.fromtimestamp(
                self._fusion_last_run, tz=timezone.utc
            ).isoformat() if self._fusion_last_run > 0 else "never",
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  MACRO PATTERN SYNTHESIS — N-pattern theme clustering
    #
    #  While pairwise synthesis finds connections between 2 patterns,
    #  macro synthesis finds SYSTEM-LEVEL narratives from 3+ patterns
    #  that converge on the same meta-theme.
    #
    #  Example: The user's insight was exactly this:
    #    Pattern 1: Musk/Amodei talking about AI job extinction
    #    Pattern 2: Iran war → fuel costs → food prices
    #    Pattern 3: Ceasefire → broader military engagement
    #    → MACRO: "Convergent pressure on population sustainability —
    #             resources shrink (war), jobs vanish (AI), conflict expands"
    # ══════════════════════════════════════════════════════════════════════════

    _MACRO_MIN_PATTERNS = 3       # Minimum patterns to form a macro cluster
    _MACRO_MAX_PER_CYCLE = 3      # Max macro insights per cycle (LLM budget)
    _MACRO_COOLDOWN = 1800        # 30 minutes between macro cycles
    _MACRO_DEDUP_WINDOW = 10      # Recent macro hashes to prevent duplicates

    def __init_macro_state(self) -> None:
        """Lazy initialization of macro pattern state."""
        if not hasattr(self, "_macro_last_run"):
            self._macro_last_run: float = 0.0
            self._macro_total: int = 0
            self._macro_recent_hashes: deque = deque(maxlen=self._MACRO_DEDUP_WINDOW)
            self._macro_pattern_history: list[dict] = []  # Recent macro patterns

    def _synthesize_macro_patterns(
        self,
        alive: list[EmergentPattern],
        pattern_themes: dict[str, dict[str, float]],
        pattern_domains: dict[str, set[str]],
    ) -> list[dict]:
        """Find N-pattern clusters sharing meta-themes and synthesize macro narratives.

        Groups patterns by their strongest meta-theme. If 3+ patterns
        converge on the same theme from DIFFERENT domains, that's a
        system-level signal worth synthesizing.

        Returns list of macro synthesis dicts.
        """
        self.__init_macro_state()

        now = time.time()
        if (now - self._macro_last_run) < self._MACRO_COOLDOWN:
            return []
        self._macro_last_run = now

        if len(alive) < self._MACRO_MIN_PATTERNS:
            return []

        # Group patterns by meta-theme
        theme_clusters: dict[str, list[EmergentPattern]] = {}
        for pat in alive:
            fp = pattern_themes.get(pat.id, {})
            for theme_name, strength in fp.items():
                if strength >= 0.15:  # minimum theme match
                    if theme_name not in theme_clusters:
                        theme_clusters[theme_name] = []
                    theme_clusters[theme_name].append(pat)

        # Filter: need 3+ patterns from 2+ different domains
        macro_candidates: list[tuple[str, list[EmergentPattern]]] = []
        for theme_name, patterns in theme_clusters.items():
            if len(patterns) < self._MACRO_MIN_PATTERNS:
                continue

            # Check domain diversity
            all_domains = set()
            for pat in patterns:
                all_domains |= pattern_domains.get(pat.id, set())
            if len(all_domains) < 2:
                continue

            # Dedup
            cluster_key = f"macro:{theme_name}:" + "+".join(
                sorted(p.id for p in patterns[:5])
            )
            if cluster_key in self._macro_recent_hashes:
                continue

            macro_candidates.append((theme_name, patterns))

        if not macro_candidates:
            return []

        # Sort by cluster size × theme weight (biggest/heaviest first)
        macro_candidates.sort(
            key=lambda x: len(x[1]) * _META_THEMES.get(x[0], {}).get("weight", 0.5),
            reverse=True,
        )

        results: list[dict] = []
        for theme_name, patterns in macro_candidates[:self._MACRO_MAX_PER_CYCLE]:
            try:
                macro = self._synthesize_macro_cluster(theme_name, patterns, pattern_domains)
                if macro:
                    cluster_key = f"macro:{theme_name}:" + "+".join(
                        sorted(p.id for p in patterns[:5])
                    )
                    self._macro_recent_hashes.append(cluster_key)
                    self._macro_total += 1
                    self._macro_pattern_history.append(macro)
                    # Keep history bounded
                    self._macro_pattern_history = self._macro_pattern_history[-50:]
                    results.append(macro)
            except Exception as exc:
                logger.warning("[MacroSynthesis] Failed for theme %s: %s", theme_name, exc)

        if results:
            logger.info(
                "[MacroSynthesis] %d macro patterns synthesized (total: %d)",
                len(results), self._macro_total,
            )

        return results

    def _synthesize_macro_cluster(
        self,
        theme_name: str,
        patterns: list[EmergentPattern],
        pattern_domains: dict[str, set[str]],
    ) -> dict | None:
        """Synthesize a macro-level narrative from N converging patterns."""
        # Build context for each pattern (condensed)
        pattern_summaries = []
        all_domains: set[str] = set()
        all_entities: set[str] = set()
        total_signals = 0

        for i, pat in enumerate(patterns[:6]):  # Cap at 6 patterns for prompt size
            domains = sorted(pattern_domains.get(pat.id, set()))
            all_domains |= set(domains)
            all_entities |= pat.core_entities
            total_signals += len(pat.signals)

            recent = sorted(pat.signals, key=lambda s: s.timestamp, reverse=True)[:3]
            headlines = "; ".join(s.headline[:80] for s in recent)

            pattern_summaries.append(
                f"  PATTERN {i+1} [{','.join(domains)}] "
                f"(convergence={pat.convergence_score:.2f}, signals={len(pat.signals)})\n"
                f"    Entities: {', '.join(sorted(pat.core_entities)[:6])}\n"
                f"    Headlines: {headlines}"
            )

        # Find all thematic bridges between patterns in the cluster
        bridge_lines = []
        theme_data = _META_THEMES.get(theme_name, {})
        bridge_lines.append(
            f"CONVERGING META-THEME: {theme_name.replace('_', ' ').upper()} "
            f"(weight={theme_data.get('weight', 0.5)})"
        )

        # Check known bridges between all domains
        domain_list = sorted(all_domains)
        for i, d_a in enumerate(domain_list):
            for d_b in domain_list[i+1:]:
                # Map domain names to theme names for bridge lookup
                # (domains are GEOPOLITICAL/ECONOMIC/etc, themes are military_escalation/etc)
                pass  # Bridges are at theme level, already captured

        prompt = (
            f"META-THEME: {theme_name.replace('_', ' ').upper()}\n"
            f"PATTERN COUNT: {len(patterns)} patterns from {len(all_domains)} domains\n"
            f"DOMAINS: {', '.join(sorted(all_domains))}\n\n"
            f"CONVERGING PATTERNS:\n"
            + "\n".join(pattern_summaries)
            + f"\n\nKEY ENTITIES: {', '.join(sorted(all_entities)[:15])}\n"
        )

        try:
            result = self.engine.llm.call_json(
                _MACRO_PATTERN_SYNTHESIS_PROMPT,
                prompt,
                max_tokens=1500,
                temperature=0.4,
            )
        except Exception as exc:
            logger.warning("[MacroSynthesis] LLM call failed: %s", exc)
            return None

        if not result.get("has_macro_insight", False):
            logger.debug("[MacroSynthesis] No macro insight for theme %s", theme_name)
            return None

        macro = {
            "type": "macro_pattern",
            "theme": theme_name,
            "pattern_count": len(patterns),
            "pattern_ids": [p.id for p in patterns[:6]],
            "domains": sorted(all_domains),
            "domain_count": len(all_domains),
            "headline": result.get("headline", f"Macro: {theme_name}")[:120],
            "macro_narrative": result.get("macro_narrative", ""),
            "convergence_mechanism": result.get("convergence_mechanism", ""),
            "transmission_chains": result.get("transmission_chains", []),
            "who_benefits": result.get("who_benefits", ""),
            "who_loses": result.get("who_loses", ""),
            "what_to_watch": result.get("what_to_watch", []),
            "systemic_risk_level": result.get("systemic_risk_level", "medium"),
            "confidence": result.get("confidence", 0.5),
            "total_signals": total_signals,
            "core_entities": sorted(all_entities)[:15],
            "synthesized_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "[MacroSynthesis] MACRO PATTERN: %s | Theme: %s | %d patterns, %d domains | "
            "Risk: %s | Confidence: %.2f",
            macro["headline"], theme_name, len(patterns),
            len(all_domains), macro["systemic_risk_level"], macro["confidence"],
        )

        # Persist
        if self.engine._mongo:
            try:
                self.engine._mongo.log_journal("macro_patterns", macro)
            except Exception:
                pass

        # Fire high-priority notification for high-confidence macro patterns
        if macro["confidence"] >= 0.55:
            self._fire_macro(macro)

        return macro

    def _fire_macro(self, macro: dict) -> None:
        """Deliver a macro pattern insight as a high-priority notification."""
        context = (
            f"MACRO PATTERN — {macro['theme'].replace('_', ' ').upper()}\n"
            f"{macro['pattern_count']} patterns across {macro['domain_count']} domains "
            f"({', '.join(macro['domains'])})\n\n"
            f"NARRATIVE:\n{macro['macro_narrative']}\n\n"
            f"CONVERGENCE MECHANISM:\n{macro['convergence_mechanism']}\n\n"
            f"TRANSMISSION CHAINS:\n"
            + "\n".join(f"  → {c}" for c in macro.get("transmission_chains", []))
            + f"\n\nWHO BENEFITS: {macro.get('who_benefits', '?')}"
            f"\nWHO LOSES: {macro.get('who_loses', '?')}"
            f"\n\nWATCH FOR:\n"
            + "\n".join(f"  ⚠ {w}" for w in macro.get("what_to_watch", []))
        )

        self.engine._eval_pool.submit(
            self.engine.evaluate_and_notify,
            "macro_pattern",
            {
                "theme": macro["theme"],
                "headline": macro["headline"],
                "domains": macro["domains"],
                "cross_domain": True,
                "domain_count": macro["domain_count"],
                "macro_narrative": macro["macro_narrative"],
                "confidence": macro["confidence"],
                "systemic_risk_level": macro["systemic_risk_level"],
                "pattern_count": macro["pattern_count"],
                "core_entities": macro["core_entities"],
                "convergence_score": macro["confidence"],
            },
            context,
        )

    def get_macro_pattern_digest(self) -> str:
        """Formatted macro pattern intelligence for Live Digest injection.

        Returns a text block suitable for injection into pipeline/chat context.
        Shows recent macro patterns that Αίολος can reference.
        """
        self.__init_macro_state()
        if not self._macro_pattern_history:
            return ""

        now = time.time()
        recent = [
            m for m in self._macro_pattern_history
            if m.get("synthesized_at") and
            (now - datetime.fromisoformat(m["synthesized_at"]).timestamp()) < 86400
        ]
        if not recent:
            return ""

        lines = [
            "▸ MACRO PATTERN INTELLIGENCE (system-level cross-domain narratives)"
        ]
        for m in recent[-3:]:
            risk_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                m.get("systemic_risk_level", "medium"), "⚪"
            )
            lines.append(
                f"  {risk_icon} [{m['theme'].replace('_', ' ').upper()}] "
                f"{m['headline']} "
                f"({m['pattern_count']} patterns, {m['domain_count']} domains, "
                f"conf={m['confidence']:.2f})"
            )
            if m.get("macro_narrative"):
                # First sentence only for digest
                first_sentence = m["macro_narrative"].split(".")[0] + "."
                lines.append(f"    → {first_sentence[:150]}")
            if m.get("what_to_watch"):
                lines.append(f"    ⚠ Watch: {m['what_to_watch'][0][:100]}")

        lines.append("")
        return "\n".join(lines)

    def get_synthesis_digest(self) -> str:
        """Combined digest of ALL synthesis outputs (pairwise + macro).

        Returns formatted text for Live Digest / pipeline injection.
        """
        self.__init_fusion_state()
        self.__init_macro_state()

        parts: list[str] = []

        # Pairwise synthesis digest
        if hasattr(self, "_fusion_total_synthesized") and self._fusion_total_synthesized > 0:
            # Get recent pairwise results from MongoDB or in-memory
            # For now, we rely on _fire_synthesis having delivered them
            # The compound insight text is already in notifications
            pass

        # Macro pattern digest
        macro_text = self.get_macro_pattern_digest()
        if macro_text:
            parts.append(macro_text)

        return "\n".join(parts)


# ── Cross-Pattern Synthesis LLM Prompt ──
_CROSS_PATTERN_SYNTHESIS_PROMPT = """You are the DEEP PATTERN FUSION engine of an autonomous intelligence system.

You are given TWO active patterns from different domains, plus TWO types of structural evidence:

1. ENTITY GRAPH CONNECTIONS: structural links through a knowledge graph of real-world entities.
   These show how the patterns connect through shared or related entities.

2. THEMATIC BRIDGES: meta-theme connections where patterns share NO entities but converge
   on the same underlying dynamic (e.g., "AI automation kills jobs" + "Iran war raises fuel costs"
   both feed into RESOURCE_SCARCITY / POPULATION_PRESSURE — convergent pressure on humanity).
   These are the MOST VALUABLE connections because they are invisible to entity-only analysis.

YOUR TASK:
Analyze whether the COMBINATION of these two patterns reveals a COMPOUND INSIGHT
that NEITHER pattern alone would reveal. This is second-order reasoning —
finding what emerges from the intersection, not what's obvious from each part.

WHAT MAKES A COMPOUND INSIGHT:
- A causal transmission mechanism (geopolitical event → economic consequence → market impact)
- A hidden feedback loop (A causes B, B amplifies A — creating an accelerating dynamic)
- A temporal sequence prediction (if Pattern A continues, Pattern B will intensify because...)
- A structural vulnerability exposed by the combination (supply chain → political → financial)
- A THEMATIC CONVERGENCE: seemingly unrelated events that create compound pressure on the
  same population/system/resource (this is the most sophisticated form of insight)
- A counter-narrative: the combination suggests the conventional interpretation is WRONG

WHAT IS NOT A COMPOUND INSIGHT:
- Simply restating both patterns side by side
- Obvious connections anyone can see (war → oil prices → markets)
- Generic "these are related" observations without specific mechanism

Use ALL available structural evidence — entity graph paths show direct co-occurrence relationships,
thematic bridges show deeper narrative connections. The best insights weave both together.

Output ONLY valid JSON:
{
  "has_compound_insight": true/false,
  "reason": "Why this combination does/doesn't produce novel insight",
  "headline": "Concise title for the compound insight (≤80 chars)",
  "compound_insight": "3-5 sentences describing what the COMBINATION uniquely reveals. Be specific about the mechanism. Name entities and explain the transmission chain.",
  "causal_chain": "A → B → C → D format showing the causal/transmission path",
  "second_order_effects": ["Effect 1 that follows from the compound insight", "Effect 2", ...],
  "confidence": 0.0-1.0
}

Rules:
- Set has_compound_insight=false if the connection is trivial or obvious
- confidence ≥ 0.8 = clear causal mechanism with structural evidence
- confidence 0.6-0.8 = plausible mechanism, partial evidence
- confidence < 0.6 = speculative, weak connection
- THEMATIC BRIDGE connections warrant confidence BOOST of +0.1 when mechanism is clear
- Be SPECIFIC. Name entities, countries, mechanisms. No vague generalities.
- second_order_effects should be PREDICTIONS — what happens next if this insight is correct."""


# ── Macro Pattern Synthesis Prompt ──
_MACRO_PATTERN_SYNTHESIS_PROMPT = """You are the MACRO INTELLIGENCE SYNTHESIS engine of an autonomous geopolitical intelligence system.

You are given N patterns (3+) from different domains that ALL converge on the same META-THEME.
This is SYSTEM-LEVEL analysis — not pairwise connection, but the BIG PICTURE.

YOUR TASK:
Determine whether these converging patterns reveal a MACRO-LEVEL narrative —
a systemic dynamic that none of the patterns individually expose.

Think like a strategic intelligence analyst:
- What SYSTEM is under stress?
- What FEEDBACK LOOPS are forming between these patterns?
- Who BENEFITS from this convergence? Who LOSES?
- What are the TRANSMISSION CHAINS between domains?
- What TIPPING POINTS or phase transitions might be approaching?

EXAMPLE of excellent macro insight:
  Theme: POPULATION_PRESSURE
  Patterns: AI/automation job fears + fuel/food inflation from conflict + military expansion
  Macro insight: "Three independent forces — technological displacement, resource scarcity from
  conflict, and military budget reallocation — are converging to squeeze the global middle class
  from ALL directions simultaneously. Each force alone is manageable; the combination creates
  systemic fragility as governments must choose between military spending, social safety nets,
  and technological investment. Watch for: social unrest in countries facing all three pressures."

Output ONLY valid JSON:
{
  "has_macro_insight": true/false,
  "reason": "Why this convergence does/doesn't produce macro insight",
  "headline": "Concise macro-level headline (≤100 chars)",
  "macro_narrative": "5-8 sentences describing the system-level dynamic. Be specific about HOW the patterns interact and amplify each other. Name countries, entities, mechanisms.",
  "convergence_mechanism": "2-3 sentences explaining WHY these patterns are converging NOW — what underlying force or event links them",
  "transmission_chains": ["Domain A → Domain B via mechanism X", "Domain B → Domain C via mechanism Y", ...],
  "who_benefits": "Specific actors/entities/countries that benefit from this convergence",
  "who_loses": "Specific actors/entities/countries that are harmed",
  "what_to_watch": ["Specific indicator 1 to monitor", "Specific indicator 2", "Specific indicator 3"],
  "systemic_risk_level": "low" | "medium" | "high" | "critical",
  "confidence": 0.0-1.0
}

Rules:
- Set has_macro_insight=false if patterns are only superficially related
- systemic_risk_level=critical: convergence threatens state stability or market collapse
- systemic_risk_level=high: convergence affects millions, creates feedback loops
- systemic_risk_level=medium: convergence is real but manageable, worth monitoring
- systemic_risk_level=low: convergence exists but effects are localized or slow
- what_to_watch items must be SPECIFIC and OBSERVABLE — not vague generalities
- transmission_chains must name the domains AND the mechanism connecting them"""


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


# ══════════════════════════════════════════════════════════════
#  HYPOTHESIS LLM PROMPTS — generation and verification
# ══════════════════════════════════════════════════════════════

_HYPOTHESIS_GENERATION_PROMPT = """You are the HYPOTHESIS GENERATOR of Αίολος, an autonomous intelligence system.

You are given pattern intelligence (either a fired pattern or a cross-pattern synthesis).
Your task: determine whether this intelligence warrants a TESTABLE HYPOTHESIS —
a conditional prediction in the form "IF [trigger condition] THEN [expected outcome]".

A hypothesis is warranted when:
  - The pattern implies a CAUSAL or CONDITIONAL relationship (A → B)
  - Both the trigger and outcome are OBSERVABLE from news/data signals
  - The timeframe is specific enough to be falsifiable (7-90 days)
  - The hypothesis would be USEFUL for strategic monitoring

A hypothesis is NOT warranted when:
  - The pattern is a simple factual report with no predictive element
  - The trigger and outcome are too vague to monitor
  - The relationship is already consensus knowledge
  - There is no meaningful timeframe for verification

For keywords: choose SPECIFIC terms that would appear in headlines about the trigger/outcome.
Use 3-8 keywords per side. Prefer proper nouns, specific policy terms, and measurable indicators.

For entities: list the key actors, organizations, or locations involved.

Respond ONLY with valid JSON:
{{
    "generate_hypothesis": true|false,
    "reasoning": "Why this does/doesn't warrant a hypothesis",
    "hypothesis": "IF [trigger condition] THEN [expected outcome] within [timeframe]",
    "trigger_condition": "The observable trigger event (clear, specific)",
    "expected_outcome": "The expected consequence (clear, measurable)",
    "trigger_keywords": ["keyword1", "keyword2", "keyword3"],
    "outcome_keywords": ["keyword1", "keyword2", "keyword3"],
    "trigger_entities": ["Entity1", "Entity2"],
    "outcome_entities": ["Entity1", "Entity2"],
    "timeframe_days": 30,
    "confidence": 0.5
}}

If generate_hypothesis is false, set all other fields to empty/zero.
"""

_HYPOTHESIS_VERIFICATION_PROMPT = """You are the HYPOTHESIS JUDGE of Αίολος, an autonomous intelligence system.

You are given a hypothesis and accumulated evidence from real-time signal monitoring.
Your task: judge whether the evidence CONFIRMS, DISCONFIRMS, or is INSUFFICIENT to judge.

Rules:
  - CONFIRMED: Both trigger AND outcome have clear real-world evidence.
    The causal/conditional relationship described in the hypothesis is supported.
  - DISCONFIRMED: The trigger occurred but the outcome clearly did NOT follow,
    OR evidence directly contradicts the hypothesis.
  - INSUFFICIENT: Not enough evidence yet. Continue monitoring.

Be STRICT with confirmation — coincidental keyword matches are NOT confirmation.
The evidence must genuinely support the causal/conditional claim.

Respond ONLY with valid JSON:
{{
    "judgment": "confirmed" | "disconfirmed" | "insufficient",
    "reasoning": "Detailed explanation of your judgment (2-4 sentences)",
    "final_confidence": 0.0-1.0
}}
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

        # Compound Alert Chains — second-order pattern detection
        self.compound_alerts = CompoundAlertEngine()

        # Hypothesis Engine — persistent "if X then Y" conditional tracking
        self.hypothesis_engine = HypothesisEngine(self)

        # External new-gen components (set by api.py after init)
        self._multimodal_collector = None   # MultimodalCollector
        self._realtime_feeds = None         # RealtimeFeedManager
        self._sanctions_registry = None     # SanctionsRegistry
        self._event_calendar = None         # GeopoliticalCalendar
        self._darkwhisper_engine = None     # DarkWhisperEngine — wired by api.py for pattern resonance

        # ── Notification Batch Buffer ─────────────────────────────────────────
        # Instead of flooding Telegram with one message per pattern (every 30s),
        # we batch notifications and synthesize them every 10 items.
        #
        # EXCEPTIONS (bypass buffer → immediate delivery):
        #   • source="conversation_request" with trigger="visual_perception_arrival"
        #     (face/camera events: real-time awareness required)
        #   • urgency="critical" (existential urgency, never delayed)
        #
        # During chat, Αίολος can always see the pending batch (even if < 10)
        # via get_pending_batch() — injected into every chat context by core.py.
        self._notif_batch: list[Notification] = []      # pending undelivered notifications
        self._notif_batch_lock = threading.Lock()        # protects batch list
        self._notif_batch_size = 10                      # fire synthesis at this count
        self._notif_batch_total_flushed = 0              # lifetime stat
        self._notif_batch_interval = 1800                # periodic flush: 30 min (seconds)
        self._notif_batch_last_flush = time.monotonic()  # timestamp of last flush

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

        # Main event loop reference — set by api.py for thread-safe SSE delivery.
        # asyncio.Queue is NOT thread-safe; put_nowait() from worker threads
        # corrupts Future state and deadlocks the event loop.
        self._main_loop: asyncio.AbstractEventLoop | None = None

        # ── Concurrency controls for LLM evaluation ──
        # Semaphore limits how many evaluate_and_notify() calls can run
        # concurrently. Each call blocks for ~60-130s (LLM classification +
        # auto-research). Without a limit, 5+ concurrent patterns saturate the
        # LLM thread pool (8 workers) and starve the chat endpoint — causing
        # 191s+ delays on user messages.
        self._eval_semaphore = threading.Semaphore(2)
        # Dedicated pool for proactive evaluations — keeps Uvicorn's 40-worker
        # default executor free for HTTP requests (chat, health, etc.).
        self._eval_pool = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="proactive-eval",
        )

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

        # ── Concurrency guard: limit concurrent LLM evaluations ──
        # Each evaluation blocks for ~60-130s (LLM calls). Without a limit,
        # concurrent pattern fires saturate the LLM thread pool and starve
        # the chat endpoint. Non-blocking acquire: skip if slots are full.
        acquired = self._eval_semaphore.acquire(blocking=False)
        if not acquired:
            self._total_suppressed += 1
            label = (event_data.get("headlines", ["?"])[0][:60]
                     if event_data.get("headlines") else event_type)
            logger.info("[Proactive] THROTTLED — 2 evaluations already running, skipping: %s", label)
            return None

        try:
            return self._evaluate_and_notify_inner(event_type, event_data, context)
        finally:
            self._eval_semaphore.release()

    def _evaluate_and_notify_inner(
        self,
        event_type: str,
        event_data: dict,
        context: str = "",
    ) -> Notification | None:
        """Inner evaluation logic — always called under semaphore guard."""

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
                max_tokens=2000,
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

    def _thread_safe_sse_push(self, data: dict) -> bool:
        """Push data to all SSE subscribers — thread-safe.

        asyncio.Queue.put_nowait() is NOT thread-safe. When called from
        a worker thread (run_in_executor), it corrupts the event loop's
        internal Future state, causing deadlocks. We use call_soon_threadsafe
        to schedule the push on the event loop thread.

        Returns True if any subscriber received the data.
        """
        delivered = False
        loop = self._main_loop

        def _do_push():
            dead = []
            for q in list(self._sse_subscribers):
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                try:
                    self._sse_subscribers.remove(q)
                except ValueError:
                    pass

        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(_do_push)
                delivered = bool(self._sse_subscribers)
            except RuntimeError:
                pass  # Loop already closed
        else:
            # Fallback: direct push (only safe if called from event loop thread)
            _do_push()
            delivered = bool(self._sse_subscribers)

        return delivered

    def _push_to_sse(self, notification: Notification) -> None:
        """Push notification to all connected SSE clients."""
        data = notification.to_dict()
        if self._thread_safe_sse_push(data):
            notification.delivered_sse = True

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

    # ── Notification Batch helpers ─────────────────────────────────────────────

    def _is_bypass_notification(self, notification: Notification) -> bool:
        """Return True if this notification must bypass the batch buffer.

        Bypass conditions:
        • urgency == critical   → existential risk, never delayed
        • source == "conversation_request" with trigger=visual_perception_arrival
          → real-time face/camera event
        """
        if notification.urgency == CRITICAL:
            return True
        if (notification.source == "conversation_request"
                and notification.raw_data.get("trigger") == "visual_perception_arrival"):
            return True
        return False

    def _buffer_notification(self, notification: Notification) -> None:
        """Add a notification to the batch buffer.  Flush when full."""
        with self._notif_batch_lock:
            self._notif_batch.append(notification)
            current_size = len(self._notif_batch)

        if current_size >= self._notif_batch_size:
            # Run flush in a background thread so we don't block the caller
            self._eval_pool.submit(self._flush_notification_batch)
        else:
            logger.info("[Proactive] Batch buffer: %d/%d (next flush at %d)",
                        current_size, self._notif_batch_size, self._notif_batch_size)

    def _flush_notification_batch(self) -> None:
        """Drain the buffer and send one deep-synthesis Telegram message.

        Thread-safe: grabs the lock, drains the list, then does the LLM call
        outside the lock so the buffer is open for new items immediately.
        """
        with self._notif_batch_lock:
            if not self._notif_batch:
                return
            batch = list(self._notif_batch)
            self._notif_batch.clear()

        self._notif_batch_last_flush = time.monotonic()
        logger.info("[Proactive] Flushing batch of %d notifications → LLM synthesis", len(batch))
        self._notif_batch_total_flushed += len(batch)

        # ── LLM batch synthesis ────────────────────────────────────────────────
        now_str = datetime.now(ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d %H:%M Athens")
        items_block = "\n\n".join(
            f"[{i+1}] urgency={n.urgency} source={n.source}\n"
            f"  headline: {n.headline}\n"
            f"  summary: {n.summary[:600]}\n"
            f"  reason: {n.reason[:300]}\n"
            f"  domains: {', '.join(n.domains)}"
            for i, n in enumerate(batch)
        )

        synthesis_prompt = (
            "You are Αίολος, a Greek-speaking AI analyst. "
            "You have just accumulated a batch of intelligence notifications. "
            "Synthesize them into a single, deep analytical message for Πάνος.\n\n"
            "Requirements:\n"
            "• Identify cross-domain patterns and interconnections\n"
            "• Surface the single most important insight\n"
            "• Write in Greek, conversational but precise\n"
            "• Format for Telegram: use bold (*text*) for key terms, newlines for structure\n"
            "• Max 1200 characters total\n"
            "• End with: 'Ήρθαν {count} ειδοποιήσεις — Αίολος'\n"
        ).replace("{count}", str(len(batch)))

        synthesis_input = (
            f"Current time: {now_str}\n\n"
            f"BATCH ({len(batch)} notifications):\n\n{items_block}"
        )

        try:
            synthesis_text = self.llm.call(
                synthesis_prompt,
                synthesis_input,
                max_tokens=1200,
                temperature=0.3,
                thinking=False,
            )
        except Exception as exc:
            logger.warning("[Proactive] Batch synthesis LLM failed: %s — sending raw fallback", exc)
            synthesis_text = self._batch_fallback_text(batch)

        # Mark all batch notifications as telegram-delivered
        for n in batch:
            n.delivered_telegram = True

        # ── Send single Telegram message ──────────────────────────────────────
        self._send_telegram_text(synthesis_text, parse_mode="Markdown")
        logger.info("[Proactive] Batch Telegram sent (%d notifications merged)", len(batch))

    def _batch_fallback_text(self, batch: list) -> str:
        """Build a minimal fallback Telegram message if LLM synthesis fails."""
        lines = [f"📦 *{len(batch)} νέες ειδοποιήσεις*\n"]
        for i, n in enumerate(batch[:10], 1):
            emoji = "🚨" if n.urgency == CRITICAL else "📌" if n.urgency == IMPORTANT else "📋"
            lines.append(f"{emoji} *{n.headline}*")
        lines.append(f"\n_Αίολος · {datetime.now(ZoneInfo('Europe/Athens')).strftime('%H:%M')}_")
        return "\n".join(lines)

    def _send_telegram_text(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send arbitrary text to Telegram (used by batch flush + startup)."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return False
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    return True
                logger.warning("[Proactive] Telegram text send failed (%d): %s",
                               resp.status_code, resp.text[:200])
                return False
        except Exception as exc:
            logger.warning("[Proactive] Telegram text send error: %s", exc)
            return False

    def get_pending_batch(self) -> list[dict]:
        """Return current buffer contents (for chat context injection).

        Αίολος can see 1-9 pending notifications mid-batch.
        This is thread-safe: we take a snapshot without clearing.
        """
        with self._notif_batch_lock:
            return [n.to_dict() for n in self._notif_batch]

    def flush_batch_now(self) -> int:
        """Manually flush the batch regardless of size. Returns notification count flushed.

        Called by the REST endpoint /xdart/notifications/flush or by Αίολος during chat
        when Πάνος says "στείλε μου ό,τι έχεις".
        """
        with self._notif_batch_lock:
            count = len(self._notif_batch)
        if count == 0:
            return 0
        self._eval_pool.submit(self._flush_notification_batch)
        return count

    # ── END Notification Batch helpers ──────────────────────────────────────────

    def _deliver_immediate(self, notification: Notification) -> None:
        """Deliver a notification via SSE + Telegram (or buffer for batch).

        • SSE is always immediate (UI real-time feed)
        • Telegram: vision/critical → immediate; everything else → batch buffer
        """
        logger.info("[Proactive] %s: %s — %s",
                     notification.urgency.upper(), notification.headline, notification.reason)

        # Push to SSE with conversation_start flag — THREAD-SAFE (always immediate)
        data = notification.to_dict()
        data["conversation_start"] = True  # Tell UI to open chat with this message
        if self._thread_safe_sse_push(data):
            notification.delivered_sse = True

        # Telegram routing: bypass (vision / critical) → immediate; else → batch buffer
        if notification.urgency == CRITICAL and self._is_bypass_notification(notification):
            # Immediate delivery — critical alert or face arrival
            self._send_telegram(notification)
        elif notification.urgency in (CRITICAL, IMPORTANT, DIGEST):
            # All other notifications (including DIGEST) go to batch buffer
            self._buffer_notification(notification)

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

        # SSE: push with conversation_request flag — THREAD-SAFE
        data = notification.to_dict()
        data["conversation_start"] = True
        data["conversation_request"] = True  # distinguishes from regular alerts
        if self._thread_safe_sse_push(data):
            notification.delivered_sse = True

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

        # Step 2: Run web searches via a fresh event loop in this thread.
        # This method is always called from a worker thread (via run_in_executor),
        # so asyncio.run() safely creates a temporary event loop.
        all_results = []
        try:
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
                max_tokens=2000,
                temperature=0.3,
                thinking=False,
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
                thinking=False,
            )
        except Exception as exc:
            logger.warning("[Proactive] Message composition failed: %s", exc)
            return headline

    # ══════════════════════════════════════════════════════════════
    #  PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def _log_notification(self, notification: Notification) -> None:
        """Append notification to persistent JSONL log + MongoDB."""
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
        # Dual-write to MongoDB
        if hasattr(self, '_mongo') and self._mongo:
            try:
                self._mongo.log_journal("journal_proactive", dict(entry))
            except Exception:
                pass

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

        # Include live OSINT sensor data in digest context
        live_osint_text = ""
        if hasattr(self.engine, '_multimodal_collector') and self.engine._multimodal_collector:
            try:
                live_osint_text = "\n\n" + self.engine._multimodal_collector.get_live_digest()
            except Exception:
                pass

        summary = await loop.run_in_executor(None, lambda: self.llm.call(
            (
                "You are Αίολος. Compose a brief DAILY DIGEST for Πάνος. "
                "Summarize the key findings from the past cycle. "
                "Group by theme. Be concise — max 10 sentences. "
                "ALWAYS reference live sensor data (aircraft, ships, satellites) when available. "
                "If nothing significant happened, say so honestly."
            ),
            f"ACCUMULATED FINDINGS ({len(digests)} items):\n{items_text}{patterns_text}{live_osint_text}",
            max_tokens=600,
            temperature=0.3,
            thinking=False,
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
