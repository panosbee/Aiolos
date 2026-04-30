"""
XDART-Φ × XHEART — Wisdom Calibration Tracker (σοφία)

Σοφία = good judgment under uncertainty, with ethical and temporal consistency.

This module tracks whether the system's judgments are actually GOOD,
not just linguistically impressive. It measures:

  1. PREDICTION CALIBRATION — Are confidence levels accurate?
     (Do things I say with 80% confidence happen ~80% of the time?)
  2. JUDGMENT QUALITY — Over time, are my assessments vindicated or refuted?
  3. EPISTEMIC HUMILITY — Am I appropriately uncertain?
  4. CONSISTENCY — Do I contradict myself without good reason?
  5. SECOND-ORDER ACCURACY — Can I correctly predict my own accuracy?

This is the hardest module to build because wisdom cannot be declared,
only demonstrated over time. The tracker collects evidence patiently.

Storage: wisdom_calibration.json (overwritten with latest state)
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from xdart.config import WISDOM_CALIBRATION_PATH as _WISDOM_PATH_STR
from xdart.llm import LLMClient

logger = logging.getLogger("xdart.wisdom")

CALIBRATION_PATH = Path(_WISDOM_PATH_STR)


class WisdomCalibrationTracker:
    """Tracks long-term judgment quality and calibration.

    Works by collecting confidence-tagged claims from pipeline runs and
    introspection reports, then tracking them against reality.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self._state = self._load()

    def _load(self) -> dict:
        """Load current calibration state."""
        try:
            with open(CALIBRATION_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return self._empty_state()

    def _save(self) -> None:
        """Persist calibration state."""
        self._state["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(CALIBRATION_PATH, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _empty_state() -> dict:
        return {
            "version": 1,
            "last_updated": None,
            "calibration_buckets": {
                "0.9": {"total": 0, "correct": 0},
                "0.8": {"total": 0, "correct": 0},
                "0.7": {"total": 0, "correct": 0},
                "0.6": {"total": 0, "correct": 0},
                "0.5": {"total": 0, "correct": 0},
            },
            "total_claims_tracked": 0,
            "total_claims_resolved": 0,
            "pending_claims": [],
            "integrity_scores": [],
            "brier_scores": [],
            "wisdom_index": None,
            "consistency_violations": 0,
            "humility_ratio": None,
            "self_accuracy_predictions": [],
        }

    def record_integrity_score(self, score: float) -> None:
        """Record an epistemic integrity score from introspection."""
        scores = self._state.setdefault("integrity_scores", [])
        scores.append({
            "score": score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 100
        if len(scores) > 100:
            self._state["integrity_scores"] = scores[-100:]
        self._save()

    def record_brier_score(self, score: float) -> None:
        """Record a Brier score from prophecy evaluation."""
        brier = self._state.setdefault("brier_scores", [])
        brier.append({
            "score": score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(brier) > 100:
            self._state["brier_scores"] = brier[-100:]
        self._save()

    def record_confidence_claim(
        self,
        claim: str,
        confidence: float,
        source_run: int,
        deadline: str | None = None,
    ) -> None:
        """Record a confidence-tagged claim for future tracking.

        Args:
            claim: The specific prediction or assessment.
            confidence: 0.0-1.0 confidence level.
            source_run: Which pipeline run generated this.
            deadline: Optional date by which the claim can be verified.
        """
        # Bucket to nearest calibration level
        bucket = str(round(max(0.5, min(0.9, confidence)), 1))

        pending = self._state.setdefault("pending_claims", [])
        pending.append({
            "claim": claim[:500],
            "confidence": confidence,
            "bucket": bucket,
            "source_run": source_run,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "deadline": deadline,
            "resolved": False,
            "outcome": None,
        })

        self._state["total_claims_tracked"] = self._state.get("total_claims_tracked", 0) + 1

        # Cap pending claims at 200
        if len(pending) > 200:
            self._state["pending_claims"] = pending[-200:]

        self._save()
        logger.info("[Wisdom] Claim recorded (confidence=%.2f, bucket=%s): %s",
                     confidence, bucket, claim[:80])

    def resolve_claim(self, claim_index: int, correct: bool) -> None:
        """Mark a pending claim as resolved.

        Args:
            claim_index: Index in pending_claims list.
            correct: Whether the claim turned out to be correct.
        """
        pending = self._state.get("pending_claims", [])
        if 0 <= claim_index < len(pending):
            entry = pending[claim_index]
            entry["resolved"] = True
            entry["outcome"] = "correct" if correct else "incorrect"
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()

            # Update calibration bucket
            bucket = entry.get("bucket", "0.5")
            buckets = self._state.get("calibration_buckets", {})
            if bucket in buckets:
                buckets[bucket]["total"] += 1
                if correct:
                    buckets[bucket]["correct"] += 1

            self._state["total_claims_resolved"] = self._state.get("total_claims_resolved", 0) + 1
            self._save()
            logger.info("[Wisdom] Claim resolved: %s — %s",
                         entry["claim"][:60], "correct" if correct else "incorrect")

    def compute_wisdom_index(self) -> dict:
        """Compute the composite wisdom index from all available data.

        Returns:
            dict with calibration_error, avg_integrity, avg_brier,
            humility_ratio, consistency_score, and composite wisdom_index.
        """
        # 1. Calibration error (how well do confidence levels match reality?)
        buckets = self._state.get("calibration_buckets", {})
        calibration_errors = []
        total_resolved_in_buckets = sum(d["total"] for d in buckets.values())
        # Use lower threshold (n>=1) if total resolved claims < 20 (early bootstrap)
        min_bucket_n = 1 if total_resolved_in_buckets < 20 else 3
        for intended_conf, data in buckets.items():
            if data["total"] >= min_bucket_n:
                actual_rate = data["correct"] / data["total"]
                error = abs(float(intended_conf) - actual_rate)
                calibration_errors.append(error)
        avg_cal_error = sum(calibration_errors) / len(calibration_errors) if calibration_errors else None

        # Low-data fallback: if no bucket qualifies, compute raw accuracy
        if avg_cal_error is None and total_resolved_in_buckets > 0:
            total_correct = sum(d["correct"] for d in buckets.values())
            avg_cal_error = 1.0 - (total_correct / total_resolved_in_buckets)  # rough proxy

        # 2. Average epistemic integrity
        integrity_scores = [s["score"] for s in self._state.get("integrity_scores", [])[-20:]]
        avg_integrity = sum(integrity_scores) / len(integrity_scores) if integrity_scores else None

        # 3. Average Brier score
        brier_scores = [s["score"] for s in self._state.get("brier_scores", [])[-20:]]
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

        # 4. Humility ratio (what fraction of claims are in lower confidence buckets?)
        total_claims = self._state.get("total_claims_tracked", 0)
        humility = None
        if total_claims > 0:
            pending = self._state.get("pending_claims", [])
            high_conf = sum(1 for p in pending if float(p.get("bucket", "0.5")) >= 0.8)
            humility = 1.0 - (high_conf / len(pending)) if pending else 0.5

        # 5. Composite wisdom index (0-1, higher is better)
        components = []
        if avg_cal_error is not None:
            components.append(1.0 - min(avg_cal_error, 1.0))  # lower cal error = better
        if avg_integrity is not None:
            components.append(avg_integrity)
        if avg_brier is not None:
            components.append(1.0 - min(avg_brier, 1.0))  # lower Brier = better
        if humility is not None:
            components.append(humility * 0.5 + 0.5)  # moderate humility is ideal

        # Bootstrap mode: if we have integrity scores but no resolved claims yet,
        # return an integrity-only index rather than None.  This prevents the wisdom
        # tracker from being "offline" (0.000) during the first days of operation
        # before any predictions can be resolved.  The index is clearly labeled as
        # preliminary so overlays know the data is sparse.
        if components:
            wisdom_index = sum(components) / len(components)
        elif avg_integrity is not None:
            # Integrity-only bootstrap — no calibration data yet
            wisdom_index = avg_integrity
            logger.info("[Wisdom] Bootstrap mode — using integrity-only index (no resolved claims yet)")
        else:
            wisdom_index = None

        result = {
            "calibration_error": avg_cal_error,
            "avg_integrity": avg_integrity,
            "avg_brier": avg_brier,
            "humility_ratio": humility,
            "wisdom_index": wisdom_index,
            "data_points": {
                "integrity_samples": len(integrity_scores),
                "brier_samples": len(brier_scores),
                "calibrated_buckets": len(calibration_errors),
                "total_claims": total_claims,
                "resolved_claims": self._state.get("total_claims_resolved", 0),
            },
        }

        # Save to state
        self._state["wisdom_index"] = wisdom_index
        self._state["humility_ratio"] = humility
        self._save()

        logger.info("[Wisdom] Index computed: %.3f (cal=%.3f, integrity=%.2f, brier=%.3f)",
                     wisdom_index or 0, avg_cal_error or 0, avg_integrity or 0, avg_brier or 0)
        return result

    def get_calibration_report(self) -> str:
        """Human-readable calibration report."""
        buckets = self._state.get("calibration_buckets", {})
        lines = ["=== WISDOM CALIBRATION REPORT ===\n"]

        for conf, data in sorted(buckets.items(), reverse=True):
            if data["total"] > 0:
                actual = data["correct"] / data["total"]
                lines.append(
                    f"  Confidence {conf}: {data['correct']}/{data['total']} correct "
                    f"({actual:.0%} actual vs {float(conf):.0%} expected)"
                )
            else:
                lines.append(f"  Confidence {conf}: no data yet")

        wisdom = self._state.get("wisdom_index")
        if wisdom is not None:
            lines.append(f"\n  Composite Wisdom Index: {wisdom:.3f}")
        else:
            lines.append("\n  Composite Wisdom Index: insufficient data")

        return "\n".join(lines)

    def to_context_string(self) -> str:
        """Summary for injection into system prompts."""
        wisdom = self._state.get("wisdom_index")
        total = self._state.get("total_claims_tracked", 0)
        resolved = self._state.get("total_claims_resolved", 0)

        integrity = [s["score"] for s in self._state.get("integrity_scores", [])[-10:]]
        avg_integrity_now = sum(integrity) / len(integrity) if integrity else None

        if wisdom is None and total == 0 and avg_integrity_now is None:
            return ""

        ctx = "WISDOM CALIBRATION: "
        if wisdom is not None:
            ctx += f"Index={wisdom:.2f} "
        elif avg_integrity_now is not None:
            ctx += f"Index={avg_integrity_now:.2f}(bootstrap) "
        ctx += f"(Claims tracked={total}, resolved={resolved})"

        if avg_integrity_now is not None:
            ctx += f" Avg integrity={avg_integrity_now:.2f}"

        return ctx

    def auto_resolve_expired_claims(self) -> int:
        """Auto-resolve pending claims whose deadlines have passed.

        Claims past their deadline without being resolved by the prophecy resolver
        are marked as 'expired' (neither correct nor incorrect) and their bucket
        count is incremented with correct=False (conservative: unverified = miss).

        Returns the number of claims resolved.
        """
        now = datetime.now(timezone.utc)
        pending = self._state.get("pending_claims", [])
        resolved_count = 0

        for claim in pending:
            if claim.get("resolved"):
                continue

            deadline_str = claim.get("deadline")
            if not deadline_str:
                continue

            try:
                # Parse deadline
                deadline = datetime.fromisoformat(
                    deadline_str.replace("Z", "+00:00")
                )
                if not deadline.tzinfo:
                    deadline = deadline.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                # Try YYYY-MM-DD format
                try:
                    deadline = datetime.strptime(deadline_str[:10], "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except (ValueError, TypeError):
                    continue

            if deadline >= now:
                continue  # Not yet expired

            # Mark as expired (unverified)
            claim["resolved"] = True
            claim["outcome"] = "expired_unverified"
            claim["resolved_at"] = now.isoformat()

            # Update calibration bucket (conservative: count as miss)
            bucket = claim.get("bucket", "0.5")
            buckets = self._state.get("calibration_buckets", {})
            if bucket in buckets:
                buckets[bucket]["total"] += 1
                # Do NOT increment correct — unverified = assumed miss

            self._state["total_claims_resolved"] = (
                self._state.get("total_claims_resolved", 0) + 1
            )
            resolved_count += 1

        if resolved_count:
            self._save()
            logger.info(
                "[Wisdom] Auto-resolved %d expired claims (conservative: counted as misses)",
                resolved_count,
            )

        return resolved_count
