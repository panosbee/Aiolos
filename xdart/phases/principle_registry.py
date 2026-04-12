"""
XDART-Φ × XHEART — Dynamic Principle Registry (δυναμική αρχειοθέτηση αρχών)

A living, evolving knowledge base where Αίολος's OWN decisions and mistakes
generate NEW operating principles — not static rules, but learned wisdom
that emerges from experience.

Unlike the static 11 Universal Axioms (which are foundational lenses),
Dynamic Principles are:
  - BORN from specific failures, patterns, or calibration errors
  - EVIDENCE-BASED — each principle cites the events that created it
  - TESTABLE — each principle has conditions where it applies
  - SCORED — effectiveness tracked over time, weak principles pruned
  - APPROVED — new principles require human approval before becoming active

Example flow:
  1. Αίολος notices he consistently overestimates geopolitical escalation risk
  2. Introspection + wisdom tracker confirm the pattern (Brier evidence)
  3. System proposes: "PRINCIPLE: For military posturing without logistics buildup,
     apply 0.7× confidence multiplier before issuing escalation prophecies"
  4. Panos approves → principle becomes active
  5. Principle is injected into relevant phase prompts when conditions match
  6. Effectiveness tracked across runs → principle strengthened or retired

The Iron Rules:
  1. EVIDENCE REQUIRED — Every principle must cite specific runs/events/metrics
  2. FALSIFIABLE — Every principle must have conditions where it doesn't apply
  3. TESTABLE — Every principle must have measurable expected effect
  4. HUMAN-GATED — New principles need Panos's approval
  5. MORTAL — Principles that don't improve performance are auto-retired
  6. UNIQUE — No duplicate or near-duplicate principles (semantic dedup)

Storage: principle_registry.json (current state)
         principle_registry_journal.jsonl (audit trail)

«Μια αρχή που δεν γεννήθηκε από λάθος είναι θεωρία.
 Μια αρχή που γεννήθηκε από λάθος και επιβεβαιώθηκε... είναι σοφία.»
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

logger = logging.getLogger("xdart.principle_registry")

# ── Paths ──
BASE_DIR = Path(__file__).parent.parent.parent
REGISTRY_PATH = BASE_DIR / "principle_registry.json"
JOURNAL_PATH = BASE_DIR / "principle_registry_journal.jsonl"

# ── Limits ──
MAX_ACTIVE_PRINCIPLES = 30       # Prevent prompt bloat
MAX_PRINCIPLE_CHARS = 1000       # Per principle text
MIN_USES_FOR_EVAL = 5            # Minimum uses before evaluating effectiveness
RETIREMENT_THRESHOLD = 0.25      # Auto-retire below this avg effectiveness
STRENGTHENING_THRESHOLD = 0.70   # Strengthen (boost) above this
MAX_HISTORY_PER_PRINCIPLE = 30   # Application history entries


# ══════════════════════════════════════════════════════════════
#  DATA MODEL
# ══════════════════════════════════════════════════════════════

@dataclass
class DynamicPrinciple:
    """A learned operating principle born from experience."""

    id: str                          # Unique identifier (e.g. "DP-014")
    title: str                       # Short name (e.g. "Posturing Discount")
    principle_text: str              # The actual principle statement
    procedure: str                   # Concrete step-by-step procedure to follow
    domain: str                      # GEOPOLITICAL, ECONOMIC, MARKET, TECHNOLOGY, META, EPISTEMIC
    trigger_conditions: list[str]    # When does this principle apply?
    non_applicable_conditions: list[str]  # When does it NOT apply? (falsifiability)
    applies_to_phases: list[str]     # Which pipeline phases should see this
    evidence: list[dict]             # [{run_number, event, metric, description}]
    expected_effect: str             # What measurable improvement is expected
    measurement_metric: str          # How to measure (e.g. "brier_score for escalation prophecies")

    # Lifecycle
    status: str = "proposed"         # proposed → active → strengthened → weakened → retired
    created_at: str = ""
    activated_at: str | None = None
    approved_by: str = ""            # "human" or empty
    retired_at: str | None = None
    retirement_reason: str = ""

    # Effectiveness tracking
    application_count: int = 0
    effectiveness_scores: list[float] = field(default_factory=list)
    application_history: list[dict] = field(default_factory=list)  # [{run, score, context}]

    # Provenance
    born_from: str = ""              # What triggered creation: "introspection", "wisdom_tracker", "brier_pattern", "self_evolution"
    born_from_pattern: str = ""      # The specific pattern that triggered it
    related_axiom: str = ""          # If related to a static axiom (e.g. "AX-08")

    @property
    def avg_effectiveness(self) -> float | None:
        if len(self.effectiveness_scores) < MIN_USES_FOR_EVAL:
            return None
        return sum(self.effectiveness_scores[-MAX_HISTORY_PER_PRINCIPLE:]) / \
            len(self.effectiveness_scores[-MAX_HISTORY_PER_PRINCIPLE:])

    @property
    def should_retire(self) -> bool:
        avg = self.avg_effectiveness
        if avg is None:
            return False
        return avg < RETIREMENT_THRESHOLD

    @property
    def should_strengthen(self) -> bool:
        avg = self.avg_effectiveness
        if avg is None:
            return False
        return avg >= STRENGTHENING_THRESHOLD

    def to_dict(self) -> dict:
        d = asdict(self)
        d["avg_effectiveness"] = self.avg_effectiveness
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "DynamicPrinciple":
        data.pop("avg_effectiveness", None)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════
#  PRINCIPLE GENESIS — LLM creates principles from evidence
# ══════════════════════════════════════════════════════════════

GENESIS_PROMPT = """\
You are the principle discovery engine of Αίολος, an AI intelligence analyst.

