"""
Affect Layer — Domain Balance Monitor

Tracks the distribution of proactive alert domains over time.
When a single domain exceeds 70% of recent alerts, it:

  1. Emits a bias warning (logged + injectable into chat context)
  2. Tells SignalScorer to increase the diversity weight (+0.05)
     and reduce the overrepresented domain's novelty baseline (-0.05)
  3. Provides a formatted bias report for dashboard / chat injection

Domain window: 2 hours (same as SignalScorer's novelty window)
Bias threshold: 70% single-domain share triggers intervention

Auto-rebalancing: after 3 consecutive bias interventions on the same
domain, the scorer's diversity weight is raised more aggressively (+0.10).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from affect_layer.signal_scorer import SignalScorer

logger = logging.getLogger("xdart.affect.balance")

_WINDOW_SECONDS = 7200     # 2-hour window
_BIAS_THRESHOLD = 0.70     # Single domain > 70% triggers alert
_INTERVENTION_ESCALATION = 3  # After this many consecutive interventions → escalate


class DomainBalanceMonitor:
    """Tracks domain distribution and intervenes when bias detected."""

    def __init__(self, scorer: SignalScorer | None = None):
        self._scorer = scorer
        # domain → list of timestamps
        self._history: dict[str, list[float]] = defaultdict(list)
        self._interventions: dict[str, int] = defaultdict(int)  # domain → consecutive count
        self._total_interventions = 0
        self._last_intervention_ts: dict[str, float] = {}
        # Minimum gap between interventions for same domain (15 min)
        self._intervention_cooldown = 900

    def record(self, domains: list[str]) -> None:
        """Record an alert delivery for the given domains."""
        now = time.time()
        cutoff = now - _WINDOW_SECONDS
        for d in (domains or ["GENERAL"]):
            hist = self._history[d]
            # Prune old entries
            while hist and hist[0] < cutoff:
                hist.pop(0)
            hist.append(now)

    def get_distribution(self) -> dict[str, float]:
        """Return the current domain share (0-1) over the last 2 hours."""
        now = time.time()
        cutoff = now - _WINDOW_SECONDS
        counts: dict[str, int] = {}
        for domain, hist in self._history.items():
            c = sum(1 for t in hist if t > cutoff)
            if c:
                counts[domain] = c
        total = sum(counts.values())
        if not total:
            return {}
        return {d: round(c / total, 3) for d, c in counts.items()}

    def get_bias_warning(self) -> str | None:
        """Return a warning string if domain bias is detected, else None.

        Also triggers scorer weight adjustment if a scorer is wired in.
        """
        distribution = self.get_distribution()
        if not distribution:
            return None

        biased_domain = None
        biased_share = 0.0
        for domain, share in distribution.items():
            if share > _BIAS_THRESHOLD and share > biased_share:
                biased_domain = domain
                biased_share = share

        if not biased_domain:
            # Reset consecutive counts for all domains that are no longer biased
            for d in list(self._interventions):
                if distribution.get(d, 0) < _BIAS_THRESHOLD:
                    self._interventions[d] = 0
            return None

        now = time.time()
        last = self._last_intervention_ts.get(biased_domain, 0)
        if now - last < self._intervention_cooldown:
            return None  # Cooldown — skip this check

        self._interventions[biased_domain] += 1
        self._total_interventions += 1
        self._last_intervention_ts[biased_domain] = now

        # Apply scorer weight adjustment
        if self._scorer is not None:
            consecutive = self._interventions[biased_domain]
            diversity_boost = 0.10 if consecutive >= _INTERVENTION_ESCALATION else 0.05
            self._scorer.update_weights_from_feedback({
                "diversity": +diversity_boost,
                "novelty":   -0.02,  # slight reduction to counterbalance
            })
            logger.warning(
                "[BalanceMonitor] Domain bias detected: %s at %.0f%% — "
                "boosting diversity weight by %.2f (intervention #%d)",
                biased_domain, biased_share * 100, diversity_boost, consecutive,
            )

        # Format warning message
        dist_str = ", ".join(
            f"{d}={v:.0%}" for d, v in sorted(distribution.items(), key=lambda x: -x[1])
        )
        return (
            f"DOMAIN BIAS: {biased_domain} is {biased_share:.0%} of recent alerts "
            f"(threshold {_BIAS_THRESHOLD:.0%}). Distribution: {dist_str}"
        )

    def get_balance_context(self) -> str:
        """Formatted domain distribution for injection into chat context."""
        distribution = self.get_distribution()
        if not distribution:
            return ""

        lines = ["▸ ALERT DOMAIN DISTRIBUTION (last 2h):"]
        for domain, share in sorted(distribution.items(), key=lambda x: -x[1]):
            bar = "█" * int(share * 20)
            flag = " ⚠ BIASED" if share > _BIAS_THRESHOLD else ""
            lines.append(f"  {domain:<14} {bar:<20} {share:.0%}{flag}")
        lines.append("")
        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Return balance monitor statistics."""
        return {
            "distribution_2h": self.get_distribution(),
            "total_interventions": self._total_interventions,
            "consecutive_interventions": dict(self._interventions),
        }
