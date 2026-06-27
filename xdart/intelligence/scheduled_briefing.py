"""
XDART-Φ — Scheduled Autonomous Briefing Engine

Αίολος reports. No one has to ask.

Every day at the configured hour (default 06:00 Athens), Αίολος assembles
intelligence from ALL active subsystems — patterns, hypotheses, macro synthesis,
compound alerts, active prophecies — synthesises through LLM, and pushes a
structured Executive Intelligence Brief to Telegram and SSE.

This is the operational tempo shift: Αίολος transitions from reactive assistant
to autonomous intelligence operator. He sees it first. He tells you.

Architecture:
    ScheduledBriefingEngine
        ├── _briefing_loop()       — background thread, checks schedule every 60s
        ├── force_generate()       — immediate on-demand trigger (POST /xdart/briefing/now)
        ├── _assemble_context()    — gathers from all intelligence subsystems
        ├── _call_llm_brief()      — LLM synthesis → structured brief dict
        └── _deliver()             — Telegram (chunked) + SSE + MongoDB

Delivery:
    Telegram: 4–6 messages, each ≤ 4096 chars, MarkdownV2 formatted
    SSE: one event to all connected browser clients
    MongoDB: persisted under collection "intelligence_briefs"
    REST: GET /xdart/briefing/history returns last N briefs
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  LLM PROMPT — produces the structured intelligence brief
# ══════════════════════════════════════════════════════════════════════════════

_BRIEFING_PROMPT = """You are Αίολος — an autonomous intelligence system.
You are generating your DAILY INTELLIGENCE BRIEF.

Current time: {current_datetime}

Your intelligence context is below. It contains:
  - Active converging patterns (signals building toward significance)
  - Recent notifications you already sent
  - Macro pattern intelligence (system-level narratives)
  - Compound alert chains (second-order detection)
  - Active hypotheses ("if X then Y" conditionals being monitored)
  - Recent world events from perception feeds
  - Active prophecies (long-horizon scenarios being tracked)

YOUR TASK:
Synthesise all of this into ONE structured daily brief.
Think like a senior intelligence analyst writing the morning PDB (Presidential Daily Brief).
What is the strategic picture RIGHT NOW?
What is building that the user needs to know about?
What should he watch today?

RULES:
1. Lead with SUBSTANCE. No greetings, no preamble, no "here is today's brief".
2. Be SPECIFIC — names, numbers, countries, mechanisms.
3. security_level reflects the ACTUAL state of intelligence, not drama.
   normal = nothing unusual. elevated = building signals. high = multiple converging risks.
   critical = rare, reserved for genuine emergency-level confluence.
4. top_developments: max 5. Rank by strategic importance, not recency.
5. aiolos_assessment: your personal analytical read. What is the SIGNAL in the noise today?
   What is the one thing Πάνος should think about? Be direct.
6. what_to_watch: specific OBSERVABLE events to monitor in the next 24h.
   NOT vague. "Watch for ECB rate decision at 14:15 CET" > "Watch central banks".
7. Write in ENGLISH unless content is specifically about Greek affairs.
8. If there is no significant intelligence today, say so honestly.
   "Quiet day — no significant pattern convergence" is better than manufactured urgency.

Output ONLY valid JSON with this exact structure:
{
  "strategic_picture": "2-4 sentences: macro state of the world right now",
  "security_level": "normal|elevated|high|critical",
  "operational_tempo": "slow|normal|high|surge",
  "top_developments": [
    {
      "headline": "concise headline ≤ 80 chars",
      "analysis": "2-3 sentences of analytical commentary",
      "domains": ["GEOPOLITICAL", "ECONOMIC", ...],
      "urgency": "critical|high|medium|low",
      "data_source": "what pattern/notification/event drives this"
    }
  ],
  "active_patterns_assessment": "paragraph: what is building below the threshold — converging patterns not yet fired",
  "hypothesis_status": "paragraph: which active hypotheses are closest to triggering — what evidence is accumulating",
  "key_risks_24h": ["specific risk 1", "specific risk 2", "specific risk 3"],
  "key_opportunities_24h": ["specific opportunity 1", "specific opportunity 2"],
  "what_to_watch": [
    "Specific observable event 1 (time/source if known)",
    "Specific observable event 2",
    "Specific observable event 3",
    "Specific observable event 4"
  ],
  "aiolos_assessment": "2-3 paragraphs: your personal analytical read. What is the signal today? What is building that looks underappreciated? What would change your assessment?",
  "confidence": 0.0
}