Your job: analyze patterns of error, bias, or suboptimal reasoning and \
PROPOSE a new operating principle that would prevent the same mistake \
from repeating.

=== EVIDENCE OF PATTERN ===
{evidence}

=== EXISTING STATIC AXIOMS (do NOT duplicate these) ===
{existing_axioms}

=== EXISTING DYNAMIC PRINCIPLES (do NOT duplicate these) ===
{existing_principles}

=== PERFORMANCE DATA ===
- Brier Score: {brier_score}
- Avg Epistemic Integrity: {avg_integrity}
- Calibration Error: {calibration_error}
- Recent Failure Patterns: {failure_patterns}

=== YOUR TASK ===
1. Is there a RECURRING pattern (not one-off) that deserves a principle?
2. Is this pattern NOT already covered by existing axioms or principles?
3. Can you formulate a SPECIFIC, ACTIONABLE, TESTABLE principle?

A good principle:
  ✓ Born from specific evidence (not abstract philosophy)
  ✓ Has clear trigger conditions (when to apply)
  ✓ Has clear non-applicable conditions (when NOT to apply — falsifiability)
  ✓ Includes a concrete PROCEDURE (not just "be careful")
  ✓ Has measurable expected effect
  ✓ Targets specific pipeline phases

A bad principle:
  ✗ Too vague ("be more careful with predictions")
  ✗ Duplicates existing axiom or principle
  ✗ Based on single event (not a pattern)
  ✗ Not falsifiable (always applies, no exceptions)

Respond ONLY with valid JSON:
{{
    "principle_needed": true|false,
    "reasoning": "Why this principle is/isn't needed",
    "principle": {{
        "title": "Short memorable name (3-5 words)",
        "principle_text": "The principle statement (1-2 sentences, max 200 chars)",
        "procedure": "Step-by-step procedure to follow (max 500 chars)",
        "domain": "GEOPOLITICAL|ECONOMIC|MARKET|TECHNOLOGY|META|EPISTEMIC",
        "trigger_conditions": ["condition1", "condition2"],
        "non_applicable_conditions": ["exception1", "exception2"],
        "applies_to_phases": ["phase names: ontology, scenario_genesis, scenario_tribunal, xheart_distillation, prophetic_bets, chat_system"],
        "expected_effect": "What measurable improvement",
        "measurement_metric": "How to measure",
        "born_from": "introspection|wisdom_tracker|brier_pattern|self_evolution|curiosity",
        "born_from_pattern": "The specific pattern that triggered this",
        "related_axiom": "AX-XX if related, else empty string"
    }},
    "confidence": 0.0-1.0
}}

If no principle needed, set principle_needed to false and principle to null."""


EFFECTIVENESS_PROMPT = """\
You are evaluating whether a Dynamic Principle helped in a specific analysis run.

PRINCIPLE:
Title: {title}
Text: {principle_text}
Procedure: {procedure}
Domain: {domain}

