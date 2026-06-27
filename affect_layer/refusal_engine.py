"""
Affect Layer — Refusal Engine + AffectLayer (Composite Facade)

RefusalEngine is the final gate that combines all four pillars:
  1. Deduplicator   — reject if exact/near-duplicate
  2. SignalScorer   — compute composite quality score
  3. BalanceMonitor — check domain distribution; adjust weights if biased
  4. AffectiveMemory— record valence/arousal; check for domain fatigue

AffectLayer is the public facade used by proactive.py.
Create ONE instance at startup and inject it into ProactiveEngine.

PreferenceEngine is the active preference system — it forms likes/dislikes
from experience and drives autonomous behaviour. It is also wired through
AffectLayer for convenience.

Usage in proactive.py:
    from affect_layer import AffectLayer

    # Startup
    self._affect_layer = AffectLayer(mongo=self._mongo)

    # In _evaluate_and_notify_inner(), BEFORE creating Notification:
    decision = self._affect_layer.evaluate(
        headline=headline,
        summary=summary,
        domains=notif_domains,
        event_type=event_type,
        event_data=event_data,
    )
    if not decision["fire"]:
        self._total_suppressed += 1
        logger.info("[Proactive] AFFECT GATE rejected: %s", decision["reason"])
        return None

    # Override urgency if scorer upgraded/downgraded it
    if decision["urgency_override"]:
        urgency = decision["urgency_override"]

    # After successful delivery:
    self._affect_layer.record_delivery(headline + " " + summary, domains, notif_domains, event_data)
"""

from __future__ import annotations

import logging
from typing import Any

from affect_layer.deduplicator import Deduplicator
from affect_layer.signal_scorer import SignalScorer
from affect_layer.balance_monitor import DomainBalanceMonitor
from affect_layer.affective_memory import AffectiveMemory
from affect_layer.preference_engine import PreferenceEngine
from affect_layer.cognitive_pool import CognitivePool

logger = logging.getLogger("xdart.affect.refusal")


