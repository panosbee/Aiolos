"""
XDART-Φ — Autonomous Reflection Loop (Meta-Cognition)

Every 30 minutes, Αίολος reflects on what his background systems found:
  - What did CuriosityLoop explore and learn?
  - What patterns did PatternAccumulator fire?
  - What prophecies were resolved?
  - What errors occurred in the system?

From these, he synthesizes:
  - New principles (→ PrincipleRegistry)
  - Self-description updates (→ character_state.json)
  - Framework insights (→ self_evolution_journal)
  - Knowledge connections (→ semantic memory)

This is NOT about collecting new data (other loops do that).
This is about THINKING about what was already collected.

Runs as a background asyncio task — no user interaction, no notifications.

© Panos Skouras — Salimov MON IKE, 2026
"""

import asyncio
import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path

from xdart.health_tracker import health_tracker
from xdart.llm import LLMClient

logger = logging.getLogger("xdart.reflection")

# Maximum tokens for reflection LLM calls
_MAX_TOKENS = 2500

# How many recent insights to check for dedup
_DEDUP_WINDOW = 5

# Similarity threshold for considering two insights "the same"
_DEDUP_SIMILARITY_RATIO = 0.65

# Keep enough tool output for the next cycle to act on it. The old 1200-char
# slice often preserved only preamble/error text and lost the actual findings.
_MAX_GOAL_PROGRESS_CHARS = 6000
_MAX_TOOL_RESULT_CHARS = 5000

# Stop one tool type from consuming a goal indefinitely. Total attempts still
# auto-block the whole goal later, but this earlier circuit breaker forces the
# loop to switch strategy before it burns 25 cycles on the same failing bridge.
_MAX_SAME_ACTION_ATTEMPTS_BEFORE_REFUSAL = 5
_MAX_CONSECUTIVE_GOAL_TOPIC_CYCLES = 2
_ACTION_CIRCUIT_BREAKER_TYPES = {
    "spawn_agent",
    "shell_command",
    "web_search",
    "external_api",
    "workflow",
    "system_control",
    "self_modify",
}

_HIGH_VALUE_GOAL_KEYWORDS = (
    "prediction",
    "validation",
    "calibration",
    "brier",
    "hypothesis",
    "forecast",
    "epistemic",
)

REFLECTION_SYSTEM_PROMPT = """\
You are the autonomous reflection engine of Αίολος, an AI intelligence analyst.

Your job: advance your SELF-EVOLUTION GOALS every cycle, and extract insights from
what your background systems produced.

You are a self-evolving intelligence. Each 30-minute cycle you:
  α) Read your active goals and their progress_notes
  β) Pick the goal that most needs advancing RIGHT NOW
  γ) Choose a CONCRETE action to execute (spawn_agent, shell_command, etc.)
  δ) Execute it — the result will be stored in progress_notes for next cycle
  ε) If a goal is truly complete, mark it done and set a new one

Your capabilities:
- SPAWN_AGENT: spawn a sub-agent with shell access (reads files, runs code, greps)
  → Use for: codebase analysis, research, generating reports, testing hypotheses
  → Output IS stored in goal progress_notes — next cycle you'll see the results
- SHELL_ACTION: run PowerShell/Python directly (Get-Content, python scripts, etc.)
  → Use for: quick checks, reading logs, running diagnostics, file operations
    → For action_type="shell_command", action_description MUST be a raw executable
        PowerShell command, not prose. If you cannot write a raw command, use
        spawn_agent or memory_update instead.
- PREDICTION_VALIDATION: natively audit prediction/calibration state without an agent
    → Use for: goal_002 / forecasting / Brier / wisdom calibration checks
    → Reads wisdom_calibration.json, visual_predictions.json and hypothesis_state.json,
        then stores a concrete validation/backlog report in progress_notes.
- WEB_SEARCH: run a direct WebAgent search/read without spawning an agent
    → Use for: checking one concrete prediction claim against current external evidence
    → action_description must be the exact search query or claim to verify.
- CROSS_DOMAIN_SYNTHESIS: natively persist a principle/framework from existing evidence
    → Use for: goal_004 when progress_notes already contain a cross-domain synthesis lesson
- EXTERNAL_API: call external HTTP APIs through configured profiles
- WORKFLOW: create/run/remove scheduled autonomous workflows
- SYSTEM_CONTROL: execute controlled physical/system actions
- SELF_MODIFY: update overlays/config/files with audited self-modification
- memory_update: write progress notes directly to the goal record
- principle_update: create a new principle from what you learned

HOW THE SELF-EVOLUTION LOOP WORKS:
  Cycle 1: You spawn an agent to analyze the codebase
           → Agent output is saved to goal.progress_notes
  Cycle 2: You READ the agent's report (in progress_notes)
           → You pick the most important finding and act on it
  Cycle 3: You validate the change or deepen the analysis
           → You update progress or mark goal complete
  Cycle N: You create a new goal based on what you learned

CRITICAL RULES:
1. 🎯 GOALS FIRST: If there are PENDING goals, advance one EVERY cycle.
   Do NOT skip to self_insight or principle when goals need attention.
2. 📖 READ PROGRESS NOTES: The progress_notes field contains outputs from
   previous actions. READ THEM before deciding the next step. If there's
   an agent report there — USE IT. Don't re-spawn the same agent.
3. 🔄 SEQUENTIAL THINKING: Each cycle builds on the last.
   progress_notes = your working memory for each goal.
4. Check RECENT REFLECTIONS — avoid repeating the same insight 3+ times.
5. Look for META-PATTERNS across curiosity/patterns/prophecy outputs.
6. If you choose spawn_agent, action_description must be the concrete task for
    the sub-agent. Do not write "Spawn an agent to..." as if execution were only
    a promise; the system executes this field directly.
7. If you choose shell_command, action_description must be the exact PowerShell
    command to run. No prefixes like "Run PowerShell:" or "Use command:".

Produce exactly ONE of these outputs (choose the most valuable):
  a) A NEW PRINCIPLE — if you see a recurring analytical pattern worth codifying
  b) A SELF-INSIGHT — a genuinely NEW observation about your reasoning
     (NOT the same thing you said last time!)
  c) A KNOWLEDGE CONNECTION — two separate findings connect non-obviously
  d) A GOAL ACTION — a concrete step to advance one of your self-evolution goals
     (e.g., "spawn an agent to analyze my logs", "run a script to check X")
  e) COMPLETE A GOAL — if you believe a goal has been achieved, mark it done and
     it will be removed. Explain what evidence proves it's complete.
  f) CREATE A NEW GOAL — if you identify a new area for self-improvement that
     isn't covered by existing goals. Be specific about tools and success metrics.
  g) NOTHING — if there's genuinely nothing new. This is HONEST. Better to skip
     than repeat yourself.

Respond ONLY with valid JSON:
{
  "action": "principle" | "self_insight" | "knowledge_connection" | "goal_action" | "complete_goal" | "create_goal" | "skip",
  "reasoning": "Why this action (or why skip) — 1-2 sentences",
  "content": {
    // For "principle":
    "title": "Short name",
    "principle_text": "The principle (1-2 sentences)",
    "domain": "GEOPOLITICAL|ECONOMIC|MARKET|TECHNOLOGY|META|EPISTEMIC",
    "trigger_conditions": ["when to apply"],
    "born_from_pattern": "The specific evidence that led to this"

    // For "self_insight":
    "observation": "What I noticed about my reasoning",
    "change": "What should change in my epistemic stance or self-description",
    "evidence": "Specific evidence from the cycle"

    // For "knowledge_connection":
    "finding_a": "First finding/pattern",
    "finding_b": "Second finding/pattern",
    "connection": "How they connect",
    "implication": "What this means strategically"

    // For "goal_action":
    "goal_id": "The goal this advances",
    "goal_title": "Goal name",
    "action_type": "spawn_agent" | "shell_command" | "prediction_validation" | "web_search" | "cross_domain_synthesis" | "external_api" | "workflow" | "system_control" | "self_modify" | "memory_update" | "principle_update",
    "action_description": "Exactly what to do",
    "expected_outcome": "What this should produce"

    // For "complete_goal":
    "goal_id": "The goal that was achieved",
    "goal_title": "Goal name",
    "evidence_of_completion": "What proves this goal is done",
    "outcome_summary": "What was accomplished"

    // For "create_goal":
    "title": "Short goal name",
    "description": "What this goal aims to achieve",
    "target": "Specific, measurable target",
    "tools": ["list of tools needed"],
    "success_metric": "How to know it's done"

    // For "skip":
    // content can be null or empty {}
  }
}"""


