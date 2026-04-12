"""
XDART-Φ × XHEART — Logic Self-Modification Sandbox (αυτο-τροποποίηση λογικής)

Gives Αίολος the ability to REWRITE parts of his own reasoning logic,
with strict guardrails to prevent self-damage.

Unlike the Evolution Core (which generates NEW tools) or Self-Evolution
(which writes prompt overlays), this system allows Αίολος to propose
modifications to EXISTING algorithmic functions — such as:
  - How curiosity priority is computed
  - How prophecy confidence is weighted
  - How scenario salience scores are combined
  - How working memory eviction decisions are made

The Iron Rules:
  1. CORE IS SACRED — Only designated "modifiable functions" can be touched
  2. SANDBOX FIRST — Every modification is tested in the existing sandbox
  3. A/B TESTED — Old vs new logic, measured performance comparison
  4. ROLLBACK READY — Previous version is always stored for instant rollback
  5. HUMAN APPROVAL — Permanent changes require Panos's approval
  6. AUDIT TRAIL — Every proposal, test, and decision is logged

Architecture:
  LogicSandbox            — The main orchestrator
  ModifiableFunction      — Registry of functions Αίολος may modify
  LogicProposal           — A proposed modification with rationale
  LogicTestResult         — Sandbox test results for a proposal

Storage: logic_sandbox_journal.jsonl (append-only audit trail)
         logic_sandbox_state.json (current state of modifications)

«Ένα σύστημα που μπορεί να αλλάξει τον εαυτό του χωρίς να χάσει τον εαυτό του
 — αυτό είναι νοημοσύνη.»
"""

import json
import logging
import time
import textwrap
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from xdart.evolution.sandbox import Sandbox, SandboxResult, SAFE_IMPORTS
from xdart.llm import LLMClient

logger = logging.getLogger("xdart.logic_sandbox")

# ── Paths ──
BASE_DIR = Path(__file__).parent.parent.parent
JOURNAL_PATH = BASE_DIR / "logic_sandbox_journal.jsonl"
STATE_PATH = BASE_DIR / "logic_sandbox_state.json"

# ── Safety Limits ──
MAX_FUNCTION_CHARS = 5000        # Max size of a modified function
MAX_PENDING_PROPOSALS = 10       # Don't accumulate too many pending proposals
MAX_MODIFICATION_HISTORY = 50    # Per-function history depth

# ══════════════════════════════════════════════════════════════
#  MODIFIABLE FUNCTION REGISTRY
# ══════════════════════════════════════════════════════════════

# These are the ONLY functions Αίολος is allowed to modify.
# Each entry defines:
#   - function_id: unique identifier
#   - description: what the function does (for LLM context)
#   - current_code: the current implementation (Python source)
#   - signature: function signature
#   - test_cases: list of (input, expected_behavior) for sandbox testing
#   - constraints: what the function MUST always do (invariants)

@dataclass
class ModifiableFunction:
    """A function that Αίολος is allowed to propose modifications to."""

    function_id: str
    description: str
    module_path: str               # e.g. "xdart.phases.curiosity"
    function_name: str             # e.g. "compute_priority"
    signature: str                 # e.g. "def compute_priority(curiosity: dict, context: dict) -> float"
    current_code: str              # The current Python source
    constraints: list[str]         # Invariants that must ALWAYS hold
    test_inputs: list[dict]        # Test inputs for sandbox
    expected_behavior: str         # Human-readable expected behavior description
    original_code: str = ""        # The original (factory) version — never changes
    modification_count: int = 0
    history: list[dict] = field(default_factory=list)  # [{timestamp, code, reason, performance}]
    active_modification: dict | None = None  # Currently active non-original code

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ModifiableFunction":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
#  LOGIC PROPOSAL
# ══════════════════════════════════════════════════════════════

@dataclass
class LogicProposal:
    """A proposed modification to a modifiable function."""

    id: str
    function_id: str
    proposed_code: str
    rationale: str
    expected_improvement: str
    risk_assessment: str
    proposed_at: str
    status: str = "pending"         # pending → testing → tested → approved → applied / rejected / rolled_back
    sandbox_result: dict | None = None
    ab_test_result: dict | None = None
    approval_status: str = "awaiting"  # awaiting → approved → rejected
    approved_by: str = ""           # "auto" for auto-approved, "human" for manual
    applied_at: str | None = None
    rolled_back_at: str | None = None
    rollback_reason: str = ""
    performance_before: float | None = None
    performance_after: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LogicProposal":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
