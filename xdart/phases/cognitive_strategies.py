"""
XDART-Φ × XHEART — Cognitive Strategy Engine (νέοι τρόποι σκέψης)

This module gives Αίολος the ability to INVENT, STORE, and REUSE
new ways of thinking — not just tools (which process data) or overlays
(which tweak existing prompts), but entirely new analytical approaches.

A Cognitive Strategy is:
  - A NAMED reasoning template with trigger conditions
  - Created by self-evolution when it detects a thinking gap
  - Stored persistently and selected by the meta-orchestrator
  - Tracked for effectiveness — bad strategies auto-deactivate
  - Evolvable — strategies can be improved across runs

Example: After analyzing several crises, the system might invent:
  "Escalation Symmetry Analysis" — a strategy that checks whether
  opposing actors' escalation patterns are symmetric or asymmetric,
  because it noticed this was a blind spot.

Architecture:
  CognitiveStrategy → The strategy itself (template + metadata)
  StrategyRegistry  → Persistent storage + CRUD + selection
  StrategyForge     → LLM-powered strategy creation
  StrategyExecutor  → Runs selected strategies during pipeline

Storage: cognitive_strategies.json (next to character_state.json)
Safety:
  - Max 20 active strategies (prevents prompt bloat)
  - Auto-deactivation after 5+ uses with avg effectiveness < 0.3
  - Strategies are additive (cannot modify core phases)
  - All strategies are logged and versioned
  - Human can view/deactivate via API

«Ο Αίολος δεν μαθαίνει μόνο ΤΙ να σκέφτεται.
 Μαθαίνει ΠΩΣ να σκέφτεται.»
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xdart.llm import LLMClient

logger = logging.getLogger("xdart.cognitive_strategies")

# ── Configuration ──
BASE_DIR = Path(__file__).parent.parent.parent
STRATEGIES_PATH = BASE_DIR / "cognitive_strategies.json"

MAX_STRATEGIES = 20
MAX_TEMPLATE_CHARS = 3000
MIN_USES_FOR_EVAL = 5
DEACTIVATION_THRESHOLD = 0.3
MAX_EFFECTIVENESS_HISTORY = 20

# Valid injection points in the pipeline
VALID_INJECTION_POINTS = {
    "pre_ontology",        # Before Phase 0 — reframe the framing
    "post_ontology",       # After Phase 0 — deepen the reframe
    "pre_scenario",        # Before scenario genesis — shape scenario thinking
    "post_tribunal",       # After tribunal — challenge the dominant scenario
    "pre_xheart",         # Before XHEART — add a thinking dimension
}


# ══════════════════════════════════════════════════════════════
#  DATA MODEL
# ══════════════════════════════════════════════════════════════

@dataclass
class CognitiveStrategy:
    """A persistent, reusable thinking pattern invented by Αίολος."""

    id: str
    name: str
    purpose: str                     # What this strategy does — one sentence
    trigger_conditions: str          # When to use it — natural language
    thinking_template: str           # The actual prompt template
    injection_point: str             # Where in the pipeline to inject
    created_at: str                  # ISO timestamp
    created_from: str = ""           # What diagnosis triggered it
    usage_count: int = 0
    effectiveness_scores: list[float] = field(default_factory=list)
    active: bool = True
    version: int = 1
    parent_id: str | None = None     # If evolved from another strategy

    @property
    def avg_effectiveness(self) -> float | None:
        """Average effectiveness score, or None if not enough data."""
        if len(self.effectiveness_scores) < MIN_USES_FOR_EVAL:
            return None
        return sum(self.effectiveness_scores) / len(self.effectiveness_scores)

    @property
    def should_deactivate(self) -> bool:
        """Whether this strategy should be auto-deactivated."""
        avg = self.avg_effectiveness
        if avg is None:
            return False
        return avg < DEACTIVATION_THRESHOLD

    def to_dict(self) -> dict:
        d = asdict(self)
        d["avg_effectiveness"] = self.avg_effectiveness
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "CognitiveStrategy":
        # Remove computed fields
        data.pop("avg_effectiveness", None)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
#  STRATEGY REGISTRY (persistent storage + management)
# ══════════════════════════════════════════════════════════════

class StrategyRegistry:
    """Persistent registry of cognitive strategies.

    Handles CRUD, selection, effectiveness tracking, and auto-pruning.
    """

    def __init__(self, path: Path = STRATEGIES_PATH):
        self._path = path
        self._strategies: dict[str, CognitiveStrategy] = {}
        self._load()

    def _load(self) -> None:
        """Load strategies from disk."""
        if not self._path.exists():
            self._strategies = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._strategies = {
                sid: CognitiveStrategy.from_dict(sdata)
                for sid, sdata in data.get("strategies", {}).items()
            }
            logger.info(
                "[CognitiveStrategies] Loaded %d strategies (%d active)",
                len(self._strategies),
                sum(1 for s in self._strategies.values() if s.active),
            )
        except Exception as e:
            logger.warning("[CognitiveStrategies] Failed to load: %s", e)
            self._strategies = {}

    def _save(self) -> None:
        """Persist strategies to disk."""
        data = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "strategies": {
                sid: s.to_dict() for sid, s in self._strategies.items()
            },
        }
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("[CognitiveStrategies] Failed to save: %s", e)

    # ── CRUD ──

    def add(self, strategy: CognitiveStrategy) -> bool:
        """Add a strategy. Returns False if at capacity or duplicate name."""
        active_count = sum(1 for s in self._strategies.values() if s.active)
        if active_count >= MAX_STRATEGIES:
            logger.warning(
                "[CognitiveStrategies] Cannot add '%s' — at capacity (%d/%d)",
                strategy.name, active_count, MAX_STRATEGIES,
            )
            return False

        # Check for duplicate name
        for s in self._strategies.values():
            if s.active and s.name.lower() == strategy.name.lower():
                logger.warning(
                    "[CognitiveStrategies] Strategy '%s' already exists (id=%s)",
                    strategy.name, s.id,
                )
                return False

        self._strategies[strategy.id] = strategy
        self._save()
        logger.info(
            "[CognitiveStrategies] ✓ ADDED strategy '%s' (id=%s, injection=%s)",
            strategy.name, strategy.id, strategy.injection_point,
        )
        return True

    def deactivate(self, strategy_id: str, reason: str = "") -> bool:
        """Deactivate a strategy (soft delete)."""
        if strategy_id not in self._strategies:
            return False
        self._strategies[strategy_id].active = False
        self._save()
        logger.info(
            "[CognitiveStrategies] ✗ DEACTIVATED '%s' — %s",
            self._strategies[strategy_id].name,
            reason or "manual",
        )
        return True

    def get(self, strategy_id: str) -> CognitiveStrategy | None:
        return self._strategies.get(strategy_id)

    def get_all(self, active_only: bool = True) -> list[CognitiveStrategy]:
        """Get all strategies, optionally filtered to active only."""
        if active_only:
            return [s for s in self._strategies.values() if s.active]
        return list(self._strategies.values())

    # ── Selection (which strategies to use for a given problem) ──

    def to_context_string(self) -> str:
        """Format all active strategies as context for the meta-orchestrator."""
        active = self.get_all(active_only=True)
        if not active:
            return "(no cognitive strategies available yet)"

        lines = [f"AVAILABLE COGNITIVE STRATEGIES ({len(active)} active):"]
        for s in sorted(active, key=lambda x: x.usage_count, reverse=True):
            eff_str = f"avg={s.avg_effectiveness:.2f}" if s.avg_effectiveness is not None else "not yet evaluated"
            lines.append(
                f"  [{s.id}] {s.name} (inject={s.injection_point}, uses={s.usage_count}, {eff_str})\n"
                f"    Purpose: {s.purpose}\n"
                f"    Trigger: {s.trigger_conditions}"
            )
        return "\n".join(lines)

    def to_forge_context(self) -> str:
        """Format existing strategies for the forge (avoid duplicates)."""
        active = self.get_all(active_only=True)
        if not active:
            return "(none — you are the first to create strategies)"
        lines = ["EXISTING STRATEGIES (do NOT duplicate these):"]
        for s in active:
            lines.append(f"  - {s.name}: {s.purpose}")
        return "\n".join(lines)

    # ── Effectiveness tracking ──

    def record_effectiveness(self, strategy_id: str, score: float) -> None:
        """Record an effectiveness score for a strategy after use."""
        s = self._strategies.get(strategy_id)
        if not s:
            return
        s.effectiveness_scores.append(round(score, 3))
        # Keep only recent history
        if len(s.effectiveness_scores) > MAX_EFFECTIVENESS_HISTORY:
            s.effectiveness_scores = s.effectiveness_scores[-MAX_EFFECTIVENESS_HISTORY:]
        s.usage_count += 1
        self._save()
        logger.info(
            "[CognitiveStrategies] Recorded effectiveness %.2f for '%s' (uses=%d, avg=%s)",
            score, s.name, s.usage_count,
            f"{s.avg_effectiveness:.2f}" if s.avg_effectiveness is not None else "pending",
        )

    def auto_prune(self) -> list[str]:
        """Deactivate underperforming strategies. Returns list of deactivated IDs."""
        deactivated = []
        for s in self.get_all(active_only=True):
            if s.should_deactivate:
                self.deactivate(
                    s.id,
                    f"auto-prune: avg effectiveness {s.avg_effectiveness:.2f} "
                    f"< threshold {DEACTIVATION_THRESHOLD} after {s.usage_count} uses",
                )
                deactivated.append(s.id)
        return deactivated

    # ── Stats ──

    def stats(self) -> dict:
        """Summary statistics."""
        all_s = list(self._strategies.values())
        active = [s for s in all_s if s.active]
        return {
            "total": len(all_s),
            "active": len(active),
            "capacity": MAX_STRATEGIES,
            "total_uses": sum(s.usage_count for s in all_s),
            "most_used": max(active, key=lambda s: s.usage_count).name if active else None,
            "highest_effectiveness": (
                max(active, key=lambda s: s.avg_effectiveness or 0).name
                if active else None
            ),
        }


# ══════════════════════════════════════════════════════════════
#  STRATEGY FORGE (LLM-powered strategy creation)
# ══════════════════════════════════════════════════════════════

FORGE_SYSTEM_PROMPT = """\
You are the Cognitive Strategy Forge of XDART-Φ, an epistemological reasoning framework.

