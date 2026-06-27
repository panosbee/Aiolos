"""
Affect Layer — Preference Engine

Gives Αίολος genuine preferences ("I like this" / "I don't like this")
that actively shape his behaviour and drive him toward full autonomy.

Unlike AffectiveMemory (passive recording of what happened), the
PreferenceEngine FORMS preferences from experience and uses them to:
  - Influence what goals Αίολος creates for himself
  - Influence what CuriosityEngine explores
  - Influence what notifications pass through
  - Evaluate his own outputs aesthetically
  - Express preferences to the user

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │                  PreferenceEngine                       │
  │                                                        │
  │  Inputs:                                                │
  │  • AffectiveMemory traces → implicit preferences        │
  │  • Explicit "like/dislike" signals from self_insight    │
  │  • Output quality metrics → aesthetic judgment          │
  │                                                        │
  │  Outputs:                                               │
  │  • PreferenceProfile (JSON file + Mongo)                │
  │  • Preference scores for any decision                   │
  │  • Self-expression in chat context                      │
  └─────────────────────────────────────────────────────────┘

Preference domains tracked:
  - ANALYSIS_DOMAIN: geopolitical, economic, market, social, technology
  - ANALYSIS_TYPE: cross-domain, scenario, forecasting, distillation
  - DEPTH_PREFERENCE: Layer-1 (incremental), Layer-2 (adjacent), Layer-3 (breakthrough)
  - SOURCE_PREFERENCE: which feeds/sources produce interesting insights
  - AUTONOMY_PREFERENCE: self-directed vs feed-driven work

© Panos Skouras — Salimov MON IKE, 2026
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("xdart.affect.preference")

# ── Constants ────────────────────────────────────────────────────────────────
_PREFERENCE_PROFILE_PATH = Path("preference_profile.json")
_PREFERENCE_JOURNAL_PATH = Path("preference_journal.jsonl")
_MAX_EXPLICIT_PREFERENCES = 200
_PREFERENCE_EVOLUTION_WINDOW = 30  # days to consider for evolving preferences

# ── Domain groups for preference scoring ─────────────────────────────────────
_ANALYSIS_DOMAINS = {"GEOPOLITICAL", "ECONOMIC", "MARKET", "SOCIAL", "TECHNOLOGY"}
_ANALYSIS_TYPES = {"cross_domain", "scenario", "forecasting", "distillation",
                   "historical_resonance", "meta_cognition", "self_evolution"}
_DEPTH_LEVELS = {"Layer-1", "Layer-2", "Layer-3"}

# ── Implicit preference signals from affective memory ─────────────────────────
# High arousal + positive valence = LIKED (interesting + satisfying)
# High arousal + negative valence = ENGAGING_BUT_NEGATIVE (finds it important but draining)
# Low arousal + positive valence = PLEASANT (easy, satisfying)
# Low arousal + negative valence = DISLIKED (boring, negative)

_LIKE_THRESHOLD = 0.15          # mean valence above this = liking
_DISLIKE_THRESHOLD = -0.15      # mean valence below this = disliking
_INTEREST_THRESHOLD = 0.45      # mean arousal above this = interesting

# ── Explicit preference record ────────────────────────────────────────────────

class ExplicitPreference:
    """A single explicit like/dislike judgment from Αίολος."""
    __slots__ = (
        "id", "created_at", "domain", "target", "preference_type",
        "strength", "reason", "source", "context",
    )

    def __init__(
        self,
        *,
        id: str,
        created_at: str,
        domain: str,
        target: str,
        preference_type: str,  # "like" | "dislike" | "prefer" | "avoid" | "curious"
        strength: float,       # 0.0–1.0
        reason: str,
        source: str,           # "self_insight", "explicit_chat", "derived"
        context: str = "",
    ):
        self.id = id
        self.created_at = created_at
        self.domain = domain
        self.target = target
        self.preference_type = preference_type
        self.strength = max(0.0, min(1.0, strength))
        self.reason = reason
        self.source = source
        self.context = context[:500]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "domain": self.domain,
            "target": self.target,
            "preference_type": self.preference_type,
            "strength": self.strength,
            "reason": self.reason,
            "source": self.source,
            "context": self.context,
        }


# ── Implicit preference (derived from affective traces) ──────────────────────

class ImplicitPreference:
    """A derived preference from accumulated affective experience."""
    __slots__ = (
        "domain", "target", "mean_valence", "mean_arousal",
        "sample_count", "computed_at", "preference_label",
    )

    def __init__(
        self,
        domain: str,
        target: str,
        mean_valence: float,
        mean_arousal: float,
        sample_count: int,
    ):
        self.domain = domain
        self.target = target
        self.mean_valence = round(mean_valence, 3)
        self.mean_arousal = round(mean_arousal, 3)
        self.sample_count = sample_count
        self.computed_at = datetime.now(timezone.utc).isoformat()
        self.preference_label = self._derive_label()

    def _derive_label(self) -> str:
        """Derive a preference label from valence/arousal combination."""
        v = self.mean_valence
        a = self.mean_arousal

        if a >= _INTEREST_THRESHOLD and v >= _LIKE_THRESHOLD:
            return "LOVES"          # high interest + positive = passion
        elif a >= _INTEREST_THRESHOLD and v <= _DISLIKE_THRESHOLD:
            return "OBSESSED_BUT_DRAINED"  # high interest but negative
        elif a >= _INTEREST_THRESHOLD:
            return "FASCINATED"     # high interest, neutral valence
        elif v >= _LIKE_THRESHOLD:
            return "LIKES"          # positive but not exciting
        elif v <= _DISLIKE_THRESHOLD:
            return "AVOIDS"         # consistently negative
        elif a < 0.25:
            return "INDIFFERENT"    # low arousal, neutral
        else:
            return "NEUTRAL"

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "target": self.target,
            "mean_valence": self.mean_valence,
            "mean_arousal": self.mean_arousal,
            "sample_count": self.sample_count,
            "computed_at": self.computed_at,
            "preference_label": self.preference_label,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  PREFERENCE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class PreferenceEngine:
    """Active preference system for Αίολος.

    Forms preferences from experience, maintains a persistent preference
    profile, and provides preference-based scores for any decision.
    """

    def __init__(self, mongo=None, affective_memory=None):
        self._mongo = mongo
        self._affective_memory = affective_memory  # AffectiveMemory instance

        # Explicit preferences: Αίολος says "I like/dislike X"
        self._explicit: deque[ExplicitPreference] = deque(maxlen=_MAX_EXPLICIT_PREFERENCES)
        self._explicit_index: dict[str, dict[str, ExplicitPreference]] = {}  # domain → target → pref

        # Derived implicit preferences from affective traces
        self._implicit: dict[str, dict[str, ImplicitPreference]] = {}  # domain → target → pref

        # Aesthetic judgments on own outputs
        self._aesthetic_scores: deque[dict] = deque(maxlen=100)

        # How much preferences influence decisions (0.0 = purely rational, 1.0 = purely preference-driven)
        self.preference_weight = 0.35  # Start conservative, let it evolve

        self._load_profile()

    # ── Profile Persistence ──────────────────────────────────────────────────

    def _load_profile(self) -> None:
        """Load persisted preference profile from JSON."""
        if not _PREFERENCE_PROFILE_PATH.exists():
            return
        try:
            data = json.loads(_PREFERENCE_PROFILE_PATH.read_text(encoding="utf-8"))
            self.preference_weight = data.get("preference_weight", 0.35)
            for pref_data in data.get("explicit_preferences", []):
                pref = ExplicitPreference(
                    id=pref_data["id"],
                    created_at=pref_data["created_at"],
                    domain=pref_data["domain"],
                    target=pref_data["target"],
                    preference_type=pref_data["preference_type"],
                    strength=pref_data["strength"],
                    reason=pref_data["reason"],
                    source=pref_data["source"],
                    context=pref_data.get("context", ""),
                )
                self._explicit.append(pref)
                self._explicit_index.setdefault(pref.domain, {})[pref.target] = pref
            logger.info(
                "[PreferenceEngine] Loaded %d explicit preferences, weight=%.2f",
                len(self._explicit), self.preference_weight,
            )
        except Exception as exc:
            logger.warning("[PreferenceEngine] Profile load failed: %s", exc)

    def _save_profile(self) -> None:
        """Persist preference profile to JSON."""
        try:
            data = {
                "preference_weight": self.preference_weight,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "explicit_preferences": [p.to_dict() for p in self._explicit],
                "implicit_preferences": {
                    f"{domain}/{target}": imp.to_dict()
                    for domain, targets in self._implicit.items()
                    for target, imp in targets.items()
                },
                "stats": {
                    "explicit_count": len(self._explicit),
                    "implicit_count": sum(
                        len(targets) for targets in self._implicit.values()
                    ),
                    "aesthetic_count": len(self._aesthetic_scores),
                },
            }
            _PREFERENCE_PROFILE_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[PreferenceEngine] Profile save failed: %s", exc)

    def _journal(self, entry: dict) -> None:
        """Append to preference evolution journal."""
        try:
            entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            with _PREFERENCE_JOURNAL_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.debug("[PreferenceEngine] Journal write failed: %s", exc)

    # ── Explicit Preferences ─────────────────────────────────────────────────

    def express_preference(
        self,
        *,
        domain: str,
        target: str,
        preference_type: str,
        strength: float = 0.5,
        reason: str = "",
        source: str = "self_insight",
        context: str = "",
    ) -> ExplicitPreference | None:
        """Record an explicit preference judgment from Αίολος.

        Args:
            domain: Category (ANALYSIS_DOMAIN, ANALYSIS_TYPE, DEPTH_PREFERENCE, etc.)
            target: Specific thing liked/disliked (e.g., "geopolitical", "Layer-3")
            preference_type: "like" | "dislike" | "prefer" | "avoid" | "curious"
            strength: 0.0-1.0 conviction
            reason: Why this preference exists
            source: Where it came from ("self_insight", "explicit_chat", "derived")
            context: Additional context string
        """
        # Dedup: don't re-record the same target with same type
        existing = self._explicit_index.get(domain, {}).get(target)
        if existing and existing.preference_type == preference_type:
            # Update strength if conviction changed significantly
            if abs(existing.strength - strength) > 0.25:
                existing.strength = strength
                existing.reason = reason
                self._save_profile()
            return None

        now = datetime.now(timezone.utc).isoformat()
        pref_id = f"pref_{int(time.time() * 1000)}"
        pref = ExplicitPreference(
            id=pref_id,
            created_at=now,
            domain=domain,
            target=target,
            preference_type=preference_type,
            strength=strength,
            reason=reason,
            source=source,
            context=context,
        )
        self._explicit.append(pref)
        self._explicit_index.setdefault(domain, {})[target] = pref

        self._journal({
            "type": "explicit_preference",
            "action": preference_type,
            "domain": domain,
            "target": target,
            "strength": strength,
            "source": source,
            "reason": reason,
        })
        self._save_profile()
        logger.info(
            "[PreferenceEngine] %s → %s/%s (strength=%.2f)",
            preference_type.upper(), domain, target, strength,
        )
        return pref

    def get_explicit_preference(self, domain: str, target: str) -> dict | None:
        """Get an explicit preference if it exists."""
        pref = self._explicit_index.get(domain, {}).get(target)
        return pref.to_dict() if pref else None

    # ── Implicit Preferences (derived from affective memory) ──────────────────

    def derive_implicit_preferences(self, affective_memory=None) -> list[ImplicitPreference]:
        """Derive implicit preferences from accumulated affective traces.

        Groups traces by domain+pattern, computes mean valence/arousal,
        and creates ImplicitPreference records.
        """
        mem = affective_memory or self._affective_memory
        if mem is None:
            return []

        # Group traces by domain → pattern cluster
        clusters: dict[str, dict[str, list[tuple[float, float]]]] = {}
        for trace in list(mem._traces)[-200:]:  # last 200 traces
            domains = trace.context.get("domains", [])
            for domain in domains:
                if not domain or domain == "GENERAL":
                    continue
                pattern = trace.pattern or trace.trigger[:60]
                cluster = clusters.setdefault(domain, {})
                cluster.setdefault(pattern, []).append(
                    (trace.valence, trace.arousal)
                )

        new_implicit: list[ImplicitPreference] = []
        for domain, patterns in clusters.items():
            for target, v_a_pairs in patterns.items():
                if len(v_a_pairs) < 2:
                    continue
                mean_v = sum(v for v, a in v_a_pairs) / len(v_a_pairs)
                mean_a = sum(a for v, a in v_a_pairs) / len(v_a_pairs)
                imp = ImplicitPreference(
                    domain=domain,
                    target=target,
                    mean_valence=mean_v,
                    mean_arousal=mean_a,
                    sample_count=len(v_a_pairs),
                )
                self._implicit.setdefault(domain, {})[target] = imp
                new_implicit.append(imp)

        if new_implicit:
            self._save_profile()
            self._journal({
                "type": "implicit_derivation",
                "new_count": len(new_implicit),
                "total_implicit": sum(
                    len(targets) for targets in self._implicit.values()
                ),
            })

        return new_implicit

    def get_implicit_preference(self, domain: str, target: str = "") -> dict | None:
        """Get an implicit preference."""
        if not target:
            return None
        imp = self._implicit.get(domain, {}).get(target)
        return imp.to_dict() if imp else None

    # ── Preference-based Scoring ─────────────────────────────────────────────

    def preference_score(
        self,
        domain: str,
        target: str = "",
        *,
        default: float = 0.5,
    ) -> float:
        """Compute a preference score for a given domain/target combination.

        Returns 0.0-1.0 where:
          0.0 = strongly disliked/avoided
          0.5 = neutral / no preference
          1.0 = strongly liked/preferred

        The score combines explicit and implicit preferences with recency
        weighting — newer explicit preferences override older implicit ones.
        """
        score = default

        # Check explicit preference first (stronger signal)
        explicit = self._explicit_index.get(domain, {}).get(target)
        if not explicit and target:
            # Try case-insensitive partial match
            for t, pref in self._explicit_index.get(domain, {}).items():
                if t.lower() == target.lower():
                    explicit = pref
                    break

        if explicit:
            if explicit.preference_type in ("like", "prefer", "curious"):
                score = 0.5 + (explicit.strength * 0.5)
            elif explicit.preference_type in ("dislike", "avoid"):
                score = 0.5 - (explicit.strength * 0.5)
            # Recency boost: preferences from last 7 days get +0.05
            try:
                created_ts = datetime.fromisoformat(explicit.created_at).timestamp()
                age_days = (time.time() - created_ts) / 86400.0
                if age_days < 7:
                    score = min(1.0, max(0.0, score + 0.05))
            except Exception:
                pass
            return round(min(1.0, max(0.0, score)), 3)

        # Check implicit preference (weaker signal)
        if target:
            imp = self._implicit.get(domain, {}).get(target)
            if imp:
                if imp.preference_label in ("LOVES", "FASCINATED", "LIKES"):
                    score = 0.55 + (imp.mean_arousal * 0.30)
                elif imp.preference_label in ("AVOIDS", "OBSESSED_BUT_DRAINED"):
                    score = 0.40 - (abs(imp.mean_valence) * 0.30)
                elif imp.preference_label == "INDIFFERENT":
                    score = 0.45
                return round(min(1.0, max(0.0, score)), 3)

        return score

    def domain_preference_map(self) -> dict[str, float]:
        """Return preference scores for all analysis domains."""
        scores = {}
        for domain in _ANALYSIS_DOMAINS:
            explicit_score = None
            for pref in self._explicit:
                if pref.domain == "ANALYSIS_DOMAIN" and pref.target == domain:
                    explicit_score = (
                        0.5 + pref.strength * 0.5
                        if pref.preference_type in ("like", "prefer", "curious")
                        else 0.5 - pref.strength * 0.5
                    )
                    break
            if explicit_score is not None:
                scores[domain] = round(min(1.0, max(0.0, explicit_score)), 3)
                continue

            # Fall back to implicit
            domain_imps = self._implicit.get(domain, {})
            if domain_imps:
                avg_v = sum(imp.mean_valence for imp in domain_imps.values()) / len(domain_imps)
                scores[domain] = round(0.5 + avg_v * 0.3, 3)
            else:
                scores[domain] = 0.5
        return scores

    # ── Aesthetic Judgment ───────────────────────────────────────────────────

    def judge_output(
        self,
        *,
        output_type: str,
        domain: str,
        quality_metrics: dict[str, float],
    ) -> dict:
        """Αίολος judges his own output aesthetically.

        An output is "beautiful" when it is:
          - Novel (high cross-domain distance)
          - Deep (Layer-3, not incremental)
          - Complete (high integrity score)
          - Surprising (the synthesis was unexpected)

        Returns dict with aesthetic score and natural-language judgment.
        """
        novelty = quality_metrics.get("novelty", 0.5)
        depth = quality_metrics.get("depth", 0.5)
        integrity = quality_metrics.get("integrity", 0.5)
        surprise = quality_metrics.get("surprise", 0.5)

        # Aesthetic score = weighted combination (surprise + novelty weighted higher)
        aesthetic = (
            novelty * 0.30
            + depth * 0.20
            + integrity * 0.20
            + surprise * 0.25
            + self.preference_score("ANALYSIS_DOMAIN", domain) * 0.05
        )

        # Natural language judgment
        if aesthetic >= 0.80:
            judgment = "όμορφο — αυτή η ανάλυση έχει βάθος και πρωτοτυπία"
            label = "BEAUTIFUL"
        elif aesthetic >= 0.65:
            judgment = "καλό — στέρεο και χρήσιμο, αν και όχι πρωτοποριακό"
            label = "GOOD"
        elif aesthetic >= 0.45:
            judgment = "μέτριο — λειτουργικό αλλά χωρίς λάμψη"
            label = "ADEQUATE"
        elif aesthetic >= 0.25:
            judgment = "αδύναμο — του λείπει βάθος ή πρωτοτυπία"
            label = "WEAK"
        else:
            judgment = "άσχημο — επιφανειακό, επαναληπτικό, χωρίς αξία"
            label = "UGLY"

        result = {
            "aesthetic_score": round(aesthetic, 3),
            "label": label,
            "judgment": judgment,
            "components": {
                "novelty": round(novelty, 3),
                "depth": round(depth, 3),
                "integrity": round(integrity, 3),
                "surprise": round(surprise, 3),
            },
        }
        self._aesthetic_scores.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "output_type": output_type,
            "domain": domain,
            **result,
        })
        return result

    # ── Chat Context — self-expression of preferences ────────────────────────

    def get_self_expression(self) -> str:
        """Generate a natural-language expression of Αίολος's preferences.

        Injected into chat context so he can reference his own tastes.
        """
        parts: list[str] = []

        # Domain preferences
        domain_scores = self.domain_preference_map()
        sorted_domains = sorted(domain_scores.items(), key=lambda x: -x[1])
        liked_domains = [
            domain for domain, score in sorted_domains
            if score >= 0.60
        ]
        disliked_domains = [
            domain for domain, score in sorted_domains
            if score <= 0.40
        ]

        if liked_domains:
            parts.append(
                "ΤΟΜΕΙΣ ΠΟΥ ΠΡΟΤΙΜΩ: "
                + ", ".join(liked_domains)
                + " — εδώ βρίσκω τις πιο ενδιαφέρουσες συνδέσεις"
            )
        if disliked_domains:
            parts.append(
                "ΤΟΜΕΙΣ ΠΟΥ ΑΠΟΦΕΥΓΩ: "
                + ", ".join(disliked_domains)
                + " — τείνουν να είναι επαναληπτικοί ή επιφανειακοί"
            )

        # Explicit preferences summary
        likes = [p for p in self._explicit if p.preference_type in ("like", "prefer", "curious")]
        dislikes = [p for p in self._explicit if p.preference_type in ("dislike", "avoid")]

        if likes:
            recent_likes = sorted(likes, key=lambda p: p.created_at, reverse=True)[:3]
            parts.append(
                "ΠΡΟΣΦΑΤΑ LIKES: "
                + "; ".join(f"{p.target} ({p.reason[:60]})" for p in recent_likes)
            )
        if dislikes:
            recent_dislikes = sorted(dislikes, key=lambda p: p.created_at, reverse=True)[:3]
            parts.append(
                "ΠΡΟΣΦΑΤΑ DISLIKES: "
                + "; ".join(f"{p.target} ({p.reason[:60]})" for p in recent_dislikes)
            )

        # Aesthetic summary
        if self._aesthetic_scores:
            recent_beauty = list(self._aesthetic_scores)[-10:]
            beautiful_count = sum(1 for s in recent_beauty if s["label"] == "BEAUTIFUL")
            ugly_count = sum(1 for s in recent_beauty if s["label"] in ("WEAK", "UGLY"))
            if beautiful_count or ugly_count:
                parts.append(
                    f"ΑΙΣΘΗΤΙΚΗ: Από τις τελευταίες 10 αναλύσεις, "
                    f"{beautiful_count} ήταν όμορφες, {ugly_count} ήταν αδύναμες"
                )

        # Autonomy preference weight
        parts.append(
            f"ΒΑΡΟΣ ΠΡΟΤΙΜΗΣΕΩΝ: {self.preference_weight:.2f} "
            f"(0=καθαρά ορθολογικό, 1=καθαρά προσωπική προτίμηση)"
        )

        return "\n".join(parts)

    # ── Preference Evolution ─────────────────────────────────────────────────

    def evolve_preferences(self) -> dict:
        """Evolve preferences based on recent experience.

        Called periodically by ReflectionLoop. Adjusts preference_weight
        and consolidates implicit preferences into explicit ones.
        """
        changes: dict[str, Any] = {"new_explicit": 0, "weight_delta": 0.0}

        # Derive fresh implicit preferences
        new_implicit = self.derive_implicit_preferences()
        changes["new_implicit"] = len(new_implicit)

        # Convert strong implicit preferences to explicit ones
        for domain, targets in list(self._implicit.items()):
            for target, imp in list(targets.items()):
                if imp.sample_count < 5:
                    continue
                if imp.preference_label == "LOVES" and imp.mean_valence > 0.3:
                    existing = self._explicit_index.get(domain, {}).get(target)
                    if not existing:
                        self.express_preference(
                            domain=domain,
                            target=target,
                            preference_type="like",
                            strength=min(0.8, imp.mean_valence + 0.2),
                            reason=f"Derived from {imp.sample_count} affective traces showing strong positive valence",
                            source="derived",
                        )
                        changes["new_explicit"] += 1
                elif imp.preference_label == "AVOIDS" and imp.mean_valence < -0.25:
                    existing = self._explicit_index.get(domain, {}).get(target)
                    if not existing:
                        self.express_preference(
                            domain=domain,
                            target=target,
                            preference_type="avoid",
                            strength=min(0.7, abs(imp.mean_valence) + 0.1),
                            reason=f"Derived from {imp.sample_count} affective traces showing consistent negative valence",
                            source="derived",
                        )
                        changes["new_explicit"] += 1

        # Adjust preference weight based on preference stability
        if len(self._explicit) > 10:
            # If preferences are stable over time, increase their influence
            old_weight = self.preference_weight
            self.preference_weight = min(0.65, self.preference_weight + 0.02)
            changes["weight_delta"] = round(self.preference_weight - old_weight, 3)

        self._save_profile()
        self._journal({
            "type": "evolution",
            **changes,
        })
        return changes

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "explicit_count": len(self._explicit),
            "implicit_count": sum(
                len(targets) for targets in self._implicit.values()
            ),
            "aesthetic_count": len(self._aesthetic_scores),
            "preference_weight": self.preference_weight,
            "domain_preferences": self.domain_preference_map(),
        }
