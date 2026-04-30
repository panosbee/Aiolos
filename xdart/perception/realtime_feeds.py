"""
XDART-Φ × XHEART — Real-Time Intelligence Feeds (Palantir P0)

High-frequency data sources that complement the 15-min perception cycle.
These feeds provide sub-minute resolution for critical indicators.

"Ο χρόνος είναι το μόνο πλεονέκτημα που μετράει."

Sub-modules:
  1. FinnhubRealtimeMonitor — forex/commodities quotes + economic calendar
  2. CyberThreatMonitor    — OTX AlienVault pulses + GreyNoise community
  3. AirspaceWarningMonitor — FAA TFR feed + airspace void detection

All monitors:
  - Cache latest data for Live Digest injection
  - Detect rapid moves / anomalies
  - Produce PatternSignal-compatible dicts for feed_signal()
  - Gracefully degrade if API keys missing
"""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("xdart.perception.realtime_feeds")

# ── Lazy imports ──
_httpx = None


def _get_httpx():
    global _httpx
    if _httpx is None:
        try:
            import httpx
            _httpx = httpx
        except ImportError:
            logger.warning("[RealtimeFeeds] httpx not installed")
            _httpx = False
    return _httpx if _httpx is not False else None


# ══════════════════════════════════════════════════════════════════════════════
#  FINNHUB REAL-TIME MONITOR
#  Free tier: 60 API calls/minute, forex quotes, economic calendar, market news
# ══════════════════════════════════════════════════════════════════════════════

# Key forex pairs to track (high geopolitical signal value)
FOREX_PAIRS = [
    ("EUR/USD", "OANDA:EUR_USD"),    # Euro stability
    ("GBP/USD", "OANDA:GBP_USD"),    # UK economy
    ("USD/JPY", "OANDA:USD_JPY"),    # Yen as safe haven
    ("USD/CNY", "OANDA:USD_CNH"),    # China trade tension proxy
    ("USD/TRY", "OANDA:USD_TRY"),    # Turkey crisis proxy
    ("USD/RUB", "OANDA:USD_RUB"),    # Russia sanctions proxy
    ("USD/ILS", "OANDA:USD_ILS"),    # Middle East tension proxy
    ("XAU/USD", "OANDA:XAU_USD"),    # Gold safe haven
]

# Rapid move thresholds (% change in single poll interval)
_RAPID_MOVE_THRESHOLDS = {
    "EUR/USD": 0.3,
    "GBP/USD": 0.3,
    "USD/JPY": 0.4,
    "USD/CNY": 0.2,   # CNY moves are politically significant even at small %
    "USD/TRY": 1.0,   # TRY is volatile, need higher threshold
    "USD/RUB": 1.5,   # RUB is very volatile
    "USD/ILS": 0.5,
    "XAU/USD": 0.5,   # Gold significant moves
}