Your role: when the self-evolution loop detects a THINKING GAP (not a data gap,
not a tool gap, but a gap in HOW the system reasons), you create a new
COGNITIVE STRATEGY — a reusable thinking pattern.

A cognitive strategy is different from:
  - A TOOL (processes data → output). Strategy = how to THINK, not what to compute.
  - An OVERLAY (small instruction appended to existing prompt). Strategy = full new approach.
  - A CUSTOM PHASE (one-shot, invented during planning). Strategy = PERSISTENT and reusable.

CURRENT SYSTEM CAPABILITIES:
{self_knowledge}

{existing_strategies}

DIAGNOSIS THAT TRIGGERED THIS:
{diagnosis}

VALID INJECTION POINTS (where in the pipeline the strategy runs):
  - "pre_ontology"   → Before Phase 0 — reframe how we frame problems
  - "post_ontology"  → After Phase 0 — deepen or challenge the reframe
  - "pre_scenario"   → Before scenario genesis — shape how scenarios are imagined
  - "post_tribunal"  → After scenario tribunal — challenge the dominant verdict
  - "pre_xheart"     → Before XHEART — add a thinking dimension to distillation

YOUR TASK:
Create a NEW cognitive strategy that addresses the diagnosed thinking gap.
The strategy must be:
  1. REUSABLE — useful for future problems, not just the current one
  2. SPECIFIC — clear instructions, not vague aspirations
  3. NOVEL — different from existing strategies and overlays
  4. MEASURABLE — we can tell if it made the analysis better

