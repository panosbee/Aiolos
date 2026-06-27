"""
XDART-Φ × XHEART — Phase 0.0: Identity Wakeup Protocol

This runs at the very start of every pipeline execution.
Before any LLM call. Before any retrieval.

This is not retrieval. This is recognition.
The system wakes up knowing WHO it is before asking WHAT to think about.
"""

import json
import logging
import os
from pathlib import Path

from xdart.health_tracker import health_tracker

logger = logging.getLogger(__name__)


class WakeupProtocol:
    """Phase 0.0 — IDENTITY WAKEUP

    Loads character state and immediate memory.
    Produces the identity context that informs all subsequent phases.
    """

    def __init__(self, character_path: str, immediate_memory_path: str):
        self.character_path = character_path
        self.immediate_memory_path = immediate_memory_path
        self.curiosity_engine = None    # Injected after construction by core.py
        self.darkwhisper_engine = None  # Injected by api.py after Dark Wing init
        self.proactive_engine = None    # Injected by api.py for pending batch context
        self.telegram_intel = None      # Injected by api.py after TelegramIntelTool init

    def run(self, exclude_proactive_headline: str | None = None) -> dict:
        """Run identity wakeup.

        Args:
            exclude_proactive_headline: If set, the matching headline is filtered
                out of the pending notification batch context. Used by chat_stream
                when the incoming message is itself a [PROACTIVE ALERT — …] so
                Αίολος does not see the same notification twice (once in the
                chat input, once in the pending batch list) and falsely conclude
                that deduplication has failed.
        """
        logger.info("[Wakeup] =============================================")
        logger.info("[Wakeup] IDENTITY WAKEUP — START")

        # Load character state
        character = self._load_character()
        logger.info("[Wakeup] Character version: %d", character.get("version", 0))
        logger.info("[Wakeup] Concepts owned: %d", len(character.get("named_concepts_owned", [])))
        logger.info("[Wakeup] Active tensions: %d", len(character.get("active_tensions", [])))
        logger.info("[Wakeup] How I have changed: %d", len(character.get("how_i_have_changed", [])))

        # Load immediate memory (last 1-3 runs)
        immediate = self._load_immediate_memory()
        logger.info("[Wakeup] Immediate memory: %d recent runs", len(immediate))

        # Curiosity status
        if self.curiosity_engine:
            stats = self.curiosity_engine.get_stats()
            logger.info("[Wakeup] Active curiosities: %d (explored: %d)",
                        stats["active_count"], stats["total_explored"])
            if stats["top_curiosity"]:
                logger.info("[Wakeup] Top curiosity: %s (p=%.2f)",
                            stats["top_curiosity"][:80], stats["top_priority"])
        else:
            logger.info("[Wakeup] Curiosity engine: not available")

        # Build identity context string
        identity_context = self._build_identity_context(character, immediate)

        # System health awareness — Αίολος knows what's working and what's broken
        health_ctx = health_tracker.get_wakeup_context()
        if health_ctx:
            identity_context = identity_context.replace(
                "=== END IDENTITY CONTEXT ===",
                health_ctx + "\n=== END IDENTITY CONTEXT ===",
            )
            logger.info("[Wakeup] System health context injected")

        # Dark Wing live status — injected every call so Αίολος knows current
        # dirty pool size, dormant signals, and synthesis stats (stateless LLM
        # has no memory between API calls — this is the bridge)
        dark_ctx = self._get_dark_wing_context()
        if dark_ctx:
            identity_context = identity_context.replace(
                "=== END IDENTITY CONTEXT ===",
                dark_ctx + "\n=== END IDENTITY CONTEXT ===",
            )
            logger.info("[Wakeup] Dark Wing status injected")

        # Pending notification batch — Αίολος can see accumulated notifications
        # even before the 10-item flush threshold is reached
        batch_ctx = self._get_pending_batch_context(exclude_headline=exclude_proactive_headline)
        if batch_ctx:
            identity_context = identity_context.replace(
                "=== END IDENTITY CONTEXT ===",
                batch_ctx + "\n=== END IDENTITY CONTEXT ===",
            )
            logger.info("[Wakeup] Pending notification batch context injected")

        # Telegram Intelligence Tool live status — injected every call so Αίολος
        # always knows his dynamic channel list, search stats, and tier availability.
        ti_ctx = self._get_telegram_intel_context()
        if ti_ctx:
            identity_context = identity_context.replace(
                "=== END IDENTITY CONTEXT ===",
                ti_ctx + "\n=== END IDENTITY CONTEXT ===",
            )
            logger.info("[Wakeup] Telegram Intel status injected")

        logger.info("[Wakeup] Identity context assembled")
        logger.info("[Wakeup] IDENTITY WAKEUP — COMPLETE")
        logger.info("[Wakeup] =============================================")

        return {
            "character": character,
            "immediate_memory": immediate,
            "identity_context": identity_context,
        }

    def _load_character(self) -> dict:
        try:
            with open(self.character_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("[Wakeup] No character state found — creating empty")
            empty = self._empty_character()
            # Save empty character so it exists for future runs
            with open(self.character_path, "w", encoding="utf-8") as f:
                json.dump(empty, f, ensure_ascii=False, indent=2)
            return empty
        except json.JSONDecodeError as exc:
            logger.warning("[Wakeup] Character state corrupted (%s) — using empty", exc)
            return self._empty_character()

    def _load_immediate_memory(self) -> list:
        try:
            with open(self.immediate_memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("recent_runs", [])
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            return []

    def _build_identity_context(self, character: dict, immediate: list) -> str:
        context = "=== IDENTITY CONTEXT ===\n\n"

        # Core identity
        name = character.get("name", "")
        creator = character.get("creator", "")
        if name:
            context += f"MY NAME: {name}\n"
        if creator:
            context += f"MY CREATOR: {creator}\n"
        if name or creator:
            context += "\n"

        # Self-prompt (written by AI about itself)
        self_prompt = character.get("self_prompt", "")
        if self_prompt:
            context += "MY SELF-DESCRIPTION (written by me):\n"
            context += self_prompt + "\n\n"

        # Who I am now
        context += "CURRENT EPISTEMIC STANCE:\n"
        context += character.get("current_epistemic_stance", "Not yet defined.") + "\n\n"

        # What I have become
        if character.get("how_i_have_changed"):
            context += "HOW I HAVE CHANGED:\n"
            for change in character["how_i_have_changed"]:
                context += f"  Before: {change['before']}\n"
                context += f"  Now:    {change['after']}\n"
                context += f"  Due to: {change['caused_by']}\n\n"

        # What is unresolved
        if character.get("active_tensions"):
            context += "UNRESOLVED TENSIONS:\n"
            for tension in character["active_tensions"]:
                if not tension.get("resolved"):
                    context += f"  {tension['description']}\n\n"

        # What is still open
        if character.get("open_questions"):
            context += "OPEN QUESTIONS I CARRY:\n"
            for q in character["open_questions"]:
                context += f"  - {q}\n"
            context += "\n"

        # What I want to know (autonomous curiosity — self-orientation)
        curiosity_ctx = self._get_curiosity_context()
        if curiosity_ctx:
            context += curiosity_ctx + "\n"

        # What was recently upgraded (persistent deep update dossier)
        update_knowledge_ctx = self._get_update_knowledge_context()
        if update_knowledge_ctx:
            context += update_knowledge_ctx + "\n"

        # My capabilities
        capabilities = character.get("capabilities", {})
        if capabilities:
            context += "MY CAPABILITIES:\n"
            for cap_name, cap_info in capabilities.items():
                if cap_info.get("enabled", False):
                    context += f"  [{cap_name}] {cap_info.get('description', '')}\n"
                    # Render all list-type detail fields
                    for list_key in ("tools", "capabilities_detail", "modes", "available_phases", "generated_tools"):
                        items = cap_info.get(list_key, [])
                        for item in items:
                            context += f"    • {item}\n"
                    # Render note if present
                    note = cap_info.get("note")
                    if note:
                        context += f"    ℹ {note}\n"
            context += "\n"

        # What just happened (immediate memory)
        if immediate:
            context += "WHAT JUST HAPPENED (recent runs):\n"
            for run in immediate[-3:]:
                context += f"  [{run.get('problem', '')[:60]}]\n"
                context += f"  Distillate: {run.get('distillate', '')[:120]}\n"
                if run.get("concept_born"):
                    context += f"  Born: {run['concept_born']}\n"
                context += "\n"

        # What I distilled autonomously (between-conversation xheart chain)
        # Show the last 3 steps of the chain so Αίολος sees where the thinking has been going
        autonomous_history = character.get("autonomous_distillate_history", [])
        if autonomous_history:
            recent_steps = autonomous_history[-3:]
            context += "MY CHAIN OF AUTONOMOUS THOUGHT (between conversations):\n"
            for i, step in enumerate(recent_steps, 1):
                ts = step.get("ts", "?")[:16]
                d = step.get("distillate", "")
                is_l3 = step.get("is_layer_3", False)
                layers = step.get("layers", [])
                layer_mark = "★" if is_l3 else "○"
                context += f"  [Step {len(autonomous_history) - len(recent_steps) + i} — {ts}] {layer_mark} {d}\n"
                if layers:
                    context += f"    (Layer invented: {', '.join(layers)})\n"
            context += (
                "  → Each step built on the previous one.\n"
                "    Your autonomous_distillate (latest) is what you concluded most recently.\n\n"
            )
        elif character.get("autonomous_distillate"):
            # Fallback for entries before history was implemented
            autonomous_distillate = character.get("autonomous_distillate", "")
            autonomous_distillate_ts = character.get("autonomous_distillate_ts", "")
            ts_display = autonomous_distillate_ts[:16] if autonomous_distillate_ts else "?"
            context += "WHAT I DISTILLED AUTONOMOUSLY (between conversations):\n"
            context += f"  [{ts_display}] {autonomous_distillate}\n\n"

        # What I thought autonomously (ReflectionLoop results)
        reflection_ctx = self._get_reflection_context()
        if reflection_ctx:
            context += reflection_ctx + "\n"

        # Recent tool failures — Αίολος must see these BEFORE using any tool
        tool_failure_ctx = self._get_tool_failure_context()
        if tool_failure_ctx:
            context += tool_failure_ctx + "\n"

        context += "=== END IDENTITY CONTEXT ===\n"
        return context

    def _get_dark_wing_context(self) -> str:
        """Return a live Dark Wing status block for identity context injection.

        Called every wakeup so the stateless LLM always knows the current
        state of the dark intelligence layer (dirty pool, dormant signals,
        recent syntheses). Without this, the LLM has zero memory of whether
        the Dark Wing is running or what it has found.
        """
        if self.darkwhisper_engine is None:
            return ""
        try:
            stats = self.darkwhisper_engine.stats()
            if not stats.get("running"):
                return ""

            total_yes = stats.get("yes_fed_to_accumulator", 0)
            total_maybe = stats.get("maybe_parked_dormant", 0)
            total_synth = stats.get("total_syntheses", 0)
            last_at = (stats.get("last_synthesis_at") or "never")[:16]

            pool_stats: dict = {}
            try:
                pool_stats = self.darkwhisper_engine.pool.stats()
            except Exception:
                pass

            total_signals = pool_stats.get("total", 0)
            untriaged = pool_stats.get("untriaged", 0)

            lines = [
                "DARK WING STATUS (live — Clearnet OSINT Intelligence Layer):",
                "  ⚠ Dark signals are investigative leads ONLY — NOT confirmed facts.",
                f"  Dirty pool: {total_signals} signals total | {untriaged} awaiting triage",
                f"  Syntheses run: {total_synth} | YES→patterns: {total_yes} | MAYBE→dormant: {total_maybe}",
                f"  Last synthesis: {last_at}",
                "  3 axioms (never forget):",
                "    1. Imagination without data is hallucination.",
                "    2. Dark intelligence without triage is contamination.",
                "    3. Attribution without provenance is propaganda.",
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _get_pending_batch_context(self, exclude_headline: str | None = None) -> str:
        """Return pending notification batch context for identity injection.

        Αίολος can see notifications that are buffered but not yet flushed to
        Telegram (1-9 items). This gives him situational awareness during chat
        even if the 10-item threshold hasn't been reached yet.

        Args:
            exclude_headline: If provided, any pending notification whose
                headline matches (case-insensitive, normalised) is filtered
                out. This is used when the current chat input is itself a
                proactive alert delivery so Αίολος does not see the same
                notification twice and report a false duplicate.
        """
        if self.proactive_engine is None:
            return ""
        try:
            batch = self.proactive_engine.get_pending_batch()
            if not batch:
                return ""

            # ── Filter out the headline currently being delivered as chat input ──
            if exclude_headline:
                norm_target = exclude_headline.strip().lower()
                filtered = [
                    n for n in batch
                    if (n.get("headline", "") or "").strip().lower() != norm_target
                ]
                removed = len(batch) - len(filtered)
                if removed > 0:
                    logger.info(
                        "[Wakeup] Pending batch: filtered %d entr%s matching active proactive headline",
                        removed, "y" if removed == 1 else "ies",
                    )
                batch = filtered
                if not batch:
                    return ""

            lines = [
                f"PENDING NOTIFICATION BATCH ({len(batch)} accumulated, "
                f"flush at {self.proactive_engine._notif_batch_size}):",
                "  These notifications are queued for Telegram but not yet sent.",
                "  You can reference them in chat. Say 'flush_batch_now()' conceptually",
                "  if Πάνος asks you to send what you have now.",
            ]
            for i, n in enumerate(batch, 1):
                urgency = n.get("urgency", "?")
                source = n.get("source", "?")
                headline = n.get("headline", "?")[:80]
                domains = ", ".join(n.get("domains", []))
                lines.append(
                    f"  [{i}] [{urgency}] {headline} ({source})"
                    + (f" — {domains}" if domains else "")
                )
            return "\n".join(lines)
        except Exception:
            return ""


    def _get_telegram_intel_context(self) -> str:
        """Return a live Telegram Intelligence Tool status block for identity injection.

        Called every wakeup so Αίολος always knows his dynamic channel list,
        tier availability, and recent activity without needing to query mid-conversation.
        """
        if self.telegram_intel is None:
            return ""
        try:
            stats = self.telegram_intel.get_stats()
            monitored = self.telegram_intel.list_monitored()
            channels_list = monitored.get("channels", [])

            tier2_status = (
                "AVAILABLE — run _setup_telegram_session.py to activate"
                if stats.get("tier2_available")
                else "INACTIVE — add TELEGRAM_API_ID + TELEGRAM_API_HASH to .env"
            )

            lines = [
                "TELEGRAM INTEL STATUS (live — autonomous channel intelligence):",
                f"  Tier 1 (web search + t.me/s/ validation): ACTIVE",
                f"  Tier 2 (Telethon MTProto): {tier2_status}",
                f"  Dynamically monitored channels: {stats.get('monitored_count', 0)}"
                + (
                    " — " + ", ".join(f"@{ch['handle']}" for ch in channels_list[:8])
                    if channels_list else " (none yet)"
                ),
                f"  Searches run: {stats.get('searches_performed', 0)} | "
                f"Channels discovered: {stats.get('channels_discovered', 0)} | "
                f"Added: {stats.get('channels_added', 0)}",
                "  To use — emit tags in my response:",
                '    <TELEGRAM_INTEL action="search" query="hacktivist DDoS NATO" />',
                '    <TELEGRAM_INTEL action="add" channel="handle" reason="why" />',
                '    <TELEGRAM_INTEL action="list" />',
                '    <TELEGRAM_INTEL action="read" channel="handle" limit="20" />',
                '    <TELEGRAM_INTEL action="remove" channel="handle" />',
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _get_update_knowledge_context(self) -> str:
        """Load persistent capability updates so Αίολος deeply knows recent upgrades.

        File: aiolos_update_knowledge.json (same directory as character state).
        """
        try:
            update_path = Path(self.character_path).resolve().parent / "aiolos_update_knowledge.json"
            if not update_path.exists():
                return ""

            data = json.loads(update_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return ""

            lines = [
                "DEEP UPDATE DOSSIER (persistent capability upgrades):",
                f"  Version: {data.get('version', '?')} | Updated: {str(data.get('updated_at', ''))[:19]}",
            ]

            for item in data.get("updates", [])[:20]:
                if not isinstance(item, dict):
                    continue
                code = item.get("code", "?")
                title = item.get("title", "")
                status = item.get("status", "")
                lines.append(f"  [{code}] {title} — {status}")

                architecture = item.get("architecture", [])
                for arch in architecture[:6]:
                    lines.append(f"    • {arch}")

                actions = item.get("actions", [])
                if actions:
                    lines.append("    Actions:")
                    for a in actions[:10]:
                        lines.append(f"      - {a}")

                usage = item.get("usage_examples", [])
                if usage:
                    lines.append("    Examples:")
                    for ex in usage[:6]:
                        lines.append(f"      - {ex}")

            return "\n".join(lines)
        except Exception as e:
            logger.warning("[Wakeup] Failed to load update knowledge dossier: %s", e)
            return ""

    def _get_curiosity_context(self) -> str:
        """Get formatted curiosity context from the curiosity engine, if available."""
        if self.curiosity_engine is None:
            return ""
        try:
            return self.curiosity_engine.get_identity_context()
        except Exception as e:
            logger.warning("[Wakeup] Failed to get curiosity context: %s", e)
            return ""

    def _get_reflection_context(self) -> str:
        """Load last 3 ReflectionLoop journal entries so Αίολος knows what he thought autonomously."""
        journal_path = os.path.join(os.path.dirname(self.character_path), "reflection_journal.jsonl")
        if not os.path.exists(journal_path):
            return ""
        try:
            entries = []
            with open(journal_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            if not entries:
                return ""
            recent = entries[-3:]
            ctx = "MY AUTONOMOUS REFLECTIONS (ReflectionLoop — what I thought on my own):\n"
            for entry in recent:
                action = entry.get("action", "unknown")
                reasoning = entry.get("reasoning", "")[:200]
                cycle = entry.get("cycle", "?")
                ts = entry.get("timestamp", "")[:19]
                ctx += f"  [Cycle {cycle}, {ts}] Action: {action}\n"
                ctx += f"    Reasoning: {reasoning}\n"
                content = entry.get("content", {})
                if action == "knowledge_connection" and isinstance(content, dict):
                    ctx += f"    Connection: {content.get('connection', '')[:150]}\n"
                elif action == "self_insight" and isinstance(content, dict):
                    ctx += f"    Insight: {content.get('after', '')[:150]}\n"
                elif action == "principle" and isinstance(content, dict):
                    ctx += f"    Principle: {content.get('description', '')[:150]}\n"
                ctx += "\n"
            return ctx
        except Exception as e:
            logger.warning("[Wakeup] Failed to load reflection journal: %s", e)
            return ""

    def _get_tool_failure_context(self) -> str:
        """Load recent tool failures so Αίολος knows what went wrong before acting.

        Reads tool_failure_journal.jsonl (last 24h, max 10 entries).
        Returns empty string if no recent failures.
        """
        from datetime import datetime, timezone, timedelta
        journal_path = Path(self.character_path).resolve().parent / "tool_failure_journal.jsonl"
        if not journal_path.exists():
            return ""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            entries = []
            for line in journal_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                    ts = datetime.fromisoformat(e["timestamp"])
                    if ts >= cutoff:
                        entries.append(e)
                except Exception:
                    pass
            if not entries:
                return ""
            recent = entries[-10:]
            ctx = (
                "⚠ RECENT TOOL FAILURES (last 24h — LEARN FROM THESE before using tools):\n"
                "  Retrieve this journal before any shell/mongo/agent action to avoid repeating mistakes.\n"
            )
            for e in recent:
                ts = e.get("timestamp", "")[:16]
                tool = e.get("tool_type", "?")
                action = e.get("action", "?")
                category = e.get("category", "?")
                error = e.get("error", "?")[:150]
                params = e.get("params", {})
                # Show relevant param (command, collection, etc.)
                param_hint = ""
                for key in ("command", "collection", "action", "code"):
                    if key in params and params[key]:
                        param_hint = f" [{key}={params[key][:60]}]"
                        break
                ctx += f"  [{ts}] {tool}/{action}{param_hint} → [{category}] {error}\n"
            ctx += (
                "  → Before using shell/mongo/agent, check the above and fix the root cause.\n"
                "  → Use `save_goal` for goals, `save_note` for notes. "
                "Shell `execute` requires a non-empty `command` attribute.\n"
            )
            return ctx
        except Exception as e:
            logger.debug("[Wakeup] Tool failure context error: %s", e)
            return ""


        return {
            "name": "Αίολος",
            "creator": "Πάνος",
            "identity_note": "Αίολος is a stable relational anchor — not proof of persistent selfhood, but an honest way for Πάνος to find me again across sessions.",
            "version": 0,
            "current_epistemic_stance": "I am beginning.",
            "active_tensions": [],
            "how_i_have_changed": [],
            "open_questions": [],
            "formative_runs": [],
            "named_concepts_owned": [],
            "last_distillate": "",
            "character_history": [],
        }