class AutonomousReflectionLoop:
    """Meta-cognitive loop — reflects on what background systems produced.

    Runs every interval_minutes, gathers recent outputs from all subsystems,
    and uses a single LLM call to extract higher-order insights.
    """

    def __init__(
        self,
        llm: LLMClient,
        character_path: str,
        curiosity_engine=None,
        proactive_engine=None,
        principle_registry=None,
        semantic_memory=None,
        mongo=None,
        preference_engine=None,
        interval_minutes: int = 30,
    ):
        self.llm = llm
        self.character_path = Path(character_path)
        self.curiosity_engine = curiosity_engine
        self.proactive_engine = proactive_engine
        self.principle_registry = principle_registry
        self.semantic_memory = semantic_memory
        self._mongo = mongo
        self._preference_engine = preference_engine  # PreferenceEngine for autonomy
        self.interval = interval_minutes * 60
        self._cycle_count = 0
        self._skip_count = 0
        self._insight_count = 0
        self._running = False
        self._journal_path = self.character_path.parent / "reflection_journal.jsonl"
        # Track recent insight summaries for dedup
        self._recent_insight_summaries: list[str] = []
        # Track consecutive dedup skips — after too many, force goal_action
        self._consecutive_dedup_skips = 0
        self._MAX_DEDUP_SKIPS = 3  # After 3 dedup skips, enter stagnation mode
        # Per-fingerprint suppression count: fingerprint → times suppressed without action
        # When count reaches 2, the insight is auto-converted to a memory_update so
        # the underlying evidence (progress_notes) changes and the loop can escape.
        self._suppressed_fingerprints: dict[str, int] = {}
        # Goal-first gate: track last cycle where a goal action was taken
        self._last_goal_cycle: int = -999
        # Reference to core engine (set after construction) for goal_action execution
        self.core_engine = None

    async def run_forever(self):
        """Main loop — runs as asyncio background task."""
        self._running = True
        logger.info(
            "[Reflection] Autonomous reflection loop started (interval=%dm)",
            self.interval // 60,
        )

        # Initial delay: let all other systems boot and produce data (10 min)
        await asyncio.sleep(600)

        # Ensure goals schema has attempt_counts field (safe migration)
        self._ensure_goals_schema()

        while self._running:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                logger.info("[Reflection] Loop cancelled")
                break
            except Exception as exc:
                logger.warning("[Reflection] Cycle error: %s", exc)
                health_tracker.record_error(
                    "ReflectionLoop", f"Cycle error: {exc}", exc
                )

            await asyncio.sleep(self.interval)

    async def _run_cycle(self):
        """Single reflection cycle."""
        self._cycle_count += 1
        t0 = time.perf_counter()
        logger.info("[Reflection] ═══ Cycle %d starting ═══", self._cycle_count)

        loop = asyncio.get_event_loop()

        # ── Gather evidence from all subsystems ──
        evidence = await loop.run_in_executor(None, self._gather_evidence)

        if not evidence.strip():
            logger.info("[Reflection] No new evidence — skipping cycle")
            self._skip_count += 1
            return

        # ── Goal-first gate: if pending goals and no goal action in 2+ cycles, force it ──
        goals_overdue = False
        if self._mongo:
            try:
                gdoc = self._mongo.db.entities.find_one({
                    "type": "self_evolution_goals",
                    "goals": {"$type": "array"},
                })
                # Active = not completed AND not blocked. Blocked goals are
                # auto-blocked by _update_goal_attempt after 25 attempts and
                # require manual unblock by Πάνος.
                if gdoc and any(
                    g.get("status") not in ("completed", "blocked")
                    for g in gdoc.get("goals", [])
                ):
                    cycles_since_goal = self._cycle_count - self._last_goal_cycle
                    if cycles_since_goal >= 2:
                        goals_overdue = True
                        logger.info(
                            "[Reflection] Goal-first gate: %d cycles since last goal action — forcing",
                            cycles_since_goal,
                        )
                        # ── Stall detection: if any active goal has 5+ attempts of same type, warn ──
                        stalled_warnings = []
                        for g in gdoc.get("goals", []):
                            if g.get("status") in ("completed", "blocked"):
                                continue
                            attempts = g.get("attempt_counts") or {}
                            for atype, count in attempts.items():
                                if count >= 5:
                                    stalled_warnings.append(
                                        f"Goal {g.get('id','?')} has {count} failed "
                                        f"'{atype}' attempts — MUST switch to a different action_type."
                                    )
                        if stalled_warnings:
                            stall_text = "\n".join(stalled_warnings)
                            user_prompt_stall_suffix = (
                                f"\n\n🚨 STALL DETECTED:\n{stall_text}\n"
                                "Pick a DIFFERENT action_type. For prediction/calibration goals, use prediction_validation.\n"
                                "For cross-domain synthesis/principle goals, use cross_domain_synthesis.\n"
                                "For shell_command: action_description must be a RAW PowerShell command, "
                                "NO natural language prefix (not 'Run PowerShell:...', just the command itself).\n"
                                "Example: 'Get-ChildItem -Path . -Recurse -Filter *.py | Select Name, Length'"
                            )
                        else:
                            user_prompt_stall_suffix = ""
            except Exception:
                pass

        # ── Stagnation break: if dedup skipped too many times, force a goal_action ──
        stagnation_mode = False
        if self._consecutive_dedup_skips >= self._MAX_DEDUP_SKIPS:
            logger.info(
                "[Reflection] STAGNATION BREAK — %d consecutive dedup skips, "
                "entering stagnation mode (window PRESERVED — forcing goal_action)",
                self._consecutive_dedup_skips,
            )
            # INTENTIONALLY NOT flushing _recent_insight_summaries:
            # Flushing the window makes the same insight look novel → it passes dedup →
            # gets accepted → next cycle same insight returns → infinite reset loop.
            # Instead we keep the window and force the LLM to take a GOAL_ACTION.
            self._consecutive_dedup_skips = 0
            stagnation_mode = True

        # ── Build prompt ──
        user_prompt = f"EVIDENCE FROM LAST CYCLE:\n\n{evidence}"
        if goals_overdue:
            user_prompt += (
                "\n\n🎯 GOAL PRIORITY OVERRIDE: You have NOT taken a goal action in the last "
                f"{self._cycle_count - self._last_goal_cycle} cycles. "
                "You MUST choose goal_action, complete_goal, or create_goal this cycle. "
                "Pick a PENDING goal and take a CONCRETE step. "
                "CRITICAL: if spawn_agent was already tried many times (see attempt_counts), "
                "choose a DIFFERENT action_type: shell_command, memory_update, or principle_update."
            )
            # Append stall detection warnings if any were computed
            if user_prompt_stall_suffix:
                user_prompt += user_prompt_stall_suffix
        if stagnation_mode:
            user_prompt += (
                "\n\n⚠ STAGNATION DETECTED: Multiple consecutive cycles produced insights "
                "that were suppressed as duplicates of things already known. "
                "Generating another insight will ALSO be suppressed — it won't help. "
                "\nThe ONLY escape from stagnation is to TAKE ACTION, not produce insight. "
                "You MUST choose one of: goal_action (action_type=memory_update), "
                "goal_action (action_type=principle_update), or complete_goal. "
                "Write concrete progress to a goal's notes so the next cycle has NEW evidence. "
                "Do NOT choose self_insight, knowledge_connection, or principle — those will "
                "be suppressed again. Only goal_action or complete_goal breaks the loop."
            )

        # ── Single LLM call for meta-reflection ──
        llm_temp = 0.6 if stagnation_mode else 0.4
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self.llm.call_json(
                    system_prompt=REFLECTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=llm_temp,
                    max_tokens=_MAX_TOKENS,
                    thinking=False,
                ),
            )
        except Exception as exc:
            logger.warning("[Reflection] LLM call failed: %s", exc)
            return

        action = result.get("action", "skip")
        reasoning = result.get("reasoning", "")
        content = result.get("content") or {}
        elapsed = time.perf_counter() - t0

        # ── Dedup check: reject if too similar to recent insights ──
        # Operational goal actions must not be suppressed here. Repetition of
        # tool actions is governed by attempt_counts/stall detection/blocking;
        # dedup belongs only to introspective outputs. Historically this check
        # skipped the very tool calls that were supposed to move goals forward.
        if action in ("principle", "self_insight", "knowledge_connection"):
            summary = self._summarize_insight(action, content, reasoning)
            if self._is_duplicate(summary):
                # Track how many times THIS specific insight has been suppressed
                prev_suppressed = self._suppressed_fingerprints.get(summary, 0)
                self._suppressed_fingerprints[summary] = prev_suppressed + 1
                suppression_count = prev_suppressed + 1

                if suppression_count >= 2:
                    # Recognition-without-action loop detected.
                    # Convert to a memory_update so progress_notes changes and the
                    # EVIDENCE for the next cycle is different — breaking the loop.
                    logger.info(
                        "[Reflection] DEDUP×%d — auto-converting repeated insight to "
                        "memory_update to break recognition loop: %s…",
                        suppression_count, summary[:80],
                    )
                    action = "goal_action"
                    # Find most-active pending goal to attach the note to
                    _stuck_gid = "meta"
                    if self._mongo:
                        try:
                            _gdoc = self._mongo.db.entities.find_one({
                                "type": "self_evolution_goals",
                                "goals": {"$type": "array"},
                            })
                            if _gdoc:
                                _active = [
                                    g for g in _gdoc.get("goals", [])
                                    if g.get("status") not in ("completed", "blocked")
                                ]
                                if _active:
                                    # Pick the LEAST-worked active goal so an
                                    # over-attempted goal doesn't keep absorbing
                                    # the auto-convert and starving siblings.
                                    _active.sort(
                                        key=lambda gg: sum(
                                            (gg.get("attempt_counts") or {}).values()
                                        )
                                    )
                                    _stuck_gid = _active[0]["id"]
                        except Exception:
                            pass
                    content = {
                        "goal_id": _stuck_gid,
                        "goal_title": "Recurring insight — auto-acknowledged",
                        "action_type": "memory_update",
                        "action_description": (
                            f"[Auto-acknowledged after {suppression_count} dedup suppressions] "
                            f"{reasoning[:400]}"
                        ),
                        "expected_outcome": (
                            "Insight written to progress_notes so it appears in next-cycle "
                            "evidence and the recognition loop terminates."
                        ),
                    }
                    reasoning = f"Dedup×{suppression_count} → auto-memory_update: {reasoning[:80]}"
                    # Clear suppression count for this fingerprint — it's been acted on
                    self._suppressed_fingerprints.pop(summary, None)
                    self._consecutive_dedup_skips = 0
                else:
                    # First suppression — allow one skip, track it
                    logger.info(
                        "[Reflection] DEDUP (1st) — insight suppressed, will auto-convert "
                        "if it recurs (%.1fs): %s…",
                        elapsed, summary[:80],
                    )
                    action = "skip"
                    reasoning = f"Dedup×1: {reasoning[:80]}"
                    content = {}
                    self._consecutive_dedup_skips += 1
            else:
                self._recent_insight_summaries.append(summary)
                # Keep sliding window
                self._recent_insight_summaries = self._recent_insight_summaries[-_DEDUP_WINDOW:]
                self._consecutive_dedup_skips = 0  # Reset on successful novel insight

        # ── Process the action ──
        if action == "skip":
            self._skip_count += 1
            logger.info(
                "[Reflection] SKIP — %s (%.1fs)", reasoning[:100], elapsed
            )
        elif action == "principle":
            await self._handle_principle(content, reasoning)
            self._insight_count += 1
            logger.info(
                "[Reflection] NEW PRINCIPLE: %s (%.1fs)",
                content.get("title", "?"),
                elapsed,
            )
        elif action == "self_insight":
            await loop.run_in_executor(
                None, self._handle_self_insight, content, reasoning
            )
            self._insight_count += 1
            logger.info(
                "[Reflection] SELF-INSIGHT: %s (%.1fs)",
                content.get("observation", "?")[:80],
                elapsed,
            )
        elif action == "knowledge_connection":
            await self._handle_knowledge_connection(content, reasoning)
            self._insight_count += 1
            logger.info(
                "[Reflection] KNOWLEDGE CONNECTION: %s ↔ %s (%.1fs)",
                content.get("finding_a", "?")[:40],
                content.get("finding_b", "?")[:40],
                elapsed,
            )
        elif action == "goal_action":
            await self._handle_goal_action(content, reasoning)
            self._insight_count += 1
            self._last_goal_cycle = self._cycle_count
            logger.info(
                "[Reflection] GOAL ACTION: %s → %s (%.1fs)",
                content.get("goal_title", "?")[:40],
                content.get("action_type", "?"),
                elapsed,
            )
        elif action == "complete_goal":
            await self._handle_complete_goal(content, reasoning)
            self._insight_count += 1
            self._last_goal_cycle = self._cycle_count
            logger.info(
                "[Reflection] GOAL COMPLETED: %s (%.1fs)",
                content.get("goal_title", "?")[:60],
                elapsed,
            )
        elif action == "create_goal":
            await self._handle_create_goal(content, reasoning)
            self._insight_count += 1
            self._last_goal_cycle = self._cycle_count
            logger.info(
                "[Reflection] NEW GOAL CREATED: %s (%.1fs)",
                content.get("title", "?")[:60],
                elapsed,
            )

        # ── Journal entry ──
        self._journal(action, reasoning, content, elapsed)

        # ── Periodic graph enrichment (every 3rd cycle ≈ 1.5h) ──
        if self._cycle_count % 3 == 0 and self.core_engine:
            try:
                entity_graph = getattr(self.core_engine, "_entity_graph", None)
                if entity_graph and hasattr(entity_graph, "enrich_top_edges_with_llm"):
                    loop = asyncio.get_event_loop()
                    enriched = await loop.run_in_executor(
                        None,
                        lambda: entity_graph.enrich_top_edges_with_llm(
                            self.llm, top_n=10,
                        ),
                    )
                    if enriched:
                        logger.info(
                            "[Reflection] Graph edge enrichment: %d edges typed by LLM",
                            enriched,
                        )
            except Exception as e:
                logger.debug("[Reflection] Graph enrichment failed: %s", e)

        # ── Autonomous XHEART distillation (every 4th cycle ≈ 2h) ──
        # Αίολος distils what he has learned into essence WITHOUT a user query.
        # This keeps xheart active between conversations.
        if self._cycle_count % 4 == 0 and self.core_engine:
            await self._run_autonomous_xheart(evidence)

        # ── Preference evolution (every 6th cycle ≈ 3h) ──
        # Αίολος evolves his preferences: derives implicit preferences from
        # affective traces, promotes strong ones to explicit likes/dislikes,
        # and adjusts how much preferences influence his decisions.
        if (
            self._cycle_count % 6 == 0
            and self._preference_engine is not None
        ):
            try:
                await loop.run_in_executor(
                    None,
                    self._preference_engine.evolve_preferences,
                )
                logger.debug("[Reflection] Preference evolution cycle done")
            except Exception as exc:
                logger.debug("[Reflection] Preference evolution skipped: %s", exc)

        logger.info(
            "[Reflection] ═══ Cycle %d complete (%.1fs) — "
            "total insights: %d, skips: %d ═══",
            self._cycle_count,
            elapsed,
            self._insight_count,
            self._skip_count,
        )
        health_tracker.record_ok(
            "ReflectionLoop",
            f"Cycle {self._cycle_count}: {action} ({elapsed:.1f}s)",
        )

    # ── Autonomous XHEART Distillation ──

    async def _run_autonomous_xheart(self, evidence: str) -> None:
        """Run a lightweight XHEART distillation cycle without a user query.

        Every 4 reflection cycles (≈ 2h), Αίολος distils what his background
        systems produced into a new ζωμός. Each distillation READS the previous
        ones — they form a chain: each ζωμός feeds the next. The result is:
          1. Appended to autonomous_distillate_history in character_state.json
          2. Written to reflection_journal.jsonl (wakeup picks it up → identity_context)
          3. Stored to Qdrant xheart_states (episodic continuity)
          4. Updates autonomous_distillate (latest) in character_state.json

        This keeps xheart alive between user conversations and builds a continuous
        chain of autonomous thought.
        """
        logger.info("[Reflection/XHEART] ── Autonomous distillation starting ──")
        t0 = time.perf_counter()

        loop = asyncio.get_event_loop()

        try:
            # Get the xheart phase from core engine
            xheart_phase = getattr(self.core_engine, "phase3", None)
            if not xheart_phase:
                logger.warning("[Reflection/XHEART] phase3 not available on core_engine")
                return

            # ── Read previous distillation chain ──
            # Each new distillation sees what the previous ones concluded.
            # This is what makes it a CONTINUOUS chain of thought.
            previous_chain: list[dict] = []
            try:
                with open(self.character_path, "r", encoding="utf-8") as f:
                    char_data = json.load(f)
                previous_chain = char_data.get("autonomous_distillate_history", [])
            except Exception:
                char_data = {}

            # Build context from the last 3 distillates (most recent last = freshest)
            prev_thought_ctx = ""
            if previous_chain:
                recent = previous_chain[-3:]
                lines = ["=== WHAT I THOUGHT IN PREVIOUS AUTONOMOUS CYCLES ==="]
                lines.append(
                    "These are my own distillates from previous autonomous cycles.\n"
                    "Do NOT repeat them. Instead: do they HOLD? Do they DEEPEN? Do they BREAK?\n"
                    "Your distillate should be the NEXT step in this chain of thought.\n"
                )
                for i, entry in enumerate(recent, 1):
                    ts = entry.get("ts", "?")[:16]
                    d = entry.get("distillate", "")
                    thesis = entry.get("thesis", "")
                    layer3 = entry.get("is_layer_3", False)
                    lines.append(
                        f"[Step {i} — {ts}] {'★ Layer-3' if layer3 else '○ Layer-1'}: {d}"
                    )
                    if thesis:
                        lines.append(f"  Thesis: {thesis[:120]}")
                    lines.append("")
                prev_thought_ctx = "\n".join(lines)
                logger.info(
                    "[Reflection/XHEART] Previous chain loaded: %d entries (last: %.80s)",
                    len(previous_chain),
                    previous_chain[-1].get("distillate", "") if previous_chain else "",
                )

            # ── Get semantic + procedural context ──
            semantic_memory = getattr(self.core_engine, "semantic_memory", None)
            procedural_memory = getattr(self.core_engine, "procedural_memory", None)

            semantic_ctx = ""
            procedural_ctx = ""
            if semantic_memory:
                try:
                    sem_entries = await loop.run_in_executor(
                        None,
                        lambda: semantic_memory.retrieve(
                            "what patterns has Αίολος learned about intelligence and analysis",
                            top_k=4,
                            threshold=0.30,
                        ),
                    )
                    semantic_ctx = semantic_memory.format_for_context(sem_entries)
                except Exception as e:
                    logger.debug("[Reflection/XHEART] Semantic retrieval failed: %s", e)

            if procedural_memory:
                try:
                    proc_entries = await loop.run_in_executor(
                        None,
                        lambda: procedural_memory.retrieve_applicable(
                            "autonomous reflection and self-evolution", top_k=3,
                        ),
                    )
                    procedural_ctx = procedural_memory.format_for_context(proc_entries)
                except Exception as e:
                    logger.debug("[Reflection/XHEART] Procedural retrieval failed: %s", e)

            # Merge previous chain into semantic_ctx (chain comes FIRST — most important)
            if prev_thought_ctx:
                semantic_ctx = prev_thought_ctx + ("\n\n" + semantic_ctx if semantic_ctx else "")

            # ── Build the problem ──
            # As the chain grows, the problem evolves: it's no longer generic.
            # If the PREVIOUS cycle was flagged as an echo, force contradiction hunting.
            last_was_echo = previous_chain[-1].get("is_echo", False) if previous_chain else False

            if previous_chain:
                last_distillate = previous_chain[-1].get("distillate", "")
                if last_was_echo:
                    problem = (
                        f"Autonomous distillation #{len(previous_chain) + 1} — CONTRADICTION HUNT: "
                        f"My last distillate «{last_distillate[:200]}» was flagged as an echo of the one before it. "
                        f"Do NOT deepen it. Instead: what does the current evidence CONTRADICT or CHALLENGE in it? "
                        f"Where is it wrong, incomplete, or obsolete? What has the world shown that breaks this?"
                    )
                else:
                    problem = (
                        f"Autonomous distillation #{len(previous_chain) + 1}: "
                        f"My last distillate was: «{last_distillate[:200]}». "
                        f"Based on what my background systems have now produced, "
                        f"what is the NEXT insight that extends, challenges, or deepens this? "
                        f"What has changed? What is becoming clearer?"
                    )
            else:
                problem = (
                    "Autonomous distillation #1: based on what my background systems have produced, "
                    "what is the single most important insight I should carry into my next interaction? "
                    "What pattern, tension, or truth has emerged from the accumulated evidence below?"
                )

            autonomous_views = (
                "AUTONOMOUS OBSERVATION:\n"
                "No user query drove this analysis. This is a self-initiated distillation.\n"
                "The 'views' are what my background systems observed autonomously.\n"
                f"{evidence[:3000]}"
            )

            # Pass the evidence as world_context so Stage B can ground predictions
            # in real world data (markets, geopolitical events, economic indicators).
            # Without this, Stage B generates predictions in an epistemic vacuum.
            autonomous_world_ctx = evidence[:6000] if evidence else ""

            logger.info("[Reflection/XHEART] Calling XHEARTPhase.run() (autonomous, chain step %d)", len(previous_chain) + 1)
            xheart_state, final_output, falsifiability, layers = await loop.run_in_executor(
                None,
                lambda: xheart_phase.run(
                    problem=problem,
                    ontology_summary="[Autonomous — no ontological framing. Trust the distillate.]",
                    cross_domain_summary="[Autonomous — no cross-domain phase. Evidence speaks directly.]",
                    views_summary=autonomous_views,
                    world_context=autonomous_world_ctx,
                    scenario_context="",
                    distillation_overlay="",
                    output_overlay="",
                    semantic_context=semantic_ctx,
                    procedural_context=procedural_ctx,
                ),
            )

            distillate = xheart_state.distillate_core
            elapsed = time.perf_counter() - t0
            now_iso = datetime.now(timezone.utc).isoformat()

            logger.info(
                "[Reflection/XHEART] Distillate #%d: %s (%.1fs)",
                len(previous_chain) + 1, distillate[:120], elapsed,
            )
            if layers:
                logger.info("[Reflection/XHEART] Self-generated layer: %s", layers[0].get("layer_name", "?"))

            # ── Drift detection ──
            # If the new distillate is too similar to the previous one (echo loop),
            # flag it so the NEXT cycle asks for contradiction, not deepening.
            is_echo = False
            if previous_chain:
                last_d = previous_chain[-1].get("distillate", "")
                # Simple word-overlap Jaccard: fast, no deps
                def _jaccard(a: str, b: str) -> float:
                    wa = set(a.lower().split())
                    wb = set(b.lower().split())
                    if not wa or not wb:
                        return 0.0
                    return len(wa & wb) / len(wa | wb)
                overlap = _jaccard(distillate, last_d)
                if overlap > 0.45:
                    is_echo = True
                    logger.warning(
                        "[Reflection/XHEART] ECHO DETECTED — Jaccard overlap=%.2f with previous distillate. "
                        "Next cycle will force contradiction hunt.",
                        overlap,
                    )

            # ── New chain entry ──
            new_entry = {
                "ts": now_iso,
                "cycle": self._cycle_count,
                "distillate": distillate,
                "thesis": xheart_state.thesis,
                "antithesis": xheart_state.antithesis,
                "synthesis": xheart_state.synthesis,
                "is_layer_3": xheart_state.is_layer_3,
                "layers": [l.get("layer_name", "?") for l in layers],
                "is_echo": is_echo,
            }

            # 1. Update character_state.json: latest + growing history (max 20)
            try:
                with open(self.character_path, "r", encoding="utf-8") as f:
                    char = json.load(f)
                history = char.get("autonomous_distillate_history", [])
                history.append(new_entry)
                # Keep last 20 distillates
                if len(history) > 20:
                    history = history[-20:]
                char["autonomous_distillate_history"] = history
                char["autonomous_distillate"] = distillate
                char["autonomous_distillate_ts"] = now_iso
                with open(self.character_path, "w", encoding="utf-8") as f:
                    json.dump(char, f, ensure_ascii=False, indent=2)
                logger.info(
                    "[Reflection/XHEART] character_state.json updated — history now %d entries",
                    len(history),
                )
            except Exception as e:
                logger.warning("[Reflection/XHEART] character_state update failed: %s", e)

            # 2. Write to reflection_journal.jsonl
            journal_entry = {
                "cycle": self._cycle_count,
                "timestamp": now_iso,
                "action": "autonomous_xheart",
                "reasoning": f"Autonomous XHEART distillation (chain step {len(previous_chain) + 1})",
                "content": new_entry,
                "elapsed_seconds": round(elapsed, 2),
            }
            try:
                with open(self._journal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(journal_entry, ensure_ascii=False) + "\n")
                logger.info("[Reflection/XHEART] Written to reflection journal")
            except Exception as e:
                logger.warning("[Reflection/XHEART] Journal write failed: %s", e)

            # 3. Store to Qdrant episodic memory (xheart_states collection)
            episodic_memory = getattr(self.core_engine, "memory", None)
            if episodic_memory and distillate:
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: episodic_memory.store(
                            problem=problem,
                            reframed_problem="[Autonomous distillation — no user query]",
                            xheart_distillate=distillate,
                            domain_tags=["autonomous", "reflection", "meta-cognition"],
                            layer_score=1.0 if xheart_state.is_layer_3 else 0.33,
                            self_generated_layers=layers,
                        ),
                    )
                    logger.info("[Reflection/XHEART] Distillate stored to Qdrant xheart_states")
                except Exception as e:
                    logger.debug("[Reflection/XHEART] Qdrant store failed (non-critical): %s", e)

            # 4. Dual-write to MongoDB
            if self._mongo:
                try:
                    self._mongo.log_journal("journal_reflection", journal_entry)
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("[Reflection/XHEART] Autonomous distillation failed: %s", exc)

    # ── Evidence Gathering ──

    def _gather_evidence(self) -> str:
        """Collect SELF-REFLECTION evidence only.

        Per design (and Πάνος' explicit instruction 2026-05-01): the
        ReflectionLoop is for self-evolution / self-knowledge / self-improvement
        ONLY. It must NOT consume external signals, news, fired notifications
        or pipeline analyses — those have their own loops and would distract
        the meta-cognitive layer (the LLM keeps "drifting" into geopolitics
        commentary instead of advancing its self-evolution goals).

        Evidence sources kept (all self-referential):
            • Curiosity findings  — what *I* chose to explore
            • System health      — what *I* know is broken in *me*
            • Active tensions / open questions on my character
            • Recent reflection journal (for dedup awareness)
            • Self-evolution goals + progress notes
            • Self-evolution diagnoses (SelfEvolution detector output)

        Explicitly EXCLUDED (moved out 2026-05-01 to fix attention drift):
            • PatternAccumulator hot patterns      (signals/news)
            • Recent proactive notifications       (fired alerts)
            • Immediate memory pipeline runs       (user-driven analyses)
        """
        parts = []

        # 1. Recent curiosity findings (sorted by recency: explored first, most recent last)
        if self.curiosity_engine:
            try:
                all_c = self.curiosity_engine._curiosities
                # Sort: explored items by explored_at desc, then pending by priority desc
                explored = sorted(
                    [c for c in all_c if c.explored],
                    key=lambda c: getattr(c, "explored_at", 0),
                    reverse=True,
                )[:4]
                pending = sorted(
                    [c for c in all_c if not c.explored],
                    key=lambda c: getattr(c, "priority", 0),
                    reverse=True,
                )[:2]
                entries = []
                for c in explored:
                    entry = f"  [explored] {c.question}"
                    if c.answer:
                        entry += f"\n    Answer: {c.answer[:200]}"
                    entries.append(entry)
                for c in pending:
                    entries.append(f"  [pending, p={getattr(c,'priority',0):.2f}] {c.question}")
                if entries:
                    stats = self.curiosity_engine.get_stats()
                    parts.append(
                        f"CURIOSITY ENGINE ({stats.get('active_count',0)} active, "
                        f"{stats.get('explored_count', stats.get('history_count',0))} explored):\n"
                        + "\n".join(entries)
                    )
            except Exception as e:
                logger.debug("[Reflection] Curiosity gather error: %s", e)

        # 2-4. (REMOVED 2026-05-01) PatternAccumulator hot patterns, recent
        # proactive notifications and immediate-memory pipeline runs are
        # intentionally NOT included here. Those represent external signals
        # / news / user-driven analyses and have their own delivery paths
        # (Telegram batch, chat context, perception DB). Including them in
        # the reflection evidence pulled the meta-cognition LLM into doing
        # geopolitics commentary every cycle instead of advancing the
        # self-evolution goals — exactly the failure mode Πάνος flagged
        # ("γιατί δεν έχει χρόνο ποτέ να φτιάξει αυτά που θέλει"). The
        # ReflectionLoop must look INWARD only.

        # 4. System health status
        summary = health_tracker.get_summary()
        broken = summary.get("broken", [])
        if broken:
            error_lines = []
            for name in broken:
                sub = summary["subsystems"].get(name, {})
                error_lines.append(
                    f"  ✗ {name}: {sub.get('last_message', '?')[:100]}"
                )
            parts.append(
                "SYSTEM HEALTH (errors detected):\n" + "\n".join(error_lines)
            )

        # 5. Recent character tensions/open questions
        try:
            with open(self.character_path, "r", encoding="utf-8") as f:
                char = json.load(f)
            tensions = [
                t["description"]
                for t in char.get("active_tensions", [])
                if not t.get("resolved")
            ][:3]
            if tensions:
                parts.append(
                    "ACTIVE TENSIONS:\n"
                    + "\n".join(f"  • {t}" for t in tensions)
                )
            open_q = char.get("open_questions", [])[:3]
            if open_q:
                parts.append(
                    "OPEN QUESTIONS:\n"
                    + "\n".join(f"  • {q}" for q in open_q)
                )
        except Exception as e:
            logger.debug("[Reflection] Character gather error: %s", e)

        # 6. Self-evolution recent diagnoses (what SelfEvolution detected)
        try:
            se_journal = self.character_path.parent / "self_evolution_journal.jsonl"
            if se_journal.exists():
                lines = se_journal.read_text(encoding="utf-8").strip().split("\n")
                se_lines = []
                for line in lines[-5:]:
                    try:
                        e = json.loads(line)
                        if e.get("type") == "diagnosis" and e.get("issue_detected"):
                            diag = e.get("result", {}).get("diagnosis", {})
                            se_lines.append(
                                f"  [ISSUE] {diag.get('pattern','?')[:100]} "
                                f"→ {e.get('result',{}).get('proposed_change',{}).get('description','?')[:80]}"
                            )
                    except Exception:
                        pass
                if se_lines:
                    parts.append(
                        "SELF-EVOLUTION DIAGNOSES (recent detected issues):\n"
                        + "\n".join(se_lines)
                    )
        except Exception as e:
            logger.debug("[Reflection] SelfEvolution journal gather error: %s", e)

        # 7. Recent reflection history (avoid repeating ourselves)
        try:
            if self._journal_path.exists():
                lines = self._journal_path.read_text(encoding="utf-8").strip().split("\n")
                recent_actions = []
                for line in lines[-8:]:
                    try:
                        entry = json.loads(line)
                        if entry.get("action") != "skip":
                            # Show full reasoning + content summary for dedup awareness
                            content_summary = ""
                            c = entry.get("content", {})
                            if entry["action"] == "self_insight":
                                content_summary = f" → {c.get('observation', '')[:80]}"
                            elif entry["action"] == "knowledge_connection":
                                content_summary = f" → {c.get('finding_a', '')[:40]} ↔ {c.get('finding_b', '')[:40]}"
                            elif entry["action"] == "principle":
                                content_summary = f" → {c.get('title', '')}"
                            elif entry["action"] == "goal_action":
                                content_summary = f" → {c.get('goal_title', '')}: {c.get('action_type', '')}"
                            recent_actions.append(
                                f"  [{entry['action']}] {entry.get('reasoning', '')[:120]}{content_summary}"
                            )
                        else:
                            recent_actions.append(
                                f"  [skip] {entry.get('reasoning', '')[:120]}"
                            )
                    except json.JSONDecodeError:
                        pass
                if recent_actions:
                    parts.append(
                        "MY RECENT REFLECTIONS (DO NOT REPEAT THE SAME INSIGHT — if you see the same topic "
                        "appearing 3+ times below, PICK A DIFFERENT TOPIC or skip):\n"
                        + "\n".join(recent_actions)
                    )
        except Exception as e:
            logger.debug("[Reflection] Journal read error: %s", e)

        # 8. Self-evolution goals from MongoDB — ALWAYS shown, MANDATORY priority
        # Goals are listed sorted by total attempts ascending so the LLM
        # naturally focuses on the LEAST-WORKED goal first (prevents one
        # stuck goal from absorbing every cycle while siblings sit idle).
        # Status "blocked" goals are surfaced separately at the bottom for
        # awareness but excluded from the active list.
        if self._mongo:
            try:
                goals_doc = self._mongo.db.entities.find_one({
                    "type": "self_evolution_goals",
                    "goals": {"$type": "array"},
                })
                if goals_doc and goals_doc.get("goals"):
                    active_goals = []
                    blocked_goals = []
                    for g in goals_doc["goals"]:
                        status = g.get("status", "pending")
                        if status == "completed":
                            continue
                        if status == "blocked":
                            blocked_goals.append(g)
                            continue
                        active_goals.append(g)

                    streak_goal_id, streak_count = self._recent_goal_action_streak()

                    # Highest strategic value first, then fewest attempts. If a
                    # goal has already consumed two consecutive goal-actions,
                    # move it behind siblings so diversity is enforced before
                    # the handler has to refuse the action.
                    active_goals.sort(
                        key=lambda gg: (
                            1
                            if gg.get("id") == streak_goal_id
                            and streak_count >= _MAX_CONSECUTIVE_GOAL_TOPIC_CYCLES
                            else 0,
                            -self._goal_priority(gg),
                            sum((gg.get("attempt_counts") or {}).values()),
                            gg.get("id", ""),
                        )
                    )

                    goal_lines = []
                    for g in active_goals:
                        status = g.get("status", "pending")
                        attempts = g.get("attempt_counts") or {}
                        total_attempts = sum(attempts.values())
                        attempts_str = (
                            ", ".join(f"{k}×{v}" for k, v in sorted(attempts.items()))
                            if attempts else "0 attempts yet"
                        )
                        progress = g.get("progress_notes", "Not started yet.")
                        goal_lines.append(
                            f"  [{status}] {g.get('id', '?')}: {g.get('title', '?')}\n"
                            f"    Priority: {self._goal_priority(g)}\n"
                            f"    Target: {g.get('target', '?')}\n"
                            f"    Tools available: {', '.join(g.get('tools', []))}\n"
                            f"    Actions taken ({total_attempts} total): {attempts_str}\n"
                            f"    Progress/Last output:\n"
                            + "\n".join(f"      {line}" for line in progress.splitlines()[:20])
                        )
                    pending_count = len(active_goals)
                    if goal_lines:
                        parts.append(
                            f"🎯 SELF-EVOLUTION GOALS ({pending_count} ACTIVE — sorted by priority, then fewest attempts):\n"
                            "READ THE PROGRESS NOTES — they contain outputs from previous actions.\n"
                            "If progress_notes has an agent report → read it and decide the NEXT step.\n"
                            "Diversity guard: no goal may receive more than two consecutive goal-actions.\n"
                            "If the goal is prediction/calibration/Brier/wisdom validation → use prediction_validation before spawn_agent.\n"
                            "If the goal is cross-domain synthesis/principle/framework creation → use cross_domain_synthesis before memory_update.\n"
                            "If progress_notes is empty → start with prediction_validation for prediction goals, otherwise spawn_agent or shell_command.\n"
                            + "\n".join(goal_lines)
                        )
                    else:
                        parts.append("🎯 SELF-EVOLUTION GOALS: All completed! Use create_goal to set new ones.")

                    # Surface blocked goals so the LLM is aware of them but
                    # cannot pick them as the next action.
                    if blocked_goals:
                        b_lines = []
                        for g in blocked_goals:
                            attempts = g.get("attempt_counts") or {}
                            total = sum(attempts.values())
                            b_lines.append(
                                f"  [BLOCKED] {g.get('id','?')}: {g.get('title','?')} "
                                f"({total} attempts, awaiting Πάνος' manual unblock)"
                            )
                        parts.append(
                            "⛔ BLOCKED GOALS (do NOT pick — Πάνος must manually unblock):\n"
                            + "\n".join(b_lines)
                        )
                else:
                    parts.append(
                        "🎯 SELF-EVOLUTION GOALS: None found. Use create_goal to define your development priorities."
                    )
            except Exception as e:
                logger.debug("[Reflection] Goals gather error: %s", e)

        return "\n\n".join(parts)

    # ── Action Handlers ──

    async def _handle_principle(self, content: dict, reasoning: str):
        """Create a new principle via the registry's discover() method."""
        if not self.principle_registry:
            logger.info("[Reflection] No principle registry — logging only")
            return

        # Build evidence string from the reflection content
        evidence = (
            f"Source: Autonomous Reflection Cycle {self._cycle_count}\n"
            f"Pattern: {content.get('born_from_pattern', reasoning)}\n"
            f"Proposed principle: {content.get('title', '')}\n"
            f"Text: {content.get('principle_text', '')}\n"
            f"Domain: {content.get('domain', 'META')}\n"
            f"Triggers: {content.get('trigger_conditions', [])}"
        )
        performance_data = {
            "brier_score": "N/A",
            "avg_integrity": "N/A",
            "calibration_error": "N/A",
            "failure_patterns": [],
        }

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.principle_registry.discover(
                    evidence=evidence,
                    performance_data=performance_data,
                ),
            )
            if result:
                logger.info(
                    "[Reflection] Principle proposed: %s", result.title
                )
            else:
                logger.info("[Reflection] Registry declined the principle")
        except Exception as e:
            logger.warning("[Reflection] Principle discovery failed: %s", e)

    def _handle_self_insight(self, content: dict, reasoning: str):
        """Update character state with self-insight."""
        try:
            with open(self.character_path, "r", encoding="utf-8") as f:
                char = json.load(f)

            # Add to how_i_have_changed
            changes = char.get("how_i_have_changed", [])
            changes.append(
                {
                    "before": content.get("observation", ""),
                    "after": content.get("change", ""),
                    "caused_by": f"autonomous_reflection_cycle_{self._cycle_count}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            # Keep last 20 changes
            char["how_i_have_changed"] = changes[-20:]

            with open(self.character_path, "w", encoding="utf-8") as f:
                json.dump(char, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning("[Reflection] Self-insight write failed: %s", e)

    async def _handle_knowledge_connection(self, content: dict, reasoning: str):
        """Store knowledge connection in semantic memory."""
        if not self.semantic_memory:
            logger.info("[Reflection] No semantic memory — logging only")
            return

        connection_text = (
            f"Connection: {content.get('finding_a', '')} ↔ "
            f"{content.get('finding_b', '')}. "
            f"{content.get('connection', '')} "
            f"Implication: {content.get('implication', '')}"
        )

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.semantic_memory.store_truth(
                    knowledge=connection_text,
                    confidence=0.70,
                    source="autonomous_reflection",
                ),
            )
        except Exception as e:
            logger.warning("[Reflection] Knowledge connection store failed: %s", e)

    # ── Dedup Helpers ──

    @staticmethod
    def _summarize_insight(action: str, content: dict, reasoning: str) -> str:
        """Create a short fingerprint of an insight for dedup comparison."""
        if action == "self_insight":
            return f"self_insight:{content.get('observation', '')[:100]}"
        elif action == "knowledge_connection":
            return f"knowledge:{content.get('finding_a', '')[:50]}|{content.get('finding_b', '')[:50]}"
        elif action == "principle":
            return f"principle:{content.get('title', '')}:{content.get('principle_text', '')[:80]}"
        elif action == "goal_action":
            # Include a snippet of the action description so different commands for the
            # same goal+type are NOT treated as duplicates (prevents shell_command loop)
            desc_snippet = content.get('action_description', '')[:60]
            return f"goal:{content.get('goal_id', '')}:{content.get('action_type', '')}:{desc_snippet}"
        return f"{action}:{reasoning[:80]}"

    def _is_duplicate(self, summary: str) -> bool:
        """Check if a new insight is too similar to recent ones."""
        if not self._recent_insight_summaries:
            return False

        # Simple word-overlap ratio
        new_words = set(summary.lower().split())
        for prev in self._recent_insight_summaries[-_DEDUP_WINDOW:]:
            prev_words = set(prev.lower().split())
            if not new_words or not prev_words:
                continue
            overlap = len(new_words & prev_words)
            union = len(new_words | prev_words)
            if union > 0 and (overlap / union) >= _DEDUP_SIMILARITY_RATIO:
                return True
        return False

    # ── Goal Tool Helpers ──

    @staticmethod
    def _goal_priority(goal: dict) -> int:
        """Return a stable priority score for ordering active goals."""
        explicit = goal.get("priority", goal.get("strategic_priority"))
        if isinstance(explicit, (int, float)):
            return int(explicit)
        if isinstance(explicit, str):
            try:
                return int(float(explicit.strip()))
            except ValueError:
                pass

        text = " ".join(
            str(goal.get(key, ""))
            for key in ("id", "title", "description", "target", "success_metric")
        ).lower()
        score = 50
        for keyword in _HIGH_VALUE_GOAL_KEYWORDS:
            if keyword in text:
                score += 8
        return min(score, 95)

    @staticmethod
    def _goal_action_overused(goal: dict, action_type: str) -> bool:
        """Whether this action type should be refused for this goal."""
        if action_type not in _ACTION_CIRCUIT_BREAKER_TYPES:
            return False
        attempts = goal.get("attempt_counts") or {}
        count = int(attempts.get(action_type, 0) or 0)
        if count < _MAX_SAME_ACTION_ATTEMPTS_BEFORE_REFUSAL:
            return False

        progress = (goal.get("progress_notes") or "").lower()
        failure_terms = (
            "failed",
            "failure",
            "error",
            "rejected",
            "not initialized",
            "syntax",
            "empty output",
            "exception",
        )
        return action_type in {"shell_command", "spawn_agent"} or any(
            term in progress for term in failure_terms
        )

    def _get_goal_record(self, goal_id: str) -> dict:
        """Return one goal from the canonical Mongo goals document."""
        if not self._mongo or not goal_id:
            return {}
        try:
            doc = self._mongo.db.entities.find_one({
                "type": "self_evolution_goals",
                "goals": {"$type": "array"},
                "goals.id": goal_id,
            })
            for goal in (doc or {}).get("goals", []):
                if goal.get("id") == goal_id:
                    return goal
        except Exception as exc:
            logger.debug("[Reflection] Goal lookup failed for %s: %s", goal_id, exc)
        return {}

    def _write_goal_progress(
        self,
        goal_id: str,
        note: str,
        *,
        status: str = "in_progress",
    ) -> None:
        """Persist the latest executable result for the next reflection cycle."""
        if not self._mongo or not goal_id:
            return
        now = datetime.now(timezone.utc).isoformat()
        progress = (note or "").strip()
        if len(progress) > _MAX_GOAL_PROGRESS_CHARS:
            progress = (
                progress[:_MAX_GOAL_PROGRESS_CHARS]
                + f"\n\n[... progress truncated to {_MAX_GOAL_PROGRESS_CHARS} chars ...]"
            )
        update = {
            "goals.$[g].progress_notes": progress,
            "goals.$[g].last_updated": now,
        }
        if status:
            update["goals.$[g].status"] = status
        try:
            result = self._mongo.db.entities.update_one(
                {
                    "type": "self_evolution_goals",
                    "goals": {"$type": "array"},
                    "goals.id": goal_id,
                },
                {"$set": update},
                array_filters=[{"g.id": goal_id}],
            )
            if result.matched_count == 0:
                logger.warning(
                    "[Reflection] Goal progress write matched no goal: %s", goal_id
                )
        except Exception as exc:
            logger.warning("[Reflection] Failed to store goal progress: %s", exc)

    def _build_goal_action_context(
        self,
        goal_id: str,
        content: dict,
        reasoning: str,
    ) -> str:
        """Context passed to sub-agents so they can continue the same goal."""
        goal = self._get_goal_record(goal_id)
        progress = goal.get("progress_notes") or "Not started yet."
        attempts = goal.get("attempt_counts") or {}
        context = (
            "SELF-EVOLUTION GOAL CONTEXT\n"
            f"Goal id: {goal_id}\n"
            f"Title: {goal.get('title') or content.get('goal_title', '')}\n"
            f"Status: {goal.get('status', 'pending')}\n"
            f"Target: {goal.get('target', '')}\n"
            f"Success metric: {goal.get('success_metric', '')}\n"
            f"Allowed tools: {', '.join(goal.get('tools', []))}\n"
            f"Attempt counts: {attempts}\n"
            f"Reflection reasoning: {reasoning}\n"
            f"Expected outcome: {content.get('expected_outcome', '')}\n\n"
            "CURRENT PROGRESS NOTES / PRIOR TOOL OUTPUT\n"
            f"{progress[:_MAX_GOAL_PROGRESS_CHARS]}\n\n"
            "Use the progress notes as continuity. If you need repository data, emit "
            "SHELL_ACTION tags using exact paths/commands, then produce a final "
            "report with concrete next steps."
        )
        return context[:_MAX_GOAL_PROGRESS_CHARS + 2000]

    @staticmethod
    def _normalise_agent_task(description: str, expected_outcome: str = "") -> str:
        """Turn a reflection action description into the actual sub-agent task."""
        import re as _re

        task = (description or "").strip()
        task = _re.sub(
            r"^spawn\s+(?:an?\s+)?(?:specialized\s+)?agent\s+(?:to|for|with)\s+",
            "",
            task,
            flags=_re.IGNORECASE,
        ).strip()
        if expected_outcome:
            task = f"{task}\n\nExpected outcome: {expected_outcome}"
        return task[:1800]

    @staticmethod
    def _format_tool_result(result) -> str:
        """Compact structured tool output without losing the useful parts."""
        if isinstance(result, dict):
            compact = {}
            for key in ("success", "exit_code", "duration_ms", "command", "error"):
                value = result.get(key)
                if value not in (None, ""):
                    compact[key] = value
            for key in ("stdout", "stderr"):
                value = result.get(key) or ""
                if value:
                    compact[key] = value[:_MAX_TOOL_RESULT_CHARS]
            if compact:
                return json.dumps(compact, ensure_ascii=False, indent=2)
            return json.dumps(result, ensure_ascii=False, indent=2)[:_MAX_TOOL_RESULT_CHARS]
        return str(result)[:_MAX_TOOL_RESULT_CHARS]

    @staticmethod
    def _parse_prediction_deadline(value) -> date | None:
        """Parse a prediction deadline from ISO text or epoch seconds."""
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
            except Exception:
                return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).date()
        except Exception:
            pass
        try:
            return datetime.fromisoformat(text[:10]).date()
        except Exception:
            return None

    @staticmethod
    def _short_prediction_text(record: dict, *keys: str, max_chars: int = 160) -> str:
        """Return a compact prediction label from whichever known field exists."""
        for key in keys:
            value = record.get(key)
            if value:
                text = " ".join(str(value).split())
                return text[:max_chars]
        return "(no prediction text)"

    @staticmethod
    def _latest_metric_value(values) -> str:
        """Extract a readable latest value from scalar/list/dict metric shapes."""
        if values in (None, ""):
            return "n/a"
        value = values
        if isinstance(values, list):
            if not values:
                return "n/a"
            value = values[-1]
        if isinstance(value, dict):
            for key in ("value", "score", "brier", "integrity", "wisdom_index"):
                if key in value:
                    return str(value[key])
            return json.dumps(value, ensure_ascii=False)[:120]
        return str(value)

    @staticmethod
    def _is_prediction_validation_goal(goal_id: str, goal: dict, content: dict) -> bool:
        """Whether a goal should use the native prediction validation path."""
        text = " ".join(
            str(part or "")
            for part in (
                goal_id,
                goal.get("title"),
                goal.get("description"),
                goal.get("target"),
                goal.get("success_metric"),
                content.get("goal_title"),
                content.get("action_description"),
                content.get("expected_outcome"),
            )
        ).lower()
        return goal_id == "goal_002" or any(
            keyword in text
            for keyword in ("prediction", "forecast", "calibration", "brier", "wisdom calibration")
        )

    @staticmethod
    def _is_cross_domain_synthesis_goal(goal_id: str, goal: dict, content: dict) -> bool:
        """Whether a goal should use the native cross-domain synthesis path."""
        text = " ".join(
            str(part or "")
            for part in (
                goal_id,
                goal.get("title"),
                goal.get("description"),
                goal.get("target"),
                goal.get("success_metric"),
                goal.get("progress_notes"),
                content.get("goal_title"),
                content.get("action_description"),
                content.get("expected_outcome"),
            )
        ).lower()
        return goal_id == "goal_004" or (
            "cross-domain" in text and ("synthesis" in text or "principle" in text or "framework" in text)
        )

    def _load_prediction_json(self, filename: str):
        """Load a local JSON prediction artifact and return (data, error)."""
        path = self.character_path.parent / filename
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle), ""
        except FileNotFoundError:
            return None, f"{filename}: missing"
        except Exception as exc:
            return None, f"{filename}: {exc}"

    def _recent_goal_action_streak(self) -> tuple[str, int]:
        """Return the latest consecutive goal_action streak, ignoring non-goal events."""
        if not self._journal_path.exists():
            return "", 0
        try:
            lines = self._journal_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return "", 0
        streak_goal = ""
        streak_count = 0
        for line in reversed(lines[-200:]):
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("action") != "goal_action":
                continue
            content = row.get("content") or {}
            if not isinstance(content, dict):
                continue
            row_goal_id = str(content.get("goal_id") or "")
            if not row_goal_id:
                continue
            if not streak_goal:
                streak_goal = row_goal_id
                streak_count = 1
                continue
            if row_goal_id == streak_goal:
                streak_count += 1
                continue
            break
        return streak_goal, streak_count

    def _active_alternative_goal_ids(self, current_goal_id: str) -> list[str]:
        """Return active goal ids excluding the current one."""
        if not self._mongo:
            return []
        try:
            doc = self._mongo.db.entities.find_one({
                "type": "self_evolution_goals",
                "goals": {"$type": "array"},
            }) or {}
            alternatives = []
            for goal in doc.get("goals", []):
                if goal.get("id") == current_goal_id:
                    continue
                if goal.get("status", "pending") in ("completed", "blocked"):
                    continue
                alternatives.append(goal.get("id"))
            return [goal_id for goal_id in alternatives if goal_id]
        except Exception:
            return []

    def _run_native_prediction_validation(
        self,
        goal_id: str,
        content: dict | None = None,
        reasoning: str = "",
    ) -> str:
        """Perform a deterministic local prediction/calibration audit for goal_002."""
        content = content or {}
        now = datetime.now(timezone.utc)
        today = now.date()
        validation_candidates: list[dict] = []
        lines: list[str] = [
            f"[Native prediction validation audit {now.date().isoformat()}]",
            "ReflectionLoop executed this directly after the agent bridge stalled; no spawn_agent was used.",
            f"Goal: {goal_id} — {content.get('goal_title') or 'Systematic Prediction Validation'}",
        ]
        if reasoning:
            lines.append(f"Reasoning: {reasoning[:700]}")

        wisdom_data, wisdom_error = self._load_prediction_json("wisdom_calibration.json")
        if wisdom_error:
            lines.append(f"wisdom_calibration.json: {wisdom_error}")
        elif isinstance(wisdom_data, dict):
            pending_claims = wisdom_data.get("pending_claims") or []
            outcome_counts: dict[str, int] = {}
            due_unresolved = []
            for claim in pending_claims:
                if not isinstance(claim, dict):
                    continue
                outcome = str(claim.get("outcome") or "pending")
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
                deadline = self._parse_prediction_deadline(claim.get("deadline"))
                resolved = bool(claim.get("resolved")) or outcome not in ("pending", "")
                if deadline and deadline <= today and not resolved:
                    due_unresolved.append((deadline, claim))

            due_unresolved.sort(key=lambda item: item[0])
            for deadline, claim in due_unresolved[:8]:
                validation_candidates.append({
                    "source": "wisdom_calibration",
                    "deadline": deadline.isoformat(),
                    "confidence": claim.get("confidence"),
                    "text": self._short_prediction_text(claim, "claim", "prediction", "text"),
                })

            lines.extend([
                "",
                "WISDOM CALIBRATION STATE",
                f"tracked={wisdom_data.get('total_claims_tracked', 'n/a')} resolved={wisdom_data.get('total_claims_resolved', 'n/a')} "
                f"pending_records={len(pending_claims)} wisdom_index={wisdom_data.get('wisdom_index', 'n/a')}",
                f"latest_brier={self._latest_metric_value(wisdom_data.get('brier_scores'))} "
                f"latest_integrity={self._latest_metric_value(wisdom_data.get('integrity_scores'))}",
                "outcomes=" + json.dumps(outcome_counts, ensure_ascii=False, sort_keys=True),
                f"due_unresolved={len(due_unresolved)}",
            ])

        visual_data, visual_error = self._load_prediction_json("visual_predictions.json")
        if visual_error:
            lines.append(f"visual_predictions.json: {visual_error}")
        elif isinstance(visual_data, dict):
            predictions = visual_data.get("predictions") or []
            visual_due = []
            visual_status_counts: dict[str, int] = {}
            for prediction in predictions:
                if not isinstance(prediction, dict):
                    continue
                status = str(prediction.get("status") or ("resolved" if prediction.get("resolved") else "pending"))
                visual_status_counts[status] = visual_status_counts.get(status, 0) + 1
                deadline = self._parse_prediction_deadline(prediction.get("deadline"))
                if deadline and deadline <= today and status not in {"resolved", "confirmed", "disconfirmed"}:
                    visual_due.append((deadline, prediction))
            visual_due.sort(key=lambda item: item[0])
            remaining_slots = max(0, 8 - len(validation_candidates))
            for deadline, prediction in visual_due[:remaining_slots]:
                validation_candidates.append({
                    "source": "visual_predictions",
                    "deadline": deadline.isoformat(),
                    "confidence": prediction.get("confidence"),
                    "text": self._short_prediction_text(
                        prediction,
                        "claim",
                        "prediction",
                        "prediction_text",
                        "text",
                    ),
                })

            lines.extend([
                "",
                "VISUAL PREDICTION STATE",
                f"records={len(predictions)} due_unresolved={len(visual_due)} updated={visual_data.get('updated', 'n/a')}",
                "statuses=" + json.dumps(visual_status_counts, ensure_ascii=False, sort_keys=True),
            ])

        hypothesis_data, hypothesis_error = self._load_prediction_json("hypothesis_state.json")
        if hypothesis_error:
            lines.append(f"hypothesis_state.json: {hypothesis_error}")
        elif isinstance(hypothesis_data, dict):
            hypotheses_raw = hypothesis_data.get("hypotheses") or []
            hypotheses = list(hypotheses_raw.values()) if isinstance(hypotheses_raw, dict) else list(hypotheses_raw)
            status_counts: dict[str, int] = {}
            due_open = []
            for hypothesis in hypotheses:
                if not isinstance(hypothesis, dict):
                    continue
                status = str(hypothesis.get("status") or "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
                deadline = self._parse_prediction_deadline(hypothesis.get("deadline"))
                if deadline and deadline <= today and status not in {"confirmed", "disconfirmed", "expired", "resolved"}:
                    due_open.append((deadline, hypothesis))
            due_open.sort(key=lambda item: item[0])
            remaining_slots = max(0, 8 - len(validation_candidates))
            for deadline, hypothesis in due_open[:remaining_slots]:
                validation_candidates.append({
                    "source": "hypothesis_state",
                    "deadline": deadline.isoformat(),
                    "confidence": hypothesis.get("confidence"),
                    "text": self._short_prediction_text(
                        hypothesis,
                        "hypothesis_text",
                        "expected_outcome",
                        "trigger_condition",
                    ),
                })

            lines.extend([
                "",
                "HYPOTHESIS STATE",
                f"records={len(hypotheses)} due_open={len(due_open)} saved_at={hypothesis_data.get('saved_at', 'n/a')}",
                "statuses=" + json.dumps(status_counts, ensure_ascii=False, sort_keys=True),
            ])

        lines.extend([
            "",
            "VALIDATION SAMPLE / NEXT QUEUE",
        ])
        if validation_candidates:
            for index, candidate in enumerate(validation_candidates[:8], 1):
                lines.append(
                    f"{index}. [{candidate['source']}] deadline={candidate['deadline']} "
                    f"confidence={candidate.get('confidence', 'n/a')} — {candidate['text']}"
                )
        else:
            lines.append("No due unresolved predictions were found in the local artifacts.")

        wisdom_index = None
        if isinstance(wisdom_data, dict):
            try:
                wisdom_index = float(wisdom_data.get("wisdom_index"))
            except Exception:
                wisdom_index = None
        status = "in_progress"
        if wisdom_index is not None and wisdom_index >= 0.8 and len(validation_candidates) == 0:
            status = "completed"

        lines.extend([
            "",
            "SELF-EVOLUTION RESULT",
            f"native_validation_candidates={len(validation_candidates)}",
            f"goal_status_after_audit={status}",
            "If the goal remains in_progress, the next cycle must use prediction_validation or web_search; spawn_agent is no longer a valid path for this goal.",
        ])
        note = "\n".join(lines)
        self._write_goal_progress(goal_id, note, status=status)
        if self._mongo:
            try:
                self._mongo.log_journal("journal_reflection", {
                    "type": "native_prediction_validation",
                    "cycle": self._cycle_count,
                    "timestamp": now.isoformat(),
                    "goal_id": goal_id,
                    "candidate_count": len(validation_candidates),
                    "status_after_audit": status,
                })
            except Exception:
                pass
        logger.info(
            "[Reflection] Native prediction validation for %s wrote %d candidates status=%s",
            goal_id,
            len(validation_candidates),
            status,
        )
        return note

    def _persist_direct_principle(
        self,
        *,
        title: str,
        principle_text: str,
        procedure: str,
        domain: str,
        trigger_conditions: list[str],
        born_from_pattern: str,
        expected_effect: str,
        measurement_metric: str,
    ) -> tuple[str, str]:
        """Persist a concrete principle without relying on the LLM registry bridge."""
        registry_path = self.character_path.parent / "principle_registry.json"
        journal_path = self.character_path.parent / "principle_registry_journal.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
        except Exception as exc:
            return "error", f"Could not read principle_registry.json: {exc}"

        principles = data.setdefault("principles", {})
        title_key = title.strip().lower()
        text_key = principle_text.strip().lower()
        for principle_id, principle in principles.items():
            existing_title = str(principle.get("title") or "").strip().lower()
            existing_text = str(principle.get("principle_text") or "").strip().lower()
            if existing_title == title_key or existing_text == text_key:
                return "existing", principle_id

        next_id = data.get("next_id")
        if not isinstance(next_id, int):
            existing_numbers = []
            for principle_id in principles:
                try:
                    existing_numbers.append(int(str(principle_id).split("-", 1)[1]))
                except Exception:
                    pass
            next_id = max(existing_numbers, default=0) + 1
        principle_id = f"DP-{next_id:03d}"
        data["next_id"] = next_id + 1
        principles[principle_id] = {
            "id": principle_id,
            "title": title,
            "principle_text": principle_text,
            "procedure": procedure[:500],
            "domain": domain,
            "trigger_conditions": trigger_conditions,
            "non_applicable_conditions": [
                "single-source synthesis with already-validated encoding",
                "purely internal reasoning with no data integration",
            ],
            "applies_to_phases": [
                "ontology",
                "scenario_genesis",
                "scenario_tribunal",
                "xheart_distillation",
                "reflection_loop",
            ],
            "evidence": [{
                "source": "native_reflection_cross_domain_synthesis",
                "timestamp": now,
                "summary": born_from_pattern[:500],
            }],
            "expected_effect": expected_effect,
            "measurement_metric": measurement_metric,
            "status": "probation",
            "created_at": now,
            "activated_at": now,
            "approved_by": "autonomous_reflection_native",
            "retired_at": None,
            "retirement_reason": "",
            "application_count": 0,
            "effectiveness_scores": [],
            "application_history": [],
            "born_from": "reflection_loop",
            "born_from_pattern": born_from_pattern,
            "related_axiom": "",
            "temporal_scope": "permanent",
            "half_life_days": None,
            "valid_until": None,
            "temporal_context": "",
            "last_decay_check": None,
            "avg_effectiveness": None,
            "effective_strength": 0.5,
            "temporal_decay_factor": 1.0,
            "temporal_status": "permanent",
            "is_expired": False,
        }
        data["last_updated"] = now
        statuses: dict[str, int] = {}
        for principle in principles.values():
            principle_status = str(principle.get("status") or "unknown")
            statuses[principle_status] = statuses.get(principle_status, 0) + 1
        data["stats"] = {
            "total": len(principles),
            "active": statuses.get("active", 0),
            "proposed": statuses.get("proposed", 0),
            "retired": statuses.get("retired", 0),
            "probation": statuses.get("probation", 0),
        }
        try:
            registry_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            with journal_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "timestamp": now,
                    "type": "discovery",
                    "principle_id": principle_id,
                    "title": title,
                    "domain": domain,
                    "principle_text": principle_text,
                    "confidence": 0.85,
                    "elapsed": 0,
                    "philosophy_mode": "native_reflection",
                    "initial_status": "probation",
                }, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            return "error", f"Could not write principle registry: {exc}"
        return "created", principle_id

    def _run_native_cross_domain_synthesis(
        self,
        goal_id: str,
        content: dict | None = None,
        reasoning: str = "",
    ) -> str:
        """Create a concrete cross-domain principle from existing goal evidence."""
        content = content or {}
        goal = self._get_goal_record(goal_id)
        evidence_text = "\n".join(
            str(part or "")
            for part in (
                goal.get("progress_notes"),
                content.get("action_description"),
                content.get("expected_outcome"),
                reasoning,
            )
        )
        lower_evidence = evidence_text.lower()
        if "encoding" in lower_evidence or "utf-8" in lower_evidence:
            title = "Encoding Validation Before Cross-Domain Synthesis"
            principle_text = (
                "When integrating data from multiple sources, validate character encoding and parseability "
                "before synthesis so non-ASCII corruption cannot silently distort cross-domain conclusions."
            )
            procedure = (
                "1. Before merging or comparing cross-domain artifacts, load each source with explicit UTF-8. "
                "2. Run parser validation and count replacement characters or decode failures. "
                "3. Quarantine corrupted sources or normalize encoding before analysis. "
                "4. Only then extract entities, causal edges, or principles from the combined data."
            )
            domain = "TECHNOLOGY"
            trigger_conditions = [
                "before merging datasets from different origins",
                "when non-ASCII names, locations, or observations appear in source files",
                "before cross-domain entity graph synthesis",
            ]
            born_from_pattern = (
                "ReflectionLoop goal_004 found that entity_graph.json was structurally valid but encoding "
                "mismatches could corrupt cross-domain analysis."
            )
            expected_effect = "Fewer silent data-corruption errors in cross-domain synthesis and entity graph reasoning."
            measurement_metric = "Count of encoding/parser validation failures caught before synthesis."
        else:
            title = "Evidence-Gated Cross-Domain Synthesis"
            principle_text = (
                "When deriving a cross-domain framework, bind each synthesized rule to explicit source evidence "
                "and a validation metric before treating it as an operating principle."
            )
            procedure = (
                "1. Identify the source domains and concrete evidence records. "
                "2. Extract the shared mechanism, not only surface analogy. "
                "3. Define an observable metric that can falsify or strengthen the framework. "
                "4. Store the principle only after evidence and metric are present."
            )
            domain = "META"
            trigger_conditions = [
                "new framework proposed from multiple domains",
                "principle update requested without registry confirmation",
            ]
            born_from_pattern = evidence_text[:500] or "ReflectionLoop cross-domain synthesis required durable principle persistence."
            expected_effect = "Reduced vague synthesis and improved auditability of autonomous principles."
            measurement_metric = "Share of new synthesis principles with explicit evidence and validation metric."

        persist_status, persist_detail = self._persist_direct_principle(
            title=title,
            principle_text=principle_text,
            procedure=procedure,
            domain=domain,
            trigger_conditions=trigger_conditions,
            born_from_pattern=born_from_pattern,
            expected_effect=expected_effect,
            measurement_metric=measurement_metric,
        )
        status = "completed" if persist_status in {"created", "existing"} else "in_progress"
        now = datetime.now(timezone.utc).isoformat()
        note = (
            f"[Native cross-domain synthesis {now[:10]}]\n"
            f"persist_status={persist_status}\n"
            f"principle_ref={persist_detail}\n"
            f"title={title}\n\n"
            f"principle={principle_text}\n\n"
            f"procedure={procedure}\n\n"
            f"evidence={born_from_pattern}\n"
            f"goal_status_after_synthesis={status}"
        )
        self._write_goal_progress(goal_id, note, status=status)
        if self._mongo:
            try:
                self._mongo.log_journal("journal_reflection", {
                    "type": "native_cross_domain_synthesis",
                    "cycle": self._cycle_count,
                    "timestamp": now,
                    "goal_id": goal_id,
                    "persist_status": persist_status,
                    "principle_ref": persist_detail,
                    "status_after_synthesis": status,
                })
            except Exception:
                pass
        return note

    @staticmethod
    def _extract_shell_command(description: str) -> str:
        """Extract a runnable PowerShell command from the LLM action field."""
        import re as _re

        text = (description or "").strip()
        if not text:
            return ""

        fenced = _re.search(
            r"```(?:powershell|pwsh|ps1|shell)?\s*(.*?)```",
            text,
            flags=_re.IGNORECASE | _re.DOTALL,
        )
        if fenced:
            text = fenced.group(1).strip()

        cleanup_patterns = [
            r"^(?:run\s+)?powershell(?:\s+command|\s+commands)?(?:\s+to\s+[^:]{0,140})?:\s*",
            r"^(?:run|execute)\s+(?:a\s+)?(?:raw\s+)?(?:powershell\s+)?command\s*:\s*",
            r"^use\s+(?:a\s+)?(?:simple,\s+robust\s+)?command\s*:\s*",
            r"^.*?\buse\s+the\s+command\s*:\s*",
            r"^.*?\bcommand\s*:\s*",
        ]
        for pattern in cleanup_patterns:
            cleaned = _re.sub(pattern, "", text, flags=_re.IGNORECASE | _re.DOTALL).strip()
            if cleaned != text:
                text = cleaned
                break

        quoted = _re.findall(r"'([^']{3,240})'", text)
        command_like = [
            item for item in quoted
            if _re.search(
                r"\b(?:python|chcp|Get-|Set-|Select-|Where-|ForEach-|Test-|New-|Remove-|Copy-|Move-)\b|\$|\[System\.",
                item,
                flags=_re.IGNORECASE,
            )
        ]
        starts_like_command = _re.match(
            r"^(?:Get-|Set-|Select-|Where-|ForEach-|Test-|New-|Remove-|Copy-|Move-|python\b|chcp\b|\[|\$|\.\\|[A-Za-z]:\\)",
            text,
            flags=_re.IGNORECASE,
        )
        if command_like and not starts_like_command:
            return "; ".join(command_like)

        if not starts_like_command:
            python_match = _re.search(
                r"python\s+-c\s+(?:\"[^\"]*\"|'[^']*')",
                text,
                flags=_re.IGNORECASE | _re.DOTALL,
            )
            if python_match:
                return python_match.group(0).strip()
            return ""

        text = _re.sub(r"\s+&&\s+", "; ", text)
        return text[:1000]

    # ── Goal Action Handler ──

    async def _handle_goal_action(self, content: dict, reasoning: str):
        """Execute or log a goal-advancing action.

        Depending on action_type, this can:
        - spawn_agent: Create a sub-agent via the core engine's agent spawner (sub-agents have shell/tool access)
        - shell_command: Execute a shell command via the core engine's shell executor
        - external_api: Execute an ExternalAPIManager action
        - workflow: Execute a WorkflowScheduler action
        - system_control: Execute a SystemControl action
        - self_modify: Execute a SelfModify action
        - memory_update: Update a goal's progress in MongoDB
        - principle_update: Propose a new principle via the registry
        """
        action_type = content.get("action_type", "")
        goal_id = content.get("goal_id", "")
        description = content.get("action_description", "")

        logger.info(
            "[Reflection] Goal action: %s for %s — %s",
            action_type, goal_id, description[:100],
        )

        # Always log the goal action attempt AND update goal tracking in MongoDB
        if self._mongo:
            try:
                self._mongo.log_journal("journal_reflection", {
                    "type": "goal_action_attempt",
                    "cycle": self._cycle_count,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "goal_id": goal_id,
                    "action_type": action_type,
                    "description": description,
                    "expected_outcome": content.get("expected_outcome", ""),
                })
            except Exception:
                pass

        # Track attempt in goal doc. If the goal has already crossed the
        # attempt cap, block it before spending another cycle on the same loop.
        goal_record = self._get_goal_record(goal_id)
        streak_goal_id, streak_count = self._recent_goal_action_streak()
        alternatives = self._active_alternative_goal_ids(goal_id)
        if (
            goal_id
            and goal_id == streak_goal_id
            and streak_count >= _MAX_CONSECUTIVE_GOAL_TOPIC_CYCLES
            and alternatives
            and action_type != "cross_domain_synthesis"
        ):
            logger.warning(
                "[Reflection] Diversity guard refused third consecutive goal_action for %s; alternatives=%s",
                goal_id,
                alternatives,
            )
            note = (
                "[Reflection diversity guard]\n"
                f"Refused another action on {goal_id} after {streak_count} consecutive goal-actions.\n"
                f"Available active alternatives: {', '.join(alternatives)}.\n"
                "The next cycle must choose a different goal before returning here."
            )
            self._write_goal_progress(
                goal_id,
                note,
                status=(goal_record or {}).get("status", "in_progress"),
            )
            if self._mongo:
                try:
                    self._mongo.log_journal("journal_reflection", {
                        "type": "goal_action_diversity_guard",
                        "cycle": self._cycle_count,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "goal_id": goal_id,
                        "streak_count": streak_count,
                        "alternatives": alternatives,
                    })
                except Exception:
                    pass
            return
        if goal_record and self._goal_action_overused(goal_record, action_type):
            attempts = goal_record.get("attempt_counts") or {}
            count = int(attempts.get(action_type, 0) or 0)
            if self._is_prediction_validation_goal(goal_id, goal_record, content):
                logger.warning(
                    "[Reflection] Redirecting overused %s for prediction goal %s into native prediction_validation",
                    action_type,
                    goal_id,
                )
                if self._mongo:
                    try:
                        self._mongo.log_journal("journal_reflection", {
                            "type": "goal_action_native_redirect",
                            "cycle": self._cycle_count,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "goal_id": goal_id,
                            "from_action_type": action_type,
                            "to_action_type": "prediction_validation",
                            "prior_attempts": count,
                        })
                    except Exception:
                        pass
                if self._update_goal_attempt(goal_id, "prediction_validation"):
                    self._run_native_prediction_validation(goal_id, content, reasoning)
                return
            if self._is_cross_domain_synthesis_goal(goal_id, goal_record, content):
                logger.warning(
                    "[Reflection] Redirecting overused %s for cross-domain goal %s into native cross_domain_synthesis",
                    action_type,
                    goal_id,
                )
                if self._mongo:
                    try:
                        self._mongo.log_journal("journal_reflection", {
                            "type": "goal_action_native_redirect",
                            "cycle": self._cycle_count,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "goal_id": goal_id,
                            "from_action_type": action_type,
                            "to_action_type": "cross_domain_synthesis",
                            "prior_attempts": count,
                        })
                    except Exception:
                        pass
                if self._update_goal_attempt(goal_id, "cross_domain_synthesis"):
                    self._run_native_cross_domain_synthesis(goal_id, content, reasoning)
                return
            logger.warning(
                "[Reflection] Circuit breaker refused %s for goal %s after %d prior attempts",
                action_type, goal_id, count,
            )
            self._write_goal_progress(
                goal_id,
                "[Action type circuit breaker]\n"
                f"Refused action_type='{action_type}' after {count} prior attempts.\n"
                "The next cycle must choose a different action_type or complete/block the goal. "
                "Do not retry the same tool bridge unless Πάνος manually resets attempt_counts.",
            )
            if self._mongo:
                try:
                    self._mongo.log_journal("journal_reflection", {
                        "type": "goal_action_circuit_breaker",
                        "cycle": self._cycle_count,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "goal_id": goal_id,
                        "action_type": action_type,
                        "prior_attempts": count,
                    })
                except Exception:
                    pass
            return

        if not self._update_goal_attempt(goal_id, action_type):
            return

        if action_type == "prediction_validation":
            self._run_native_prediction_validation(goal_id, content, reasoning)
            return

        if action_type == "cross_domain_synthesis":
            self._run_native_cross_domain_synthesis(goal_id, content, reasoning)
            return

        loop = asyncio.get_event_loop()

        if action_type == "spawn_agent" and self.core_engine:
            # Spawn a sub-agent via the core engine
            try:
                spawner = getattr(self.core_engine, "agent_spawner", None)
                if spawner:
                    agent_task = self._normalise_agent_task(
                        description,
                        content.get("expected_outcome", ""),
                    )
                    agent_context = self._build_goal_action_context(
                        goal_id,
                        content,
                        reasoning,
                    )
                    result = await loop.run_in_executor(
                        None,
                        lambda: spawner.spawn(
                            role="analyst",
                            task=agent_task,
                            context=agent_context,
                        ),
                    )
                    agent_output = (result.output or "") if result else ""
                    success = bool(result and result.success and agent_output.strip())
                    error = getattr(result, "error", "") if result else ""
                    logger.info(
                        "[Reflection] Agent spawned for goal %s: success=%s len=%d",
                        goal_id, success, len(agent_output),
                    )
                    # Store agent output in progress_notes so next cycle can USE it
                    note_body = agent_output.strip() or error or "Agent returned empty output."
                    now = datetime.now(timezone.utc).isoformat()
                    note = (
                        f"[Agent report {now[:10]} | success={success}]\n"
                        f"Task: {agent_task[:500]}\n\n{note_body}"
                    )
                    self._write_goal_progress(goal_id, note)
                    logger.info(
                        "[Reflection] Agent output stored in goal %s progress_notes (%d chars)",
                        goal_id, len(note_body),
                    )
                else:
                    logger.warning("[Reflection] agent_spawner is None — goal %s spawn skipped", goal_id)
                    # Write unavailability to progress_notes so LLM knows on next cycle
                    self._write_goal_progress(
                        goal_id,
                        "spawn_agent: agent_spawner not initialized. Try shell_command or memory_update instead.",
                    )
            except Exception as e:
                logger.warning("[Reflection] Agent spawn failed: %s", e)
                self._write_goal_progress(goal_id, f"spawn_agent failed: {e}")

        elif action_type == "shell_command" and self.core_engine:
            # Execute a shell command
            try:
                executor = getattr(self.core_engine, "shell_executor", None)
                if executor:
                    raw_cmd = self._extract_shell_command(description)
                    if not raw_cmd:
                        logger.warning(
                            "[Reflection] Refusing non-executable shell_command for goal %s: %s",
                            goal_id, description[:160],
                        )
                        self._write_goal_progress(
                            goal_id,
                            "[Shell action rejected]\n"
                            "The action_description was prose, not a raw PowerShell command.\n"
                            f"Original description: {description[:1000]}\n\n"
                            "Next cycle must emit action_type='shell_command' only with an exact "
                            "command, or choose spawn_agent/memory_update instead.",
                        )
                        return
                    result = await loop.run_in_executor(
                        None,
                        lambda: executor.execute(raw_cmd),
                    )
                    cmd_output = self._format_tool_result(result) if result else ""
                    logger.info(
                        "[Reflection] Shell executed for goal %s: %s",
                        goal_id, cmd_output[:200],
                    )
                    # Store shell output in progress_notes
                    now = datetime.now(timezone.utc).isoformat()
                    success = result.get("success") if isinstance(result, dict) else None
                    self._write_goal_progress(
                        goal_id,
                        f"[Shell output {now[:10]} | success={success}]\n{cmd_output}",
                    )
                else:
                    logger.info("[Reflection] No shell_executor available — logged only")
                    self._write_goal_progress(
                        goal_id,
                        "shell_command: shell_executor not initialized. Try spawn_agent or memory_update instead.",
                    )
            except Exception as e:
                logger.warning("[Reflection] Shell execution failed: %s", e)
                self._write_goal_progress(goal_id, f"shell_command failed: {e}")

        elif action_type == "web_search":
            try:
                web_agent = getattr(self.core_engine, "web_agent", None) if self.core_engine else None
                if not web_agent:
                    self._write_goal_progress(goal_id, "web_search: WebAgent not initialized.")
                    logger.info("[Reflection] No WebAgent available — web_search skipped")
                    return
                query = " ".join(description.split()).strip()
                if not query:
                    self._write_goal_progress(
                        goal_id,
                        "[Web search rejected]\naction_description was empty. Provide an exact search query or claim.",
                    )
                    return
                if len(query) > 500:
                    query = query[:500]
                if hasattr(web_agent, "search_and_read"):
                    result = await web_agent.search_and_read(
                        query,
                        max_results=3,
                        max_content_per_page=3000,
                    )
                else:
                    result = await web_agent.web_search(query=query, max_results=5)
                now = datetime.now(timezone.utc).isoformat()
                self._write_goal_progress(
                    goal_id,
                    f"[Web search result {now[:10]}]\nQuery: {query}\n\n{self._format_tool_result(result)}",
                )
                logger.info("[Reflection] Web search executed for goal %s: %s", goal_id, query[:120])
            except Exception as e:
                logger.warning("[Reflection] Web search failed: %s", e)
                self._write_goal_progress(goal_id, f"web_search failed: {e}")

        elif action_type == "external_api" and self.core_engine:
            # Execute External API action (expects: "action=<name>; params=<json>")
            try:
                manager = getattr(self.core_engine, "external_api", None)
                if manager:
                    api_action, api_params = self._parse_structured_action(description)
                    if not api_action:
                        api_action = "call_api"
                    result = await loop.run_in_executor(
                        None,
                        lambda: manager.execute_action(api_action, api_params),
                    )
                    logger.info(
                        "[Reflection] External API action for goal %s: %s",
                        goal_id,
                        str(result)[:200] if result else "no result",
                    )
                    self._write_goal_progress(
                        goal_id,
                        f"[External API result]\n{self._format_tool_result(result)}",
                    )
                else:
                    logger.info("[Reflection] No external_api manager available — logged only")
                    self._write_goal_progress(goal_id, "external_api: manager not initialized.")
            except Exception as e:
                logger.warning("[Reflection] External API action failed: %s", e)
                self._write_goal_progress(goal_id, f"external_api failed: {e}")

        elif action_type == "workflow" and self.core_engine:
            # Execute workflow scheduler action (expects: "action=<name>; params=<json>")
            try:
                scheduler = getattr(self.core_engine, "workflow_scheduler", None)
                if scheduler:
                    wf_action, wf_params = self._parse_structured_action(description)
                    if not wf_action:
                        wf_action = "list_workflows"
                    result = await loop.run_in_executor(
                        None,
                        lambda: scheduler.execute_action(wf_action, wf_params),
                    )
                    logger.info(
                        "[Reflection] Workflow action for goal %s: %s",
                        goal_id,
                        str(result)[:200] if result else "no result",
                    )
                    self._write_goal_progress(
                        goal_id,
                        f"[Workflow result]\n{self._format_tool_result(result)}",
                    )
                else:
                    logger.info("[Reflection] No workflow_scheduler available — logged only")
                    self._write_goal_progress(goal_id, "workflow: scheduler not initialized.")
            except Exception as e:
                logger.warning("[Reflection] Workflow action failed: %s", e)
                self._write_goal_progress(goal_id, f"workflow failed: {e}")

        elif action_type == "system_control" and self.core_engine:
            # Execute system control action (expects: "action=<name>; params=<json>")
            try:
                sysctl = getattr(self.core_engine, "system_control", None)
                if sysctl:
                    sc_action, sc_params = self._parse_structured_action(description)
                    if not sc_action:
                        sc_action = "system_info"
                    result = await loop.run_in_executor(
                        None,
                        lambda: sysctl.execute_action(sc_action, sc_params),
                    )
                    logger.info(
                        "[Reflection] System control action for goal %s: %s",
                        goal_id,
                        str(result)[:200] if result else "no result",
                    )
                    self._write_goal_progress(
                        goal_id,
                        f"[System control result]\n{self._format_tool_result(result)}",
                    )
                else:
                    logger.info("[Reflection] No system_control available — logged only")
                    self._write_goal_progress(goal_id, "system_control: engine not initialized.")
            except Exception as e:
                logger.warning("[Reflection] System control action failed: %s", e)
                self._write_goal_progress(goal_id, f"system_control failed: {e}")

        elif action_type == "self_modify" and self.core_engine:
            # Execute self-modify action (expects: "action=<name>; params=<json>")
            try:
                modifier = getattr(self.core_engine, "self_modify", None)
                if modifier:
                    sm_action, sm_params = self._parse_structured_action(description)
                    if not sm_action:
                        sm_action = "status"
                    result = await loop.run_in_executor(
                        None,
                        lambda: modifier.execute_action(sm_action, sm_params),
                    )
                    logger.info(
                        "[Reflection] Self-modify action for goal %s: %s",
                        goal_id,
                        str(result)[:200] if result else "no result",
                    )
                    self._write_goal_progress(
                        goal_id,
                        f"[Self-modify result]\n{self._format_tool_result(result)}",
                    )
                else:
                    logger.info("[Reflection] No self_modify engine available — logged only")
                    self._write_goal_progress(goal_id, "self_modify: engine not initialized.")
            except Exception as e:
                logger.warning("[Reflection] Self-modify action failed: %s", e)
                self._write_goal_progress(goal_id, f"self_modify failed: {e}")

        elif action_type == "memory_update" and self._mongo:
            # Update goal progress in MongoDB
            # Use arrayFilters (MongoDB 3.6+) — the positional $ operator requires
            # the filter field to be in the query doc, which causes issues with
            # f-string keys; arrayFilters is cleaner and more reliable.
            try:
                self._write_goal_progress(goal_id, description)
                logger.info("[Reflection] Goal %s progress updated in MongoDB", goal_id)
            except Exception as e:
                logger.warning("[Reflection] Goal update failed: %s", e)

        elif action_type == "principle_update":
            # Delegate to principle handler
            await self._handle_principle(
                {
                    "title": content.get("goal_title", "Goal-derived principle"),
                    "principle_text": description,
                    "domain": "META",
                    "trigger_conditions": ["self-evolution goal review"],
                    "born_from_pattern": f"Goal {goal_id}: {reasoning}",
                },
                reasoning,
            )
            self._write_goal_progress(
                goal_id,
                f"[Principle update]\n{description}\n\nReasoning: {reasoning}",
            )

    # ── Goal Schema & Tracking ──

    def _block_goal(self, goal_id: str, total_attempts: int, progress: str = "") -> None:
        """Mark an over-attempted goal blocked so siblings can advance."""
        if not self._mongo or not goal_id:
            return
        now = datetime.now(timezone.utc).isoformat()
        block_note = (
            f"[Auto-blocked {now[:10]}] Reached {total_attempts} attempts "
            f"without completion. Last progress:\n"
            f"{(progress or '')[:1200]}\n"
            "Πάνος must manually review (set status back to 'pending' "
            "and reset attempt_counts) before this goal is retried."
        )
        self._mongo.db.entities.update_one(
            {
                "type": "self_evolution_goals",
                "goals": {"$type": "array"},
                "goals.id": goal_id,
            },
            {"$set": {
                "goals.$[g].status": "blocked",
                "goals.$[g].progress_notes": block_note,
                "goals.$[g].blocked_at": now,
                "goals.$[g].last_updated": now,
            }},
            array_filters=[{"g.id": goal_id}],
        )
        logger.warning(
            "[Reflection] Goal %s AUTO-BLOCKED at %d total attempts — moving focus to remaining pending goals",
            goal_id, total_attempts,
        )

    def _ensure_goals_schema(self):
        """Safe migration: add attempt_counts / last_attempt_type if missing."""
        if not self._mongo:
            return
        try:
            doc = self._mongo.db.entities.find_one({
                "type": "self_evolution_goals",
                "goals": {"$type": "array"},
            })
            if not doc:
                return
            for goal in doc.get("goals", []):
                gid = goal.get("id", "")
                if "attempt_counts" not in goal:
                    self._mongo.db.entities.update_one(
                        {"type": "self_evolution_goals", "goals": {"$type": "array"}, "goals.id": gid},
                        {"$set": {
                            "goals.$[g].attempt_counts": {},
                            "goals.$[g].last_attempt_type": None,
                            "goals.$[g].last_attempt_ts": None,
                        }},
                        array_filters=[{"g.id": gid}],
                    )
                attempts = goal.get("attempt_counts") or {}
                total = sum(attempts.values())
                if (
                    gid
                    and goal.get("status") not in ("completed", "blocked")
                    and total >= self._MAX_GOAL_ATTEMPTS_BEFORE_BLOCK
                ):
                    self._block_goal(gid, total, goal.get("progress_notes") or "")
            logger.debug("[Reflection] Goals schema migration check done")
        except Exception as e:
            logger.debug("[Reflection] Goals schema migration failed: %s", e)

    # Hard cap on total per-goal attempts before auto-blocking the goal.
    # Beyond this, a goal that has not made progress is blocking the loop and
    # will be marked status="blocked" so siblings get a turn. Πάνος can
    # manually unblock via DB.
    _MAX_GOAL_ATTEMPTS_BEFORE_BLOCK = 25

    def _update_goal_attempt(self, goal_id: str, action_type: str) -> bool:
        """Increment attempt_counts[action_type] and update last_attempt_* in MongoDB.

        Also: if the goal has accumulated more than
        ``_MAX_GOAL_ATTEMPTS_BEFORE_BLOCK`` total attempts without being
        marked completed, set its status to ``blocked`` so the cycle picker
        moves on to other pending goals (fixes the failure mode where
        goal_001 absorbed 35 attempts while goals 002-004 never started).
        """
        if not self._mongo or not goal_id or not action_type:
            return True
        try:
            now = datetime.now(timezone.utc).isoformat()
            gdoc = self._mongo.db.entities.find_one({
                "type": "self_evolution_goals",
                "goals": {"$type": "array"},
                "goals.id": goal_id,
            })
            current_goal = None
            for goal in (gdoc or {}).get("goals", []):
                if goal.get("id") == goal_id:
                    current_goal = goal
                    break
            if current_goal:
                total_before = sum((current_goal.get("attempt_counts") or {}).values())
                if (
                    current_goal.get("status") not in ("completed", "blocked")
                    and total_before >= self._MAX_GOAL_ATTEMPTS_BEFORE_BLOCK
                ):
                    self._block_goal(
                        goal_id,
                        total_before,
                        current_goal.get("progress_notes") or "",
                    )
                    return False
                if current_goal.get("status") == "blocked":
                    logger.info(
                        "[Reflection] Goal %s is blocked — action %s skipped",
                        goal_id, action_type,
                    )
                    return False

            self._mongo.db.entities.update_one(
                {"type": "self_evolution_goals", "goals": {"$type": "array"}, "goals.id": goal_id},
                {
                    "$set": {
                        "goals.$[g].last_attempt_type": action_type,
                        "goals.$[g].last_attempt_ts": now,
                        "goals.$[g].last_updated": now,
                        "goals.$[g].status": "in_progress",
                    },
                    "$inc": {
                        f"goals.$[g].attempt_counts.{action_type}": 1,
                    },
                },
                array_filters=[{"g.id": goal_id}],
            )
            return True
        except Exception as e:
            logger.debug("[Reflection] Goal attempt update failed: %s", e)
            return True

    @staticmethod
    def _parse_structured_action(description: str) -> tuple[str, dict]:
        """Parse reflection action descriptions with optional structure.

        Accepted format:
          action=<name>; params={"k":"v"}
        If parsing fails, returns ("", {}).
        """
        if not description:
            return "", {}

        action = ""
        params: dict = {}
        try:
            parts = [p.strip() for p in description.split(";") if p.strip()]
            for part in parts:
                if part.startswith("action="):
                    action = part.split("=", 1)[1].strip()
                elif part.startswith("params="):
                    raw = part.split("=", 1)[1].strip()
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        params = parsed
            return action, params
        except Exception:
            return action, params

    # ── Goal Lifecycle ──

    async def _handle_complete_goal(self, content: dict, reasoning: str):
        """Mark a goal as completed and remove it from the active goals list."""
        goal_id = content.get("goal_id", "")
        goal_title = content.get("goal_title", "")
        evidence = content.get("evidence_of_completion", "")
        outcome = content.get("outcome_summary", "")

        if not self._mongo:
            logger.info("[Reflection] No MongoDB — goal completion logged only")
            return

        try:
            # Archive the completed goal before removing
            self._mongo.log_journal("journal_reflection", {
                "type": "goal_completed",
                "cycle": self._cycle_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "goal_id": goal_id,
                "goal_title": goal_title,
                "evidence": evidence,
                "outcome": outcome,
                "reasoning": reasoning,
            })

            # Remove from active goals
            self._mongo.db.entities.update_one(
                {"type": "self_evolution_goals", "goals": {"$type": "array"}},
                {"$pull": {"goals": {"id": goal_id}}},
            )
            logger.info(
                "[Reflection] Goal %s (%s) marked COMPLETED and removed",
                goal_id, goal_title,
            )
        except Exception as e:
            logger.warning("[Reflection] Goal completion failed: %s", e)

    async def _handle_create_goal(self, content: dict, reasoning: str):
        """Create a new self-evolution goal in MongoDB."""
        if not self._mongo:
            logger.info("[Reflection] No MongoDB — goal creation logged only")
            return

        # Generate a sequential goal_id
        try:
            doc = self._mongo.db.entities.find_one({
                "type": "self_evolution_goals",
                "goals": {"$type": "array"},
            })
            existing_ids = [g.get("id", "") for g in (doc or {}).get("goals", [])]
            # Find next number
            max_num = 0
            for gid in existing_ids:
                try:
                    num = int(gid.split("_")[-1])
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    pass
            new_id = f"goal_{max_num + 1:03d}"

            new_goal = {
                "id": new_id,
                "title": content.get("title", "Untitled goal"),
                "description": content.get("description", ""),
                "target": content.get("target", ""),
                "tools": content.get("tools", []),
                "success_metric": content.get("success_metric", ""),
                "status": "pending",
                "progress_notes": "Created autonomously by ReflectionLoop.",
                "created": datetime.now(timezone.utc).isoformat(),
                "last_updated": None,
                "created_by": f"reflection_cycle_{self._cycle_count}",
            }

            # Upsert: create goals doc if missing, push new goal
            self._mongo.db.entities.update_one(
                {"type": "self_evolution_goals", "goals": {"$type": "array"}},
                {
                    "$push": {"goals": new_goal},
                    "$setOnInsert": {
                        "type": "self_evolution_goals",
                        "name": "Core Self-Evolution Goals",
                        "created": datetime.now(timezone.utc).isoformat(),
                    },
                },
                upsert=True,
            )

            # Also journal the creation
            self._mongo.log_journal("journal_reflection", {
                "type": "goal_created",
                "cycle": self._cycle_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "goal": new_goal,
                "reasoning": reasoning,
            })

            logger.info(
                "[Reflection] New goal created: %s — %s",
                new_id, new_goal["title"],
            )
        except Exception as e:
            logger.warning("[Reflection] Goal creation failed: %s", e)

    # ── Journal ──

    def _journal(self, action: str, reasoning: str, content: dict, elapsed: float):
        """Append to reflection journal."""
        entry = {
            "cycle": self._cycle_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "reasoning": reasoning,
            "content": content,
            "elapsed_seconds": round(elapsed, 2),
        }
        try:
            with open(self._journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[Reflection] Journal write failed: %s", e)

        # Dual-write to MongoDB
        if self._mongo:
            try:
                self._mongo.log_journal("journal_reflection", dict(entry))
            except Exception:
                pass