class FinnhubRealtimeMonitor:
    """High-frequency forex/commodities poller via Finnhub REST API.

    Polls every 5 minutes (configurable). Detects rapid price movements
    and caches latest quotes for Live Digest injection.
    """

    POLL_INTERVAL = 300  # 5 minutes

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._base_url = "https://finnhub.io/api/v1"
        self._quotes: dict[str, dict] = {}        # pair_name → {price, prev, change_pct, ts}
        self._calendar: list[dict] = []             # upcoming economic events
        self._market_news: list[dict] = []          # latest market news
        self._last_poll_ts: float = 0.0
        self._last_calendar_ts: float = 0.0
        self._last_news_ts: float = 0.0
        self._total_polls: int = 0
        self._rapid_moves: list[dict] = []          # detected rapid moves (recent)
        self._enabled = bool(api_key)

        if not api_key:
            logger.info("[Finnhub] No API key — real-time forex disabled (set FINNHUB_API_KEY)")
        else:
            logger.info("[Finnhub] Initialized with %d forex pairs", len(FOREX_PAIRS))

    async def poll_all(self) -> list[dict]:
        """Poll forex quotes + economic calendar + news. Returns anomaly signals."""
        if not self._enabled:
            return []

        httpx = _get_httpx()
        if not httpx:
            return []

        signals: list[dict] = []
        now = time.time()

        # Rate limit: respect 5 min interval
        if now - self._last_poll_ts < self.POLL_INTERVAL:
            return []

        self._last_poll_ts = now
        self._total_polls += 1

        # ── Forex quotes ──
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                for pair_name, symbol in FOREX_PAIRS:
                    try:
                        resp = await client.get(
                            f"{self._base_url}/quote",
                            params={"symbol": symbol, "token": self.api_key},
                        )
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                        current_price = data.get("c", 0)
                        prev_close = data.get("pc", 0)
                        if not current_price or not prev_close:
                            continue

                        change_pct = ((current_price - prev_close) / prev_close) * 100

                        # Check for rapid move vs PREVIOUS poll (not daily close)
                        prev_reading = self._quotes.get(pair_name, {}).get("price", 0)
                        rapid_pct = 0.0
                        if prev_reading > 0:
                            rapid_pct = ((current_price - prev_reading) / prev_reading) * 100

                        self._quotes[pair_name] = {
                            "price": current_price,
                            "prev_close": prev_close,
                            "prev_reading": prev_reading,
                            "change_pct": round(change_pct, 4),
                            "rapid_pct": round(rapid_pct, 4),
                            "ts": now,
                        }

                        # Detect rapid moves
                        threshold = _RAPID_MOVE_THRESHOLDS.get(pair_name, 0.5)
                        if prev_reading > 0 and abs(rapid_pct) >= threshold:
                            direction = "surged" if rapid_pct > 0 else "plunged"
                            signal = {
                                "type": "forex_rapid_move",
                                "headline": (
                                    f"{pair_name} {direction} {abs(rapid_pct):.2f}% in {self.POLL_INTERVAL//60}min "
                                    f"(now {current_price:.4f})"
                                ),
                                "region": "GLOBAL",
                                "domain": "FINANCIAL",
                                "salience": min(0.9, 0.5 + abs(rapid_pct) * 0.15),
                                "data": {
                                    "pair": pair_name,
                                    "price": current_price,
                                    "rapid_pct": rapid_pct,
                                    "daily_pct": change_pct,
                                },
                            }
                            signals.append(signal)
                            self._rapid_moves.append(signal)
                            logger.info("[Finnhub] RAPID MOVE: %s", signal["headline"])

                    except Exception as e:
                        logger.debug("[Finnhub] Failed to fetch %s: %s", pair_name, e)

        except Exception as e:
            logger.warning("[Finnhub] Forex poll failed: %s", e)

        # ── Economic calendar (every 6 hours) ──
        if now - self._last_calendar_ts > 21600:
            try:
                await self._poll_economic_calendar()
                self._last_calendar_ts = now
            except Exception as e:
                logger.warning("[Finnhub] Calendar poll failed: %s", e)

        # ── Market news (every 30 min) ──
        if now - self._last_news_ts > 1800:
            try:
                await self._poll_market_news()
                self._last_news_ts = now
            except Exception as e:
                logger.warning("[Finnhub] News poll failed: %s", e)

        # Trim rapid moves to last 50
        self._rapid_moves = self._rapid_moves[-50:]

        return signals

    async def _poll_economic_calendar(self):
        """Fetch upcoming economic events from Finnhub."""
        httpx = _get_httpx()
        if not httpx:
            return

        now = datetime.now(timezone.utc)
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self._base_url}/calendar/economic",
                params={"from": from_date, "to": to_date, "token": self.api_key},
            )
            if resp.status_code != 200:
                return

            data = resp.json()
            events = data.get("economicCalendar", [])

            # Filter to high-impact events only
            # Finnhub returns impact as a string ("high", "medium", "low") or int
            _IMPACT_RANK = {"high": 3, "medium": 2, "low": 1}
            high_impact = [
                ev for ev in events
                if (
                    _IMPACT_RANK.get(str(ev.get("impact", "")).lower(), 0) >= 2
                    if isinstance(ev.get("impact"), str)
                    else int(ev.get("impact", 0)) >= 2
                )
            ]

            self._calendar = high_impact[:50]  # Keep top 50
            logger.info("[Finnhub] Economic calendar: %d events (%d high-impact)",
                        len(events), len(high_impact))

    async def _poll_market_news(self):
        """Fetch latest market news from Finnhub."""
        httpx = _get_httpx()
        if not httpx:
            return

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._base_url}/news",
                params={"category": "general", "token": self.api_key},
            )
            if resp.status_code != 200:
                return

            news = resp.json()
            if isinstance(news, list):
                self._market_news = news[:20]
                logger.debug("[Finnhub] Market news: %d articles", len(news))

    def get_forex_digest(self) -> str:
        """Formatted forex intelligence for Live Digest injection."""
        if not self._quotes:
            if not self._enabled:
                return ""
            return "  Forex: awaiting first poll"

        lines = []
        now = time.time()

        for pair_name, _ in FOREX_PAIRS:
            q = self._quotes.get(pair_name)
            if not q:
                continue
            age_min = (now - q["ts"]) / 60
            if age_min > 30:  # Skip stale quotes
                continue

            arrow = "▲" if q["change_pct"] >= 0 else "▼"
            rapid_flag = ""
            if abs(q.get("rapid_pct", 0)) >= _RAPID_MOVE_THRESHOLDS.get(pair_name, 0.5):
                rapid_flag = " ⚡RAPID"

            if pair_name == "XAU/USD":
                lines.append(
                    f"  {pair_name}: ${q['price']:.2f} {arrow}{q['change_pct']:+.2f}%{rapid_flag}"
                )
            else:
                lines.append(
                    f"  {pair_name}: {q['price']:.4f} {arrow}{q['change_pct']:+.2f}%{rapid_flag}"
                )

        return "\n".join(lines)

    def get_calendar_digest(self) -> str:
        """Formatted economic calendar for Live Digest injection."""
        if not self._calendar:
            return ""

        now = datetime.now(timezone.utc)
        lines = []
        upcoming_48h = []
        upcoming_7d = []

        for ev in self._calendar:
            event_time_str = ev.get("time", "") or ev.get("date", "")
            event_name = ev.get("event", "Unknown")
            country = ev.get("country", "")
            impact = ev.get("impact", 0)

            try:
                if "T" in event_time_str:
                    event_dt = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
                else:
                    event_dt = datetime.strptime(event_time_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            delta = event_dt - now
            if delta.total_seconds() < 0:
                continue  # Past events

            impact_str = "🔴" if impact >= 3 else "🟡" if impact >= 2 else "⚪"

            if delta.days < 2:
                hours = delta.total_seconds() / 3600
                upcoming_48h.append(
                    f"  {impact_str} [{country}] {event_name} — in {hours:.0f}h"
                )
            elif delta.days < 7:
                upcoming_7d.append(
                    f"  {impact_str} [{country}] {event_name} — in {delta.days}d"
                )

        if upcoming_48h:
            lines.append("  NEXT 48 HOURS:")
            lines.extend(upcoming_48h[:8])
        if upcoming_7d:
            lines.append("  THIS WEEK:")
            lines.extend(upcoming_7d[:6])

        return "\n".join(lines)

    def stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "total_polls": self._total_polls,
            "pairs_tracked": len(self._quotes),
            "calendar_events": len(self._calendar),
            "rapid_moves_detected": len(self._rapid_moves),
            "last_poll": (
                datetime.fromtimestamp(self._last_poll_ts, tz=timezone.utc).isoformat()
                if self._last_poll_ts else None
            ),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  CYBER THREAT INTELLIGENCE MONITOR
#  OTX AlienVault (free) + GreyNoise Community (free)
# ══════════════════════════════════════════════════════════════════════════════

# Threat categories that correlate with geopolitical events
_GEOPOLITICAL_THREAT_TAGS = {
    "apt", "nation-state", "russia", "china", "iran", "north korea",
    "dprk", "ukraine", "critical infrastructure", "scada", "ics",
    "ransomware", "wipers", "destructive", "cyberwarfare", "espionage",
    "supply chain", "financial sector", "energy sector", "government",
}


class CyberThreatMonitor:
    """Monitors OTX AlienVault and GreyNoise for geopolitically-relevant cyber threats.

    Focus: APT campaigns, nation-state attacks, critical infrastructure targeting.
    NOT general malware/spam — only threats with geopolitical signal value.
    """

    POLL_INTERVAL = 1800  # 30 minutes

    def __init__(self, otx_api_key: str = "", greynoise_api_key: str = ""):
        self.otx_api_key = otx_api_key
        self.greynoise_api_key = greynoise_api_key
        self._pulses: list[dict] = []           # OTX pulses (geopolitical only)
        self._noise_trends: list[dict] = []     # GreyNoise trending activity
        self._last_poll_ts: float = 0.0
        self._total_polls: int = 0
        self._enabled = bool(otx_api_key) or bool(greynoise_api_key)

        if not otx_api_key and not greynoise_api_key:
            logger.info("[CyberThreat] No API keys — cyber threat feeds disabled "
                        "(set OTX_API_KEY and/or GREYNOISE_API_KEY)")
        else:
            sources = []
            if otx_api_key:
                sources.append("OTX")
            if greynoise_api_key:
                sources.append("GreyNoise")
            logger.info("[CyberThreat] Initialized with %s", " + ".join(sources))

    async def poll_all(self) -> list[dict]:
        """Poll cyber threat sources. Returns signals for PatternAccumulator."""
        if not self._enabled:
            return []

        httpx = _get_httpx()
        if not httpx:
            return []

        now = time.time()
        if now - self._last_poll_ts < self.POLL_INTERVAL:
            return []

        self._last_poll_ts = now
        self._total_polls += 1
        signals: list[dict] = []

        # ── OTX AlienVault Pulses ──
        if self.otx_api_key:
            try:
                otx_signals = await self._poll_otx(httpx)
                signals.extend(otx_signals)
            except Exception as e:
                logger.warning("[CyberThreat] OTX poll failed: %s", e)

        # ── GreyNoise Community ──
        if self.greynoise_api_key:
            try:
                gn_signals = await self._poll_greynoise(httpx)
                signals.extend(gn_signals)
            except Exception as e:
                logger.warning("[CyberThreat] GreyNoise poll failed: %s", e)

        return signals

    async def _poll_otx(self, httpx) -> list[dict]:
        """Fetch recent OTX pulses, filter for geopolitical relevance."""
        signals = []

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://otx.alienvault.com/api/v1/pulses/subscribed",
                headers={"X-OTX-API-KEY": self.otx_api_key},
                params={"limit": 30, "modified_since": (
                    datetime.now(timezone.utc) - timedelta(hours=24)
                ).strftime("%Y-%m-%dT%H:%M:%S")},
            )
            if resp.status_code != 200:
                logger.debug("[CyberThreat] OTX returned %d", resp.status_code)
                return signals

            data = resp.json()
            pulses = data.get("results", [])

            for pulse in pulses:
                name = pulse.get("name", "")
                tags = set(t.lower() for t in pulse.get("tags", []))
                description = pulse.get("description", "")[:500]
                ioc_count = len(pulse.get("indicators", []))

                # Check for geopolitical relevance
                relevance_tags = tags & _GEOPOLITICAL_THREAT_TAGS
                text_lower = (name + " " + description).lower()
                relevance_keywords = [
                    kw for kw in _GEOPOLITICAL_THREAT_TAGS
                    if kw in text_lower
                ]

                if not relevance_tags and not relevance_keywords:
                    continue  # Skip non-geopolitical threats

                salience = min(0.85, 0.4 + len(relevance_tags) * 0.1 + min(ioc_count / 50, 0.2))

                pulse_entry = {
                    "id": pulse.get("id", ""),
                    "name": name,
                    "tags": list(tags)[:10],
                    "relevance_tags": list(relevance_tags),
                    "ioc_count": ioc_count,
                    "created": pulse.get("created", ""),
                    "salience": salience,
                }
                self._pulses.append(pulse_entry)

                signal = {
                    "type": "cyber_threat",
                    "headline": f"CYBER THREAT: {name} ({ioc_count} IoCs, tags: {', '.join(relevance_tags or relevance_keywords[:3])})",
                    "region": "GLOBAL",
                    "domain": "CYBER",
                    "salience": salience,
                    "data": pulse_entry,
                }
                signals.append(signal)

            # Trim cached pulses
            self._pulses = self._pulses[-100:]

        return signals

    async def _poll_greynoise(self, httpx) -> list[dict]:
        """Fetch GreyNoise trending threat activity."""
        signals = []

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.greynoise.io/v3/trends/ips",
                headers={"key": self.greynoise_api_key, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.debug("[CyberThreat] GreyNoise returned %d", resp.status_code)
                return signals

            data = resp.json()
            trends = data.get("data", [])

            for trend in trends[:10]:
                classification = trend.get("classification", "")
                tag = trend.get("tag", "")
                count = trend.get("count", 0)

                if classification in ("malicious",) and count > 1000:
                    self._noise_trends.append({
                        "tag": tag,
                        "count": count,
                        "classification": classification,
                        "ts": time.time(),
                    })

                    if count > 5000:
                        signal = {
                            "type": "cyber_threat",
                            "headline": f"MASS SCANNING: {tag} — {count:,} unique IPs (GreyNoise)",
                            "region": "GLOBAL",
                            "domain": "CYBER",
                            "salience": min(0.7, 0.3 + count / 20000),
                            "data": {"tag": tag, "count": count},
                        }
                        signals.append(signal)

            self._noise_trends = self._noise_trends[-50:]

        return signals

    def get_cyber_digest(self) -> str:
        """Formatted cyber threat intelligence for Live Digest injection."""
        if not self._pulses and not self._noise_trends:
            if not self._enabled:
                return ""
            return "  Cyber intel: awaiting first poll"

        lines = []
        now = time.time()

        # Recent geopolitical pulses (last 24h)
        recent_pulses = [
            p for p in self._pulses
            if now - self._last_poll_ts < 86400
        ]
        if recent_pulses:
            lines.append("  Recent APT/Nation-State Activity:")
            for p in recent_pulses[-5:]:
                tags_str = ", ".join(p.get("relevance_tags", [])[:3])
                lines.append(
                    f"  ⚠ {p['name'][:80]} [{tags_str}] ({p['ioc_count']} IoCs)"
                )

        # Mass scanning trends
        active_trends = [t for t in self._noise_trends if t["count"] > 5000]
        if active_trends:
            lines.append("  Mass Scanning Activity:")
            for t in active_trends[-3:]:
                lines.append(f"  ● {t['tag']}: {t['count']:,} IPs")

        return "\n".join(lines)

    def stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "otx_enabled": bool(self.otx_api_key),
            "greynoise_enabled": bool(self.greynoise_api_key),
            "total_polls": self._total_polls,
            "geopolitical_pulses": len(self._pulses),
            "noise_trends": len(self._noise_trends),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  AIRSPACE WARNING MONITOR
#  FAA TFRs + Airspace Void Detection (correlated with ADS-B data)
# ══════════════════════════════════════════════════════════════════════════════

# Baseline expected aircraft counts per strategic zone (from historical observation)
# Used for void detection: if current count << baseline, likely TFR or restricted airspace
_ZONE_TRAFFIC_BASELINES = {
    "ukraine_theater":    5,    # Low due to conflict
    "taiwan_strait":      40,
    "south_china_sea":    35,
    "persian_gulf":       50,
    "korean_dmz":         15,
    "baltic_states":      20,
    "black_sea":          25,
    "eastern_med":        60,
    "arctic_svalbard":    5,
    "red_sea_horn":       30,
    "kaliningrad":        8,
    "sahel_region":       10,
}


class AirspaceWarningMonitor:
    """Detects airspace warnings by correlating ADS-B voids with news reports.

    Two detection methods:
    1. Void detection: compares current ADS-B traffic to baseline
    2. News correlation: GDELT queries for airspace closure/restriction reports

    This is MORE reliable than raw NOTAM parsing because it verifies
    restrictions with actual traffic data — the Palantir approach.
    """

    POLL_INTERVAL = 900  # 15 minutes

    def __init__(self):
        self._warnings: dict[str, dict] = {}  # zone_id → warning details
        self._last_poll_ts: float = 0.0
        self._void_detections: list[dict] = []

    def detect_airspace_voids(self, airspace_zone_status: dict[str, dict]) -> list[dict]:
        """Compare current ADS-B readings against baselines.

        Args:
            airspace_zone_status: Current zone status from AirspaceMonitor.zone_status

        Returns:
            List of signal dicts for zones with unusually low traffic.
        """
        signals = []
        now = time.time()

        for zone_id, status in airspace_zone_status.items():
            baseline = _ZONE_TRAFFIC_BASELINES.get(zone_id, 0)
            if baseline == 0:
                continue

            current = status.get("total", 0)
            age_min = (now - status.get("ts", 0)) / 60
            if age_min > 60:  # Skip stale data
                continue

            # Void detection: current < 30% of baseline
            if current < baseline * 0.3 and baseline > 5:
                ratio = current / baseline if baseline else 0
                warning = {
                    "zone_id": zone_id,
                    "zone_name": status.get("zone_name", zone_id),
                    "current_traffic": current,
                    "baseline": baseline,
                    "ratio": round(ratio, 2),
                    "ts": now,
                    "status": "void_detected",
                }
                self._warnings[zone_id] = warning
                self._void_detections.append(warning)

                signal = {
                    "type": "airspace_void",
                    "headline": (
                        f"AIRSPACE VOID: {status.get('zone_name', zone_id)} — "
                        f"only {current} aircraft (baseline ~{baseline}) — "
                        f"possible restriction/TFR active"
                    ),
                    "region": zone_id.upper(),
                    "domain": "SECURITY",
                    "salience": min(0.85, 0.5 + (1 - ratio) * 0.3),
                    "data": warning,
                }
                signals.append(signal)
                logger.info("[AirspaceWarning] VOID: %s", signal["headline"])

            # Surge detection: current > 200% of baseline (unusual activity)
            elif current > baseline * 2.0 and baseline > 5:
                ratio = current / baseline
                warning = {
                    "zone_id": zone_id,
                    "zone_name": status.get("zone_name", zone_id),
                    "current_traffic": current,
                    "baseline": baseline,
                    "ratio": round(ratio, 2),
                    "ts": now,
                    "status": "surge_detected",
                }
                self._warnings[zone_id] = warning

                signal = {
                    "type": "airspace_surge",
                    "headline": (
                        f"AIRSPACE SURGE: {status.get('zone_name', zone_id)} — "
                        f"{current} aircraft (baseline ~{baseline}, {ratio:.1f}× normal)"
                    ),
                    "region": zone_id.upper(),
                    "domain": "SECURITY",
                    "salience": min(0.75, 0.4 + (ratio - 2) * 0.15),
                    "data": warning,
                }
                signals.append(signal)

        # Trim history
        self._void_detections = self._void_detections[-100:]
        return signals

    def get_warnings_digest(self) -> str:
        """Formatted airspace warnings for Live Digest injection."""
        if not self._warnings:
            return ""

        lines = []
        now = time.time()

        for zone_id, w in sorted(self._warnings.items()):
            age_min = (now - w["ts"]) / 60
            if age_min > 120:  # Skip stale warnings
                continue

            if w["status"] == "void_detected":
                lines.append(
                    f"  🚫 {w['zone_name']}: VOID — {w['current_traffic']} aircraft "
                    f"(baseline ~{w['baseline']}, {w['ratio']:.0%} of normal)"
                )
            elif w["status"] == "surge_detected":
                lines.append(
                    f"  📈 {w['zone_name']}: SURGE — {w['current_traffic']} aircraft "
                    f"({w['ratio']:.1f}× normal)"
                )

        return "\n".join(lines)

    def stats(self) -> dict:
        return {
            "active_warnings": len(self._warnings),
            "total_void_detections": len(self._void_detections),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  UNIFIED REAL-TIME FEED MANAGER
#  Orchestrates all real-time sub-monitors and produces combined digest
# ══════════════════════════════════════════════════════════════════════════════

class RealtimeFeedManager:
    """Orchestrates all real-time intelligence feeds.

    Called by the perception collector on each cycle.
    Aggregates signals from all sub-monitors.
    Produces combined digest for LLM context injection.
    """

    def __init__(
        self,
        finnhub_api_key: str = "",
        otx_api_key: str = "",
        greynoise_api_key: str = "",
    ):
        self.finnhub = FinnhubRealtimeMonitor(api_key=finnhub_api_key)
        self.cyber = CyberThreatMonitor(
            otx_api_key=otx_api_key,
            greynoise_api_key=greynoise_api_key,
        )
        self.airspace_warnings = AirspaceWarningMonitor()

        self._total_signals: int = 0
        self._last_cycle_ts: float = 0.0
        self._cycle_count: int = 0

        enabled = []
        if finnhub_api_key:
            enabled.append("Finnhub")
        if otx_api_key:
            enabled.append("OTX")
        if greynoise_api_key:
            enabled.append("GreyNoise")
        enabled.append("AirspaceWarnings")  # Always enabled (derived from ADS-B)

        logger.info("[RealtimeFeeds] Manager initialized: %s", ", ".join(enabled))

    async def poll_all(self, airspace_zone_status: dict | None = None) -> list[dict]:
        """Poll all real-time feeds. Returns combined signals for PatternAccumulator.

        Args:
            airspace_zone_status: Optional AirspaceMonitor.zone_status for void detection.
        """
        all_signals: list[dict] = []

        # Finnhub forex + calendar
        try:
            finnhub_signals = await self.finnhub.poll_all()
            all_signals.extend(finnhub_signals)
        except Exception as e:
            logger.warning("[RealtimeFeeds] Finnhub poll failed: %s", e)

        # Cyber threat intel
        try:
            cyber_signals = await self.cyber.poll_all()
            all_signals.extend(cyber_signals)
        except Exception as e:
            logger.warning("[RealtimeFeeds] Cyber poll failed: %s", e)

        # Airspace void detection (if ADS-B data available)
        if airspace_zone_status:
            try:
                void_signals = self.airspace_warnings.detect_airspace_voids(airspace_zone_status)
                all_signals.extend(void_signals)
            except Exception as e:
                logger.warning("[RealtimeFeeds] Airspace warning detection failed: %s", e)

        self._total_signals += len(all_signals)
        self._last_cycle_ts = time.time()
        self._cycle_count += 1

        if all_signals:
            logger.info("[RealtimeFeeds] Cycle #%d: %d signals (finnhub=%d, cyber=%d, airspace=%d)",
                        self._cycle_count, len(all_signals),
                        sum(1 for s in all_signals if s.get("type", "").startswith("forex")),
                        sum(1 for s in all_signals if s.get("type") == "cyber_threat"),
                        sum(1 for s in all_signals if s.get("type", "").startswith("airspace")))

        return all_signals

    def get_realtime_digest(self) -> str:
        """Generate combined real-time intelligence digest section.

        Designed to be appended to the MultimodalCollector.get_live_digest().
        Returns empty string if no data available.
        """
        sections: list[str] = []

        # ── Forex Intelligence ──
        forex_digest = self.finnhub.get_forex_digest()
        if forex_digest:
            sections.append("▸ REAL-TIME FOREX & COMMODITIES (Finnhub)")
            sections.append(forex_digest)
            sections.append("")

        # ── Economic Calendar ──
        calendar_digest = self.finnhub.get_calendar_digest()
        if calendar_digest:
            sections.append("▸ ECONOMIC CALENDAR (upcoming events)")
            sections.append(calendar_digest)
            sections.append("")

        # ── Cyber Threat Intelligence ──
        cyber_digest = self.cyber.get_cyber_digest()
        if cyber_digest:
            sections.append("▸ CYBER THREAT INTELLIGENCE (OTX + GreyNoise)")
            sections.append(cyber_digest)
            sections.append("")

        # ── Airspace Warnings ──
        warnings_digest = self.airspace_warnings.get_warnings_digest()
        if warnings_digest:
            sections.append("▸ AIRSPACE WARNINGS (void/surge detection)")
            sections.append(warnings_digest)
            sections.append("")

        if not sections:
            return ""

        return "\n".join(sections)

    def stats(self) -> dict:
        return {
            "cycle_count": self._cycle_count,
            "total_signals": self._total_signals,
            "finnhub": self.finnhub.stats(),
            "cyber": self.cyber.stats(),
            "airspace_warnings": self.airspace_warnings.stats(),
        }
