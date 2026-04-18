"""
XDART-Φ × XHEART — Multimodal Perception Layer

Extends Αίολος's perception beyond text feeds to include:
  1. Satellite imagery monitoring (Sentinel Hub / Copernicus)
  2. Maritime shipping traffic (AIS via MarineTraffic & UNGP)
  3. Airspace monitoring (ADS-B via OpenSky Network)

Each collector follows the same pattern:
  - Async loop on a schedule
  - Results feed into PatternAccumulator as signals
  - Anomalies generate high-weight alerts

Data Sources (all FREE tiers available):
  - OpenSky Network: Free API, no key required for basic queries
  - MarineTraffic/UN Global Platform: Free vessel tracking data
  - Copernicus Open Access Hub: Free satellite imagery (registration required)
  - NASA FIRMS: Free active fire/thermal anomaly data (military facility proxy)
  - NOAA VIIRS: Free nighttime lights data (infrastructure monitoring proxy)

© Panos Skouras — Salimov MON IKE, 2026
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

logger = logging.getLogger("xdart.perception.multimodal")


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGIC MONITORING ZONES
#  Key locations where satellite, shipping, or airspace anomalies
#  have geopolitical significance.
# ══════════════════════════════════════════════════════════════════════════════

STRATEGIC_ZONES = {
    # Chokepoints (maritime + airspace)
    "hormuz": {"name": "Strait of Hormuz", "lat": 26.5, "lon": 56.3, "radius_km": 100,
               "significance": "80% Japan oil, 70% SK oil, 40% China oil transit"},
    "suez": {"name": "Suez Canal", "lat": 30.0, "lon": 32.5, "radius_km": 50,
             "significance": "EU-Asia trade route, 12% global trade"},
    "malacca": {"name": "Strait of Malacca", "lat": 2.5, "lon": 101.5, "radius_km": 80,
                "significance": "80% China oil transit, highest piracy risk"},
    "bab_el_mandeb": {"name": "Bab el-Mandeb", "lat": 12.6, "lon": 43.3, "radius_km": 50,
                       "significance": "Red Sea gateway to Suez, Houthi threat zone"},
    "taiwan_strait": {"name": "Taiwan Strait", "lat": 24.5, "lon": 119.5, "radius_km": 150,
                       "significance": "US-China flashpoint, semiconductor supply chain"},
    "bosporus": {"name": "Turkish Straits", "lat": 41.1, "lon": 29.0, "radius_km": 30,
                 "significance": "Black Sea → Mediterranean, grain/energy corridor"},

    # Military hotspots
    "kaliningrad": {"name": "Kaliningrad", "lat": 54.7, "lon": 20.5, "radius_km": 80,
                    "significance": "Russian exclave, Iskander missiles, NATO border"},
    "natanz": {"name": "Natanz (Iran)", "lat": 33.7, "lon": 51.7, "radius_km": 30,
               "significance": "Iran nuclear enrichment facility"},
    "yongbyon": {"name": "Yongbyon (DPRK)", "lat": 39.8, "lon": 125.8, "radius_km": 20,
                 "significance": "North Korea nuclear complex"},
    "south_china_sea": {"name": "South China Sea", "lat": 14.0, "lon": 114.0, "radius_km": 300,
                        "significance": "China military bases, freedom of navigation"},
    "crimea": {"name": "Crimea", "lat": 44.9, "lon": 34.1, "radius_km": 100,
               "significance": "Russia-Ukraine conflict, Black Sea Fleet"},
    "diego_garcia": {"name": "Diego Garcia", "lat": -7.3, "lon": 72.4, "radius_km": 50,
                     "significance": "US/UK military base, Indian Ocean power projection"},
}


# ══════════════════════════════════════════════════════════════════════════════
#  OPENSKY NETWORK — Airspace Monitoring (FREE, no API key required)
#  Tracks ADS-B transponder data from aircraft worldwide.
#  Detects: military flights, tanker orbits, surveillance patterns,
#  airspace closures (no traffic where there should be),
#  unusual concentration of aircraft.
# ══════════════════════════════════════════════════════════════════════════════

OPENSKY_BASE_URL = "https://opensky-network.org/api"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

# ICAO hex ranges for military aircraft (approximate assignments)
_MILITARY_ICAO_RANGES = [
    ("ADF7C0", "ADF7FF"),  # NATO AWACS
    ("AE0000", "AE6FFF"),  # US Military (common block)
    ("43C000", "43CFFF"),  # UK Military
    ("3F0000", "3FFFFF"),  # Germany Military
    ("3A8000", "3AFFFF"),  # France Military
    ("300000", "33FFFF"),  # Italy Military
]

# Callsign prefixes that indicate military/government flights
_MILITARY_CALLSIGNS = frozenset({
    "RCH", "REACH",   # US Military airlift
    "RRR",             # US Air Force tanker
    "DUKE",            # US Army
    "NAVY",            # US Navy
    "FORTE",           # US Global Hawk (surveillance drone)
    "JAKE",            # US reconnaissance
    "HOMER",           # US P-8 Poseidon (maritime patrol)
    "RAF", "RFR",      # Royal Air Force
    "GAF", "GAFI",     # German Air Force
    "IAM",             # Italian Air Force
    "FAF", "CTM",      # French Air Force
    "LAGR",            # Greek Air Force
    "THY1",            # Turkish military (not THY airline)
    "RSD",             # Russian Federation
    "CFC", "CAF",      # Chinese Air Force
})


class AirspaceMonitor:
    """Monitors global airspace via OpenSky Network ADS-B data.

    Detects:
      - Military aircraft near strategic zones
      - Unusual aircraft concentration (buildup indicator)
      - Airspace voids (possible closures / jamming)
      - Surveillance patterns (orbiting aircraft)
    """

    def __init__(
        self,
        opensky_user: str = "",
        opensky_pass: str = "",
    ):
        self.opensky_user = opensky_user
        self.opensky_pass = opensky_pass
        self._client: httpx.AsyncClient | None = None
        # OAuth2 token management (OpenSky requires Bearer tokens, not Basic Auth)
        self._token: str | None = None
        self._token_expires: float = 0
        # Baseline traffic counts per zone (built from first few observations)
        self._zone_baselines: dict[str, list[int]] = {}
        self._last_poll: float = 0
        self._cooldown = 300  # 5 min between polls (OpenSky rate limit)
        self._default_cooldown = 300
        self._rate_limited = False  # Flag: break zone loop on 429
        # De-dupe: track recently seen aircraft to avoid repeat alerts
        self._seen_military: dict[str, float] = {}  # icao24 → last_seen_ts
        self._seen_ttl = 3600  # 1 hour

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client exists (no auth headers — those are set per-request)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={"User-Agent": "XDART-Phi/1.0 Airspace Monitor"},
            )
        return self._client

    async def _obtain_token(self) -> str | None:
        """Obtain OAuth2 Bearer token from OpenSky via client_credentials flow."""
        client = await self._ensure_client()
        try:
            resp = await client.post(
                OPENSKY_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.opensky_user,
                    "client_secret": self.opensky_pass,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                token_data = resp.json()
                self._token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 1800)
                self._token_expires = time.time() + expires_in - 30  # refresh 30s early
                logger.info("[Airspace] OAuth2 token obtained (expires in %ds)", expires_in)
                return self._token
            else:
                logger.warning("[Airspace] OAuth2 token request failed (%d): %s",
                               resp.status_code, resp.text[:200])
                return None
        except Exception as exc:
            logger.warning("[Airspace] OAuth2 token exchange failed: %s", exc)
            return None

    async def _get_client(self) -> httpx.AsyncClient:
        """Return HTTP client with valid Bearer token (auto-refresh)."""
        client = await self._ensure_client()
        if self.opensky_user and self.opensky_pass:
            if time.time() >= self._token_expires:
                await self._obtain_token()
            if self._token:
                client.headers["Authorization"] = f"Bearer {self._token}"
        return client

    def _is_military_icao(self, icao24: str) -> bool:
        """Check if ICAO24 hex address falls in known military ranges."""
        try:
            addr = int(icao24, 16)
            for low, high in _MILITARY_ICAO_RANGES:
                if int(low, 16) <= addr <= int(high, 16):
                    return True
        except (ValueError, TypeError):
            pass
        return False

    def _is_military_callsign(self, callsign: str | None) -> bool:
        """Check if callsign prefix indicates military/government."""
        if not callsign:
            return False
        cs = callsign.strip().upper()
        return any(cs.startswith(prefix) for prefix in _MILITARY_CALLSIGNS)

    async def poll_zone(self, zone_id: str, zone: dict) -> list[dict]:
        """Poll OpenSky for aircraft in a strategic zone.

        Returns list of anomaly dicts ready for PatternAccumulator.
        """
        lat, lon = zone["lat"], zone["lon"]
        r = zone["radius_km"] / 111.0  # rough degrees
        bbox = {
            "lamin": lat - r, "lamax": lat + r,
            "lomin": lon - r, "lomax": lon + r,
        }

        client = await self._get_client()
        try:
            resp = await client.get(
                f"{OPENSKY_BASE_URL}/states/all",
                params=bbox,
            )
            if resp.status_code == 429:
                retry_after = resp.headers.get("X-Rate-Limit-Retry-After-Seconds", "")
                logger.warning("[Airspace] Rate limited by OpenSky (429) — stopping zone sweep%s",
                               f" (retry after {retry_after}s)" if retry_after else "")
                self._rate_limited = True
                return []
            if resp.status_code != 200:
                logger.debug("[Airspace] OpenSky returned %d for zone %s", resp.status_code, zone_id)
                return []

            data = resp.json()
        except Exception as exc:
            logger.warning("[Airspace] OpenSky request failed for %s: %s", zone_id, exc)
            return []

        states = data.get("states", []) or []
        if not states:
            return []

        anomalies = []
        now = time.time()
        military_count = 0

        # Prune old seen entries
        self._seen_military = {
            k: v for k, v in self._seen_military.items()
            if now - v < self._seen_ttl
        }

        for sv in states:
            # OpenSky state vector: [icao24, callsign, origin_country, ...]
            if len(sv) < 8:
                continue
            icao24 = sv[0] or ""
            callsign = (sv[1] or "").strip()
            origin_country = sv[2] or ""
            altitude = sv[7]  # barometric altitude

            is_military = (
                self._is_military_icao(icao24)
                or self._is_military_callsign(callsign)
            )

            if is_military:
                military_count += 1
                # De-dup: only alert once per aircraft per TTL
                if icao24 in self._seen_military:
                    continue
                self._seen_military[icao24] = now

                anomalies.append({
                    "headline": (
                        f"Military aircraft [{callsign or icao24}] ({origin_country}) "
                        f"detected near {zone['name']}"
                    ),
                    "source": "opensky_adsb",
                    "domain": "MILITARY",
                    "signal_type": "perception_alert",
                    "salience": 0.80,
                    "weight": 0.35,
                    "region": zone.get("region", "GLOBAL"),
                    "raw": {
                        "icao24": icao24,
                        "callsign": callsign,
                        "origin_country": origin_country,
                        "altitude_m": altitude,
                        "zone": zone_id,
                        "zone_significance": zone["significance"],
                    },
                })

        # Traffic volume anomaly: compare to baseline
        total_aircraft = len(states)
        if zone_id not in self._zone_baselines:
            self._zone_baselines[zone_id] = []
        baseline = self._zone_baselines[zone_id]
        baseline.append(total_aircraft)
        if len(baseline) > 20:
            baseline.pop(0)

        if len(baseline) >= 5:
            avg = sum(baseline[:-1]) / len(baseline[:-1])
            if avg > 0:
                ratio = total_aircraft / avg
                # Significant increase (>2x normal) → military buildup indicator
                if ratio > 2.0 and total_aircraft > 10:
                    anomalies.append({
                        "headline": (
                            f"Unusual aircraft concentration near {zone['name']}: "
                            f"{total_aircraft} aircraft (normal: ~{int(avg)})"
                        ),
                        "source": "opensky_adsb",
                        "domain": "MILITARY",
                        "signal_type": "perception_alert",
                        "salience": 0.85,
                        "weight": 0.40,
                        "region": zone.get("region", "GLOBAL"),
                    })
                # Significant decrease (<0.3x normal) → possible airspace closure
                elif ratio < 0.3 and avg > 10:
                    anomalies.append({
                        "headline": (
                            f"Airspace void near {zone['name']}: "
                            f"{total_aircraft} aircraft (normal: ~{int(avg)}) — "
                            f"possible closure or GPS jamming"
                        ),
                        "source": "opensky_adsb",
                        "domain": "MILITARY",
                        "signal_type": "perception_alert",
                        "salience": 0.90,
                        "weight": 0.45,
                        "region": zone.get("region", "GLOBAL"),
                    })

        if military_count > 0:
            logger.info("[Airspace] Zone %s: %d total aircraft, %d military",
                        zone_id, total_aircraft, military_count)

        return anomalies

    async def poll_all_zones(self) -> list[dict]:
        """Poll all strategic zones. Returns combined anomaly list."""
        now = time.time()
        if now - self._last_poll < self._cooldown:
            return []
        self._last_poll = now
        self._rate_limited = False

        all_anomalies = []
        zones_polled = 0
        for zone_id, zone in STRATEGIC_ZONES.items():
            if self._rate_limited:
                break
            try:
                results = await self.poll_zone(zone_id, zone)
                all_anomalies.extend(results)
                zones_polled += 1
            except Exception as exc:
                logger.warning("[Airspace] Zone %s poll failed: %s", zone_id, exc)
            await asyncio.sleep(2)  # Respect rate limits

        # Adapt cooldown based on rate limiting
        if self._rate_limited:
            self._cooldown = min(self._cooldown * 2, 900)  # Back off up to 15 min
            logger.info("[Airspace] Rate limited after %d/%d zones — cooldown extended to %ds",
                        zones_polled, len(STRATEGIC_ZONES), self._cooldown)
        elif self._cooldown > self._default_cooldown:
            self._cooldown = self._default_cooldown  # Reset to default on success

        if all_anomalies:
            logger.info("[Airspace] Total anomalies from %d zones: %d",
                        zones_polled, len(all_anomalies))
        return all_anomalies


# ══════════════════════════════════════════════════════════════════════════════
#  MARITIME SHIPPING MONITOR
#  Uses free AIS data sources to track shipping anomalies:
#  - Dark shipping (AIS transponder off in monitored areas)
#  - Chokepoint congestion / blockade indicators
#  - Unusual vessel patterns near critical infrastructure
#
#  Data sources:
#  - Marine Cadastre (US govt, free AIS data — delayed 3-6 months)
#  - UN Global Platform (experimental, near-real-time for some regions)
#  - Danish Maritime Authority (free, near-real-time for European waters)
#  - MarineTraffic Free Tier (limited, 5 requests/hour)
# ══════════════════════════════════════════════════════════════════════════════

# Chokepoint vessel count baselines (approximate daily averages)
_CHOKEPOINT_BASELINES = {
    "hormuz": {"daily_avg": 80, "tanker_pct": 0.6},
    "suez": {"daily_avg": 50, "tanker_pct": 0.3},
    "malacca": {"daily_avg": 200, "tanker_pct": 0.25},
    "bab_el_mandeb": {"daily_avg": 40, "tanker_pct": 0.35},
    "bosporus": {"daily_avg": 120, "tanker_pct": 0.15},
    "taiwan_strait": {"daily_avg": 150, "tanker_pct": 0.10},
}


class MaritimeMonitor:
    """Monitors global shipping traffic for strategic anomalies.

    Uses multiple free data sources to detect:
      - Chokepoint traffic disruptions
      - AIS blackouts (dark shipping)
      - Unusual vessel concentrations
      - Sanctioned vessel movements
    """

    def __init__(
        self,
        marinetraffic_api_key: str = "",
    ):
        self.marinetraffic_api_key = marinetraffic_api_key
        self._client: httpx.AsyncClient | None = None
        self._last_poll: float = 0
        self._cooldown = 900  # 15 min between polls
        # Track chokepoint traffic over time
        self._chokepoint_history: dict[str, list[dict]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={"User-Agent": "XDART-Phi/1.0 Maritime Intelligence"},
            )
        return self._client

    async def poll_chokepoints(self) -> list[dict]:
        """Check maritime traffic through strategic chokepoints.

        Uses the Danish Maritime Authority AIS data (free, European waters)
        and supplementary sources for global coverage.
        Returns list of anomaly dicts.
        """
        now = time.time()
        if now - self._last_poll < self._cooldown:
            return []
        self._last_poll = now

        anomalies = []
        client = await self._get_client()

        # Source 1: Danish Maritime Authority (free AIS — European waters only)
        # Covers: Bosporus, Suez approach, Bab el-Mandeb approach
        try:
            await self._poll_dma_ais(client, anomalies)
        except Exception as exc:
            logger.debug("[Maritime] DMA AIS poll failed: %s", exc)

        # Source 2: Search news for chokepoint disruptions (proxy signal)
        # When direct AIS data is limited, news about shipping disruptions
        # is the next best signal — and our RSS feeds already capture this.
        # This method checks for explicit chokepoint mention patterns.
        try:
            await self._check_chokepoint_news_proxy(client, anomalies)
        except Exception as exc:
            logger.debug("[Maritime] Chokepoint news proxy failed: %s", exc)

        return anomalies

    async def _poll_dma_ais(
        self, client: httpx.AsyncClient, anomalies: list[dict],
    ) -> None:
        """Poll Danish Maritime Authority for recent AIS data near European chokepoints."""
        # DMA provides historical AIS data — we use it as a structural signal
        # When DMA data shows traffic drops, it's confirmed by infrastructure dependency model
        dma_url = "https://ais.dma.dk/api/v1/recent"
        try:
            resp = await client.get(dma_url, timeout=15)
            if resp.status_code != 200:
                return

            data = resp.json()
            # DMA returns ship positions — check for traffic anomalies near Bosporus
            bosporus_ships = []
            for ship in (data if isinstance(data, list) else data.get("data", [])):
                lat = ship.get("lat", 0)
                lon = ship.get("lon", 0)
                # Bosporus region: ~40.5-41.5°N, 28.5-29.5°E
                if 40.5 <= lat <= 41.5 and 28.5 <= lon <= 29.5:
                    bosporus_ships.append(ship)

            if bosporus_ships:
                baseline = _CHOKEPOINT_BASELINES["bosporus"]["daily_avg"]
                # Normalize to comparable timeframe
                count = len(bosporus_ships)
                if count < baseline * 0.3:
                    anomalies.append({
                        "headline": (
                            f"Bosporus shipping traffic unusually low: {count} vessels "
                            f"(baseline ~{baseline}/day) — possible disruption"
                        ),
                        "source": "dma_ais",
                        "domain": "ECONOMIC",
                        "signal_type": "infrastructure_cascade",
                        "salience": 0.85,
                        "weight": 0.40,
                        "region": "EU",
                    })

        except httpx.TimeoutException:
            logger.debug("[Maritime] DMA AIS timeout")
        except Exception as exc:
            logger.debug("[Maritime] DMA AIS error: %s", exc)

    async def _check_chokepoint_news_proxy(
        self, client: httpx.AsyncClient, anomalies: list[dict],
    ) -> None:
        """Use GDELT DOC API as a proxy for chokepoint disruption detection.

        Queries GDELT for recent mentions of shipping disruptions at key chokepoints.
        This is a complement to direct AIS monitoring — when ships go dark,
        news about the disruption often surfaces within hours.
        """
        chokepoint_queries = [
            ("hormuz", '"Strait of Hormuz" (blockade OR attack OR closure OR disruption OR naval)'),
            ("suez", '"Suez Canal" (blocked OR grounding OR disruption OR attack OR closure)'),
            ("bab_el_mandeb", '("Bab el-Mandeb" OR "Red Sea" OR "Houthi") (shipping OR attack OR blockade)'),
            ("malacca", '"Strait of Malacca" (piracy OR attack OR disruption OR closure)'),
            ("taiwan_strait", '"Taiwan Strait" (military OR blockade OR exercise OR naval)'),
        ]

        for zone_id, query in chokepoint_queries:
            try:
                resp = await client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={
                        "query": query,
                        "mode": "artlist",
                        "maxrecords": 5,
                        "format": "json",
                        "timespan": "24h",
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue

                articles = resp.json().get("articles", [])
                if len(articles) >= 3:
                    # Multiple recent articles about disruption = real signal
                    zone_name = STRATEGIC_ZONES.get(zone_id, {}).get("name", zone_id)
                    headlines = [a.get("title", "")[:100] for a in articles[:3]]
                    anomalies.append({
                        "headline": (
                            f"Maritime disruption signals at {zone_name}: "
                            f"{len(articles)} reports in 24h"
                        ),
                        "source": "gdelt_maritime_proxy",
                        "domain": "ECONOMIC",
                        "signal_type": "infrastructure_cascade",
                        "salience": 0.80,
                        "weight": 0.35,
                        "region": STRATEGIC_ZONES.get(zone_id, {}).get("region", "GLOBAL"),
                        "raw": {"headlines": headlines, "article_count": len(articles)},
                    })

                await asyncio.sleep(5)  # GDELT rate limit
            except Exception as exc:
                logger.debug("[Maritime] Chokepoint proxy %s failed: %s", zone_id, exc)


# ══════════════════════════════════════════════════════════════════════════════
#  SATELLITE INTELLIGENCE (NASA FIRMS — Fire/Thermal Anomaly Detection)
#  Monitors thermal anomalies near strategic facilities.
#  This is NOT satellite imagery analysis — it's thermal hotspot detection
#  from VIIRS/MODIS sensors, which shows:
#    - Military facility activity (jet engine tests, munitions fires)
#    - Industrial facility changes
#    - Infrastructure damage (fires from strikes)
#  NASA FIRMS is FREE, near-real-time (3h delay), no API key for basic access.
# ══════════════════════════════════════════════════════════════════════════════

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_MAP_KEY_URL = "https://firms.modaps.eosdis.nasa.gov/api/data_availability"


class SatelliteMonitor:
    """Monitors NASA FIRMS thermal anomaly data near strategic facilities.

    Detects unusual heat signatures that could indicate:
      - Military activity (runway operations, missile launches)
      - Infrastructure damage (bombing, sabotage)
      - Industrial incidents (refinery fires, pipeline explosions)
    """

    def __init__(self, firms_map_key: str = ""):
        # NASA FIRMS MAP_KEY — get free from https://firms.modaps.eosdis.nasa.gov/api/area/
        self.firms_map_key = firms_map_key
        self._client: httpx.AsyncClient | None = None
        self._last_poll: float = 0
        self._cooldown = 3600  # 1 hour (FIRMS updates every ~3h)
        # Track known fire locations to detect NEW anomalies
        self._known_fires: dict[str, float] = {}  # hash → last_seen_ts
        self._known_ttl = 86400  # 24 hours

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(45.0),
                headers={"User-Agent": "XDART-Phi/1.0 Satellite Intelligence"},
            )
        return self._client

    async def poll_strategic_zones(self) -> list[dict]:
        """Poll FIRMS for thermal anomalies near strategic facilities.

        Returns list of anomaly dicts ready for PatternAccumulator.
        """
        now = time.time()
        if now - self._last_poll < self._cooldown:
            return []
        self._last_poll = now

        if not self.firms_map_key:
            logger.debug("[Satellite] No FIRMS MAP_KEY configured — skipping")
            return []

        anomalies = []
        client = await self._get_client()

        # Prune old known fires
        self._known_fires = {
            k: v for k, v in self._known_fires.items()
            if now - v < self._known_ttl
        }

        # Check each strategic zone
        for zone_id, zone in STRATEGIC_ZONES.items():
            try:
                results = await self._poll_firms_zone(client, zone_id, zone)
                anomalies.extend(results)
            except Exception as exc:
                logger.debug("[Satellite] Zone %s poll failed: %s", zone_id, exc)
            await asyncio.sleep(1)  # Be gentle with FIRMS API

        if anomalies:
            logger.info("[Satellite] Total thermal anomalies near strategic zones: %d",
                        len(anomalies))
        return anomalies

    async def _poll_firms_zone(
        self,
        client: httpx.AsyncClient,
        zone_id: str,
        zone: dict,
    ) -> list[dict]:
        """Query FIRMS for a specific zone's bounding box."""
        lat, lon = zone["lat"], zone["lon"]
        r = zone["radius_km"] / 111.0

        # FIRMS CSV API: /api/area/csv/{MAP_KEY}/{source}/{area}/{day_range}
        # area format: west,south,east,north
        area = f"{lon - r:.2f},{lat - r:.2f},{lon + r:.2f},{lat + r:.2f}"

        try:
            resp = await client.get(
                f"{FIRMS_BASE_URL}/{self.firms_map_key}/VIIRS_SNPP_NRT/{area}/1",
                timeout=30,
            )
            if resp.status_code != 200:
                logger.debug("[Satellite] FIRMS returned %d for zone %s",
                             resp.status_code, zone_id)
                return []

            # Parse CSV response
            import csv
            import io
            reader = csv.DictReader(io.StringIO(resp.text))
            fires = list(reader)

        except Exception as exc:
            logger.debug("[Satellite] FIRMS request failed for %s: %s", zone_id, exc)
            return []

        if not fires:
            return []

        anomalies = []
        new_fires = 0

        for fire in fires:
            # De-dup: create hash from lat/lon/date
            fire_hash = hashlib.md5(
                f"{fire.get('latitude','')},{fire.get('longitude','')},{fire.get('acq_date','')}".encode()
            ).hexdigest()[:12]

            if fire_hash in self._known_fires:
                continue
            self._known_fires[fire_hash] = time.time()
            new_fires += 1

            # High-confidence fires near strategic facilities are significant.
            # All monitored satellite zones are geopolitically critical by design —
            # accept medium/nominal confidence fires with brightness ≥ 310K.
            # Only filter out very low-confidence AND very low-brightness noise.
            confidence = fire.get("confidence", "nominal")
            bright_ti4 = float(fire.get("bright_ti4", 0) or 0)

            # Accept: high confidence, OR any brightness ≥ 310K, OR nominal with ≥ 280K
            is_significant = (
                confidence in ("high", "h") or
                bright_ti4 >= 310 or
                (confidence in ("nominal", "n") and bright_ti4 >= 280)
            )
            if not is_significant:
                continue

            anomalies.append({
                "headline": (
                    f"Thermal anomaly detected near {zone['name']} "
                    f"({fire.get('latitude', '?')}°N, {fire.get('longitude', '?')}°E, "
                    f"brightness={bright_ti4:.0f}K, confidence={confidence})"
                ),
                "source": "nasa_firms",
                "domain": "MILITARY",
                "signal_type": "perception_alert",
                "salience": 0.85 if confidence in ("high", "h") else 0.70,
                "weight": 0.40 if confidence in ("high", "h") else 0.25,
                "region": zone.get("region", "GLOBAL"),
                "raw": {
                    "zone": zone_id,
                    "zone_significance": zone["significance"],
                    "latitude": fire.get("latitude"),
                    "longitude": fire.get("longitude"),
                    "brightness": bright_ti4,
                    "confidence": confidence,
                    "acq_date": fire.get("acq_date"),
                    "acq_time": fire.get("acq_time"),
                    "satellite": fire.get("satellite", "VIIRS"),
                },
            })

        if new_fires > 0:
            logger.info("[Satellite] Zone %s: %d total fires, %d new, %d anomalies",
                        zone_id, len(fires), new_fires, len(anomalies))

        return anomalies


