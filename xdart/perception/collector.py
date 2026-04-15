"""
XDART-Φ × XHEART — Data Collector

Continuously collects real-world data from multi-perspective sources.
Runs independently of the pipeline on three cadence loops:
  - Realtime  (every 15 min): GDELT, RSS feeds
  - Hourly    (every 60 min): Wire services, ReliefWeb
  - Daily     (every 24h):    FRED, World Bank, ECB economic indicators

Design principles:
  - No single source is "truth"
  - Multiple sources reveal the real pattern
  - Facts and opinions are always separated
  - The system knows where every piece of data comes from
  - Never modifies collected data — only appends

Sources added beyond world.txt spec:
  - GDELT DOC 2.0 API  (free, no key, 65 languages, 130+ countries)
  - World Bank API v2   (free, no key, 16,000+ indicators)
  - ReliefWeb API v2    (free, appname only, UN OCHA humanitarian data)
"""

import asyncio
import csv
import hashlib
import io
import json
import logging
import random
import time
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from xdart.perception.db import PerceptionDB
from xdart.perception.feed_catalog import (
    RSS_CATALOG,
    get_propaganda_risk,
    score_headline,
    ALERT_EXCLUSIONS,
)
from xdart.perception.keyword_spikes import KeywordSpikeDetector

logger = logging.getLogger("xdart.perception.collector")

# Legacy alias — some external code may reference RSS_SOURCES
RSS_SOURCES = RSS_CATALOG

# ── FRED Economic Series (Tier 1 — primary data) ──

FRED_SERIES = [
    ("FEDFUNDS", "Federal Funds Rate", "%"),
    ("CPIAUCSL", "US CPI", "index"),
    ("UNRATE", "Unemployment Rate", "%"),
    ("GDP", "US GDP", "USD billions"),
    ("DGS10", "10-Year Treasury Yield", "%"),
    ("T10YIE", "10-Year Breakeven Inflation", "%"),
    ("DCOILBRENTEU", "Brent Crude Oil (FRED)", "USD/bbl"),
    ("DHHNGSP", "Natural Gas Henry Hub (FRED)", "USD/MMBtu"),
    # ── Financial expansion: Currency stress, sovereign debt, macro-financial coupling ──
    ("DTWEXBGS", "Trade-Weighted USD Index (Broad)", "index"),
    ("DEXUSEU", "USD/EUR Exchange Rate", "USD/EUR"),
    ("DEXJPUS", "JPY/USD Exchange Rate", "JPY/USD"),
    ("DEXCHUS", "CNY/USD Exchange Rate", "CNY/USD"),
    ("BAMLH0A0HYM2", "High Yield Corporate Bond Spread", "bps"),
    ("T10Y2Y", "10Y-2Y Treasury Spread (Yield Curve)", "bps"),
    ("TEDRATE", "TED Spread (Interbank Stress)", "%"),
    ("GFDEBTN", "US Federal Debt Total", "USD millions"),
    ("M2SL", "M2 Money Supply", "USD billions"),
    ("UMCSENT", "U Michigan Consumer Sentiment", "index"),
    ("STLFSI4", "St. Louis Financial Stress Index", "index"),
    ("DEXMXUS", "MXN/USD Exchange Rate", "MXN/USD"),
    ("DEXBZUS", "BRL/USD Exchange Rate", "BRL/USD"),
    ("DEXTAUS", "THB/USD Exchange Rate", "THB/USD"),
]

# ── World Bank Indicators (Tier 1 — primary data, FREE, no key) ──

WORLDBANK_INDICATORS = [
    ("NY.GDP.MKTP.KD.ZG", "World GDP Growth", "%"),
    ("FP.CPI.TOTL.ZG", "Global CPI Inflation", "%"),
    ("SL.UEM.TOTL.ZS", "Global Unemployment Rate", "%"),
    ("BX.KLT.DINV.CD.WD", "Foreign Direct Investment", "USD"),
    ("DT.DOD.DECT.CD", "External Debt Stock", "USD"),
]