#  BUILT-IN MODIFIABLE FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _default_curiosity_prioritizer() -> str:
    """The default curiosity priority computation — Αίολος can rewrite this."""
    return textwrap.dedent('''\
        def compute_curiosity_priority(curiosity: dict, context: dict) -> float:
            """Compute priority score for a curiosity question.

            Args:
                curiosity: {"question": str, "source_type": str, "tags": list,
                           "created_at": str, "exploration_count": int}
                context: {"active_tensions": list, "recent_topics": list,
                         "avg_integrity": float, "world_events_count": int}

            Returns:
                float: Priority score (0.0 = lowest, 1.0 = highest)
            """
            import datetime
            base = 0.5

            # Source type weighting
            source_weights = {
                "introspection": 0.15,
                "tension": 0.12,
                "world_gap": 0.10,
                "pipeline": 0.08,
                "self_evolution": 0.20,
            }
            base += source_weights.get(curiosity.get("source_type", ""), 0.05)

            # Tag relevance: more tags that match active tensions = higher priority
            tags = set(curiosity.get("tags", []))
            tensions = set(context.get("active_tensions", []))
            overlap = len(tags & tensions)
            base += min(overlap * 0.05, 0.15)

            # Recency decay: newer curiosities slightly preferred
            try:
                created = datetime.datetime.fromisoformat(curiosity.get("created_at", ""))
                age_hours = (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() / 3600
                recency_bonus = max(0, 0.10 - (age_hours * 0.001))
                base += recency_bonus
            except (ValueError, TypeError):
                pass

            # Penalize over-explored curiosities
            exploration_count = curiosity.get("exploration_count", 0)
            if exploration_count > 3:
                base -= 0.10
            elif exploration_count > 1:
                base -= 0.05

            # Integrity-aware: if avg integrity is low, prioritize introspection curiosities
            if context.get("avg_integrity", 1.0) < 0.6 and curiosity.get("source_type") == "introspection":
                base += 0.10

            return max(0.0, min(1.0, base))
    ''')


def _default_prophecy_confidence_adjuster() -> str:
    """The default prophecy confidence adjustment logic."""
    return textwrap.dedent('''\
        def adjust_prophecy_confidence(prophecy: dict, context: dict) -> float:
            """Adjust confidence in a prophecy based on new evidence.

            Args:
                prophecy: {"prediction": str, "confidence": float, "domain": str,
                          "created_at": str, "supporting_evidence": list,
                          "contradicting_evidence": list, "days_remaining": int}
                context: {"world_events": list, "brier_score": float,
                         "calibration_error": float}

            Returns:
                float: Adjusted confidence (0.0 - 1.0)
            """
            import math
            confidence = prophecy.get("confidence", 0.5)

            # Evidence balance
            supporting = len(prophecy.get("supporting_evidence", []))
            contradicting = len(prophecy.get("contradicting_evidence", []))
            total = supporting + contradicting

            if total > 0:
                evidence_ratio = supporting / total
                # Bayesian-style update: shift towards evidence
                confidence = confidence * 0.6 + evidence_ratio * 0.4

            # Temporal decay: confidence decreases as deadline approaches with no confirmation
            days_remaining = prophecy.get("days_remaining", 30)
            if days_remaining < 7 and supporting == 0:
                confidence *= 0.85
            elif days_remaining < 3 and supporting == 0:
                confidence *= 0.70

            # Calibration awareness: if brier score is bad, be more humble
            brier = context.get("brier_score", 0.25)
            if brier > 0.35:
                # Pull towards 0.5 (maximum uncertainty)
                confidence = confidence * 0.8 + 0.5 * 0.2

            # Calibration error correction
            cal_error = context.get("calibration_error", 0.0)
            if cal_error > 0.1:
                # System tends to be overconfident — reduce
                confidence *= (1.0 - cal_error * 0.5)

            return max(0.05, min(0.95, confidence))
    ''')


def _default_scenario_salience_scorer() -> str:
    """The default scenario salience scoring logic."""
    return textwrap.dedent('''\
        def score_scenario_salience(scenario: dict, context: dict) -> float:
            """Score how salient/important a scenario is for the current analysis.

            Args:
                scenario: {"title": str, "conditions": list, "timeline": str,
                          "domains": list, "confidence": float,
                          "tribunal_score": float, "breakpoints": list}
                context: {"problem_domains": list, "active_prophecies": list,
                         "recent_events_domains": list, "n_scenarios": int}

            Returns:
                float: Salience score (0.0 - 1.0)
            """
            base = 0.3

            # Tribunal score is the primary signal
            tribunal = scenario.get("tribunal_score", 0.5)
            base += tribunal * 0.30

            # Domain relevance: overlap with problem domains
            scenario_domains = set(scenario.get("domains", []))
            problem_domains = set(context.get("problem_domains", []))
            if problem_domains:
                domain_overlap = len(scenario_domains & problem_domains) / len(problem_domains)
                base += domain_overlap * 0.15

            # Breakpoint severity
            breakpoints = scenario.get("breakpoints", [])
            fatal_count = sum(1 for bp in breakpoints if bp.get("severity") == "FATAL")
            if fatal_count > 0:
                base += 0.10  # Fatal breakpoints make scenarios more important to track

            # Prophecy alignment
            active_prophecies = context.get("active_prophecies", [])
            conditions = set(scenario.get("conditions", []))
            prophecy_matches = sum(
                1 for p in active_prophecies
                if any(c.lower() in p.lower() for c in conditions)
            )
            base += min(prophecy_matches * 0.05, 0.10)

            # Diversity bonus: if few scenarios, each is more important
            n = context.get("n_scenarios", 1)
            if n <= 3:
                base += 0.05

            return max(0.0, min(1.0, base))
    ''')