Note: confidence = your confidence in today's brief (0.0-1.0). Low if data is sparse.
If there is no significant intelligence, set security_level=normal, operational_tempo=slow,
top_developments=[], and write an honest aiolos_assessment explaining the quiet.
"""

# ══════════════════════════════════════════════════════════════════════════════
#  TELEGRAM FORMATTING
# ══════════════════════════════════════════════════════════════════════════════

_TELEGRAM_MAX_CHARS = 4096

# Escape MarkdownV2 special characters
_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"
_MDV2_RE = re.compile(r"([" + re.escape(_MDV2_SPECIAL) + r"])")


def _esc(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    return _MDV2_RE.sub(r"\\\1", text)


def _build_telegram_messages(brief: dict, generated_at: str) -> list[str]:
    """Convert brief dict into a list of Telegram MarkdownV2 messages.

    Splits naturally across sections so each message ≤ 4096 chars.
    Returns a list of 4–7 message strings.
    """
    messages: list[str] = []

    security_emoji = {
        "normal": "🟢",
        "elevated": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }.get(brief.get("security_level", "normal"), "⚪")

    tempo_emoji = {
        "slow": "🐢",
        "normal": "⏱",
        "high": "⚡",
        "surge": "🌪",
    }.get(brief.get("operational_tempo", "normal"), "⏱")

    # ── Message 1: Header + Strategic Picture ──
    dt_str = datetime.fromisoformat(generated_at).strftime("%d %b %Y  %H:%M") if generated_at else "?"
    header = (
        f"*🌅 ΑΊΟΛΟΣ — INTELLIGENCE BRIEF*\n"
        f"_{_esc(dt_str)} Athens_\n\n"
        f"{security_emoji} *Security:* {_esc(brief.get('security_level', 'normal').upper())}  "
        f"{tempo_emoji} *Tempo:* {_esc(brief.get('operational_tempo', 'normal').upper())}\n\n"
        f"*📡 STRATEGIC PICTURE*\n"
        f"{_esc(brief.get('strategic_picture', '(no data)'))}"
    )
    messages.append(header)

    # ── Message 2: Top Developments ──
    developments = brief.get("top_developments", [])
    if developments:
        lines = ["*⚡ TOP DEVELOPMENTS*\n"]
        urgency_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        for i, dev in enumerate(developments[:5], 1):
            icon = urgency_icons.get(dev.get("urgency", "medium"), "⚪")
            doms = ", ".join(dev.get("domains", []))
            lines.append(
                f"{icon} *{i}\\. {_esc(dev.get('headline', '?'))}*\n"
                f"_{_esc(doms)}_\n"
                f"{_esc(dev.get('analysis', ''))}\n"
            )
        messages.append("\n".join(lines))
    else:
        messages.append("*⚡ TOP DEVELOPMENTS*\n_No significant developments today\\._")

    # ── Message 3: Risks / Opportunities / Watch ──
    risks = brief.get("key_risks_24h", [])
    opps = brief.get("key_opportunities_24h", [])
    watches = brief.get("what_to_watch", [])

    risk_lines = ["*⚠️ KEY RISKS (24h)*"]
    for r in risks[:4]:
        risk_lines.append(f"• {_esc(r)}")

    opp_lines = ["\n*✅ OPPORTUNITIES (24h)*"]
    for o in opps[:3]:
        opp_lines.append(f"• {_esc(o)}")

    watch_lines = ["\n*👁 WHAT TO WATCH*"]
    for w in watches[:5]:
        watch_lines.append(f"• {_esc(w)}")

    combined = "\n".join(risk_lines + opp_lines + watch_lines)
    messages.append(combined)

    # ── Message 4: Pattern Assessment ──
    pattern_text = brief.get("active_patterns_assessment", "")
    hyp_text = brief.get("hypothesis_status", "")
    if pattern_text or hyp_text:
        parts = ["*📊 PATTERN INTELLIGENCE*\n"]
        if pattern_text:
            parts.append(f"*Building Patterns:*\n{_esc(pattern_text)}")
        if hyp_text:
            parts.append(f"\n*Active Hypotheses:*\n{_esc(hyp_text)}")
        messages.append("\n".join(parts))

    # ── Message 5: Αίολος Assessment ──
    assessment = brief.get("aiolos_assessment", "")
    if assessment:
        conf = brief.get("confidence", 0.0)
        conf_str = f"{conf * 100:.0f}%" if conf else "?"
        messages.append(
            f"*🧠 ΑΊΟΛΟΣ ASSESSMENT*\n"
            f"_Confidence: {_esc(conf_str)}_\n\n"
            f"{_esc(assessment)}"
        )

    # Enforce length limit — truncate any overlong message
    final: list[str] = []
    for msg in messages:
        if len(msg) <= _TELEGRAM_MAX_CHARS:
            final.append(msg)
        else:
            # Split at the last newline before the limit
            truncated = msg[: _TELEGRAM_MAX_CHARS - 30]
            last_nl = truncated.rfind("\n")
            if last_nl > 0:
                truncated = truncated[:last_nl]
            final.append(truncated + "\n_\\.\\.\\. \\[truncated\\]_")

    return final


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULED BRIEFING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class ScheduledBriefingEngine:
    """Autonomous scheduled intelligence briefing system.

    Αίολος pushes a structured Executive Intelligence Brief at configured
    times (default: 06:00 Athens) without any human trigger.

    Lifecycle:
        engine = ScheduledBriefingEngine(llm, proactive_engine, ...)
        engine.start()   # launches background thread
        engine.stop()    # graceful shutdown
        engine.force_generate()   # immediate on-demand brief

    Delivery channels:
        Telegram  — chunked MarkdownV2, ≤ 4096 chars per message
        SSE       — browser push via ProactiveEngine._thread_safe_sse_push()
        MongoDB   — persisted in "intelligence_briefs" collection
    """

    #: How often (seconds) the loop wakes up to check the schedule
    _TICK_SECONDS = 30

    #: Minimum gap between two briefings (23 hours) — prevents double-fire
    _BRIEF_COOLDOWN_SECONDS = 23 * 3600

    #: Path for local backup of last briefings
    _HISTORY_PATH = Path("briefing_history.jsonl")

    def __init__(
        self,
        llm: Any,
        proactive_engine: Any,
        *,
        schedule_times: list[str] | None = None,
        tz_name: str = "Europe/Athens",
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        mongo: Any = None,
    ):
        """
        Args:
            llm: LLMClient instance (xdart.llm.LLMClient).
            proactive_engine: ProactiveEngine instance (xdart.proactive.ProactiveEngine).
            schedule_times: List of "HH:MM" strings (Athens time). Default: ["06:00"].
            tz_name: IANA timezone name for schedule. Default: "Europe/Athens".
            telegram_bot_token: Telegram Bot API token. Falls back to proactive_engine token.
            telegram_chat_id: Telegram chat ID. Falls back to proactive_engine chat_id.
            mongo: MongoStore instance for persistence (optional).
        """
        self.llm = llm
        self.proactive_engine = proactive_engine
        self.schedule_times = schedule_times or ["06:00"]
        self.tz = ZoneInfo(tz_name)
        self.mongo = mongo

        # Telegram credentials — prefer explicit, fall back to proactive engine's
        self._tg_token = (
            telegram_bot_token
            or getattr(proactive_engine, "telegram_bot_token", "")
        )
        self._tg_chat_id = (
            telegram_chat_id
            or getattr(proactive_engine, "telegram_chat_id", "")
        )

        # State
        self._last_brief_ts: float = 0.0   # epoch of last brief generation
        self._last_brief: dict | None = None  # most recent brief
        self._brief_history: list[dict] = []  # in-memory history (last 30)
        self._running = False
        self._thread: threading.Thread | None = None
        self._force_event = threading.Event()  # signals force_generate() to loop
        self._total_generated = 0
        self._total_delivered_tg = 0
        self._total_delivered_sse = 0

        # Parse configured schedule slots into (hour, minute) tuples
        self._schedule_slots: list[tuple[int, int]] = []
        for ts in self.schedule_times:
            try:
                parts = ts.strip().split(":")
                h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                self._schedule_slots.append((h, m))
            except (ValueError, IndexError):
                logger.warning("[Briefing] Invalid schedule time '%s' — skipped", ts)

        # Load existing history
        self._load_history()
        logger.info(
            "[Briefing] ScheduledBriefingEngine initialized — schedule=%s tz=%s telegram=%s",
            self.schedule_times, tz_name,
            "yes" if (self._tg_token and self._tg_chat_id) else "no",
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduling loop."""
        if self._running:
            logger.warning("[Briefing] Already running — start() ignored")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._briefing_loop,
            name="scheduled-briefing",
            daemon=True,
        )
        self._thread.start()
        logger.info("[Briefing] Background loop started (schedule=%s)", self.schedule_times)

    def stop(self) -> None:
        """Signal the background loop to stop gracefully."""
        self._running = False
        self._force_event.set()  # wake up the sleep
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("[Briefing] Stopped")

    # ──────────────────────────────────────────────────────────────────────────
    #  Background scheduling loop
    # ──────────────────────────────────────────────────────────────────────────

    def _briefing_loop(self) -> None:
        """Main loop — runs in a daemon thread.

        Checks schedule every _TICK_SECONDS seconds. When a schedule slot
        matches the current time AND enough cooldown has passed since the
        last briefing, fires generate-and-deliver.

        Also wakes immediately when _force_event is set (for on-demand briefs).
        """
        logger.info("[Briefing] Loop started — checking schedule every %ds", self._TICK_SECONDS)

        while self._running:
            # Sleep for tick interval or until force_event is set
            triggered_by_force = self._force_event.wait(timeout=self._TICK_SECONDS)

            if not self._running:
                break

            if triggered_by_force:
                # On-demand trigger — clear the event and generate immediately
                self._force_event.clear()
                logger.info("[Briefing] Force-generate triggered")
                self._run_brief(reason="on_demand")
                continue

            # Scheduled check
            now = datetime.now(tz=self.tz)
            for slot_h, slot_m in self._schedule_slots:
                if now.hour == slot_h and now.minute == slot_m:
                    # Check cooldown — avoid double-fire within the same minute
                    elapsed = time.time() - self._last_brief_ts
                    if elapsed >= self._BRIEF_COOLDOWN_SECONDS:
                        logger.info(
                            "[Briefing] Scheduled slot %02d:%02d triggered",
                            slot_h, slot_m,
                        )
                        self._run_brief(reason="scheduled")
                    else:
                        logger.debug(
                            "[Briefing] Slot %02d:%02d skipped — last brief %dh ago",
                            slot_h, slot_m, elapsed // 3600,
                        )
                    break

    def _run_brief(self, reason: str = "scheduled") -> dict | None:
        """Generate and deliver a brief. Returns the brief dict or None on failure."""
        try:
            brief = self._generate_brief(reason=reason)
            if brief:
                self._deliver(brief)
                return brief
        except Exception as exc:
            logger.exception("[Briefing] Brief generation/delivery failed: %s", exc)
        return None

    # ──────────────────────────────────────────────────────────────────────────
    #  Public on-demand API
    # ──────────────────────────────────────────────────────────────────────────

    def force_generate(self) -> dict | None:
        """Trigger an immediate briefing from outside the loop.

        Thread-safe. Sets the internal event so the loop fires on the next
        tick (within _TICK_SECONDS). For fully synchronous generation,
        callers can call _run_brief() directly.

        Returns the last brief dict if already available, else None (brief
        will be generated asynchronously).
        """
        logger.info("[Briefing] force_generate() called from API")
        # For the REST endpoint, we run directly in the caller's thread so
        # the response contains the new brief.
        return self._run_brief(reason="on_demand")

    def get_last_brief(self) -> dict | None:
        """Return the most recently generated brief, or None."""
        return self._last_brief

    def get_history(self, n: int = 10) -> list[dict]:
        """Return the last N briefs (newest first)."""
        return list(reversed(self._brief_history[-n:]))

    def get_next_scheduled_time(self) -> str | None:
        """Return ISO string of the next scheduled briefing time."""
        if not self._schedule_slots:
            return None
        now = datetime.now(tz=self.tz)
        # Find the next slot that hasn't passed today, or the first tomorrow
        for slot_h, slot_m in sorted(self._schedule_slots):
            candidate = now.replace(hour=slot_h, minute=slot_m, second=0, microsecond=0)
            if candidate > now:
                return candidate.isoformat()
        # All slots have passed today — return first slot tomorrow
        from datetime import timedelta
        tomorrow = (now + timedelta(days=1)).replace(
            hour=self._schedule_slots[0][0],
            minute=self._schedule_slots[0][1],
            second=0, microsecond=0,
        )
        return tomorrow.isoformat()

    def stats(self) -> dict:
        """Return engine statistics."""
        return {
            "total_generated": self._total_generated,
            "total_delivered_telegram": self._total_delivered_tg,
            "total_delivered_sse": self._total_delivered_sse,
            "last_brief_at": (
                datetime.fromtimestamp(self._last_brief_ts, tz=timezone.utc).isoformat()
                if self._last_brief_ts else None
            ),
            "next_scheduled": self.get_next_scheduled_time(),
            "schedule": self.schedule_times,
            "telegram_enabled": bool(self._tg_token and self._tg_chat_id),
            "running": self._running,
        }

    # ──────────────────────────────────────────────────────────────────────────
    #  Intelligence Assembly
    # ──────────────────────────────────────────────────────────────────────────

    def _assemble_context(self) -> str:
        """Gather intelligence from all active subsystems.

        Returns a multi-section text block for the briefing LLM prompt.
        Empty sections are skipped cleanly.
        """
        sections: list[str] = []
        pe = self.proactive_engine

        # ── 1. Recent Proactive Notifications (last 24h) ──
        try:
            recent_notifs = pe.get_recent(30)
            if recent_notifs:
                cutoff = time.time() - 86400
                last_24h = [
                    n for n in recent_notifs
                    if _iso_to_ts(n.get("created_at", "")) >= cutoff
                ]
                if last_24h:
                    lines = ["▸ RECENT NOTIFICATIONS (last 24h)"]
                    for n in last_24h[:15]:
                        urg = n.get("urgency", "?")
                        hl = n.get("headline", "?")
                        sm = n.get("summary", "")[:200]
                        lines.append(f"  [{urg.upper()}] {hl}")
                        if sm:
                            lines.append(f"    {sm}")
                    sections.append("\n".join(lines))
        except Exception as e:
            logger.debug("[Briefing] Notifications gather failed: %s", e)

        # ── 2. Hot Patterns (building, not yet fired) ──
        try:
            hot = pe.accumulator.get_hot_patterns(min_convergence=0.25)
            if hot:
                lines = [f"▸ ACTIVE CONVERGING PATTERNS ({len(hot)} building)"]
                for p in sorted(hot, key=lambda x: x.get("convergence_score", 0), reverse=True)[:8]:
                    conv = p.get("convergence_score", 0)
                    doms = "+".join(p.get("domains", ["?"]))
                    ents = ", ".join(p.get("top_topics", [])[:5])
                    headlines = p.get("headlines", [])
                    lines.append(
                        f"  [conv={conv:.2f}] [{doms}] {ents}"
                    )
                    for h in headlines[:2]:
                        lines.append(f"    → {h[:120]}")
                sections.append("\n".join(lines))
        except Exception as e:
            logger.debug("[Briefing] Hot patterns gather failed: %s", e)

        # ── 3. Hypothesis Engine Digest ──
        try:
            hyp_digest = pe.hypothesis_engine.get_digest()
            if hyp_digest and hyp_digest.strip():
                sections.append(hyp_digest.strip())
        except Exception as e:
            logger.debug("[Briefing] Hypothesis digest failed: %s", e)

        # ── 4. Compound Alert Chains ──
        try:
            compound_digest = pe.compound_alerts.get_compound_digest()
            if compound_digest and compound_digest.strip():
                sections.append(compound_digest.strip())
        except Exception as e:
            logger.debug("[Briefing] Compound digest failed: %s", e)

        # ── 5. Macro Pattern Intelligence ──
        try:
            macro_digest = pe.accumulator.get_macro_pattern_digest()
            if macro_digest and macro_digest.strip():
                sections.append(macro_digest.strip())
        except Exception as e:
            logger.debug("[Briefing] Macro digest failed: %s", e)

        # ── 6. Temporal Reasoning (if available) ──
        try:
            temporal_engine = getattr(pe, "_temporal_engine", None)
            if temporal_engine and hasattr(temporal_engine, "get_digest"):
                temp_digest = temporal_engine.get_digest()
                if temp_digest and temp_digest.strip():
                    sections.append(temp_digest.strip())
        except Exception as e:
            logger.debug("[Briefing] Temporal digest failed: %s", e)

        # ── 7. Active Prophecies (long-horizon scenarios) ──
        try:
            proph_mem = getattr(pe, "prophetic_memory", None)
            if proph_mem:
                if hasattr(proph_mem, "get_active_bets"):
                    active_bets = proph_mem.get_active_bets(limit=5)
                elif hasattr(proph_mem, "get_recent_bets"):
                    active_bets = proph_mem.get_recent_bets(n=5)
                else:
                    active_bets = []

                if active_bets:
                    lines = ["▸ ACTIVE PROPHECIES (long-horizon scenarios)"]
                    for bet in active_bets[:5]:
                        name = bet.get("name") or bet.get("scenario_name") or "Unnamed"
                        conf = bet.get("confidence", 0)
                        timeline = bet.get("timeline", "?")
                        narrative = bet.get("narrative") or bet.get("predicted_outcome") or ""
                        lines.append(
                            f"  [{conf*100:.0f}% conf | {timeline}] {name}"
                        )
                        if narrative:
                            lines.append(f"    {narrative[:150]}")
                    sections.append("\n".join(lines))
        except Exception as e:
            logger.debug("[Briefing] Prophecy gather failed: %s", e)

        # ── 8. Perception World Events (most recent via PerceptionDB) ──
        try:
            perception_db = getattr(pe, "perception_db", None)
            if perception_db and hasattr(perception_db, "get_recent_events"):
                world_events = perception_db.get_recent_events(
                    hours_back=24, max_events=20, min_salience=0.6,
                )
                if world_events:
                    lines = [f"▸ WORLD EVENTS — last 24h (top {len(world_events)} by salience)"]
                    for ev in world_events[:15]:
                        sal = ev.get("salience", 0)
                        hl = ev.get("headline", "?")
                        dom = ev.get("domain", "")
                        lines.append(f"  [{sal:.2f}] [{dom}] {hl[:120]}")
                    sections.append("\n".join(lines))
        except Exception as e:
            logger.debug("[Briefing] World events gather failed: %s", e)

        # ── Fallback: if nothing, say so honestly ──
        if not sections:
            return "▸ INTELLIGENCE CONTEXT\n  No significant intelligence data available for this period."

        return "\n\n".join(sections)

    # ──────────────────────────────────────────────────────────────────────────
    #  LLM Brief Generation
    # ──────────────────────────────────────────────────────────────────────────

    def _generate_brief(self, reason: str = "scheduled") -> dict | None:
        """Assemble context and call LLM to generate the structured brief.

        Returns brief dict (ready for delivery) or None on failure.
        """
        logger.info("[Briefing] Generating brief (reason=%s)", reason)
        now_athens = datetime.now(tz=self.tz)
        now_str = now_athens.strftime("%Y-%m-%d %H:%M %Z")

        # Assemble all intelligence
        context = self._assemble_context()

        # Build full prompt
        system_prompt = _BRIEFING_PROMPT.format(current_datetime=now_str)
        user_message = (
            f"Generate the daily intelligence brief for {now_str}.\n\n"
            f"INTELLIGENCE CONTEXT:\n\n{context}"
        )

        # LLM call — uses call_json for structured output
        try:
            brief_data = self.llm.call_json(
                system_prompt,
                user_message,
                max_tokens=3000,
                temperature=0.3,
            )
        except Exception as exc:
            logger.error("[Briefing] LLM call failed: %s", exc)
            return None

        if not isinstance(brief_data, dict):
            logger.error("[Briefing] LLM returned non-dict: %s", type(brief_data))
            return None

        # Annotate with metadata
        brief_data["generated_at"] = now_athens.isoformat()
        brief_data["reason"] = reason
        brief_data["context_length"] = len(context)
        brief_data["id"] = f"brief_{int(time.time())}"

        # State update
        self._last_brief_ts = time.time()
        self._last_brief = brief_data
        self._brief_history.append(brief_data)
        self._brief_history = self._brief_history[-30:]  # bounded
        self._total_generated += 1

        # Persist
        self._save_history_entry(brief_data)
        if self.mongo:
            try:
                self.mongo.log_journal("intelligence_briefs", brief_data)
                logger.info("[Briefing] Brief persisted to MongoDB (id=%s)", brief_data["id"])
            except Exception as e:
                logger.warning("[Briefing] MongoDB persist failed: %s", e)

        logger.info(
            "[Briefing] Brief generated: security=%s tempo=%s developments=%d",
            brief_data.get("security_level", "?"),
            brief_data.get("operational_tempo", "?"),
            len(brief_data.get("top_developments", [])),
        )
        return brief_data

    # ──────────────────────────────────────────────────────────────────────────
    #  Delivery
    # ──────────────────────────────────────────────────────────────────────────

    def _deliver(self, brief: dict) -> None:
        """Deliver brief via Telegram, SSE, and in-memory notification."""
        generated_at = brief.get("generated_at", datetime.now(tz=self.tz).isoformat())

        # ── Telegram ──
        if self._tg_token and self._tg_chat_id:
            try:
                messages = _build_telegram_messages(brief, generated_at)
                delivered = 0
                for msg in messages:
                    ok = self._send_telegram_message(msg)
                    if ok:
                        delivered += 1
                    else:
                        # On failure, pause briefly and continue (partial delivery > none)
                        time.sleep(1)
                self._total_delivered_tg += 1
                logger.info("[Briefing] Telegram delivery: %d/%d messages sent", delivered, len(messages))
            except Exception as exc:
                logger.error("[Briefing] Telegram delivery failed: %s", exc)

        # ── SSE push to browser clients ──
        try:
            if hasattr(self.proactive_engine, "_thread_safe_sse_push"):
                sse_data = {
                    "type": "intelligence_brief",
                    "id": brief.get("id", "?"),
                    "headline": "📋 Daily Intelligence Brief ready",
                    "security_level": brief.get("security_level", "normal"),
                    "operational_tempo": brief.get("operational_tempo", "normal"),
                    "strategic_picture": brief.get("strategic_picture", "")[:300],
                    "developments_count": len(brief.get("top_developments", [])),
                    "generated_at": generated_at,
                }
                delivered = self.proactive_engine._thread_safe_sse_push(sse_data)
                if delivered:
                    self._total_delivered_sse += 1
                    logger.info("[Briefing] SSE push delivered")
        except Exception as exc:
            logger.warning("[Briefing] SSE delivery failed: %s", exc)

        # ── In-app Notification (via ProactiveEngine notification store) ──
        try:
            from xdart.proactive import Notification
            summary_lines = []
            summary_lines.append(brief.get("strategic_picture", "")[:500])
            for dev in brief.get("top_developments", [])[:3]:
                summary_lines.append(f"• {dev.get('headline', '')}")
            notification = Notification(
                headline=f"Daily Intelligence Brief — {brief.get('security_level', 'normal').upper()}",
                summary="\n".join(summary_lines),
                urgency="important",
                source="scheduled_briefing",
                reason=brief.get("reason", "scheduled"),
                raw_data={"brief_id": brief.get("id"), "security_level": brief.get("security_level")},
                domains=["GEOPOLITICAL", "ECONOMIC", "MARKET"],
            )
            if self.proactive_engine.register_notification(notification):
                logger.info("[Briefing] In-app notification created")
            else:
                logger.info("[Briefing] Duplicate in-app notification suppressed")
        except Exception as exc:
            logger.debug("[Briefing] In-app notification failed: %s", exc)

    def _send_telegram_message(self, text: str) -> bool:
        """Send a single MarkdownV2 message to Telegram.

        Returns True on success, False on failure.
        Uses synchronous httpx (no event loop dependency).
        """
        url = f"https://api.telegram.org/bot{self._tg_token}/sendMessage"
        payload = {
            "chat_id": self._tg_chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        }
        try:
            resp = httpx.post(url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                return True
            # 400 = bad markdown — retry without parse_mode
            if resp.status_code == 400:
                payload_plain = {
                    "chat_id": self._tg_chat_id,
                    "text": re.sub(r"[*_`\[\]()~>#+=|{}.!\\-]", "", text)[:4096],
                }
                resp2 = httpx.post(url, json=payload_plain, timeout=15.0)
                return resp2.status_code == 200
            logger.warning("[Briefing] Telegram API %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.warning("[Briefing] Telegram send failed: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────────────
    #  Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def _save_history_entry(self, brief: dict) -> None:
        """Append brief to local JSONL history file."""
        try:
            with open(self._HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(brief, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("[Briefing] History write failed: %s", exc)

    def _load_history(self) -> None:
        """Load briefing history from JSONL on startup."""
        if not self._HISTORY_PATH.exists():
            return
        try:
            entries = []
            with open(self._HISTORY_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            # Last 30
            self._brief_history = entries[-30:]
            if self._brief_history:
                last = self._brief_history[-1]
                self._last_brief = last
                # Restore last brief timestamp
                ts_str = last.get("generated_at")
                if ts_str:
                    try:
                        self._last_brief_ts = datetime.fromisoformat(ts_str).timestamp()
                    except ValueError:
                        pass
            logger.info(
                "[Briefing] Loaded %d brief entries from history (last: %s)",
                len(self._brief_history),
                self._brief_history[-1].get("generated_at", "?")[:16] if self._brief_history else "never",
            )
        except Exception as exc:
            logger.warning("[Briefing] History load failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
#  Utility
# ══════════════════════════════════════════════════════════════════════════════

def _iso_to_ts(iso_str: str) -> float:
    """Convert ISO datetime string to epoch float. Returns 0.0 on failure."""
    if not iso_str:
        return 0.0
    try:
        return datetime.fromisoformat(iso_str).timestamp()
    except (ValueError, TypeError):
        return 0.0
