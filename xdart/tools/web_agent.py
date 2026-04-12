"""
XDART-Φ × XHEART — Web Agent

Gives Αίολος eyes and hands on the web:
  - web_search()    → Search the web (DuckDuckGo, no API key needed)
  - web_browse()    → Navigate to URL, render JS, extract content
  - web_scrape()    → Extract specific data from a page with CSS selectors
  - web_extract()   → Smart extraction: main text + metadata from any URL

Architecture:
  Layer 1: httpx + BeautifulSoup (fast, no JS — for static pages)
  Layer 2: Lightpanda CDP / Playwright (full JS rendering — for SPAs)

  Lightpanda (Docker): docker run -d --name lightpanda -p 9222:9222 lightpanda/browser:nightly
  Fallback: Playwright's built-in Chromium

All results are returned as structured dicts ready for memory storage.

© Panos Skouras — Salimov MON IKE, 2026
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Comment

logger = logging.getLogger("xdart.web_agent")

# ── Hard limits (prevent abuse / runaway) ──
MAX_CONTENT_LENGTH = 200_000     # 200KB max page content
MAX_SEARCH_RESULTS = 10
BROWSE_TIMEOUT = 30              # seconds
SCRAPE_TIMEOUT = 20


class WebAgent:
    """Web browsing and search agent for Αίολος.

    Uses httpx + BeautifulSoup for static pages (fast, lightweight).
    Uses CDP (Lightpanda or Playwright) for JS-heavy pages when available.
    """

    def __init__(
        self,
        lightpanda_cdp_url: str = "",
        user_agent: str = "XDART-Phi/1.0 (research-agent; +https://github.com)",
        respect_robots: bool = True,
    ):
        self.lightpanda_cdp_url = lightpanda_cdp_url
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self._cdp_available: bool | None = None     # lazy check
        self._playwright = None                      # lazy init
        self._browser = None
        self._http_client: httpx.AsyncClient | None = None
        self._http_loop: asyncio.AbstractEventLoop | None = None  # track which loop owns the client
        # Search result cache — avoid redundant queries within TTL
        self._search_cache: dict[str, tuple[float, dict]] = {}  # normalised_query → (ts, result)
        self._search_cache_ttl = 86400  # 24 hours

    # ── Lifecycle ──

    async def _get_http(self) -> httpx.AsyncClient:
        """Lazy-init shared httpx client, recreating if the event loop changed."""
        current_loop = asyncio.get_running_loop()
        needs_new = (
            self._http_client is None
            or self._http_client.is_closed
            or self._http_loop is not current_loop
        )
        if needs_new:
            # Close stale client from previous loop (best-effort)
            if self._http_client and not self._http_client.is_closed:
                try:
                    await self._http_client.aclose()
                except Exception:
                    pass
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(BROWSE_TIMEOUT),
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10),
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,el;q=0.8",
                },
            )
            self._http_loop = current_loop
        return self._http_client

    async def _check_cdp(self) -> bool:
        """Check if Lightpanda/CDP is reachable."""
        if self._cdp_available is not None:
            return self._cdp_available

        if not self.lightpanda_cdp_url:
            self._cdp_available = False
            return False

        try:
            # CDP exposes /json/version on HTTP
            http_url = self.lightpanda_cdp_url.replace("ws://", "http://").replace("wss://", "https://")
            http_url = http_url.rstrip("/")
            client = await self._get_http()
            resp = await client.get(f"{http_url}/json/version", timeout=5)
            self._cdp_available = resp.status_code == 200
            if self._cdp_available:
                logger.info("[WebAgent] Lightpanda CDP available at %s", self.lightpanda_cdp_url)
            return self._cdp_available
        except Exception:
            self._cdp_available = False
            logger.info("[WebAgent] CDP not available, using httpx fallback")
            return False

    async def _get_browser_page(self):
        """Get a Playwright page connected to CDP (Lightpanda or built-in)."""
        try:
            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            if self._browser is None or not self._browser.is_connected():
                if await self._check_cdp():
                    self._browser = await self._playwright.chromium.connect_over_cdp(
                        self.lightpanda_cdp_url
                    )
                    logger.info("[WebAgent] Connected to Lightpanda via CDP")
                else:
                    self._browser = await self._playwright.chromium.launch(headless=True)
                    logger.info("[WebAgent] Using Playwright built-in Chromium")

            context = await self._browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()
            return page, context
        except ImportError:
            logger.warning("[WebAgent] Playwright not installed — JS rendering unavailable")
            return None, None
        except Exception as exc:
            logger.warning("[WebAgent] Browser creation failed: %s", exc)
            return None, None

    async def close(self):
        """Cleanup resources."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    # ══════════════════════════════════════════════════════════════════
    #  WEB SEARCH — Multi-engine: SearXNG → Brave → DuckDuckGo
    # ══════════════════════════════════════════════════════════════════

    async def web_search(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
    ) -> dict:
        """Search the web using multiple engines with automatic fallback.

        Engine priority is configured via SEARCH_ENGINE_ORDER in config.
        Default: SearXNG (self-hosted) → Brave Search API → DuckDuckGo.

        Args:
            query: Search query.
            max_results: Max results (1-10).
            region: Region code (wt-wt=worldwide, gr-el=Greece, us-en=US).

        Returns:
            dict with keys: query, results[], timestamp, source
        """
        from xdart.config import SEARCH_ENGINE_ORDER, SEARXNG_URL, BRAVE_SEARCH_API_KEY

        max_results = min(max_results, MAX_SEARCH_RESULTS)
        start = time.time()
        logger.info("[WebAgent] Search: %s (max=%d)", query[:80], max_results)

        # ── Cache check: return cached result if query was searched within TTL ──
        cache_key = query.strip().lower()
        now = time.time()
        if cache_key in self._search_cache:
            cached_ts, cached_result = self._search_cache[cache_key]
            if now - cached_ts < self._search_cache_ttl:
                cached_result["from_cache"] = True
                logger.info("[WebAgent] Search CACHE HIT for '%s' (%.0fh ago, %d results)",
                            query[:60], (now - cached_ts) / 3600, cached_result.get("count", 0))
                return cached_result

        # Prune expired cache entries (keep memory bounded)
        self._search_cache = {
            k: v for k, v in self._search_cache.items()
            if now - v[0] < self._search_cache_ttl
        }

        # Build engine dispatch table
        engines = {
            "searxng": lambda: self._search_searxng(query, max_results, SEARXNG_URL),
            "brave": lambda: self._search_brave(query, max_results, BRAVE_SEARCH_API_KEY),
            "duckduckgo": lambda: self._search_duckduckgo(query, max_results, region),
        }

        # Parse ordered engine list
        order = [e.strip().lower() for e in SEARCH_ENGINE_ORDER.split(",") if e.strip()]
        # Filter: skip engines that aren't configured
        if not SEARXNG_URL:
            order = [e for e in order if e != "searxng"]
        if not BRAVE_SEARCH_API_KEY:
            order = [e for e in order if e != "brave"]
        if not order:
            order = ["duckduckgo"]  # always have at least DDG

        last_error = ""
        for engine_name in order:
            engine_fn = engines.get(engine_name)
            if not engine_fn:
                continue
            try:
                result = await engine_fn()
                if result.get("count", 0) > 0:
                    result["elapsed_seconds"] = round(time.time() - start, 2)
                    logger.info(
                        "[WebAgent] Search via %s returned %d results in %.1fs",
                        result.get("source", engine_name), result["count"],
                        result["elapsed_seconds"],
                    )
                    # Cache successful result
                    self._search_cache[cache_key] = (time.time(), result)
                    return result
                # 0 results — try next engine
                last_error = f"{engine_name}: 0 results"
                logger.warning("[WebAgent] %s returned 0 results, trying next engine", engine_name)
            except Exception as exc:
                last_error = f"{engine_name}: {exc}"
                logger.warning("[WebAgent] %s search failed: %s — trying next engine", engine_name, exc)

        # All engines exhausted
        elapsed = round(time.time() - start, 2)
        logger.error("[WebAgent] All search engines failed for: %s", query[:80])
        return {
            "query": query,
            "results": [],
            "count": 0,
            "error": last_error,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "error",
        }

    # ── SearXNG (self-hosted meta-search — recommended primary) ──

    async def _search_searxng(self, query: str, max_results: int, base_url: str) -> dict:
        """Search via SearXNG JSON API (self-hosted, no rate limits)."""
        client = await self._get_http()
        url = f"{base_url.rstrip('/')}/search"
        params = {
            "q": query,
            "format": "json",
            "categories": "general",
            "language": "en",
            "pageno": 1,
        }

        resp = await client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            })

        logger.info("[WebAgent] SearXNG returned %d results (engines: %s)",
                     len(results), ", ".join(data.get("engines", [])))

        return {
            "query": query,
            "results": results,
            "count": len(results),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "searxng",
        }

    # ── Brave Search API (free tier: 2000/month) ──

    async def _search_brave(self, query: str, max_results: int, api_key: str) -> dict:
        """Search via Brave Search API (reliable, free tier available)."""
        client = await self._get_http()
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
        params = {
            "q": query,
            "count": min(max_results, 20),
        }

        resp = await client.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("web", {}).get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
            })

        return {
            "query": query,
            "results": results,
            "count": len(results),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "brave",
        }

    # ── DuckDuckGo (no key needed — aggressive rate-limiting) ──

    async def _search_duckduckgo(self, query: str, max_results: int, region: str) -> dict:
        """Search via DuckDuckGo DDGS library + HTML fallback."""
        # Try DDGS library with retry (handles 202 rate limits)
        last_exc = None
        for attempt in range(3):
            try:
                from duckduckgo_search import DDGS

                with DDGS() as ddgs:
                    raw = list(ddgs.text(
                        query,
                        region=region,
                        max_results=max_results,
                    ))

                results = []
                for r in raw:
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", r.get("link", "")),
                        "snippet": r.get("body", r.get("snippet", "")),
                    })

                return {
                    "query": query,
                    "results": results,
                    "count": len(results),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "duckduckgo",
                }

            except ImportError:
                logger.warning("[WebAgent] duckduckgo_search not installed, using HTML fallback")
                return await self._search_ddg_html(query, max_results)
            except Exception as exc:
                last_exc = exc
                is_ratelimit = "Ratelimit" in str(exc) or "202" in str(exc)
                if is_ratelimit and attempt < 2:
                    wait = 2 ** (attempt + 1)  # 2s, 4s
                    logger.warning(
                        "[WebAgent] DuckDuckGo rate-limited, retrying in %ds (attempt %d/3)",
                        wait, attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                break

        # DDGS failed — try HTML scrape fallback
        logger.warning("[WebAgent] DDGS failed after retries: %s — trying HTML fallback", last_exc)
        fallback = await self._search_ddg_html(query, max_results)
        if fallback.get("count", 0) > 0:
            return fallback

        # Propagate the error so the multi-engine loop can try the next engine
        raise RuntimeError(f"DuckDuckGo failed: {last_exc}")

    async def _search_ddg_html(self, query: str, max_results: int) -> dict:
        """Fallback search using DuckDuckGo HTML (no library needed)."""
        try:
            client = await self._get_http()
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            resp = await client.get(url)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []

            for item in soup.select(".result__body")[:max_results]:
                title_el = item.select_one(".result__a")
                snippet_el = item.select_one(".result__snippet")
                link_el = item.select_one(".result__url")

                title = title_el.get_text(strip=True) if title_el else ""
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                href = ""
                if title_el and title_el.get("href"):
                    href = title_el["href"]
                elif link_el:
                    href = link_el.get_text(strip=True)

                if title:
                    results.append({"title": title, "url": href, "snippet": snippet})

            return {
                "query": query,
                "results": results,
                "count": len(results),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "duckduckgo_html",
            }
        except Exception as exc:
            return {
                "query": query,
                "results": [],
                "count": 0,
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "error",
            }

    # ══════════════════════════════════════════════════════════════════
    #  WEB BROWSE (full page fetch + content extraction)
    # ══════════════════════════════════════════════════════════════════

    async def web_browse(
        self,
        url: str,
        use_js: bool = False,
        wait_for: str | None = None,
    ) -> dict:
        """Navigate to URL and extract the page content.

        Args:
            url: Target URL.
            use_js: Force JS rendering via CDP/Playwright.
            wait_for: CSS selector to wait for (only with JS rendering).

        Returns:
            dict with: url, title, text, links[], metadata, timestamp
        """
        start = time.time()
        logger.info("[WebAgent] Browse: %s (js=%s)", url[:100], use_js)

        # Validate URL
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"url": url, "error": "Invalid URL scheme — must be http or https"}

        if use_js:
            result = await self._browse_with_js(url, wait_for)
        else:
            result = await self._browse_static(url)

        result["elapsed_seconds"] = round(time.time() - start, 2)
        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        return result

    async def _browse_static(self, url: str) -> dict:
        """Fetch and parse with httpx + BeautifulSoup (no JS)."""
        try:
            client = await self._get_http()
            resp = await client.get(url)
            resp.raise_for_status()

            # Check content length
            content = resp.text[:MAX_CONTENT_LENGTH]
            return self._parse_html(content, url)

        except httpx.HTTPStatusError as exc:
            return {"url": url, "error": f"HTTP {exc.response.status_code}"}
        except Exception as exc:
            return {"url": url, "error": str(exc)}

    async def _browse_with_js(self, url: str, wait_for: str | None = None) -> dict:
        """Fetch with full JS rendering via CDP/Playwright."""
        page, context = await self._get_browser_page()
        if page is None:
            logger.warning("[WebAgent] JS rendering unavailable, falling back to static")
            return await self._browse_static(url)

        try:
            await page.goto(url, wait_until="networkidle", timeout=BROWSE_TIMEOUT * 1000)

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=10_000)

            content = await page.content()
            content = content[:MAX_CONTENT_LENGTH]
            result = self._parse_html(content, url)
            result["js_rendered"] = True
            return result

        except Exception as exc:
            return {"url": url, "error": f"JS browse failed: {exc}", "js_rendered": True}
        finally:
            try:
                await page.close()
                if context:
                    await context.close()
            except Exception:
                pass

    def _parse_html(self, html: str, url: str) -> dict:
        """Parse HTML into structured content."""
        soup = BeautifulSoup(html, "html.parser")

        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        # Title
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        # Meta description
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag:
            meta_desc = meta_tag.get("content", "")

        # Main text content
        # Try article/main first, then body
        main_el = soup.find("article") or soup.find("main") or soup.find("body")
        text = ""
        if main_el:
            text = main_el.get_text(separator="\n", strip=True)
            # Clean up excessive whitespace
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = text[:50_000]  # Cap text at 50K chars

        # Extract links
        links = []
        for a in soup.find_all("a", href=True)[:50]:
            href = a["href"]
            if href.startswith(("javascript:", "#", "mailto:")):
                continue
            abs_url = urljoin(url, href)
            link_text = a.get_text(strip=True)[:100]
            if link_text:
                links.append({"text": link_text, "url": abs_url})

        # Extract headings for structure
        headings = []
        for h in soup.find_all(["h1", "h2", "h3"])[:20]:
            headings.append({
                "level": int(h.name[1]),
                "text": h.get_text(strip=True)[:150],
            })

        return {
            "url": url,
            "title": title,
            "description": meta_desc,
            "text": text,
            "text_length": len(text),
            "headings": headings,
            "links": links[:30],
            "link_count": len(links),
        }

    # ══════════════════════════════════════════════════════════════════
    #  WEB SCRAPE (targeted extraction)
    # ══════════════════════════════════════════════════════════════════

    async def web_scrape(
        self,
        url: str,
        selectors: dict[str, str] | None = None,
        extract_tables: bool = False,
        use_js: bool = False,
    ) -> dict:
        """Scrape specific data from a page using CSS selectors.

        Args:
            url: Target URL.
            selectors: Dict of {name: css_selector} to extract.
                       e.g. {"title": "h1", "price": ".price-tag", "paragraphs": "article p"}
            extract_tables: If True, also extract all HTML tables as dicts.
            use_js: Force JS rendering.

        Returns:
            dict with: url, extracted{}, tables[], timestamp
        """
        start = time.time()
        logger.info("[WebAgent] Scrape: %s (selectors=%s, tables=%s)", url[:80], bool(selectors), extract_tables)

        # Get the page HTML
        if use_js:
            page_data = await self._browse_with_js(url)
        else:
            page_data = await self._browse_static(url)

        if "error" in page_data:
            return {"url": url, "error": page_data["error"]}

        # Re-parse for extraction (we need original HTML, not stripped)
        try:
            client = await self._get_http()
            if use_js:
                # Already browsed, use page_data text
                html = page_data.get("text", "")
                soup = BeautifulSoup(f"<body>{html}</body>", "html.parser")
            else:
                resp = await client.get(url)
                soup = BeautifulSoup(resp.text[:MAX_CONTENT_LENGTH], "html.parser")
        except Exception:
            soup = BeautifulSoup(f"<body>{page_data.get('text', '')}</body>", "html.parser")

        result = {
            "url": url,
            "title": page_data.get("title", ""),
            "extracted": {},
            "tables": [],
            "elapsed_seconds": round(time.time() - start, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Extract by selectors
        if selectors:
            for name, selector in selectors.items():
                try:
                    elements = soup.select(selector)
                    if len(elements) == 1:
                        result["extracted"][name] = elements[0].get_text(strip=True)
                    elif elements:
                        result["extracted"][name] = [
                            el.get_text(strip=True) for el in elements[:20]
                        ]
                    else:
                        result["extracted"][name] = None
                except Exception as exc:
                    result["extracted"][name] = f"selector_error: {exc}"

        # Extract tables
        if extract_tables:
            for table in soup.find_all("table")[:5]:
                rows = []
                headers = []
                for th in table.find_all("th"):
                    headers.append(th.get_text(strip=True))
                for tr in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td"])]
                    if cells:
                        if headers and len(cells) == len(headers):
                            rows.append(dict(zip(headers, cells)))
                        else:
                            rows.append(cells)
                if rows:
                    result["tables"].append({
                        "headers": headers,
                        "rows": rows[:50],
                        "row_count": len(rows),
                    })

        return result

    # ══════════════════════════════════════════════════════════════════
    #  WEB EXTRACT (smart content extraction)
    # ══════════════════════════════════════════════════════════════════

    async def web_extract(self, url: str, use_js: bool = False) -> dict:
        """Smart extraction: main article text + structured metadata.

        Good for news articles, blog posts, research pages.
        Attempts to find the main content and strip navigation/ads.

        Returns:
            dict with: url, title, author, date, content, word_count, summary_ready
        """
        logger.info("[WebAgent] Extract: %s", url[:100])

        page_data = await self.web_browse(url, use_js=use_js)
        if "error" in page_data:
            return page_data

        # Try to get original HTML for metadata extraction
        try:
            client = await self._get_http()
            resp = await client.get(url)
            soup = BeautifulSoup(resp.text[:MAX_CONTENT_LENGTH], "html.parser")
        except Exception:
            soup = BeautifulSoup(f"<body>{page_data.get('text', '')}</body>", "html.parser")

        # Extract metadata
        author = ""
        date = ""

        # Author
        for meta_name in ["author", "article:author", "dc.creator"]:
            meta = soup.find("meta", attrs={"name": meta_name}) or \
                   soup.find("meta", attrs={"property": meta_name})
            if meta and meta.get("content"):
                author = meta["content"]
                break

        # Date
        for meta_name in ["article:published_time", "date", "pubdate", "dc.date"]:
            meta = soup.find("meta", attrs={"name": meta_name}) or \
                   soup.find("meta", attrs={"property": meta_name})
            if meta and meta.get("content"):
                date = meta["content"]
                break
        if not date:
            time_el = soup.find("time")
            if time_el and time_el.get("datetime"):
                date = time_el["datetime"]

        text = page_data.get("text", "")
        word_count = len(text.split())

        return {
            "url": url,
            "title": page_data.get("title", ""),
            "author": author,
            "date": date,
            "description": page_data.get("description", ""),
            "content": text,
            "word_count": word_count,
            "headings": page_data.get("headings", []),
            "links": page_data.get("links", [])[:10],
            "elapsed_seconds": page_data.get("elapsed_seconds", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary_ready": word_count > 50,
        }

    # ══════════════════════════════════════════════════════════════════
    #  SEARCH + READ (compound: search → browse top results)
    # ══════════════════════════════════════════════════════════════════

    async def search_and_read(
        self,
        query: str,
        max_results: int = 3,
        max_content_per_page: int = 5000,
    ) -> dict:
        """Search the web and read the top results.

        This is the primary intelligence-gathering tool.

        Args:
            query: Search query.
            max_results: How many top results to read (1-5).
            max_content_per_page: Max chars per page content.

        Returns:
            dict with: query, results_read[], total_content_chars, timestamp
        """
        max_results = min(max_results, 5)
        start = time.time()
        logger.info("[WebAgent] Search+Read: %s (top %d)", query[:80], max_results)

        # Step 1: Search
        search = await self.web_search(query, max_results=max_results + 2)
        urls = [r["url"] for r in search.get("results", []) if r.get("url")][:max_results]

        if not urls:
            return {
                "query": query,
                "results_read": [],
                "error": "No search results found",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Step 2: Read each result
        results_read = []
        total_chars = 0

        for url in urls:
            try:
                page = await self.web_browse(url)
                content = page.get("text", "")[:max_content_per_page]
                results_read.append({
                    "url": url,
                    "title": page.get("title", ""),
                    "content": content,
                    "word_count": len(content.split()),
                })
                total_chars += len(content)
            except Exception as exc:
                results_read.append({
                    "url": url,
                    "title": "",
                    "content": "",
                    "error": str(exc),
                })

        elapsed = round(time.time() - start, 2)
        logger.info(
            "[WebAgent] Search+Read complete: %d pages, %d chars in %.1fs",
            len(results_read), total_chars, elapsed,
        )

        return {
            "query": query,
            "results_read": results_read,
            "pages_read": len(results_read),
            "total_content_chars": total_chars,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ══════════════════════════════════════════════════════════════════
    #  CAPABILITY SUMMARY (for identity injection)
    # ══════════════════════════════════════════════════════════════════

    def capability_summary(self) -> str:
        """Return a description of web agent capabilities for identity context."""
        cdp_status = "Lightpanda CDP configured" if self.lightpanda_cdp_url else "httpx only (no JS rendering)"
        from xdart.config import SEARCH_ENGINE_ORDER
        engines = SEARCH_ENGINE_ORDER
        return (
            "WEB AGENT CAPABILITIES (you CAN use these):\n"
            f"- web_search(query): Search the web via multi-engine ({engines}). Returns titles, URLs, snippets.\n"
            "- web_browse(url): Navigate to any URL, extract text content, headings, links.\n"
            "- web_scrape(url, selectors): Extract specific data with CSS selectors.\n"
            "- web_extract(url): Smart article extraction (author, date, content, metadata).\n"
            "- search_and_read(query): Combined search + read top results for deep research.\n"
            f"- JS rendering: {cdp_status}\n"
            "- You can search for current events, read news articles, check data sources,\n"
            "  verify claims against live web content, and gather intelligence from any public website.\n"
            "- When a user asks about something current, you can search the web to supplement your knowledge.\n"
            "- When you need to verify a prediction or check a prophecy, you can look it up.\n"
        )