class DataCollector:
    """Collects real-world data from multiple sources.

    Runs continuously, independently of pipeline runs.
    Never modifies collected data — only appends.
    """

    def __init__(self, db: PerceptionDB, filter_layer: Any, fred_api_key: str = "",
                 ucdp_api_token: str = "",
                 finnhub_api_key: str = "",
                 on_alert: Any | None = None,
                 entity_graph: Any | None = None,
                 market_collector: Any | None = None):
        self.db = db
        self.filter = filter_layer
        self.fred_api_key = fred_api_key
        self.ucdp_api_token = ucdp_api_token
        self.finnhub_api_key = finnhub_api_key
        self._client: httpx.AsyncClient | None = None
        self.on_alert = on_alert  # callable(list[dict]) — fired when high-salience events detected
        self._alert_threshold = 0.85
        # Entity Knowledge Graph — every headline gets NER-processed
        self.entity_graph = entity_graph
        # Financial Market Collector — polled every realtime cycle
        self.market_collector = market_collector
        # Proactive trigger accumulator — must init here (was only in _disable_gdelt before)
        self._pending_alerts: list[dict] = []
        # GDELT backoff state
        self._gdelt_consecutive_failures = 0
        self._gdelt_backoff_seconds = 10
        self._gdelt_disabled = False
        self._gdelt_max_failures = 8  # disable after N consecutive failures
        self._gdelt_disabled_until: float = 0  # re-enable after cooldown
        # GDELT response cache — avoid re-querying within cache window
        self._gdelt_cache: dict[str, tuple[float, list]] = {}  # query → (timestamp, articles)
        self._gdelt_cache_ttl = 900  # 15 minutes — matches realtime loop interval
        # GDELT DOC query rotation — run 3 of 5 per cycle to reduce pressure
        self._gdelt_query_offset = 0
        self._gdelt_queries_per_cycle = 3
        # Adaptive realtime interval — extends after GDELT rate-limits
        self._realtime_interval = 15 * 60  # default 15 min
        self._realtime_interval_default = 15 * 60
        self._realtime_interval_backoff = 25 * 60  # 25 min after rate-limit
        self._gdelt_rate_limited_recently = False
        # Keyword spike detector (trending term detection)
        self.spike_detector = KeywordSpikeDetector()
        # Cross-stream correlation engine
        from xdart.perception.correlation import CorrelationEngine
        self.correlation_engine = CorrelationEngine()

    def _disable_gdelt(self, cooldown_seconds: int = 600):
        """Temporarily disable GDELT with a cooldown period (default 10 min)."""
        self._gdelt_disabled = True
        self._gdelt_disabled_until = time.time() + cooldown_seconds

    # ── feedparser wrapper with proper User-Agent ──
    # Raw feedparser.parse(url) uses Python's default urllib UA
    # which gets rejected by Google News, military/defense sites,
    # and many news servers as bot traffic → "Remote end closed connection"
    _FEED_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    @staticmethod
    def _parse_feed(url: str) -> "feedparser.FeedParserDict":
        """Parse an RSS/Atom feed with a browser-like User-Agent.

        Prevents 'Remote end closed connection' rejections from servers
        that block the default Python/feedparser UA.
        """
        import feedparser
        return feedparser.parse(url, agent=DataCollector._FEED_USER_AGENT)

    def _build_client(self) -> httpx.AsyncClient:
        """Build an httpx client with transport-level retries for flaky networks."""
        transport = httpx.AsyncHTTPTransport(retries=3)
        return httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(60.0, connect=30.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/html, application/xml, */*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    def _build_gdelt_data_client(self) -> httpx.AsyncClient:
        """Build a no-verify client for data.gdeltproject.org (known SSL cert mismatch).

        NOTE: When a custom transport is provided, AsyncClient's verify= is IGNORED.
        We must pass verify=False directly to the transport.
        """
        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        return httpx.AsyncClient(
            verify=ssl_ctx,
            timeout=httpx.Timeout(60.0, connect=30.0),
            follow_redirects=True,
            headers={"User-Agent": "XDART-Perception/1.0"},
        )

    async def run_forever(self):
        """Main loop — runs all collectors on their schedules."""
        logger.info("[Collector] Starting continuous perception loop")
        self._client = self._build_client()
        self._gdelt_data_client = self._build_gdelt_data_client()
        try:
            tasks = [
                self._run_realtime_loop(),
                self._run_hourly_loop(),
                self._run_daily_loop(),
            ]
            await asyncio.gather(*tasks)
        finally:
            await self._client.aclose()

    # ── Cadence Loops ──

    async def _run_realtime_loop(self):
        """Every 15 minutes: RSS feeds + Google News + GDELT (DOC + Events + GKG)."""
        while True:
            try:
                self._pending_alerts.clear()
                # Phase 1: RSS + Google News + GDELT DOC (concurrent)
                await asyncio.gather(
                    self._collect_rss_feeds(),
                    self._collect_gnews(),
                    self._collect_gdelt(),
                    return_exceptions=True,
                )
                # Phase 2: GDELT bulk CSV downloads (Events then GKG, sequential)
                # Both hit data.gdeltproject.org — running concurrent causes SSL/rate issues
                # Skip if GDELT DOC just got rate-limited — don't pile on
                if not self._gdelt_disabled and not self._gdelt_rate_limited_recently:
                    await self._collect_gdelt_events()
                    await asyncio.sleep(5)
                    await self._collect_gdelt_gkg()
                elif self._gdelt_disabled:
                    logger.info("[Collector] GDELT Events/GKG skipped (GDELT disabled, cooldown)")
                else:
                    logger.info("[Collector] GDELT Events/GKG skipped (recent rate-limit, backing off)")

                # Phase 3: Financial market data (if collector available)
                if self.market_collector:
                    try:
                        loop = asyncio.get_event_loop()
                        snapshot = await loop.run_in_executor(
                            None, self.market_collector.poll,
                        )
                        # Feed market anomalies into proactive alerts
                        # Enrich financial headlines with recent entity context
                        # so topic words overlap with geopolitical text signals
                        context_entities: list[str] = []
                        if self.entity_graph:
                            try:
                                top_nodes = self.entity_graph.get_top_entities(5)
                                context_entities = [n for n, _ in top_nodes]
                                if context_entities:
                                    logger.info("[Collector] Financial context entities: %s",
                                                context_entities)
                            except Exception as e:
                                logger.debug("[Collector] Entity context enrichment error: %s", e)

                        for anomaly in snapshot.anomalies:
                            headline = anomaly["headline"]
                            if context_entities:
                                ctx_str = ", ".join(context_entities[:4])
                                headline = f"{headline} (context: {ctx_str})"
                            self._pending_alerts.append({
                                "headline": headline,
                                "source": "financial_feeds",
                                "domain": "ECONOMIC",
                                "salience": 0.95,
                                "region": [],
                                "signal_type": "financial_anomaly",
                                "weight": anomaly.get("weight", 0.45),
                            })
                        if snapshot.data:
                            logger.info("[Collector] Financial: %d tickers, %d anomalies",
                                        len(snapshot.data), len(snapshot.anomalies))
                    except Exception as e:
                        logger.warning("[Collector] Financial feeds error: %s", e)

                # Phase 4: Save entity graph periodically
                if self.entity_graph and self._pending_alerts:
                    try:
                        logger.debug("[Collector] Saving entity graph (%d nodes, %d edges)",
                                     self.entity_graph._graph.number_of_nodes(),
                                     self.entity_graph._graph.number_of_edges())
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, self.entity_graph.save)
                    except Exception as e:
                        logger.debug("[Collector] Entity graph save failed: %s", e)

                # Fire proactive alert if high-salience events detected
                if self._pending_alerts and self.on_alert:
                    try:
                        logger.info("[Collector] PROACTIVE ALERT: %d high-salience events detected",
                                    len(self._pending_alerts))
                        await asyncio.get_event_loop().run_in_executor(
                            None, self.on_alert, list(self._pending_alerts),
                        )
                    except Exception as e:
                        logger.warning("[Collector] Alert callback failed: %s", e)
            except Exception as e:
                logger.error("[Collector] Realtime loop error: %s", e)
            # Adaptive interval — back off after GDELT rate-limits
            if self._gdelt_rate_limited_recently:
                self._realtime_interval = self._realtime_interval_backoff
                logger.info("[Collector] Realtime interval extended to %dmin (GDELT backoff)",
                            self._realtime_interval // 60)
            else:
                self._realtime_interval = self._realtime_interval_default
            await asyncio.sleep(self._realtime_interval)

    async def _run_hourly_loop(self):
        """Every hour: ACLED + USGS earthquakes + NASA EONET + GDACS disasters."""
        while True:
            try:
                # Track alerts from hourly sources (earthquakes, conflicts, disasters)
                pre_count = len(self._pending_alerts)
                await asyncio.gather(
                    self._collect_acled(),
                    self._collect_usgs_earthquakes(),
                    self._collect_nasa_eonet(),
                    self._collect_gdacs(),
                    return_exceptions=True,
                )
                # Fire alerts accumulated by hourly collectors
                new_alerts = self._pending_alerts[pre_count:]
                if new_alerts and self.on_alert:
                    try:
                        logger.info("[Collector] HOURLY ALERT: %d events from hourly sources",
                                    len(new_alerts))
                        await asyncio.get_event_loop().run_in_executor(
                            None, self.on_alert, list(new_alerts),
                        )
                    except Exception as e:
                        logger.warning("[Collector] Hourly alert callback failed: %s", e)
            except Exception as e:
                logger.error("[Collector] Hourly loop error: %s", e)
            await asyncio.sleep(60 * 60)

    async def _run_daily_loop(self):
        """Every 24h: FRED + World Bank + ECB + UCDP + FX + Commodities + Yahoo Markets + Finnhub + Financial.

        Economic data collectors generate economic_shift signals for meaningful changes.
        Signals feed into PatternAccumulator to enable geo+econ cross-domain fusion.
        """
        while True:
            try:
                pre_count = len(self._pending_alerts)
                await self._collect_fred()
                await self._collect_worldbank()
                await self._collect_ecb()
                await self._collect_ucdp()
                await self._collect_exchange_rates()
                await self._collect_commodities()
                await self._collect_yahoo_markets()
                await self._collect_yahoo_currency_pairs()
                await self._collect_finnhub_forex()
                await self._collect_finnhub_earnings_calendar()
                await self._collect_finnhub_economic_calendar()
                await self._collect_finnhub_market_news()

                # Fire economic signals accumulated by daily collectors
                new_alerts = self._pending_alerts[pre_count:]
                if new_alerts and self.on_alert:
                    try:
                        logger.info(
                            "[Collector] DAILY ECONOMIC ALERT: %d economic signals "
                            "from daily collectors — feeding to PatternAccumulator",
                            len(new_alerts),
                        )
                        await asyncio.get_event_loop().run_in_executor(
                            None, self.on_alert, list(new_alerts),
                        )
                    except Exception as e:
                        logger.warning("[Collector] Daily alert callback failed: %s", e)
            except Exception as e:
                logger.error("[Collector] Daily loop error: %s", e)
            await asyncio.sleep(24 * 60 * 60)

    # ── GDELT DOC 2.0 (FREE, no key, Tier 1 — primary structured news) ──

    async def _collect_gdelt(self):
        """Collect from GDELT DOC 2.0 API — primary global news intelligence.

        130+ countries, 65 languages, real-time event monitoring.
        Returns structured JSON with articles from worldwide media.
        Rate limit: 1 request per 5 seconds — we use 30s between queries.

        Implements exponential backoff, response caching, and auto-disable
        after repeated failures.
        """
        if self._gdelt_disabled:
            if time.time() < self._gdelt_disabled_until:
                return
            logger.info("[Collector] GDELT cooldown expired, re-enabling")
            self._gdelt_disabled = False
            self._gdelt_consecutive_failures = 0

        all_queries = [
            '(economy OR inflation OR "interest rate" OR "central bank")',
            '(war OR conflict OR sanctions OR "military" OR "cease fire")',
            '(election OR government OR policy OR "political crisis")',
            '(technology OR AI OR semiconductor OR "artificial intelligence")',
            '(trade OR tariff OR "supply chain" OR "trade war")',
        ]
        # Rotate queries — run _gdelt_queries_per_cycle per cycle, cycling through all domains
        n = len(all_queries)
        start = self._gdelt_query_offset % n
        indices = [(start + i) % n for i in range(self._gdelt_queries_per_cycle)]
        queries = [all_queries[i] for i in indices]
        self._gdelt_query_offset += self._gdelt_queries_per_cycle
        logger.info("[Collector] GDELT DOC: running %d/%d queries this cycle (domains: %s)",
                    len(queries), n, [i + 1 for i in indices])

        any_success = False
        client_recreated_this_cycle = False
        now = time.time()

        # Prune expired cache entries
        self._gdelt_cache = {
            k: v for k, v in self._gdelt_cache.items()
            if now - v[0] < self._gdelt_cache_ttl
        }

        for i, query in enumerate(queries):
            try:
                # Check cache first — skip query if we got results within cache TTL
                if query in self._gdelt_cache:
                    cached_ts, cached_articles = self._gdelt_cache[query]
                    if now - cached_ts < self._gdelt_cache_ttl:
                        logger.debug("[Collector] GDELT cache hit for '%s' (%d articles, %.0fs ago)",
                                     query[:40], len(cached_articles), now - cached_ts)
                        continue

                # 30-45s between queries (rate-limit safe margin with jitter)
                if i > 0:
                    await asyncio.sleep(30 + random.uniform(0, 15))
                elif self._gdelt_consecutive_failures > 0 and not any_success:
                    await asyncio.sleep(min(20 * self._gdelt_consecutive_failures, 120))

                resp = await self._client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={
                        "query": query,
                        "mode": "artlist",
                        "maxrecords": 75,
                        "timespan": "24h",
                        "format": "json",
                        "sort": "datedesc",
                    },
                )
                if resp.status_code == 429:
                    self._gdelt_consecutive_failures += 1
                    self._gdelt_rate_limited_recently = True
                    wait = min(self._gdelt_backoff_seconds * (2 ** self._gdelt_consecutive_failures), 300)
                    logger.info("[Collector] GDELT rate-limited, backoff %ds (failures=%d/%d)",
                                wait, self._gdelt_consecutive_failures, self._gdelt_max_failures)
                    if self._gdelt_consecutive_failures >= self._gdelt_max_failures:
                        self._disable_gdelt()
                        logger.warning("[Collector] GDELT disabled after %d consecutive failures (cooldown 10min).",
                                       self._gdelt_consecutive_failures)
                    # Stop cycle on rate-limit — remaining queries run next cycle
                    logger.info("[Collector] GDELT stopping cycle early after 429 — remaining queries deferred")
                    return
                if resp.status_code != 200:
                    self._gdelt_consecutive_failures += 1
                    logger.warning("[Collector] GDELT HTTP %d for query '%s' (failures=%d)",
                                   resp.status_code, query[:40], self._gdelt_consecutive_failures)
                    if self._gdelt_consecutive_failures >= self._gdelt_max_failures:
                        self._disable_gdelt()
                        logger.warning("[Collector] GDELT disabled after %d consecutive failures (cooldown 10min).",
                                       self._gdelt_consecutive_failures)
                        return
                    continue

                # Check Content-Type before parsing — GDELT returns HTML on errors
                content_type = resp.headers.get("content-type", "")
                if "json" not in content_type and "javascript" not in content_type:
                    self._gdelt_consecutive_failures += 1
                    logger.warning(
                        "[Collector] GDELT returned non-JSON content-type '%s' for '%s' (failures=%d)",
                        content_type[:50], query[:40], self._gdelt_consecutive_failures,
                    )
                    if self._gdelt_consecutive_failures >= self._gdelt_max_failures:
                        self._disable_gdelt()
                    continue

                try:
                    data = resp.json()
                except Exception:
                    self._gdelt_consecutive_failures += 1
                    logger.warning("[Collector] GDELT returned unparseable response for '%s' (failures=%d, body=%s)",
                                   query[:40], self._gdelt_consecutive_failures, resp.text[:200])
                    if self._gdelt_consecutive_failures >= self._gdelt_max_failures:
                        self._disable_gdelt()
                        logger.warning("[Collector] GDELT disabled after %d consecutive failures (cooldown 10min).",
                                       self._gdelt_consecutive_failures)
                        return
                    continue

                # Success — reset backoff per-query (not just end of cycle)
                any_success = True
                self._gdelt_consecutive_failures = 0

                articles = data.get("articles", [])

                # Cache this response to avoid redundant requests
                self._gdelt_cache[query] = (time.time(), articles)

                for article in articles:
                    event_hash = hashlib.md5(
                        (article.get("title", "") + article.get("url", "")).encode()
                    ).hexdigest()

                    headline = article.get("title", "").strip()
                    if not headline:
                        continue

                    # Feed into Entity Knowledge Graph
                    if self.entity_graph:
                        try:
                            ents = self.entity_graph.ingest_headline(
                                headline, source=f"GDELT/{article.get('domain', 'unknown')}",
                            )
                            if ents:
                                logger.debug("[Collector] NER/GDELT: %d entities → %s",
                                             len(ents), [n for n, _ in ents[:4]])
                        except Exception as e:
                            logger.debug("[Collector] EntityGraph/GDELT error: %s", e)

                    # Classify through filter
                    classified = self.filter.classify(
                        headline=headline,
                        content=article.get("seendate", ""),
                        source_name=f"GDELT/{article.get('domain', 'unknown')}",
                        source_tier=1,
                        source_region=self._gdelt_region(article),
                    )
                    if not classified:
                        continue

                    self.db.store_event(
                        source_name=f"GDELT/{article.get('domain', 'unknown')}",
                        source_tier=1,
                        source_region=classified["region_focus"][0] if classified["region_focus"] else "MULTI",
                        headline=classified["headline"],
                        summary=article.get("socialimage", ""),
                        content_type=classified["content_type"],
                        domain=classified["domain"],
                        region_focus=classified["region_focus"],
                        salience_score=classified["salience_score"],
                        event_hash=event_hash,
                        source_url=article.get("url", ""),
                        published_at=article.get("seendate", ""),
                        raw_payload=article,
                    )

                    # Accumulate high-salience events for proactive alerts
                    if classified["salience_score"] >= self._alert_threshold:
                        self._pending_alerts.append({
                            "headline": classified["headline"],
                            "source": f"GDELT/{article.get('domain', 'unknown')}",
                            "domain": classified["domain"],
                            "salience": classified["salience_score"],
                            "region": classified["region_focus"],
                        })

                logger.info("[Collector] GDELT: processed %d articles for '%s'", len(articles), query[:50])

            except Exception as e:
                self._gdelt_consecutive_failures += 1
                err_type = type(e).__name__
                logger.warning("[Collector] GDELT error for '%s': [%s] %s (failures=%d/%d)",
                               query[:50], err_type, e, self._gdelt_consecutive_failures, self._gdelt_max_failures)

                # On connection errors, recreate the HTTP client ONCE per cycle (stale pool)
                if not client_recreated_this_cycle and (
                    "Connect" in err_type or "Pool" in err_type or "Timeout" in err_type
                ):
                    try:
                        logger.info("[Collector] Recreating HTTP client after connection error")
                        old = self._client
                        self._client = self._build_client()
                        await old.aclose()
                        client_recreated_this_cycle = True
                    except Exception:
                        pass
                    # Wait extra after recreating client to let DNS/TCP settle
                    await asyncio.sleep(15)

                if self._gdelt_consecutive_failures >= self._gdelt_max_failures:
                    self._disable_gdelt()
                    logger.warning("[Collector] GDELT disabled after %d consecutive failures (cooldown 10min).",
                                   self._gdelt_consecutive_failures)
                    return

        # If at least one query succeeded, reset failure counters
        if any_success:
            self._gdelt_consecutive_failures = 0
            self._gdelt_backoff_seconds = 10
            self._gdelt_rate_limited_recently = False

    @staticmethod
    def _gdelt_region(article: dict) -> str:
        """Infer region from GDELT article domain."""
        domain = article.get("domain", "").lower()
        region_map = {
            ".cn": "CN", ".ru": "RU", ".jp": "JP", ".kr": "KR",
            ".in": "IN", ".br": "BR", ".de": "EU", ".fr": "EU",
            ".uk": "UK", ".gov": "US", "reuters": "MULTI",
            "bbc": "UK", "aljazeera": "MULTI", "xinhua": "CN",
        }
        for key, region in region_map.items():
            if key in domain:
                return region
        return "MULTI"

    # ── CAMEO Event Root Codes (used by GDELT Events) ──
    _CAMEO_ROOT_CODES = {
        "01": "Make public statement",
        "02": "Appeal",
        "03": "Express intent to cooperate",
        "04": "Consult",
        "05": "Engage in diplomatic cooperation",
        "06": "Engage in material cooperation",
        "07": "Provide aid",
        "08": "Yield",
        "09": "Investigate",
        "10": "Demand",
        "11": "Disapprove",
        "12": "Reject",
        "13": "Threaten",
        "14": "Protest",
        "15": "Exhibit military posture",
        "16": "Reduce relations",
        "17": "Coerce",
        "18": "Assault",
        "19": "Fight",
        "20": "Engage in unconventional mass violence",
    }

    # ── GDELT Events (CAMEO-coded, CSV bulk download, Tier 1) ──

    async def _collect_gdelt_events(self):
        """Download GDELT Events export (15-min updates) and extract high-impact events.

        Each 15-min update contains ~1000 events, coded with CAMEO event codes,
        Goldstein scale (-10 to +10), actor info, and geolocation.
        We filter for high-conflict events (Goldstein < -5, mentions >= 3).
        """
        if self._gdelt_disabled:
            if time.time() < self._gdelt_disabled_until:
                return
            logger.info("[Collector] GDELT Events: cooldown expired, re-enabling")
            self._gdelt_disabled = False
            self._gdelt_consecutive_failures = 0
        try:
            # Get lastupdate.txt for the latest export URL
            # Uses no-verify client — data.gdeltproject.org has a known SSL cert mismatch
            resp = await self._gdelt_data_client.get(
                "https://data.gdeltproject.org/gdeltv2/lastupdate.txt",
                timeout=15.0,
            )
            if resp.status_code != 200:
                logger.warning("[Collector] GDELT lastupdate.txt HTTP %d", resp.status_code)
                return

            # First line is the events export URL
            export_url = None
            for line in resp.text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 3 and "export" in parts[2].lower():
                    export_url = parts[2]
                    break

            if not export_url:
                logger.warning("[Collector] GDELT lastupdate.txt: no export URL found")
                return

            # Download the ZIP
            zip_resp = await self._gdelt_data_client.get(export_url, timeout=30.0)
            if zip_resp.status_code != 200:
                # Fall back to previous 15-min slot
                ts = export_url.split("/")[-1].split(".")[0]
                try:
                    dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
                    prev_dt = dt - timedelta(minutes=15)
                    prev_url = export_url.replace(ts, prev_dt.strftime("%Y%m%d%H%M%S"))
                    zip_resp = await self._gdelt_data_client.get(prev_url, timeout=30.0)
                    if zip_resp.status_code != 200:
                        logger.warning("[Collector] GDELT Events CSV HTTP %d (both current and prev slot)", zip_resp.status_code)
                        return
                except Exception:
                    logger.warning("[Collector] GDELT Events CSV HTTP %d", zip_resp.status_code)
                    return

            # Extract and parse CSV from ZIP
            zf = zipfile.ZipFile(io.BytesIO(zip_resp.content))
            csv_name = zf.namelist()[0]
            raw = zf.read(csv_name).decode("utf-8", errors="replace")

            stored = 0
            for line in raw.strip().split("\n"):
                cols = line.split("\t")
                if len(cols) < 61:
                    continue

                try:
                    goldstein = float(cols[30]) if cols[30] else 0.0
                    num_mentions = int(cols[31]) if cols[31] else 0
                    avg_tone = float(cols[34]) if cols[34] else 0.0
                except (ValueError, IndexError):
                    continue

                # Filter: only high-conflict events (negative Goldstein, multiple mentions)
                if goldstein >= -5 or num_mentions < 3:
                    continue

                event_code = cols[26] if len(cols) > 26 else ""
                root_code = cols[28] if len(cols) > 28 else ""
                cameo_label = self._CAMEO_ROOT_CODES.get(root_code, f"CAMEO-{root_code}")

                actor1_name = cols[6] if len(cols) > 6 else ""
                actor1_country = cols[7] if len(cols) > 7 else ""
                actor2_name = cols[16] if len(cols) > 16 else ""
                actor2_country = cols[17] if len(cols) > 17 else ""
                location = cols[36] if len(cols) > 36 else ""
                source_url = cols[60] if len(cols) > 60 else ""
                event_date = cols[1] if len(cols) > 1 else ""

                # Build headline from CAMEO data
                actor1 = actor1_name or actor1_country or "Unknown"
                actor2 = actor2_name or actor2_country or "Unknown"
                headline = f"[CAMEO {event_code}] {actor1} → {cameo_label} → {actor2}"
                if location:
                    headline += f" ({location})"

                event_hash = hashlib.md5(
                    f"gdelt_event_{event_date}_{event_code}_{actor1}_{actor2}".encode()
                ).hexdigest()

                # Map region from actor countries
                region = "MULTI"
                for country_code in [actor1_country, actor2_country]:
                    if country_code:
                        mapped = self._country_to_region(country_code)
                        if mapped != "MULTI":
                            region = mapped
                            break

                # Salience from Goldstein scale + mentions
                salience = min(1.0, abs(goldstein) / 10.0 * 0.6 + min(num_mentions / 50, 1.0) * 0.4)

                self.db.store_event(
                    source_name="GDELT/Events",
                    source_tier=1,
                    source_region=region,
                    headline=headline,
                    summary=f"Goldstein={goldstein:.1f} Tone={avg_tone:.1f} Mentions={num_mentions} CAMEO={cameo_label}",
                    content_type="event",
                    domain="SECURITY" if goldstein < -7 else "GEOPOLITICS",
                    region_focus=[region],
                    salience_score=salience,
                    event_hash=event_hash,
                    source_url=source_url,
                    published_at=event_date,
                    raw_payload={
                        "event_code": event_code,
                        "root_code": root_code,
                        "cameo_label": cameo_label,
                        "actor1": actor1_name,
                        "actor1_country": actor1_country,
                        "actor2": actor2_name,
                        "actor2_country": actor2_country,
                        "goldstein": goldstein,
                        "num_mentions": num_mentions,
                        "avg_tone": avg_tone,
                        "location": location,
                    },
                )
                stored += 1

                # High-impact events as alerts
                if salience >= self._alert_threshold:
                    self._pending_alerts.append({
                        "headline": headline,
                        "source": "GDELT/Events",
                        "domain": "SECURITY" if goldstein < -7 else "GEOPOLITICS",
                        "salience": salience,
                        "region": [region],
                    })

            logger.info("[Collector] GDELT Events: stored %d high-conflict events from CAMEO data", stored)

        except Exception as e:
            logger.warning("[Collector] GDELT Events error: [%s] %s", type(e).__name__, e)

    # ── GDELT Global Knowledge Graph (GKG) — entities, themes, tone ──

    async def _collect_gdelt_gkg(self):
        """Download GDELT GKG export (15-min updates) and extract entity/theme data.

        GKG provides structured knowledge: who (persons, organizations),
        what (themes), where (locations), and sentiment (tone).
        Much richer than article headlines — this is the GDELT metadata layer.
        """
        if self._gdelt_disabled:
            if time.time() < self._gdelt_disabled_until:
                return
            logger.info("[Collector] GDELT GKG: cooldown expired, re-enabling")
            self._gdelt_disabled = False
            self._gdelt_consecutive_failures = 0
        try:
            # Get lastupdate.txt for the latest GKG URL
            # Uses no-verify client — data.gdeltproject.org has a known SSL cert mismatch
            resp = await self._gdelt_data_client.get(
                "https://data.gdeltproject.org/gdeltv2/lastupdate.txt",
                timeout=15.0,
            )
            if resp.status_code != 200:
                logger.warning("[Collector] GDELT GKG lastupdate HTTP %d", resp.status_code)
                return

            gkg_url = None
            for line in resp.text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 3 and "gkg" in parts[2].lower():
                    gkg_url = parts[2]
                    break

            if not gkg_url:
                logger.warning("[Collector] GDELT lastupdate.txt: no GKG URL found")
                return

            # Download GKG ZIP — with multi-slot fallback for 404 race condition
            # GKG files are announced in lastupdate.txt before they finish uploading.
            # Try the announced URL first, then fall back through up to 4 previous
            # 15-minute slots until we find a ready file.
            zip_resp = await self._gdelt_data_client.get(gkg_url, timeout=30.0)
            if zip_resp.status_code == 404:
                ts = gkg_url.split("/")[-1].split(".")[0]
                try:
                    dt = datetime.strptime(ts, "%Y%m%d%H%M%S")
                    for slots_back in range(1, 5):
                        prev_dt = dt - timedelta(minutes=15 * slots_back)
                        prev_url = gkg_url.replace(ts, prev_dt.strftime("%Y%m%d%H%M%S"))
                        zip_resp = await self._gdelt_data_client.get(prev_url, timeout=30.0)
                        if zip_resp.status_code == 200:
                            logger.debug("[Collector] GDELT GKG: used slot -%d (-%dmin)",
                                         slots_back, slots_back * 15)
                            break
                except Exception:
                    pass

            if zip_resp.status_code != 200:
                logger.warning("[Collector] GDELT GKG CSV HTTP %d", zip_resp.status_code)
                return

            # Extract and parse GKG CSV
            zf = zipfile.ZipFile(io.BytesIO(zip_resp.content))
            csv_name = zf.namelist()[0]
            raw = zf.read(csv_name).decode("utf-8", errors="replace")

            stored = 0
            for line in raw.strip().split("\n"):
                cols = line.split("\t")
                if len(cols) < 12:
                    continue

                source_name = cols[3] if len(cols) > 3 else ""
                source_url = cols[4] if len(cols) > 4 else ""
                themes_raw = cols[7] if len(cols) > 7 else ""
                locations_raw = cols[8] if len(cols) > 8 else ""
                persons_raw = cols[9] if len(cols) > 9 else ""
                orgs_raw = cols[10] if len(cols) > 10 else ""
                tone_raw = cols[11] if len(cols) > 11 else ""

                # Parse themes (semicolon-separated)
                themes = [t.strip() for t in themes_raw.split(";") if t.strip()][:10]
                persons = [p.strip() for p in persons_raw.split(";") if p.strip()][:5]
                orgs = [o.strip() for o in orgs_raw.split(";") if o.strip()][:5]

                # Parse tone (comma-separated: tone, positive, negative, polarity, ...)
                try:
                    tone_parts = tone_raw.split(",")
                    avg_tone = float(tone_parts[0]) if tone_parts[0] else 0.0
                except (ValueError, IndexError):
                    avg_tone = 0.0

                # Filter: only entries with notable themes or entities, or strong tone
                has_content = bool(themes or persons or orgs)
                strong_tone = abs(avg_tone) > 5.0
                if not has_content and not strong_tone:
                    continue

                # Build a descriptive headline from GKG data
                headline_parts = []
                if persons:
                    headline_parts.append(f"Persons: {', '.join(persons[:3])}")
                if orgs:
                    headline_parts.append(f"Orgs: {', '.join(orgs[:3])}")
                if themes:
                    headline_parts.append(f"Themes: {', '.join(themes[:3])}")

                headline = "[GKG] " + " | ".join(headline_parts) if headline_parts else "[GKG] Unstructured entry"

                event_hash = hashlib.md5(
                    f"gdelt_gkg_{source_url}_{themes_raw[:50]}".encode()
                ).hexdigest()

                # Infer domain from themes
                domain = "GENERAL"
                theme_str = themes_raw.upper()
                if any(t in theme_str for t in ["MILITARY", "TERROR", "CONFLICT", "KILL", "ARREST"]):
                    domain = "SECURITY"
                elif any(t in theme_str for t in ["ECON", "TRADE", "TAX", "INFLATION", "BANK"]):
                    domain = "ECONOMY"
                elif any(t in theme_str for t in ["ELECT", "GOVERN", "DIPLOMACY", "POLITIC"]):
                    domain = "GEOPOLITICS"
                elif any(t in theme_str for t in ["TECH", "CYBER", "AI_", "SCIENCE"]):
                    domain = "TECHNOLOGY"

                # Parse location for region
                region = "MULTI"
                if locations_raw:
                    loc_parts = locations_raw.split(";")
                    if loc_parts:
                        first_loc = loc_parts[0].split("#")
                        if len(first_loc) >= 4:
                            country_code = first_loc[3].strip()[:2]
                            if country_code:
                                region = self._country_to_region(country_code)

                salience = min(1.0, abs(avg_tone) / 15.0 * 0.4 + (len(themes) / 10.0) * 0.3 + (len(persons) + len(orgs)) / 10.0 * 0.3)

                self.db.store_event(
                    source_name=f"GDELT/GKG/{source_name}" if source_name else "GDELT/GKG",
                    source_tier=1,
                    source_region=region,
                    headline=headline,
                    summary=f"Tone={avg_tone:.1f} Themes={len(themes)} Persons={len(persons)} Orgs={len(orgs)}",
                    content_type="analysis",
                    domain=domain,
                    region_focus=[region],
                    salience_score=salience,
                    event_hash=event_hash,
                    source_url=source_url,
                    published_at=cols[1] if len(cols) > 1 else "",
                    raw_payload={
                        "themes": themes,
                        "persons": persons,
                        "organizations": orgs,
                        "avg_tone": avg_tone,
                        "locations_raw": locations_raw[:200],
                        "source": source_name,
                    },
                )
                stored += 1

                # Cap per cycle to avoid flooding the DB with thousands of GKG rows
                if stored >= 200:
                    break

            logger.info("[Collector] GDELT GKG: stored %d entity/theme records", stored)

        except Exception as e:
            logger.warning("[Collector] GDELT GKG error: [%s] %s", type(e).__name__, e)

    # ── Google News RSS (FREE, no key, no rate limit — complementary news source) ──

    # Topic feeds (Google News curated categories)
    _GNEWS_TOPICS = {
        "WORLD": "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB",
        "BUSINESS": "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB",
        "TECHNOLOGY": "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB",
        "SCIENCE": "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB",
        "NATION": "CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSmxiaWdBUAE",
    }

    # Search-based queries — deep geopolitical/economic coverage
    _GNEWS_SEARCH_QUERIES = [
        ("Geopolitics", "geopolitics+sanctions+diplomacy+conflict"),
        ("War & Security", "war+military+conflict+ceasefire+nuclear"),
        ("Energy & Commodities", "oil+gas+energy+commodity+prices"),
        ("Central Banks", "central+bank+interest+rate+inflation+monetary+policy"),
        ("Trade & Economy", "trade+tariff+supply+chain+GDP+recession"),
    ]

    async def _collect_gnews(self):
        """Collect from Google News RSS — topic feeds + search queries.

        Free, no key, no rate limit. Returns up to 100 articles per search query.
        Complements GDELT with different article selection and broader coverage.
        """
        try:
            import feedparser
        except ImportError:
            logger.warning("[Collector] feedparser not installed — skipping Google News")
            return

        total_stored = 0
        loop = asyncio.get_event_loop()

        # Phase 1: Topic feeds (curated categories)
        for i, (topic_name, topic_id) in enumerate(self._GNEWS_TOPICS.items()):
            try:
                if i > 0:
                    await asyncio.sleep(2)  # throttle: 2s between GNews topic requests
                url = f"https://news.google.com/rss/topics/{topic_id}"
                feed = await loop.run_in_executor(None, self._parse_feed, url)

                for entry in feed.entries[:20]:
                    headline = entry.get("title", "").strip()
                    if not headline:
                        continue

                    # Remove " - Source" suffix that Google News adds
                    source_name = "Google News"
                    if " - " in headline:
                        parts = headline.rsplit(" - ", 1)
                        source_name = parts[1].strip() if len(parts) > 1 else "Google News"
                        headline = parts[0].strip()

                    # Feed into Entity Knowledge Graph
                    if self.entity_graph:
                        try:
                            ents = self.entity_graph.ingest_headline(
                                headline, source=f"GNews/{source_name}",
                            )
                            if ents:
                                logger.debug("[Collector] NER/GNews-topic: %d entities → %s",
                                             len(ents), [n for n, _ in ents[:4]])
                        except Exception as e:
                            logger.debug("[Collector] EntityGraph/GNews-topic error: %s", e)

                    event_hash = hashlib.md5(
                        (headline + entry.get("link", "")).encode()
                    ).hexdigest()

                    classified = self.filter.classify(
                        headline=headline,
                        content=entry.get("summary", "")[:300],
                        source_name=f"GNews/{source_name}",
                        source_tier=2,
                        source_region="MULTI",
                    )
                    if not classified:
                        continue

                    self.db.store_event(
                        source_name=f"GNews/{source_name}",
                        source_tier=2,
                        source_region=classified["region_focus"][0] if classified["region_focus"] else "MULTI",
                        headline=classified["headline"],
                        summary=entry.get("summary", "")[:300],
                        content_type=classified["content_type"],
                        domain=classified["domain"],
                        region_focus=classified["region_focus"],
                        salience_score=classified["salience_score"],
                        event_hash=event_hash,
                        source_url=entry.get("link", ""),
                        published_at=entry.get("published", ""),
                        raw_payload={"title": headline, "source": source_name, "topic": topic_name},
                    )
                    total_stored += 1

                    # Accumulate high-salience events for proactive alerts
                    if classified["salience_score"] >= self._alert_threshold:
                        self._pending_alerts.append({
                            "headline": classified["headline"],
                            "source": f"GNews/{source_name}",
                            "domain": classified["domain"],
                            "salience": classified["salience_score"],
                            "region": classified["region_focus"],
                        })

            except Exception as e:
                logger.warning("[Collector] GNews topic %s error: %s", topic_name, e)

        # Phase 2: Search queries (deep geopolitical/economic monitoring)
        for i, (query_name, query_str) in enumerate(self._GNEWS_SEARCH_QUERIES):
            try:
                if i > 0:
                    await asyncio.sleep(2)  # throttle: 2s between GNews search requests
                url = f"https://news.google.com/rss/search?q={query_str}&hl=en-US&gl=US&ceid=US:en"
                feed = await loop.run_in_executor(None, self._parse_feed, url)

                for entry in feed.entries[:25]:
                    headline = entry.get("title", "").strip()
                    if not headline:
                        continue

                    source_name = "Google News"
                    if " - " in headline:
                        parts = headline.rsplit(" - ", 1)
                        source_name = parts[1].strip() if len(parts) > 1 else "Google News"
                        headline = parts[0].strip()

                    # Feed into Entity Knowledge Graph
                    if self.entity_graph:
                        try:
                            ents = self.entity_graph.ingest_headline(
                                headline, source=f"GNews/{source_name}",
                            )
                            if ents:
                                logger.debug("[Collector] NER/GNews-search: %d entities → %s",
                                             len(ents), [n for n, _ in ents[:4]])
                        except Exception as e:
                            logger.debug("[Collector] EntityGraph/GNews-search error: %s", e)

                    event_hash = hashlib.md5(
                        (headline + entry.get("link", "")).encode()
                    ).hexdigest()

                    classified = self.filter.classify(
                        headline=headline,
                        content=entry.get("summary", "")[:300],
                        source_name=f"GNews/{source_name}",
                        source_tier=2,
                        source_region="MULTI",
                    )
                    if not classified:
                        continue

                    self.db.store_event(
                        source_name=f"GNews/{source_name}",
                        source_tier=2,
                        source_region=classified["region_focus"][0] if classified["region_focus"] else "MULTI",
                        headline=classified["headline"],
                        summary=entry.get("summary", "")[:300],
                        content_type=classified["content_type"],
                        domain=classified["domain"],
                        region_focus=classified["region_focus"],
                        salience_score=classified["salience_score"],
                        event_hash=event_hash,
                        source_url=entry.get("link", ""),
                        published_at=entry.get("published", ""),
                        raw_payload={"title": headline, "source": source_name, "search_query": query_name},
                    )
                    total_stored += 1

                    if classified["salience_score"] >= self._alert_threshold:
                        self._pending_alerts.append({
                            "headline": classified["headline"],
                            "source": f"GNews/{source_name}",
                            "domain": classified["domain"],
                            "salience": classified["salience_score"],
                            "region": classified["region_focus"],
                        })

            except Exception as e:
                logger.warning("[Collector] GNews search '%s' error: %s", query_name, e)

        if total_stored > 0:
            logger.info("[Collector] Google News: stored %d events (%d topics + %d search queries)",
                        total_stored, len(self._GNEWS_TOPICS), len(self._GNEWS_SEARCH_QUERIES))

    # ── RSS Feeds (120+ sources from feed_catalog — batched & rotated) ──

    _rss_batch_offset: int = 0          # rotate through catalog across cycles
    _RSS_BATCH_SIZE: int = 30           # feeds per 15-min cycle
    _RSS_CONCURRENCY: int = 4           # parallel feedparser tasks (was 6, reduced to avoid connection resets)

    async def _collect_rss_feeds(self):
        """Collect from RSS_CATALOG in rotating batches of _RSS_BATCH_SIZE.

        With 120+ feeds we cannot fetch them all every 15 minutes.
        Each cycle picks the next batch; full rotation every ~4-6 cycles.
        High-priority categories (crisis, defense, nuclear) are always included.
        """
        try:
            import feedparser
        except ImportError:
            logger.error("[Collector] feedparser not installed — pip install feedparser")
            return

        catalog = list(RSS_CATALOG)

        # Always-include categories — crisis-critical + economic feeds every cycle
        priority_cats = {"crisis", "defense", "nuclear", "osint", "finance", "economic"}
        priority_feeds = [f for f in catalog if f.get("category") in priority_cats]
        regular_feeds = [f for f in catalog if f.get("category") not in priority_cats]

        # Rotate regular feeds
        start = self._rss_batch_offset % max(len(regular_feeds), 1)
        batch = regular_feeds[start:start + self._RSS_BATCH_SIZE]
        if len(batch) < self._RSS_BATCH_SIZE:
            batch += regular_feeds[:self._RSS_BATCH_SIZE - len(batch)]
        self._rss_batch_offset = (start + self._RSS_BATCH_SIZE) % max(len(regular_feeds), 1)

        # Combine: priority feeds + rotated batch (deduplicate by url)
        seen_urls = set()
        cycle_feeds = []
        for f in priority_feeds + batch:
            if f["url"] not in seen_urls:
                seen_urls.add(f["url"])
                cycle_feeds.append(f)

        logger.info("[Collector] RSS cycle: %d feeds (%d priority + %d rotated) of %d total",
                    len(cycle_feeds), len(priority_feeds), len(batch), len(catalog))

        total_stored = 0
        total_alerts = 0

        # Process feeds in concurrent batches
        sem = asyncio.Semaphore(self._RSS_CONCURRENCY)

        async def _fetch_one_feed(source: dict) -> int:
            count = 0
            async with sem:
                try:
                    loop = asyncio.get_event_loop()
                    feed = await loop.run_in_executor(None, self._parse_feed, source["url"])

                    for entry in feed.entries[:15]:
                        headline = entry.get("title", "").strip()
                        if not headline:
                            continue

                        # Skip alert-excluded content (lifestyle, entertainment noise)
                        headline_lower = headline.lower()
                        if any(exc in headline_lower for exc in ALERT_EXCLUSIONS):
                            continue

                        # Feed headline into keyword spike detector
                        spikes = self.spike_detector.ingest_headline(
                            headline, source["name"],
                        )
                        for spike in spikes:
                            self._pending_alerts.append({
                                "headline": f"[KEYWORD SPIKE] '{spike.term}' — {spike.current_count} mentions from {spike.unique_sources} sources ({spike.surge_ratio}× baseline)",
                                "source": "spike_detector",
                                "domain": "MULTI",
                                "salience": 0.95,
                                "region": [],
                                "headline_score": 0,
                            })

                        # Feed headline into Entity Knowledge Graph (NER → relationship tracking)
                        if self.entity_graph:
                            try:
                                ents = self.entity_graph.ingest_headline(
                                    headline, source=source["name"],
                                )
                                if ents:
                                    logger.debug("[Collector] NER/RSS: %d entities → %s",
                                                 len(ents), [n for n, _ in ents[:4]])
                            except Exception as e:
                                logger.debug("[Collector] EntityGraph/RSS error: %s", e)

                        event_hash = hashlib.md5(
                            (headline + entry.get("link", "")).encode()
                        ).hexdigest()

                        summary_text = entry.get("summary", "")[:500]

                        classified = self.filter.classify(
                            headline=headline,
                            content=summary_text,
                            source_name=source["name"],
                            source_tier=source["tier"],
                            source_region=source["region"],
                        )
                        if not classified:
                            continue

                        published = ""
                        if hasattr(entry, "published_parsed") and entry.published_parsed:
                            try:
                                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                            except Exception:
                                pass

                        stored = self.db.store_event(
                            source_name=source["name"],
                            source_tier=source["tier"],
                            source_region=source["region"],
                            headline=classified["headline"],
                            summary=summary_text,
                            content_type=classified["content_type"],
                            domain=classified["domain"],
                            region_focus=classified["region_focus"],
                            salience_score=classified["salience_score"],
                            event_hash=event_hash,
                            source_url=entry.get("link", ""),
                            published_at=published,
                            raw_payload={
                                "title": headline,
                                "link": entry.get("link", ""),
                                "summary": summary_text,
                                "category": source.get("category", ""),
                                "propaganda_risk": get_propaganda_risk(source["name"]).get("risk", "low"),
                                "headline_score": score_headline(headline),
                            },
                        )
                        if stored:
                            count += 1
                            if classified["salience_score"] >= self._alert_threshold:
                                self._pending_alerts.append({
                                    "headline": classified["headline"],
                                    "source": source["name"],
                                    "domain": classified["domain"],
                                    "salience": classified["salience_score"],
                                    "region": classified["region_focus"],
                                    "headline_score": score_headline(headline),
                                })

                except Exception as e:
                    logger.warning("[Collector] RSS error %s: [%s] %s", source["name"], type(e).__name__, e)
            return count

        tasks = [_fetch_one_feed(src) for src in cycle_feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, int):
                total_stored += r

        if total_stored:
            logger.info("[Collector] RSS cycle complete: stored %d new events from %d feeds",
                        total_stored, len(cycle_feeds))

    # ── ACLED Conflict Data (FREE read-only, Tier 1 — replaced defunct ReliefWeb) ──

    async def _collect_acled(self):
        """Collect from ACLED curated data export — structured conflict events.

        Uses the public ACLED read-access endpoint (no key needed for basic access).
        Provides geo-coded conflict event data: battles, protests, violence against
        civilians, explosions/remote violence, riots, strategic developments.
        """
        try:
            # DNS pre-check — ACLED API has frequent DNS resolution failures
            import socket
            try:
                socket.getaddrinfo("api.acleddata.com", 443, socket.AF_INET, socket.SOCK_STREAM)
            except socket.gaierror:
                logger.debug("[Collector] ACLED DNS unreachable — skipping this cycle")
                return

            resp = await self._client.get(
                "https://api.acleddata.com/acled/read",
                params={
                    "limit": 25,
                    "terms": "accept",
                    "event_date_where": "BETWEEN",
                    "event_date": f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}|{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                },
            )
            if resp.status_code == 403:
                logger.info("[Collector] ACLED requires API key for full access — using public endpoint")
                return
            if resp.status_code != 200:
                logger.warning("[Collector] ACLED HTTP %d", resp.status_code)
                return

            data = resp.json()
            events = data.get("data", [])
            count = 0

            for item in events:
                headline = f"{item.get('event_type', '?')}: {item.get('notes', '')[:120]}"
                if not headline.strip(":").strip():
                    continue

                event_hash = hashlib.md5(
                    (str(item.get("data_id", "")) + headline).encode()
                ).hexdigest()

                country = item.get("country", "")
                region = self._country_to_region(country)

                stored = self.db.store_event(
                    source_name="ACLED",
                    source_tier=1,
                    source_region=region,
                    headline=headline,
                    summary=item.get("notes", "")[:500],
                    content_type="FACT",
                    domain="GEOPOLITICAL",
                    region_focus=[region],
                    salience_score=0.75,
                    event_hash=event_hash,
                    source_url="",
                    published_at=item.get("event_date", ""),
                    raw_payload=item,
                )
                if stored:
                    count += 1
                    # Feed high-impact ACLED events into proactive alerts
                    event_type = item.get("event_type", "").lower()
                    fatalities = int(item.get("fatalities", 0) or 0)
                    is_high_impact = (
                        fatalities >= 10
                        or event_type in ("battles", "explosions/remote violence",
                                          "violence against civilians",
                                          "strategic developments")
                    )
                    if is_high_impact:
                        self._pending_alerts.append({
                            "headline": headline,
                            "source": "ACLED",
                            "domain": "GEOPOLITICAL",
                            "salience": min(0.95, 0.80 + fatalities * 0.005),
                            "region": [region],
                        })

            if count:
                logger.info("[Collector] ACLED: stored %d new conflict events", count)

        except Exception as e:
            logger.warning("[Collector] ACLED error: %s", e)

    @staticmethod
    def _country_to_region(country: str) -> str:
        """Map country name to region code."""
        country_lower = country.lower()
        region_map = {
            "united states": "US", "china": "CN", "russia": "RU",
            "japan": "JP", "india": "IN", "brazil": "BR",
            "united kingdom": "UK", "germany": "EU", "france": "EU",
            "italy": "EU", "spain": "EU", "ukraine": "EU",
            "turkey": "MULTI", "south korea": "KR", "iran": "ME",
            "saudi arabia": "ME", "israel": "ME", "palestine": "ME",
            "egypt": "AF", "nigeria": "AF", "south africa": "AF",
        }
        for key, region in region_map.items():
            if key in country_lower:
                return region
        return "MULTI"

    # ── FRED API (Tier 1 — US economic data, free key) ──

    async def _collect_fred(self):
        """Collect from FRED (Federal Reserve Economic Data)."""
        if not self.fred_api_key:
            logger.info("[Collector] FRED API key not set — skipping US economic data")
            return

        for series_id, name, unit in FRED_SERIES:
            try:
                resp = await self._client.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series_id,
                        "api_key": self.fred_api_key,
                        "limit": 2,
                        "sort_order": "desc",
                        "file_type": "json",
                    },
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                observations = data.get("observations", [])
                if not observations:
                    continue

                current = observations[0]
                previous = observations[1] if len(observations) > 1 else None

                current_val = float(current["value"]) if current["value"] != "." else None
                previous_val = None
                change_pct = None

                if previous and previous["value"] != ".":
                    previous_val = float(previous["value"])
                    if previous_val and current_val:
                        change_pct = ((current_val - previous_val) / abs(previous_val)) * 100

                self.db.store_economic(
                    source="FRED",
                    indicator=series_id,
                    value=current_val,
                    period=current["date"],
                    unit=unit,
                    previous_value=previous_val,
                    change_pct=change_pct,
                    raw_payload=current,
                )

                logger.info("[Collector] FRED %s: %.4f %s (%s)", series_id,
                            current_val or 0, unit, current["date"])

                # ── Generate economic_shift signals for meaningful changes ──
                # These feed into PatternAccumulator to enable geo+econ fusion
                if change_pct is not None and current_val is not None:
                    abs_change = abs(change_pct)
                    # Thresholds vary by indicator type
                    is_significant = False
                    if series_id in ("FEDFUNDS", "DGS10", "TEDRATE"):
                        # Interest rates: any change > 2% relative is significant
                        is_significant = abs_change >= 2.0
                    elif series_id in ("CPIAUCSL", "T10YIE"):
                        # Inflation: > 1% relative change
                        is_significant = abs_change >= 1.0
                    elif series_id == "UNRATE":
                        # Unemployment: > 3% relative change
                        is_significant = abs_change >= 3.0
                    elif series_id in ("DCOILBRENTEU", "DHHNGSP"):
                        # Energy: > 5% change
                        is_significant = abs_change >= 5.0
                    elif series_id in ("BAMLH0A0HYM2", "STLFSI4"):
                        # Stress indicators: > 10% relative change
                        is_significant = abs_change >= 10.0
                    elif series_id in ("T10Y2Y",):
                        # Yield curve: any > 15% relative change (or inversion signal)
                        is_significant = abs_change >= 15.0 or (current_val < 0 and previous_val and previous_val >= 0)
                    elif series_id in ("DTWEXBGS", "DEXUSEU", "DEXJPUS", "DEXCHUS",
                                       "DEXMXUS", "DEXBZUS", "DEXTAUS"):
                        # Currency: > 1.5% change
                        is_significant = abs_change >= 1.5
                    elif series_id in ("M2SL", "GFDEBTN"):
                        # Money supply / debt: > 2% change
                        is_significant = abs_change >= 2.0
                    elif series_id == "UMCSENT":
                        # Consumer sentiment: > 5% change
                        is_significant = abs_change >= 5.0
                    else:
                        # Generic: > 3% relative change
                        is_significant = abs_change >= 3.0

                    if is_significant:
                        direction = "rose" if change_pct > 0 else "fell"
                        headline = (
                            f"[ECONOMIC SHIFT] FRED {name} {direction} to "
                            f"{current_val:.2f}{unit} ({change_pct:+.2f}% vs previous)"
                        )
                        self._pending_alerts.append({
                            "headline": headline,
                            "source": "FRED",
                            "domain": "ECONOMIC",
                            "salience": 0.90,
                            "region": ["US"],
                            "signal_type": "economic_shift",
                        })
                        logger.info("[Collector] FRED economic_shift signal: %s", headline)

            except Exception as e:
                logger.warning("[Collector] FRED error %s: %s", series_id, e)

    # ── World Bank API (FREE, no key, Tier 1) ──

    # Change thresholds per WorldBank indicator type (% relative change)
    _WORLDBANK_THRESHOLDS = {
        "NY.GDP.MKTP.KD.ZG": 1.0,   # GDP growth: >1pp shift is significant
        "FP.CPI.TOTL.ZG": 1.5,      # CPI inflation: >1.5pp shift
        "SL.UEM.TOTL.ZS": 1.0,      # Unemployment: >1pp shift
        "BX.KLT.DINV.CD.WD": 10.0,  # FDI: >10% change (volatile)
        "DT.DOD.DECT.CD": 5.0,      # External debt: >5% change
    }

    async def _collect_worldbank(self):
        """Collect from World Bank API v2 — 16,000+ global indicators.

        Some indicators (CPI, debt stock) may not have WLD aggregate data.
        Falls back progressively: world → composite → individual countries.

        WorldBank API is unreliable (frequent 502s, timeouts). Uses:
          - Per-request 15s timeout (shorter than default to not block cycle)
          - Graceful skip on any HTTP error (API has frequent outages)

        Change detection: fetches last 2 values (mrnev=2) and fires
        economic_shift signals when the latest value deviates significantly
        from the previous one.
        """
        # Fallback chains: composite first, then individual countries
        country_sets = [
            "WLD",
            "USA;CHN;EMU",
            "USA",
        ]

        total_stored = 0
        total_skipped = 0

        for indicator_id, name, unit in WORLDBANK_INDICATORS:
            got_data = False
            for country_set in country_sets:
                if got_data:
                    break
                try:
                    resp = await self._client.get(
                        f"https://api.worldbank.org/v2/country/{country_set}/indicator/{indicator_id}",
                        params={
                            "format": "json",
                            "per_page": 5,
                            "mrv": 2,  # Most Recent Values — last 2 non-empty for change detection
                        },
                        timeout=15.0,  # Short timeout — WorldBank is flaky
                    )
                    if resp.status_code >= 500:
                        # Server error — WorldBank outage, skip to next indicator entirely
                        logger.debug("[Collector] WorldBank %d for %s — server error, skipping indicator",
                                     resp.status_code, name)
                        break  # Don't try other country sets for this indicator
                    if resp.status_code != 200:
                        logger.debug("[Collector] WorldBank HTTP %d for %s (%s) — trying next",
                                     resp.status_code, name, country_set)
                        continue

                    data = resp.json()
                    if not isinstance(data, list) or len(data) < 2:
                        continue

                    records = data[1]
                    if not records:
                        continue

                    # Collect valid values sorted by date (newest first)
                    valid_records: list[tuple[str, float, str, dict]] = []
                    stored_count = 0
                    for record in records:
                        value = record.get("value")
                        if value is None:
                            continue

                        country = record.get("country", {}).get("value", "World")
                        period = record.get("date", "")

                        self.db.store_economic(
                            source="WorldBank",
                            indicator=f"{indicator_id}/{country}",
                            value=float(value),
                            period=period,
                            unit=unit,
                            raw_payload=record,
                        )
                        stored_count += 1
                        valid_records.append((period, float(value), country, record))

                    if stored_count > 0:
                        logger.info("[Collector] WorldBank %s: %d records from %s",
                                    name, stored_count, country_set)
                        got_data = True
                        total_stored += stored_count

                    # ── Change detection: compare latest two values ──
                    if len(valid_records) >= 2:
                        # Records come newest-first from WorldBank API
                        curr_period, curr_val, curr_country, _ = valid_records[0]
                        prev_period, prev_val, _, _ = valid_records[1]

                        if prev_val and abs(prev_val) > 1e-9:
                            # For rates (%, index), use absolute difference in percentage points
                            # For monetary values (USD), use relative % change
                            if unit == "%":
                                change_pp = curr_val - prev_val
                                threshold = self._WORLDBANK_THRESHOLDS.get(indicator_id, 2.0)
                                is_significant = abs(change_pp) >= threshold
                                change_desc = f"{change_pp:+.2f}pp"
                            else:
                                change_pct = ((curr_val - prev_val) / abs(prev_val)) * 100
                                threshold = self._WORLDBANK_THRESHOLDS.get(indicator_id, 5.0)
                                is_significant = abs(change_pct) >= threshold
                                change_desc = f"{change_pct:+.1f}%"

                            if is_significant:
                                direction = "rose" if curr_val > prev_val else "fell"
                                headline = (
                                    f"[ECONOMIC SHIFT] WorldBank {name} {direction}: "
                                    f"{curr_val:.2f}{unit} ({change_desc} vs {prev_period})"
                                )
                                self._pending_alerts.append({
                                    "headline": headline,
                                    "source": "WorldBank",
                                    "domain": "ECONOMIC",
                                    "salience": 0.87,
                                    "region": ["GLOBAL"],
                                    "signal_type": "economic_shift",
                                })
                                logger.info("[Collector] WorldBank economic_shift signal: %s", headline)

                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    # Network-level failure — WorldBank is down, skip indicator
                    logger.debug("[Collector] WorldBank %s timeout/connect error: %s — skipping indicator", name, e)
                    break  # Don't try other country sets
                except Exception as e:
                    logger.debug("[Collector] WorldBank %s (%s) error: %s", name, country_set, e)

            if not got_data:
                total_skipped += 1
                logger.debug("[Collector] WorldBank %s: no data from any country set — skipping", name)

        if total_stored > 0:
            logger.info("[Collector] WorldBank cycle: %d records stored, %d indicators skipped",
                        total_stored, total_skipped)
        elif total_skipped > 0:
            logger.info("[Collector] WorldBank: all %d indicators failed (API may be down)", total_skipped)

    # ── ECB API (FREE, Tier 1 — EU economic data) ──

    # ECB change detection thresholds
    _ECB_THRESHOLDS = {
        "Euro Area HICP Inflation": 0.3,     # Inflation: >0.3pp monthly change
        "EUR/USD Exchange Rate": 1.0,         # FX: >1% change
    }

    async def _collect_ecb(self):
        """Collect from ECB Statistical Data Warehouse (SDMX-JSON API).

        Change detection: fetches last 2 observations per series and fires
        economic_shift signals for significant moves — inflation jumps,
        EUR/USD volatility, etc.
        """
        # ECB SDMX endpoint: data-api.ecb.europa.eu/service/data/{flowRef}/{key}
        # The key uses dots as dimension separators within the dataflow
        ecb_series = [
            ("ICP", "M.U2.N.000000.4.ANR", "Euro Area HICP Inflation", "%"),
            ("EXR", "D.USD.EUR.SP00.A", "EUR/USD Exchange Rate", "USD"),
        ]

        for flow_ref, key, name, unit in ecb_series:
            try:
                resp = await self._client.get(
                    f"https://data-api.ecb.europa.eu/service/data/{flow_ref}/{key}",
                    params={"format": "jsondata", "lastNObservations": 2},
                )
                if resp.status_code != 200:
                    logger.warning("[Collector] ECB HTTP %d for %s", resp.status_code, name)
                    continue

                data = resp.json()

                # Parse ECB SDMX-JSON structure
                observations = self._parse_ecb_response(data)
                for period, value in observations:
                    self.db.store_economic(
                        source="ECB",
                        indicator=name,
                        value=value,
                        period=period,
                        unit=unit,
                        raw_payload={"flow_ref": flow_ref, "key": key, "period": period, "value": value},
                    )

                if observations:
                    logger.info("[Collector] ECB %s: %d observations", name, len(observations))

                # ── Change detection: compare the 2 most recent observations ──
                if len(observations) >= 2:
                    # observations are (period, value) tuples, newest last from SDMX
                    curr_period, curr_val = observations[-1]
                    prev_period, prev_val = observations[-2]

                    if prev_val and abs(prev_val) > 1e-9:
                        # For inflation (%), use absolute difference in percentage points
                        # For exchange rates, use relative % change
                        if unit == "%":
                            change_pp = curr_val - prev_val
                            threshold = self._ECB_THRESHOLDS.get(name, 0.5)
                            is_significant = abs(change_pp) >= threshold
                            change_desc = f"{change_pp:+.2f}pp"
                        else:
                            change_pct = ((curr_val - prev_val) / abs(prev_val)) * 100
                            threshold = self._ECB_THRESHOLDS.get(name, 1.0)
                            is_significant = abs(change_pct) >= threshold
                            change_desc = f"{change_pct:+.2f}%"

                        if is_significant:
                            direction = "rose" if curr_val > prev_val else "fell"
                            headline = (
                                f"[ECONOMIC SHIFT] ECB {name} {direction}: "
                                f"{curr_val:.4f} {unit} ({change_desc} vs {prev_period})"
                            )
                            self._pending_alerts.append({
                                "headline": headline,
                                "source": "ECB",
                                "domain": "ECONOMIC",
                                "salience": 0.88,
                                "region": ["EU"],
                                "signal_type": "economic_shift",
                            })
                            logger.info("[Collector] ECB economic_shift signal: %s", headline)

            except Exception as e:
                logger.warning("[Collector] ECB error %s: %s", name, e)

    @staticmethod
    def _parse_ecb_response(data: dict) -> list[tuple[str, float]]:
        """Parse ECB SDMX-JSON response into (period, value) tuples."""
        results = []
        try:
            datasets = data.get("dataSets", [{}])
            if not datasets:
                return results

            series = datasets[0].get("series", {})
            for key, series_data in series.items():
                observations = series_data.get("observations", {})
                for idx, obs_values in observations.items():
                    if obs_values and obs_values[0] is not None:
                        results.append((str(idx), float(obs_values[0])))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        return results

    # ── Status ──

    def status(self) -> dict:
        """Return current collector status."""
        return {
            "events_stored": self.db.event_count(),
            "economic_stored": self.db.economic_count(),
            "fred_enabled": bool(self.fred_api_key),
            "ucdp_enabled": bool(self.ucdp_api_token),
            "rss_sources": len(RSS_SOURCES),
            "spike_detector_terms": self.spike_detector.registry_size,
            "recent_spikes": len(self.spike_detector.get_recent_spikes()),
        }

    # ── USGS Earthquake Hazards (FREE, no key, Tier 1) ──

    async def _collect_usgs_earthquakes(self):
        """Collect significant earthquakes from USGS GeoJSON feed.

        Free, no API key, updates every 5 minutes.
        Returns M2.5+ earthquakes from the last hour.
        """
        try:
            resp = await self._client.get(
                "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_hour.geojson",
            )
            if resp.status_code != 200:
                logger.warning("[Collector] USGS HTTP %d", resp.status_code)
                return

            data = resp.json()
            features = data.get("features", [])
            count = 0

            for quake in features:
                props = quake.get("properties", {})
                geo = quake.get("geometry", {})

                magnitude = props.get("mag", 0)
                place = props.get("place", "Unknown")
                quake_time = props.get("time", 0)
                url = props.get("url", "")
                tsunami = props.get("tsunami", 0)
                alert_level = props.get("alert", "")  # green/yellow/orange/red
                coords = geo.get("coordinates", [0, 0, 0])

                headline = f"M{magnitude:.1f} earthquake — {place}"
                if tsunami:
                    headline += " [TSUNAMI WARNING]"

                event_hash = hashlib.md5(
                    f"usgs-{props.get('ids', headline)}".encode()
                ).hexdigest()

                # Classify salience by magnitude
                if magnitude >= 7.0:
                    salience = 0.95
                elif magnitude >= 6.0:
                    salience = 0.85
                elif magnitude >= 5.0:
                    salience = 0.70
                elif magnitude >= 4.0:
                    salience = 0.55
                else:
                    salience = 0.40

                if tsunami:
                    salience = min(1.0, salience + 0.10)

                published = ""
                if quake_time:
                    try:
                        published = datetime.fromtimestamp(
                            quake_time / 1000, tz=timezone.utc,
                        ).isoformat()
                    except Exception:
                        pass

                stored = self.db.store_event(
                    source_name="USGS",
                    source_tier=1,
                    source_region="GLOBAL",
                    headline=headline,
                    summary=f"Magnitude {magnitude:.1f} at depth {coords[2]:.0f}km. {place}. Alert: {alert_level or 'none'}.",
                    content_type="DATA",
                    domain="GEOPOLITICAL",
                    region_focus=["GLOBAL"],
                    salience_score=salience,
                    event_hash=event_hash,
                    source_url=url,
                    published_at=published,
                    raw_payload={
                        "magnitude": magnitude,
                        "place": place,
                        "coordinates": coords,
                        "tsunami": tsunami,
                        "alert": alert_level,
                        "depth_km": coords[2] if len(coords) > 2 else 0,
                    },
                )
                if stored:
                    count += 1
                    if salience >= self._alert_threshold:
                        self._pending_alerts.append({
                            "headline": headline,
                            "source": "USGS",
                            "domain": "GEOPOLITICAL",
                            "salience": salience,
                            "region": ["GLOBAL"],
                        })

            if count:
                logger.info("[Collector] USGS: stored %d earthquakes", count)

        except Exception as e:
            logger.warning("[Collector] USGS error: [%s] %s", type(e).__name__, e)

    # ── NASA EONET (FREE, no key, Tier 1 — natural events) ──

    async def _collect_nasa_eonet(self):
        """Collect active natural events from NASA Earth Observatory.

        Free, no key. Returns wildfires, volcanic eruptions, severe storms,
        floods, and other natural hazards.
        """
        try:
            resp = await self._client.get(
                "https://eonet.gsfc.nasa.gov/api/v3/events",
                params={"status": "open", "limit": 30, "days": 3},
            )
            if resp.status_code != 200:
                logger.warning("[Collector] NASA EONET HTTP %d", resp.status_code)
                return

            data = resp.json()
            events = data.get("events", [])
            count = 0

            for event in events:
                title = event.get("title", "")
                event_id = event.get("id", "")
                categories = event.get("categories", [])
                sources = event.get("sources", [])
                geometries = event.get("geometry", [])

                if not title:
                    continue

                cat_names = [c.get("title", "") for c in categories]
                cat_str = ", ".join(cat_names)

                # Get latest geometry point
                coords = None
                event_date = ""
                if geometries:
                    latest = geometries[-1]
                    coords = latest.get("coordinates")
                    event_date = latest.get("date", "")

                source_urls = [s.get("url", "") for s in sources if s.get("url")]
                headline = f"[EONET] {title}"

                event_hash = hashlib.md5(
                    f"eonet-{event_id}".encode()
                ).hexdigest()

                # Salience by category
                high_impact = {"Volcanoes", "Earthquakes", "Severe Storms", "Floods"}
                salience = 0.75 if any(c in high_impact for c in cat_names) else 0.55

                stored = self.db.store_event(
                    source_name="NASA-EONET",
                    source_tier=1,
                    source_region="GLOBAL",
                    headline=headline,
                    summary=f"Categories: {cat_str}. Sources: {len(sources)}.",
                    content_type="DATA",
                    domain="GEOPOLITICAL",
                    region_focus=["GLOBAL"],
                    salience_score=salience,
                    event_hash=event_hash,
                    source_url=source_urls[0] if source_urls else "",
                    published_at=event_date,
                    raw_payload={
                        "eonet_id": event_id,
                        "categories": cat_names,
                        "coordinates": coords,
                        "source_count": len(sources),
                    },
                )
                if stored:
                    count += 1

            if count:
                logger.info("[Collector] NASA EONET: stored %d natural events", count)

        except Exception as e:
            logger.warning("[Collector] NASA EONET error: %s", e)

    # ── UCDP Conflict Data (FREE, no key, Tier 1 — Uppsala University) ──

    async def _collect_ucdp(self):
        """Collect from UCDP GED / Candidate Events API.

        Academic API from Uppsala Conflict Data Program.
        Provides structured conflict event data with fatality estimates.
        Since Feb 2026, requires token auth via x-ucdp-access-token header.
        Token: email mertcan.yilmaz@pcr.uu.se to request.
        """
        if not self.ucdp_api_token:
            logger.info("[Collector] UCDP: no API token set (UCDP_API_TOKEN) — skipping. "
                        "Request token at mertcan.yilmaz@pcr.uu.se")
            return

        try:
            current_year = datetime.now(timezone.utc).year

            # UCDP version format: GED=YY.N, Candidate monthly=YY.0.M, quarterly=YY.01.YY.MM
            # See https://ucdp.uu.se/apidocs/ for available versions
            api_urls = [
                f"https://ucdpapi.pcr.uu.se/api/gedevents/25.1",
                f"https://ucdpapi.pcr.uu.se/api/gedevents/24.1",
                f"https://ucdpapi.pcr.uu.se/api/candidateevents/26.0.2",
                f"https://ucdpapi.pcr.uu.se/api/candidateevents/26.0.1",
                f"https://ucdpapi.pcr.uu.se/api/candidateevents/25.0.12",
                f"https://ucdpapi.pcr.uu.se/api/candidateevents/25.01.25.12",
            ]

            headers = {"x-ucdp-access-token": self.ucdp_api_token}

            resp = None
            for url in api_urls:
                try:
                    resp = await self._client.get(
                        url,
                        params={
                            "pagesize": 50,
                            "page": 0,
                            "Year": current_year,
                        },
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        break
                    logger.debug("[Collector] UCDP %s returned HTTP %d, trying next",
                                 url.split("/api/")[-1], resp.status_code)
                    resp = None
                except Exception:
                    resp = None

            if not resp or resp.status_code != 200:
                logger.warning("[Collector] UCDP: all endpoints unavailable (token may be expired) — skipping")
                return

            data = resp.json()
            events = data.get("Result", [])
            count = 0

            for item in events:
                event_id = item.get("id", "")
                country = item.get("country", "Unknown")
                region = item.get("region", "")
                date_start = item.get("date_start", "")
                date_end = item.get("date_end", "")
                deaths_a = item.get("deaths_a", 0) or 0
                deaths_b = item.get("deaths_b", 0) or 0
                deaths_civilians = item.get("deaths_civilians", 0) or 0
                deaths_unknown = item.get("deaths_unknown", 0) or 0
                total_deaths = deaths_a + deaths_b + deaths_civilians + deaths_unknown
                event_type = item.get("type_of_violence", "")
                source_article = item.get("source_article", "")

                # Violence type labels
                type_labels = {
                    1: "state-based",
                    2: "non-state",
                    3: "one-sided violence",
                }
                type_str = type_labels.get(event_type, f"type-{event_type}")

                side_a = item.get("side_a", "Unknown")
                side_b = item.get("side_b", "Unknown")
                headline = f"[UCDP] {country}: {side_a} vs {side_b} — {total_deaths} fatalities ({type_str})"
                if total_deaths == 0:
                    headline = f"[UCDP] {country}: {side_a} vs {side_b} ({type_str})"

                event_hash = hashlib.md5(
                    f"ucdp-{event_id}".encode()
                ).hexdigest()

                # Salience by fatality count
                if total_deaths >= 50:
                    salience = 0.90
                elif total_deaths >= 10:
                    salience = 0.75
                elif total_deaths > 0:
                    salience = 0.60
                else:
                    salience = 0.45

                # Civilian violence gets extra salience
                if deaths_civilians > 0:
                    salience = min(1.0, salience + 0.10)

                latitude = item.get("latitude", 0)
                longitude = item.get("longitude", 0)

                stored = self.db.store_event(
                    source_name="UCDP",
                    source_tier=1,
                    source_region="GLOBAL",
                    headline=headline,
                    summary=f"Period: {date_start} to {date_end}. Deaths: A={deaths_a}, B={deaths_b}, Civ={deaths_civilians}, Unknown={deaths_unknown}.",
                    content_type="DATA",
                    domain="GEOPOLITICAL",
                    region_focus=[region] if region else ["GLOBAL"],
                    salience_score=salience,
                    event_hash=event_hash,
                    source_url=source_article,
                    published_at=date_start,
                    raw_payload={
                        "ucdp_id": event_id,
                        "country": country,
                        "type_of_violence": event_type,
                        "total_deaths": total_deaths,
                        "deaths_civilians": deaths_civilians,
                        "side_a": side_a,
                        "side_b": side_b,
                        "coordinates": [longitude, latitude],
                    },
                )
                if stored:
                    count += 1

            if count:
                logger.info("[Collector] UCDP: stored %d conflict events", count)

        except Exception as e:
            logger.warning("[Collector] UCDP error: %s", e)

    # ── Exchange Rates (FREE tier — 1,500 req/month) ──

    FOREX_PAIRS = ["EUR", "GBP", "CNY", "JPY", "RUB", "INR", "CHF", "BRL", "TRY", "ZAR"]

    async def _collect_exchange_rates(self):
        """Collect USD-based exchange rates from ExchangeRate-API (free, no key).

        Tracks 10 major/emerging currencies. Stores each as an economic indicator.
        Free open endpoint: https://open.er-api.com/v6/latest/USD
        """
        try:
            resp = await self._client.get(
                "https://open.er-api.com/v6/latest/USD",
            )
            if resp.status_code != 200:
                logger.warning("[Collector] ExchangeRate-API HTTP %d", resp.status_code)
                return

            data = resp.json()
            if data.get("result") != "success":
                logger.warning("[Collector] ExchangeRate-API error: %s", data.get("error-type", "unknown"))
                return

            rates = data.get("rates", {})
            update_time = data.get("time_last_update_utc", "")
            count = 0

            for currency in self.FOREX_PAIRS:
                rate = rates.get(currency)
                if rate is None:
                    continue

                self.db.store_economic(
                    source="ExchangeRate",
                    indicator=f"USD/{currency}",
                    value=float(rate),
                    period=update_time[:10] if update_time else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    unit=f"{currency}/USD",
                    raw_payload={"base": "USD", "target": currency, "rate": rate},
                )
                count += 1

            if count:
                logger.info("[Collector] ExchangeRate: stored %d FX pairs", count)

        except Exception as e:
            logger.warning("[Collector] ExchangeRate error: %s", e)

    # ── Commodities (Yahoo Finance futures + ExchangeRate metals) ──

    COMMODITY_SYMBOLS = {
        "XAU": ("Gold", "USD/oz"),
        "XAG": ("Silver", "USD/oz"),
    }

    # Yahoo Finance futures symbols → (indicator_name, unit)
    YAHOO_FUTURES = {
        "BZ=F": ("Brent Crude Oil", "USD/bbl"),
        "CL=F": ("WTI Crude Oil", "USD/bbl"),
        "NG=F": ("Natural Gas (Henry Hub)", "USD/MMBtu"),
        "GC=F": ("Gold Futures", "USD/oz"),
    }

    async def _collect_commodities(self):
        """Collect commodity prices from multiple free sources.

        Primary: Yahoo Finance futures API — real-time oil, gas, gold futures.
        Secondary: ExchangeRate-API for spot precious metals (XAU, XAG).
        Fallback: EIA API for oil/gas if Yahoo fails.
        """
        count = 0
        yahoo_got_oil = False
        yahoo_got_gas = False

        # ── Yahoo Finance Futures (primary — real-time) ──
        for symbol, (name, unit) in self.YAHOO_FUTURES.items():
            try:
                resp = await self._client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"interval": "1d", "range": "5d"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("chart", {}).get("result", [])
                    if result:
                        meta = result[0].get("meta", {})
                        price = meta.get("regularMarketPrice")
                        prev_close = meta.get("previousClose")
                        if price and price > 0:
                            period = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                            change_pct = None
                            if prev_close and prev_close > 0:
                                change_pct = round(((price - prev_close) / prev_close) * 100, 3)

                            self.db.store_economic(
                                source="Commodities",
                                indicator=name,
                                value=round(float(price), 2),
                                period=period,
                                unit=unit,
                                previous_value=float(prev_close) if prev_close else None,
                                change_pct=change_pct,
                                raw_payload={
                                    "yahoo_symbol": symbol,
                                    "price": price,
                                    "previous_close": prev_close,
                                    "currency": meta.get("currency", "USD"),
                                    "exchange": meta.get("exchangeName", ""),
                                    "market_state": meta.get("marketState", ""),
                                },
                            )
                            count += 1
                            chg_str = f" ({change_pct:+.2f}%)" if change_pct is not None else ""
                            logger.info("[Collector] %s: $%.2f %s%s (Yahoo, %s)",
                                        name, float(price), unit, chg_str, period)
                            if "Brent" in name or "WTI" in name:
                                yahoo_got_oil = True
                            if "Natural Gas" in name:
                                yahoo_got_gas = True

                            # ── Commodity price shock detection ──
                            if change_pct is not None:
                                abs_chg = abs(change_pct)
                                # Energy: >3% daily move; Gold: >2%
                                threshold = 2.0 if "Gold" in name else 3.0
                                if abs_chg >= threshold:
                                    direction = "up" if change_pct > 0 else "down"
                                    headline = (
                                        f"[COMMODITY SHOCK] {name} {direction} {abs_chg:.1f}% "
                                        f"to ${float(price):.2f} (prev: ${float(prev_close):.2f})"
                                    )
                                    self._pending_alerts.append({
                                        "headline": headline,
                                        "source": "Commodities/Yahoo",
                                        "domain": "ECONOMIC",
                                        "salience": 0.90,
                                        "region": ["GLOBAL"],
                                        "signal_type": "financial_anomaly",
                                    })
                                    logger.info("[Collector] Commodity signal: %s", headline)

            except Exception as e:
                logger.debug("[Collector] Yahoo %s error: %s", symbol, e)

        # ── Gold & Silver from ExchangeRate-API (spot prices) ──
        try:
            resp = await self._client.get("https://open.er-api.com/v6/latest/USD")
            if resp.status_code == 200:
                data = resp.json()
                rates = data.get("rates", {})
                period = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                for symbol, (name, unit) in self.COMMODITY_SYMBOLS.items():
                    rate = rates.get(symbol)
                    if rate and rate > 0:
                        price = round(1.0 / rate, 2)
                        self.db.store_economic(
                            source="Commodities",
                            indicator=name,
                            value=price,
                            period=period,
                            unit=unit,
                            raw_payload={"symbol": symbol, "price_usd": price, "inverse_rate": rate},
                        )
                        count += 1
                        logger.info("[Collector] Commodity %s: $%.2f %s", name, price, unit)
        except Exception as e:
            logger.warning("[Collector] Commodity metals error: %s", e)

        # ── EIA Fallback — only if Yahoo failed for oil/gas ──
        if not yahoo_got_oil:
            try:
                resp = await self._client.get(
                    "https://api.eia.gov/v2/petroleum/pri/spt/data/",
                    params={
                        "frequency": "daily",
                        "data[0]": "value",
                        "facets[series][]": "RBRTE",
                        "sort[0][column]": "period",
                        "sort[0][direction]": "desc",
                        "length": 2,
                        "api_key": "DEMO_KEY",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    records = data.get("response", {}).get("data", [])
                    for rec in records[:1]:
                        val = rec.get("value")
                        period = rec.get("period", "")
                        if val is not None:
                            # Staleness check
                            try:
                                data_date = datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                                age_days = (datetime.now(timezone.utc) - data_date).days
                                if age_days > 3:
                                    logger.warning(
                                        "[Collector] EIA Brent data is %d days stale (%s) — consider Yahoo Finance",
                                        age_days, period,
                                    )
                            except ValueError:
                                pass
                            self.db.store_economic(
                                source="Commodities",
                                indicator="Brent Crude Oil (EIA)",
                                value=float(val),
                                period=period,
                                unit="USD/bbl",
                                raw_payload=rec,
                            )
                            count += 1
                            logger.info("[Collector] Brent Crude (EIA fallback): $%.2f/bbl (%s)", float(val), period)
            except Exception as e:
                logger.warning("[Collector] EIA Brent fallback error: %s", e)

        if not yahoo_got_gas:
            try:
                resp = await self._client.get(
                    "https://api.eia.gov/v2/natural-gas/pri/fut/data/",
                    params={
                        "frequency": "daily",
                        "data[0]": "value",
                        "facets[series][]": "RNGWHHD",
                        "sort[0][column]": "period",
                        "sort[0][direction]": "desc",
                        "length": 2,
                        "api_key": "DEMO_KEY",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    records = data.get("response", {}).get("data", [])
                    for rec in records[:1]:
                        val = rec.get("value")
                        period = rec.get("period", "")
                        if val is not None:
                            self.db.store_economic(
                                source="Commodities",
                                indicator="Natural Gas (EIA)",
                                value=float(val),
                                period=period,
                                unit="USD/MMBtu",
                                raw_payload=rec,
                            )
                            count += 1
                            logger.info("[Collector] Natural Gas (EIA fallback): $%.2f/MMBtu (%s)", float(val), period)
            except Exception as e:
                logger.warning("[Collector] EIA NatGas fallback error: %s", e)

        if count:
            logger.info("[Collector] Commodities: stored %d prices total", count)

    # ── Yahoo Finance Market Data (FREE, no key — indices, VIX, sectors) ──

    YAHOO_MARKET_INDICES = {
        "^GSPC": ("S&P 500", "index"),
        "^DJI": ("Dow Jones Industrial", "index"),
        "^IXIC": ("NASDAQ Composite", "index"),
        "^VIX": ("VIX Fear Index", "index"),
        "^GDAXI": ("DAX (Germany)", "index"),
        "^FTSE": ("FTSE 100 (UK)", "index"),
        "^N225": ("Nikkei 225 (Japan)", "index"),
        "000001.SS": ("Shanghai Composite (China)", "index"),
        "^STOXX50E": ("Euro Stoxx 50", "index"),
        "^RUT": ("Russell 2000 Small Cap", "index"),
    }

    async def _collect_yahoo_markets(self):
        """Collect market indices and financial indicators from Yahoo Finance.

        Free, no key needed. Provides near-real-time market data.
        Runs on daily cadence — captures closing prices and intraday during market hours.
        """
        count = 0
        period = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for symbol, (name, unit) in self.YAHOO_MARKET_INDICES.items():
            try:
                resp = await self._client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"interval": "1d", "range": "5d"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code != 200:
                    logger.debug("[Collector] Yahoo %s HTTP %d", symbol, resp.status_code)
                    continue

                data = resp.json()
                result = data.get("chart", {}).get("result", [])
                if not result:
                    continue

                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("previousClose")

                if not price or price <= 0:
                    continue

                change_pct = None
                if prev_close and prev_close > 0:
                    change_pct = round(((price - prev_close) / prev_close) * 100, 3)

                self.db.store_economic(
                    source="YahooFinance",
                    indicator=name,
                    value=round(float(price), 2),
                    period=period,
                    unit=unit,
                    previous_value=float(prev_close) if prev_close else None,
                    change_pct=change_pct,
                    raw_payload={
                        "yahoo_symbol": symbol,
                        "price": price,
                        "previous_close": prev_close,
                        "currency": meta.get("currency", ""),
                        "exchange": meta.get("exchangeName", ""),
                        "market_state": meta.get("marketState", ""),
                    },
                )
                count += 1
                chg_str = f" ({change_pct:+.2f}%)" if change_pct is not None else ""
                logger.info("[Collector] Yahoo %s: %.2f%s", name, float(price), chg_str)

                # ── Generate economic_shift signals for significant daily market moves ──
                if change_pct is not None:
                    abs_chg = abs(change_pct)
                    # Thresholds: indices > 1.5%, VIX > 10% change
                    threshold = 10.0 if "VIX" in name else 1.5
                    if abs_chg >= threshold:
                        direction = "up" if change_pct > 0 else "down"
                        headline = (
                            f"[MARKET SHIFT] {name} {direction} {abs_chg:.1f}% "
                            f"to {float(price):.2f} (prev: {float(prev_close):.2f})"
                        )
                        # Map indices to regions
                        idx_region = "GLOBAL"
                        if any(x in name for x in ("S&P", "Dow", "NASDAQ", "Russell")):
                            idx_region = "US"
                        elif "DAX" in name or "Stoxx" in name:
                            idx_region = "EU"
                        elif "FTSE" in name:
                            idx_region = "UK"
                        elif "Nikkei" in name:
                            idx_region = "JP"
                        elif "Shanghai" in name:
                            idx_region = "CN"

                        self._pending_alerts.append({
                            "headline": headline,
                            "source": "YahooFinance",
                            "domain": "MARKET",
                            "salience": 0.90,
                            "region": [idx_region],
                            "signal_type": "economic_shift",
                        })
                        logger.info("[Collector] Yahoo economic_shift signal: %s", headline)

            except Exception as e:
                logger.debug("[Collector] Yahoo %s error: %s", symbol, e)

        if count:
            logger.info("[Collector] Yahoo Finance: stored %d market indicators", count)

    # ── Finnhub (market data, earnings, economic calendar — FREE tier 60 calls/min) ──

    FINNHUB_FOREX_PAIRS = [
        ("OANDA:EUR_USD", "EUR/USD", "rate"),
        ("OANDA:GBP_USD", "GBP/USD", "rate"),
        ("OANDA:USD_JPY", "USD/JPY", "rate"),
        ("OANDA:USD_CHF", "USD/CHF", "rate"),
        ("OANDA:AUD_USD", "AUD/USD", "rate"),
        ("OANDA:USD_CNH", "USD/CNH", "rate"),
        ("OANDA:USD_TRY", "USD/TRY", "rate"),
        ("OANDA:USD_ZAR", "USD/ZAR", "rate"),
    ]

    async def _collect_finnhub_market_news(self):
        """Collect market-moving news from Finnhub (general + forex + crypto).

        FREE tier: 60 API calls/min. Provides categorized financial news
        with sentiment data not available from RSS feeds.
        """
        if not self.finnhub_api_key:
            return

        count = 0
        categories = ["general", "forex", "merger"]

        for cat in categories:
            try:
                resp = await self._client.get(
                    "https://finnhub.io/api/v1/news",
                    params={"category": cat, "token": self.finnhub_api_key},
                )
                if resp.status_code != 200:
                    logger.debug("[Collector] Finnhub news %s HTTP %d", cat, resp.status_code)
                    continue

                articles = resp.json()
                for art in articles[:10]:
                    headline = art.get("headline", "")
                    if not headline:
                        continue

                    uid = hashlib.sha256(f"finnhub_{art.get('id', '')}_{headline}".encode()).hexdigest()[:16]
                    ts = art.get("datetime", 0)
                    pub_date = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""

                    self.db.store_event(
                        source="Finnhub",
                        event_type=f"financial_news_{cat}",
                        title=headline,
                        summary=art.get("summary", "")[:500],
                        url=art.get("url", ""),
                        pub_date=pub_date,
                        uid=uid,
                        raw_payload={
                            "category": cat,
                            "source": art.get("source", ""),
                            "related": art.get("related", ""),
                            "image": art.get("image", ""),
                        },
                    )
                    count += 1

                    # ── Feed significant financial news into proactive alerts ──
                    # Finnhub market news enriches pattern accumulator with
                    # financial context that can merge with geopolitical patterns
                    hl_lower = headline.lower()
                    is_significant = any(
                        kw in hl_lower
                        for kw in (
                            "fed", "ecb", "interest rate", "inflation", "gdp",
                            "recession", "rate cut", "rate hike", "tariff",
                            "sanctions", "trade war", "oil", "crude",
                            "crash", "selloff", "rally", "downgrade",
                            "earnings miss", "layoffs", "merger", "acquisition",
                            "default", "debt", "yield", "treasury",
                            "stimulus", "quantitative", "currency",
                        )
                    )
                    if is_significant:
                        self._pending_alerts.append({
                            "headline": headline,
                            "source": f"Finnhub/{cat}",
                            "domain": "ECONOMIC",
                            "salience": 0.87,
                            "region": [],
                            "signal_type": "perception_alert",
                        })

                await asyncio.sleep(1)  # Rate limit: stay under 60/min
            except Exception as e:
                logger.debug("[Collector] Finnhub news %s error: %s", cat, e)

        if count:
            logger.info("[Collector] Finnhub news: stored %d articles", count)

    async def _collect_finnhub_earnings_calendar(self):
        """Collect upcoming and recent earnings from Finnhub.

        Tracks earnings surprises — the gap between expected and actual EPS
        is a critical signal for market regime detection.
        """
        if not self.finnhub_api_key:
            return

        count = 0
        now = datetime.now(timezone.utc)
        from_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")

        try:
            resp = await self._client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "from": from_date,
                    "to": to_date,
                    "token": self.finnhub_api_key,
                },
            )
            if resp.status_code != 200:
                logger.debug("[Collector] Finnhub earnings HTTP %d", resp.status_code)
                return

            data = resp.json()
            earnings = data.get("earningsCalendar", [])

            for e in earnings[:30]:
                symbol = e.get("symbol", "")
                if not symbol:
                    continue

                eps_actual = e.get("epsActual")
                eps_estimate = e.get("epsEstimate")
                surprise_pct = None
                if eps_actual is not None and eps_estimate and eps_estimate != 0:
                    surprise_pct = round(((eps_actual - eps_estimate) / abs(eps_estimate)) * 100, 2)

                uid = hashlib.sha256(f"finnhub_earn_{symbol}_{e.get('date', '')}".encode()).hexdigest()[:16]

                self.db.store_event(
                    source="Finnhub",
                    event_type="earnings_report",
                    title=f"{symbol} Earnings — EPS: {eps_actual} (est: {eps_estimate})",
                    summary=(
                        f"Revenue: {e.get('revenueActual', 'N/A')} "
                        f"(est: {e.get('revenueEstimate', 'N/A')}). "
                        f"Surprise: {surprise_pct}%." if surprise_pct is not None else
                        f"Revenue: {e.get('revenueActual', 'N/A')} (est: {e.get('revenueEstimate', 'N/A')})."
                    ),
                    url="",
                    pub_date=e.get("date", ""),
                    uid=uid,
                    raw_payload={
                        "symbol": symbol,
                        "eps_actual": eps_actual,
                        "eps_estimate": eps_estimate,
                        "surprise_pct": surprise_pct,
                        "revenue_actual": e.get("revenueActual"),
                        "revenue_estimate": e.get("revenueEstimate"),
                        "hour": e.get("hour", ""),
                        "quarter": e.get("quarter"),
                        "year": e.get("year"),
                    },
                )
                count += 1

                # ── Feed significant earnings surprises into proactive alerts ──
                if surprise_pct is not None and abs(surprise_pct) >= 20.0:
                    direction = "beat" if surprise_pct > 0 else "missed"
                    headline = (
                        f"[EARNINGS] {symbol} {direction} estimates by "
                        f"{abs(surprise_pct):.1f}% — EPS: {eps_actual} vs est: {eps_estimate}"
                    )
                    self._pending_alerts.append({
                        "headline": headline,
                        "source": "Finnhub/Earnings",
                        "domain": "MARKET",
                        "salience": 0.88,
                        "region": ["US"],
                        "signal_type": "economic_shift",
                    })

            await asyncio.sleep(1)
        except Exception as e:
            logger.debug("[Collector] Finnhub earnings error: %s", e)

        if count:
            logger.info("[Collector] Finnhub earnings: stored %d reports", count)

    async def _collect_finnhub_economic_calendar(self):
        """Collect economic events — Fed decisions, CPI releases, GDP, PMI, etc.

        Covers: FOMC meetings, central bank decisions, major economic releases.
        Critical for detecting regime shifts before markets price them in.
        """
        if not self.finnhub_api_key:
            return

        count = 0
        now = datetime.now(timezone.utc)
        from_date = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=14)).strftime("%Y-%m-%d")

        try:
            resp = await self._client.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={
                    "from": from_date,
                    "to": to_date,
                    "token": self.finnhub_api_key,
                },
            )
            if resp.status_code != 200:
                logger.debug("[Collector] Finnhub econ calendar HTTP %d", resp.status_code)
                return

            data = resp.json()
            events = data.get("economicCalendar", [])

            for ev in events[:40]:
                event_name = ev.get("event", "")
                if not event_name:
                    continue

                country = ev.get("country", "")
                impact = ev.get("impact", "")
                actual = ev.get("actual")
                estimate = ev.get("estimate")
                prev = ev.get("prev")

                surprise = None
                if actual is not None and estimate is not None and estimate != 0:
                    surprise = round(((actual - estimate) / abs(estimate)) * 100, 2)

                uid = hashlib.sha256(
                    f"finnhub_econ_{event_name}_{ev.get('time', '')}_{country}".encode()
                ).hexdigest()[:16]

                self.db.store_event(
                    source="Finnhub",
                    event_type=f"economic_calendar_{impact}",
                    title=f"[{country}] {event_name}",
                    summary=(
                        f"Actual: {actual}, Estimate: {estimate}, Previous: {prev}. "
                        f"Impact: {impact}. "
                        + (f"Surprise: {surprise}%." if surprise is not None else "")
                    ),
                    url="",
                    pub_date=ev.get("time", ""),
                    uid=uid,
                    raw_payload={
                        "country": country,
                        "event": event_name,
                        "impact": impact,
                        "actual": actual,
                        "estimate": estimate,
                        "prev": prev,
                        "surprise": surprise,
                        "unit": ev.get("unit", ""),
                    },
                )
                count += 1

                # ── Generate economic_shift signals for high-impact surprises ──
                # Rate decisions, CPI, GDP releases with significant surprise
                is_high_impact = impact in ("high", "medium")
                has_data = actual is not None
                has_surprise = surprise is not None and abs(surprise) >= 5.0
                is_rate_decision = any(
                    kw in event_name.lower()
                    for kw in ("interest rate", "rate decision", "fomc", "ecb rate",
                               "boe rate", "boj rate", "rba rate", "central bank")
                )

                if has_data and (has_surprise or is_rate_decision):
                    region_map = {
                        "US": "US", "EU": "EU", "GB": "UK", "JP": "JP",
                        "CN": "CN", "DE": "EU", "FR": "EU", "IN": "IN",
                    }
                    region = region_map.get(country, "GLOBAL")
                    surprise_str = f" (surprise: {surprise:+.1f}%)" if surprise is not None else ""
                    headline = (
                        f"[ECONOMIC EVENT] [{country}] {event_name}: "
                        f"actual={actual}, estimate={estimate}, prev={prev}"
                        f"{surprise_str} — impact: {impact}"
                    )
                    self._pending_alerts.append({
                        "headline": headline,
                        "source": "Finnhub/EconCalendar",
                        "domain": "ECONOMIC",
                        "salience": 0.92 if is_rate_decision else 0.88,
                        "region": [region],
                        "signal_type": "economic_shift",
                    })
                    logger.info("[Collector] Finnhub economic_shift signal: %s", headline)

            await asyncio.sleep(1)
        except Exception as e:
            logger.debug("[Collector] Finnhub econ calendar error: %s", e)

        if count:
            logger.info("[Collector] Finnhub econ calendar: stored %d events", count)

    async def _collect_finnhub_forex(self):
        """Collect real-time forex quotes from Finnhub.

        Tracks currency pairs critical for geopolitical-financial coupling:
        EM currencies, safe havens, and major pairs.
        """
        if not self.finnhub_api_key:
            return

        count = 0
        period = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for symbol, name, unit in self.FINNHUB_FOREX_PAIRS:
            try:
                resp = await self._client.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": symbol, "token": self.finnhub_api_key},
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                price = data.get("c")  # Current price
                prev_close = data.get("pc")  # Previous close

                if not price or price <= 0:
                    continue

                change_pct = None
                if prev_close and prev_close > 0:
                    change_pct = round(((price - prev_close) / prev_close) * 100, 3)

                self.db.store_economic(
                    source="Finnhub",
                    indicator=f"FX {name}",
                    value=round(float(price), 5),
                    period=period,
                    unit=unit,
                    previous_value=float(prev_close) if prev_close else None,
                    change_pct=change_pct,
                    raw_payload={
                        "symbol": symbol,
                        "open": data.get("o"),
                        "high": data.get("h"),
                        "low": data.get("l"),
                        "timestamp": data.get("t"),
                    },
                )
                count += 1
                chg_str = f" ({change_pct:+.3f}%)" if change_pct is not None else ""
                logger.info("[Collector] Finnhub FX %s: %.5f%s", name, float(price), chg_str)

                # ── Generate financial_anomaly signals for significant FX moves ──
                if change_pct is not None:
                    abs_chg = abs(change_pct)
                    # FX thresholds: majors >1%, EM/volatile pairs >2%
                    is_em = any(em in symbol for em in ("TRY", "ZAR", "CNH"))
                    threshold = 2.0 if is_em else 1.0

                    if abs_chg >= threshold:
                        direction = "up" if change_pct > 0 else "down"
                        headline = (
                            f"[FX SHIFT] Finnhub {name} {direction} {abs_chg:.2f}% "
                            f"to {float(price):.5f} (prev: {float(prev_close):.5f})"
                        )
                        # Map FX pairs to regions
                        fx_region = "GLOBAL"
                        region_hints = {
                            "EUR": "EU", "GBP": "UK", "JPY": "JP",
                            "CHF": "CH", "AUD": "AU", "CNH": "CN",
                            "TRY": "TR", "ZAR": "ZA",
                        }
                        for hint, reg in region_hints.items():
                            if hint in name:
                                fx_region = reg
                                break

                        self._pending_alerts.append({
                            "headline": headline,
                            "source": "Finnhub/FX",
                            "domain": "ECONOMIC",
                            "salience": 0.87,
                            "region": [fx_region],
                            "signal_type": "financial_anomaly",
                        })
                        logger.info("[Collector] Finnhub FX signal: %s", headline)

                await asyncio.sleep(1)  # Rate limit
            except Exception as e:
                logger.debug("[Collector] Finnhub FX %s error: %s", name, e)

        if count:
            logger.info("[Collector] Finnhub FX: stored %d pairs", count)

    # ── Yahoo Finance: Currency Pairs + Sector ETFs + Bond ETFs ──

    YAHOO_CURRENCY_PAIRS = {
        "EURUSD=X": ("EUR/USD", "rate"),
        "GBPUSD=X": ("GBP/USD", "rate"),
        "USDJPY=X": ("USD/JPY", "rate"),
        "USDCNH=X": ("USD/CNH (offshore yuan)", "rate"),
        "USDRUB=X": ("USD/RUB", "rate"),
        "USDTRY=X": ("USD/TRY", "rate"),
        "USDZAR=X": ("USD/ZAR", "rate"),
        "DX-Y.NYB": ("US Dollar Index (DXY)", "index"),
    }

    YAHOO_SECTOR_ETFS = {
        "XLF": ("Financial Select Sector SPDR", "USD"),
        "XLE": ("Energy Select Sector SPDR", "USD"),
        "XLK": ("Technology Select Sector SPDR", "USD"),
        "XLV": ("Health Care Select Sector SPDR", "USD"),
        "XLI": ("Industrial Select Sector SPDR", "USD"),
        "GDX": ("Gold Miners ETF", "USD"),
    }

    YAHOO_BOND_ETFS = {
        "TLT": ("iShares 20+ Year Treasury Bond", "USD"),
        "HYG": ("iShares High Yield Corporate Bond", "USD"),
        "LQD": ("iShares Investment Grade Corporate Bond", "USD"),
        "EMB": ("iShares JP Morgan EM Bond", "USD"),
        "SHY": ("iShares 1-3 Year Treasury Bond", "USD"),
    }

    async def _collect_yahoo_currency_pairs(self):
        """Collect currency pair data from Yahoo Finance.

        Tracks major FX pairs + emerging market currencies critical for
        currency stress detection and geopolitical-financial coupling.
        """
        count = 0
        period = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        all_symbols = {
            **self.YAHOO_CURRENCY_PAIRS,
            **self.YAHOO_SECTOR_ETFS,
            **self.YAHOO_BOND_ETFS,
        }

        for symbol, (name, unit) in all_symbols.items():
            try:
                resp = await self._client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"interval": "1d", "range": "5d"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                result = data.get("chart", {}).get("result", [])
                if not result:
                    continue

                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("previousClose")

                if not price or price <= 0:
                    continue

                change_pct = None
                if prev_close and prev_close > 0:
                    change_pct = round(((price - prev_close) / prev_close) * 100, 3)

                source_tag = "YahooFinance"
                if symbol in self.YAHOO_CURRENCY_PAIRS:
                    source_tag = "YahooFinance_FX"
                elif symbol in self.YAHOO_SECTOR_ETFS:
                    source_tag = "YahooFinance_Sector"
                elif symbol in self.YAHOO_BOND_ETFS:
                    source_tag = "YahooFinance_Bonds"

                self.db.store_economic(
                    source=source_tag,
                    indicator=name,
                    value=round(float(price), 4),
                    period=period,
                    unit=unit,
                    previous_value=float(prev_close) if prev_close else None,
                    change_pct=change_pct,
                    raw_payload={
                        "yahoo_symbol": symbol,
                        "price": price,
                        "previous_close": prev_close,
                        "currency": meta.get("currency", ""),
                        "exchange": meta.get("exchangeName", ""),
                        "market_state": meta.get("marketState", ""),
                    },
                )
                count += 1
                chg_str = f" ({change_pct:+.3f}%)" if change_pct is not None else ""
                logger.info("[Collector] Yahoo %s: %.4f%s", name, float(price), chg_str)

                # ── Generate economic_shift signals for significant FX/Sector/Bond moves ──
                if change_pct is not None:
                    abs_chg = abs(change_pct)
                    # Dynamic thresholds by asset class
                    if symbol in self.YAHOO_CURRENCY_PAIRS:
                        # FX: >1% daily move is significant; EM currencies >2%
                        is_em = any(em in symbol for em in ("RUB", "TRY", "ZAR", "CNH"))
                        threshold = 2.0 if is_em else 1.0
                        signal_type = "financial_anomaly"
                        # Map FX pairs to regions
                        fx_region_map = {
                            "EUR": "EU", "GBP": "UK", "JPY": "JP",
                            "CNH": "CN", "RUB": "RU", "TRY": "TR",
                            "ZAR": "ZA", "DX-Y": "US",
                        }
                        region = "GLOBAL"
                        for k, r in fx_region_map.items():
                            if k in symbol:
                                region = r
                                break
                    elif symbol in self.YAHOO_SECTOR_ETFS:
                        # Sector ETFs: >2.5% daily move
                        threshold = 2.5
                        signal_type = "economic_shift"
                        region = "US"
                    elif symbol in self.YAHOO_BOND_ETFS:
                        # Bond ETFs: >1.5% daily move (bonds are normally stable)
                        threshold = 1.5
                        signal_type = "financial_anomaly"
                        # EM bonds map to GLOBAL, US treasuries to US
                        region = "GLOBAL" if "EM" in name else "US"
                    else:
                        threshold = 2.0
                        signal_type = "economic_shift"
                        region = "GLOBAL"

                    if abs_chg >= threshold:
                        direction = "up" if change_pct > 0 else "down"
                        headline = (
                            f"[MARKET SHIFT] {name} {direction} {abs_chg:.2f}% "
                            f"to {float(price):.4f} (prev: {float(prev_close):.4f})"
                        )
                        self._pending_alerts.append({
                            "headline": headline,
                            "source": source_tag,
                            "domain": "ECONOMIC",
                            "salience": 0.88,
                            "region": [region],
                            "signal_type": signal_type,
                        })
                        logger.info("[Collector] Yahoo FX/Sector/Bond signal: %s", headline)

            except Exception as e:
                logger.debug("[Collector] Yahoo %s error: %s", symbol, e)

        if count:
            logger.info("[Collector] Yahoo FX/Sectors/Bonds: stored %d indicators", count)

    # ── GDACS (Global Disaster Alert — UN-backed, FREE, no key, Tier 1) ──

    async def _collect_gdacs(self):
        """Collect disaster/crisis alerts from GDACS (Global Disaster Alert System).

        UN-backed, free, no key needed. Replaces UCDP for structured crisis events.
        Covers: Earthquakes, Tropical Cyclones, Floods, Volcanoes, Droughts, Wildfires.
        Provides alert levels (Green/Orange/Red) with impact estimates.
        """
        try:
            now = datetime.now(timezone.utc)
            resp = await self._client.get(
                "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
                params={
                    "eventlist": "EQ;TC;FL;VO;DR;WF",
                    "fromDate": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "toDate": now.strftime("%Y-%m-%d"),
                    "alertlevel": "Green;Orange;Red",
                },
            )
            if resp.status_code != 200:
                logger.warning("[Collector] GDACS HTTP %d", resp.status_code)
                return

            data = resp.json()
            features = data.get("features", [])
            count = 0

            type_labels = {
                "EQ": "Earthquake",
                "TC": "Tropical Cyclone",
                "FL": "Flood",
                "VO": "Volcanic Activity",
                "DR": "Drought",
                "WF": "Wildfire",
            }

            for f in features:
                props = f.get("properties", {})
                event_type = props.get("eventtype", "")
                name = props.get("name", "Unknown")
                alert_level = props.get("alertlevel", "Green")
                alert_score = props.get("alertscore", 0)
                country = props.get("country", "")
                from_date = props.get("fromdate", "")
                event_id = props.get("eventid", "")
                episode_id = props.get("episodeid", "")

                type_label = type_labels.get(event_type, event_type)
                headline = f"[GDACS] {type_label}: {name}"

                event_hash = hashlib.md5(
                    f"gdacs-{event_id}-{episode_id}".encode()
                ).hexdigest()

                # Salience by alert level
                salience_map = {"Red": 0.95, "Orange": 0.80, "Green": 0.55}
                salience = salience_map.get(alert_level, 0.50)

                # Get coordinates if available
                geometry = f.get("geometry", {})
                coords = geometry.get("coordinates", [0, 0])

                url_data = props.get("url", {})
                report_url = ""
                if isinstance(url_data, dict):
                    report_url = url_data.get("report", "")

                severity_data = props.get("severity", {})
                severity_text = ""
                if isinstance(severity_data, dict):
                    severity_text = severity_data.get("severity_text", "")

                # Extract country regions
                regions = []
                if country:
                    for c_name in country.split(","):
                        c_name = c_name.strip()
                        regions.append(self._country_to_region(c_name))
                if not regions:
                    regions = ["GLOBAL"]

                stored = self.db.store_event(
                    source_name="GDACS",
                    source_tier=1,
                    source_region="GLOBAL",
                    headline=headline,
                    summary=f"Alert: {alert_level} (score={alert_score}). "
                            f"Countries: {country}. Severity: {severity_text}. "
                            f"Period: {from_date[:10]}.",
                    content_type="DATA",
                    domain="GEOPOLITICAL",
                    region_focus=regions,
                    salience_score=salience,
                    event_hash=event_hash,
                    source_url=report_url,
                    published_at=from_date[:10] if from_date else "",
                    raw_payload={
                        "gdacs_event_id": event_id,
                        "episode_id": episode_id,
                        "event_type": event_type,
                        "alert_level": alert_level,
                        "alert_score": alert_score,
                        "country": country,
                        "coordinates": coords,
                        "severity": severity_text,
                    },
                )
                if stored:
                    count += 1

            if count:
                logger.info("[Collector] GDACS: stored %d crisis/disaster events (%d Orange/Red)",
                            count, sum(1 for ft in features
                                       if ft.get("properties", {}).get("alertlevel") in ("Orange", "Red")))

        except Exception as e:
            logger.warning("[Collector] GDACS error: %s", e)
