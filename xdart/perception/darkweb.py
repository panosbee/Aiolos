"""
XDART-Φ × Dark Web Intelligence — Clearnet OSINT Collector
============================================================

Collects threat signals from dark-adjacent CLEARNET sources:

  1. Telegram public channels    — t.me/s/{channel} scrape (no API key needed)
  2. Pastebin public archive     — HTML scrape + content fetch for keyword matches
  3. Ahmia.fi clearnet search    — dark web index, searched by threat keywords
  4. OSINT APIs (optional)       — DarkOwl / IntelligenceX when API keys configured

ARCHITECTURE:
  ┌─────────────────────────┐
  │   clearnet dark sources  │
  └──────────┬──────────────┘
             │  raw signals
             ▼
  ┌─────────────────────────┐
  │   DIRTY POOL            │  MongoDB: dark_signals_raw
  │   ISOLATION BOUNDARY    │  ← NEVER mixed with clean PerceptionDB
  └──────────┬──────────────┘
             │  → DarkSignalTriage (intelligence/dark_triage.py)
             ▼
  ┌─────────────────────────┐
  │   TRIAGE + SYNTHESIS    │  intelligence/dark_triage.py
  │   → DarkWhisperEngine   │  intelligence/darkwhisper.py
  └─────────────────────────┘

The collector runs as a background asyncio task.
Collection interval: DARKWEB_COLLECTION_INTERVAL (default 30 minutes).
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from xdart import config

logger = logging.getLogger(__name__)

# ── HTTP client settings ──────────────────────────────────────────────────────
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 20  # seconds per request
_MAX_SIGNALS_PER_CHANNEL = 20  # cap per Telegram channel per collection cycle
_MAX_PASTES_PER_CYCLE = 30     # cap for pastebin per collection cycle
_MAX_AHMIA_RESULTS = 15        # cap for ahmia.fi results per keyword


# ══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DarkSignal:
    """A single raw signal collected from a dark-adjacent clearnet source.

    This object lives in the DIRTY POOL until triage. It is immutable after
    creation (the triage engine operates on copies). raw_credibility is a
    heuristic estimate from the collector; the authoritative score comes from
    LLM triage.
    """

    # Content
    text: str                        # Raw text of the signal
    source_url: str                  # Where it was found (exact URL or channel path)
    source_type: str                 # "telegram" | "paste" | "ahmia" | "darkowl" | "intelx"
    channel_name: str                # Channel/site name (e.g. "killnet_channel")

    # Timing
    collected_at: str                # ISO-8601 UTC timestamp of collection
    published_at: str                # ISO-8601 UTC timestamp from source (may equal collected_at)

    # Heuristic pre-triage attributes (rough estimates, triage will override)
    raw_credibility: float = 0.10    # Baseline — how credible from source reputation alone
    appeared_in_n_channels: int = 1  # Cross-channel corroboration count (updated post-collection)
    pgp_signed: bool = False         # Whether source content carries a PGP signature claim
    language_hint: str = ""          # ISO 639-1 code if detectable from source context

    # Deduplication
    content_hash: str = ""           # SHA256 of normalized text — set by collector

    # Internal
    _id: str = ""                    # MongoDB ObjectId string (set after insertion)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.text.strip().lower().encode("utf-8", errors="replace")
            ).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_id", None)
        return d


# ══════════════════════════════════════════════════════════════════════════════
#  DIRTY POOL — MongoDB isolation layer
# ══════════════════════════════════════════════════════════════════════════════

class DirtyPool:
    """MongoDB-backed isolated storage for unprocessed dark signals.

    ISOLATION GUARANTEE: This collection (dark_signals_raw) is NEVER read
    by clean perception systems. Only the DarkSignalTriage engine reads it.
    """

    COLLECTION = "dark_signals_raw"

    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db
        self._available = mongo_db is not None
        if self._available:
            try:
                # Compound index: deduplication + query efficiency
                self._db[self.COLLECTION].create_index(
                    [("content_hash", 1)], unique=True, background=True
                )
                self._db[self.COLLECTION].create_index(
                    [("collected_at", -1)], background=True
                )
                self._db[self.COLLECTION].create_index(
                    [("source_type", 1), ("triaged", 1)], background=True
                )
                logger.debug("[DirtyPool] Indexes ensured on %s", self.COLLECTION)
            except Exception as exc:
                logger.warning("[DirtyPool] Index creation failed: %s", exc)

    def insert(self, signal: DarkSignal) -> bool:
        """Insert a signal. Returns True if inserted, False if duplicate.

        Uses upsert on content_hash to prevent duplicates silently.
        """
        if not self._available:
            return False
        try:
            doc = signal.to_dict()
            doc["triaged"] = False
            doc["triage_result"] = None
            doc["inserted_at"] = datetime.now(timezone.utc).isoformat()
            # upsert=False with unique index → raises DuplicateKeyError for dupes
            self._db[self.COLLECTION].insert_one(doc)
            return True
        except Exception as exc:
            # DuplicateKeyError or other insertion error
            dup_str = str(exc)
            if "duplicate" in dup_str.lower() or "E11000" in dup_str:
                logger.debug("[DirtyPool] Duplicate signal skipped: %.60s", signal.text)
            else:
                logger.warning("[DirtyPool] Insert failed: %s", exc)
            return False

    def insert_batch(self, signals: list[DarkSignal]) -> int:
        """Insert multiple signals. Returns count of newly inserted signals."""
        inserted = 0
        for s in signals:
            if self.insert(s):
                inserted += 1
        return inserted

    def get_untriaged(self, limit: int = 50) -> list[dict]:
        """Return unprocessed signals for the triage engine."""
        if not self._available:
            return []
        try:
            return list(
                self._db[self.COLLECTION]
                .find({"triaged": False}, {"_id": 1, **{k: 1 for k in DarkSignal.__dataclass_fields__}})
                .sort("collected_at", 1)
                .limit(limit)
            )
        except Exception as exc:
            logger.warning("[DirtyPool] get_untriaged failed: %s", exc)
            return []

    def mark_triaged(self, mongo_id: Any, triage_result: dict) -> None:
        """Mark a signal as triaged with the triage result."""
        if not self._available:
            return
        try:
            self._db[self.COLLECTION].update_one(
                {"_id": mongo_id},
                {"$set": {"triaged": True, "triage_result": triage_result}},
            )
        except Exception as exc:
            logger.warning("[DirtyPool] mark_triaged failed: %s", exc)

    def stats(self) -> dict:
        """Return dirty pool statistics."""
        if not self._available:
            return {"available": False}
        try:
            total = self._db[self.COLLECTION].count_documents({})
            untriaged = self._db[self.COLLECTION].count_documents({"triaged": False})
            by_source = {}
            for src in ("telegram", "paste", "ahmia", "darkowl", "intelx"):
                by_source[src] = self._db[self.COLLECTION].count_documents({"source_type": src})
            return {
                "available": True,
                "total_signals": total,
                "untriaged": untriaged,
                "by_source": by_source,
            }
        except Exception:
            return {"available": False}

    def purge_old(self, max_age_hours: int = 168) -> int:
        """Remove signals older than max_age_hours. Returns count removed."""
        if not self._available:
            return 0
        try:
            from datetime import timedelta
            cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            ).isoformat()
            result = self._db[self.COLLECTION].delete_many(
                {"collected_at": {"$lt": cutoff}}
            )
            return result.deleted_count
        except Exception as exc:
            logger.warning("[DirtyPool] purge_old failed: %s", exc)
            return 0


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE-SPECIFIC PARSERS
# ══════════════════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape HTML entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _channel_credibility(channel: str) -> float:
    """Baseline credibility for known Telegram threat-actor channels.

    Known high-noise hacktivist channels get lower baseline; known APT-linked
    channels get a slightly higher one. Triage will refine this score.
    """
    _HIGH_NOISE = {
        "killnet_channel", "anonymous_sudan", "anonymoussudan",
        "noname05716", "noname057",
    }
    _APT_LINKED = {
        "predatory_sparrow", "cyberarmyofrussia_reborn",
        "cyber_army_russia_reborn", "xaknet_team",
    }
    ch = channel.lower().replace(" ", "_")
    if ch in _APT_LINKED:
        return 0.35
    if ch in _HIGH_NOISE:
        return 0.18
    return 0.22  # unknown channel — conservative default


async def _fetch_telegram_channel(
    client: httpx.AsyncClient,
    channel: str,
) -> list[DarkSignal]:
    """Scrape a public Telegram channel via t.me/s/{channel}.

    Telegram's channel preview endpoint returns HTML with message content.
    No authentication required — these are public broadcast channels.

    NOTE: Many Telegram channels do NOT support the web-preview /s/ endpoint.
    When t.me/s/{channel} returns a 302, the channel has no public preview
    (private group, deleted, or preview disabled). We detect this by issuing
    the first request WITHOUT following redirects. If we get a redirect, we
    skip the channel and log a warning.
    """
    signals: list[DarkSignal] = []
    url = f"https://t.me/s/{channel}"
    try:
        # Use follow_redirects=False so we can detect channels without preview
        resp = await client.get(url, timeout=_REQUEST_TIMEOUT, follow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            logger.warning(
                "[DarkWeb/Telegram] %s → redirect (no public preview, channel "
                "is private/deleted/group — consider removing from config)",
                channel,
            )
            return signals
        if resp.status_code != 200:
            logger.debug("[DarkWeb/Telegram] %s → HTTP %d", channel, resp.status_code)
            return signals

        text_html = resp.text
        # Extract message blocks: <div class="tgme_widget_message_text ...">...</div>
        # Also extract timestamps from <time datetime="...">
        msg_pattern = re.compile(
            r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )
        time_pattern = re.compile(r'<time[^>]+datetime="([^"]+)"', re.IGNORECASE)
        times = time_pattern.findall(text_html)

        raw_cred = _channel_credibility(channel)
        for i, match in enumerate(msg_pattern.finditer(text_html)):
            msg_text = _strip_html(match.group(1)).strip()
            if len(msg_text) < 20:
                continue  # skip empty or single-word posts

            pub_at = times[i] if i < len(times) else _now_iso()
            # Normalize datetime format
            try:
                pub_at = datetime.fromisoformat(pub_at.rstrip("Z")).replace(
                    tzinfo=timezone.utc
                ).isoformat()
            except (ValueError, AttributeError):
                pub_at = _now_iso()

            signals.append(DarkSignal(
                text=msg_text,
                source_url=url,
                source_type="telegram",
                channel_name=channel,
                collected_at=_now_iso(),
                published_at=pub_at,
                raw_credibility=raw_cred,
            ))

            if len(signals) >= _MAX_SIGNALS_PER_CHANNEL:
                break

        logger.info(
            "[DarkWeb/Telegram] %s → %d signals collected", channel, len(signals)
        )
    except httpx.TimeoutException:
        logger.debug("[DarkWeb/Telegram] Timeout on channel: %s", channel)
    except Exception as exc:
        logger.warning("[DarkWeb/Telegram] Error on %s: %s", channel, exc)

    return signals


async def _fetch_pastebin_archive(
    client: httpx.AsyncClient,
    keywords: list[str],
) -> list[DarkSignal]:
    """Scrape pastebin.com/archive for recent public pastes matching threat keywords.

    Pastebin public archive lists recent pastes. We fetch the list, then
    fetch individual paste content for those that match threat keywords in title.
    """
    signals: list[DarkSignal] = []
    archive_url = "https://pastebin.com/archive"
    try:
        resp = await client.get(archive_url, timeout=_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.debug("[DarkWeb/Paste] Archive HTTP %d", resp.status_code)
            return signals

        # Extract paste links: /[a-zA-Z0-9]{8} — may have ?source=archive suffix
        # Pastebin now appends ?source=archive to archive page links
        paste_links = re.findall(r'href="/([a-zA-Z0-9]{8})(?:\?[^"]*)?\"', resp.text)
        # Also extract titles from anchor text near those links
        title_pattern = re.compile(
            r'href="/([a-zA-Z0-9]{8})(?:\?[^"]*)?\"[^>]*>([^<]*)</a>', re.IGNORECASE
        )
        paste_map = {m.group(1): m.group(2).strip() for m in title_pattern.finditer(resp.text)}

        # Keywords to match in title (lowercased)
        kw_lower = [k.lower() for k in keywords]

        # Step 1: title-matched pastes (high priority)
        title_matched: list[tuple[str, str]] = []
        title_unmatched: list[tuple[str, str]] = []
        for pid, title in paste_map.items():
            title_lower = title.lower()
            if any(kw in title_lower for kw in kw_lower):
                title_matched.append((pid, title))
            else:
                title_unmatched.append((pid, title))

        # Step 2: also content-scan a sample of unmatched pastes (catches "Untitled" pastes
        # that actually contain threat-relevant content). Limit to _MAX_PASTES_PER_CYCLE total.
        _MAX_CONTENT_SCAN = 20  # max unmatched pastes to content-scan per cycle
        fetch_queue: list[tuple[str, str]] = title_matched[:]
        # Add unmatched pastes up to remaining budget for content scanning
        content_scan_candidates = title_unmatched[:_MAX_CONTENT_SCAN]
        fetch_queue.extend(content_scan_candidates)

        # Fetch up to _MAX_PASTES_PER_CYCLE paste contents total
        fetch_limit = min(len(fetch_queue), _MAX_PASTES_PER_CYCLE)
        content_matched = 0
        for pid, title in fetch_queue[:fetch_limit]:
            raw_url = f"https://pastebin.com/raw/{pid}"
            try:
                pr = await client.get(raw_url, timeout=_REQUEST_TIMEOUT)
                if pr.status_code != 200:
                    continue
                content = pr.text.strip()
                if len(content) < 30:
                    continue

                # For unmatched-title pastes, filter by content keyword
                is_title_matched = (pid, title) in title_matched
                if not is_title_matched:
                    content_lower = content.lower()
                    if not any(kw in content_lower for kw in kw_lower):
                        continue
                    content_matched += 1

                # Truncate very long pastes
                if len(content) > 4000:
                    content = content[:4000] + " [TRUNCATED]"

                signals.append(DarkSignal(
                    text=f"[PASTE: {title}]\n{content}",
                    source_url=f"https://pastebin.com/{pid}",
                    source_type="paste",
                    channel_name="pastebin",
                    collected_at=_now_iso(),
                    published_at=_now_iso(),
                    raw_credibility=0.12,  # paste sites have low baseline credibility
                ))
            except Exception:
                continue

        logger.info(
            "[DarkWeb/Paste] %d signals collected (title-match=%d, content-match=%d, scanned=%d)",
            len(signals), len(title_matched), content_matched, fetch_limit,
        )
    except httpx.TimeoutException:
        logger.debug("[DarkWeb/Paste] Archive timeout")
    except Exception as exc:
        logger.warning("[DarkWeb/Paste] Error: %s", exc)

    return signals


async def _fetch_ahmia(
    client: httpx.AsyncClient,
    keywords: list[str],
) -> list[DarkSignal]:
    """Query ahmia.fi for dark web content matching threat keywords.

    Ahmia.fi is a clearnet search engine that indexes .onion content.
    Returns HTML search results with title + snippet + .onion URL.
    """
    signals: list[DarkSignal] = []
    # Use a small subset of the most actionable keywords to avoid hammering ahmia
    priority_keywords = keywords[:5]  # top 5 only per cycle

    for keyword in priority_keywords:
        search_url = f"https://ahmia.fi/search/?q={quote_plus(keyword)}"
        try:
            resp = await client.get(search_url, timeout=_REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.debug("[DarkWeb/Ahmia] %s → HTTP %d", keyword, resp.status_code)
                continue

            # Parse result blocks: <li class="result">
            result_blocks = re.findall(
                r'<li[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</li>',
                resp.text,
                re.DOTALL | re.IGNORECASE,
            )
            count = 0
            for block in result_blocks[:_MAX_AHMIA_RESULTS]:
                # Extract title
                title_match = re.search(
                    r'<h4[^>]*>(.*?)</h4>', block, re.DOTALL | re.IGNORECASE
                )
                title = _strip_html(title_match.group(1)) if title_match else "Unknown"

                # Extract snippet/description
                desc_match = re.search(
                    r'<p[^>]*>(.*?)</p>', block, re.DOTALL | re.IGNORECASE
                )
                description = _strip_html(desc_match.group(1)) if desc_match else ""

                # Extract .onion URL (purely for provenance — not accessed)
                onion_match = re.search(r'href="(https?://[^"]+\.onion[^"]*)"', block, re.IGNORECASE)
                onion_url = onion_match.group(1) if onion_match else search_url

                combined_text = f"[AHMIA RESULT: {keyword}] {title}. {description}".strip()
                if len(combined_text) < 30:
                    continue

                signals.append(DarkSignal(
                    text=combined_text,
                    source_url=onion_url,
                    source_type="ahmia",
                    channel_name=f"ahmia_{keyword[:20].replace(' ', '_')}",
                    collected_at=_now_iso(),
                    published_at=_now_iso(),
                    raw_credibility=0.15,  # index result — actual .onion content unverified
                ))
                count += 1

            logger.debug("[DarkWeb/Ahmia] '%s' → %d results", keyword, count)

        except httpx.TimeoutException:
            logger.debug("[DarkWeb/Ahmia] Timeout for keyword: %s", keyword)
        except Exception as exc:
            logger.warning("[DarkWeb/Ahmia] Error for '%s': %s", keyword, exc)

    logger.info("[DarkWeb/Ahmia] Total: %d signals from %d keywords", len(signals), len(priority_keywords))
    return signals


async def _fetch_intelx(
    client: httpx.AsyncClient,
    api_key: str,
    keywords: list[str],
) -> list[DarkSignal]:
    """Query IntelligenceX API for dark signal intelligence.

    IntelX free tier: limited searches/day.
    API docs: https://intelx.io/tools?tab=developer
    """
    if not api_key:
        return []

    signals: list[DarkSignal] = []
    # IntelX two-step: POST /intelligent/search → GET /intelligent/search/result?id=...
    search_url = "https://2.intelx.io/intelligent/search"
    headers = {"x-key": api_key, "Content-Type": "application/json"}

    # Only search first 3 keywords to conserve quota
    for keyword in keywords[:3]:
        try:
            payload = {
                "term": keyword,
                "maxresults": 5,
                "media": 0,
                "sort": 2,
                "terminate": [],
            }
            post_resp = await client.post(
                search_url, json=payload, headers=headers, timeout=_REQUEST_TIMEOUT
            )
            if post_resp.status_code not in (200, 201):
                continue
            search_id = post_resp.json().get("id", "")
            if not search_id:
                continue

            # Fetch results
            result_url = f"https://2.intelx.io/intelligent/search/result?id={search_id}&limit=5"
            get_resp = await client.get(result_url, headers=headers, timeout=_REQUEST_TIMEOUT)
            if get_resp.status_code != 200:
                continue

            records = get_resp.json().get("records", []) or []
            for rec in records:
                name = rec.get("name", "")
                systags = " ".join(rec.get("systemtags", []))
                bucket = rec.get("bucket", "")
                combined = f"[INTELX: {keyword}] {name} — bucket:{bucket} tags:{systags}".strip()
                if len(combined) < 20:
                    continue
                signals.append(DarkSignal(
                    text=combined,
                    source_url=f"https://intelx.io/?did={rec.get('storageid', '')}",
                    source_type="intelx",
                    channel_name="intelx",
                    collected_at=_now_iso(),
                    published_at=_now_iso(),
                    raw_credibility=0.30,
                ))

        except Exception as exc:
            logger.debug("[DarkWeb/IntelX] Error for '%s': %s", keyword, exc)

    logger.info("[DarkWeb/IntelX] %d signals collected", len(signals))
    return signals


async def _fetch_darkowl(
    client: httpx.AsyncClient,
    api_key: str,
    keywords: list[str],
) -> list[DarkSignal]:
    """Query DarkOwl DARKINT API (enterprise tier).

    Returns signals only if API key is configured.
    """
    if not api_key:
        return []

    signals: list[DarkSignal] = []
    # DarkOwl requires HMAC authentication — simplified version for integration
    # Full integration requires their SDK or HMAC-SHA1 signing
    logger.info("[DarkWeb/DarkOwl] API key present but full HMAC auth not yet implemented — skipping")
    return signals


async def _fetch_rss_threat_feeds(
    client: httpx.AsyncClient,
    feed_urls: list[str],
    keywords: list[str],
) -> list[DarkSignal]:
    """Scrape RSS/Atom feeds from public threat intelligence sources.

    Parses standard RSS/Atom XML for <item> or <entry> elements.
    Filters entries by threat keywords to keep only relevant signals.
    No API key required — all feeds are public.

    Primary feeds (CISA, BleepingComputer, The Hacker News, etc.) provide
    verified, high-quality threat intelligence as reliable fallback when
    Telegram channels lack public previews.
    """
    signals: list[DarkSignal] = []
    kw_lower = [k.lower() for k in keywords]
    # Max items per feed per cycle
    _MAX_PER_FEED = 10

    for feed_url in feed_urls:
        try:
            resp = await client.get(feed_url, timeout=_REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.debug("[DarkWeb/RSS] %s → HTTP %d", feed_url, resp.status_code)
                continue

            feed_text = resp.text

            # Support both RSS <item> and Atom <entry> formats
            # Try RSS items first
            items = re.findall(r'<item[^>]*>(.*?)</item>', feed_text, re.DOTALL | re.IGNORECASE)
            if not items:
                # Try Atom entries
                items = re.findall(r'<entry[^>]*>(.*?)</entry>', feed_text, re.DOTALL | re.IGNORECASE)

            feed_domain = re.sub(r'^https?://', '', feed_url).split('/')[0]
            count = 0

            for item_xml in items[:_MAX_PER_FEED * 3]:  # check more, filter by keyword
                # Extract title
                title_m = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item_xml, re.DOTALL | re.IGNORECASE)
                title = _strip_html(title_m.group(1)) if title_m else ""

                # Extract description/summary
                desc_m = re.search(
                    r'<(?:description|summary|content)[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:description|summary|content)>',
                    item_xml, re.DOTALL | re.IGNORECASE
                )
                description = _strip_html(desc_m.group(1)) if desc_m else ""
                if len(description) > 1000:
                    description = description[:1000] + " [...]"

                # Extract link
                link_m = re.search(r'<link[^>]*>([^<]+)</link>', item_xml, re.IGNORECASE)
                if not link_m:
                    link_m = re.search(r'<link[^>]+href="([^"]+)"', item_xml, re.IGNORECASE)
                link = link_m.group(1).strip() if link_m else feed_url

                # Extract publish date
                date_m = re.search(
                    r'<(?:pubDate|published|updated)[^>]*>([^<]+)</(?:pubDate|published|updated)>',
                    item_xml, re.IGNORECASE
                )
                pub_at = _now_iso()
                if date_m:
                    try:
                        import email.utils
                        t = email.utils.parsedate_to_datetime(date_m.group(1).strip())
                        pub_at = t.isoformat()
                    except Exception:
                        pass

                combined = f"{title}. {description}".strip()
                if len(combined) < 20:
                    continue

                # Filter by keyword relevance
                combined_lower = combined.lower()
                if not any(kw in combined_lower for kw in kw_lower):
                    continue

                signals.append(DarkSignal(
                    text=f"[RSS:{feed_domain}] {combined}",
                    source_url=link,
                    source_type="rss",
                    channel_name=feed_domain,
                    collected_at=_now_iso(),
                    published_at=pub_at,
                    raw_credibility=0.55,  # established media/CERT sources are more credible
                ))
                count += 1
                if count >= _MAX_PER_FEED:
                    break

            logger.debug("[DarkWeb/RSS] %s → %d keyword-matched items", feed_domain, count)

        except httpx.TimeoutException:
            logger.debug("[DarkWeb/RSS] Timeout: %s", feed_url)
        except Exception as exc:
            logger.warning("[DarkWeb/RSS] Error on %s: %s", feed_url, exc)

    logger.info("[DarkWeb/RSS] Total: %d signals from %d feeds", len(signals), len(feed_urls))
    return signals


# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-CHANNEL CORROBORATION
# ══════════════════════════════════════════════════════════════════════════════

def _update_corroboration(signals: list[DarkSignal]) -> list[DarkSignal]:
    """Count how many distinct channels/sources mention similar content.

    Uses a simple token overlap heuristic: signals with >50% shared significant
    tokens are considered corroborating. Increments appeared_in_n_channels for
    all signals in a corroboration cluster.
    """
    if len(signals) <= 1:
        return signals

    def _tokens(text: str) -> set[str]:
        # Extract significant tokens (>= 4 chars, no punctuation)
        return {t.lower() for t in re.findall(r'\b\w{4,}\b', text)}

    token_sets = [_tokens(s.text) for s in signals]

    for i, sig_i in enumerate(signals):
        count = 1  # counts itself
        ts_i = token_sets[i]
        if not ts_i:
            continue
        for j, sig_j in enumerate(signals):
            if i == j:
                continue
            if sig_i.channel_name == sig_j.channel_name:
                continue  # same source doesn't count as corroboration
            ts_j = token_sets[j]
            if not ts_j:
                continue
            overlap = len(ts_i & ts_j) / min(len(ts_i), len(ts_j))
            if overlap > 0.50:
                count += 1
        sig_i.appeared_in_n_channels = count

    return signals


# ══════════════════════════════════════════════════════════════════════════════
#  DARK WEB COLLECTOR — main class
# ══════════════════════════════════════════════════════════════════════════════

class DarkWebCollector:
    """Background clearnet OSINT collector for dark-adjacent threat intelligence.

    Runs as a long-lived asyncio task. On each cycle:
      1. Collects from all enabled sources concurrently
      2. Updates cross-channel corroboration scores
      3. Inserts new (non-duplicate) signals into DirtyPool
      4. Reports stats to logger

    The collector does NOT triage or synthesize. It only collects.
    Triage is done by DarkSignalTriage. Synthesis by DarkWhisperEngine.
    """

    # Path to the dynamic channel registry managed by TelegramIntelTool
    _INTEL_CHANNELS_FILE = (
        __import__("pathlib").Path(__file__).resolve().parent.parent.parent
        / "telegram_intel_channels.json"
    )

    def __init__(self, dirty_pool: DirtyPool) -> None:
        self.pool = dirty_pool
        self._running = False
        self._task: asyncio.Task | None = None
        self._total_collected = 0
        self._total_inserted = 0
        self._last_cycle_at: str = ""
        self._cycle_count = 0
        # Dynamically managed channels — populated by TelegramIntelTool at runtime
        self._dynamic_channels: list[str] = self._load_dynamic_channels()

    def _load_dynamic_channels(self) -> list[str]:
        """Load channels added by TelegramIntelTool from the channel registry file."""
        try:
            if self._INTEL_CHANNELS_FILE.exists():
                import json as _json
                data = _json.loads(self._INTEL_CHANNELS_FILE.read_text(encoding="utf-8"))
                handles = list(data.get("channels", {}).keys())
                if handles:
                    logger.info(
                        "[DarkWebCollector] Loaded %d dynamic Telegram channels from %s",
                        len(handles), self._INTEL_CHANNELS_FILE.name,
                    )
                return handles
        except Exception as exc:
            logger.debug("[DarkWebCollector] Dynamic channels load failed: %s", exc)
        return []

    def start(self) -> None:
        """Start the background collection loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._loop())
        logger.info(
            "[DarkWebCollector] Started — interval=%ds, telegram=%d channels (%d static, %d dynamic), "
            "ahmia=%s, paste=%s, rss=%s (%d feeds)",
            config.DARKWEB_COLLECTION_INTERVAL,
            len(config.DARKWEB_TELEGRAM_CHANNELS) + len(self._dynamic_channels),
            len(config.DARKWEB_TELEGRAM_CHANNELS),
            len(self._dynamic_channels),
            config.DARKWEB_AHMIA_ENABLED,
            config.DARKWEB_PASTE_ENABLED,
            config.DARKWEB_RSS_ENABLED,
            len(config.DARKWEB_RSS_FEEDS),
        )

    def stop(self) -> None:
        """Stop the collection loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[DarkWebCollector] Stopped after %d cycles", self._cycle_count)

    def stats(self) -> dict:
        return {
            "running": self._running,
            "cycles_completed": self._cycle_count,
            "total_signals_collected": self._total_collected,
            "total_inserted_to_pool": self._total_inserted,
            "last_cycle_at": self._last_cycle_at,
            "pool": self.pool.stats(),
        }

    async def collect_now(self) -> int:
        """Run a single collection cycle immediately.

        Returns number of signals inserted into dirty pool.
        """
        return await self._run_cycle()

    # ── Internal loop ─────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Main background loop."""
        # Brief startup delay to let other services initialize
        await asyncio.sleep(30)
        while self._running:
            try:
                inserted = await self._run_cycle()
                logger.info(
                    "[DarkWebCollector] Cycle %d complete — %d new signals → dirty pool",
                    self._cycle_count, inserted,
                )
            except Exception as exc:
                logger.warning("[DarkWebCollector] Cycle error: %s", exc)

            # Purge old signals from dirty pool (runs after each cycle)
            try:
                removed = self.pool.purge_old(config.DARKWEB_MAX_SIGNAL_AGE_HOURS)
                if removed:
                    logger.info("[DarkWebCollector] Purged %d expired signals from dirty pool", removed)
            except Exception as exc:
                logger.debug("[DarkWebCollector] Purge failed: %s", exc)

            try:
                await asyncio.sleep(config.DARKWEB_COLLECTION_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _run_cycle(self) -> int:
        """Execute one full collection cycle. Returns signals inserted."""
        self._cycle_count += 1
        self._last_cycle_at = _now_iso()
        all_signals: list[DarkSignal] = []

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            # Gather all source tasks concurrently
            tasks = []

            # Telegram channels — from config + dynamically added by TelegramIntelTool
            all_telegram = list(config.DARKWEB_TELEGRAM_CHANNELS)
            for ch in self._dynamic_channels:
                if ch not in all_telegram:
                    all_telegram.append(ch)
            for channel in all_telegram:
                tasks.append(_fetch_telegram_channel(client, channel))

            # Paste sites
            if config.DARKWEB_PASTE_ENABLED:
                tasks.append(_fetch_pastebin_archive(client, config.DARKWEB_THREAT_KEYWORDS))

            # Ahmia.fi
            if config.DARKWEB_AHMIA_ENABLED:
                tasks.append(_fetch_ahmia(client, config.DARKWEB_THREAT_KEYWORDS))

            # OSINT APIs
            if config.DARKWEB_INTELX_KEY:
                tasks.append(_fetch_intelx(client, config.DARKWEB_INTELX_KEY, config.DARKWEB_THREAT_KEYWORDS))

            if config.DARKWEB_DARKOWL_KEY:
                tasks.append(_fetch_darkowl(client, config.DARKWEB_DARKOWL_KEY, config.DARKWEB_THREAT_KEYWORDS))

            # RSS threat intelligence feeds (CISA, BleepingComputer, The Hacker News, etc.)
            if config.DARKWEB_RSS_ENABLED and config.DARKWEB_RSS_FEEDS:
                tasks.append(_fetch_rss_threat_feeds(
                    client, config.DARKWEB_RSS_FEEDS, config.DARKWEB_THREAT_KEYWORDS
                ))

            # Execute all tasks concurrently, collect results
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.debug("[DarkWebCollector] Source task error: %s", res)
                elif isinstance(res, list):
                    all_signals.extend(res)

        self._total_collected += len(all_signals)

        # Filter by minimum raw credibility
        all_signals = [
            s for s in all_signals
            if s.raw_credibility >= config.DARKWEB_MIN_CREDIBILITY
        ]

        # Update cross-channel corroboration scores
        all_signals = _update_corroboration(all_signals)

        # Insert into dirty pool (deduplication via content_hash)
        inserted = self.pool.insert_batch(all_signals)
        self._total_inserted += inserted

        return inserted