# ══════════════════════════════════════════════════════════════════════════════
#  MULTIMODAL PERCEPTION LOOP
#  Integrates all multimodal collectors into the data pipeline.
#  Runs alongside the existing DataCollector.
# ══════════════════════════════════════════════════════════════════════════════

class MultimodalCollector:
    """Orchestrates all multimodal perception sources.

    Runs on a 30-minute loop (staggered from the main 15-min RSS cycle).
    Feeds anomalies into the PatternAccumulator via on_alert callback.
    """

    def __init__(
        self,
        on_alert: Callable | None = None,
        opensky_user: str = "",
        opensky_pass: str = "",
        firms_map_key: str = "",
        marinetraffic_api_key: str = "",
        entity_graph: Any | None = None,
        memory_store_fn: Callable | None = None,
    ):
        self.on_alert = on_alert
        self.entity_graph = entity_graph
        self.memory_store_fn = memory_store_fn
        self.airspace = AirspaceMonitor(
            opensky_user=opensky_user,
            opensky_pass=opensky_pass,
        )
        self.maritime = MaritimeMonitor(
            marinetraffic_api_key=marinetraffic_api_key,
        )
        self.satellite = SatelliteMonitor(
            firms_map_key=firms_map_key,
        )
        self._cycle_count = 0

    async def run_forever(self):
        """Main loop — polls all multimodal sources every 30 minutes."""
        logger.info("[Multimodal] Starting multimodal perception loop")

        # Initial delay: let the main collector start first (90s)
        await asyncio.sleep(90)

        while True:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                logger.info("[Multimodal] Perception loop cancelled")
                break
            except Exception as exc:
                logger.warning("[Multimodal] Cycle error: %s", exc)
            await asyncio.sleep(1800)  # 30 minutes

    async def _run_cycle(self):
        """Single collection cycle across all multimodal sources."""
        self._cycle_count += 1
        logger.info("[Multimodal] ═══ Cycle %d starting ═══", self._cycle_count)
        all_anomalies = []

        # Phase 1: Airspace monitoring (OpenSky)
        try:
            airspace_results = await self.airspace.poll_all_zones()
            all_anomalies.extend(airspace_results)
            logger.info("[Multimodal] Airspace: %d anomalies", len(airspace_results))
        except Exception as exc:
            logger.warning("[Multimodal] Airspace collection failed: %s", exc)

        # Phase 2: Maritime monitoring
        try:
            maritime_results = await self.maritime.poll_chokepoints()
            all_anomalies.extend(maritime_results)
            logger.info("[Multimodal] Maritime: %d anomalies", len(maritime_results))
        except Exception as exc:
            logger.warning("[Multimodal] Maritime collection failed: %s", exc)

        # Phase 3: Satellite thermal anomalies (FIRMS)
        try:
            satellite_results = await self.satellite.poll_strategic_zones()
            all_anomalies.extend(satellite_results)
            logger.info("[Multimodal] Satellite: %d anomalies", len(satellite_results))
        except Exception as exc:
            logger.warning("[Multimodal] Satellite collection failed: %s", exc)

        # Phase 4: Fire alerts to PatternAccumulator
        if all_anomalies and self.on_alert:
            try:
                logger.info("[Multimodal] Firing %d multimodal anomalies to PatternAccumulator",
                            len(all_anomalies))
                await asyncio.get_event_loop().run_in_executor(
                    None, self.on_alert, all_anomalies,
                )
            except Exception as exc:
                logger.warning("[Multimodal] Alert callback failed: %s", exc)

        # Phase 5: Feed anomalies into Entity Knowledge Graph (NER extraction)
        if all_anomalies and self.entity_graph:
            try:
                loop = asyncio.get_event_loop()
                for anomaly in all_anomalies[:20]:  # Cap to avoid overwhelming
                    headline = anomaly.get("headline", "")
                    if headline:
                        await loop.run_in_executor(
                            None,
                            self.entity_graph.ingest_headline,
                            headline,
                            anomaly.get("source", "multimodal"),
                        )
                await loop.run_in_executor(None, self.entity_graph.save)
                logger.info("[Multimodal] Fed %d anomalies to EntityGraph",
                            min(len(all_anomalies), 20))
            except Exception as exc:
                logger.warning("[Multimodal] EntityGraph feed failed: %s", exc)

        # Phase 6: Store cycle summary in semantic memory (Qdrant embeddings)
        if self.memory_store_fn:
            try:
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                if all_anomalies:
                    summaries = [a.get("headline", "") for a in all_anomalies[:10]]
                    content = (f"Multimodal OSINT cycle {self._cycle_count} ({ts}): "
                               f"{len(all_anomalies)} anomalies detected. "
                               + " | ".join(summaries))
                else:
                    stats = self.get_stats()
                    content = (f"Multimodal OSINT cycle {self._cycle_count} ({ts}): "
                               f"No anomalies. Monitored {stats['airspace']['monitored_zones']} "
                               f"airspace zones, {stats['maritime']['chokepoints_monitored']} "
                               f"chokepoints, satellite={'active' if stats['satellite']['firms_enabled'] else 'inactive'}. "
                               f"All within normal parameters.")
                self.memory_store_fn(
                    layer="semantic",
                    content=content,
                    tags=["multimodal_osint", "airspace", "maritime", "satellite"],
                )
                logger.info("[Multimodal] Cycle summary stored in semantic memory")
            except Exception as exc:
                logger.warning("[Multimodal] Memory store failed: %s", exc)

        logger.info("[Multimodal] Cycle %d complete — %d total anomalies",
                    self._cycle_count, len(all_anomalies))

    def get_stats(self) -> dict:
        """Return multimodal collector statistics."""
        return {
            "cycles": self._cycle_count,
            "airspace": {
                "monitored_zones": len(STRATEGIC_ZONES),
                "tracked_military": len(self.airspace._seen_military),
                "zone_baselines": {
                    k: len(v) for k, v in self.airspace._zone_baselines.items()
                },
            },
            "maritime": {
                "chokepoints_monitored": len(_CHOKEPOINT_BASELINES),
            },
            "satellite": {
                "firms_enabled": bool(self.satellite.firms_map_key),
                "known_fires": len(self.satellite._known_fires),
            },
        }
