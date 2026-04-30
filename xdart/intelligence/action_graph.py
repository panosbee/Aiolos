"""
XDART-Φ Palantir Upgrade — Βήμα 2: Intelligence Action Graph
=============================================================

Implements the analysis → decision → action → outcome feedback loop.

Every significant intelligence event (fired pattern, briefing, confirmed hypothesis)
creates an AnalysisRecord. The system auto-generates 2-3 DecisionRecords via LLM,
each producing 1-2 ActionRecords (concrete next steps: research, alert, monitor, brief).
Outcomes are logged when subsequent signals confirm or deny the analysis.

This creates a closed-loop intelligence cycle that learns whether its decisions
were correct — and feeds accuracy stats back into briefing confidence.

Integration points:
  - PatternAccumulator: record_analysis() called on each high-confidence pattern fire
  - ScheduledBriefingEngine: record_analysis() called after each briefing generation
  - HypothesisEngine: record_analysis() on hypothesis confirmation
  - ProactiveEngine: pending actions injected into notification context
  - Briefing context: get_action_digest() → assembled into daily brief
  - MongoDB: intelligence_actions collection for persistence

REST API:
  GET  /xdart/actions/pending
  GET  /xdart/actions/history?n=20
  POST /xdart/actions/{action_id}/execute
  POST /xdart/actions/{action_id}/outcome
  GET  /xdart/actions/stats
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xdart.llm import LLMClient

logger = logging.getLogger("xdart.intelligence.action_graph")

# ─────────────────────────────────────────────────────────────────────────────
#  ENUMERATIONS
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisTrigger(str, Enum):
    PATTERN             = "pattern"
    BRIEFING            = "briefing"
    HYPOTHESIS_CONFIRM  = "hypothesis_confirmed"
    MANUAL              = "manual"
    COMPOUND_ALERT      = "compound_alert"


class DecisionType(str, Enum):
    MONITOR     = "monitor"       # watch and accumulate more signals
    RESEARCH    = "research"      # deep-dive web research
    ALERT       = "alert"         # immediate push notification
    BRIEF       = "brief"         # generate a focused intelligence brief
    ESCALATE    = "escalate"      # raise priority level
    STAND_BY    = "stand_by"      # do nothing — situation is under control


class ActionStatus(str, Enum):
    PENDING     = "pending"
    EXECUTING   = "executing"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"
    FAILED      = "failed"


class OutcomeType(str, Enum):
    CONFIRMED   = "confirmed"     # situation developed as predicted
    PARTIAL     = "partial"       # partial confirmation
    DENIED      = "denied"        # prediction was wrong
    UNKNOWN     = "unknown"       # insufficient evidence
    PENDING     = "pending"       # not yet resolved


# ─────────────────────────────────────────────────────────────────────────────
#  LLM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

_DECISION_GENERATION_PROMPT = """You are the Intelligence Decision Engine for XDART-Φ.

Given an intelligence analysis, generate 2-3 strategic decisions that Αίολος should make.
Each decision MUST:
  - Be directly actionable (not vague)
  - Map to one of: monitor / research / alert / brief / escalate / stand_by
  - Have a clear, specific rationale
  - Include a priority (1=critical, 2=high, 3=medium)

Intelligence Analysis:
  Trigger: {trigger_type} — {trigger_summary}
  Situation: {situation}
  Key entities: {entities}
  Domains: {domains}
  Confidence: {confidence}

