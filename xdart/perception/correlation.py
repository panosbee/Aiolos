"""
XDART-Φ × XHEART — Cross-Stream Correlation Engine

Ported from WorldMonitor's cross-stream correlation and signal aggregation logic.

Detects meaningful correlations across data streams — patterns that no single
source would reveal.  Signals are clustered by country/region, deduplicated per-type
with configurable cooldowns, and emitted as correlation events.

Supported signal types (adapted for XDART-Φ's data sources):
  - velocity_spike:     News cluster from 6+ Tier 1-2 sources/hour
  - keyword_spike:      Trending term exceeds 3× its 7-day baseline
  - convergence:        3+ signal types in same country within 24h window
  - triangulation:      Same entity across news + conflict data + economic signals
  - cii_spike:          CII score change ≥ 10 points
  - infrastructure:     Infrastructure cascade alert triggered
  - explained_market:   Economic indicator move with matching news cluster
  - hotspot_escalation: Country with CII > 60 and rising

Alert fusion: signals within 2-hour window in same country are merged.
Alert queue cap: 50 entries with 24-hour pruning.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("xdart.perception.correlation")


# ─────────────────────────────────────────────────────────────────────
# Signal Types
# ─────────────────────────────────────────────────────────────────────

class SignalType(str, Enum):
    VELOCITY_SPIKE = "velocity_spike"
    KEYWORD_SPIKE = "keyword_spike"
    CONVERGENCE = "convergence"
    TRIANGULATION = "triangulation"
    CII_SPIKE = "cii_spike"
    INFRASTRUCTURE = "infrastructure"
    EXPLAINED_MARKET = "explained_market"
    HOTSPOT_ESCALATION = "hotspot_escalation"
    # Phase A additions
    SILENT_DIVERGENCE = "silent_divergence"       # CII rising but news velocity flat/dropping
    COMMODITY_SHOCK = "commodity_shock"            # Oil/gold/gas price spike > 10%
    SENTIMENT_SPLIT = "sentiment_split"            # Same event, opposing sentiment by region


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    """A single detected signal from any data stream."""
    signal_type: SignalType
    severity: Severity
    country_code: str           # ISO country code or "GLOBAL"
    summary: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)
    source: str = ""            # which collector/module generated this


@dataclass
class CorrelationAlert:
    """Alert generated when signals correlate across streams."""
    alert_id: str
    signal_types: list[str]
    severity: Severity
    country_code: str
    summary: str
    signals: list[Signal]
    timestamp: float = field(default_factory=time.time)
    merged_count: int = 1


# ─────────────────────────────────────────────────────────────────────
# Cooldown Configuration (per signal type, in seconds)
# ─────────────────────────────────────────────────────────────────────

COOLDOWNS: dict[SignalType, int] = {
    SignalType.VELOCITY_SPIKE: 1800,       # 30 min
    SignalType.KEYWORD_SPIKE: 1800,
    SignalType.CONVERGENCE: 3600,          # 1 hour
    SignalType.TRIANGULATION: 3600,
    SignalType.CII_SPIKE: 7200,            # 2 hours
    SignalType.INFRASTRUCTURE: 7200,
    SignalType.EXPLAINED_MARKET: 3600,
    SignalType.HOTSPOT_ESCALATION: 21600,  # 6 hours
    SignalType.SILENT_DIVERGENCE: 14400,   # 4 hours
    SignalType.COMMODITY_SHOCK: 7200,      # 2 hours
    SignalType.SENTIMENT_SPLIT: 3600,      # 1 hour
}

# Alert fusion window (seconds)
FUSION_WINDOW = 7200     # 2 hours
# Max alerts in queue
MAX_ALERTS = 50
# Alert pruning age
PRUNE_AGE = 86400        # 24 hours


# ─────────────────────────────────────────────────────────────────────
# Correlation Engine
# ─────────────────────────────────────────────────────────────────────

class CorrelationEngine:
    """Cross-stream signal correlation engine.

    Aggregates signals by country, detects convergence patterns,
    and emits correlation alerts with deduplication and fusion.
    """

    def __init__(self):
        # Per-country signal buffer: country_code → [Signal]
        self._country_signals: dict[str, list[Signal]] = {}
        # Cooldown tracker: (signal_type, country_code) → last_fire_time
        self._cooldowns: dict[tuple[str, str], float] = {}
        # Alert queue
        self._alerts: list[CorrelationAlert] = []
        # CII history for spike detection: country_code → [(timestamp, score)]
        self._cii_history: dict[str, list[tuple[float, float]]] = {}

    # ── Signal Ingestion ──

    def ingest_signal(self, signal: Signal) -> CorrelationAlert | None:
        """Ingest a signal and check for cross-stream correlations.

        Returns a CorrelationAlert if correlation detected, else None.
        """
        now = signal.timestamp or time.time()

        # Cooldown check
        cooldown_key = (signal.signal_type.value, signal.country_code)
        last_fire = self._cooldowns.get(cooldown_key, 0)
        cooldown_period = COOLDOWNS.get(signal.signal_type, 1800)
        if now - last_fire < cooldown_period:
            return None

        # Store signal in country buffer
        country = signal.country_code
        if country not in self._country_signals:
            self._country_signals[country] = []
        self._country_signals[country].append(signal)

        # Prune old signals from buffer (keep 24h)
        cutoff = now - PRUNE_AGE
        self._country_signals[country] = [
            s for s in self._country_signals[country] if s.timestamp > cutoff
        ]

        # Check for convergence (3+ signal types in same country within window)
        alert = self._check_convergence(country, now)
        if alert:
            self._cooldowns[cooldown_key] = now
            return alert

        # Update cooldown for this signal type
        self._cooldowns[cooldown_key] = now
        return None

    def ingest_cii_score(
        self, country_code: str, score: float, timestamp: float | None = None,
    ) -> Signal | None:
        """Track CII score and emit CII_SPIKE signal if ≥10-point change.

        Returns a Signal if spike detected, else None.
        """
        ts = timestamp or time.time()

        if country_code not in self._cii_history:
            self._cii_history[country_code] = []

        history = self._cii_history[country_code]
        history.append((ts, score))

        # Keep 48h history
        cutoff = ts - 172800
        self._cii_history[country_code] = [
            (t, s) for t, s in history if t > cutoff
        ]

        # Check for spike: compare against most recent different score
        if len(history) >= 2:
            prev_score = history[-2][1]
            delta = score - prev_score
            if abs(delta) >= 10:
                severity = Severity.CRITICAL if abs(delta) >= 20 else Severity.HIGH
                direction = "escalating" if delta > 0 else "de-escalating"
                signal = Signal(
                    signal_type=SignalType.CII_SPIKE,
                    severity=severity,
                    country_code=country_code,
                    summary=f"CII {direction}: {prev_score:.0f} → {score:.0f} (Δ{delta:+.0f})",
                    timestamp=ts,
                    metadata={"prev_score": prev_score, "new_score": score, "delta": delta},
                    source="cii_tracker",
                )
                self.ingest_signal(signal)
                return signal

        return None

    # ── Query ──

    def get_recent_alerts(self, max_age: float = 3600) -> list[CorrelationAlert]:
        """Get alerts from last N seconds."""
        cutoff = time.time() - max_age
        return [a for a in self._alerts if a.timestamp > cutoff]

    def get_country_signals(
        self, country_code: str, max_age: float = 86400,
    ) -> list[Signal]:
        """Get all signals for a country within max_age."""
        cutoff = time.time() - max_age
        return [
            s for s in self._country_signals.get(country_code, [])
            if s.timestamp > cutoff
        ]

    def get_signal_summary(self) -> dict:
        """Summary of signal activity across all countries."""
        now = time.time()
        active_countries = 0
        total_signals_24h = 0
        signal_type_counts: dict[str, int] = {}

        for country, signals in self._country_signals.items():
            recent = [s for s in signals if s.timestamp > now - 86400]
            if recent:
                active_countries += 1
                total_signals_24h += len(recent)
                for s in recent:
                    st = s.signal_type.value
                    signal_type_counts[st] = signal_type_counts.get(st, 0) + 1

        return {
            "active_countries": active_countries,
            "total_signals_24h": total_signals_24h,
            "signal_type_counts": signal_type_counts,
            "alert_queue_size": len(self._alerts),
            "cii_tracked_countries": len(self._cii_history),
        }

    def compute_trend(self, country_code: str) -> str:
        """Compute CII trend for a country: 'escalating', 'de-escalating', or 'stable'.

        Uses last two CII readings. Delta ≥3 = escalating, ≤-3 = de-escalating.
        """
        history = self._cii_history.get(country_code, [])
        if len(history) < 2:
            return "stable"
        prev = history[-2][1]
        current = history[-1][1]
        delta = current - prev
        if delta >= 3:
            return "escalating"
        elif delta <= -3:
            return "de-escalating"
        return "stable"

    # ── Internal ──

    def check_silent_divergence(
        self, country_code: str, news_velocity_24h: int,
    ) -> Signal | None:
        """Detect silent divergence: CII rising but news volume flat or dropping.

        This pattern indicates covert escalation — something is happening but
        it's not being reported (censorship, fog of war, deliberate silence).
        """
        history = self._cii_history.get(country_code, [])
        if len(history) < 2:
            return None

        prev_score = history[-2][1]
        current_score = history[-1][1]
        delta = current_score - prev_score

        # CII rising by ≥5 but news velocity LOW (≤3 events/24h)
        if delta >= 5 and news_velocity_24h <= 3:
            signal = Signal(
                signal_type=SignalType.SILENT_DIVERGENCE,
                severity=Severity.HIGH if delta >= 10 else Severity.MEDIUM,
                country_code=country_code,
                summary=(
                    f"SILENT DIVERGENCE [{country_code}]: CII +{delta:.0f} "
                    f"({prev_score:.0f}→{current_score:.0f}) but only "
                    f"{news_velocity_24h} events in 24h"
                ),
                metadata={
                    "cii_delta": delta,
                    "news_velocity": news_velocity_24h,
                    "prev_cii": prev_score,
                    "current_cii": current_score,
                },
                source="correlation_engine",
            )
            result = self.ingest_signal(signal)
            logger.info("[Correlation] %s", signal.summary)
            return signal
        return None

    def check_commodity_shock(
        self,
        commodity: str,
        current_price: float,
        previous_price: float,
    ) -> Signal | None:
        """Detect commodity price shock: >10% move in any tracked commodity.

        Oil, gold, gas spikes often precede geopolitical escalations or
        indicate sanctions/supply disruption.
        """
        if previous_price <= 0:
            return None

        change_pct = ((current_price - previous_price) / previous_price) * 100

        if abs(change_pct) >= 10:
            direction = "surge" if change_pct > 0 else "crash"
            severity = Severity.CRITICAL if abs(change_pct) >= 20 else Severity.HIGH

            signal = Signal(
                signal_type=SignalType.COMMODITY_SHOCK,
                severity=severity,
                country_code="GLOBAL",
                summary=(
                    f"COMMODITY SHOCK: {commodity} {direction} "
                    f"{change_pct:+.1f}% (${previous_price:.2f}→${current_price:.2f})"
                ),
                metadata={
                    "commodity": commodity,
                    "change_pct": round(change_pct, 2),
                    "current_price": current_price,
                    "previous_price": previous_price,
                    "direction": direction,
                },
                source="commodity_tracker",
            )
            self.ingest_signal(signal)
            logger.info("[Correlation] %s", signal.summary)
            return signal
        return None

    def check_sentiment_split(
        self,
        country_code: str,
        positive_sources: int,
        negative_sources: int,
        topic: str = "",
    ) -> Signal | None:
        """Detect sentiment split: same event with sharply opposing coverage.

        Indicates propaganda, spin, or genuinely contested interpretation.
        Requires ≥3 sources on each side to avoid noise.
        """
        total = positive_sources + negative_sources
        if total < 6 or positive_sources < 3 or negative_sources < 3:
            return None

        # Split ratio: how evenly divided (1.0 = perfect 50/50 split)
        minor = min(positive_sources, negative_sources)
        split_ratio = minor / (total / 2)

        if split_ratio >= 0.6:  # At least 60% balanced = genuine split
            signal = Signal(
                signal_type=SignalType.SENTIMENT_SPLIT,
                severity=Severity.HIGH if split_ratio >= 0.8 else Severity.MEDIUM,
                country_code=country_code,
                summary=(
                    f"SENTIMENT SPLIT [{country_code}]: {positive_sources} positive vs "
                    f"{negative_sources} negative sources"
                    + (f" on '{topic}'" if topic else "")
                    + f" (split ratio {split_ratio:.0%})"
                ),
                metadata={
                    "positive_sources": positive_sources,
                    "negative_sources": negative_sources,
                    "split_ratio": round(split_ratio, 2),
                    "topic": topic,
                },
                source="sentiment_tracker",
            )
            self.ingest_signal(signal)
            logger.info("[Correlation] %s", signal.summary)
            return signal
        return None

    def _check_convergence(
        self, country_code: str, now: float,
    ) -> CorrelationAlert | None:
        """Check if 3+ different signal types have fired for this country in window."""
        window_cutoff = now - FUSION_WINDOW
        recent_signals = [
            s for s in self._country_signals.get(country_code, [])
            if s.timestamp > window_cutoff
        ]

        # Count unique signal types
        types_seen: dict[str, Signal] = {}
        for s in recent_signals:
            types_seen.setdefault(s.signal_type.value, s)

        if len(types_seen) < 3:
            return None

        # Convergence detected!
        type_list = sorted(types_seen.keys())
        alert_id = hashlib.md5(
            f"conv-{country_code}-{'-'.join(type_list)}".encode()
        ).hexdigest()[:12]

        # Check if we already have a similar alert
        for existing in self._alerts:
            if existing.alert_id == alert_id and now - existing.timestamp < FUSION_WINDOW:
                # Merge into existing alert
                existing.merged_count += 1
                return None

        # Determine severity based on signal count and individual severities
        if len(types_seen) >= 5:
            severity = Severity.CRITICAL
        elif len(types_seen) >= 4:
            severity = Severity.HIGH
        else:
            # Use highest severity from component signals
            sev_order = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
            max_sev = max(types_seen.values(), key=lambda s: sev_order.get(s.severity, 0))
            severity = max_sev.severity

        summary = (
            f"CONVERGENCE [{country_code}]: {len(types_seen)} signal types correlated — "
            f"{', '.join(type_list)}"
        )

        alert = CorrelationAlert(
            alert_id=alert_id,
            signal_types=type_list,
            severity=severity,
            country_code=country_code,
            summary=summary,
            signals=list(types_seen.values()),
            timestamp=now,
        )

        self._alerts.append(alert)

        # Prune old alerts
        prune_cutoff = now - PRUNE_AGE
        self._alerts = self._alerts[-MAX_ALERTS:]
        self._alerts = [a for a in self._alerts if a.timestamp > prune_cutoff]

        logger.info("[Correlation] %s", summary)
        return alert
