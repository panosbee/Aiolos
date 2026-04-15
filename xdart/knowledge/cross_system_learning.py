"""
XDART-Φ × XHEART — Cross-system Learning

Automated knowledge ingestion from external AI/research systems.
Αίολος can read and integrate knowledge from:
  1. arXiv — preprint research papers (physics, CS, economics, quant-ph)
  2. OpenAlex — 248M+ works, citations, topics (free, no key, 100K req/day)
  3. SSRN — social science / economics / finance working papers
  4. CORE — open access research aggregator (130M+ papers)

Architecture:
  - Runs on a daily schedule (or triggered by curiosity)
  - Queries are derived from: active curiosity topics, recent patterns,
    and configured research interests
  - Papers are summarized via LLM, key findings stored in semantic memory
  - High-relevance papers trigger proactive notification

No manual web scraping needed — all through structured APIs.

Data Sources (all FREE):
  - arXiv: Free API, no key, unlimited queries
  - OpenAlex: Free API, no key, 100K req/day (polite pool with mailto)
  - CORE: Free API key required (15K papers/month)
  - SSRN: RSS feeds (free, structured)

© Panos Skouras — Salimov MON IKE, 2026
"""

import asyncio
import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger("xdart.knowledge.cross_system")

# ── Research domains aligned with XDART's analytical scope ──
DEFAULT_RESEARCH_INTERESTS = [
    # Geopolitical & strategic
    "geopolitical risk assessment",
    "international conflict prediction",
    "sanctions economic impact",
    "nuclear proliferation detection",
    # Economic & financial
    "systemic financial risk",
    "central bank policy prediction",
    "currency crisis early warning",
    "supply chain disruption modeling",
    # Technology & security
    "cyber warfare attribution",
    "AI autonomous weapons",
    "semiconductor supply chain",
    "infrastructure vulnerability assessment",
    # Methodology (improve Αίολος's own methods)
    "Bayesian inference geopolitics",
    "fuzzy logic risk assessment",
    "scenario planning methodology",
    "forecasting accuracy calibration",
]

# Max papers to process per source per cycle
MAX_PAPERS_PER_SOURCE = 10

# Cache: avoid re-reading same papers
PAPER_CACHE_PATH = "cross_system_cache.json"