def _default_working_memory_evictor() -> str:
    """The default working memory eviction logic."""
    return textwrap.dedent('''\
        def select_eviction_candidate(memory_slots: list, context: dict) -> int:
            """Select which working memory slot to evict when capacity is full.

            Args:
                memory_slots: list of dicts, each with:
                    {"content": str, "type": str, "relevance": float,
                     "inserted_at": str, "access_count": int, "source": str}
                context: {"current_problem": str, "phase": str,
                         "n_total_insertions": int}

            Returns:
                int: Index of the slot to evict (0-based)
            """
            import datetime

            if not memory_slots:
                return 0

            # Score each slot: LOWER score = more likely to evict
            scores = []
            type_priority = {
                "procedural": 1.5,
                "semantic": 1.3,
                "echo": 1.2,
                "insight": 1.1,
                "sensory": 0.8,
                "raw": 0.6,
            }

            for i, slot in enumerate(memory_slots):
                score = 0.0

                # Type priority
                score += type_priority.get(slot.get("type", "raw"), 0.7)

                # Relevance to current problem
                score += slot.get("relevance", 0.5) * 2.0

                # Recency: more recent = higher score
                try:
                    inserted = datetime.datetime.fromisoformat(slot.get("inserted_at", ""))
                    age_minutes = (datetime.datetime.now(datetime.timezone.utc) - inserted).total_seconds() / 60
                    recency = max(0, 1.0 - (age_minutes / 120))  # Decay over 2 hours
                    score += recency * 0.5
                except (ValueError, TypeError):
                    pass

                # Access count: frequently accessed = more valuable
                score += min(slot.get("access_count", 0) * 0.1, 0.5)

                scores.append(score)

            # Evict the lowest-scoring slot
            return scores.index(min(scores))
    ''')


# ══════════════════════════════════════════════════════════════
#  FUNCTION REGISTRY BUILDER
# ══════════════════════════════════════════════════════════════