THIS RUN:
Problem: {problem}
Phase that used principle: {phase}
Output quality indicators:
{quality_indicators}

Question: On a scale of 0.0 to 1.0, how relevant and effective was this \
principle for THIS specific run?

0.0 = Completely irrelevant or actively harmful
0.3 = Mildly relevant but didn't measurably help
0.5 = Somewhat helpful
0.7 = Clearly helpful — improved the analysis
1.0 = Critical — this principle was essential

Respond ONLY with JSON: {{"score": 0.0-1.0, "reasoning": "brief explanation"}}"""


# ══════════════════════════════════════════════════════════════
#  PRINCIPLE REGISTRY
# ══════════════════════════════════════════════════════════════

class PrincipleRegistry:
    """Manages the lifecycle of dynamic principles.

    Handles: creation, approval, activation, tracking, retirement.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self._principles: dict[str, DynamicPrinciple] = {}
        self._next_id: int = 1
        self._load()

    def _load(self) -> None:
        """Load from disk."""
        if not REGISTRY_PATH.exists():
            self._principles = {}
            self._next_id = 1
            return
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._principles = {
                pid: DynamicPrinciple.from_dict(pdata)
                for pid, pdata in data.get("principles", {}).items()
            }
            self._next_id = data.get("next_id", len(self._principles) + 1)
            logger.info(
                "[PrincipleRegistry] Loaded %d principles (%d active)",
                len(self._principles),
                sum(1 for p in self._principles.values() if p.status == "active"),
            )
        except Exception as e:
            logger.warning("[PrincipleRegistry] Failed to load: %s — starting fresh", e)
            self._principles = {}
            self._next_id = 1

    def _save(self) -> None:
        """Persist to disk."""
        data = {
            "principles": {pid: p.to_dict() for pid, p in self._principles.items()},
            "next_id": self._next_id,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "stats": {
                "total": len(self._principles),
                "active": sum(1 for p in self._principles.values() if p.status == "active"),
                "proposed": sum(1 for p in self._principles.values() if p.status == "proposed"),
                "retired": sum(1 for p in self._principles.values() if p.status == "retired"),
            },
        }
        try:
            REGISTRY_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[PrincipleRegistry] Failed to save: %s", e)

    def _journal(self, entry: dict) -> None:
        """Append to audit journal."""
        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error("[PrincipleRegistry] Journal write failed: %s", e)

    # ──────────────────────────────────────────────────────────
    #  DISCOVER — Find new principles from evidence
    # ──────────────────────────────────────────────────────────

    def discover(
        self,
        evidence: str,
        performance_data: dict,
        existing_axioms_text: str = "",
        callback=None,
    ) -> DynamicPrinciple | None:
        """Analyze evidence and propose a new principle if warranted.

        Args:
            evidence: Aggregated evidence from introspection, wisdom, failures
            performance_data: Brier score, integrity, calibration metrics
            existing_axioms_text: Static axioms (to avoid duplication)
            callback: SSE callback

        Returns:
            New DynamicPrinciple if one is proposed, else None
        """
        t0 = time.perf_counter()

        # Guard: max active principles
        active_count = sum(1 for p in self._principles.values() if p.status == "active")
        if active_count >= MAX_ACTIVE_PRINCIPLES:
            logger.info("[PrincipleRegistry] Max active principles reached (%d), skipping", active_count)
            return None

        # Build existing principles text for dedup
        existing_text = self._format_existing_principles()

        prompt = GENESIS_PROMPT.format(
            evidence=evidence[:3000],
            existing_axioms=existing_axioms_text[:2000] or "(not provided)",
            existing_principles=existing_text[:2000] or "(none yet)",
            brier_score=performance_data.get("brier_score", "N/A"),
            avg_integrity=performance_data.get("avg_integrity", "N/A"),
            calibration_error=performance_data.get("calibration_error", "N/A"),
            failure_patterns=json.dumps(
                performance_data.get("failure_patterns", [])[:5],
                ensure_ascii=False,
            ),
        )

        try:
            result = self.llm.call_json(
                system_prompt=prompt,
                user_prompt="Analyze the evidence and decide whether a new operating principle is warranted.",
                max_tokens=4096,
                temperature=0.3,
                thinking=False,
            )
        except Exception as e:
            logger.warning("[PrincipleRegistry] Discovery LLM call failed: %s", e)
            return None

        elapsed = time.perf_counter() - t0

        if not result.get("principle_needed"):
            logger.info(
                "[PrincipleRegistry] No principle needed (%.2fs): %s",
                elapsed, result.get("reasoning", ""),
            )
            self._journal({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "discovery_skip",
                "reasoning": result.get("reasoning", ""),
                "elapsed": round(elapsed, 2),
            })
            return None

        # Extract principle data
        p_data = result.get("principle", {})
        if not p_data:
            return None

        principle_text = p_data.get("principle_text", "")
        if not principle_text or len(principle_text) > MAX_PRINCIPLE_CHARS:
            logger.warning("[PrincipleRegistry] Principle text empty or too long")
            return None

        # Check for semantic duplicates among existing principles
        if self._is_duplicate(principle_text):
            logger.info("[PrincipleRegistry] Duplicate principle detected, skipping")
            return None

        # Create the principle
        principle_id = f"DP-{self._next_id:03d}"
        self._next_id += 1

        principle = DynamicPrinciple(
            id=principle_id,
            title=p_data.get("title", "Untitled"),
            principle_text=principle_text,
            procedure=p_data.get("procedure", "")[:500],
            domain=p_data.get("domain", "META"),
            trigger_conditions=p_data.get("trigger_conditions", []),
            non_applicable_conditions=p_data.get("non_applicable_conditions", []),
            applies_to_phases=p_data.get("applies_to_phases", []),
            evidence=[{
                "source": "auto_discovery",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "summary": evidence[:500],
            }],
            expected_effect=p_data.get("expected_effect", ""),
            measurement_metric=p_data.get("measurement_metric", ""),
            status="proposed",
            created_at=datetime.now(timezone.utc).isoformat(),
            born_from=p_data.get("born_from", "introspection"),
            born_from_pattern=p_data.get("born_from_pattern", ""),
            related_axiom=p_data.get("related_axiom", ""),
        )

        self._principles[principle_id] = principle
        self._save()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "discovery",
            "principle_id": principle_id,
            "title": principle.title,
            "domain": principle.domain,
            "principle_text": principle.principle_text,
            "confidence": result.get("confidence", 0),
            "elapsed": round(elapsed, 2),
        })

        logger.info(
            "[PrincipleRegistry] NEW PRINCIPLE proposed: %s — %s (%.2fs)",
            principle_id, principle.title, elapsed,
        )

        if callback:
            callback("principle_proposed", {
                "id": principle_id,
                "title": principle.title,
                "principle_text": principle.principle_text,
                "domain": principle.domain,
                "status": "proposed — awaiting approval",
            })

        return principle

    # ──────────────────────────────────────────────────────────
    #  APPROVE / REJECT
    # ──────────────────────────────────────────────────────────

    def approve(self, principle_id: str, approved_by: str = "human") -> dict:
        """Approve a proposed principle — makes it active."""
        if principle_id not in self._principles:
            return {"error": "Principle not found"}

        p = self._principles[principle_id]
        if p.status != "proposed":
            return {"error": f"Principle must be 'proposed', is '{p.status}'"}

        p.status = "active"
        p.activated_at = datetime.now(timezone.utc).isoformat()
        p.approved_by = approved_by
        self._save()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "approval",
            "principle_id": principle_id,
            "approved_by": approved_by,
        })

        logger.info("[PrincipleRegistry] ✓ ACTIVATED principle %s: %s", principle_id, p.title)
        return {"status": "active", "principle_id": principle_id, "title": p.title}

    def reject(self, principle_id: str, reason: str = "") -> dict:
        """Reject a proposed principle."""
        if principle_id not in self._principles:
            return {"error": "Principle not found"}

        p = self._principles[principle_id]
        p.status = "retired"
        p.retired_at = datetime.now(timezone.utc).isoformat()
        p.retirement_reason = reason or "Rejected by human"
        self._save()

        self._journal({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "rejection",
            "principle_id": principle_id,
            "reason": reason,
        })

        logger.info("[PrincipleRegistry] ✗ REJECTED principle %s: %s", principle_id, reason)
        return {"status": "retired", "principle_id": principle_id}

    # ──────────────────────────────────────────────────────────
    #  TRACK — Record effectiveness after application
    # ──────────────────────────────────────────────────────────

    def record_application(
        self,
        principle_id: str,
        run_number: int,
        problem: str,
        phase: str,
        quality_indicators: dict,
    ) -> float | None:
        """Record that a principle was applied and evaluate its effectiveness.

        Returns effectiveness score, or None if evaluation failed.
        """
        if principle_id not in self._principles:
            return None

        p = self._principles[principle_id]
        if p.status not in ("active", "strengthened"):
            return None

        p.application_count += 1

        # LLM evaluates effectiveness
        try:
            prompt = EFFECTIVENESS_PROMPT.format(
                title=p.title,
                principle_text=p.principle_text,
                procedure=p.procedure,
                domain=p.domain,
                problem=problem[:500],
                phase=phase,
                quality_indicators=json.dumps(quality_indicators, ensure_ascii=False)[:1000],
            )

            result = self.llm.call_json(
                system_prompt=prompt,
                user_prompt="Evaluate the principle's effectiveness for this run.",
                max_tokens=256,
                temperature=0.2,
                thinking=False,
            )

            score = float(result.get("score", 0.5))
            score = max(0.0, min(1.0, score))

        except Exception as e:
            logger.warning("[PrincipleRegistry] Effectiveness eval failed: %s", e)
            score = 0.5  # Neutral on failure

        p.effectiveness_scores.append(score)

        # Trim history
        if len(p.effectiveness_scores) > MAX_HISTORY_PER_PRINCIPLE:
            p.effectiveness_scores = p.effectiveness_scores[-MAX_HISTORY_PER_PRINCIPLE:]

        p.application_history.append({
            "run": run_number,
            "score": score,
            "phase": phase,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(p.application_history) > MAX_HISTORY_PER_PRINCIPLE:
            p.application_history = p.application_history[-MAX_HISTORY_PER_PRINCIPLE:]

        # Check for auto-strengthen or auto-retire
        if p.should_strengthen and p.status == "active":
            p.status = "strengthened"
            logger.info(
                "[PrincipleRegistry] ★ STRENGTHENED %s (avg=%.2f after %d uses)",
                principle_id, p.avg_effectiveness, p.application_count,
            )
        elif p.should_retire:
            p.status = "weakened"
            logger.warning(
                "[PrincipleRegistry] ⚠ WEAKENED %s (avg=%.2f after %d uses) — may retire soon",
                principle_id, p.avg_effectiveness, p.application_count,
            )

        self._save()
        return score

    def auto_retire(self) -> list[str]:
        """Auto-retire principles that consistently underperform.

        Returns list of retired principle IDs.
        """
        retired = []
        for pid, p in self._principles.items():
            if p.status in ("active", "weakened") and p.should_retire:
                p.status = "retired"
                p.retired_at = datetime.now(timezone.utc).isoformat()
                p.retirement_reason = f"Auto-retired: avg effectiveness {p.avg_effectiveness:.2f} < {RETIREMENT_THRESHOLD}"
                retired.append(pid)

                self._journal({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "auto_retirement",
                    "principle_id": pid,
                    "avg_effectiveness": p.avg_effectiveness,
                    "application_count": p.application_count,
                })

                logger.info(
                    "[PrincipleRegistry] AUTO-RETIRED %s: %s (avg=%.2f, uses=%d)",
                    pid, p.title, p.avg_effectiveness, p.application_count,
                )

        if retired:
            self._save()
        return retired

    # ──────────────────────────────────────────────────────────
    #  QUERY — For pipeline injection and API
    # ──────────────────────────────────────────────────────────

    def get_active_for_phase(self, phase: str, domain: str | None = None) -> list[DynamicPrinciple]:
        """Get active principles applicable to a specific phase.

        Args:
            phase: Pipeline phase name (e.g. "ontology", "scenario_genesis")
            domain: If given, filter by domain too

        Returns:
            List of matching active principles, sorted by avg effectiveness (desc)
        """
        results = []
        for p in self._principles.values():
            if p.status not in ("active", "strengthened"):
                continue
            if phase in p.applies_to_phases:
                if domain and p.domain != domain and p.domain != "META" and p.domain != "EPISTEMIC":
                    continue
                results.append(p)

        # Sort: strengthened first, then by effectiveness
        def sort_key(p):
            avg = p.avg_effectiveness or 0.5
            boost = 0.1 if p.status == "strengthened" else 0
            return -(avg + boost)

        results.sort(key=sort_key)
        return results

    def format_for_prompt(self, phase: str, domain: str | None = None) -> str:
        """Format active principles as text for injection into LLM prompts.

        Returns empty string if no applicable principles.
        """
        principles = self.get_active_for_phase(phase, domain)
        if not principles:
            return ""

        lines = ["\n=== DYNAMIC OPERATING PRINCIPLES (learned from experience) ===\n"]

        for p in principles:
            strength = "★" if p.status == "strengthened" else ""
            avg = f" (effectiveness: {p.avg_effectiveness:.0%})" if p.avg_effectiveness is not None else ""
            lines.append(f"[{p.id}] {strength}{p.title}{avg}")
            lines.append(f"  Principle: {p.principle_text}")
            lines.append(f"  Procedure: {p.procedure}")
            lines.append(f"  Applies when: {', '.join(p.trigger_conditions)}")
            lines.append(f"  Does NOT apply when: {', '.join(p.non_applicable_conditions)}")
            lines.append("")

        return "\n".join(lines)

    def get_all(self, include_retired: bool = False) -> list[dict]:
        """Get all principles for API display."""
        results = []
        for p in self._principles.values():
            if not include_retired and p.status == "retired":
                continue
            results.append(p.to_dict())
        return sorted(results, key=lambda x: x.get("created_at", ""), reverse=True)

    def get_stats(self) -> dict:
        """Summary statistics."""
        total = len(self._principles)
        active = sum(1 for p in self._principles.values() if p.status == "active")
        strengthened = sum(1 for p in self._principles.values() if p.status == "strengthened")
        proposed = sum(1 for p in self._principles.values() if p.status == "proposed")
        retired = sum(1 for p in self._principles.values() if p.status == "retired")
        weakened = sum(1 for p in self._principles.values() if p.status == "weakened")

        avg_effectiveness_all = None
        scored = [p.avg_effectiveness for p in self._principles.values()
                  if p.avg_effectiveness is not None and p.status in ("active", "strengthened")]
        if scored:
            avg_effectiveness_all = sum(scored) / len(scored)

        return {
            "total": total,
            "active": active,
            "strengthened": strengthened,
            "proposed": proposed,
            "weakened": weakened,
            "retired": retired,
            "avg_effectiveness": avg_effectiveness_all,
            "pending_approval": proposed,
        }

    def get_pending_approvals(self) -> list[dict]:
        """Get principles awaiting human approval."""
        return [
            p.to_dict() for p in self._principles.values()
            if p.status == "proposed"
        ]

    # ──────────────────────────────────────────────────────────
    #  INTERNAL — Dedup and formatting
    # ──────────────────────────────────────────────────────────

    def _is_duplicate(self, principle_text: str) -> bool:
        """Check if a principle is semantically too similar to existing ones.

        Uses simple keyword overlap (no embedding call needed).
        """
        new_words = set(principle_text.lower().split())

        for p in self._principles.values():
            if p.status == "retired":
                continue
            existing_words = set(p.principle_text.lower().split())
            if not existing_words or not new_words:
                continue

            # Jaccard similarity
            overlap = len(new_words & existing_words)
            union = len(new_words | existing_words)
            if union > 0 and overlap / union > 0.6:
                logger.info(
                    "[PrincipleRegistry] Duplicate detected: %.2f overlap with %s",
                    overlap / union, p.id,
                )
                return True

        return False

    def _format_existing_principles(self) -> str:
        """Format existing principles for the discovery prompt."""
        active = [p for p in self._principles.values() if p.status in ("active", "strengthened", "proposed")]
        if not active:
            return "(no dynamic principles yet)"

        lines = []
        for p in active:
            lines.append(f"[{p.id}] {p.title}: {p.principle_text} (domain: {p.domain})")
        return "\n".join(lines)

    def to_context_string(self) -> str:
        """Full context for self-evolution prompt."""
        stats = self.get_stats()
        lines = [
            f"Dynamic Principle Registry: {stats['active']} active, "
            f"{stats['strengthened']} strengthened, {stats['proposed']} proposed",
        ]

        for p in self._principles.values():
            if p.status in ("active", "strengthened"):
                avg = f" (avg={p.avg_effectiveness:.2f})" if p.avg_effectiveness is not None else ""
                lines.append(f"  [{p.id}] {p.title}{avg}: {p.principle_text[:100]}...")

        return "\n".join(lines)
