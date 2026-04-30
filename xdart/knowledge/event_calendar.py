"""
XDART-Φ × XHEART — Geopolitical Event Calendar (Palantir P0/P5)

Structured calendar of upcoming geopolitical events with temporal intelligence.
Auto-injects countdown context into LLM prompts so Αίολος can correlate
incoming signals with upcoming events.

"Ο χρόνος δεν είναι γραμμικός στη γεωπολιτική. Κάθε ημερομηνία είναι σημείο εκτόνωσης."

Features:
  - Curated major events (central bank meetings, elections, summits)
  - Auto-fetched economic calendar from Finnhub
  - Countdown mode: "X days until Y" injected into LLM context
  - Proximity alerts: boost monitoring sensitivity near events
  - Historical context: what happened last time a similar event occurred

Sources:
  - Curated: central bank meetings (Fed, ECB, BOE, BOJ, PBOC)
  - Curated: major elections, treaty deadlines, summits
  - Dynamic: Finnhub economic calendar (high-impact events)
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("xdart.knowledge.event_calendar")


# ══════════════════════════════════════════════════════════════════════════════
#  CURATED EVENTS — Major geopolitical events with known dates
#  Updated periodically. These are the events that MATTER.
# ══════════════════════════════════════════════════════════════════════════════

# Event format: {
#   "date": "YYYY-MM-DD",
#   "name": "Event Name",
#   "category": "central_bank" | "election" | "summit" | "treaty" | "economic" | "military",
#   "region": "GLOBAL" | region code,
#   "impact": 1-5 (5 = highest),
#   "description": "Why this matters",
#   "watch_keywords": ["keyword1", "keyword2"],  # boost signals matching these
# }

# Central bank meeting dates for 2025-2026
# These are THE most market-moving scheduled events
_CENTRAL_BANK_2025_2026 = [
    # Federal Reserve FOMC
    {"date": "2025-05-07", "name": "FOMC Decision", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "Federal Reserve interest rate decision",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell", "federal reserve"]},
    {"date": "2025-06-18", "name": "FOMC Decision + Projections", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "FOMC with dot plot projections",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell", "dot plot"]},
    {"date": "2025-07-30", "name": "FOMC Decision", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "Federal Reserve interest rate decision",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell"]},
    {"date": "2025-09-17", "name": "FOMC Decision + Projections", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "FOMC with economic projections",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell", "dot plot"]},
    {"date": "2025-10-29", "name": "FOMC Decision", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "Federal Reserve interest rate decision",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell"]},
    {"date": "2025-12-17", "name": "FOMC Decision + Projections", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "Final FOMC of 2025 with projections",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell", "dot plot"]},
    {"date": "2026-01-28", "name": "FOMC Decision", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "First FOMC of 2026",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell"]},
    {"date": "2026-03-18", "name": "FOMC Decision + Projections", "category": "central_bank",
     "region": "USA", "impact": 5, "description": "FOMC with dot plot projections",
     "watch_keywords": ["fed", "fomc", "interest rate", "powell", "dot plot"]},

    # European Central Bank
    {"date": "2025-04-17", "name": "ECB Rate Decision", "category": "central_bank",
     "region": "EUROPE", "impact": 5, "description": "ECB interest rate decision",
     "watch_keywords": ["ecb", "lagarde", "eurozone", "european central bank"]},
    {"date": "2025-06-05", "name": "ECB Rate Decision", "category": "central_bank",
     "region": "EUROPE", "impact": 5, "description": "ECB interest rate decision",
     "watch_keywords": ["ecb", "lagarde", "eurozone"]},
    {"date": "2025-07-24", "name": "ECB Rate Decision", "category": "central_bank",
     "region": "EUROPE", "impact": 5, "description": "ECB interest rate decision",
     "watch_keywords": ["ecb", "lagarde", "eurozone"]},
    {"date": "2025-09-11", "name": "ECB Rate Decision", "category": "central_bank",
     "region": "EUROPE", "impact": 5, "description": "ECB interest rate decision",
     "watch_keywords": ["ecb", "lagarde", "eurozone"]},
    {"date": "2025-10-30", "name": "ECB Rate Decision", "category": "central_bank",
     "region": "EUROPE", "impact": 5, "description": "ECB interest rate decision",
     "watch_keywords": ["ecb", "lagarde", "eurozone"]},
    {"date": "2025-12-18", "name": "ECB Rate Decision", "category": "central_bank",
     "region": "EUROPE", "impact": 5, "description": "Final ECB decision 2025",
     "watch_keywords": ["ecb", "lagarde", "eurozone"]},

    # Bank of Japan
    {"date": "2025-05-01", "name": "BOJ Rate Decision", "category": "central_bank",
     "region": "JAPAN", "impact": 4, "description": "Bank of Japan rate decision — yen watch",
     "watch_keywords": ["boj", "bank of japan", "yen", "ueda"]},
    {"date": "2025-06-13", "name": "BOJ Rate Decision", "category": "central_bank",
     "region": "JAPAN", "impact": 4, "description": "Bank of Japan rate decision",
     "watch_keywords": ["boj", "bank of japan", "yen"]},
    {"date": "2025-07-31", "name": "BOJ Rate Decision + Outlook", "category": "central_bank",
     "region": "JAPAN", "impact": 5, "description": "BOJ with quarterly outlook report",
     "watch_keywords": ["boj", "bank of japan", "yen", "ueda"]},

    # People's Bank of China
    {"date": "2025-04-21", "name": "PBOC LPR Decision", "category": "central_bank",
     "region": "CHINA", "impact": 4, "description": "China loan prime rate — stimulus signal",
     "watch_keywords": ["pboc", "china", "lpr", "stimulus", "yuan"]},
    {"date": "2025-05-20", "name": "PBOC LPR Decision", "category": "central_bank",
     "region": "CHINA", "impact": 4, "description": "China loan prime rate",
     "watch_keywords": ["pboc", "china", "lpr", "yuan"]},

    # Bank of England
    {"date": "2025-05-08", "name": "BOE Rate Decision", "category": "central_bank",
     "region": "UK", "impact": 4, "description": "Bank of England interest rate decision",
     "watch_keywords": ["boe", "bank of england", "bailey", "sterling"]},
    {"date": "2025-06-19", "name": "BOE Rate Decision", "category": "central_bank",
     "region": "UK", "impact": 4, "description": "Bank of England interest rate decision",
     "watch_keywords": ["boe", "bank of england", "sterling"]},
]

# Major geopolitical events
_GEOPOLITICAL_EVENTS = [
    # 2025 elections and political events
    {"date": "2025-05-03", "name": "Canada Federal Election Results", "category": "election",
     "region": "CANADA", "impact": 3, "description": "Canadian federal election",
     "watch_keywords": ["canada", "election", "carney", "poilievre"]},
    {"date": "2025-07-01", "name": "G20 Summit (South Africa)", "category": "summit",
     "region": "GLOBAL", "impact": 4, "description": "G20 leaders summit in Johannesburg",
     "watch_keywords": ["g20", "summit", "south africa"]},
    {"date": "2025-09-01", "name": "UN General Assembly (UNGA 80)", "category": "summit",
     "region": "GLOBAL", "impact": 4, "description": "UN General Assembly 80th session opens",
     "watch_keywords": ["unga", "united nations", "general assembly"]},
    {"date": "2025-11-10", "name": "COP30 Climate Summit (Belém)", "category": "summit",
     "region": "GLOBAL", "impact": 3, "description": "UN Climate Change Conference in Brazil",
     "watch_keywords": ["cop30", "climate", "belem", "amazon"]},

    # Known geopolitical deadlines
    {"date": "2025-06-01", "name": "US Debt Ceiling X-Date (estimated)", "category": "economic",
     "region": "USA", "impact": 5, "description": "Estimated US Treasury exhaustion date",
     "watch_keywords": ["debt ceiling", "treasury", "default", "shutdown"]},

    # Military/security dates
    {"date": "2025-05-09", "name": "Russia Victory Day Parade", "category": "military",
     "region": "RUSSIA", "impact": 3, "description": "Russian Victory Day — potential announcements",
     "watch_keywords": ["russia", "victory day", "putin", "military parade"]},
    {"date": "2025-07-04", "name": "US Independence Day", "category": "military",
     "region": "USA", "impact": 2, "description": "US holiday — reduced market activity",
     "watch_keywords": ["independence day", "july 4th"]},
    {"date": "2025-10-01", "name": "China National Day", "category": "military",
     "region": "CHINA", "impact": 3, "description": "PRC founding anniversary — military displays",
     "watch_keywords": ["china", "national day", "prc", "military"]},
    {"date": "2025-10-10", "name": "Taiwan National Day", "category": "military",
     "region": "TAIWAN", "impact": 4, "description": "Taiwan National Day — cross-strait tension point",
     "watch_keywords": ["taiwan", "national day", "cross-strait", "china"]},
]

# Combine all curated events
ALL_CURATED_EVENTS = _CENTRAL_BANK_2025_2026 + _GEOPOLITICAL_EVENTS


class GeopoliticalCalendar:
    """Geopolitical event calendar with temporal intelligence.

    Maintains a combined calendar of curated + dynamic events.
    Provides countdown context for LLM injection.
    Boosts signal sensitivity near important events.
    """

    def __init__(self):
        self._curated_events = list(ALL_CURATED_EVENTS)
        self._dynamic_events: list[dict] = []  # From Finnhub or other sources
        self._proximity_alerts: list[dict] = []
        self._last_check_ts: float = 0.0

    def add_dynamic_events(self, events: list[dict]):
        """Add dynamically fetched events (e.g., from Finnhub calendar)."""
        for ev in events:
            # Deduplicate by date + name similarity
            duplicate = False
            for existing in self._curated_events + self._dynamic_events:
                if (existing.get("date") == ev.get("date") and
                        existing.get("name", "").lower()[:20] == ev.get("name", "").lower()[:20]):
                    duplicate = True
                    break
            if not duplicate:
                self._dynamic_events.append(ev)

        # Trim dynamic events to 200
        self._dynamic_events = self._dynamic_events[-200:]

    def get_upcoming_events(self, days_ahead: int = 14) -> list[dict]:
        """Get events within the next N days, sorted by date."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days_ahead)
        upcoming = []

        for ev in self._curated_events + self._dynamic_events:
            try:
                ev_date = datetime.strptime(ev["date"][:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, KeyError, TypeError):
                continue

            if now <= ev_date <= cutoff:
                delta = ev_date - now
                upcoming.append({
                    **ev,
                    "days_until": delta.days,
                    "hours_until": delta.total_seconds() / 3600,
                    "parsed_date": ev_date,
                })

        upcoming.sort(key=lambda x: x["days_until"])
        return upcoming

    def get_active_watch_keywords(self, days_ahead: int = 7) -> set[str]:
        """Get keywords to boost for upcoming events.

        Signals matching these keywords should receive higher weight.
        """
        upcoming = self.get_upcoming_events(days_ahead)
        keywords = set()
        for ev in upcoming:
            for kw in ev.get("watch_keywords", []):
                keywords.add(kw.lower())
        return keywords

    def check_proximity_alerts(self) -> list[dict]:
        """Check for events within 48 hours and 7 days.

        Returns new proximity alerts (not previously generated).
        """
        now = time.time()
        if now - self._last_check_ts < 3600:  # Check once per hour
            return []
        self._last_check_ts = now

        alerts = []
        upcoming = self.get_upcoming_events(days_ahead=7)

        for ev in upcoming:
            hours = ev["hours_until"]
            alert_id = f"{ev['date']}_{ev['name'][:20]}"

            # Already alerted?
            if any(a.get("id") == alert_id for a in self._proximity_alerts):
                continue

            if hours <= 48:
                alert = {
                    "id": alert_id,
                    "event": ev["name"],
                    "hours_until": round(hours, 1),
                    "impact": ev.get("impact", 3),
                    "category": ev.get("category", ""),
                    "region": ev.get("region", "GLOBAL"),
                    "ts": now,
                }
                alerts.append(alert)
                self._proximity_alerts.append(alert)

        # Trim old alerts
        self._proximity_alerts = [
            a for a in self._proximity_alerts
            if now - a.get("ts", 0) < 604800  # 7 days
        ]

        return alerts

    def get_calendar_digest(self) -> str:
        """Formatted calendar intelligence for LLM context injection.

        Structured as:
        1. IMMINENT (< 48h) — highest priority
        2. THIS WEEK (< 7d) — medium priority
        3. AHEAD (7-14d) — awareness
        """
        upcoming = self.get_upcoming_events(days_ahead=14)
        if not upcoming:
            return ""

        lines = ["▸ GEOPOLITICAL CALENDAR (upcoming events)"]

        # Imminent events (< 48h)
        imminent = [ev for ev in upcoming if ev["hours_until"] <= 48]
        if imminent:
            lines.append("  ⏰ IMMINENT (next 48 hours):")
            for ev in imminent:
                impact_icon = "🔴" if ev.get("impact", 0) >= 4 else "🟡"
                hours = ev["hours_until"]
                if hours < 1:
                    time_str = "< 1 hour"
                elif hours < 24:
                    time_str = f"{hours:.0f}h"
                else:
                    time_str = f"{ev['days_until']}d {hours % 24:.0f}h"
                lines.append(
                    f"  {impact_icon} [{ev.get('region', 'GLOBAL')}] "
                    f"{ev['name']} — in {time_str}"
                )
                if ev.get("description"):
                    lines.append(f"      {ev['description']}")

        # This week (< 7d)
        this_week = [ev for ev in upcoming if 48 < ev["hours_until"] <= 168]
        if this_week:
            lines.append("  📅 THIS WEEK:")
            for ev in this_week[:6]:
                impact_icon = "🔴" if ev.get("impact", 0) >= 4 else "🟡" if ev.get("impact", 0) >= 3 else "⚪"
                lines.append(
                    f"  {impact_icon} [{ev.get('region', 'GLOBAL')}] "
                    f"{ev['name']} — in {ev['days_until']}d "
                    f"({ev.get('category', '')})"
                )

        # Ahead (7-14d)
        ahead = [ev for ev in upcoming if ev["hours_until"] > 168]
        if ahead:
            high_impact_ahead = [ev for ev in ahead if ev.get("impact", 0) >= 4]
            if high_impact_ahead:
                lines.append("  📋 AHEAD (high-impact only):")
                for ev in high_impact_ahead[:4]:
                    lines.append(
                        f"  ● [{ev.get('region', 'GLOBAL')}] "
                        f"{ev['name']} — in {ev['days_until']}d"
                    )

        lines.append("")
        return "\n".join(lines)

    def get_proximity_signals(self) -> list[dict]:
        """Generate PatternAccumulator signals for imminent events."""
        alerts = self.check_proximity_alerts()
        signals = []
        for alert in alerts:
            signals.append({
                "type": "calendar_proximity",
                "headline": (
                    f"EVENT APPROACHING: {alert['event']} in {alert['hours_until']:.0f}h "
                    f"(impact={alert['impact']}/5, {alert['category']})"
                ),
                "region": alert.get("region", "GLOBAL"),
                "domain": "GEOPOLITICS" if alert["category"] != "central_bank" else "ECONOMIC",
                "salience": min(0.8, 0.3 + alert["impact"] * 0.1),
                "data": alert,
            })
        return signals

    def keyword_boost(self, headline: str, base_weight: float = 0.0) -> float:
        """Calculate weight boost for a headline based on proximity to events.

        Returns additional weight (0.0-0.15) if headline matches upcoming event keywords.
        """
        active_keywords = self.get_active_watch_keywords()
        if not active_keywords:
            return 0.0

        headline_lower = headline.lower()
        matched = sum(1 for kw in active_keywords if kw in headline_lower)
        if matched == 0:
            return 0.0

        # Scale boost by number of keyword matches (max 0.15)
        return min(0.15, matched * 0.05)

    def stats(self) -> dict:
        upcoming_7d = self.get_upcoming_events(7)
        upcoming_48h = [ev for ev in upcoming_7d if ev["hours_until"] <= 48]
        return {
            "curated_events": len(self._curated_events),
            "dynamic_events": len(self._dynamic_events),
            "upcoming_7d": len(upcoming_7d),
            "upcoming_48h": len(upcoming_48h),
            "active_watch_keywords": len(self.get_active_watch_keywords()),
            "proximity_alerts": len(self._proximity_alerts),
        }
