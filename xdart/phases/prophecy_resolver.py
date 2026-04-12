"""
XDART-Φ — Prophecy Resolution Checker

This is what closes the loop between prediction and reality.

The system has 41+ stored prophecies and prophetic bets with specific
deadlines. This module:

  1. Scans all prophecies/bets with passed deadlines
  2. Retrieves current world data (GDELT, RSS, indicators)
  3. Uses LLM to evaluate: did the prediction come true? (binary)
  4. Computes real Brier scores
  5. Updates WisdomCalibrationTracker with actual calibration data
  6. Marks prophecies as confirmed/disconfirmed/expired

Without this, every confidence number in the system is decorative.
With this, the system learns from its actual prediction record.

Runs as:
  - Background task (every 6 hours)
  - On-demand via API (GET /xdart/resolve-prophecies)
"""

import json
import logging
import time
from datetime import datetime, timezone

from xdart.llm import LLMClient

logger = logging.getLogger("xdart.prophecy_resolver")


RESOLUTION_PROMPT = """\
You are a STRICT BINARY JUDGE. No hedging. No nuance. Just truth.

You are evaluating whether a specific prediction came true.

PREDICTION:
  Statement: {statement}
  Deadline: {deadline}
  Original confidence: {confidence}
  Mechanism: {mechanism}
  Tracking signal: {tracking_signal}

CURRENT DATE: {current_date}

AVAILABLE EVIDENCE (recent world data):
{evidence}

YOUR TASK:
Determine the outcome. This is BINARY — no "partially confirmed."

Decision criteria:
- CONFIRMED: The specific event described in the statement observably happened
  before the deadline. Not "something similar" — the actual thing described.
- DISCONFIRMED: The deadline passed and the event did NOT happen, OR evidence
  shows it clearly will not happen (contradictory events occurred).
- EXPIRED: The deadline passed but there is genuinely insufficient evidence to
  determine either way. Use this RARELY — most predictions can be judged.
- STILL_ACTIVE: The deadline has NOT yet passed and the prediction is still plausible.

BE HARSH. The purpose of this evaluation is to find out where the system
is wrong, not to make it feel good. If the prediction was vague enough to
be "technically" confirmed by anything, that's a design flaw — note it.

Respond ONLY with valid JSON:
{
  "outcome": "confirmed" | "disconfirmed" | "expired" | "still_active",
  "evidence_summary": "What specific evidence supports this judgment — 2-3 sentences",
  "was_prediction_specific_enough": true | false,
  "specificity_note": "If false, explain what was vague",
  "confidence_in_judgment": 0.0-1.0
}"""


