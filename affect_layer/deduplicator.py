"""
Affect Layer — Deduplication Engine

Prevents identical or near-identical alerts from being sent multiple times.
Uses two complementary strategies:

  1. Exact Hash    — SHA-256 of (normalised_text + sorted_sources).
                     Fires only once per 30-minute window.

  2. Semantic Sim  — Jaccard word overlap + bigram overlap + entity overlap,
                     blended into a single similarity score [0-1].
                     Alerts with similarity ≥ 0.85 to a recent alert are rejected.

State is in-memory (deque, bounded to 100 entries).  It does NOT need to
survive restarts — the 30-minute window is short enough that false negatives
at boot are acceptable.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("xdart.affect.dedup")

# ── Configuration ───────────────────────────────────────────────────────────
_WINDOW_SECONDS = 1800          # 30-minute dedup window
_MAX_HISTORY = 100              # Maximum entries kept in the sliding window
_SEMANTIC_THRESHOLD = 0.85      # Similarity ≥ this → near-duplicate


# ── Helper: text normalisation ───────────────────────────────────────────────
_NOISE = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "and", "or", "but",
    "not", "that", "this", "it", "its", "he", "she", "they",
    "we", "you", "new", "said", "says",
})

_TOKEN_RE = re.compile(r"[a-zA-Zα-ωΑ-Ωάέήίόύώΐΰϊϋ]{3,}", re.UNICODE)


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation."""
    return text.lower().strip()


def _tokenise(text: str) -> set[str]:
    """Extract meaningful tokens (length ≥ 3, noise-filtered)."""
    tokens = set(_TOKEN_RE.findall(text.lower()))
    return tokens - _NOISE


def _bigrams(tokens: set[str]) -> set[tuple[str, str]]:
    """Build bigrams from a sorted token set."""
    lst = sorted(tokens)
    return {(lst[i], lst[i + 1]) for i in range(len(lst) - 1)}


def _entity_tokens(text: str) -> set[str]:
    """Rough entity extraction: words that start with a capital letter."""
    words = re.findall(r"\b[A-ZΑ-Ω][a-zA-Zα-ωΑ-Ω]{2,}", text)
    return {w.lower() for w in words}


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class _DedupEntry:
    """A single stored alert for dedup comparison."""
    hash_hex: str
    tokens: set[str]
    bigrams: set[tuple[str, str]]
    entities: set[str]
    timestamp: float = field(default_factory=time.time)


@dataclass
class DedupResult:
    """Result of a dedup check."""
    is_duplicate: bool
    reason: str
    similarity: float = 0.0          # Highest similarity found (0 if hash match)
    matched_hash: str = ""           # Hash of the matched entry (if any)


# ── Deduplicator class ───────────────────────────────────────────────────────

