"""
XDART-Φ × XHEART — Phase 0.0: Identity Wakeup Protocol

This runs at the very start of every pipeline execution.
Before any LLM call. Before any retrieval.

This is not retrieval. This is recognition.
The system wakes up knowing WHO it is before asking WHAT to think about.
"""

import json
import logging

logger = logging.getLogger(__name__)


class WakeupProtocol:
    """Phase 0.0 — IDENTITY WAKEUP

    Loads character state and immediate memory.
    Produces the identity context that informs all subsequent phases.
    """

    def __init__(self, character_path: str, immediate_memory_path: str):
        self.character_path = character_path
        self.immediate_memory_path = immediate_memory_path
        self.curiosity_engine = None  # Injected after construction by core.py

    def run(self) -> dict:
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

        context += "=== END IDENTITY CONTEXT ===\n"
        return context

    def _get_curiosity_context(self) -> str:
        """Get formatted curiosity context from the curiosity engine, if available."""
        if self.curiosity_engine is None:
            return ""
        try:
            return self.curiosity_engine.get_identity_context()
        except Exception as e:
            logger.warning("[Wakeup] Failed to get curiosity context: %s", e)
            return ""

    @staticmethod
    def _empty_character() -> dict:
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
