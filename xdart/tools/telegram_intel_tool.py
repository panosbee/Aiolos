"""
XDART-Φ — Telegram Intelligence Tool
======================================

Gives Αίολος the ability to autonomously DISCOVER, EVALUATE, and MONITOR
Telegram channels for threat intelligence, without human curation.

Αίολος uses web search to find relevant channels, validates them for
public preview access, and adds them to the live DarkWebCollector pipeline.

TWO-TIER ARCHITECTURE:
  ┌──────────────────────────────────────────────────────┐
  │ Tier 1 — Active immediately, no extra credentials    │
  │   • Channel discovery via Brave web search           │
  │   • Validation via t.me/s/ preview check (no-redir)  │
  │   • Dynamic monitoring list (telegram_channels.json) │
  │   • DarkWebCollector hot-reload (no restart needed)  │
  └──────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────┐
  │ Tier 2 — Full MTProto access (requires setup once)   │
  │   • Join private/restricted channels                 │
  │   • Read full channel history                        │
  │   • Telegram native channel search                   │
  │   • Channel network graph (discover similar channels)│
  │                                                      │
  │   Setup:                                             │
  │   1. https://my.telegram.org/apps → create app       │
  │      → get api_id (int) + api_hash (str)             │
  │   2. Add to .env:                                    │
  │        TELEGRAM_API_ID=12345678                      │
  │        TELEGRAM_API_HASH=abcdef...                   │
  │   3. Run:                                            │
  │        python _setup_telegram_session.py             │
  │      (one-time interactive phone verification)       │
  └──────────────────────────────────────────────────────┘

TAG INTERFACE (Αίολος uses these in his chat responses):

  <TELEGRAM_INTEL action="search" query="hacktivist DDoS Russia" />
  <TELEGRAM_INTEL action="search" query="cyber threat Ukraine" limit="10" />
  <TELEGRAM_INTEL action="add" channel="channel_handle" reason="APT-linked" />
  <TELEGRAM_INTEL action="remove" channel="channel_handle" />
  <TELEGRAM_INTEL action="list" />
  <TELEGRAM_INTEL action="read" channel="channel_handle" limit="20" />

© Panos Skouras — Salimov MON IKE, 2026
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("xdart.telegram_intel")

# ── Config ────────────────────────────────────────────────────────────────────
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 12  # seconds
_MAX_CHANNELS_PER_SEARCH = 20  # how many candidate handles to test per search
_MAX_MONITORED_CHANNELS = 50  # cap on dynamic channel list size

# Channel list file — written to workspace root; loaded by DarkWebCollector
_CHANNELS_FILE = Path(__file__).resolve().parent.parent.parent / "telegram_intel_channels.json"


# ══════════════════════════════════════════════════════════════════════════════
#  CHANNEL STORAGE
# ══════════════════════════════════════════════════════════════════════════════

def _load_channels() -> dict[str, dict]:
    """Load the dynamic channel registry from disk. Returns {handle: metadata}."""
    if not _CHANNELS_FILE.exists():
        return {}
    try:
        data = json.loads(_CHANNELS_FILE.read_text(encoding="utf-8"))
        return data.get("channels", {})
    except Exception:
        return {}


def _save_channels(channels: dict[str, dict]) -> None:
    """Persist the channel registry to disk."""
    try:
        _CHANNELS_FILE.write_text(
            json.dumps(
                {"channels": channels, "updated_at": datetime.now(timezone.utc).isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("[TelegramIntel] Failed to save channels file: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
#  CHANNEL VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def _has_web_preview(handle: str, client: httpx.Client) -> tuple[bool, int]:
    """Check if t.me/s/{handle} has a working web preview (no redirect).

    Returns (has_preview, message_count).
    """
    url = f"https://t.me/s/{handle}"
    try:
        r = client.get(url, follow_redirects=False, timeout=_REQUEST_TIMEOUT)
        if r.status_code in (301, 302, 303, 307, 308):
            return False, 0
        if r.status_code != 200:
            return False, 0
        has_msgs = "tgme_widget_message" in r.text
        count = len(re.findall(r"tgme_widget_message_text", r.text))
        # Skip channels that only have the "Channel created" system message
        if count <= 1:
            sample = re.search(
                r'tgme_widget_message_text[^>]*>(.*?)</div>', r.text, re.DOTALL
            )
            if sample:
                text = re.sub(r"<[^>]+>", " ", sample.group(1)).strip().lower()
                if "channel created" in text or len(text) < 10:
                    return False, 0
        return has_msgs and count > 0, count
    except Exception:
        return False, 0


def _extract_handles_from_text(text: str) -> list[str]:
    """Extract t.me/{handle} references from arbitrary text (web search results)."""
    # Match t.me/handle — handles can contain letters, numbers, underscores, min 5 chars
    patterns = [
        r't\.me/([a-zA-Z][a-zA-Z0-9_]{4,})',
        r'telegram\.me/([a-zA-Z][a-zA-Z0-9_]{4,})',
        r'@([a-zA-Z][a-zA-Z0-9_]{4,})',  # @handle mentions in text
    ]
    handles = []
    for pat in patterns:
        handles.extend(re.findall(pat, text))
    # Deduplicate preserving order, filter out common non-channel handles
    _SKIP = {"telegram", "telegrambot", "storebot", "channelbot", "vote", "search", "privacy"}
    seen = set()
    result = []
    for h in handles:
        h_lower = h.lower()
        if h_lower not in seen and h_lower not in _SKIP and len(h) >= 5:
            seen.add(h_lower)
            result.append(h)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN TOOL CLASS
# ══════════════════════════════════════════════════════════════════════════════

class TelegramIntelTool:
    """Autonomous Telegram channel discovery and monitoring tool for Αίολος.

    Tier 1 (always active):
      - Web search to discover candidate channels by topic
      - t.me/s/ validation (channels with web preview yield real signals)
      - Dynamic channel registry (telegram_intel_channels.json)
      - Hot-injects discovered channels into the running DarkWebCollector

    Tier 2 (requires Telethon setup):
      - Full MTProto access: join, read history, discover via Telegram search
      - Activated when TELEGRAM_API_ID and TELEGRAM_API_HASH are set
    """

    def __init__(
        self,
        brave_api_key: str = "",
        api_id: int = 0,
        api_hash: str = "",
        session_name: str = ".telegram_session",
        dark_collector: Any | None = None,  # DarkWebCollector instance for hot-reload
        dirty_pool: Any | None = None,       # DirtyPool for direct signal injection
    ):
        self.brave_api_key = brave_api_key
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.dark_collector = dark_collector  # wired in api.py after init
        self.dirty_pool = dirty_pool          # wired in api.py after init

        # Tier 2 state
        self._telethon_available = bool(api_id and api_hash)
        self._telethon_client: Any = None
        self._telethon_lock = threading.Lock()

        # Runtime stats
        self._searches_performed = 0
        self._channels_discovered = 0
        self._channels_added = 0

        logger.info(
            "[TelegramIntel] Initialized — tier1=active, tier2=%s",
            "available (run _setup_telegram_session.py first)" if self._telethon_available else "inactive (no API ID/hash)",
        )

    # ── Tier 1: Discovery via web search ──────────────────────────────────────

    def search_channels(
        self,
        query: str,
        limit: int = 10,
    ) -> dict:
        """Search for Telegram channels related to a topic.

        Uses Brave Search API to find t.me links, then validates each
        candidate with a t.me/s/ check. Returns channels with working
        web preview (meaning signals can be collected from them).

        Args:
            query: Natural language query, e.g. "hacktivist DDoS Russia NATO"
            limit: Max channels to validate and return

        Returns:
            dict with keys: query, candidates_found, working_channels, already_monitored
        """
        self._searches_performed += 1
        logger.info("[TelegramIntel] Searching channels for: '%s'", query[:100])

        candidate_handles: list[str] = []

        # Step 1: Web search for Telegram channels
        search_queries = [
            f"telegram channel {query} t.me",
            f"site:t.me {query}",
            f"telegram {query} threat intelligence channel",
        ]

        if self.brave_api_key:
            for sq in search_queries[:2]:  # limit API calls
                handles = self._brave_search(sq)
                candidate_handles.extend(handles)
                if len(candidate_handles) >= _MAX_CHANNELS_PER_SEARCH:
                    break
        else:
            # Fallback: DuckDuckGo HTML scrape (no API key needed)
            for sq in search_queries[:2]:
                handles = self._duckduckgo_search(sq)
                candidate_handles.extend(handles)
                if len(candidate_handles) >= _MAX_CHANNELS_PER_SEARCH:
                    break

        # Deduplicate
        seen: set[str] = set()
        unique_handles: list[str] = []
        for h in candidate_handles:
            if h.lower() not in seen:
                seen.add(h.lower())
                unique_handles.append(h)

        unique_handles = unique_handles[:_MAX_CHANNELS_PER_SEARCH]
        logger.info("[TelegramIntel] Validating %d candidate handles...", len(unique_handles))

        # Step 2: Validate each handle
        existing_channels = _load_channels()
        working: list[dict] = []
        already_monitored: list[str] = []

        with httpx.Client(headers={"User-Agent": _UA}, follow_redirects=False, timeout=15) as client:
            for handle in unique_handles[:limit * 3]:  # check more to find limit working ones
                if handle.lower() in {k.lower() for k in existing_channels}:
                    already_monitored.append(handle)
                    continue

                has_preview, msg_count = _has_web_preview(handle, client)
                if has_preview:
                    working.append({
                        "handle": handle,
                        "url": f"https://t.me/s/{handle}",
                        "message_count_visible": msg_count,
                        "web_preview": True,
                    })
                    self._channels_discovered += 1
                    logger.info("[TelegramIntel] ✓ %s — %d messages visible", handle, msg_count)
                    if len(working) >= limit:
                        break
                else:
                    logger.debug("[TelegramIntel] ✗ %s — no web preview", handle)

        return {
            "query": query,
            "candidates_tested": len(unique_handles),
            "working_channels": working,
            "already_monitored": already_monitored,
            "summary": (
                f"Found {len(working)} Telegram channels with active web preview "
                f"for query '{query}'. "
                + (f"{len(already_monitored)} were already being monitored. " if already_monitored else "")
                + (
                    f"Channels: {', '.join('@' + c['handle'] for c in working[:5])}"
                    if working else "No channels with web preview found — these channels may have disabled public preview."
                )
            ),
        }

    def add_channel(self, handle: str, reason: str = "") -> dict:
        """Add a Telegram channel to the live monitoring list.

        Validates the channel first. If it has web preview, adds it to
        telegram_intel_channels.json and hot-reloads into DarkWebCollector.

        Returns dict with status and details.
        """
        handle = handle.lstrip("@").strip()
        if not handle:
            return {"status": "error", "message": "No channel handle provided"}

        existing = _load_channels()
        if handle.lower() in {k.lower() for k in existing}:
            return {
                "status": "already_monitored",
                "handle": handle,
                "message": f"@{handle} is already in the monitoring list.",
            }

        if len(existing) >= _MAX_MONITORED_CHANNELS:
            return {
                "status": "error",
                "message": f"Monitoring list is at capacity ({_MAX_MONITORED_CHANNELS}). Remove a channel first.",
            }

        # Validate
        with httpx.Client(headers={"User-Agent": _UA}, follow_redirects=False, timeout=15) as client:
            has_preview, msg_count = _has_web_preview(handle, client)

        if not has_preview:
            return {
                "status": "no_preview",
                "handle": handle,
                "message": (
                    f"@{handle} does not have a public web preview enabled "
                    f"(t.me/s/{handle} redirects). Cannot collect signals from it "
                    f"via Tier 1. Tier 2 (Telethon) would be needed to access this channel."
                ),
            }

        # Add to registry
        existing[handle] = {
            "handle": handle,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "added_by": "Αίολος (TelegramIntelTool)",
            "reason": reason or "Autonomous discovery",
            "messages_at_discovery": msg_count,
            "tier": 1,
        }
        _save_channels(existing)
        self._channels_added += 1

        # Hot-reload into running DarkWebCollector
        if self.dark_collector is not None:
            try:
                if handle not in self.dark_collector._dynamic_channels:
                    self.dark_collector._dynamic_channels.append(handle)
                    logger.info(
                        "[TelegramIntel] Hot-reloaded @%s into DarkWebCollector", handle
                    )
            except Exception as exc:
                logger.warning("[TelegramIntel] Hot-reload failed: %s", exc)

        logger.info("[TelegramIntel] Added @%s to monitoring (%d messages visible)", handle, msg_count)
        return {
            "status": "added",
            "handle": handle,
            "messages_visible": msg_count,
            "message": (
                f"@{handle} added to monitoring. {msg_count} messages currently visible via web preview. "
                f"DarkWebCollector will scrape it in the next cycle."
            ),
        }

    def remove_channel(self, handle: str) -> dict:
        """Remove a channel from the monitoring list."""
        handle = handle.lstrip("@").strip()
        channels = _load_channels()
        if handle.lower() not in {k.lower() for k in channels}:
            return {"status": "not_found", "handle": handle, "message": f"@{handle} is not in the monitoring list."}

        # Find exact key (case-insensitive)
        actual_key = next(k for k in channels if k.lower() == handle.lower())
        del channels[actual_key]
        _save_channels(channels)

        # Hot-remove from collector
        if self.dark_collector is not None:
            try:
                if actual_key in self.dark_collector._dynamic_channels:
                    self.dark_collector._dynamic_channels.remove(actual_key)
            except Exception:
                pass

        return {"status": "removed", "handle": actual_key, "message": f"@{actual_key} removed from monitoring."}

    def list_monitored(self) -> dict:
        """Return the current list of dynamically monitored channels."""
        channels = _load_channels()
        return {
            "count": len(channels),
            "channels": list(channels.values()),
            "summary": (
                f"Monitoring {len(channels)} dynamically-added Telegram channels: "
                + ", ".join(f"@{h}" for h in channels)
                if channels else "No dynamically-added channels yet."
            ),
        }

    def read_channel_preview(self, handle: str, limit: int = 20) -> dict:
        """Read recent messages from a channel's public web preview.

        Returns the most recent messages visible via t.me/s/{handle}.
        """
        handle = handle.lstrip("@").strip()
        url = f"https://t.me/s/{handle}"

        with httpx.Client(headers={"User-Agent": _UA}, follow_redirects=False, timeout=20) as client:
            try:
                r = client.get(url, timeout=20)
                if r.status_code != 200:
                    return {
                        "status": "error",
                        "handle": handle,
                        "message": f"HTTP {r.status_code} — channel may not have web preview.",
                    }

                # Extract messages
                msg_blocks = re.findall(
                    r'<div[^>]+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                    r.text,
                    re.DOTALL | re.IGNORECASE,
                )
                # Extract timestamps
                times = re.findall(r'<time[^>]+datetime="([^"]+)"', r.text)

                messages = []
                for i, block in enumerate(msg_blocks[:limit]):
                    text = re.sub(r"<[^>]+>", " ", block)
                    import html as htmllib
                    text = htmllib.unescape(re.sub(r"\s+", " ", text)).strip()
                    if len(text) < 10:
                        continue
                    messages.append({
                        "text": text,
                        "timestamp": times[i] if i < len(times) else "",
                    })

                return {
                    "status": "ok",
                    "handle": handle,
                    "messages_found": len(messages),
                    "messages": messages,
                    "summary": (
                        f"@{handle}: {len(messages)} messages read from web preview.\n"
                        + "\n".join(f"  [{m.get('timestamp', '')[:16]}] {m['text'][:120]}" for m in messages[:5])
                    ),
                }
            except Exception as exc:
                return {"status": "error", "handle": handle, "message": str(exc)}

    # ── Tier 2: Telethon ──────────────────────────────────────────────────────

    def telethon_search_channels(self, query: str, limit: int = 10) -> dict:
        """Search channels via Telegram MTProto API (requires Telethon setup).

        This uses Telegram's native search — finds channels that don't
        have web preview but are publicly searchable within Telegram.
        """
        if not self._telethon_available:
            return {
                "status": "tier2_unavailable",
                "message": (
                    "Tier 2 (Telethon) is not configured. "
                    "To enable: add TELEGRAM_API_ID and TELEGRAM_API_HASH to .env, "
                    "then run _setup_telegram_session.py to create a session."
                ),
            }
        try:
            from telethon import TelegramClient
            from telethon.tl.functions.contacts import SearchRequest
        except ImportError:
            return {
                "status": "tier2_unavailable",
                "message": "telethon is not installed. Run: pip install telethon",
            }

        async def _search():
            client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                return {"status": "error", "message": "Session not authorized. Run _setup_telegram_session.py"}
            result = await client(SearchRequest(q=query, limit=limit))
            channels = []
            for chat in result.chats:
                channels.append({
                    "id": getattr(chat, "id", 0),
                    "username": getattr(chat, "username", "") or "",
                    "title": getattr(chat, "title", ""),
                    "participants_count": getattr(chat, "participants_count", 0),
                    "verified": getattr(chat, "verified", False),
                })
            await client.disconnect()
            return {"status": "ok", "results": channels}

        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_search())
            loop.close()
            return result
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def telethon_read_channel(self, handle: str, limit: int = 50) -> dict:
        """Read messages from a channel via Telegram MTProto (requires Telethon).

        Unlike web preview (max ~20 messages), Telethon can read full history.
        Results are injected directly into DirtyPool.
        """
        if not self._telethon_available:
            return {
                "status": "tier2_unavailable",
                "message": "Configure TELEGRAM_API_ID and TELEGRAM_API_HASH to enable Tier 2.",
            }
        try:
            from telethon import TelegramClient
        except ImportError:
            return {"status": "tier2_unavailable", "message": "pip install telethon"}

        handle = handle.lstrip("@").strip()

        async def _read():
            client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                return {"status": "error", "message": "Not authorized. Run _setup_telegram_session.py"}
            messages = []
            async for msg in client.iter_messages(handle, limit=limit):
                if msg.text:
                    messages.append({
                        "id": msg.id,
                        "text": msg.text,
                        "date": msg.date.isoformat() if msg.date else "",
                        "views": getattr(msg, "views", 0) or 0,
                    })
            await client.disconnect()
            return {"status": "ok", "handle": handle, "messages": messages}

        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_read())
            loop.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

        # Inject into DirtyPool
        if result.get("status") == "ok" and self.dirty_pool:
            from xdart.perception.darkweb import DarkSignal
            from datetime import timezone as _tz
            injected = 0
            for msg in result.get("messages", []):
                text = (msg.get("text") or "").strip()
                if len(text) < 20:
                    continue
                sig = DarkSignal(
                    text=f"[Telegram:{handle}] {text}",
                    source_url=f"https://t.me/{handle}/{msg.get('id', 0)}",
                    source_type="telegram",
                    channel_name=handle,
                    collected_at=datetime.now(_tz.utc).isoformat(),
                    published_at=msg.get("date", datetime.now(_tz.utc).isoformat()),
                    raw_credibility=0.30,
                )
                if self.dirty_pool.insert(sig):
                    injected += 1
            result["injected_to_pool"] = injected
            logger.info("[TelegramIntel] Tier2: @%s — %d messages → %d injected to dirty pool", handle, len(result["messages"]), injected)

        return result

    # ── Web search helpers ─────────────────────────────────────────────────────

    def _brave_search(self, query: str) -> list[str]:
        """Search via Brave API and extract Telegram handles."""
        if not self.brave_api_key:
            return []
        try:
            from urllib.parse import quote_plus
            resp = httpx.get(
                f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count=10",
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.brave_api_key,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = data.get("web", {}).get("results", [])
            handles = []
            for r in results:
                text = f"{r.get('url', '')} {r.get('title', '')} {r.get('description', '')}"
                handles.extend(_extract_handles_from_text(text))
            return handles
        except Exception as exc:
            logger.debug("[TelegramIntel] Brave search failed: %s", exc)
            return []

    def _duckduckgo_search(self, query: str) -> list[str]:
        """Fallback search via DuckDuckGo HTML scrape."""
        try:
            from urllib.parse import quote_plus
            resp = httpx.get(
                f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
                headers={
                    "User-Agent": _UA,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return []
            return _extract_handles_from_text(resp.text)
        except Exception as exc:
            logger.debug("[TelegramIntel] DDG search failed: %s", exc)
            return []

    # ── Status for context injection ──────────────────────────────────────────

    def to_context_string(self) -> str:
        """Return a status block for injection into Αίολος' context."""
        channels = _load_channels()
        tier2_status = (
            "AVAILABLE — TELEGRAM_API_ID configured (run _setup_telegram_session.py to activate)"
            if self._telethon_available
            else "INACTIVE — add TELEGRAM_API_ID + TELEGRAM_API_HASH to .env to enable"
        )
        lines = [
            "TELEGRAM INTELLIGENCE TOOL:",
            f"  Tier 1 (web preview): ACTIVE",
            f"  Tier 2 (Telethon MTProto): {tier2_status}",
            f"  Dynamic channels monitored: {len(channels)}"
            + (f" — {', '.join('@' + h for h in list(channels)[:5])}" if channels else ""),
            f"  Searches performed: {self._searches_performed}",
            f"  Channels discovered: {self._channels_discovered}",
            f"  Channels added: {self._channels_added}",
            "",
            "  TO USE — emit XML tags in your response:",
            '    <TELEGRAM_INTEL action="search" query="hacktivist DDoS NATO" />',
            '    <TELEGRAM_INTEL action="add" channel="handle" reason="why" />',
            '    <TELEGRAM_INTEL action="read" channel="handle" limit="20" />',
            '    <TELEGRAM_INTEL action="list" />',
            '    <TELEGRAM_INTEL action="remove" channel="handle" />',
        ]
        return "\n".join(lines)

    def get_stats(self) -> dict:
        channels = _load_channels()
        return {
            "monitored_count": len(channels),
            "searches_performed": self._searches_performed,
            "channels_discovered": self._channels_discovered,
            "channels_added": self._channels_added,
            "tier1_active": True,
            "tier2_available": self._telethon_available,
            "channels_file": str(_CHANNELS_FILE),
        }