Respond ONLY with valid JSON array of decisions:
[
  {{
    "decision_type": "monitor|research|alert|brief|escalate|stand_by",
    "rationale": "specific reason why this is the right decision",
    "action_description": "concrete action to take (e.g., 'Monitor VIX and gold spread for correlation with Iran-Israel escalation signals for next 48h')",
    "parameters": {{"key": "value"}},
    "priority": 1,
    "confidence": 0.75
  }}
]
Output only the JSON array — no explanation."""


# ─────────────────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisRecord:
    """Intelligence analysis derived from a trigger event."""
    id: str
    trigger_type: str                    # AnalysisTrigger value
    trigger_id: str                      # ID of triggering object
    trigger_summary: str                 # One-line summary of trigger
    situation_summary: str               # Αίολος's assessment of the situation
    key_entities: list[str]
    domains: list[str]
    confidence: float
    timestamp: float
    decision_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DecisionRecord:
    """Strategic decision derived from an analysis."""
    id: str
    analysis_id: str
    decision_type: str                   # DecisionType value
    rationale: str
    action_description: str
    parameters: dict
    priority: int                        # 1=critical, 2=high, 3=medium
    confidence: float
    generated_at: float
    action_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ActionRecord:
    """Concrete action derived from a decision."""
    id: str
    decision_id: str
    analysis_id: str
    action_type: str                     # mirrors decision_type
    description: str
    parameters: dict
    status: str                          # ActionStatus value
    priority: int
    created_at: float
    executed_at: float | None = None
    result: str = ""
    outcome_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class OutcomeRecord:
    """Observed outcome for a completed action cycle."""
    id: str
    action_id: str
    analysis_id: str
    outcome_type: str                    # OutcomeType value
    observed_at: float
    evidence: str                        # what signal confirmed/denied the prediction
    impact_score: float                  # 0.0-1.0 actual impact of the event

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────────────────────────────────────
#  INTELLIGENCE ACTION GRAPH ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class IntelligenceActionGraph:
    """
    Closed-loop intelligence cycle: analysis → decision → action → outcome.

    Every triggered event creates an analysis. The LLM generates decisions.
    Actions are created and tracked. Outcomes close the loop and build
    predictive accuracy metrics over time.
    """

    _HISTORY_FILE     = "action_graph.json"
    _OUTCOMES_FILE    = "action_outcomes.jsonl"
    _AUTO_RESOLVE_INTERVAL = 10 * 60   # 10 minutes
    _MAX_ANALYSES     = 200            # keep last N analyses in memory
    _ACTION_AUTO_EXPIRE = 72 * 3600   # auto-expire PENDING actions after 72h
    _LLM_COOLDOWN     = 300           # min 5 min between LLM decision calls per trigger type

    def __init__(
        self,
        llm: "LLMClient | None" = None,
        proactive_engine=None,
        mongo=None,
        persist_path: str | Path | None = None,
    ):
        self._llm = llm
        self._proactive_engine = proactive_engine
        self._mongo = mongo

        base = Path(persist_path) if persist_path else Path(".")
        self._history_path = base / self._HISTORY_FILE
        self._outcomes_path = base / self._OUTCOMES_FILE

        # Core stores
        self._analyses:      dict[str, AnalysisRecord]  = {}
        self._decisions:     dict[str, DecisionRecord]  = {}
        self._actions:       dict[str, ActionRecord]    = {}
        self._outcomes:      dict[str, OutcomeRecord]   = {}

        # LLM call rate limiting per trigger type
        self._last_llm_call: dict[str, float] = {}

        # Threading
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._resolve_thread: threading.Thread | None = None

        # Stats
        self._total_analyses   = 0
        self._total_decisions  = 0
        self._total_actions    = 0
        self._total_outcomes   = 0

        self._load()
        logger.info(
            "[ActionGraph] Ready — %d analyses, %d actions (%d pending)",
            len(self._analyses),
            len(self._actions),
            sum(1 for a in self._actions.values() if a.status == ActionStatus.PENDING.value),
        )

    # ─────────────────────────────────────────────────────────────
    #  STARTUP / SHUTDOWN
    # ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background auto-resolve thread."""
        self._resolve_thread = threading.Thread(
            target=self._auto_resolve_loop,
            name="action-graph-resolve",
            daemon=True,
        )
        self._resolve_thread.start()
        logger.info("[ActionGraph] Background resolve thread started")

    def stop(self) -> None:
        """Stop background thread and save."""
        self._stop_event.set()
        self._save()

    # ─────────────────────────────────────────────────────────────
    #  CORE API — RECORD ANALYSIS
    # ─────────────────────────────────────────────────────────────

    def record_analysis(
        self,
        trigger_type: AnalysisTrigger | str,
        trigger_id: str,
        trigger_summary: str,
        situation_summary: str,
        key_entities: list[str] | None = None,
        domains: list[str] | None = None,
        confidence: float = 0.5,
    ) -> AnalysisRecord:
        """
        Record a new intelligence analysis.
        Auto-generates decisions via LLM (rate-limited).
        """
        if isinstance(trigger_type, AnalysisTrigger):
            trigger_type = trigger_type.value

        analysis = AnalysisRecord(
            id=str(uuid.uuid4()),
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            trigger_summary=trigger_summary[:300],
            situation_summary=situation_summary[:1000],
            key_entities=(key_entities or [])[:10],
            domains=(domains or [])[:5],
            confidence=confidence,
            timestamp=time.time(),
        )

        with self._lock:
            self._analyses[analysis.id] = analysis
            self._total_analyses += 1
            # Enforce memory limit
            if len(self._analyses) > self._MAX_ANALYSES:
                oldest_ids = sorted(
                    self._analyses.keys(),
                    key=lambda aid: self._analyses[aid].timestamp,
                )[:20]
                for old_id in oldest_ids:
                    del self._analyses[old_id]

        logger.info("[ActionGraph] Analysis recorded: %s — %s", trigger_type, trigger_summary[:80])

        # Auto-generate decisions (rate limited)
        last_call = self._last_llm_call.get(trigger_type, 0.0)
        if time.time() - last_call >= self._LLM_COOLDOWN:
            self._generate_decisions(analysis)
            self._last_llm_call[trigger_type] = time.time()
        else:
            # Still create a default monitoring action without LLM
            self._create_default_action(analysis)

        # Persist + MongoDB
        self._save()
        self._write_to_mongo(analysis)

        return analysis

    # ─────────────────────────────────────────────────────────────
    #  LLM DECISION GENERATION
    # ─────────────────────────────────────────────────────────────

    def _generate_decisions(self, analysis: AnalysisRecord) -> None:
        """Call LLM to generate strategic decisions for an analysis."""
        if not self._llm:
            self._create_default_action(analysis)
            return

        try:
            prompt = _DECISION_GENERATION_PROMPT.format(
                trigger_type=analysis.trigger_type,
                trigger_summary=analysis.trigger_summary,
                situation=analysis.situation_summary[:600],
                entities=", ".join(analysis.key_entities[:5]) or "N/A",
                domains=", ".join(analysis.domains) or "general",
                confidence=f"{analysis.confidence:.0%}",
            )

            raw = self._llm.call_json(
                system=prompt,
                user="Generate decisions for this intelligence analysis.",
                temperature=0.3,
                max_tokens=800,
            )

            decisions_data = raw if isinstance(raw, list) else raw.get("decisions", [])
            if not isinstance(decisions_data, list):
                decisions_data = [decisions_data]

            for d_raw in decisions_data[:3]:
                if not isinstance(d_raw, dict):
                    continue
                try:
                    decision = DecisionRecord(
                        id=str(uuid.uuid4()),
                        analysis_id=analysis.id,
                        decision_type=d_raw.get("decision_type", "monitor"),
                        rationale=str(d_raw.get("rationale", ""))[:500],
                        action_description=str(d_raw.get("action_description", ""))[:500],
                        parameters=d_raw.get("parameters", {}),
                        priority=int(d_raw.get("priority", 3)),
                        confidence=float(d_raw.get("confidence", 0.5)),
                        generated_at=time.time(),
                    )
                    with self._lock:
                        self._decisions[decision.id] = decision
                        analysis.decision_ids.append(decision.id)
                        self._total_decisions += 1

                    self._create_action_from_decision(decision, analysis)

                except Exception as exc:
                    logger.debug("[ActionGraph] Decision parse error: %s — %s", exc, d_raw)

            logger.info(
                "[ActionGraph] Generated %d decisions for analysis %s",
                len(analysis.decision_ids), analysis.id[:8],
            )

        except Exception as exc:
            logger.warning("[ActionGraph] Decision generation failed: %s", exc)
            self._create_default_action(analysis)

    def _create_action_from_decision(
        self,
        decision: DecisionRecord,
        analysis: AnalysisRecord,
    ) -> ActionRecord:
        """Create an ActionRecord from a DecisionRecord."""
        action = ActionRecord(
            id=str(uuid.uuid4()),
            decision_id=decision.id,
            analysis_id=analysis.id,
            action_type=decision.decision_type,
            description=decision.action_description,
            parameters=decision.parameters,
            status=ActionStatus.PENDING.value,
            priority=decision.priority,
            created_at=time.time(),
        )

        with self._lock:
            self._actions[action.id] = action
            decision.action_ids.append(action.id)
            self._total_actions += 1

        return action

    def _create_default_action(self, analysis: AnalysisRecord) -> None:
        """Create a default MONITOR action when LLM is unavailable or rate-limited."""
        action = ActionRecord(
            id=str(uuid.uuid4()),
            decision_id="",
            analysis_id=analysis.id,
            action_type=DecisionType.MONITOR.value,
            description=f"Monitor developments related to: {analysis.trigger_summary[:200]}",
            parameters={"auto_generated": True, "cooldown_active": True},
            status=ActionStatus.PENDING.value,
            priority=3,
            created_at=time.time(),
        )
        with self._lock:
            self._actions[action.id] = action
            self._total_actions += 1

    # ─────────────────────────────────────────────────────────────
    #  ACTION MANAGEMENT
    # ─────────────────────────────────────────────────────────────

    def mark_action_executed(self, action_id: str, result: str = "") -> bool:
        """Mark an action as executed."""
        with self._lock:
            action = self._actions.get(action_id)
            if not action:
                return False
            action.status = ActionStatus.COMPLETED.value
            action.executed_at = time.time()
            action.result = result[:500]
        self._save()
        return True

    def cancel_action(self, action_id: str) -> bool:
        """Cancel a pending action."""
        with self._lock:
            action = self._actions.get(action_id)
            if not action or action.status != ActionStatus.PENDING.value:
                return False
            action.status = ActionStatus.CANCELLED.value
        self._save()
        return True

    def record_outcome(
        self,
        action_id: str,
        outcome_type: OutcomeType | str,
        evidence: str,
        impact_score: float = 0.5,
    ) -> OutcomeRecord | None:
        """Record an observed outcome for an action."""
        with self._lock:
            action = self._actions.get(action_id)
            if not action:
                return None

            outcome = OutcomeRecord(
                id=str(uuid.uuid4()),
                action_id=action_id,
                analysis_id=action.analysis_id,
                outcome_type=outcome_type.value if isinstance(outcome_type, OutcomeType) else outcome_type,
                observed_at=time.time(),
                evidence=evidence[:500],
                impact_score=min(1.0, max(0.0, impact_score)),
            )

            self._outcomes[outcome.id] = outcome
            action.outcome_id = outcome.id
            if action.status == ActionStatus.PENDING.value:
                action.status = ActionStatus.COMPLETED.value
                action.executed_at = time.time()
            self._total_outcomes += 1

        self._append_outcome(outcome)
        self._save()
        logger.info("[ActionGraph] Outcome recorded: %s → %s", action_id[:8], outcome.outcome_type)
        return outcome

    # ─────────────────────────────────────────────────────────────
    #  QUERY INTERFACE
    # ─────────────────────────────────────────────────────────────

    def get_pending_actions(self, limit: int = 10) -> list[dict]:
        """Return pending actions sorted by priority."""
        with self._lock:
            pending = [
                a.to_dict() for a in self._actions.values()
                if a.status == ActionStatus.PENDING.value
            ]
        pending.sort(key=lambda x: x["priority"])
        return pending[:limit]

    def get_recent_analyses(self, n: int = 20) -> list[dict]:
        """Return the N most recent analysis records."""
        with self._lock:
            sorted_analyses = sorted(
                self._analyses.values(),
                key=lambda a: -a.timestamp,
            )[:n]
        return [a.to_dict() for a in sorted_analyses]

    def get_cycle_stats(self) -> dict:
        """
        Prediction accuracy and completion stats for the action graph.
        """
        with self._lock:
            total_outcomes = len(self._outcomes)
            if total_outcomes == 0:
                accuracy = None
            else:
                confirmed = sum(
                    1 for o in self._outcomes.values()
                    if o.outcome_type in (OutcomeType.CONFIRMED.value, OutcomeType.PARTIAL.value)
                )
                accuracy = round(confirmed / total_outcomes, 3)

            pending_count = sum(1 for a in self._actions.values() if a.status == ActionStatus.PENDING.value)
            completed_count = sum(1 for a in self._actions.values() if a.status == ActionStatus.COMPLETED.value)

            # Average impact of confirmed outcomes
            confirmed_outcomes = [
                o for o in self._outcomes.values()
                if o.outcome_type in (OutcomeType.CONFIRMED.value, OutcomeType.PARTIAL.value)
            ]
            avg_impact = (
                round(sum(o.impact_score for o in confirmed_outcomes) / len(confirmed_outcomes), 3)
                if confirmed_outcomes else 0.0
            )

            return {
                "total_analyses":  self._total_analyses,
                "total_decisions": self._total_decisions,
                "total_actions":   self._total_actions,
                "total_outcomes":  self._total_outcomes,
                "pending_actions": pending_count,
                "completed_actions": completed_count,
                "prediction_accuracy": accuracy,
                "avg_confirmed_impact": avg_impact,
                "active_analyses_in_memory": len(self._analyses),
            }

    def get_action_digest(self, max_items: int = 5) -> str:
        """
        Compact text digest of pending high-priority actions for briefing/chat injection.
        """
        pending = self.get_pending_actions(limit=max_items)
        if not pending:
            return "⚡ INTELLIGENCE ACTION GRAPH: No pending actions."

        lines = [f"⚡ INTELLIGENCE ACTION GRAPH — {len(pending)} pending actions\n"]
        for i, action in enumerate(pending, 1):
            analysis = self._analyses.get(action["analysis_id"])
            ctx = analysis.trigger_summary[:80] if analysis else "unknown trigger"
            lines.append(
                f"[{i}] [{action['action_type'].upper()}] P{action['priority']} — "
                f"{action['description'][:120]}\n"
                f"    Triggered by: {ctx}"
            )

        stats = self.get_cycle_stats()
        if stats["prediction_accuracy"] is not None:
            lines.append(
                f"\nAccuracy: {stats['prediction_accuracy']:.0%} "
                f"({stats['total_outcomes']} outcomes logged)"
            )

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    #  AUTO-RESOLVE BACKGROUND LOOP
    # ─────────────────────────────────────────────────────────────

    def _auto_resolve_loop(self) -> None:
        """Background: expire stale pending actions + auto-mark outcomes."""
        while not self._stop_event.wait(timeout=self._AUTO_RESOLVE_INTERVAL):
            try:
                self._expire_stale_actions()
                self._save()
            except Exception as exc:
                logger.warning("[ActionGraph] Auto-resolve error: %s", exc)

    def _expire_stale_actions(self) -> int:
        """Auto-cancel PENDING actions older than AUTO_EXPIRE window."""
        now = time.time()
        expired = 0
        with self._lock:
            for action in self._actions.values():
                if action.status == ActionStatus.PENDING.value:
                    age = now - action.created_at
                    if age > self._ACTION_AUTO_EXPIRE:
                        action.status = ActionStatus.CANCELLED.value
                        expired += 1
        if expired:
            logger.info("[ActionGraph] Auto-expired %d stale actions", expired)
        return expired

    # ─────────────────────────────────────────────────────────────
    #  PERSISTENCE
    # ─────────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Save analyses, decisions, actions to JSON."""
        try:
            with self._lock:
                state = {
                    "version": 1,
                    "saved_at": time.time(),
                    "analyses":  {k: v.to_dict() for k, v in self._analyses.items()},
                    "decisions": {k: v.to_dict() for k, v in self._decisions.items()},
                    "actions":   {k: v.to_dict() for k, v in self._actions.items()},
                    "outcomes":  {k: v.to_dict() for k, v in self._outcomes.items()},
                    "stats": {
                        "total_analyses":  self._total_analyses,
                        "total_decisions": self._total_decisions,
                        "total_actions":   self._total_actions,
                        "total_outcomes":  self._total_outcomes,
                    },
                }
            self._history_path.write_text(
                json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[ActionGraph] Save failed: %s", exc)

    def _load(self) -> None:
        """Load state from JSON on startup."""
        if not self._history_path.exists():
            return
        try:
            raw = json.loads(self._history_path.read_text(encoding="utf-8"))
            with self._lock:
                for k, d in raw.get("analyses", {}).items():
                    try:
                        self._analyses[k] = AnalysisRecord.from_dict(d)
                    except Exception:
                        pass
                for k, d in raw.get("decisions", {}).items():
                    try:
                        self._decisions[k] = DecisionRecord.from_dict(d)
                    except Exception:
                        pass
                for k, d in raw.get("actions", {}).items():
                    try:
                        self._actions[k] = ActionRecord.from_dict(d)
                    except Exception:
                        pass
                for k, d in raw.get("outcomes", {}).items():
                    try:
                        self._outcomes[k] = OutcomeRecord.from_dict(d)
                    except Exception:
                        pass

                stored_stats = raw.get("stats", {})
                self._total_analyses  = stored_stats.get("total_analyses", len(self._analyses))
                self._total_decisions = stored_stats.get("total_decisions", len(self._decisions))
                self._total_actions   = stored_stats.get("total_actions", len(self._actions))
                self._total_outcomes  = stored_stats.get("total_outcomes", len(self._outcomes))

            logger.info(
                "[ActionGraph] Loaded: %d analyses, %d decisions, %d actions, %d outcomes",
                len(self._analyses), len(self._decisions),
                len(self._actions), len(self._outcomes),
            )
        except Exception as exc:
            logger.warning("[ActionGraph] Load failed (starting fresh): %s", exc)

    def _append_outcome(self, outcome: OutcomeRecord) -> None:
        """Append outcome record to JSONL file."""
        try:
            with self._outcomes_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(outcome.to_dict(), ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("[ActionGraph] Outcome append failed: %s", exc)

    def _write_to_mongo(self, analysis: AnalysisRecord) -> None:
        """Dual-write analysis to MongoDB (fire and forget)."""
        if not self._mongo:
            return
        try:
            doc = analysis.to_dict()
            doc["_type"] = "intelligence_analysis"
            self._mongo.store_model(
                collection="intelligence_actions",
                model_id=analysis.id,
                data=doc,
            )
        except Exception:
            pass  # MongoDB errors never block the cycle