class RefusalEngine:
    """Applies dedup + scoring + balance + fatigue checks."""

    def __init__(
        self,
        deduplicator: Deduplicator,
        scorer: SignalScorer,
        balance: DomainBalanceMonitor,
        memory: AffectiveMemory,
    ):
        self.deduplicator = deduplicator
        self.scorer = scorer
        self.balance = balance
        self.memory = memory

        self._total_evaluated = 0
        self._total_rejected = 0
        self._total_approved = 0

    def evaluate(
        self,
        headline: str,
        summary: str,
        domains: list[str],
        event_type: str,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Run all checks and return a decision dict.

        Returns:
            {
              "fire":             bool,
              "urgency_override": str | None,   # "critical"|"important"|"digest"|None
              "reason":           str,
              "score":            dict,          # SignalScore.to_dict()
              "dedup":            dict,          # DedupResult fields
            }
        """
        self._total_evaluated += 1
        combined_text = (headline + " " + summary).strip()

        # ── Step 1: Deduplication ────────────────────────────────────────────
        source_types = event_data.get("source_types", [event_type])
        dedup_result = self.deduplicator.check(combined_text, source_types)
        if dedup_result.is_duplicate:
            self._total_rejected += 1
            return {
                "fire": False,
                "urgency_override": None,
                "reason": f"dedup: {dedup_result.reason}",
                "score": {},
                "dedup": {"is_duplicate": True, "reason": dedup_result.reason,
                          "similarity": dedup_result.similarity},
            }

        # ── Step 2: Balance monitor (updates scorer weights if biased) ────────
        bias_warning = self.balance.get_bias_warning()
        if bias_warning:
            logger.info("[AffectLayer] %s", bias_warning)

        # ── Step 3: Signal scoring ────────────────────────────────────────────
        sig_score = self.scorer.score(
            headline=headline,
            summary=summary,
            domains=domains,
            event_type=event_type,
            event_data=event_data,
        )

        # ── Step 4: Fatigue check ─────────────────────────────────────────────
        # If a domain is generating boring alerts, downgrade but don't suppress
        for domain in domains:
            if self.memory.is_fatigued(domain, lookback=8):
                logger.debug("[AffectLayer] Fatigue detected for domain %s", domain)
                # Downgrade category one step (critical→important, important→digest, digest→skip)
                old_cat = sig_score.category
                if sig_score.category == "critical":
                    sig_score.category = "important"
                elif sig_score.category == "important":
                    sig_score.category = "digest"
                elif sig_score.category == "digest":
                    sig_score.category = "skip"
                if old_cat != sig_score.category:
                    logger.info("[AffectLayer] Fatigue downgrade %s → %s for domain %s",
                                old_cat, sig_score.category, domain)
                break  # One domain fatigue = one level downgrade

        # ── Step 5: Final routing decision ────────────────────────────────────
        if sig_score.category == "skip":
            self._total_rejected += 1
            return {
                "fire": False,
                "urgency_override": None,
                "reason": f"score too low: composite={sig_score.composite:.2f} (skip threshold)",
                "score": sig_score.to_dict(),
                "dedup": {"is_duplicate": False},
            }

        self._total_approved += 1

        # Map score category to urgency override
        category_to_urgency = {
            "critical":  "critical",
            "important": "important",
            "digest":    "digest",
        }
        urgency_override = category_to_urgency.get(sig_score.category)

        return {
            "fire": True,
            "urgency_override": urgency_override,
            "reason": f"score={sig_score.composite:.2f} → {sig_score.category}",
            "score": sig_score.to_dict(),
            "dedup": {"is_duplicate": False, "similarity": dedup_result.similarity},
        }

    def record_delivery(
        self,
        combined_text: str,
        domains: list[str],
        source_types: list[str],
        event_data: dict[str, Any],
        score: dict | None = None,
    ) -> None:
        """Call AFTER a successful delivery to update all state."""
        self.deduplicator.record(combined_text, source_types)
        self.scorer.record(domains)
        self.balance.record(domains)
        # Derive affective trace from score data
        if score:
            valence = score.get("relevance", 0.5) - 0.5
            arousal = score.get("composite", 0.5)
        else:
            valence = 0.0
            arousal = 0.5
        # Extract rough pattern cluster from domains
        pattern = "/".join(sorted(domains)[:2]) if domains else "GENERAL"
        self.memory.record_trigger(
            trigger=combined_text[:150],
            valence=valence,
            arousal=arousal,
            context={"domains": domains, "event_type": event_data.get("source_types", [])},
            pattern=pattern,
        )

    def get_stats(self) -> dict:
        """Return combined stats from all components."""
        return {
            "refusal_engine": {
                "total_evaluated": self._total_evaluated,
                "total_rejected": self._total_rejected,
                "total_approved": self._total_approved,
                "rejection_rate": (
                    round(self._total_rejected / self._total_evaluated, 3)
                    if self._total_evaluated else 0.0
                ),
            },
            "deduplicator": self.deduplicator.get_stats(),
            "scorer": self.scorer.get_stats(),
            "balance": self.balance.get_stats(),
            "affective_memory": self.memory.get_stats(),
        }


class AffectLayer:
    """Public facade — create once at startup, pass to ProactiveEngine.

    Wires together all 6 pillars + PreferenceEngine + CognitivePool
    and exposes a simple evaluate() interface.
    """

    def __init__(self, mongo=None):
        """
        Args:
            mongo: Optional MongoClient-like object for AffectiveMemory persistence.
        """
        self.deduplicator = Deduplicator(window_minutes=30, semantic_threshold=0.85)
        self.scorer = SignalScorer()
        self.balance = DomainBalanceMonitor(scorer=self.scorer)
        self.affective_memory = AffectiveMemory(mongo=mongo)
        self.preferences = PreferenceEngine(mongo=mongo, affective_memory=self.affective_memory)
        self.cognitive_pool = CognitivePool(mongo=mongo)
        self._engine = RefusalEngine(
            deduplicator=self.deduplicator,
            scorer=self.scorer,
            balance=self.balance,
            memory=self.affective_memory,
        )
        logger.info("[AffectLayer] Initialised (dedup 30min / score threshold 0.35)")

    def evaluate(
        self,
        headline: str,
        summary: str,
        domains: list[str],
        event_type: str,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Full evaluation pipeline.  Returns decision dict (see RefusalEngine.evaluate)."""
        return self._engine.evaluate(
            headline=headline,
            summary=summary,
            domains=domains,
            event_type=event_type,
            event_data=event_data,
        )

    def record_delivery(
        self,
        headline: str,
        summary: str,
        domains: list[str],
        source_types: list[str],
        event_data: dict[str, Any],
        score: dict | None = None,
    ) -> None:
        """Record a successful delivery.  Must be called after every fired alert."""
        combined_text = (headline + " " + summary).strip()
        self._engine.record_delivery(
            combined_text=combined_text,
            domains=domains,
            source_types=source_types,
            event_data=event_data,
            score=score,
        )

    def get_balance_context(self) -> str:
        """Get domain balance context string for chat injection."""
        return self.balance.get_balance_context()

    def get_affective_context(self) -> str:
        """Get affective memory summary for chat injection."""
        return self.affective_memory.get_context_summary()

    def get_preference_context(self) -> str:
        """Get Αίολος's self-expression of his current preferences."""
        return self.preferences.get_self_expression()

    def get_cognitive_pool_context(self) -> str:
        """Get cognitive pool digest for chat/wakeup context injection."""
        return self.cognitive_pool.get_context_for_wakeup()

    def get_stats(self) -> dict:
        """Combined stats from all components."""
        return self._engine.get_stats()