class Paper:
    """A research paper from any source."""

    def __init__(
        self,
        title: str,
        authors: list[str],
        abstract: str,
        source: str,
        url: str,
        published: str = "",
        categories: list[str] | None = None,
        citation_count: int = 0,
        relevance_score: float = 0.0,
    ):
        self.title = title
        self.authors = authors
        self.abstract = abstract
        self.source = source
        self.url = url
        self.published = published
        self.categories = categories or []
        self.citation_count = citation_count
        self.relevance_score = relevance_score
        self.id = hashlib.md5(f"{source}:{title}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "authors": self.authors[:5],  # limit for storage
            "abstract": self.abstract[:1000],
            "source": self.source,
            "url": self.url,
            "published": self.published,
            "categories": self.categories,
            "citation_count": self.citation_count,
            "relevance_score": round(self.relevance_score, 3),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  arXiv API — Free, no key, structured XML responses
#  Best for: cutting-edge research in physics, CS, econ, math
# ══════════════════════════════════════════════════════════════════════════════

ARXIV_API_URL = "https://export.arxiv.org/api/query"

# arXiv categories relevant to XDART's analysis
ARXIV_CATEGORIES = [
    "cs.AI",        # Artificial Intelligence
    "cs.CY",        # Computers and Society
    "cs.CR",        # Cryptography and Security
    "econ.GN",      # General Economics
    "q-fin.RM",     # Risk Management
    "q-fin.EC",     # Economics (Quantitative Finance)
    "physics.soc-ph",  # Physics and Society
    "stat.ML",      # Machine Learning (Statistics)
]


async def search_arxiv(
    query: str,
    max_results: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[Paper]:
    """Search arXiv for papers matching a query."""
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=30)
        own_client = True

    try:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(max_results, MAX_PAPERS_PER_SOURCE),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        resp = await client.get(ARXIV_API_URL, params=params, follow_redirects=True)
        if resp.status_code != 200:
            logger.warning("[arXiv] Search failed (%d): %s", resp.status_code, query[:60])
            return []

        # Parse Atom XML
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        papers = []
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            published_el = entry.find("atom:published", ns)

            title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
            abstract = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""
            published = (published_el.text or "")[:10] if published_el is not None else ""

            authors = []
            for author_el in entry.findall("atom:author/atom:name", ns):
                if author_el.text:
                    authors.append(author_el.text.strip())

            # Get paper URL
            url = ""
            for link_el in entry.findall("atom:link", ns):
                if link_el.get("type") == "text/html":
                    url = link_el.get("href", "")
                    break
            if not url:
                id_el = entry.find("atom:id", ns)
                url = (id_el.text or "") if id_el is not None else ""

            categories = []
            for cat_el in entry.findall("atom:category", ns):
                term = cat_el.get("term", "")
                if term:
                    categories.append(term)

            if title and abstract:
                papers.append(Paper(
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    source="arxiv",
                    url=url,
                    published=published,
                    categories=categories,
                ))

        logger.info("[arXiv] Found %d papers for: %s", len(papers), query[:60])
        return papers

    except Exception as exc:
        logger.warning("[arXiv] Search error: %s", exc)
        return []
    finally:
        if own_client:
            await client.aclose()


# ══════════════════════════════════════════════════════════════════════════════
#  OPENALEX API — Free, open, no key required, generous rate limits
#  100K requests/day with polite pool (email in User-Agent)
#  248M+ works, citation counts, topics, open access status
#  Replaces Semantic Scholar (persistent 429 issues)
# ══════════════════════════════════════════════════════════════════════════════

OPENALEX_API_URL = "https://api.openalex.org"
OPENALEX_MAILTO = "xdart@protonmail.com"  # Polite pool: 100K/day vs 10K without


async def search_openalex(
    query: str,
    max_results: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[Paper]:
    """Search OpenAlex for academic papers.

    Free, no key, no auth. 100K req/day with mailto in params (polite pool).
    Returns papers with citations, authors, topics, open access links.
    """
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=30)
        own_client = True

    try:
        params = {
            "search": query,
            "per_page": min(max_results, MAX_PAPERS_PER_SOURCE),
            "select": "id,title,authorships,abstract_inverted_index,publication_year,"
                      "cited_by_count,topics,primary_location,doi",
            "mailto": OPENALEX_MAILTO,
        }
        resp = await client.get(
            f"{OPENALEX_API_URL}/works",
            params=params,
        )
        if resp.status_code == 429:
            logger.warning("[OpenAlex] Rate limited (429) — unusual, skipping")
            return []
        if resp.status_code != 200:
            logger.debug("[OpenAlex] Search failed (%d)", resp.status_code)
            return []

        data = resp.json()
        papers = []
        for item in data.get("results", []):
            title = item.get("title", "")
            if not title:
                continue

            # Reconstruct abstract from inverted index
            abstract = _reconstruct_openalex_abstract(
                item.get("abstract_inverted_index")
            )

            # Extract authors
            authors = []
            for authorship in (item.get("authorships") or []):
                author = authorship.get("author", {})
                name = author.get("display_name", "")
                if name:
                    authors.append(name)

            # Extract URL: prefer DOI, then OpenAlex landing page
            doi = item.get("doi") or ""
            primary_loc = item.get("primary_location") or {}
            landing_url = ""
            if primary_loc:
                source = primary_loc.get("source") or {}
                landing_url = primary_loc.get("landing_page_url", "")
            url = doi if doi else landing_url

            year = str(item.get("publication_year", ""))
            citations = item.get("cited_by_count", 0) or 0

            # Extract topic/field names
            fields = []
            for topic in (item.get("topics") or [])[:3]:
                display_name = topic.get("display_name", "")
                if display_name:
                    fields.append(display_name)

            papers.append(Paper(
                title=title,
                authors=authors[:5],
                abstract=abstract[:1000],
                source="openalex",
                url=url,
                published=year,
                categories=fields,
                citation_count=citations,
            ))

        logger.info("[OpenAlex] Found %d papers for: %s", len(papers), query[:60])
        return papers

    except Exception as exc:
        logger.warning("[OpenAlex] Search error: %s", exc)
        return []
    finally:
        if own_client:
            await client.aclose()


def _reconstruct_openalex_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract from OpenAlex inverted index format.

    OpenAlex stores abstracts as {word: [position_indices]} to save space.
    """
    if not inverted_index:
        return ""
    try:
        # Build (position, word) list and sort by position
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        return " ".join(w for _, w in word_positions)
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
#  CORE API — Open access research aggregator (130M+ papers)
#  Free API key: https://core.ac.uk/services/api
# ══════════════════════════════════════════════════════════════════════════════

CORE_API_URL = "https://api.core.ac.uk/v3"


async def search_core(
    query: str,
    api_key: str = "",
    max_results: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[Paper]:
    """Search CORE for open access papers.

    Works without API key (100 tokens/day, 10/min for unauth users).
    With key: 1000+ tokens/day depending on tier.
    Auth via Authorization: Bearer header.
    """

    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=30)
        own_client = True

    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = await client.get(
            f"{CORE_API_URL}/search/works",
            params={"q": query, "limit": min(max_results, MAX_PAPERS_PER_SOURCE)},
            headers=headers,
        )
        if resp.status_code != 200:
            logger.debug("[CORE] Search failed (%d)", resp.status_code)
            return []

        data = resp.json()
        papers = []
        for item in data.get("results", []):
            title = item.get("title", "")
            abstract = item.get("abstract", "") or ""
            if not title:
                continue

            authors = [
                a.get("name", "") for a in (item.get("authors") or [])
                if a.get("name")
            ]

            papers.append(Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                source="core",
                url=item.get("downloadUrl") or item.get("sourceFulltextUrls", [""])[0] if item.get("sourceFulltextUrls") else "",
                published=str(item.get("yearPublished", "")),
                categories=item.get("fieldOfStudy", "") if isinstance(item.get("fieldOfStudy"), list) else [],
            ))

        logger.info("[CORE] Found %d papers for: %s", len(papers), query[:60])
        return papers

    except Exception as exc:
        logger.warning("[CORE] Search error: %s", exc)
        return []
    finally:
        if own_client:
            await client.aclose()


# ══════════════════════════════════════════════════════════════════════════════
#  SSRN — Social Science Research Network (RSS-based discovery)
# ══════════════════════════════════════════════════════════════════════════════

SSRN_RSS_FEEDS = {
    "political_economy": "https://papers.ssrn.com/sol3/Jeljour.cfm?npage=1&rss=1&journalid=209",
    "international_economics": "https://papers.ssrn.com/sol3/Jeljour.cfm?npage=1&rss=1&journalid=200",
    "risk_management": "https://papers.ssrn.com/sol3/Jeljour.cfm?npage=1&rss=1&journalid=500",
    "geopolitics": "https://papers.ssrn.com/sol3/Jeljour.cfm?npage=1&rss=1&journalid=3218332",
}


async def fetch_ssrn_feeds(
    client: httpx.AsyncClient | None = None,
) -> list[Paper]:
    """Fetch recent papers from SSRN RSS feeds."""
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=30)
        own_client = True

    papers = []
    try:
        import feedparser

        for feed_name, feed_url in SSRN_RSS_FEEDS.items():
            try:
                resp = await client.get(feed_url, timeout=15)
                if resp.status_code != 200:
                    continue

                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:5]:
                    title = entry.get("title", "")
                    abstract = entry.get("summary", "") or entry.get("description", "")
                    url = entry.get("link", "")
                    published = entry.get("published", "")

                    # Clean HTML from abstract
                    abstract = re.sub(r"<[^>]+>", "", abstract).strip()

                    if title:
                        papers.append(Paper(
                            title=title,
                            authors=[a.get("name", "") for a in entry.get("authors", [])],
                            abstract=abstract[:1000],
                            source="ssrn",
                            url=url,
                            published=published[:10],
                            categories=[feed_name],
                        ))

            except Exception as exc:
                logger.debug("[SSRN] Feed %s failed: %s", feed_name, exc)

        logger.info("[SSRN] Found %d papers from %d feeds", len(papers), len(SSRN_RSS_FEEDS))

    except ImportError:
        logger.debug("[SSRN] feedparser not available — skipping SSRN feeds")
    except Exception as exc:
        logger.warning("[SSRN] Fetch error: %s", exc)
    finally:
        if own_client:
            await client.aclose()

    return papers


# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-SYSTEM LEARNING ENGINE
#  Orchestrates paper discovery, relevance scoring, summarization,
#  and knowledge integration.
# ══════════════════════════════════════════════════════════════════════════════

RELEVANCE_PROMPT = """You are a research paper relevance assessor for a geopolitical-financial intelligence system.

Given a paper title and abstract, assess its relevance to our analytical interests:
- Geopolitical risk, conflict prediction, international relations
- Financial systemic risk, currency crises, market disruptions
- Technology security (cyber, AI weapons, semiconductor supply chains)
- Analytical methodology (Bayesian inference, scenario planning, forecasting)
- Infrastructure vulnerability, supply chain disruption
- Cross-domain analysis (where geopolitics meets economics meets technology)

Return JSON:
{{
  "relevance_score": 0.0-1.0,
  "key_insights": ["insight1", "insight2", "insight3"],
  "applicable_to": ["domain1", "domain2"],
  "summary": "2-3 sentence summary of the paper's contribution"
}}
"""

SYNTHESIS_PROMPT = """You are a research synthesizer for Αίολος, a geopolitical-financial intelligence system.

Given {count} research papers, create a concise intelligence brief that:
1. Identifies the most important findings across all papers
2. Notes any methodological innovations Αίολος could adopt
3. Flags contradictions between papers (essential for balanced analysis)
4. Highlights cross-domain connections (geopolitics ↔ economics ↔ technology)

Write in a direct, analytical style. No fluff. Focus on actionable intelligence.

Papers:
{papers}

Generate a structured intelligence brief (max 500 words).
"""


class CrossSystemLearner:
    """Orchestrates knowledge acquisition from external research systems.

    Runs daily (or on-demand), queries multiple paper databases,
    scores relevance, summarizes findings, and stores in memory.
    """

    def __init__(
        self,
        llm: Any = None,
        core_api_key: str = "",
        s2_api_key: str = "",  # Legacy param — ignored (S2 replaced by OpenAlex)
        proactive_notify_fn: Callable | None = None,
        conversation_request_fn: Callable | None = None,
        memory_store_fn: Callable | None = None,
        cache_path: str = "",
    ):
        self.llm = llm
        self.core_api_key = core_api_key
        self.proactive_notify_fn = proactive_notify_fn
        self.conversation_request_fn = conversation_request_fn
        self.memory_store_fn = memory_store_fn
        self._cache_path = Path(cache_path) if cache_path else None
        self._seen_papers: set[str] = set()  # paper IDs already processed
        self._total_papers_ingested = 0
        self._total_papers_relevant = 0
        self._total_cycles = 0
        self._load_cache()

    def _load_cache(self):
        """Load previously seen paper IDs."""
        if self._cache_path and self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                self._seen_papers = set(data.get("seen_papers", []))
                self._total_papers_ingested = data.get("total_ingested", 0)
                self._total_papers_relevant = data.get("total_relevant", 0)
                logger.info("[CrossSystem] Cache loaded: %d known papers", len(self._seen_papers))
            except Exception:
                pass

    def _save_cache(self):
        """Persist seen paper IDs."""
        if not self._cache_path:
            return
        try:
            data = {
                "seen_papers": list(self._seen_papers)[-1000:],  # keep last 1000
                "total_ingested": self._total_papers_ingested,
                "total_relevant": self._total_papers_relevant,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            self._cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("[CrossSystem] Cache save failed: %s", exc)

    def _build_queries(
        self,
        curiosity_topics: list[str] | None = None,
        recent_patterns: list[str] | None = None,
    ) -> list[str]:
        """Generate search queries from active interests + dynamic context."""
        queries = []

        # Static research interests
        for interest in DEFAULT_RESEARCH_INTERESTS[:8]:
            queries.append(interest)

        # Dynamic: from curiosity engine's active topics
        if curiosity_topics:
            for topic in curiosity_topics[:5]:
                # Convert curiosity question to search query
                clean = re.sub(r"[?!.,]", "", topic)
                if len(clean.split()) <= 8:
                    queries.append(clean)
                else:
                    # Take most informative words
                    words = clean.split()
                    queries.append(" ".join(words[:6]))

        # Dynamic: from recent pattern topics
        if recent_patterns:
            for pattern_topic in recent_patterns[:3]:
                queries.append(f"{pattern_topic} analysis")

        # De-dup and limit
        seen_q = set()
        unique = []
        for q in queries:
            q_lower = q.lower().strip()
            if q_lower not in seen_q and len(q_lower) > 5:
                seen_q.add(q_lower)
                unique.append(q)
        return unique[:15]

    async def run_daily_cycle(
        self,
        curiosity_topics: list[str] | None = None,
        recent_patterns: list[str] | None = None,
    ) -> dict:
        """Main daily knowledge acquisition cycle.

        1. Generate queries from interests + context
        2. Search all paper databases
        3. De-dup and score relevance
        4. Summarize top papers
        5. Store findings in memory
        6. Notify if breakthrough found
        """
        self._total_cycles += 1
        logger.info("[CrossSystem] ═══ Daily cycle %d starting ═══", self._total_cycles)

        queries = self._build_queries(curiosity_topics, recent_patterns)
        if not queries:
            logger.info("[CrossSystem] No queries generated — skipping")
            return {"status": "no_queries"}

        # Phase 1: Collect papers from all sources
        all_papers = await self._collect_papers(queries)

        # Phase 2: De-dup against cache
        new_papers = [p for p in all_papers if p.id not in self._seen_papers]
        logger.info("[CrossSystem] %d papers total, %d new (after cache dedup)",
                    len(all_papers), len(new_papers))

        if not new_papers:
            return {"status": "no_new_papers", "total_found": len(all_papers)}

        # Phase 3: Score relevance via LLM
        scored = await self._score_relevance(new_papers)

        # Phase 4: Filter to relevant papers (score > 0.6)
        relevant = [p for p in scored if p.relevance_score >= 0.6]
        relevant.sort(key=lambda p: p.relevance_score, reverse=True)
        relevant = relevant[:10]

        logger.info("[CrossSystem] %d papers scored relevant (>0.6) out of %d",
                    len(relevant), len(scored))

        # Phase 5: Synthesize intelligence brief
        brief = ""
        if relevant and self.llm:
            brief = await self._synthesize_papers(relevant)

        # Phase 6: Store in memory
        if relevant and self.memory_store_fn:
            try:
                self.memory_store_fn(
                    layer="semantic",
                    content=brief or "\n".join(f"- {p.title}: {p.abstract[:200]}" for p in relevant[:5]),
                    tags=["cross_system_learning", "research_papers"],
                )
            except Exception as exc:
                logger.warning("[CrossSystem] Memory store failed: %s", exc)

        # Phase 7: Update cache
        for p in all_papers:
            self._seen_papers.add(p.id)
        self._total_papers_ingested += len(new_papers)
        self._total_papers_relevant += len(relevant)
        self._save_cache()

        # Phase 8: Notify about breakthrough papers
        breakthrough = [p for p in relevant if p.relevance_score >= 0.85]
        if breakthrough:
            self._notify_breakthrough(breakthrough, brief)

        result = {
            "status": "complete",
            "queries": len(queries),
            "total_found": len(all_papers),
            "new_papers": len(new_papers),
            "relevant": len(relevant),
            "breakthroughs": len(breakthrough),
            "brief_length": len(brief),
            "top_papers": [p.to_dict() for p in relevant[:5]],
        }
        logger.info("[CrossSystem] Cycle complete: %s", json.dumps({
            k: v for k, v in result.items() if k != "top_papers"
        }))
        return result

    async def _collect_papers(self, queries: list[str]) -> list[Paper]:
        """Search all paper databases with the generated queries."""
        all_papers = []
        async with httpx.AsyncClient(timeout=30) as client:
            # arXiv: 3-4 queries (free, no rate limit issues)
            for q in queries[:4]:
                try:
                    papers = await search_arxiv(q, max_results=5, client=client)
                    all_papers.extend(papers)
                    await asyncio.sleep(3)  # arXiv courtesy delay
                except Exception as exc:
                    logger.debug("[CrossSystem] arXiv query failed: %s", exc)

            # OpenAlex: 3-4 queries (free, no key, 100K/day with polite pool)
            for q in queries[4:8]:
                try:
                    papers = await search_openalex(q, max_results=5, client=client)
                    all_papers.extend(papers)
                    await asyncio.sleep(1)  # OpenAlex is generous, 1s courtesy
                except Exception as exc:
                    logger.debug("[CrossSystem] OpenAlex query failed: %s", exc)

            # CORE: 2-3 queries (works without key at 100 tokens/day, better with key)
            for q in queries[8:11]:
                try:
                    papers = await search_core(q, api_key=self.core_api_key, max_results=5, client=client)
                    all_papers.extend(papers)
                    await asyncio.sleep(2)
                except Exception as exc:
                    logger.debug("[CrossSystem] CORE query failed: %s", exc)

            # SSRN: RSS feeds (always runs)
            try:
                ssrn_papers = await fetch_ssrn_feeds(client=client)
                all_papers.extend(ssrn_papers)
            except Exception as exc:
                logger.debug("[CrossSystem] SSRN fetch failed: %s", exc)

        # De-dup by title similarity
        seen_titles = set()
        unique = []
        for p in all_papers:
            title_key = p.title.lower().strip()[:80]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(p)

        return unique

    async def _score_relevance(self, papers: list[Paper]) -> list[Paper]:
        """Score each paper's relevance using LLM."""
        if not self.llm:
            # No LLM: use keyword-based scoring as fallback
            for p in papers:
                p.relevance_score = self._keyword_relevance(p)
            return papers

        scored = []
        loop = asyncio.get_event_loop()

        for paper in papers[:20]:  # Limit LLM calls
            try:
                context = f"Title: {paper.title}\n\nAbstract: {paper.abstract[:800]}"
                result = await loop.run_in_executor(
                    None,
                    lambda ctx=context: self.llm.call_json(
                        RELEVANCE_PROMPT,
                        ctx,
                        max_tokens=400,
                        temperature=0.1,
                    ),
                )
                paper.relevance_score = min(1.0, max(0.0, result.get("relevance_score", 0.0)))
                scored.append(paper)

            except Exception as exc:
                logger.debug("[CrossSystem] Relevance scoring failed for '%s': %s",
                             paper.title[:60], exc)
                paper.relevance_score = self._keyword_relevance(paper)
                scored.append(paper)

        return scored

    def _keyword_relevance(self, paper: Paper) -> float:
        """Fallback relevance scoring based on keyword matching."""
        text = f"{paper.title} {paper.abstract}".lower()
        keywords = {
            "geopolitical": 0.15, "conflict": 0.10, "sanctions": 0.12,
            "systemic risk": 0.15, "financial crisis": 0.12, "currency": 0.08,
            "bayesian": 0.15, "fuzzy logic": 0.12, "scenario": 0.08,
            "cyber": 0.10, "semiconductor": 0.10, "infrastructure": 0.08,
            "prediction": 0.10, "forecasting": 0.10, "early warning": 0.12,
            "supply chain": 0.10, "nuclear": 0.08, "escalation": 0.10,
        }
        score = 0.0
        for kw, weight in keywords.items():
            if kw in text:
                score += weight
        return min(1.0, score)

    async def _synthesize_papers(self, papers: list[Paper]) -> str:
        """Generate an intelligence brief from relevant papers via LLM."""
        if not self.llm:
            return ""

        papers_text = "\n\n".join(
            f"[{i+1}] {p.title} ({p.source}, {p.published})\n"
            f"Authors: {', '.join(p.authors[:3])}\n"
            f"Abstract: {p.abstract[:400]}\n"
            f"Relevance: {p.relevance_score:.2f}"
            for i, p in enumerate(papers[:8])
        )

        prompt = SYNTHESIS_PROMPT.format(count=len(papers), papers=papers_text)

        loop = asyncio.get_event_loop()
        try:
            brief = await loop.run_in_executor(
                None,
                lambda: self.llm.call(
                    prompt,
                    "Generate the intelligence brief.",
                    max_tokens=1000,
                    temperature=0.3,
                ),
            )
            logger.info("[CrossSystem] Intelligence brief generated (%d chars)", len(brief))
            return brief
        except Exception as exc:
            logger.warning("[CrossSystem] Synthesis failed: %s", exc)
            return ""

    def _notify_breakthrough(self, papers: list[Paper], brief: str) -> None:
        """Notify about breakthrough paper discoveries."""
        top = papers[0]

        # Feed into pattern accumulator
        if self.proactive_notify_fn:
            try:
                self.proactive_notify_fn(
                    source_type="curiosity_finding",
                    headline=f"Research: {top.title[:100]}",
                    region="GLOBAL",
                    raw_data={
                        "source": "cross_system_learning",
                        "paper_count": len(papers),
                        "top_relevance": top.relevance_score,
                        "top_citations": top.citation_count,
                    },
                )
            except Exception as exc:
                logger.debug("[CrossSystem] Proactive notify failed: %s", exc)

        # Request conversation for truly exceptional papers
        if self.conversation_request_fn and top.relevance_score >= 0.90:
            try:
                self.conversation_request_fn(
                    topic=f"Breakthrough research: {top.title[:80]}",
                    reason=(
                        f"Found {len(papers)} highly relevant paper(s). "
                        f"Top: '{top.title}' (relevance={top.relevance_score:.2f}, "
                        f"citations={top.citation_count}). "
                        f"This could improve our analytical methods or reveal new patterns."
                    ),
                    urgency="important",
                    context_data={
                        "key_finding": brief[:500] if brief else top.abstract[:500],
                        "paper_count": len(papers),
                        "top_paper": top.to_dict(),
                    },
                )
            except Exception as exc:
                logger.debug("[CrossSystem] Conversation request failed: %s", exc)

    def get_stats(self) -> dict:
        return {
            "total_cycles": self._total_cycles,
            "total_papers_ingested": self._total_papers_ingested,
            "total_papers_relevant": self._total_papers_relevant,
            "cache_size": len(self._seen_papers),
            "sources": ["arxiv", "openalex", "core", "ssrn"],
            "core_enabled": True,  # CORE works without key (unauth: 100 tokens/day)
            "core_has_key": bool(self.core_api_key),
            "openalex_enabled": True,  # OpenAlex: free, no key, 100K req/day
        }


# ══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND LOOP — runs daily alongside other background tasks
# ══════════════════════════════════════════════════════════════════════════════

class CrossSystemLearningLoop:
    """Background loop for daily paper acquisition."""

    def __init__(
        self,
        learner: CrossSystemLearner,
        curiosity_engine: Any = None,
        proactive_engine: Any = None,
        interval_hours: int = 24,
    ):
        self.learner = learner
        self.curiosity_engine = curiosity_engine
        self.proactive_engine = proactive_engine
        self.interval = interval_hours * 3600

    async def run_forever(self):
        """Main loop — runs daily."""
        logger.info("[CrossSystemLoop] Starting cross-system learning loop (interval=%dh)",
                    self.interval // 3600)

        # Initial delay: let everything else start first (2 min)
        await asyncio.sleep(120)

        while True:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                logger.info("[CrossSystemLoop] Cancelled")
                break
            except Exception as exc:
                logger.warning("[CrossSystemLoop] Cycle error: %s", exc)
            await asyncio.sleep(self.interval)

    async def _run_cycle(self):
        """Single daily learning cycle."""
        # Gather dynamic context from curiosity + patterns
        curiosity_topics = []
        recent_patterns = []

        if self.curiosity_engine:
            try:
                active = self.curiosity_engine.get_active_curiosities()
                curiosity_topics = [
                    c.get("question", "") if isinstance(c, dict) else getattr(c, "question", "")
                    for c in active[:10]
                ]
            except Exception:
                pass

        if self.proactive_engine and hasattr(self.proactive_engine, "accumulator"):
            try:
                hot = self.proactive_engine.accumulator.get_hot_patterns(min_convergence=0.3)
                for p in hot[:5]:
                    topics = p.get("top_topics", [])
                    if topics:
                        recent_patterns.append(" ".join(topics[:4]))
            except Exception:
                pass

        result = await self.learner.run_daily_cycle(
            curiosity_topics=curiosity_topics,
            recent_patterns=recent_patterns,
        )
        logger.info("[CrossSystemLoop] Cycle result: %s", result.get("status", "unknown"))
