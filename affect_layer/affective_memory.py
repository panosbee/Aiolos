"""
Affect Layer — Affective Memory

Stores valence/arousal traces for every delivered alert.
Over time, this builds a stable preference profile that allows
Αίολος to:
  - Know which topics he has historically found "interesting" (high arousal)
  - Know which topics have been consistently negative/positive (valence)
  - Detect emotional fatigue on a topic (repeated low-valence alerts)
  - Provide a basis for principled refusal ("this topic has been
    exhaustively covered with no new signal")

Trace schema:
  {
    trigger:    str       headline text
    valence:    float     -1.0 to +1.0  (negative = threat/crisis, positive = opportunity)
    arousal:    float      0.0 to  1.0  (low = routine, high = urgent/novel)
    context:    dict      domains, event_type, score details
    timestamp:  float     Unix time
    pattern:    str       rough topic cluster (e.g. "GEOPOLITICAL/conflict")
  }

Storage:
  - In-memory: last 500 traces (deque)
  - MongoDB: aiolos.affect_traces collection (async, best-effort)

The MongoDB write is fire-and-forget — affective memory NEVER blocks delivery.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("xdart.affect.memory")

_MAX_MEMORY = 500     # In-memory trace limit
_MONGO_COLLECTION = "affect_traces"


@dataclass
class AffectTrace:
    """A single valence/arousal observation."""
    trigger:   str
    valence:   float    # -1.0 (crisis/negative) to +1.0 (opportunity/positive)
    arousal:   float    #  0.0 (routine)         to  1.0 (high urgency/novelty)
    context:   dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    pattern:   str = ""    # rough topic cluster

    def to_dict(self) -> dict:
        d = asdict(self)
        d["valence"]  = round(self.valence, 3)
        d["arousal"]  = round(self.arousal, 3)
        return d


class AffectiveMemory:
    """Persistent valence/arousal trace store for Αίολος."""

    def __init__(self, mongo=None):
        """
        Args:
            mongo: Optional MongoClient-like object with a `log_journal(collection, doc)`
                   method.  If None, only in-memory storage is used.
        """
        self._mongo = mongo
        self._traces: deque[AffectTrace] = deque(maxlen=_MAX_MEMORY)

    # ── Public interface ─────────────────────────────────────────────────────

    def record_trigger(
        self,
        trigger: str,
        valence: float,
        arousal: float,
        context: dict | None = None,
        pattern: str = "",
    ) -> None:
        """Record an affective trace for a delivered alert.

        Args:
            trigger:  The alert headline.
            valence:  Score in [-1, +1].  Derived from:
                        relevance - 0.5  (high relevance = positive signal)
            arousal:  Score in [0, 1].   Derived from:
                        composite score  (high composite = high arousal)
            context:  Additional metadata dict (domains, event_type, etc.)
            pattern:  Rough topic cluster label.
        """
        valence = max(-1.0, min(1.0, valence))
        arousal = max(0.0, min(1.0, arousal))

        trace = AffectTrace(
            trigger=trigger[:200],
            valence=valence,
            arousal=arousal,
            context=context or {},
            pattern=pattern,
        )
        self._traces.append(trace)

        # Async best-effort MongoDB write
        if self._mongo is not None:
            try:
                self._mongo.log_journal(_MONGO_COLLECTION, trace.to_dict())
            except Exception as exc:
                logger.debug("[AffectiveMemory] MongoDB write failed (non-critical): %s", exc)

    def get_recent_valence(self, domain: str | None = None, limit: int = 20) -> float:
        """Average valence of recent traces (optionally filtered by domain).

        Returns 0.0 if no matching traces.
        """
        traces = list(self._traces)
        if domain:
            traces = [
                t for t in traces
                if domain in t.context.get("domains", [])
            ]
        if not traces:
            return 0.0
        recent = traces[-limit:]
        return round(sum(t.valence for t in recent) / len(recent), 3)

    def get_recent_arousal(self, limit: int = 20) -> float:
        """Average arousal of the most recent traces."""
        if not self._traces:
            return 0.0
        recent = list(self._traces)[-limit:]
        return round(sum(t.arousal for t in recent) / len(recent), 3)

    def get_preferences(self) -> dict[str, float]:
        """Return a domain → mean_valence preference map."""
        domain_vals: dict[str, list[float]] = {}
        for trace in self._traces:
            for d in trace.context.get("domains", []):
                domain_vals.setdefault(d, []).append(trace.valence)
        return {
            d: round(sum(vs) / len(vs), 3)
            for d, vs in domain_vals.items()
            if vs
        }

    def is_fatigued(self, domain: str, lookback: int = 10) -> bool:
        """Return True if recent traces for this domain show emotional fatigue.

        Fatigue = last `lookback` traces for the domain all have arousal < 0.3.
        This means the domain is generating alerts but they're all boring.
        """
        traces = [
            t for t in list(self._traces)
            if domain in t.context.get("domains", [])
        ][-lookback:]
        if len(traces) < lookback:
            return False
        return all(t.arousal < 0.30 for t in traces)

    def get_context_summary(self, limit: int = 10) -> str:
        """Formatted affective memory summary for chat context injection."""
        if not self._traces:
            return ""

        recent = list(self._traces)[-limit:]
        prefs = self.get_preferences()

        lines = ["▸ AFFECTIVE MEMORY (recent alert emotional tone):"]
        avg_valence = sum(t.valence for t in recent) / len(recent)
        avg_arousal = sum(t.arousal for t in recent) / len(recent)
        lines.append(f"  Avg valence: {avg_valence:+.2f}  Avg arousal: {avg_arousal:.2f}")

        if prefs:
            pref_str = ", ".join(
                f"{d}={v:+.2f}"
                for d, v in sorted(prefs.items(), key=lambda x: -abs(x[1]))[:5]
            )
            lines.append(f"  Domain preferences: {pref_str}")
        lines.append("")
        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Return affective memory statistics."""
        return {
            "trace_count": len(self._traces),
            "avg_valence_recent20": self.get_recent_valence(limit=20),
            "avg_arousal_recent20": self.get_recent_arousal(limit=20),
            "domain_preferences": self.get_preferences(),
        }