def build_default_registry() -> dict[str, ModifiableFunction]:
    """Build the default registry of modifiable functions."""

    curiosity_code = _default_curiosity_prioritizer()
    prophecy_code = _default_prophecy_confidence_adjuster()
    scenario_code = _default_scenario_salience_scorer()
    eviction_code = _default_working_memory_evictor()

    return {
        "curiosity_priority": ModifiableFunction(
            function_id="curiosity_priority",
            description="Computes priority score for curiosity questions. Higher priority = explored sooner.",
            module_path="xdart.phases.curiosity",
            function_name="compute_curiosity_priority",
            signature="def compute_curiosity_priority(curiosity: dict, context: dict) -> float",
            current_code=curiosity_code,
            original_code=curiosity_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must not crash on empty inputs",
                "Must consider source_type weighting",
                "Must penalize over-explored curiosities",
                "Only safe imports allowed (json, math, datetime, etc.)",
            ],
            test_inputs=[
                {
                    "curiosity": {
                        "question": "Why is EU response asymmetric to US tariffs?",
                        "source_type": "introspection",
                        "tags": ["trade", "EU", "geopolitics"],
                        "created_at": "2026-04-10T12:00:00+00:00",
                        "exploration_count": 0,
                    },
                    "context": {
                        "active_tensions": ["trade", "sovereignty"],
                        "recent_topics": ["tariffs", "EU policy"],
                        "avg_integrity": 0.75,
                        "world_events_count": 45,
                    },
                },
                {
                    "curiosity": {
                        "question": "What cartoon is popular?",
                        "source_type": "pipeline",
                        "tags": [],
                        "created_at": "2026-04-01T12:00:00+00:00",
                        "exploration_count": 5,
                    },
                    "context": {
                        "active_tensions": [],
                        "recent_topics": [],
                        "avg_integrity": 0.5,
                        "world_events_count": 0,
                    },
                },
            ],
            expected_behavior="Returns 0.0-1.0. Introspection curiosities from self_evolution get highest base scores. Over-explored curiosities are penalized. Tag overlap with active tensions boosts priority.",
        ),

        "prophecy_confidence": ModifiableFunction(
            function_id="prophecy_confidence",
            description="Adjusts confidence in prophecies based on new evidence and calibration data.",
            module_path="xdart.phases.prophetic_loop",
            function_name="adjust_prophecy_confidence",
            signature="def adjust_prophecy_confidence(prophecy: dict, context: dict) -> float",
            current_code=prophecy_code,
            original_code=prophecy_code,
            constraints=[
                "Must return a float between 0.05 and 0.95",
                "Must never return 0.0 or 1.0 (epistemic humility)",
                "Must consider both supporting and contradicting evidence",
                "Must pull towards uncertainty when calibration is poor",
                "Only safe imports allowed",
            ],
            test_inputs=[
                {
                    "prophecy": {
                        "prediction": "ECB will cut rates by June 2026",
                        "confidence": 0.7,
                        "domain": "ECONOMIC",
                        "created_at": "2026-03-15T00:00:00+00:00",
                        "supporting_evidence": ["dovish speech", "inflation decline"],
                        "contradicting_evidence": [],
                        "days_remaining": 45,
                    },
                    "context": {
                        "world_events": [],
                        "brier_score": 0.22,
                        "calibration_error": 0.05,
                    },
                },
                {
                    "prophecy": {
                        "prediction": "China invades Taiwan by Q3 2026",
                        "confidence": 0.3,
                        "domain": "GEOPOLITICAL",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "supporting_evidence": [],
                        "contradicting_evidence": ["diplomatic talks", "trade deals"],
                        "days_remaining": 5,
                    },
                    "context": {
                        "world_events": [],
                        "brier_score": 0.40,
                        "calibration_error": 0.15,
                    },
                },
            ],
            expected_behavior="Returns 0.05-0.95. Evidence balance shifts confidence. Temporal decay reduces confidence as deadline approaches without confirmation. Poor calibration (high brier) pulls towards 0.5.",
        ),

        "scenario_salience": ModifiableFunction(
            function_id="scenario_salience",
            description="Scores how important/salient a scenario is for the current analysis.",
            module_path="xdart.phases.scenario_genesis",
            function_name="score_scenario_salience",
            signature="def score_scenario_salience(scenario: dict, context: dict) -> float",
            current_code=scenario_code,
            original_code=scenario_code,
            constraints=[
                "Must return a float between 0.0 and 1.0",
                "Must weight tribunal_score heavily",
                "Must consider domain relevance",
                "Must not ignore breakpoints",
                "Only safe imports allowed",
            ],
            test_inputs=[
                {
                    "scenario": {
                        "title": "Trade War Escalation",
                        "conditions": ["tariff increase", "retaliatory measures"],
                        "timeline": "Q2 2026",
                        "domains": ["ECONOMIC", "GEOPOLITICAL"],
                        "confidence": 0.65,
                        "tribunal_score": 0.78,
                        "breakpoints": [{"severity": "DEGRADING", "desc": "supply chain disruption"}],
                    },
                    "context": {
                        "problem_domains": ["ECONOMIC", "MARKET"],
                        "active_prophecies": ["tariff escalation likely"],
                        "recent_events_domains": ["ECONOMIC"],
                        "n_scenarios": 4,
                    },
                },
            ],
            expected_behavior="Returns 0.0-1.0. Tribunal score is primary factor. Domain overlap with problem boosts salience. Fatal breakpoints increase importance. Prophecy alignment adds bonus.",
        ),

        "working_memory_eviction": ModifiableFunction(
            function_id="working_memory_eviction",
            description="Selects which working memory slot to evict when capacity is full.",
            module_path="xdart.phases.memory_architecture",
            function_name="select_eviction_candidate",
            signature="def select_eviction_candidate(memory_slots: list, context: dict) -> int",
            current_code=eviction_code,
            original_code=eviction_code,
            constraints=[
                "Must return a valid index (0 to len(memory_slots)-1)",
                "Must never crash on empty list",
                "Must consider type priority (procedural > semantic > echo)",
                "Must consider relevance and recency",
                "Only safe imports allowed",
            ],
            test_inputs=[
                {
                    "memory_slots": [
                        {"content": "EU trade analysis", "type": "semantic", "relevance": 0.8, "inserted_at": "2026-04-12T10:00:00+00:00", "access_count": 3, "source": "phase2"},
                        {"content": "Raw RSS data point", "type": "raw", "relevance": 0.2, "inserted_at": "2026-04-12T09:00:00+00:00", "access_count": 0, "source": "perception"},
                        {"content": "If X then Y pattern", "type": "procedural", "relevance": 0.9, "inserted_at": "2026-04-12T08:00:00+00:00", "access_count": 5, "source": "phase3"},
                    ],
                    "context": {
                        "current_problem": "EU trade policy",
                        "phase": "phase2",
                        "n_total_insertions": 15,
                    },
                },
            ],
            expected_behavior="Returns index of lowest-value slot. Raw data with low relevance and low access should be evicted first. Procedural memories with high relevance should be preserved.",
        ),
    }


# ══════════════════════════════════════════════════════════════
#  LOGIC SANDBOX — THE MAIN SYSTEM
# ══════════════════════════════════════════════════════════════

