"""
XDART-Φ × XHEART — Country Risk Profiles & CII Scoring

Ported from WorldMonitor (koala73/worldmonitor) countries.ts + algorithms.mdx.

31 curated Tier-1 nations with individually tuned baseline risk and event
multipliers.  All other countries use DEFAULT_BASELINE_RISK / DEFAULT_EVENT_MULTIPLIER.

CII Formula (Country Instability Index, 0-100):
    cii = baseline_component (40%) + event_component (60%)

    baseline_component = baseline_risk * 0.8   (scaled from 0-50 → 0-40)
    event_component    = weighted blend of:
        - unrest_score   (25%)  — protests, riots, outages
        - conflict_score (30%)  — ACLED battles, explosions, civilian violence
        - security_score (20%)  — GPS jamming, border incidents
        - info_score     (25%)  — news velocity, headline severity

    Floors: active_war → min 70, minor_conflict → min 50,
            do_not_travel advisory → min 60, reconsider → min 50
    Boosts: travel advisory +5/+10/+15, climate +up to 15, cyber +up to 10
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("xdart.perception.country_risk")

# ─────────────────────────────────────────────────────────────────────
# Curated Country Profiles
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CountryProfile:
    """Risk profile for a single country."""

    code: str
    name: str
    scoring_keywords: list[str]
    search_aliases: list[str]
    baseline_risk: int            # 0-50 structural fragility
    event_multiplier: float       # scales event-driven component


CURATED_COUNTRIES: dict[str, CountryProfile] = {
    "US": CountryProfile(
        code="US", name="United States",
        scoring_keywords=["united states", "usa", "america", "washington", "biden", "trump", "pentagon"],
        search_aliases=["united states", "american", "washington", "pentagon", "white house", "usa", "america", "biden", "trump"],
        baseline_risk=5, event_multiplier=0.3,
    ),
    "RU": CountryProfile(
        code="RU", name="Russia",
        scoring_keywords=["russia", "moscow", "kremlin", "putin"],
        search_aliases=["russia", "russian", "moscow", "kremlin", "putin", "ukraine war"],
        baseline_risk=35, event_multiplier=2.0,
    ),
    "CN": CountryProfile(
        code="CN", name="China",
        scoring_keywords=["china", "beijing", "xi jinping", "prc"],
        search_aliases=["china", "chinese", "beijing", "taiwan strait", "south china sea", "xi jinping"],
        baseline_risk=25, event_multiplier=2.5,
    ),
    "UA": CountryProfile(
        code="UA", name="Ukraine",
        scoring_keywords=["ukraine", "kyiv", "zelensky", "donbas"],
        search_aliases=["ukraine", "ukrainian", "kyiv", "zelensky", "zelenskyy"],
        baseline_risk=50, event_multiplier=0.8,
    ),
    "IR": CountryProfile(
        code="IR", name="Iran",
        scoring_keywords=["iran", "tehran", "khamenei", "irgc"],
        search_aliases=["iran", "iranian", "tehran", "persian", "irgc", "khamenei"],
        baseline_risk=40, event_multiplier=2.0,
    ),
    "IL": CountryProfile(
        code="IL", name="Israel",
        scoring_keywords=["israel", "tel aviv", "netanyahu", "idf", "gaza"],
        search_aliases=["israel", "israeli", "gaza", "hamas", "hezbollah", "netanyahu", "idf", "west bank", "tel aviv", "jerusalem"],
        baseline_risk=45, event_multiplier=0.7,
    ),
    "TW": CountryProfile(
        code="TW", name="Taiwan",
        scoring_keywords=["taiwan", "taipei"],
        search_aliases=["taiwan", "taiwanese", "taipei"],
        baseline_risk=30, event_multiplier=1.5,
    ),
    "KP": CountryProfile(
        code="KP", name="North Korea",
        scoring_keywords=["north korea", "pyongyang", "kim jong"],
        search_aliases=["north korea", "pyongyang", "kim jong"],
        baseline_risk=45, event_multiplier=3.0,
    ),
    "SA": CountryProfile(
        code="SA", name="Saudi Arabia",
        scoring_keywords=["saudi arabia", "riyadh", "mbs"],
        search_aliases=["saudi", "riyadh", "mbs"],
        baseline_risk=20, event_multiplier=2.0,
    ),
    "TR": CountryProfile(
        code="TR", name="Turkey",
        scoring_keywords=["turkey", "ankara", "erdogan"],
        search_aliases=["turkey", "turkish", "ankara", "erdogan", "türkiye"],
        baseline_risk=25, event_multiplier=1.2,
    ),
    "PL": CountryProfile(
        code="PL", name="Poland",
        scoring_keywords=["poland", "warsaw"],
        search_aliases=["poland", "polish", "warsaw"],
        baseline_risk=10, event_multiplier=0.8,
    ),
    "DE": CountryProfile(
        code="DE", name="Germany",
        scoring_keywords=["germany", "berlin"],
        search_aliases=["germany", "german", "berlin"],
        baseline_risk=5, event_multiplier=0.5,
    ),
    "FR": CountryProfile(
        code="FR", name="France",
        scoring_keywords=["france", "paris", "macron"],
        search_aliases=["france", "french", "paris", "macron"],
        baseline_risk=10, event_multiplier=0.6,
    ),
    "GB": CountryProfile(
        code="GB", name="United Kingdom",
        scoring_keywords=["britain", "uk", "london", "starmer"],
        search_aliases=["united kingdom", "british", "london", "uk "],
        baseline_risk=5, event_multiplier=0.5,
    ),
    "IN": CountryProfile(
        code="IN", name="India",
        scoring_keywords=["india", "delhi", "modi"],
        search_aliases=["india", "indian", "new delhi", "modi"],
        baseline_risk=20, event_multiplier=0.8,
    ),
    "PK": CountryProfile(
        code="PK", name="Pakistan",
        scoring_keywords=["pakistan", "islamabad"],
        search_aliases=["pakistan", "pakistani", "islamabad"],
        baseline_risk=35, event_multiplier=1.5,
    ),
    "SY": CountryProfile(
        code="SY", name="Syria",
        scoring_keywords=["syria", "damascus", "assad"],
        search_aliases=["syria", "syrian", "damascus", "assad"],
        baseline_risk=50, event_multiplier=0.7,
    ),
    "YE": CountryProfile(
        code="YE", name="Yemen",
        scoring_keywords=["yemen", "sanaa", "houthi"],
        search_aliases=["yemen", "houthi", "sanaa"],
        baseline_risk=50, event_multiplier=0.7,
    ),
    "MM": CountryProfile(
        code="MM", name="Myanmar",
        scoring_keywords=["myanmar", "burma", "rangoon"],
        search_aliases=["myanmar", "burmese", "burma", "rangoon"],
        baseline_risk=45, event_multiplier=1.8,
    ),
    "VE": CountryProfile(
        code="VE", name="Venezuela",
        scoring_keywords=["venezuela", "caracas", "maduro"],
        search_aliases=["venezuela", "venezuelan", "caracas", "maduro"],
        baseline_risk=40, event_multiplier=1.8,
    ),
    "BR": CountryProfile(
        code="BR", name="Brazil",
        scoring_keywords=["brazil", "brasilia", "lula", "bolsonaro"],
        search_aliases=["brazil", "brazilian", "brasilia", "lula", "bolsonaro"],
        baseline_risk=15, event_multiplier=0.6,
    ),
    "AE": CountryProfile(
        code="AE", name="United Arab Emirates",
        scoring_keywords=["uae", "emirates", "dubai", "abu dhabi"],
        search_aliases=["united arab emirates", "uae", "emirati", "dubai", "abu dhabi"],
        baseline_risk=10, event_multiplier=1.5,
    ),
    "MX": CountryProfile(
        code="MX", name="Mexico",
        scoring_keywords=["mexico", "mexican", "amlo", "sheinbaum", "cartel", "sinaloa", "jalisco", "cjng"],
        search_aliases=["mexico", "mexican", "amlo", "sheinbaum", "cartel", "sinaloa", "jalisco", "cjng", "tijuana", "juarez", "sedena", "fentanyl", "narco"],
        baseline_risk=35, event_multiplier=1.0,
    ),
    "KR": CountryProfile(
        code="KR", name="South Korea",
        scoring_keywords=["south korea", "seoul"],
        search_aliases=["south korea", "seoul"],
        baseline_risk=15, event_multiplier=1.0,
    ),
    "IQ": CountryProfile(
        code="IQ", name="Iraq",
        scoring_keywords=["iraq", "iraqi", "baghdad"],
        search_aliases=["iraq", "iraqi", "baghdad"],
        baseline_risk=35, event_multiplier=1.0,
    ),
    "AF": CountryProfile(
        code="AF", name="Afghanistan",
        scoring_keywords=["afghanistan", "afghan", "kabul", "taliban"],
        search_aliases=["afghanistan", "afghan", "kabul", "taliban"],
        baseline_risk=15, event_multiplier=1.0,
    ),
    "LB": CountryProfile(
        code="LB", name="Lebanon",
        scoring_keywords=["lebanon", "lebanese", "beirut"],
        search_aliases=["lebanon", "lebanese", "beirut"],
        baseline_risk=15, event_multiplier=1.0,
    ),
    "EG": CountryProfile(
        code="EG", name="Egypt",
        scoring_keywords=["egypt", "egyptian", "cairo", "suez"],
        search_aliases=["egypt", "egyptian", "cairo", "suez"],
        baseline_risk=15, event_multiplier=1.0,
    ),
    "JP": CountryProfile(
        code="JP", name="Japan",
        scoring_keywords=["japan", "japanese", "tokyo"],
        search_aliases=["japan", "japanese", "tokyo"],
        baseline_risk=15, event_multiplier=1.0,
    ),
    "QA": CountryProfile(
        code="QA", name="Qatar",
        scoring_keywords=["qatar", "qatari", "doha"],
        search_aliases=["qatar", "qatari", "doha"],
        baseline_risk=15, event_multiplier=1.0,
    ),
    "CU": CountryProfile(
        code="CU", name="Cuba",
        scoring_keywords=["cuba", "cuban", "havana", "diaz-canel"],
        search_aliases=["cuba", "cuban", "havana", "diaz-canel", "canel"],
        baseline_risk=45, event_multiplier=2.0,
    ),
}

# Tier-1 country codes (for quick membership checks)
TIER1_COUNTRIES: set[str] = set(CURATED_COUNTRIES.keys())

DEFAULT_BASELINE_RISK = 15
DEFAULT_EVENT_MULTIPLIER = 1.0

# ─────────────────────────────────────────────────────────────────────
# Hotspot → Country Mapping
# ─────────────────────────────────────────────────────────────────────

HOTSPOT_COUNTRY_MAP: dict[str, str | list[str]] = {
    "tehran": "IR", "moscow": "RU", "beijing": "CN", "kyiv": "UA",
    "taipei": "TW", "telaviv": "IL", "pyongyang": "KP", "sanaa": "YE",
    "riyadh": "SA", "ankara": "TR", "damascus": "SY", "caracas": "VE",
    "dc": "US", "london": "GB", "brussels": "BE", "baghdad": "IQ",
    "beirut": "LB", "doha": "QA", "abudhabi": "AE", "mexico": "MX",
    "havana": "CU", "nuuk": "GL",
    "sahel": ["ML", "NE", "BF"],
    "haiti": "HT",
    "horn_africa": ["ET", "SO", "SD"],
    "silicon_valley": "US", "wall_street": "US", "houston": "US",
    "cairo": "EG",
}


def get_hotspot_countries(hotspot_id: str) -> list[str]:
    """Resolve hotspot identifier to list of ISO country codes."""
    val = HOTSPOT_COUNTRY_MAP.get(hotspot_id.lower().replace(" ", "_"))
    if not val:
        return []
    return val if isinstance(val, list) else [val]


# ─────────────────────────────────────────────────────────────────────
# Country Detection from Text
# ─────────────────────────────────────────────────────────────────────

def detect_countries_in_text(text: str) -> list[tuple[str, float]]:
    """Detect which curated countries are mentioned in text.

    Returns list of (country_code, confidence) sorted by confidence desc.
    Confidence: keyword match = 1.0, alias match = 0.85.
    Uses word-boundary matching to prevent false positives
    (e.g. 'uk' in 'ukraine', 'iran' in 'ukraine').
    """
    import re
    text_lower = text.lower()
    results: dict[str, float] = {}

    def _wb_match(keyword: str, txt: str) -> bool:
        """Word-boundary match — prevents substring false positives."""
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', txt))

    for code, profile in CURATED_COUNTRIES.items():
        # Primary scoring keywords → confidence 1.0
        for kw in profile.scoring_keywords:
            if _wb_match(kw, text_lower):
                results[code] = max(results.get(code, 0.0), 1.0)
                break

        # Search aliases → confidence 0.85
        if code not in results:
            for alias in profile.search_aliases:
                if _wb_match(alias.strip(), text_lower):
                    results[code] = max(results.get(code, 0.0), 0.85)
                    break

    return sorted(results.items(), key=lambda x: x[1], reverse=True)


# ─────────────────────────────────────────────────────────────────────
# CII Scoring Engine
# ─────────────────────────────────────────────────────────────────────

@dataclass
class EventSignals:
    """Aggregated event signals for a country in a scoring window."""

    # Unrest signals
    protest_count: int = 0
    riot_count: int = 0
    protest_fatalities: int = 0
    outage_severity: str = ""       # "TOTAL" | "MAJOR" | "PARTIAL" | ""

    # Conflict signals (sourced from ACLED)
    battle_count: int = 0
    explosion_count: int = 0
    civilian_violence_count: int = 0
    conflict_fatalities: int = 0

    # Security signals
    gps_jamming_high: int = 0       # high-severity hex count
    gps_jamming_medium: int = 0     # medium-severity hex count
    border_incidents: int = 0

    # Information signals
    news_article_count: int = 0
    avg_headline_score: float = 0.0  # average score_headline() value

    # Floor overrides
    active_war: bool = False         # UCDP active war → floor 70
    minor_conflict: bool = False     # UCDP minor conflict → floor 50
    travel_advisory: str = ""        # "do_not_travel" | "reconsider" | "caution" | ""


def _compute_unrest_score(signals: EventSignals, multiplier: float) -> float:
    """Unrest score (0-100): protests, riots, outages."""
    raw = signals.protest_count + signals.riot_count * 2

    # Log2 dampening for low-multiplier countries (high-volume noise reduction)
    if multiplier < 0.7 and raw > 0:
        base = min(50, math.log2(1 + raw) * 10)
    else:
        base = min(50, raw * 5)

    # Fatality boost (up to 30)
    fatality_boost = min(30, signals.protest_fatalities * 5)

    # Outage severity boost (capped at 50 total with base)
    outage_map = {"TOTAL": 30, "MAJOR": 15, "PARTIAL": 5}
    outage_boost = outage_map.get(signals.outage_severity, 0)

    return min(100, base + fatality_boost + outage_boost)


def _compute_conflict_score(signals: EventSignals) -> float:
    """Conflict score (0-100): ACLED weighted events + fatalities."""
    # Weighted ACLED events (capped at 50)
    event_score = min(
        50,
        signals.battle_count * 3
        + signals.explosion_count * 4
        + signals.civilian_violence_count * 5,
    )

    # Sqrt-scaled fatalities (up to 40)
    fatality_score = min(40, math.sqrt(signals.conflict_fatalities) * 4)

    # Civilian violence bonus (up to 10)
    civilian_boost = min(10, signals.civilian_violence_count * 2)

    return min(100, event_score + fatality_score + civilian_boost)


def _compute_security_score(signals: EventSignals) -> float:
    """Security score (0-100): GPS jamming + border incidents."""
    # GPS jamming (capped at 35)
    jamming = min(35, signals.gps_jamming_high * 5 + signals.gps_jamming_medium * 2)

    # Border incidents
    border = min(30, signals.border_incidents * 10)

    return min(100, jamming + border)


def _compute_info_score(signals: EventSignals) -> float:
    """Information score (0-100): news velocity + headline severity."""
    # News volume component (0-50)
    volume = min(50, signals.news_article_count * 2)

    # Headline severity component (0-50)
    severity = min(50, signals.avg_headline_score / 4)

    return min(100, volume + severity)


def compute_cii(
    country_code: str,
    signals: EventSignals,
) -> float:
    """Compute Country Instability Index (0-100) for given country and signals.

    Formula:
        CII = baseline_component (40%) + event_component (60%)
        baseline_component = baseline_risk * 0.8
        event_component = unrest(25%) + conflict(30%) + security(20%) + info(25%)

    Plus floor overrides and advisory boosts.
    """
    profile = CURATED_COUNTRIES.get(country_code)
    if profile:
        baseline_risk = profile.baseline_risk
        multiplier = profile.event_multiplier
    else:
        baseline_risk = DEFAULT_BASELINE_RISK
        multiplier = DEFAULT_EVENT_MULTIPLIER

    # ── Baseline component (40%) ──
    # baseline_risk is 0-50 scale, map to 0-40 contribution
    baseline_component = baseline_risk * 0.8

    # ── Event component (60%) ──
    unrest = _compute_unrest_score(signals, multiplier)
    conflict = _compute_conflict_score(signals)
    security = _compute_security_score(signals)
    info = _compute_info_score(signals)

    # Apply event multiplier — amplifies/dampens event sensitivity
    raw_event = (
        unrest * 0.25
        + conflict * 0.30
        + security * 0.20
        + info * 0.25
    )
    event_component = min(60, raw_event * 0.6 * min(multiplier, 3.0))

    cii = baseline_component + event_component

    # ── Floor overrides ──
    if signals.active_war:
        cii = max(cii, 70)
    elif signals.minor_conflict:
        cii = max(cii, 50)

    if signals.travel_advisory == "do_not_travel":
        cii = max(cii, 60)
    elif signals.travel_advisory == "reconsider":
        cii = max(cii, 50)

    # ── Advisory boosts ──
    advisory_boost = {
        "do_not_travel": 15,
        "reconsider": 10,
        "caution": 5,
    }.get(signals.travel_advisory, 0)
    cii += advisory_boost

    return round(min(100, max(0, cii)), 1)


# ─────────────────────────────────────────────────────────────────────
# Lightweight CII from perception data (no external signals)
# ─────────────────────────────────────────────────────────────────────

def estimate_cii_from_events(
    country_code: str,
    events: list[dict],
) -> float:
    """Estimate CII purely from XDART perception events (no ACLED/GDELT needed).

    This is a lightweight version that works with the data we already collect:
    - headline scores from feed_catalog.score_headline()
    - salience scores from filter
    - content type classifications

    Good enough for Phase 1 integration — later we can add ACLED signals from collector.
    """
    from xdart.perception.feed_catalog import score_headline

    signals = EventSignals()

    for ev in events:
        headline = ev.get("headline", "")
        content_type = ev.get("content_type", "")
        domain = ev.get("domain", "")
        salience = ev.get("salience_score", 0.0)
        raw = ev.get("raw_payload", {})

        # Count articles
        signals.news_article_count += 1

        # Accumulate headline scores
        hl_score = raw.get("headline_score", 0) or score_headline(headline)
        signals.avg_headline_score += hl_score

        # Infer conflict signals from high-salience geopolitical events
        if domain == "GEOPOLITICAL" and salience >= 0.7:
            hl_lower = headline.lower()
            if any(w in hl_lower for w in ("battle", "fighting", "combat", "clash")):
                signals.battle_count += 1
            if any(w in hl_lower for w in ("explosion", "airstrike", "missile", "bombing", "shelling")):
                signals.explosion_count += 1
            if any(w in hl_lower for w in ("killed", "civilian", "massacre", "atrocity")):
                signals.civilian_violence_count += 1
            if any(w in hl_lower for w in ("protest", "demonstration", "march")):
                signals.protest_count += 1
            if any(w in hl_lower for w in ("riot", "unrest", "looting")):
                signals.riot_count += 1

    # Average headline score
    if signals.news_article_count > 0:
        signals.avg_headline_score /= signals.news_article_count

    return compute_cii(country_code, signals)


# ─────────────────────────────────────────────────────────────────────
# Top-N CII for Strategic Risk Score
# ─────────────────────────────────────────────────────────────────────

def compute_strategic_cii_score(cii_scores: dict[str, float]) -> float:
    """Compute aggregate strategic CII risk score from individual country CIIs.

    Uses WorldMonitor formula: top 5 countries weighted [0.40, 0.25, 0.20, 0.10, 0.05]
    plus bonus for each country above CII 50.
    Returns 0-100.
    """
    if not cii_scores:
        return 0.0

    sorted_scores = sorted(cii_scores.values(), reverse=True)
    weights = [0.40, 0.25, 0.20, 0.10, 0.05]

    weighted_sum = sum(
        score * weight
        for score, weight in zip(sorted_scores[:5], weights)
    )

    # Bonus: +5 for each country above CII 50 (capped at +20)
    elevated_count = sum(1 for s in cii_scores.values() if s > 50)
    bonus = min(20, elevated_count * 5)

    return round(min(100, weighted_sum + bonus), 1)


# ─────────────────────────────────────────────────────────────────────
# Convenience: get_country_profile
# ─────────────────────────────────────────────────────────────────────

def get_country_profile(country_code: str) -> CountryProfile:
    """Get profile for a country. Returns curated or default."""
    if country_code in CURATED_COUNTRIES:
        return CURATED_COUNTRIES[country_code]
    return CountryProfile(
        code=country_code,
        name=country_code,
        scoring_keywords=[],
        search_aliases=[],
        baseline_risk=DEFAULT_BASELINE_RISK,
        event_multiplier=DEFAULT_EVENT_MULTIPLIER,
    )
