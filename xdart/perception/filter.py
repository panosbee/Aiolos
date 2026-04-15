"""
XDART-Φ × XHEART — Perception Filter

Phase 1 MVP: keyword-based classification (no LLM cost).
Separates FACT from ANALYSIS from OPINION.
Classifies domain and region.
Assigns salience score.

Phase 2 will add LLM-based classification for nuanced cases.
"""

import logging
import re

from xdart.perception.feed_catalog import (
    get_propaganda_risk,
    score_headline,
    DEMOTION_KEYWORDS,
)
from xdart.perception.country_risk import (
    detect_countries_in_text,
    CURATED_COUNTRIES,
)

logger = logging.getLogger("xdart.perception.filter")


class PerceptionFilter:
    """Classifies incoming events.

    Separates what happened from how it is interpreted.
    Phase 1 MVP uses keyword heuristics — fast, free, no LLM.
    """

    # ── Keyword Sets ──

    FACT_INDICATORS = [
        "announced", "raised", "cut", "released", "published",
        "reported", "signed", "agreed", "voted", "increased",
        "decreased", "fell", "rose", "appointed", "resigned",
        "approved", "enacted", "launched", "imposed", "lifted",
        "declared", "opened", "closed", "arrested", "killed",
        "deployed", "withdrew", "collapsed", "surged", "plunged",
    ]

    OPINION_INDICATORS = [
        "believes", "argues", "warns", "fears", "hopes",
        "should", "must", "could", "might", "likely",
        "editorial", "opinion", "analysis", "commentary",
        "according to analysts", "experts say", "sources say",
        "is expected to", "may lead to",
    ]

    DOMAIN_KEYWORDS = {
        "ECONOMIC": [
            "rate", "gdp", "inflation", "trade", "tariff", "economy",
            "unemployment", "deficit", "debt", "bond", "yield",
            "fiscal", "monetary", "central bank", "fed ", "ecb",
            "imf", "world bank", "currency", "exchange rate",
            "recession", "growth", "cpi", "ppi", "manufacturing",
            "supply chain", "export", "import", "commodity",
        ],
        "GEOPOLITICAL": [
            "war", "conflict", "sanction", "election", "treaty",
            "ceasefire", "invasion", "coup", "protest", "diplomacy",
            "alliance", "nato", "un ", "g7", "g20", "brics",
            "nuclear", "missile", "military", "territory", "border",
            "refugee", "humanitarian", "crisis", "disaster",
        ],
        "TECHNOLOGY": [
            "ai ", "artificial intelligence", "tech", "semiconductor",
            "cyber", "quantum", "blockchain", "software", "chip",
            "data center", "cloud", "robotics", "biotech",
            "space", "satellite", "5g", "6g", "machine learning",
        ],
        "MARKET": [
            "stock", "market", "index", "dow", "nasdaq", "s&p",
            "ftse", "nikkei", "shanghai", "crypto", "bitcoin",
            "ipo", "merger", "acquisition", "earnings", "profit",
            "revenue", "shares", "trading", "investor",
        ],
    }

    REGION_KEYWORDS = {
        "US": ["united states", "u.s.", "us ", "america", "washington",
               "biden", "trump", "congress", "fed ", "pentagon", "wall street"],
        "EU": ["europe", "eu ", "european", "brussels", "ecb",
               "germany", "france", "italy", "spain", "berlin", "paris"],
        "CN": ["china", "chinese", "beijing", "shanghai", "xi jinping",
               "pbc", "ccp", "taiwan"],
        "RU": ["russia", "russian", "moscow", "putin", "kremlin"],
        "JP": ["japan", "japanese", "tokyo", "boj"],
        "UK": ["britain", "british", "uk ", "london", "bank of england"],
        "IN": ["india", "indian", "delhi", "mumbai", "modi"],
        "ME": ["middle east", "iran", "saudi", "israel", "palestine",
               "gaza", "lebanon", "syria", "iraq"],
        "AF": ["africa", "african", "nigeria", "south africa", "egypt",
               "kenya", "ethiopia"],
        "LATAM": ["brazil", "mexico", "argentina", "latin america",
                  "south america", "colombia"],
        "KR": ["korea", "korean", "seoul"],
    }

    HIGH_SALIENCE_KEYWORDS = [
        "breaking", "urgent", "crisis", "war ", "attack",
        "collapse", "emergency", "unprecedented", "historic",
        "rate decision", "rate cut", "rate hike", "default",
        "invasion", "nuclear", "pandemic", "earthquake", "tsunami",
        # Economic high-salience additions
        "recession", "bailout", "bank run", "flash crash",
        "downgrade", "debt ceiling", "sovereign debt",
        "trade war", "sanctions", "tariff",
        "supply shock", "stagflation", "contagion",
        "capital controls", "currency crisis",
    ]

    def classify(
        self,
        headline: str,
        content: str,
        source_name: str,
        source_tier: int,
        source_region: str,
    ) -> dict | None:
        """Classify an incoming event.

        Returns classified dict or None if irrelevant.
        """
        text = f"{headline} {content}".lower()

        # Tier 1 sources are always FACT or DATA — no classification needed
        if source_tier == 1:
            return {
                "headline": headline,
                "summary": content[:500],
                "content_type": "DATA",
                "domain": self._classify_domain(text),
                "region_focus": self._classify_regions(text) or [source_region],
                "salience_score": 0.8,
            }

        # Determine content type
        content_type = self._classify_type(text, source_tier)
        if content_type == "IRRELEVANT":
            return None

        # Classify domain
        domain = self._classify_domain(text)

        # Classify regions
        regions = self._classify_regions(text)
        if not regions:
            regions = [source_region] if source_region != "MULTI" else ["GLOBAL"]

        # Detect curated countries mentioned in text (for CII integration)
        country_detections = detect_countries_in_text(text)
        detected_codes = [c for c, _ in country_detections[:3]]

        # Calculate salience
        salience = self._calculate_salience(
            text, content_type, source_tier, domain,
            source_name=source_name, headline=headline,
            country_codes=detected_codes,
        )

        return {
            "headline": headline,
            "summary": content[:500],
            "content_type": content_type,
            "domain": domain,
            "region_focus": regions,
            "salience_score": salience,
            "country_codes": detected_codes,
        }

    def _classify_type(self, text: str, source_tier: int) -> str:
        """Classify as FACT, ANALYSIS, OPINION, or IRRELEVANT."""
        # Tier 3 sources are ALWAYS analysis
        if source_tier == 3:
            return "ANALYSIS"

        fact_score = sum(1 for kw in self.FACT_INDICATORS if kw in text)
        opinion_score = sum(1 for kw in self.OPINION_INDICATORS if kw in text)

        if opinion_score > fact_score:
            return "OPINION" if opinion_score >= 2 else "ANALYSIS"

        if fact_score > 0:
            return "FACT"

        # Check if it matches any domain at all
        domain = self._classify_domain(text)
        if domain == "MULTI":
            # No strong domain signal — might be irrelevant
            # But still accept from Tier 2 wire services
            if source_tier == 2:
                return "FACT"
            return "IRRELEVANT"

        return "FACT"

    def _classify_domain(self, text: str) -> str:
        """Classify domain based on keyword matches."""
        scores = {}
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[domain] = score

        if not scores:
            return "MULTI"

        return max(scores, key=scores.get)

    def _classify_regions(self, text: str) -> list[str]:
        """Identify regions mentioned in the text."""
        regions = []
        for region, keywords in self.REGION_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                regions.append(region)
        return regions[:4]  # Max 4 regions per event

    def _calculate_salience(
        self,
        text: str,
        content_type: str,
        source_tier: int,
        domain: str,
        source_name: str = "",
        headline: str = "",
        country_codes: list[str] | None = None,
    ) -> float:
        """Calculate salience score (0.0 to 1.0).

        Factors: tier, content-type, keyword urgency, headline importance,
        propaganda risk penalty, and corporate-noise demotion.
        """
        base = 0.5

        # Tier affects base salience
        tier_bonus = {1: 0.3, 2: 0.1, 3: 0.0}.get(source_tier, 0.0)
        base += tier_bonus

        # Facts are more salient than opinions
        type_bonus = {"FACT": 0.1, "DATA": 0.15, "ANALYSIS": 0.0, "OPINION": -0.1}
        base += type_bonus.get(content_type, 0.0)

        # High-salience keywords boost score
        high_sal = sum(1 for kw in self.HIGH_SALIENCE_KEYWORDS if kw in text)
        base += min(high_sal * 0.1, 0.3)

        # ── Domain-based salience adjustment ──
        # Economic/market events get a boost to reach alert threshold (0.85)
        # more easily — mirrors the natural importance of economic signals
        if domain in ("ECONOMIC", "MARKET"):
            base += 0.08

        # ── Headline importance score (WorldMonitor-ported) ──
        if headline:
            hl_score = score_headline(headline)
            # Map 0-500 → 0.0-0.25 bonus
            base += min(hl_score / 2000.0, 0.25)

        # ── Propaganda risk penalty ──
        if source_name:
            risk_info = get_propaganda_risk(source_name)
            risk_level = risk_info.get("risk", "low")
            if risk_level == "high":
                base -= 0.15
            elif risk_level == "medium":
                base -= 0.05
            # State-controlled sources get additional penalty
            if risk_info.get("state_controlled"):
                base -= 0.05

        # ── Corporate noise demotion ──
        text_lower = text.lower() if text else ""
        if any(kw in text_lower for kw in DEMOTION_KEYWORDS):
            base -= 0.10

        # ── Country baseline risk boost ──
        # Events mentioning high-risk countries get salience boost
        if country_codes:
            max_baseline = 0
            for cc in country_codes:
                profile = CURATED_COUNTRIES.get(cc)
                if profile:
                    max_baseline = max(max_baseline, profile.baseline_risk)
            # Map baseline 0-50 → 0.0-0.15 boost
            if max_baseline >= 40:
                base += 0.15
            elif max_baseline >= 25:
                base += 0.10
            elif max_baseline >= 15:
                base += 0.05

        return max(0.1, min(1.0, round(base, 2)))