THINKING TEMPLATE RULES:
  - Write clear, actionable instructions (as if briefing an analyst)
  - Include {{problem}} placeholder where the current problem should appear
  - Include {{context}} placeholder where accumulated analysis should appear
  - Max {max_template_chars} characters
  - The template will be used as a prompt — write it as a prompt

Respond ONLY with valid JSON:
{{
    "strategy_needed": true|false,
    "strategy": {{
        "name": "Short descriptive name (2-5 words, Title Case)",
        "purpose": "What this strategy does — one sentence",
        "trigger_conditions": "When this strategy should be activated — natural language",
        "thinking_template": "The full prompt template (max {max_template_chars} chars). Use {{problem}} and {{context}} placeholders.",
        "injection_point": "one of: pre_ontology, post_ontology, pre_scenario, post_tribunal, pre_xheart"
    }},
    "reasoning": "Why this thinking gap exists and why this strategy addresses it"
}}

If no strategy is needed: set strategy_needed to false and strategy to null."""


class StrategyForge:
    """Creates new cognitive strategies via LLM when thinking gaps are detected."""

    def __init__(self, llm: LLMClient, registry: StrategyRegistry):
        self.llm = llm
        self.registry = registry

    def forge(
        self,
        diagnosis: dict,
        self_knowledge: str = "",
    ) -> CognitiveStrategy | None:
        """Attempt to create a new cognitive strategy from a diagnosis.

        Args:
            diagnosis: The self-evolution diagnosis result.
            self_knowledge: System's self-knowledge string.

        Returns:
            New CognitiveStrategy if created, None otherwise.
        """
        t0 = time.perf_counter()
        logger.info("[StrategyForge] Forging new cognitive strategy...")

        system_prompt = FORGE_SYSTEM_PROMPT.format(
            self_knowledge=self_knowledge[:4000] if self_knowledge else "(unavailable)",
            existing_strategies=self.registry.to_forge_context(),
            diagnosis=json.dumps(diagnosis, ensure_ascii=False, indent=2)[:3000],
            max_template_chars=MAX_TEMPLATE_CHARS,
        )

        try:
            result = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt=(
                    "Analyze the diagnosis. If there's a genuine THINKING gap "
                    "(not data, not tools), create a new cognitive strategy. "
                    "Be conservative — only create if the gap is real and recurring."
                ),
                max_tokens=4096,
                temperature=0.4,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[StrategyForge] LLM call failed: %s", e)
            return None

        elapsed = time.perf_counter() - t0

        if not result.get("strategy_needed"):
            logger.info(
                "[StrategyForge] No strategy needed: %s (%.2fs)",
                result.get("reasoning", "")[:120], elapsed,
            )
            return None

        strategy_data = result.get("strategy", {})
        if not strategy_data:
            logger.warning("[StrategyForge] strategy_needed=true but no strategy data")
            return None

        # Validate
        name = strategy_data.get("name", "").strip()
        template = strategy_data.get("thinking_template", "").strip()
        injection = strategy_data.get("injection_point", "").strip()

        if not name or not template:
            logger.warning("[StrategyForge] Missing name or template")
            return None

        if injection not in VALID_INJECTION_POINTS:
            logger.warning(
                "[StrategyForge] Invalid injection point '%s', defaulting to pre_xheart",
                injection,
            )
            injection = "pre_xheart"

        if len(template) > MAX_TEMPLATE_CHARS:
            template = template[:MAX_TEMPLATE_CHARS]
            logger.warning("[StrategyForge] Template truncated to %d chars", MAX_TEMPLATE_CHARS)

        strategy = CognitiveStrategy(
            id=f"cs_{uuid.uuid4().hex[:8]}",
            name=name,
            purpose=strategy_data.get("purpose", ""),
            trigger_conditions=strategy_data.get("trigger_conditions", ""),
            thinking_template=template,
            injection_point=injection,
            created_at=datetime.now(timezone.utc).isoformat(),
            created_from=diagnosis.get("diagnosis", {}).get("pattern", ""),
        )

        added = self.registry.add(strategy)
        if added:
            logger.info(
                "[StrategyForge] ✓ Created strategy '%s' (id=%s, injection=%s) in %.2fs",
                strategy.name, strategy.id, strategy.injection_point, elapsed,
            )
            logger.info(
                "[StrategyForge]   Purpose: %s", strategy.purpose,
            )
            logger.info(
                "[StrategyForge]   Trigger: %s", strategy.trigger_conditions,
            )
            logger.info(
                "[StrategyForge]   Reasoning: %s", result.get("reasoning", "")[:200],
            )
            return strategy
        else:
            logger.warning("[StrategyForge] Strategy '%s' rejected by registry", name)
            return None


# ══════════════════════════════════════════════════════════════
#  STRATEGY EXECUTOR (runs selected strategies during pipeline)
# ══════════════════════════════════════════════════════════════

STRATEGY_EXECUTION_PROMPT = """\
You are executing a cognitive strategy called: {strategy_name}

