"""
XDART-Φ × XHEART — World Context Retriever

Pipeline step [0.35]: retrieves world events and economic indicators
from the perception DB — prioritized by salience, capped to prevent
context explosion.

Events are sorted by salience (highest first), un-injected events
preferred. Per-domain cap ensures diversity across domains.

Max budget: ~300 events, ~50K chars (~15K tokens) — fits comfortably
in the context window while leaving room for reasoning.

Tag format:
  - [FACT] = verified by source, concrete event
  - [DATA] = numeric indicator from Tier 1 source
  - [ANALYSIS] = one source's interpretation — not fact
  - Source names preserved for provenance
"""

import logging
import math
import re
import time
from datetime import datetime, timezone

from xdart.perception.db import PerceptionDB

logger = logging.getLogger("xdart.perception.context_retriever")

# Budget limits
MAX_EVENTS = 1500             # DB fetch pool (wide net, domain-capped later)
MAX_EVENTS_PER_DOMAIN = 40    # per-domain cap for diversity (was 80 — halved to prevent context bloat)
MAX_CONTEXT_CHARS = 25000     # hard char budget for the full context string (was 50K — halved for pipeline speed)

# Query-aware ranking
QUERY_AWARE_MAX_EVENTS = 80   # when a query is provided, cap final events to this
QUERY_AWARE_RECENCY_ALWAYS = 10  # always include this many most-recent events regardless of relevance
RECENCY_HALF_LIFE_HOURS = 6.0    # recency decay half-life: events 6h old have 0.5 recency score

# Stopwords to ignore in keyword extraction
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "in", "on", "at", "to", "for", "of", "and", "or", "but", "not",
    "with", "by", "from", "as", "into", "through", "about", "against",
    "between", "during", "after", "before", "above", "below", "it", "its",
    "this", "that", "these", "those", "i", "we", "you", "he", "she", "they",
    "what", "which", "who", "whom", "how", "when", "where", "why",
    "αν", "και", "ή", "σε", "για", "να", "από", "με", "που", "ότι",
    "της", "του", "τον", "την", "τα", "τη", "τις", "των", "τους",
})


