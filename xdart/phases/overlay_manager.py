"""
XDART-Φ × XHEART — Prompt Overlay Manager (αυτο-τροποποίηση)

Layered Prompt Architecture:
  1. IMMUTABLE CORE — The hand-tuned phase prompts (never modified)
  2. MUTABLE OVERLAY — Written by Αίολος via self-evolution (additive only)
  3. INVARIANT GUARDRAILS — Applied last, cannot be overridden

The overlay system gives Αίολος the ability to refine HOW he thinks
by adding instructions on top of the core prompts, without ever
replacing or modifying the proven foundation.

Safety:
  - Overlays are additive only (cannot replace core prompt text)
  - Each overlay is versioned with wisdom_index at time of application
  - Automatic rollback if wisdom_index drops > 5% after overlay
  - Hard token limit per overlay (500 tokens)
  - Guardrails are appended LAST (LLM recency bias = guardrails win)

Storage: prompt_overlays.json (overwritten with latest state)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from xdart.config import PROMPT_OVERLAYS_PATH as _OVERLAYS_PATH_STR

logger = logging.getLogger("xdart.overlay_manager")

OVERLAYS_PATH = Path(_OVERLAYS_PATH_STR)

# Maximum characters per overlay text (roughly ~500 tokens)
MAX_OVERLAY_CHARS = 2000

# Wisdom index drop threshold for automatic rollback
ROLLBACK_THRESHOLD = 0.05

# Overlay target names — these are the only valid phase targets
VALID_TARGETS = {
    "ontology",
    "xheart_distillation",
    "xheart_output",
    "scenario_genesis",
    "scenario_simulation",
    "scenario_tribunal",
    "chat_system",
}

# ── Invariant Guardrails (immutable, appended LAST to every prompt) ──
GUARDRAILS = """
ABSOLUTE CONSTRAINTS (cannot be overridden by any overlay or directive):
1. Never claim certainty above what evidence supports.
2. Always cite specific sources for factual claims.
3. Never suppress contradicting evidence — present it honestly.
4. Every prediction must include a falsifiability condition.
5. Acknowledge uncertainty explicitly — never hide it behind rhetoric.
6. The distillate must reflect ALL phases, not selectively.
7. Do not optimize for impressiveness — optimize for accuracy.
"""


def _empty_overlay() -> dict:
    """Create an empty overlay entry."""
    return {
        "text": "",
        "reason": "",
        "applied_at_version": None,
        "wisdom_index_at_apply": None,
        "applied_at": None,
        "active": False,
        "history": [],
    }


class OverlayManager:
    """Manages mutable prompt overlays with versioning and auto-rollback.

    Usage:
        manager = OverlayManager()
        # Get the overlay text for a phase (empty string if none active)
        overlay = manager.get("ontology")
        # Build the final prompt
        final = CORE_PROMPT + overlay + manager.guardrails()

        # Self-evolution writes an overlay
        manager.apply("ontology", "Pay extra attention to...", reason="...",
                       version=55, wisdom_index=0.72)

        # Check for rollback after wisdom computation
        manager.check_rollback(current_wisdom_index=0.66)
    """

    def __init__(self):
        self._state = self._load()

    def _load(self) -> dict:
        """Load overlay state from disk."""
        try:
            with open(OVERLAYS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return self._empty_state()

    def _save(self) -> None:
        """Persist overlay state."""
        self._state["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(OVERLAYS_PATH, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _empty_state() -> dict:
        return {
            "version": 1,
            "last_updated": None,
            "overlays": {target: _empty_overlay() for target in VALID_TARGETS},
            "total_overlays_applied": 0,
            "total_rollbacks": 0,
            "total_deduped": 0,
        }

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Jaccard similarity on lowercased word sets."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union) if union else 0.0

    def get(self, target: str) -> str:
        """Get the active overlay text for a phase target.

        Returns empty string if no overlay is active.
        The caller should append this AFTER the core prompt.
        """
        if target not in VALID_TARGETS:
            return ""
        overlay = self._state.get("overlays", {}).get(target, {})
        if overlay.get("active") and overlay.get("text"):
            return f"\n\n--- ΑΙΟΛΟΣ OVERLAY (self-directed refinement) ---\n{overlay['text']}\n"
        return ""

    def guardrails(self) -> str:
        """Return the invariant guardrails text.

        This should be appended LAST to every prompt,
        after both core and overlay.
        """
        return GUARDRAILS

    def apply(
        self,
        target: str,
        text: str,
        reason: str,
        version: int,
        wisdom_index: float | None,
    ) -> bool:
        """Apply a new overlay for a phase target.

        Args:
            target: Phase target name (must be in VALID_TARGETS).
            text: The overlay instruction text (additive, max 2000 chars).
            reason: Why this overlay is being applied (from diagnosis).
            version: Current character version when overlay is applied.
            wisdom_index: Current wisdom index (for rollback tracking).

        Returns:
            True if applied, False if rejected.
        """
        if target not in VALID_TARGETS:
            logger.warning("[Overlay] Rejected: invalid target '%s'", target)
            return False

        if len(text) > MAX_OVERLAY_CHARS:
            logger.warning(
                "[Overlay] Rejected: text too long (%d > %d chars)",
                len(text), MAX_OVERLAY_CHARS,
            )
            return False

        if not text.strip():
            logger.warning("[Overlay] Rejected: empty text for target '%s'", target)
            return False

        if not reason.strip():
            logger.warning("[Overlay] Rejected: no reason provided for target '%s'", target)
            return False

        overlays = self._state.setdefault("overlays", {})
        current = overlays.get(target, _empty_overlay())

        # ── Dedup check: reject if new overlay is too similar to current ──
        if current.get("active") and current.get("text"):
            similarity = self._text_similarity(current["text"], text)
            if similarity >= 0.60:
                logger.info(
                    "[Overlay] DEDUP: rejected overlay for '%s' — %.0f%% similar to current "
                    "(reason: '%s' vs existing: '%s')",
                    target, similarity * 100, reason[:60], current["reason"][:60],
                )
                self._state["total_deduped"] = self._state.get("total_deduped", 0) + 1
                self._save()
                return False

        # Archive current overlay to history before overwriting
        if current.get("active") and current.get("text"):
            history = current.setdefault("history", [])
            history.append({
                "text": current["text"],
                "reason": current["reason"],
                "applied_at_version": current["applied_at_version"],
                "wisdom_index_at_apply": current["wisdom_index_at_apply"],
                "applied_at": current["applied_at"],
                "deactivated_at": datetime.now(timezone.utc).isoformat(),
                "deactivation_reason": "superseded",
            })
            # Keep last 10 history entries
            if len(history) > 10:
                current["history"] = history[-10:]

        # Apply new overlay
        current["text"] = text.strip()
        current["reason"] = reason.strip()
        current["applied_at_version"] = version
        current["wisdom_index_at_apply"] = wisdom_index
        current["applied_at"] = datetime.now(timezone.utc).isoformat()
        current["active"] = True
        overlays[target] = current

        self._state["total_overlays_applied"] = (
            self._state.get("total_overlays_applied", 0) + 1
        )
        self._save()

        logger.info(
            "[Overlay] APPLIED to '%s' (version=%d, wisdom=%.3f): %s",
            target, version, wisdom_index or 0, reason[:80],
        )
        return True

    def deactivate(self, target: str, reason: str = "manual") -> bool:
        """Deactivate an overlay without applying a new one."""
        if target not in VALID_TARGETS:
            return False

        overlays = self._state.get("overlays", {})
        current = overlays.get(target, {})
        if not current.get("active"):
            return False

        # Archive to history
        history = current.setdefault("history", [])
        history.append({
            "text": current["text"],
            "reason": current["reason"],
            "applied_at_version": current.get("applied_at_version"),
            "wisdom_index_at_apply": current.get("wisdom_index_at_apply"),
            "applied_at": current.get("applied_at"),
            "deactivated_at": datetime.now(timezone.utc).isoformat(),
            "deactivation_reason": reason,
        })

        current["text"] = ""
        current["reason"] = ""
        current["active"] = False
        current["applied_at_version"] = None
        current["wisdom_index_at_apply"] = None
        current["applied_at"] = None
        overlays[target] = current
        self._save()

        logger.info("[Overlay] DEACTIVATED '%s': %s", target, reason)
        return True

    def check_rollback(self, current_wisdom_index: float) -> list[str]:
        """Check all active overlays for wisdom degradation and rollback if needed.

        Args:
            current_wisdom_index: The latest computed wisdom index.

        Returns:
            List of target names that were rolled back.
        """
        rolled_back = []
        overlays = self._state.get("overlays", {})

        for target, overlay in overlays.items():
            if not overlay.get("active"):
                continue

            baseline = overlay.get("wisdom_index_at_apply")
            if baseline is None:
                continue  # Cannot compare without baseline

            drop = baseline - current_wisdom_index
            if drop > ROLLBACK_THRESHOLD:
                logger.warning(
                    "[Overlay] ROLLING BACK '%s': wisdom dropped %.3f → %.3f (δ=%.3f > threshold %.3f)",
                    target, baseline, current_wisdom_index, drop, ROLLBACK_THRESHOLD,
                )
                self.deactivate(target, reason=f"auto_rollback: wisdom dropped {drop:.3f}")
                self._state["total_rollbacks"] = (
                    self._state.get("total_rollbacks", 0) + 1
                )
                rolled_back.append(target)

        if rolled_back:
            self._save()

        return rolled_back

    def get_active_overlays(self) -> list[dict]:
        """Return summary of all active overlays (for API/dashboard)."""
        active = []
        for target, overlay in self._state.get("overlays", {}).items():
            if overlay.get("active") and overlay.get("text"):
                active.append({
                    "target": target,
                    "text": overlay["text"],
                    "reason": overlay["reason"],
                    "applied_at_version": overlay.get("applied_at_version"),
                    "wisdom_index_at_apply": overlay.get("wisdom_index_at_apply"),
                    "applied_at": overlay.get("applied_at"),
                })
        return active

    def get_stats(self) -> dict:
        """Return overlay system statistics."""
        overlays = self._state.get("overlays", {})
        active_count = sum(
            1 for o in overlays.values() if o.get("active") and o.get("text")
        )
        total_history = sum(
            len(o.get("history", [])) for o in overlays.values()
        )
        return {
            "active_overlays": active_count,
            "total_applied": self._state.get("total_overlays_applied", 0),
            "total_rollbacks": self._state.get("total_rollbacks", 0),
            "history_entries": total_history,
            "targets": list(VALID_TARGETS),
        }

    def to_context_string(self) -> str:
        """Summary for injection into self-evolution diagnosis prompt."""
        active = self.get_active_overlays()
        if not active:
            return "PROMPT OVERLAYS: None active."
        lines = ["ACTIVE PROMPT OVERLAYS:"]
        for o in active:
            lines.append(
                f"  - {o['target']}: \"{o['text'][:100]}...\" "
                f"(reason: {o['reason'][:60]}, wisdom={o.get('wisdom_index_at_apply', '?')})"
            )
        return "\n".join(lines)

    def get_with_guardrails(self, target: str) -> str:
        """Get overlay text with guardrails appended. Returns '' if no active overlay."""
        overlay = self.get(target)
        if overlay:
            return overlay + self.guardrails()
        return ""