class ProphecyResolver:
    """Automated prophecy resolution — closes the Brier loop."""

    def __init__(
        self,
        llm: LLMClient,
        prophetic_memory,
        wisdom_tracker,
        world_context=None,
    ):
        self.llm = llm
        self.prophetic_memory = prophetic_memory
        self.wisdom_tracker = wisdom_tracker
        self.world_context = world_context
        self._last_run_result = None

    def resolve_all(self) -> dict:
        """Scan all prophecies, resolve any with passed deadlines.

        Returns summary of resolution actions taken.
        """
        t0 = time.perf_counter()
        logger.info("[ProphecyResolver] Starting resolution scan")

        all_prophecies = self.prophetic_memory.list_all(limit=500)
        now = datetime.now(timezone.utc)
        current_date = now.strftime("%Y-%m-%d")

        # Separate into categories
        needs_resolution = []
        already_resolved = []
        still_active = []

        for p in all_prophecies:
            status = p.get("tracking_status", "active")

            if status in ("confirmed", "disconfirmed", "expired"):
                already_resolved.append(p)
                continue

            # Check if this has a deadline that's passed
            deadline = self._extract_deadline(p)
            if deadline and deadline < now:
                needs_resolution.append(p)
            else:
                still_active.append(p)

        logger.info(
            "[ProphecyResolver] Found %d total prophecies: %d need resolution, %d already resolved, %d still active",
            len(all_prophecies), len(needs_resolution), len(already_resolved), len(still_active),
        )

        # Log next upcoming deadline for visibility
        if still_active:
            next_deadlines = []
            for p in still_active:
                d = self._extract_deadline(p)
                if d:
                    next_deadlines.append((d, self._get_prophecy_name(p)))
            if next_deadlines:
                next_deadlines.sort(key=lambda x: x[0])
                nd, nn = next_deadlines[0]
                days_until = (nd - now).days
                logger.info(
                    "[ProphecyResolver] Next deadline: %s (%s) in %d days (%d prophecies have deadlines)",
                    nn[:50], nd.strftime("%Y-%m-%d"), days_until, len(next_deadlines),
                )

        if not needs_resolution:
            # Even with 0 new resolutions, compute accuracy stats from
            # previously-resolved prophecies (e.g. resolved by prophetic loop)
            # and feed their Brier scores to wisdom tracker.
            accuracy = self.prophetic_memory.compute_accuracy_stats()
            if accuracy.get("avg_brier_score") is not None:
                self.wisdom_tracker.record_brier_score(accuracy["avg_brier_score"])
                logger.info(
                    "[ProphecyResolver] No new resolutions but %d already resolved — "
                    "aggregate Brier=%.4f fed to wisdom tracker",
                    len(already_resolved), accuracy["avg_brier_score"],
                )

            # Auto-resolve expired wisdom claims
            expired_claims = self.wisdom_tracker.auto_resolve_expired_claims()

            # Recompute wisdom index with any new data
            wisdom = self.wisdom_tracker.compute_wisdom_index()

            result = {
                "resolved_this_run": 0,
                "total_prophecies": len(all_prophecies),
                "already_resolved": len(already_resolved),
                "still_active": len(still_active),
                "needs_resolution": 0,
                "accuracy_stats": accuracy,
                "wisdom_index": wisdom.get("wisdom_index"),
                "resolutions": [],
                "elapsed_seconds": round(time.perf_counter() - t0, 2),
            }
            self._last_run_result = result
            return result

        # Get current world data for evidence
        evidence = self._gather_evidence()

        # Resolve each prophecy
        resolutions = []
        confirmed_count = 0
        disconfirmed_count = 0
        expired_count = 0

        for p in needs_resolution:
            try:
                resolution = self._resolve_single(p, evidence, current_date)
                resolutions.append(resolution)

                outcome = resolution.get("outcome", "expired")

                # Update prophecy status in memory
                self.prophetic_memory.update_tracking_status(
                    entry_id=p.get("id", ""),
                    new_status=outcome if outcome != "still_active" else "tracking",
                    reality_check={
                        "checked_at": now.isoformat(),
                        "assessment": resolution.get("evidence_summary", ""),
                        "outcome": outcome,
                        "confidence_in_judgment": resolution.get("confidence_in_judgment", 0),
                        "was_specific_enough": resolution.get("was_prediction_specific_enough", True),
                        "resolver": "automated",
                    },
                )

                # Update wisdom tracker with real calibration data
                if outcome == "confirmed":
                    confirmed_count += 1
                    self._update_wisdom(p, correct=True)
                elif outcome == "disconfirmed":
                    disconfirmed_count += 1
                    self._update_wisdom(p, correct=False)
                elif outcome == "expired":
                    expired_count += 1

                logger.info(
                    "[ProphecyResolver] %s → %s (confidence_in_judgment=%.2f)",
                    self._get_prophecy_name(p)[:60],
                    outcome,
                    resolution.get("confidence_in_judgment", 0),
                )

            except Exception as e:
                logger.warning(
                    "[ProphecyResolver] Failed to resolve %s: %s",
                    p.get("id", "?")[:8], e,
                )
                resolutions.append({
                    "prophecy_id": p.get("id", "?"),
                    "outcome": "error",
                    "error": str(e),
                })

        # Compute fresh accuracy stats
        accuracy = self.prophetic_memory.compute_accuracy_stats()

        # Record aggregate Brier to wisdom tracker
        if accuracy.get("avg_brier_score") is not None:
            self.wisdom_tracker.record_brier_score(accuracy["avg_brier_score"])

        # Auto-resolve expired wisdom claims (deadlines that passed)
        expired_claims = self.wisdom_tracker.auto_resolve_expired_claims()

        # Recompute wisdom index with new data
        wisdom = self.wisdom_tracker.compute_wisdom_index()

        elapsed = time.perf_counter() - t0

        result = {
            "resolved_this_run": confirmed_count + disconfirmed_count + expired_count,
            "confirmed": confirmed_count,
            "disconfirmed": disconfirmed_count,
            "expired": expired_count,
            "total_prophecies": len(all_prophecies),
            "already_resolved": len(already_resolved),
            "still_active": len(still_active),
            "accuracy_stats": accuracy,
            "wisdom_index": wisdom.get("wisdom_index"),
            "resolutions": resolutions,
            "elapsed_seconds": round(elapsed, 2),
        }
        self._last_run_result = result

        logger.info(
            "[ProphecyResolver] Resolution complete in %.2fs: %d confirmed, %d disconfirmed, %d expired",
            elapsed, confirmed_count, disconfirmed_count, expired_count,
        )
        if accuracy.get("avg_brier_score") is not None:
            logger.info(
                "[ProphecyResolver] Aggregate Brier: %.4f (%s) | Confirmation rate: %s",
                accuracy["avg_brier_score"],
                accuracy.get("accuracy_rating", "?"),
                accuracy.get("confirmation_rate", "?"),
            )

        return result

    def _resolve_single(self, prophecy: dict, evidence: str, current_date: str) -> dict:
        """Evaluate a single prophecy against current evidence."""

        # Extract prediction details
        scenario = prophecy.get("scenario", {})
        statement = scenario.get("predicted_outcome", "")
        if not statement:
            statement = scenario.get("narrative", "")

        # Check for prophetic bet format
        bets = prophecy.get("bets", [])
        if bets and isinstance(bets, list):
            # This is a bets-format entry — resolve each bet
            return self._resolve_bet(bets[0] if bets else {}, evidence, current_date)

        deadline = self._extract_deadline(prophecy)
        deadline_str = deadline.strftime("%Y-%m-%d") if deadline else "unknown"
        confidence = prophecy.get("tribunal_score", scenario.get("confidence", 0.5))
        mechanism = prophecy.get("narrative", scenario.get("narrative", ""))
        tracking_signal = ""

        # Check conditions if available
        conditions = scenario.get("conditions", [])
        if conditions:
            cond_texts = []
            for c in conditions[:3]:
                if isinstance(c, dict):
                    cond_texts.append(c.get("description", ""))
                elif isinstance(c, str):
                    cond_texts.append(c)
            tracking_signal = "; ".join(cond_texts)

        prompt = RESOLUTION_PROMPT.format(
            statement=statement[:500],
            deadline=deadline_str,
            confidence=f"{confidence:.2f}",
            mechanism=mechanism[:300],
            tracking_signal=tracking_signal[:300],
            current_date=current_date,
            evidence=evidence[:3000],
        )

        result = self.llm.call_json(
            prompt,
            "Judge this prediction. Be strict and honest.",
            max_tokens=500,
            temperature=0.2,
        )

        result["prophecy_id"] = prophecy.get("id", "")
        result["prophecy_name"] = self._get_prophecy_name(prophecy)
        result["original_confidence"] = confidence
        return result

    def _resolve_bet(self, bet: dict, evidence: str, current_date: str) -> dict:
        """Resolve a single prophetic bet."""
        prompt = RESOLUTION_PROMPT.format(
            statement=bet.get("statement", bet.get("prediction", ""))[:500],
            deadline=bet.get("deadline", "unknown"),
            confidence=f"{bet.get('confidence', 0.5):.2f}",
            mechanism=bet.get("mechanism", "")[:300],
            tracking_signal=bet.get("tracking_signal", "")[:300],
            current_date=current_date,
            evidence=evidence[:3000],
        )

        result = self.llm.call_json(
            prompt,
            "Judge this prediction. Be strict and honest.",
            max_tokens=500,
            temperature=0.2,
        )

        result["bet_id"] = bet.get("bet_id", "")
        result["original_confidence"] = bet.get("confidence", 0.5)
        return result

    def _gather_evidence(self) -> str:
        """Retrieve current world data as evidence for resolution."""
        if not self.world_context:
            return "(No world data available — judging based on general knowledge only)"

        try:
            # Broad query to get recent world events
            ctx = self.world_context.retrieve("global events developments updates", hours_back=168)
            evidence = ctx.get("context_string", "")
            if evidence:
                logger.info("[ProphecyResolver] Gathered %d chars of world evidence", len(evidence))
                return evidence
        except Exception as e:
            logger.warning("[ProphecyResolver] World data retrieval failed: %s", e)

        return "(World data retrieval failed — judging based on general knowledge only)"

    def _update_wisdom(self, prophecy: dict, correct: bool) -> None:
        """Update wisdom tracker calibration with real outcome."""
        scenario = prophecy.get("scenario", {})
        confidence = prophecy.get("tribunal_score", scenario.get("confidence", 0.5))

        # Find the bucket
        bucket = str(round(max(0.5, min(0.9, confidence)), 1))

        # Directly update calibration bucket
        state = self.wisdom_tracker._state
        buckets = state.get("calibration_buckets", {})
        if bucket in buckets:
            buckets[bucket]["total"] += 1
            if correct:
                buckets[bucket]["correct"] += 1

        state["total_claims_resolved"] = state.get("total_claims_resolved", 0) + 1

        # Bridge: also mark matching pending claims as resolved
        # Match by overlapping text (prophecy statement vs claim text)
        prophecy_text = (
            scenario.get("predicted_outcome", "")
            or scenario.get("narrative", "")
            or ""
        ).lower()
        # Also check bets
        bets = prophecy.get("bets", [])
        bet_texts = []
        for b in (bets or []):
            if isinstance(b, dict):
                bet_texts.append((b.get("statement", "") or b.get("prediction", "") or "").lower())

        pending = state.get("pending_claims", [])
        resolved_count = 0
        for claim in pending:
            if claim.get("resolved"):
                continue
            claim_text = claim.get("claim", "").lower()
            if not claim_text:
                continue
            # Match if significant word overlap or substring match
            matched = False
            if prophecy_text and (
                prophecy_text[:80] in claim_text or claim_text[:80] in prophecy_text
            ):
                matched = True
            for bt in bet_texts:
                if bt and (bt[:80] in claim_text or claim_text[:80] in bt):
                    matched = True
                    break
            if matched:
                claim["resolved"] = True
                claim["outcome"] = "correct" if correct else "incorrect"
                claim["resolved_at"] = datetime.now(timezone.utc).isoformat()
                resolved_count += 1

        if resolved_count:
            logger.info("[ProphecyResolver] Also resolved %d matching pending wisdom claims", resolved_count)

        self.wisdom_tracker._save()

        # Also compute and record Brier score for this individual prediction
        outcome = 1.0 if correct else 0.0
        brier = (confidence - outcome) ** 2
        self.wisdom_tracker.record_brier_score(brier)

        logger.info(
            "[ProphecyResolver] Wisdom updated: confidence=%.2f, correct=%s, brier=%.4f, bucket=%s",
            confidence, correct, brier, bucket,
        )

    def _extract_deadline(self, prophecy: dict) -> datetime | None:
        """Extract the deadline from a prophecy in various formats.

        Search order (most explicit → least):
        1. Bets with explicit deadlines
        2. scenario.timeline / scenario.timeframe
        3. scenario.conditions (date hints)
        4. scenario.predicted_outcome (date hints)
        5. scenario.falsifiability (often says "within 6 months")
        6. simulation.forward_projection (extract LAST date from step-by-step)
        7. scenario.narrative / scenario.trajectory (date hints)
        8. Fallback: creation_date + 45 days
        """
        scenario = prophecy.get("scenario", {})

        # Try bets format (most explicit)
        bets = prophecy.get("bets", [])
        if bets and isinstance(bets, list):
            deadline_str = bets[0].get("deadline", "") if bets else ""
            if deadline_str:
                parsed = self._parse_date(deadline_str)
                if parsed:
                    return parsed

        # Try to parse timeline as a date or date range (check both field names)
        for key in ("timeline", "timeframe"):
            timeline = scenario.get(key, "")
            if timeline:
                parsed = self._parse_date(timeline)
                if parsed:
                    return parsed

        # Try conditions for date hints
        conditions = scenario.get("conditions", [])
        for c in conditions:
            if isinstance(c, dict):
                desc = c.get("description", "")
                parsed = self._parse_date(desc)
                if parsed:
                    return parsed

        # Try predicted_outcome for date hints
        predicted_outcome = scenario.get("predicted_outcome", "")
        if predicted_outcome:
            parsed = self._parse_date(predicted_outcome)
            if parsed:
                return parsed

        # Try falsifiability (often contains "within 6 months" or specific dates)
        falsifiability = scenario.get("falsifiability", "")
        if falsifiability:
            parsed = self._parse_date(falsifiability)
            if parsed:
                return parsed

        # Try simulation.forward_projection — extract the LAST date mentioned
        # (the final step represents the scenario's endpoint)
        simulation = prophecy.get("simulation", {})
        forward_proj = simulation.get("forward_projection", "")
        if forward_proj:
            timestamp = prophecy.get("timestamp", "")
            parsed = self._extract_last_date(forward_proj, created_at=timestamp)
            if parsed:
                return parsed

        # Try narrative and trajectory for any date hints
        for field in ("narrative", "trajectory"):
            text = scenario.get(field, "")
            if text:
                parsed = self._parse_date(text)
                if parsed:
                    return parsed

        # Fallback: prophecy created > 45 days ago → treat as expired
        # Geopolitical predictions have ~6 week shelf life before they need re-evaluation
        timestamp = prophecy.get("timestamp", "")
        if timestamp:
            try:
                created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                from datetime import timedelta
                deadline = created + timedelta(days=45)
                if deadline < datetime.now(timezone.utc):
                    logger.debug(
                        "[ProphecyResolver] No parseable deadline for '%s' — using 45-day fallback (created %s)",
                        self._get_prophecy_name(prophecy)[:50], timestamp[:10],
                    )
                    return deadline
            except (ValueError, TypeError):
                pass

        return None

    @staticmethod
    def _parse_date(text: str) -> datetime | None:
        """Try to extract a date from text. Handles many formats."""
        import re
        import calendar

        if not text or len(text) > 500:
            return None

        text_lower = text.lower().strip()

        # Try ISO format first: YYYY-MM-DD
        match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        month_map = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }

        # "by Month YYYY" or "Month YYYY" or "Month DD, YYYY"
        match = re.search(r'(?:by\s+)?(\w+)\s+(\d{4})', text_lower)
        if match:
            month_name, year = match.group(1), match.group(2)
            if month_name in month_map:
                month = month_map[month_name]
                last_day = calendar.monthrange(int(year), month)[1]
                try:
                    return datetime(int(year), month, last_day, tzinfo=timezone.utc)
                except ValueError:
                    pass

        # "Q1/Q2/Q3/Q4 YYYY" or "YYYY Q1"
        match = re.search(r'Q([1-4])\s*(\d{4})', text)
        if not match:
            match = re.search(r'(\d{4})\s*Q([1-4])', text)
            if match:
                year, quarter = int(match.group(1)), int(match.group(2))
                end_month = quarter * 3
                last_day = calendar.monthrange(year, end_month)[1]
                return datetime(year, end_month, last_day, tzinfo=timezone.utc)
        if match:
            quarter, year = int(match.group(1)), int(match.group(2))
            end_month = quarter * 3
            last_day = calendar.monthrange(year, end_month)[1]
            return datetime(year, end_month, last_day, tzinfo=timezone.utc)

        # "early/mid/late YYYY" or "beginning/end of YYYY"
        match = re.search(r'(early|beginning of|start of)\s+(\d{4})', text_lower)
        if match:
            return datetime(int(match.group(2)), 3, 31, tzinfo=timezone.utc)
        match = re.search(r'(mid|middle of)\s*[-–]?\s*(\d{4})', text_lower)
        if match:
            return datetime(int(match.group(2)), 6, 30, tzinfo=timezone.utc)
        match = re.search(r'(late|end of)\s+(\d{4})', text_lower)
        if match:
            return datetime(int(match.group(2)), 12, 31, tzinfo=timezone.utc)

        # "within N months" or "N-M months" (relative to now)
        match = re.search(r'within\s+(\d+)\s+months?', text_lower)
        if match:
            from datetime import timedelta
            months = int(match.group(1))
            return datetime.now(timezone.utc) + timedelta(days=months * 30)
        match = re.search(r'(\d+)\s*[-–to]+\s*(\d+)\s+months?', text_lower)
        if match:
            from datetime import timedelta
            max_months = int(match.group(2))
            return datetime.now(timezone.utc) + timedelta(days=max_months * 30)

        # "YYYY-YYYY" range → use end year
        match = re.search(r'(\d{4})\s*[-–]\s*(\d{4})', text)
        if match:
            end_year = int(match.group(2))
            if 2020 <= end_year <= 2035:
                return datetime(end_year, 6, 30, tzinfo=timezone.utc)

        # Bare "YYYY" — only if it seems like a deadline year (2024-2030)
        match = re.search(r'\b(202[4-9]|203[0-5])\b', text)
        if match:
            year = int(match.group(1))
            return datetime(year, 12, 31, tzinfo=timezone.utc)

        return None

    def _extract_last_date(self, text: str, created_at: str = "") -> datetime | None:
        """Extract the LAST (furthest future) date from a long text like forward_projection.

        Scans for all date-like patterns and returns the latest one.
        Handles formats like: "April-June 2026", "2027", "July-Dec 2026",
        "Step 3 (2027-2028)", "Q3 2027", "6-12 months", "within 3 months", etc.
        """
        import re
        import calendar
        from datetime import timedelta

        if not text or len(text) < 10:
            return None

        text_lower = text.lower()
        candidates = []

        # Anchor for relative time references
        if created_at:
            try:
                anchor = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                anchor = datetime.now(timezone.utc)
        else:
            anchor = datetime.now(timezone.utc)

        month_map = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }

        # ISO dates: YYYY-MM-DD
        for m in re.finditer(r'(\d{4})-(\d{2})-(\d{2})', text):
            try:
                candidates.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc))
            except ValueError:
                pass

        # "Month YYYY" or "Month-Month YYYY" (take the later month)
        for m in re.finditer(r'(?:(\w+)\s*[-–/]\s*)?(\w+)\s+(\d{4})', text_lower):
            month_name = m.group(2)
            year = int(m.group(3))
            if month_name in month_map and 2020 <= year <= 2035:
                month = month_map[month_name]
                last_day = calendar.monthrange(year, month)[1]
                try:
                    candidates.append(datetime(year, month, last_day, tzinfo=timezone.utc))
                except ValueError:
                    pass

        # "Q1/Q2/Q3/Q4 YYYY"
        for m in re.finditer(r'Q([1-4])\s*(\d{4})', text):
            quarter, year = int(m.group(1)), int(m.group(2))
            if 2020 <= year <= 2035:
                end_month = quarter * 3
                last_day = calendar.monthrange(year, end_month)[1]
                candidates.append(datetime(year, end_month, last_day, tzinfo=timezone.utc))

        # "YYYY-YYYY" ranges — take end year
        for m in re.finditer(r'(\d{4})\s*[-–]\s*(\d{4})', text):
            end_year = int(m.group(2))
            if 2020 <= end_year <= 2035:
                candidates.append(datetime(end_year, 6, 30, tzinfo=timezone.utc))

        # Bare years "2027", "2028" etc
        for m in re.finditer(r'\b(202[4-9]|203[0-5])\b', text):
            year = int(m.group(1))
            candidates.append(datetime(year, 12, 31, tzinfo=timezone.utc))

        # Relative: "N-M months" or "N to M months" (common in step-by-step projections)
        for m in re.finditer(r'(\d+)\s*[-–to]+\s*(\d+)\s+months?', text_lower):
            max_months = int(m.group(2))
            if 0 < max_months <= 120:
                candidates.append(anchor + timedelta(days=max_months * 30))

        # Relative: "within N months" or "N months"
        for m in re.finditer(r'(?:within\s+)?(\d+)\s+months?\b', text_lower):
            months = int(m.group(1))
            if 0 < months <= 120:
                candidates.append(anchor + timedelta(days=months * 30))

        # Relative: "N-M years" or "N years"
        for m in re.finditer(r'(\d+)\s*[-–to]+\s*(\d+)\s+years?', text_lower):
            max_years = int(m.group(2))
            if 0 < max_years <= 20:
                candidates.append(anchor + timedelta(days=max_years * 365))
        for m in re.finditer(r'(?:within\s+)?(\d+)\s+years?\b', text_lower):
            years = int(m.group(1))
            if 0 < years <= 20:
                candidates.append(anchor + timedelta(days=years * 365))

        # Relative: "N-M weeks" or "N weeks" or "weeks N-M"
        for m in re.finditer(r'(\d+)\s*[-–to]+\s*(\d+)\s+weeks?', text_lower):
            max_weeks = int(m.group(2))
            if 0 < max_weeks <= 104:
                candidates.append(anchor + timedelta(weeks=max_weeks))
        for m in re.finditer(r'weeks?\s+(\d+)\s*[-–to]+\s*(\d+)', text_lower):
            max_weeks = int(m.group(2))
            if 0 < max_weeks <= 104:
                candidates.append(anchor + timedelta(weeks=max_weeks))
        for m in re.finditer(r'(?:within\s+)?(\d+)\s+weeks?\b', text_lower):
            weeks = int(m.group(1))
            if 0 < weeks <= 104:
                candidates.append(anchor + timedelta(weeks=weeks))

        # Relative: "N-M days" or "N days" or "next several days" or "next N-M days"
        for m in re.finditer(r'(\d+)\s*[-–to]+\s*(\d+)\s+days?', text_lower):
            max_days = int(m.group(2))
            if 0 < max_days <= 365:
                candidates.append(anchor + timedelta(days=max_days))
        for m in re.finditer(r'(?:within|next|over the next)\s+(\d+)\s+days?\b', text_lower):
            days = int(m.group(1))
            if 0 < days <= 365:
                candidates.append(anchor + timedelta(days=days))
        # "next several days" / "over the next several days" → ~7 days
        if re.search(r'(?:next|over the next)\s+(?:several|few)\s+days', text_lower):
            candidates.append(anchor + timedelta(days=7))

        if candidates:
            # Return the LATEST date (the scenario's endpoint)
            latest = max(candidates)
            logger.debug(
                "[ProphecyResolver] Extracted deadline %s from forward_projection (%d candidates)",
                latest.strftime("%Y-%m-%d"), len(candidates),
            )
            return latest

        return None

    @staticmethod
    def _get_prophecy_name(prophecy: dict) -> str:
        """Get a human-readable name for a prophecy."""
        scenario = prophecy.get("scenario", {})
        return scenario.get("name", prophecy.get("problem", "unnamed"))[:80]

    @property
    def last_run_result(self) -> dict | None:
        return self._last_run_result