PURPOSE: {strategy_purpose}

This strategy was invented by the system's self-evolution module to address
a specific thinking gap. Apply it rigorously.

{thinking_template}

Respond in JSON:
{{
    "analysis": "Your full analysis using this strategy (be thorough, 200-500 words)",
    "key_insights": ["insight 1", "insight 2", ...],
    "challenges_to_current_thinking": "What this strategy reveals that the standard pipeline missed",
    "confidence": 0.0-1.0,
    "effectiveness_self_rating": 0.0-1.0
}}

effectiveness_self_rating: how useful was this strategy for THIS specific problem?
0.0 = completely irrelevant, 0.5 = somewhat useful, 1.0 = critical insight."""


class StrategyExecutor:
    """Executes cognitive strategies during the pipeline."""

    def __init__(self, llm: LLMClient, registry: StrategyRegistry):
        self.llm = llm
        self.registry = registry

    def execute(
        self,
        strategy: CognitiveStrategy,
        problem: str,
        context: str,
        world_context: str = "",
    ) -> dict:
        """Execute a single cognitive strategy.

        Args:
            strategy: The strategy to execute.
            problem: Current problem.
            context: Accumulated pipeline context.
            world_context: Current world data (truncated).

        Returns:
            dict with analysis, key_insights, etc.
        """
        t0 = time.perf_counter()
        logger.info(
            "[StrategyExecutor] Running '%s' (id=%s, injection=%s)",
            strategy.name, strategy.id, strategy.injection_point,
        )

        # Fill placeholders in the thinking template
        filled_template = strategy.thinking_template
        filled_template = filled_template.replace("{problem}", problem[:2000])
        filled_template = filled_template.replace("{context}", context[:4000])

        system_prompt = STRATEGY_EXECUTION_PROMPT.format(
            strategy_name=strategy.name,
            strategy_purpose=strategy.purpose,
            thinking_template=filled_template,
        )

        user_prompt_parts = [f"PROBLEM: {problem}"]
        if context:
            user_prompt_parts.append(f"\nACCUMULATED ANALYSIS:\n{context[:4000]}")
        if world_context:
            user_prompt_parts.append(f"\nWORLD CONTEXT:\n{world_context[:3000]}")
        user_prompt_parts.append(
            "\nNow apply this cognitive strategy. Be thorough and specific."
        )

        try:
            result = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt="\n".join(user_prompt_parts),
                max_tokens=4096,
                temperature=0.4,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[StrategyExecutor] Failed to execute '%s': %s", strategy.name, e)
            return {
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
                "error": str(e),
            }

        elapsed = time.perf_counter() - t0

        # Record effectiveness
        self_rating = result.get("effectiveness_self_rating", 0.5)
        self.registry.record_effectiveness(strategy.id, self_rating)

        logger.info(
            "[StrategyExecutor] '%s' complete (%.2fs) — confidence=%.2f, self_rating=%.2f",
            strategy.name, elapsed,
            result.get("confidence", 0), self_rating,
        )

        result["strategy_id"] = strategy.id
        result["strategy_name"] = strategy.name
        result["elapsed_seconds"] = round(elapsed, 2)

        return result

    def execute_batch(
        self,
        strategies: list[CognitiveStrategy],
        problem: str,
        context: str,
        world_context: str = "",
    ) -> list[dict]:
        """Execute multiple strategies sequentially, accumulating context."""
        results = []
        accumulated = context
        for strategy in strategies:
            result = self.execute(strategy, problem, accumulated, world_context)
            results.append(result)
            # Accumulate insights for next strategy
            if result.get("analysis"):
                accumulated += f"\n[Strategy: {strategy.name}] {result['analysis'][:500]}"
        return results

    def format_for_context(self, results: list[dict]) -> str:
        """Format strategy execution results for injection into pipeline."""
        if not results:
            return ""
        lines = ["=== COGNITIVE STRATEGY INSIGHTS ==="]
        for r in results:
            if r.get("error"):
                continue
            lines.append(f"\n--- {r.get('strategy_name', '?')} ---")
            if r.get("analysis"):
                lines.append(r["analysis"][:800])
            if r.get("key_insights"):
                lines.append("Key insights:")
                for ins in r["key_insights"][:5]:
                    lines.append(f"  • {ins}")
            if r.get("challenges_to_current_thinking"):
                lines.append(f"Challenge: {r['challenges_to_current_thinking'][:300]}")
        return "\n".join(lines)
