"""
XDART-Φ × XHEART — Financial Market Intelligence

Real-time market data feed for Αίολος. Converts numbers into
intelligence signals that corroborate (or contradict) text-based patterns.

"Λέξεις ψεύδονται. Αριθμοί μόνο αντιδρούν."

Data sources (all FREE, no API key):
  - yfinance: VIX, S&P500, Oil (Brent), Gold, BTC, EUR/USD, 10Y Treasury
  - Derived: Fear level detection, flash-crash detection, anomaly flags

Architecture:
  - MarketDataCollector pulls snapshots every 15 min (aligned with RSS cycle)
  - Market anomalies (VIX spike, oil crash, etc.) produce PatternSignals
  - Signals feed into PatternAccumulator alongside text-based signals
  - Combined: text spike + financial anomaly = high-confidence alert

Integration:
  - Collector calls MarketDataCollector.poll() every realtime cycle
  - Anomalies fed to ProactiveEngine.feed_signal() as 'financial_anomaly' type
  - Chat mode: Αίολος queries via get_market_brief()
  - Pipeline: context enrichment via get_market_context()

THIS IS PART OF ΑΙΟΛΟΣ — not a separate module.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("xdart.perception.financial_feeds")

# ── Lazy yfinance import (avoid startup penalty) ──
_yf = None


def _get_yf():
    global _yf
    if _yf is None:
        try:
            import yfinance
            _yf = yfinance
            logger.info("[FinancialFeeds] yfinance loaded")
        except ImportError:
            logger.warning("[FinancialFeeds] yfinance not installed — financial feeds disabled")
            _yf = False
    return _yf if _yf is not False else None


# ══════════════════════════════════════════════════════════════════════════════
#  MARKET TICKERS — what we track and threshold for anomaly detection
# ══════════════════════════════════════════════════════════════════════════════

# Each ticker has:
#   symbol: yfinance ticker
#   name: human-readable
#   anomaly_type: 'spike_above' or 'drop_below' or 'change_pct'
#   threshold: value that triggers anomaly signal
#   weight: signal weight when anomaly fires (for PatternAccumulator)

MARKET_TICKERS = [
    {
        "symbol": "^VIX",
        "name": "VIX (Fear Index)",
        "anomaly_rules": [
            {"type": "spike_above", "threshold": 25.0, "label": "elevated_fear", "weight": 0.45},
            {"type": "spike_above", "threshold": 35.0, "label": "extreme_fear", "weight": 0.60},
        ],
    },
    {
        "symbol": "^GSPC",
        "name": "S&P 500",
        "anomaly_rules": [
            {"type": "change_pct", "threshold": -2.0, "label": "sp500_selloff", "weight": 0.40},
            {"type": "change_pct", "threshold": -4.0, "label": "sp500_crash", "weight": 0.55},
        ],
    },
    {
        "symbol": "BZ=F",
        "name": "Brent Crude Oil",
        "anomaly_rules": [
            {"type": "change_pct", "threshold": 8.0, "label": "oil_spike", "weight": 0.45},
            {"type": "change_pct", "threshold": -8.0, "label": "oil_crash", "weight": 0.40},
            {"type": "spike_above", "threshold": 100.0, "label": "oil_crisis_level", "weight": 0.50},
        ],
    },
    {
        "symbol": "GC=F",
        "name": "Gold",
        "anomaly_rules": [
            {"type": "change_pct", "threshold": 3.0, "label": "gold_flight_to_safety", "weight": 0.35},
        ],
    },
    {
        "symbol": "BTC-USD",
        "name": "Bitcoin",
        "anomaly_rules": [
            {"type": "change_pct", "threshold": -10.0, "label": "btc_crash", "weight": 0.30},
            {"type": "change_pct", "threshold": 15.0, "label": "btc_mania", "weight": 0.25},
        ],
    },
    {
        "symbol": "EURUSD=X",
        "name": "EUR/USD",
        "anomaly_rules": [
            {"type": "change_pct", "threshold": 2.0, "label": "eurusd_volatility", "weight": 0.30},
            {"type": "change_pct", "threshold": -2.0, "label": "eurusd_volatility", "weight": 0.30},
        ],
    },
    {
        "symbol": "^TNX",
        "name": "10-Year Treasury Yield",
        "anomaly_rules": [
            {"type": "spike_above", "threshold": 5.0, "label": "yield_crisis", "weight": 0.45},
            {"type": "change_pct", "threshold": 10.0, "label": "yield_spike", "weight": 0.40},
        ],
    },
    {
        "symbol": "DX-Y.NYB",
        "name": "US Dollar Index",
        "anomaly_rules": [
            {"type": "change_pct", "threshold": 2.0, "label": "dollar_spike", "weight": 0.35},
            {"type": "change_pct", "threshold": -2.0, "label": "dollar_crash", "weight": 0.35},
        ],
    },
]

# ── Cooldowns — don't repeat the same anomaly signal within window ──
ANOMALY_COOLDOWN_SECONDS = 3600  # 1 hour between same-type signals


class MarketSnapshot:
    """A point-in-time market data snapshot."""

    def __init__(self):
        self.timestamp: float = time.time()
        self.data: dict[str, dict] = {}  # symbol → {price, change_pct, prev_close, ...}
        self.anomalies: list[dict] = []  # detected anomalies this snapshot

    def to_dict(self) -> dict:
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "tickers": self.data,
            "anomalies": self.anomalies,
        }


class MarketDataCollector:
    """Collects real-time market data and detects anomalies.

    Runs alongside the perception collector on the same 15-min cadence.
    Anomalies generate headlines fed into PatternAccumulator.
    """

    def __init__(self):
        self._last_snapshot: MarketSnapshot | None = None
        self._anomaly_cooldowns: dict[str, float] = {}  # label → last_fired_at
        self._total_polls = 0
        self._total_anomalies = 0
        self._history: list[MarketSnapshot] = []  # last N snapshots for trend analysis
        self._max_history = 24  # 24 × 15min = 6 hours of history

    def poll(self) -> MarketSnapshot:
        """Poll all market tickers and detect anomalies.

        Returns MarketSnapshot with current data and any anomalies.
        Called by collector every 15 minutes.
        """
        yf = _get_yf()
        if not yf:
            return MarketSnapshot()

        snapshot = MarketSnapshot()
        self._total_polls += 1
        now = time.time()

        # Fetch all tickers in one batch call (efficient)
        symbols = [t["symbol"] for t in MARKET_TICKERS]
        try:
            tickers = yf.Tickers(" ".join(symbols))
        except Exception as e:
            logger.warning("[FinancialFeeds] Failed to create tickers batch: %s", e)
            return snapshot

        for ticker_config in MARKET_TICKERS:
            symbol = ticker_config["symbol"]
            name = ticker_config["name"]

            try:
                ticker = tickers.tickers.get(symbol)
                if not ticker:
                    continue

                info = ticker.fast_info
                current_price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)

                if current_price is None:
                    continue

                change_pct = 0.0
                if prev_close and prev_close > 0:
                    change_pct = ((current_price - prev_close) / prev_close) * 100

                snapshot.data[symbol] = {
                    "name": name,
                    "price": round(current_price, 2),
                    "prev_close": round(prev_close, 2) if prev_close else None,
                    "change_pct": round(change_pct, 2),
                }

                # Check anomaly rules
                for rule in ticker_config.get("anomaly_rules", []):
                    anomaly = self._check_anomaly(
                        symbol=symbol,
                        name=name,
                        price=current_price,
                        change_pct=change_pct,
                        rule=rule,
                        now=now,
                    )
                    if anomaly:
                        snapshot.anomalies.append(anomaly)
                        self._total_anomalies += 1

            except Exception as e:
                logger.debug("[FinancialFeeds] Error fetching %s: %s", symbol, e)

        self._last_snapshot = snapshot
        self._history.append(snapshot)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        if snapshot.data:
            logger.info("[FinancialFeeds] Poll #%d: %d tickers, %d anomalies",
                        self._total_polls, len(snapshot.data), len(snapshot.anomalies))

        return snapshot

    def _check_anomaly(
        self,
        symbol: str,
        name: str,
        price: float,
        change_pct: float,
        rule: dict,
        now: float,
    ) -> dict | None:
        """Check if a market value triggers an anomaly rule."""
        label = rule["label"]

        # Cooldown check
        last_fired = self._anomaly_cooldowns.get(label, 0)
        if (now - last_fired) < ANOMALY_COOLDOWN_SECONDS:
            return None

        triggered = False
        anomaly_type = rule["type"]
        threshold = rule["threshold"]

        if anomaly_type == "spike_above" and price >= threshold:
            triggered = True
        elif anomaly_type == "drop_below" and price <= threshold:
            triggered = True
        elif anomaly_type == "change_pct":
            if threshold > 0 and change_pct >= threshold:
                triggered = True
            elif threshold < 0 and change_pct <= threshold:
                triggered = True

        if not triggered:
            return None

        self._anomaly_cooldowns[label] = now

        headline = self._format_anomaly_headline(name, label, price, change_pct)
        logger.info("[FinancialFeeds] ANOMALY DETECTED: %s | price=%.2f change=%.2f%% threshold=%s",
                    label, price, change_pct, threshold)

        return {
            "symbol": symbol,
            "name": name,
            "label": label,
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "threshold": threshold,
            "weight": rule.get("weight", 0.30),
            "headline": headline,
        }

    def _format_anomaly_headline(
        self,
        name: str,
        label: str,
        price: float,
        change_pct: float,
    ) -> str:
        """Generate a headline for a market anomaly (fed into PatternAccumulator)."""
        headlines = {
            "elevated_fear": f"[MARKET] VIX at {price:.1f} — elevated market fear",
            "extreme_fear": f"[MARKET] VIX at {price:.1f} — EXTREME fear / panic territory",
            "sp500_selloff": f"[MARKET] S&P 500 down {abs(change_pct):.1f}% — significant selloff",
            "sp500_crash": f"[MARKET] S&P 500 down {abs(change_pct):.1f}% — market crash territory",
            "oil_spike": f"[MARKET] Brent crude up {change_pct:.1f}% to ${price:.2f} — supply crisis signal",
            "oil_crash": f"[MARKET] Brent crude down {abs(change_pct):.1f}% to ${price:.2f} — demand collapse signal",
            "oil_crisis_level": f"[MARKET] Brent crude at ${price:.2f} — crisis price level",
            "gold_flight_to_safety": f"[MARKET] Gold up {change_pct:.1f}% — flight to safety",
            "btc_crash": f"[MARKET] Bitcoin down {abs(change_pct):.1f}% — crypto panic",
            "btc_mania": f"[MARKET] Bitcoin up {change_pct:.1f}% — speculative mania",
            "eurusd_volatility": f"[MARKET] EUR/USD moved {change_pct:+.1f}% — currency stress",
            "yield_crisis": f"[MARKET] 10Y yield at {price:.2f}% — borrowing cost crisis",
            "yield_spike": f"[MARKET] 10Y yield spiked {change_pct:.1f}% — bond market stress",
            "dollar_spike": f"[MARKET] US Dollar Index up {change_pct:.1f}% — dollar strength surge",
            "dollar_crash": f"[MARKET] US Dollar Index down {abs(change_pct):.1f}% — dollar confidence collapse",
        }
        return headlines.get(label, f"[MARKET] {name} anomaly: {label} at {price:.2f} ({change_pct:+.1f}%)")

    # ══════════════════════════════════════════════════════════════
    #  QUERY INTERFACE — for Αίολος chat mode + pipeline context
    # ══════════════════════════════════════════════════════════════

    def get_market_brief(self) -> str:
        """Human-readable market briefing for Αίολος.

        Used in chat mode when user asks about markets.
        """
        if not self._last_snapshot or not self._last_snapshot.data:
            return "No market data available yet — financial feeds not polled this session."

        snap = self._last_snapshot
        ts = datetime.fromtimestamp(snap.timestamp, tz=timezone.utc)
        lines = [f"MARKET SNAPSHOT — {ts:%Y-%m-%d %H:%M UTC}", ""]

        for symbol, data in snap.data.items():
            arrow = "▲" if data["change_pct"] >= 0 else "▼"
            lines.append(
                f"  {data['name']}: {data['price']:.2f} "
                f"{arrow} {data['change_pct']:+.2f}%"
            )

        # Fear level interpretation
        vix_data = snap.data.get("^VIX")
        if vix_data:
            vix = vix_data["price"]
            if vix >= 35:
                lines.append(f"\n  🔴 FEAR LEVEL: EXTREME (VIX={vix:.1f})")
            elif vix >= 25:
                lines.append(f"\n  🟠 FEAR LEVEL: ELEVATED (VIX={vix:.1f})")
            elif vix >= 18:
                lines.append(f"\n  🟡 FEAR LEVEL: MODERATE (VIX={vix:.1f})")
            else:
                lines.append(f"\n  🟢 FEAR LEVEL: CALM (VIX={vix:.1f})")

        if snap.anomalies:
            lines.append(f"\nANOMALIES DETECTED ({len(snap.anomalies)}):")
            for a in snap.anomalies:
                lines.append(f"  ⚠ {a['headline']}")

        return "\n".join(lines)

    def get_market_context(self) -> str:
        """Market context string for pipeline enrichment.

        Shorter than brief — designed for injection into LLM prompts.
        """
        if not self._last_snapshot or not self._last_snapshot.data:
            return ""

        snap = self._last_snapshot
        parts = []
        for symbol, data in snap.data.items():
            parts.append(f"{data['name']}={data['price']:.2f}({data['change_pct']:+.1f}%)")

        anomaly_str = ""
        if snap.anomalies:
            anomaly_str = " | ANOMALIES: " + "; ".join(a["label"] for a in snap.anomalies)

        return f"MARKETS [{datetime.fromtimestamp(snap.timestamp, tz=timezone.utc):%H:%M UTC}]: " + ", ".join(parts) + anomaly_str

    def get_fear_level(self) -> tuple[str, float]:
        """Get current fear level as (label, VIX_value).

        Returns ("unknown", 0.0) if no VIX data available.
        """
        if not self._last_snapshot:
            return ("unknown", 0.0)
        vix_data = self._last_snapshot.data.get("^VIX")
        if not vix_data:
            return ("unknown", 0.0)
        vix = vix_data["price"]
        if vix >= 35:
            return ("extreme", vix)
        elif vix >= 25:
            return ("elevated", vix)
        elif vix >= 18:
            return ("moderate", vix)
        else:
            return ("calm", vix)

    def stats(self) -> dict:
        return {
            "total_polls": self._total_polls,
            "total_anomalies": self._total_anomalies,
            "tickers_tracked": len(MARKET_TICKERS),
            "history_snapshots": len(self._history),
            "last_poll": (
                datetime.fromtimestamp(self._last_snapshot.timestamp, tz=timezone.utc).isoformat()
                if self._last_snapshot else None
            ),
        }
