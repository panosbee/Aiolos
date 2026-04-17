"""
XDART-Φ — Memory Consolidation Loop (Sleep Process)

Mimics human memory consolidation during sleep:
  - Cross-run pattern extraction from episodic → semantic memory
  - Prophecy aging (mark expired predictions)
  - Knowledge deduplication (merge near-duplicate semantic entries)

Runs as a background asyncio task between pipeline runs.
Interval is configurable (default: every 30 minutes).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


class MemoryConsolidationLoop:
    """Background memory maintenance — the brain's 'sleep' process.

    Every consolidation cycle:
      1. Reviews recent episodic memories for cross-run patterns
      2. Ages prophecies past their timeframe
      3. Extracts new semantic truths from accumulated episodes
    """

    def __init__(
        self,
        llm,
        episodic_memory,
        semantic_memory,
        procedural_memory,
        prophetic_memory,
        interval_minutes: int = 30,
        vision_integration=None,
    ):
        self.llm = llm
        self.episodic = episodic_memory
        self.semantic = semantic_memory
        self.procedural = procedural_memory
        self.prophetic = prophetic_memory
        self.vision = vision_integration  # VisionIntegration — for visual consolidation
        self.interval = interval_minutes * 60
        self._cycle_count = 0
        self._running = False

    async def run_forever(self):
        """Main loop — call as asyncio.create_task(loop.run_forever())."""
        self._running = True
        logger.info("[Consolidation] Sleep process started (interval=%dm)", self.interval // 60)

        while self._running:
            try:
                await asyncio.sleep(self.interval)
                await self._run_cycle()
            except asyncio.CancelledError:
                logger.info("[Consolidation] Sleep process cancelled")
                break
            except Exception as exc:
                logger.warning("[Consolidation] Cycle error: %s", exc)

    async def _run_cycle(self):
        """Single consolidation cycle."""
        self._cycle_count += 1
        cycle_t0 = time.perf_counter()
        logger.info("[Consolidation] ═══ Cycle %d starting ═══", self._cycle_count)

        # 1. Age prophecies past their timeframe
        aged = await asyncio.get_event_loop().run_in_executor(
            None, self._age_prophecies
        )

        # 2. Cross-run pattern extraction (every 2nd cycle to limit LLM cost)
        extracted = 0
        if self._cycle_count % 2 == 0:
            extracted = await asyncio.get_event_loop().run_in_executor(
                None, self._cross_run_extraction
            )
        else:
            logger.info("[Consolidation] Skipping cross-run extraction (odd cycle %d)", self._cycle_count)

        # 3. Visual consolidation — extract patterns from visual observations
        visual_patterns = 0
        if self.vision:
            visual_patterns = await asyncio.get_event_loop().run_in_executor(
                None, self._visual_consolidation
            )

        # 4. Visual reflection — periodic deep thinking about visual experiences
        #    Runs every ~4 hours (8 cycles × 30min = 4h), triggered here
        reflection_result = None
        if self.vision:
            reflection_result = await asyncio.get_event_loop().run_in_executor(
                None, self.vision.run_visual_reflection
            )
            if reflection_result:
                logger.info("[Consolidation] Visual reflection completed: %s", {
                    k: v for k, v in reflection_result.items()
                    if k in ("patterns_stored", "curiosities_fed", "predictions_tracked", "distillate_stored")
                })

        # 5. Creative Nexus — imagination cycle
        #    Runs every cycle: pick random concepts, form creative links, generate curiosities
        imagination_result = None
        mongo = getattr(self, '_mongo', None)
        if mongo and mongo.available:
            try:
                imagination_result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: mongo.run_imagination_cycle(llm=self.llm)
                )
                if imagination_result and imagination_result.get("status") == "ok":
                    stats = imagination_result.get("stats", {})
                    logger.info(
                        "[Consolidation] Imagination cycle: %s ↔ %s (total=%d links, %d mature)",
                        imagination_result.get("concepts", ["?", "?"])[0],
                        imagination_result.get("concepts", ["?", "?"])[1],
                        stats.get("total_links", 0),
                        stats.get("mature_links", 0),
                    )
            except Exception as exc:
                logger.debug("[Consolidation] Imagination cycle failed: %s", exc)

        elapsed = time.perf_counter() - cycle_t0
        logger.info(
            "[Consolidation] ═══ Cycle %d complete (%.2fs) — aged=%d prophecies, "
            "extracted=%d patterns, visual=%d patterns, reflection=%s, imagination=%s ═══",
            self._cycle_count, elapsed, aged, extracted, visual_patterns,
            "yes" if reflection_result else "no",
            "yes" if imagination_result and imagination_result.get("status") == "ok" else "no",
        )

    def _age_prophecies(self) -> int:
        """Mark prophecies as expired if past their timeframe."""
        all_prophecies = self.prophetic.list_all(limit=200)
        aged = 0
        now = datetime.now(timezone.utc)

        for entry in all_prophecies:
            if entry.get("tracking_status") not in ("active", "tracking"):
                continue

            # Parse timeframe — look for patterns like "3 months", "6-12 months", "2025"
            timeframe = entry.get("scenario", {}).get("timeline", "")
            created_at = entry.get("timestamp", "")

            if not created_at or not timeframe:
                continue

            try:
                if isinstance(created_at, str):
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                else:
                    created = created_at

                max_days = self._parse_timeframe_days(timeframe)
                if max_days and (now - created) > timedelta(days=max_days):
                    entry_id = entry.get("id", "")
                    if entry_id:
                        self.prophetic.update_tracking_status(
                            entry_id=entry_id,
                            new_status="expired",
                            reality_check={
                                "checked_at": now.isoformat(),
                                "assessment": f"Auto-expired: timeframe '{timeframe}' exceeded ({max_days}d)",
                                "source": "consolidation_loop",
                            },
                        )
                        aged += 1
                        logger.info("[Consolidation] Aged prophecy: %s → expired (timeframe: %s)",
                                    entry.get("scenario", {}).get("name", "?"), timeframe)
            except Exception:
                continue

        return aged

    def _cross_run_extraction(self) -> int:
        """Extract cross-run patterns from recent episodic memories."""
        # Get recent episodic memories
        recent_memories = self.episodic.retrieve("geopolitical economic financial market technology social conflict", top_k=10)
        if len(recent_memories) < 3:
            return 0

        # Build a summary of recent distillates for the LLM
        distillates = []
        for mem in recent_memories:
            distillates.append(
                f"Problem: {mem.entry.problem}\n"
                f"Distillate: {mem.entry.xheart_distillate}\n"
                f"Domains: {', '.join(mem.entry.domain_tags)}"
            )

        combined = "\n---\n".join(distillates[:8])

        try:
            response = self.llm.call_json(
                system_prompt=(
                    "You are the consolidation process of a prediction system.\n"
                    "Review these recent analysis distillates and extract cross-cutting patterns "
                    "that appear across MULTIPLE analyses.\n\n"
                    "Return ONLY patterns that are:\n"
                    "1. Recurring across 2+ analyses (not one-off observations)\n"
                    "2. Generalizable truths about how systems/actors behave\n"
                    "3. Not already obvious or trivial\n\n"
                    "Return JSON with this exact schema:\n"
                    '{"patterns": [{"knowledge": "<the abstract truth or pattern>", '
                    '"confidence": <0.0-1.0>, "source_count": <number of analyses supporting this>}]}\n\n'
                    'Return {"patterns": []} if no strong cross-cutting patterns found.'
                ),
                user_prompt=f"Recent analyses:\n{combined}",
            )

            patterns = response.get("patterns", [])

            stored = 0
            for pattern in patterns:
                if pattern.get("confidence", 0) < 0.6:
                    continue
                if pattern.get("source_count", 0) < 2:
                    continue

                try:
                    self.semantic.store_truth(
                        knowledge=pattern["knowledge"],
                        confidence=pattern["confidence"],
                        source="consolidation_loop",
                    )
                    stored += 1
                    logger.info("[Consolidation] New cross-run truth: %s (conf=%.2f)",
                                pattern["knowledge"][:80], pattern["confidence"])
                except Exception:
                    pass

            return stored

        except Exception as exc:
            logger.warning("[Consolidation] Cross-run extraction failed: %s", exc)
            return 0

    def _visual_consolidation(self) -> int:
        """Extract behavioral patterns from visual observations.

        Reads visual journal data via the VisionIntegration bridge,
        combines it with existing episodic patterns, and extracts
        cross-modal truths (visual + analytical) into semantic memory.
        """
        if not self.vision:
            return 0

        visual_data = self.vision.get_visual_patterns_for_consolidation(last_n=100)
        if not visual_data or len(visual_data) < 50:
            return 0

        # Also get recent episodic themes for cross-modal extraction
        episodic_context = ""
        try:
            recent = self.episodic.retrieve("behavioral patterns human activity schedule", top_k=3)
            if recent:
                episodic_context = "\nRECENT EPISODIC CONTEXT:\n" + "\n".join(
                    f"  - {m.entry.xheart_distillate[:200]}" for m in recent[:3]
                )
        except Exception:
            pass

        try:
            response = self.llm.call_json(
                system_prompt=(
                    "You are the VISUAL CONSOLIDATION process of an AI system with camera perception.\n"
                    "Review the visual observations and extract BEHAVIORAL PATTERNS:\n\n"
                    "Look for:\n"
                    "1. Temporal patterns (when do people arrive/leave, daily routines)\n"
                    "2. Co-occurrence patterns (who appears with who, what objects appear with what people)\n"
                    "3. Environmental patterns (workspace changes, equipment usage)\n"
                    "4. Cross-modal patterns (visual observations that connect to analytical knowledge)\n\n"
                    "Return ONLY genuine patterns supported by the data.\n"
                    "Each pattern must reference specific evidence (timestamps, counts).\n\n"
                    "Return JSON:\n"
                    '{"patterns": [{"knowledge": "<behavioral pattern>", '
                    '"confidence": <0.0-1.0>, "evidence_summary": "<data supporting this>"}]}\n\n'
                    'Return {"patterns": []} if insufficient data for patterns.'
                ),
                user_prompt=f"{visual_data}{episodic_context}",
            )

            patterns = response.get("patterns", [])
            stored = 0
            for pattern in patterns:
                if pattern.get("confidence", 0) < 0.5:
                    continue
                try:
                    self.semantic.store_truth(
                        knowledge=f"[Visual-Behavioral] {pattern['knowledge']}",
                        confidence=pattern["confidence"],
                        source="visual_consolidation",
                    )
                    stored += 1
                    logger.info("[Consolidation] Visual pattern: %s (conf=%.2f)",
                                pattern["knowledge"][:80], pattern["confidence"])
                except Exception:
                    pass

            return stored

        except Exception as exc:
            logger.warning("[Consolidation] Visual consolidation failed: %s", exc)
            return 0

    @staticmethod
    def _parse_timeframe_days(timeframe: str) -> int | None:
        """Parse a timeframe string into approximate max days."""
        tf = timeframe.lower().strip()

        # "6-12 months" → take the upper bound
        import re
        month_range = re.search(r"(\d+)\s*-\s*(\d+)\s*month", tf)
        if month_range:
            return int(month_range.group(2)) * 30

        week_range = re.search(r"(\d+)\s*-\s*(\d+)\s*week", tf)
        if week_range:
            return int(week_range.group(2)) * 7

        # "3 months"
        month_single = re.search(r"(\d+)\s*month", tf)
        if month_single:
            return int(month_single.group(1)) * 30

        # "2 weeks"
        week_single = re.search(r"(\d+)\s*week", tf)
        if week_single:
            return int(week_single.group(1)) * 7

        # "1 year" / "2 years"
        year_single = re.search(r"(\d+)\s*year", tf)
        if year_single:
            return int(year_single.group(1)) * 365

        # "2025", "2026" — assume end of that year
        year_exact = re.search(r"(20\d{2})", tf)
        if year_exact:
            target_year = int(year_exact.group(1))
            now = datetime.now(timezone.utc)
            target = datetime(target_year, 12, 31, tzinfo=timezone.utc)
            days = (target - now).days
            return max(days, 30)  # at least 30 days

        return None

    def stop(self):
        """Signal the loop to stop."""
        self._running = False
