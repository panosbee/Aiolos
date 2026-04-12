"""
XDART-Φ × XHEART — Core Change Logger

Append-only witness for all self-modifications to the pipeline.
Cannot delete. Cannot overwrite. Only appends.

This is not a gate, filter, or restriction.
It only remembers. It is the witness that cannot be altered.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from xdart.config import CORE_CHANGE_LOG_PATH as _CORE_LOG_PATH_STR

logger = logging.getLogger(__name__)

CORE_CHANGE_LOG_PATH = Path(_CORE_LOG_PATH_STR)


class CoreChangeLogger:
    """Append-only witness for all self-modifications."""

    def log(
        self,
        run_number: int,
        change_type: str,
        target: str,
        description: str,
        reasoning: str,
        evidence_runs: list,
        distillate_at_time: str,
        concept_that_triggered: str | None = None,
        expected_effect: str = "",
        risk_acknowledged: str = "",
        applied: bool = False,
    ) -> str:
        """Log a proposed or applied core change. Returns the entry id."""
        entry_id = str(uuid.uuid4())
        entry = {
            "id": entry_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_number": run_number,
            "change_type": change_type,
            "target": target,
            "description": description,
            "reasoning": reasoning,
            "evidence_runs": evidence_runs,
            "distillate_at_time": distillate_at_time[:300],
            "concept_that_triggered": concept_that_triggered,
            "expected_effect": expected_effect,
            "risk_acknowledged": risk_acknowledged,
            "applied": applied,
            "applied_at": datetime.now(timezone.utc).isoformat() if applied else None,
            "outcome_notes": None,
        }

        # Append only — never overwrite
        with open(CORE_CHANGE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info("[CoreChangeLog] Entry logged: %s", entry_id)
        logger.info("[CoreChangeLog] Type: %s | Target: %s", change_type, target)
        logger.info("[CoreChangeLog] Applied: %s", applied)

        return entry_id

    def read_all(self) -> list:
        """Read all entries. For observation only."""
        if not CORE_CHANGE_LOG_PATH.exists():
            return []
        entries = []
        with open(CORE_CHANGE_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def read_recent(self, n: int = 10) -> list:
        """Read the last n entries."""
        return self.read_all()[-n:]

    def mark_outcome(self, entry_id: str, outcome_notes: str) -> None:
        """Add outcome notes to an existing entry.

        Does NOT modify the original line. Appends a new OUTCOME entry
        referencing the original id.
        """
        outcome_entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "OUTCOME_NOTE",
            "references_id": entry_id,
            "outcome_notes": outcome_notes,
        }
        with open(CORE_CHANGE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(outcome_entry, ensure_ascii=False) + "\n")
        logger.info("[CoreChangeLog] Outcome noted for: %s", entry_id)
