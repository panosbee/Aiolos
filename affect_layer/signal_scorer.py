"""
Affect Layer — Signal Scorer

Evaluates the quality and urgency of a proactive alert across 5 dimensions:

  1. Novelty       (30%) — How different is this from recent alerts?
  2. Relevance     (25%) — Does this match known strategic importance signals?
  3. Actionability (20%) — Does this imply a decision or response?
  4. Timeliness    (15%) — How fresh is the underlying data?
  5. Diversity     (10%) — Does this broaden domain coverage?
                           (increases when a rarely-covered domain fires)

Composite score → category:
  critical  ≥ 0.80   (bypass batch, immediate delivery)
  important ≥ 0.60   (route to important urgency)
  digest    ≥ 0.35   (buffer for batch synthesis)
  skip      < 0.35   (suppress entirely)

The scorer also maintains a rolling domain-frequency table that the
DomainBalanceMonitor uses to detect single-domain saturation.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("xdart.affect.scorer")

# ── Scoring weights (must sum to 1.0) ──────────────────────────────────────
_DEFAULT_WEIGHTS = {
    "novelty":       0.30,
    "relevance":     0.25,
    "actionability": 0.20,
    "timeliness":    0.15,
    "diversity":     0.10,
}

# ── Score category thresholds ───────────────────────────────────────────────
_CRITICAL_THRESHOLD  = 0.80
_IMPORTANT_THRESHOLD = 0.60
_DIGEST_THRESHOLD    = 0.35

# ── Relevance signals ───────────────────────────────────────────────────────
# High-importance keywords in any domain (boost relevance score)
_HIGH_RELEVANCE_KEYWORDS: frozenset[str] = frozenset({
    # Strategic severity
    "war", "nuclear", "invasion", "coup", "assassination", "attack",
    "collapse", "default", "crash", "pandemic", "outbreak", "emergency",
    "catastrophe", "disaster", "explosion", "missile", "escalation",
    # Market severity
    "flash crash", "circuit breaker", "bank run", "bailout",
    "rate emergency", "systemic risk", "contagion",
    # Tech severity
    "zero-day", "critical vulnerability", "infrastructure attack",
    "agi", "quantum breakthrough", "grid failure",
    # Social severity
    "mass protest", "revolution", "martial law", "famine",
    # Climate severity
    "climate tipping", "record temperature", "mega-drought",
})

_MEDIUM_RELEVANCE_KEYWORDS: frozenset[str] = frozenset({
    "sanction", "conflict", "election", "inflation", "recession",
    "strike", "protest", "migration", "drought", "flood",
    "cyber attack", "ransomware", "hack", "data breach",
    "rate decision", "gdp", "unemployment", "trade war",
    "epidemic", "vaccine", "mutation",
    "breakthrough", "discovery", "launch", "summit",
    "treaty", "alliance", "deal", "agreement",
})

# ── Actionability signals ────────────────────────────────────────────────────
# Patterns that suggest a decision or response is possible
_ACTIONABILITY_KEYWORDS: frozenset[str] = frozenset({
    "imminent", "warning", "alert", "breaking", "urgent",
    "deadline", "decision", "vote", "tomorrow", "today", "hours",
    "expected", "scheduled", "anticipated", "likely", "confirmed",
    "respond", "prepare", "evacuate", "mobilize", "deploy",
    "forecast", "prediction", "estimate", "projection",
    "opportunity", "window", "threshold", "trigger",
})

# ── Domain vocabulary for diversity scoring ──────────────────────────────────
_DOMAIN_VOCAB: dict[str, frozenset[str]] = {
    "GEOPOLITICAL": frozenset({
        "war", "conflict", "nato", "military", "troops", "coup",
        "diplomatic", "sanction", "espionage", "invasion", "missile",
        "ceasefire", "alliance", "treaty", "territorial",
    }),
    "ECONOMIC": frozenset({
        "gdp", "inflation", "recession", "rate", "central bank",
        "fiscal", "monetary", "deficit", "trade", "tariff",
        "unemployment", "growth", "contraction", "budget",
    }),
    "MARKET": frozenset({
        "stock", "crash", "vix", "volatility", "bitcoin", "crypto",
        "gold", "oil", "brent", "commodity", "yield", "bond",
        "nasdaq", "dow", "currency", "devaluation",
    }),
    "SOCIAL": frozenset({
        "protest", "unrest", "riot", "strike", "election",
        "migration", "refugee", "pandemic", "epidemic", "famine",
        "humanitarian", "poverty", "inequality", "civil",
    }),
    "TECHNOLOGY": frozenset({
        "cyber", "hack", "ai", "artificial intelligence", "quantum",
        "semiconductor", "chip", "satellite", "autonomous", "drone",
        "renewable", "fusion", "biotech", "crispr", "gene",
    }),
    "SCIENCE": frozenset({
        "discovery", "research", "study", "climate", "carbon",
        "species", "astronomy", "physics", "medicine", "vaccine",
        "trial", "breakthrough", "nobel", "publication",
    }),
}


@dataclass
class SignalScore:
    """Multi-dimensional quality score for a single alert."""
    novelty:       float = 0.0
    relevance:     float = 0.0
    actionability: float = 0.0
    timeliness:    float = 0.0
    diversity:     float = 0.0
    composite:     float = 0.0
    category:      str = "skip"   # critical | important | digest | skip
    weights_used:  dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "novelty":       round(self.novelty, 3),
            "relevance":     round(self.relevance, 3),
            "actionability": round(self.actionability, 3),
            "timeliness":    round(self.timeliness, 3),
            "diversity":     round(self.diversity, 3),
            "composite":     round(self.composite, 3),
            "category":      self.category,
        }


class SignalScorer:
    """5-dimensional alert quality scorer with adaptive domain diversity."""

    def __init__(self):
        # Mutable weights — can be adjusted by DomainBalanceMonitor feedback
        self._weights: dict[str, float] = dict(_DEFAULT_WEIGHTS)

        # Rolling domain counters for novelty + diversity scoring
        # domain → list of timestamps (last 2 hours)
        self._domain_history: dict[str, list[float]] = defaultdict(list)

        # Stats
        self._total_scored = 0
        self._category_counts: dict[str, int] = defaultdict(int)

    # ── Public interface ─────────────────────────────────────────────────────

    def score(
        self,
        headline: str,
        summary: str,
        domains: list[str],
        event_type: str,
        event_data: dict[str, Any],
    ) -> SignalScore:
        """Compute a SignalScore for the given alert."""
        self._total_scored += 1
        text = (headline + " " + summary).lower()

        novelty       = self._score_novelty(text, domains)
        relevance     = self._score_relevance(text, event_type, event_data)
        actionability = self._score_actionability(text, event_data)
        timeliness    = self._score_timeliness(event_data)
        diversity     = self._score_diversity(domains)

        w = self._weights
        composite = (
            w["novelty"]       * novelty
            + w["relevance"]     * relevance
            + w["actionability"] * actionability
            + w["timeliness"]    * timeliness
            + w["diversity"]     * diversity
        )
        composite = min(1.0, max(0.0, composite))

        category = self._classify(composite)
        self._category_counts[category] += 1

        return SignalScore(
            novelty=round(novelty, 3),
            relevance=round(relevance, 3),
            actionability=round(actionability, 3),
            timeliness=round(timeliness, 3),
            diversity=round(diversity, 3),
            composite=round(composite, 3),
            category=category,
            weights_used=dict(self._weights),
        )

    def record(self, domains: list[str]) -> None:
        """Record that an alert with these domains was delivered."""
        now = time.time()
        cutoff = now - 7200  # 2-hour window
        for d in domains:
            hist = self._domain_history[d]
            # Prune old entries
            while hist and hist[0] < cutoff:
                hist.pop(0)
            hist.append(now)

    def get_domain_balance(self) -> dict[str, int]:
        """Return recent domain counts (last 2 hours)."""
        now = time.time()
        cutoff = now - 7200
        result: dict[str, int] = {}
        for domain, history in self._domain_history.items():
            count = sum(1 for t in history if t > cutoff)
            if count:
                result[domain] = count
        return result

    def update_weights_from_feedback(self, adjustments: dict[str, float]) -> None:
        """Apply weight adjustments (called by DomainBalanceMonitor).

        adjustments: e.g. {"diversity": +0.05, "novelty": -0.05}
        Weights are renormalised to sum to 1.0 after adjustment.
        """
        for key, delta in adjustments.items():
            if key in self._weights:
                self._weights[key] = max(0.05, min(0.60, self._weights[key] + delta))

        # Renormalise
        total = sum(self._weights.values())
        if total > 0:
            for k in self._weights:
                self._weights[k] = round(self._weights[k] / total, 4)

        logger.debug("[Scorer] Weights updated: %s", self._weights)

    def get_stats(self) -> dict:
        """Return scorer statistics."""
        return {
            "total_scored": self._total_scored,
            "category_counts": dict(self._category_counts),
            "current_weights": dict(self._weights),
            "domain_balance_2h": self.get_domain_balance(),
        }

    # ── Scoring sub-methods ───────────────────────────────────────────────────

    def _score_novelty(self, text: str, domains: list[str]) -> float:
        """Novelty: high when the domain hasn't fired recently."""
        now = time.time()
        cutoff = now - 3600  # 1-hour novelty window

        if not domains:
            return 0.7  # Unknown domain → assume novel

        min_recent = float("inf")
        for d in domains:
            hist = self._domain_history.get(d, [])
            recent = sum(1 for t in hist if t > cutoff)
            min_recent = min(min_recent, recent)

        if min_recent == float("inf"):
            return 0.9  # Brand new domain — very novel

        # Novelty decays with frequency: 0 recent = 0.9, 5+ recent = 0.2
        return max(0.10, 0.90 - (min_recent * 0.14))

    def _score_relevance(
        self,
        text: str,
        event_type: str,
        event_data: dict[str, Any],
    ) -> float:
        """Relevance: how strategically important is this signal?"""
        score = 0.3  # Baseline

        # High-relevance keyword match
        high_matches = sum(1 for kw in _HIGH_RELEVANCE_KEYWORDS if kw in text)
        if high_matches:
            score += min(0.50, high_matches * 0.15)

        # Medium-relevance keyword match
        med_matches = sum(1 for kw in _MEDIUM_RELEVANCE_KEYWORDS if kw in text)
        if med_matches and high_matches == 0:
            score += min(0.25, med_matches * 0.08)

        # Cross-domain pattern bonus (most valuable insight type)
        domains = event_data.get("domains", [])
        if len(set(domains)) >= 2:
            score += 0.10
        if len(set(domains)) >= 3:
            score += 0.10

        # Source type bonus
        high_value_sources = {
            "prophecy_resolved", "cross_pattern_synthesis",
            "temporal_precursor", "financial_anomaly",
            "correlation_alert",
        }
        source_types = event_data.get("source_types", [event_type])
        if any(s in high_value_sources for s in source_types):
            score += 0.10

        # Convergence score bonus (if available from pattern data)
        convergence = event_data.get("convergence_score", 0.0)
        if convergence >= 0.80:
            score += 0.10
        elif convergence >= 0.60:
            score += 0.05

        return min(1.0, score)

    def _score_actionability(self, text: str, event_data: dict[str, Any]) -> float:
        """Actionability: does this alert imply a decision is needed?"""
        matches = sum(1 for kw in _ACTIONABILITY_KEYWORDS if kw in text)
        base = min(0.80, 0.20 + matches * 0.12)

        # Breaking indicators → always actionable
        if any(kw in text for kw in ("breaking", "urgent", "flash", "εκτακτο")):
            base = max(base, 0.75)

        # Prophecy resolution → high actionability (prediction came true/false)
        source_types = event_data.get("source_types", [])
        if "prophecy_resolved" in source_types:
            base = max(base, 0.70)

        return round(min(1.0, base), 3)

    def _score_timeliness(self, event_data: dict[str, Any]) -> float:
        """Timeliness: how fresh is the most recent signal in the pattern?"""
        # Prefer signal_count as a proxy — more signals = more active topic
        signal_count = event_data.get("signal_count", 1)

        # Fresh patterns (many recent signals) score higher
        if signal_count >= 15:
            return 0.95
        elif signal_count >= 8:
            return 0.80
        elif signal_count >= 5:
            return 0.65
        elif signal_count >= 3:
            return 0.50
        else:
            return 0.35

    def _score_diversity(self, domains: list[str]) -> float:
        """Diversity: reward domains that are under-represented in recent history."""
        if not domains:
            return 0.5

        now = time.time()
        cutoff = now - 7200  # 2-hour window

        total_recent = sum(
            len([t for t in hist if t > cutoff])
            for hist in self._domain_history.values()
        )

        if total_recent == 0:
            return 0.8  # No history → anything is diverse

        # Score each domain by its inverse frequency
        domain_scores = []
        for d in domains:
            hist = self._domain_history.get(d, [])
            domain_recent = sum(1 for t in hist if t > cutoff)
            # Fraction of total → low fraction = high diversity
            frac = domain_recent / max(1, total_recent)
            domain_scores.append(1.0 - frac)

        return round(max(domain_scores), 3) if domain_scores else 0.5

    @staticmethod
    def _classify(composite: float) -> str:
        """Map composite score to category."""
        if composite >= _CRITICAL_THRESHOLD:
            return "critical"
        elif composite >= _IMPORTANT_THRESHOLD:
            return "important"
        elif composite >= _DIGEST_THRESHOLD:
            return "digest"
        else:
            return "skip"