class Deduplicator:
    """Stateful deduplication engine for proactive alerts.

    Thread-safety: the internal deque and all mutations are protected
    by a threading.Lock so the engine can be called from the ProactiveEngine
    worker pool without race conditions.
    """

    def __init__(
        self,
        window_minutes: int = 30,
        semantic_threshold: float = _SEMANTIC_THRESHOLD,
        max_history: int = _MAX_HISTORY,
    ):
        import threading
        self._window = window_minutes * 60
        self._threshold = semantic_threshold
        self._history: deque[_DedupEntry] = deque(maxlen=max_history)
        self._lock = threading.Lock()

        # Stats
        self._total_checked = 0
        self._total_hash_rejected = 0
        self._total_semantic_rejected = 0
        self._total_passed = 0

    # ── Public interface ─────────────────────────────────────────────────────

    def check(self, summary: str, sources: list[str] | None = None) -> DedupResult:
        """Check whether an alert is a duplicate.

        Args:
            summary:  The alert headline + summary text.
            sources:  List of source type strings (e.g. ["perception_alert"]).

        Returns:
            DedupResult with is_duplicate=True if duplicate found.
        """
        sources = sources or []
        self._total_checked += 1
        now = time.time()
        cutoff = now - self._window

        normalised = _normalise(summary)
        h = self.compute_hash(normalised, sources)
        tokens = _tokenise(normalised)
        bigs = _bigrams(tokens)
        entities = _entity_tokens(summary)

        with self._lock:
            self._prune(cutoff)

            # 1. Exact hash match
            for entry in self._history:
                if entry.hash_hex == h:
                    self._total_hash_rejected += 1
                    logger.debug("[Dedup] HASH duplicate: %s", h[:12])
                    return DedupResult(
                        is_duplicate=True,
                        reason="exact duplicate (hash match)",
                        similarity=1.0,
                        matched_hash=h,
                    )

            # 2. Semantic similarity
            best_sim = 0.0
            best_hash = ""
            for entry in self._history:
                sim = self._similarity(tokens, bigs, entities,
                                       entry.tokens, entry.bigrams, entry.entities)
                if sim > best_sim:
                    best_sim = sim
                    best_hash = entry.hash_hex
                if sim >= self._threshold:
                    self._total_semantic_rejected += 1
                    logger.debug("[Dedup] SEMANTIC duplicate (sim=%.3f): %s", sim, h[:12])
                    return DedupResult(
                        is_duplicate=True,
                        reason=f"near-duplicate (semantic similarity={sim:.2f})",
                        similarity=round(sim, 3),
                        matched_hash=best_hash,
                    )

        self._total_passed += 1
        return DedupResult(is_duplicate=False, reason="unique", similarity=round(best_sim, 3))

    def record(self, summary: str, sources: list[str] | None = None) -> None:
        """Record an alert that passed dedup (was delivered)."""
        sources = sources or []
        normalised = _normalise(summary)
        h = self.compute_hash(normalised, sources)
        tokens = _tokenise(normalised)
        bigs = _bigrams(tokens)
        entities = _entity_tokens(summary)

        entry = _DedupEntry(
            hash_hex=h,
            tokens=tokens,
            bigrams=bigs,
            entities=entities,
        )
        with self._lock:
            self._history.append(entry)

    def get_stats(self) -> dict:
        """Return dedup statistics."""
        with self._lock:
            live = len(self._history)
        return {
            "total_checked": self._total_checked,
            "hash_rejected": self._total_hash_rejected,
            "semantic_rejected": self._total_semantic_rejected,
            "passed": self._total_passed,
            "history_size": live,
            "window_minutes": self._window // 60,
            "semantic_threshold": self._threshold,
        }

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def compute_hash(normalised_text: str, sources: list[str]) -> str:
        """Deterministic SHA-256 hash of (text + sorted sources)."""
        source_str = "|".join(sorted(sources))
        payload = f"{normalised_text}::{source_str}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _prune(self, cutoff: float) -> None:
        """Remove entries older than the window. Must be called under lock."""
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()

    @staticmethod
    def _similarity(
        tok_a: set[str], big_a: set[tuple[str, str]], ent_a: set[str],
        tok_b: set[str], big_b: set[tuple[str, str]], ent_b: set[str],
    ) -> float:
        """Blended similarity: 50% token Jaccard + 30% bigram Jaccard + 20% entity overlap."""
        # Token Jaccard
        if tok_a or tok_b:
            inter = len(tok_a & tok_b)
            union = len(tok_a | tok_b)
            tok_sim = inter / union if union else 0.0
        else:
            tok_sim = 0.0

        # Bigram Jaccard
        if big_a or big_b:
            inter = len(big_a & big_b)
            union = len(big_a | big_b)
            big_sim = inter / union if union else 0.0
        else:
            big_sim = 0.0

        # Entity overlap (Dice coefficient — gentler than Jaccard for sparse sets)
        if ent_a and ent_b:
            inter = len(ent_a & ent_b)
            ent_sim = (2 * inter) / (len(ent_a) + len(ent_b))
        elif not ent_a and not ent_b:
            ent_sim = 0.0  # Neither has entities → no similarity from this
        else:
            ent_sim = 0.0

        return 0.50 * tok_sim + 0.30 * big_sim + 0.20 * ent_sim