class WorldContextRetriever:
    """Retrieves prioritized world events for the pipeline.

    Pipeline step [0.35] — events sorted by salience, capped sensibly.
    Un-injected events (not yet used by previous runs) come first.

    When a problem/query is provided, applies query-aware re-ranking so that
    semantically relevant events bubble up and irrelevant ones are suppressed.
    This means the LLM gets ~80 targeted events instead of 200+ flat dump —
    freeing context window for deeper reasoning.
    """

    def __init__(self, db: PerceptionDB, llm=None):
        self.db = db
        self.llm = llm  # kept for interface compat, not used for retrieval

    # ── Query-aware keyword extraction ───────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from a query/problem string."""
        words = re.findall(r"[a-zA-Zα-ωΑ-Ω0-9]{3,}", text.lower())
        return {w for w in words if w not in _STOPWORDS}

    @staticmethod
    def _recency_score(event: dict) -> float:
        """Exponential decay score based on event timestamp (0.0–1.0).
        Events from now → 1.0; events RECENCY_HALF_LIFE_HOURS ago → 0.5."""
        ts_raw = event.get("collected_at") or event.get("timestamp") or event.get("published_at")
        if not ts_raw:
            return 0.5
        try:
            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            else:
                ts = ts_raw
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            return math.exp(-0.693 * age_hours / RECENCY_HALF_LIFE_HOURS)  # half-life decay
        except Exception:
            return 0.5

    @staticmethod
    def _keyword_relevance(event: dict, keywords: set[str]) -> float:
        """Fraction of query keywords that appear in the event headline (0.0–1.0)."""
        if not keywords:
            return 0.0
        headline = event.get("headline", "").lower()
        summary = event.get("summary", "").lower()
        text = headline + " " + summary
        hits = sum(1 for kw in keywords if kw in text)
        return min(hits / len(keywords), 1.0)

    def _query_aware_rank(self, events: list[dict], query: str) -> list[dict]:
        """Re-rank events combining salience + recency + keyword relevance.

        Formula:
          score = salience × 0.35 + recency × 0.30 + keyword_relevance × 0.35

        Always ensures QUERY_AWARE_RECENCY_ALWAYS most-recent events are included
        so Αίολος never misses breaking news.
        """
        keywords = self._extract_keywords(query)

        # Score each event
        scored = []
        for evt in events:
            salience = evt.get("salience_score", 0.5)
            recency = self._recency_score(evt)
            relevance = self._keyword_relevance(evt, keywords)
            score = salience * 0.35 + recency * 0.30 + relevance * 0.35
            scored.append((score, evt))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Always include N most-recent regardless of score (breaking news guarantee)
        all_sorted_by_time = sorted(events, key=self._recency_score, reverse=True)
        must_include = {id(e) for e in all_sorted_by_time[:QUERY_AWARE_RECENCY_ALWAYS]}

        # Build final list: top scored + must-include-recent
        result = []
        seen = set()
        for score, evt in scored[:QUERY_AWARE_MAX_EVENTS]:
            result.append(evt)
            seen.add(id(evt))

        for evt in all_sorted_by_time[:QUERY_AWARE_RECENCY_ALWAYS]:
            if id(evt) not in seen:
                result.append(evt)

        logger.info(
            "[WorldContext] Query-aware ranking: %d → %d events (keywords: %s)",
            len(events), len(result), ", ".join(list(keywords)[:8]),
        )
        return result

    def retrieve(
        self,
        problem: str,
        max_events: int = MAX_EVENTS,
        max_economic: int = 100,
        hours_back: int = 72,
    ) -> dict:
        """Fetch events and indicators, prioritized by salience + query relevance.

        When `problem` is non-empty, applies query-aware re-ranking to return
        the most relevant events instead of a flat salience-sorted dump.
        Events capped at max_events total. Per-domain diversity enforced.
        Context string capped at MAX_CONTEXT_CHARS.

        Returns:
            {
                "events": [...],           # prioritized events
                "indicators": [...],       # economic indicators
                "context_string": "...",   # formatted context (budget-capped)
                "event_ids": [...]         # event IDs for provenance
            }
        """
        logger.info("[WorldContext] Retrieving world events (max=%d, hours_back=%d)...",
                     max_events, hours_back)
        t0 = time.perf_counter()

        # Fetch from DB — already sorted by salience DESC, un-injected first
        all_events, all_indicators = self.db.get_all_recent(
            hours_back=hours_back,
            max_events=max_events,
        )

        # Per-domain cap for diversity
        by_domain: dict[str, list[dict]] = {}
        for e in all_events:
            domain = e.get("domain", "MULTI")
            by_domain.setdefault(domain, []).append(e)

        capped_events = []
        for domain, domain_events in by_domain.items():
            capped_events.extend(domain_events[:MAX_EVENTS_PER_DOMAIN])

        # Re-sort by salience DESC after domain cap
        capped_events.sort(key=lambda e: e.get("salience_score", 0), reverse=True)

        # ── Query-aware re-ranking ──────────────────────────────────────────
        # When a problem/query is provided, re-rank by relevance+recency+salience
        # instead of flat salience dump. Reduces ~200 events → ~80 targeted.
        if problem and problem.strip():
            capped_events = self._query_aware_rank(capped_events, problem)

        elapsed = time.perf_counter() - t0

        logger.info(
            "[WorldContext] Data pool: %d events (from %d raw), %d indicators (%.3fs DB query)",
            len(capped_events), len(all_events), len(all_indicators), elapsed,
        )

        if not capped_events and not all_indicators:
            logger.info("[WorldContext] No events collected yet")
            return {
                "events": [],
                "indicators": [],
                "context_string": "",
                "event_ids": [],
            }

        event_ids = [e["id"] for e in capped_events]

        # Build context with char budget
        context_string = self._build_full_context(capped_events, all_indicators)

        # Enforce hard char budget
        if len(context_string) > MAX_CONTEXT_CHARS:
            context_string = context_string[:MAX_CONTEXT_CHARS] + "\n\n[... context truncated at budget limit ...]"
            logger.warning("[WorldContext] Context truncated: %d → %d chars",
                          len(context_string), MAX_CONTEXT_CHARS)

        # Count unique sources
        sources = set(e.get("source_name", "?") for e in capped_events)
        sources.update(i.get("source", "?") for i in all_indicators)

        logger.info(
            "[WorldContext] Final context: %d chars — %d events from %d sources + %d indicators",
            len(context_string), len(capped_events), len(sources), len(all_indicators),
        )

        return {
            "events": capped_events,
            "indicators": all_indicators,
            "context_string": context_string,
            "event_ids": event_ids,
        }

    def _build_full_context(self, events: list[dict], indicators: list[dict]) -> str:
        """Build the world context — events grouped by domain, capped. Source names preserved.

        The reasoning phases will cross-reference through their own lenses.
        """
        # Count unique sources
        sources = set(e.get("source_name", "?") for e in events)
        sources.update(i.get("source", "?") for i in indicators)

        lines = [
            f"=== WORLD PERCEPTION — FULL AWARENESS ===",
            f"(Total: {len(events)} events from {len(sources)} sources, "
            f"{len(indicators)} economic indicators)",
            "",
            "You are seeing ALL collected world data. Cross-reference freely.",
            "Facts labeled [FACT] — from wire services / official data.",
            "Analysis labeled [ANALYSIS] — one source's interpretation.",
            "When sources report the same event differently, note the divergence.",
            "",
        ]

        # Group events by domain
        by_domain: dict[str, list[dict]] = {}
        for e in events:
            domain = e.get("domain", "MULTI")
            by_domain.setdefault(domain, []).append(e)

        for domain, domain_events in sorted(by_domain.items()):
            lines.append(f"── {domain} ({len(domain_events)} events) ──")
            for e in domain_events:
                source = e.get("source_name", "?")
                headline = e.get("headline", "")
                tag = e.get("content_type", "FACT")

                # Show corroboration if available
                corroborated = e.get("corroborated_by", [])
                contradicted = e.get("contradicted_by", [])

                line = f"  [{tag}] [{source}] {headline}"
                if corroborated:
                    line += f" (also: {', '.join(corroborated[:2])})"
                if contradicted:
                    line += f" ⚠ disputed by: {', '.join(contradicted)}"
                lines.append(line)
            lines.append("")

        # All economic indicators
        if indicators:
            lines.append(f"── ECONOMIC INDICATORS ({len(indicators)}) ──")
            for ind in indicators:
                name = ind.get("indicator", "?")
                value = ind.get("value")
                unit = ind.get("unit", "")
                change = ind.get("change_pct")
                source = ind.get("source", "?")
                period = ind.get("period", "?")

                change_str = ""
                if change is not None:
                    arrow = "↑" if change > 0 else "↓"
                    change_str = f" ({arrow}{abs(change):.2f}%)"

                val_str = f"{value:.4f}" if isinstance(value, float) else str(value)
                lines.append(
                    f"  [DATA] [{source}] {name}: {val_str} {unit}{change_str} "
                    f"(period: {period})"
                )
            lines.append("")

        lines.append("=== END WORLD PERCEPTION ===")
        return "\n".join(lines)

    def mark_used(self, event_ids: list[str], run_number: int):
        """Mark events as used by a pipeline run (provenance tracking)."""
        if event_ids:
            self.db.mark_injected(event_ids, run_number)
            logger.info(
                "[WorldContext] Marked %d events as used in run %d",
                len(event_ids), run_number,
            )

    def status(self) -> dict:
        """Return current world context status."""
        recent = self.db.get_recent_events(hours_back=24, max_events=5)
        econ = self.db.get_recent_economic(max_indicators=5)
        return {
            "total_events": self.db.event_count(),
            "total_economic": self.db.economic_count(),
            "recent_events_24h": len(recent),
            "latest_headlines": [e.get("headline", "") for e in recent[:3]],
            "latest_indicators": [
                f"{e.get('indicator', '?')}: {e.get('value', '?')}"
                for e in econ[:3]
            ],
        }