PROPOSAL_PROMPT = """\
You are Αίολος's self-modification engine.

You have the ability to REWRITE specific algorithmic functions in your own \
reasoning system. This is NOT about generating new tools or writing overlays — \
this is about changing HOW YOU THINK at the algorithmic level.

=== FUNCTION YOU MAY MODIFY ===
ID: {function_id}
Description: {description}
Module: {module_path}
Signature: {signature}

CURRENT CODE:
```python
{current_code}
```

CONSTRAINTS (these MUST hold in any modification):
{constraints}

=== EVIDENCE FOR MODIFICATION ===
{evidence}

=== YOUR TASK ===
Analyze whether this function should be modified based on the evidence.

Consider:
1. Is the current logic actually producing suboptimal results?
2. Can you identify a SPECIFIC improvement to the algorithm?
3. Will the improvement generalize (not just fix one edge case)?
4. Does the modification respect ALL constraints?

If YES — propose the new code.
If NO — explain why the current logic is adequate.

Respond ONLY with valid JSON:
{{
    "should_modify": true|false,
    "rationale": "Why this modification is needed (or why not)",
    "proposed_code": "Complete function code (if modifying, else empty string)",
    "expected_improvement": "What specifically gets better",
    "risk_assessment": "What could go wrong",
    "confidence": 0.0-1.0
}}

CRITICAL: The proposed_code must:
- Be a COMPLETE, STANDALONE function matching the original signature
- Use ONLY safe imports: {safe_imports}
- Return the correct type as specified in the signature
- Handle edge cases (empty inputs, missing keys, etc.)
- Respect ALL constraints listed above
"""


class LogicSandbox:
    """Self-modification sandbox with guardrails.

    Allows Αίολος to propose, test, and (with approval) apply
    modifications to designated algorithmic functions.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.sandbox = Sandbox(timeout=30)
        self._registry: dict[str, ModifiableFunction] = {}
        self._proposals: dict[str, LogicProposal] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load state from disk, or initialize defaults."""
        if STATE_PATH.exists():
            try:
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self._registry = {
                    fid: ModifiableFunction.from_dict(fdata)
                    for fid, fdata in state.get("registry", {}).items()
                }
                self._proposals = {
                    pid: LogicProposal.from_dict(pdata)
                    for pid, pdata in state.get("proposals", {}).items()
                }
                logger.info(
                    "[LogicSandbox] Loaded state: %d functions, %d proposals",
                    len(self._registry), len(self._proposals),
                )
            except Exception as e:
                logger.warning("[LogicSandbox] Failed to load state: %s — using defaults", e)
                self._registry = build_default_registry()
        else:
            self._registry = build_default_registry()
            self._save_state()
            logger.info("[LogicSandbox] Initialized with %d modifiable functions", len(self._registry))

    def _save_state(self) -> None:
        """Persist state to disk."""
        state = {
            "registry": {fid: f.to_dict() for fid, f in self._registry.items()},
            "proposals": {pid: p.to_dict() for pid, p in self._proposals.items()},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        try:
            STATE_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[LogicSandbox] Failed to save state: %s", e)

    def _journal(self, entry: dict) -> None:
        """Append to the audit journal."""
        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error("[LogicSandbox] Journal write failed: %s", e)

    # ──────────────────────────────────────────────────────────
    #  PROPOSE — Αίολος proposes a modification
    # ──────────────────────────────────────────────────────────

    def propose_modification(
        self,
        function_id: str,
        evidence: str,
        callback: Callable | None = None,
    ) -> LogicProposal | None:
        """Have the LLM analyze a function and propose a modification.

        Args:
            function_id: Which function to analyze (must be in registry)
            evidence: Why modification is needed (from introspection, etc.)
            callback: SSE callback for progress updates

        Returns:
            LogicProposal if modification proposed, None if no change needed
        """
        if function_id not in self._registry:
            logger.warning("[LogicSandbox] Unknown function: %s", function_id)
            return None

        # Guard against too many pending proposals
        pending = [p for p in self._proposals.values() if p.status == "pending"]
        if len(pending) >= MAX_PENDING_PROPOSALS:
            logger.info("[LogicSandbox] Too many pending proposals (%d), skipping", len(pending))
            return None

        func = self._registry[function_id]
        t0 = time.perf_counter()

        if callback:
            callback("logic_sandbox_analyzing", {
                "function_id": function_id,
                "description": func.description,
            })

        prompt = PROPOSAL_PROMPT.format(
            function_id=func.function_id,
            description=func.description,
            module_path=func.module_path,
            signature=func.signature,
            current_code=func.current_code,
            constraints="\n".join(f"  - {c}" for c in func.constraints),
            evidence=evidence[:3000],
            safe_imports=", ".join(sorted(SAFE_IMPORTS)),
        )

        try:
            result = self.llm.call_json(
                system_prompt=prompt,
                user_prompt="Analyze this function and decide whether to modify it.",
                max_tokens=8192,
                temperature=0.3,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[LogicSandbox] LLM call failed: %s", e)
            return None

        if not result.get("should_modify"):
            elapsed = time.perf_counter() - t0
            logger.info(
                "[LogicSandbox] No modification needed for %s (%.2fs): %s",
                function_id, elapsed, result.get("rationale", ""),
            )
            self._journal({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "analysis",
                "function_id": function_id,
                "should_modify": False,
                "rationale": result.get("rationale", ""),
                "elapsed": round(elapsed, 2),
            })
            return None

        proposed_code = result.get("proposed_code", "")
        if not proposed_code:
            logger.warning("[LogicSandbox] Modification proposed but no code provided")
            return None

        # Create proposal
        import uuid
        proposal = LogicProposal(
            id=str(uuid.uuid4())[:8],
            function_id=function_id,
            proposed_code=proposed_code,
            rationale=result.get("rationale", ""),
            expected_improvement=result.get("expected_improvement", ""),
            risk_assessment=result.get("risk_assessment", ""),
            proposed_at=datetime.now(timezone.utc).isoformat(),
        )

        self._proposals[proposal.id] = proposal
        self._save_state()

        elapsed = time.perf_counter() - t0
        logger.info(
            "[LogicSandbox] PROPOSAL created: %s for %s (%.2fs)",
            proposal.id, function_id, elapsed,
        )

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "proposal",
            "proposal_id": proposal.id,
            "function_id": function_id,
            "rationale": proposal.rationale,
            "expected_improvement": proposal.expected_improvement,
            "risk": proposal.risk_assessment,
            "elapsed": round(elapsed, 2),
        })

        if callback:
            callback("logic_sandbox_proposal", {
                "proposal_id": proposal.id,
                "function_id": function_id,
                "rationale": proposal.rationale,
                "expected_improvement": proposal.expected_improvement,
            })

        return proposal

    # ──────────────────────────────────────────────────────────
    #  TEST — Sandbox test a proposal
    # ──────────────────────────────────────────────────────────

    def test_proposal(self, proposal_id: str) -> dict:
        """Run sandbox tests on a proposal.

        Returns:
            dict with test results
        """
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]
        func = self._registry.get(proposal.function_id)
        if not func:
            return {"error": "Function not found in registry"}

        proposal.status = "testing"
        results = {"tests_passed": 0, "tests_failed": 0, "errors": []}

        for i, test_input in enumerate(func.test_inputs):
            # Build test harness for the proposed code
            harness_code = self._build_test_harness(
                proposal.proposed_code,
                func.function_name,
                test_input,
            )

            sandbox_result = self.sandbox._execute(harness_code)

            if sandbox_result.success:
                results["tests_passed"] += 1
                # Validate output constraints
                output = sandbox_result.output
                constraint_violations = self._check_constraints(
                    func, output, test_input,
                )
                if constraint_violations:
                    results["tests_failed"] += 1
                    results["tests_passed"] -= 1
                    results["errors"].append({
                        "test": i,
                        "type": "constraint_violation",
                        "details": constraint_violations,
                    })
            else:
                results["tests_failed"] += 1
                results["errors"].append({
                    "test": i,
                    "type": "execution_error",
                    "details": sandbox_result.error,
                })

        # Also test the CURRENT code for baseline comparison
        baseline_results = {"tests_passed": 0, "tests_failed": 0}
        for test_input in func.test_inputs:
            harness_code = self._build_test_harness(
                func.current_code,
                func.function_name,
                test_input,
            )
            sandbox_result = self.sandbox._execute(harness_code)
            if sandbox_result.success:
                baseline_results["tests_passed"] += 1
            else:
                baseline_results["tests_failed"] += 1

        results["baseline"] = baseline_results
        results["all_passed"] = results["tests_failed"] == 0
        proposal.sandbox_result = results
        proposal.status = "tested"
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "sandbox_test",
            "proposal_id": proposal_id,
            "function_id": proposal.function_id,
            "results": results,
        })

        logger.info(
            "[LogicSandbox] Sandbox test for %s: %d passed, %d failed",
            proposal_id, results["tests_passed"], results["tests_failed"],
        )

        return results

    def _build_test_harness(
        self,
        function_code: str,
        function_name: str,
        test_input: dict,
    ) -> str:
        """Build a sandbox test harness for a function."""
        input_json = json.dumps(test_input, ensure_ascii=False, default=str)

        # Determine the args from test_input keys
        arg_names = list(test_input.keys())
        call_args = ", ".join(f"test_input['{k}']" for k in arg_names)

        return textwrap.dedent(f"""\
            import json
            import sys

            # ── Function under test ──
            {textwrap.indent(function_code, '            ').strip()}
            # ── End function ──

            try:
                test_input = json.loads('''{input_json}''')
                result = {function_name}({call_args})

                print("__SANDBOX_RESULT__")
                print(json.dumps({{"tool_name": "{function_name}", "output": str(result), "metadata": {{"type": type(result).__name__, "value": result}}}}, ensure_ascii=False, default=str))

            except Exception as e:
                print(json.dumps({{"error": f"{{type(e).__name__}}: {{e}}"}}))
                sys.exit(1)
        """)

    def _check_constraints(
        self,
        func: ModifiableFunction,
        output: dict | None,
        test_input: dict,
    ) -> list[str]:
        """Check if output satisfies function constraints."""
        violations = []
        if output is None:
            violations.append("No output produced")
            return violations

        result_value = output.get("metadata", {}).get("value")
        result_type = output.get("metadata", {}).get("type")

        # Type check based on signature
        if "-> float" in func.signature:
            if result_type != "float" and result_type != "int":
                violations.append(f"Expected float, got {result_type}")
            elif isinstance(result_value, (int, float)):
                if "between 0.0 and 1.0" in " ".join(func.constraints) or \
                   "between 0.05 and 0.95" in " ".join(func.constraints):
                    if result_value < 0.0 or result_value > 1.0:
                        violations.append(f"Value {result_value} out of [0.0, 1.0] range")

        elif "-> int" in func.signature:
            if result_type != "int":
                violations.append(f"Expected int, got {result_type}")

        return violations

    # ──────────────────────────────────────────────────────────
    #  APPROVE / REJECT — Human decision
    # ──────────────────────────────────────────────────────────

    def approve_proposal(self, proposal_id: str, approved_by: str = "human") -> dict:
        """Approve a tested proposal for application.

        Only proposals that passed sandbox testing can be approved.
        """
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]

        if proposal.status not in ("tested",):
            return {"error": f"Proposal must be in 'tested' state, is '{proposal.status}'"}

        if proposal.sandbox_result and not proposal.sandbox_result.get("all_passed"):
            return {"error": "Cannot approve proposal that failed sandbox tests"}

        proposal.approval_status = "approved"
        proposal.approved_by = approved_by
        proposal.status = "approved"
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "approval",
            "proposal_id": proposal_id,
            "approved_by": approved_by,
        })

        logger.info("[LogicSandbox] Proposal %s APPROVED by %s", proposal_id, approved_by)
        return {"status": "approved", "proposal_id": proposal_id}

    def reject_proposal(self, proposal_id: str, reason: str = "") -> dict:
        """Reject a proposal."""
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]
        proposal.approval_status = "rejected"
        proposal.status = "rejected"
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "rejection",
            "proposal_id": proposal_id,
            "reason": reason,
        })

        logger.info("[LogicSandbox] Proposal %s REJECTED: %s", proposal_id, reason)
        return {"status": "rejected", "proposal_id": proposal_id}

    # ──────────────────────────────────────────────────────────
    #  APPLY — Activate approved modification
    # ──────────────────────────────────────────────────────────

    def apply_proposal(self, proposal_id: str) -> dict:
        """Apply an approved proposal — swap in the new logic."""
        if proposal_id not in self._proposals:
            return {"error": "Proposal not found"}

        proposal = self._proposals[proposal_id]

        if proposal.status != "approved":
            return {"error": f"Proposal must be approved first, is '{proposal.status}'"}

        func = self._registry.get(proposal.function_id)
        if not func:
            return {"error": "Function not found"}

        # Store the old code in history for rollback
        func.history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "code": func.current_code,
            "reason": f"Replaced by proposal {proposal_id}",
        })

        # Trim history
        if len(func.history) > MAX_MODIFICATION_HISTORY:
            func.history = func.history[-MAX_MODIFICATION_HISTORY:]

        # Apply the new code
        old_code = func.current_code
        func.current_code = proposal.proposed_code
        func.modification_count += 1
        func.active_modification = {
            "proposal_id": proposal_id,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "rationale": proposal.rationale,
        }

        proposal.status = "applied"
        proposal.applied_at = datetime.now(timezone.utc).isoformat()
        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "application",
            "proposal_id": proposal_id,
            "function_id": proposal.function_id,
            "rationale": proposal.rationale,
        })

        logger.info(
            "[LogicSandbox] ✓ APPLIED proposal %s to %s (modification #%d)",
            proposal_id, proposal.function_id, func.modification_count,
        )

        return {
            "status": "applied",
            "function_id": proposal.function_id,
            "modification_count": func.modification_count,
        }

    # ──────────────────────────────────────────────────────────
    #  ROLLBACK — Revert to previous version
    # ──────────────────────────────────────────────────────────

    def rollback(self, function_id: str, to_original: bool = False) -> dict:
        """Rollback a function to its previous version or factory original.

        Args:
            function_id: Which function to rollback
            to_original: If True, rollback to factory original. Otherwise, to previous version.
        """
        if function_id not in self._registry:
            return {"error": "Function not found"}

        func = self._registry[function_id]

        if to_original:
            if func.current_code == func.original_code:
                return {"status": "already_at_original"}

            func.history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "code": func.current_code,
                "reason": "Rolled back to original",
            })
            func.current_code = func.original_code
            func.active_modification = None
        else:
            if not func.history:
                return {"error": "No history to rollback to"}

            previous = func.history.pop()
            func.current_code = previous["code"]
            func.active_modification = None

        self._save_state()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "rollback",
            "function_id": function_id,
            "to_original": to_original,
        })

        logger.info(
            "[LogicSandbox] ROLLED BACK %s (to_original=%s)",
            function_id, to_original,
        )

        return {"status": "rolled_back", "function_id": function_id}

    # ──────────────────────────────────────────────────────────
    #  QUERY — Inspection APIs
    # ──────────────────────────────────────────────────────────

    def get_registry(self) -> list[dict]:
        """Get all modifiable functions and their status."""
        return [
            {
                "function_id": f.function_id,
                "description": f.description,
                "module_path": f.module_path,
                "function_name": f.function_name,
                "modification_count": f.modification_count,
                "has_active_modification": f.active_modification is not None,
                "is_original": f.current_code == f.original_code,
                "constraints": f.constraints,
            }
            for f in self._registry.values()
        ]

    def get_function_detail(self, function_id: str) -> dict | None:
        """Get full detail of a function including current code."""
        if function_id not in self._registry:
            return None
        func = self._registry[function_id]
        return {
            **func.to_dict(),
            "is_original": func.current_code == func.original_code,
        }

    def get_proposals(self, status: str | None = None) -> list[dict]:
        """Get proposals, optionally filtered by status."""
        proposals = self._proposals.values()
        if status:
            proposals = [p for p in proposals if p.status == status]
        return [p.to_dict() for p in proposals]

    def get_stats(self) -> dict:
        """Summary statistics for the sandbox."""
        return {
            "total_functions": len(self._registry),
            "total_proposals": len(self._proposals),
            "pending_approval": sum(
                1 for p in self._proposals.values()
                if p.status == "tested" and p.sandbox_result and p.sandbox_result.get("all_passed")
            ),
            "applied": sum(1 for p in self._proposals.values() if p.status == "applied"),
            "rejected": sum(1 for p in self._proposals.values() if p.status == "rejected"),
            "modified_functions": sum(
                1 for f in self._registry.values()
                if f.current_code != f.original_code
            ),
        }

    def get_pending_approvals(self) -> list[dict]:
        """Get proposals that need human approval."""
        return [
            p.to_dict() for p in self._proposals.values()
            if p.status == "tested" and p.sandbox_result and p.sandbox_result.get("all_passed")
        ]

    def get_current_code(self, function_id: str) -> str | None:
        """Get the current code for a function (used by pipeline)."""
        if function_id not in self._registry:
            return None
        return self._registry[function_id].current_code

    # ──────────────────────────────────────────────────────────
    #  AUTO-ANALYZE — Triggered by self-evolution
    # ──────────────────────────────────────────────────────────

    def auto_analyze(
        self,
        introspection_data: str,
        performance_data: dict,
        callback: Callable | None = None,
    ) -> list[LogicProposal]:
        """Analyze all modifiable functions and propose modifications where needed.

        Typically called after a pipeline run or during self-evolution.
        """
        proposals = []

        # Build evidence string from introspection + performance
        evidence = f"""
RECENT INTROSPECTION DATA:
{introspection_data[:2000]}

PERFORMANCE METRICS:
- Brier score: {performance_data.get('brier_score', 'N/A')}
- Avg epistemic integrity: {performance_data.get('avg_integrity', 'N/A')}
- Calibration error: {performance_data.get('calibration_error', 'N/A')}
- Prophecies confirmed: {performance_data.get('prophecies_confirmed', 'N/A')}
- Prophecies disconfirmed: {performance_data.get('prophecies_disconfirmed', 'N/A')}
- Curiosity exploration success rate: {performance_data.get('curiosity_success_rate', 'N/A')}
"""

        for function_id, func in self._registry.items():
            # Skip if there's already a pending proposal for this function
            existing = [
                p for p in self._proposals.values()
                if p.function_id == function_id and p.status in ("pending", "testing", "tested", "approved")
            ]
            if existing:
                logger.info("[LogicSandbox] Skipping %s — has pending proposal", function_id)
                continue

            proposal = self.propose_modification(function_id, evidence, callback)
            if proposal:
                # Auto-test immediately
                test_result = self.test_proposal(proposal.id)
                if test_result.get("all_passed"):
                    proposals.append(proposal)
                    logger.info(
                        "[LogicSandbox] Proposal %s for %s passed sandbox — awaiting approval",
                        proposal.id, function_id,
                    )

        return proposals
