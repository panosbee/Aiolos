"""
XDART-Φ × XHEART — Workflow Scheduler

Provides persistent, autonomous workflow scheduling for Αίολος.

Capabilities:
  - Create interval-based workflows
  - Execute shell/python/API tasks on schedule
  - Persist workflow state to disk
  - Manual run/enable/disable/update/remove from chat tags
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("xdart.tools.workflow_scheduler")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_PATH = BASE_DIR / "workflow_scheduler_state.json"
JOURNAL_PATH = BASE_DIR / "workflow_scheduler_journal.jsonl"

TICK_SECONDS = 15


class WorkflowScheduler:
    """Persistent interval workflow scheduler."""

    def __init__(self, shell_executor=None, external_api=None, tick_seconds: int = TICK_SECONDS):
        self.shell_executor = shell_executor
        self.external_api = external_api
        self.tick_seconds = max(5, int(tick_seconds))
        self._lock = threading.Lock()
        self._state = self._load_state()
        self._runs = 0
        self._errors = 0
        self._boot_time = datetime.now(timezone.utc)

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="workflow-scheduler")
        self._thread.start()
        logger.info(
            "[WorkflowScheduler] Started (%d workflows, tick=%ss)",
            len(self._state.get("workflows", {})),
            self.tick_seconds,
        )

    # ── Dispatcher ──────────────────────────────────────────────────

    def execute_action(self, action: str, params: dict) -> dict:
        action = (action or "").strip().lower()
        handler = getattr(self, action, None)
        if not handler or action.startswith("_"):
            return {"success": False, "error": f"Unknown action: {action}"}

        try:
            result = handler(**params)
        except Exception as e:
            result = {"success": False, "error": str(e)}

        self._log(action, params, result)
        return result

    # ── Public actions ──────────────────────────────────────────────

    def create_workflow(
        self,
        name: str = "",
        kind: str = "shell",
        payload: str = "",
        interval_seconds: str = "300",
        enabled: str = "true",
        run_immediately: str = "false",
        **_,
    ) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        if kind not in ("shell", "python", "external_api"):
            return {"success": False, "error": "kind must be shell|python|external_api"}
        if not payload:
            return {"success": False, "error": "payload is required"}

        try:
            interval = max(10, int(float(interval_seconds)))
        except ValueError:
            return {"success": False, "error": "interval_seconds must be numeric"}

        now = datetime.now(timezone.utc)
        wf = {
            "name": name,
            "kind": kind,
            "payload": payload,
            "interval_seconds": interval,
            "enabled": enabled.lower() in ("true", "1", "yes"),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "next_run_at": now.isoformat(),
            "last_run_at": None,
            "last_success": None,
            "last_error": "",
            "run_count": 0,
        }

        with self._lock:
            self._state.setdefault("workflows", {})[name] = wf
            self._save_state_locked()

        result = {"success": True, "workflow": name, "kind": kind, "interval_seconds": interval}

        if run_immediately.lower() in ("true", "1", "yes"):
            run_res = self.run_workflow(name=name)
            result["run_immediately"] = run_res

        return result

    def list_workflows(self, **_) -> dict:
        with self._lock:
            workflows = list(self._state.get("workflows", {}).values())

        rows = []
        for wf in sorted(workflows, key=lambda x: x.get("name", "")):
            rows.append({
                "name": wf.get("name"),
                "kind": wf.get("kind"),
                "enabled": wf.get("enabled"),
                "interval_seconds": wf.get("interval_seconds"),
                "next_run_at": wf.get("next_run_at"),
                "last_run_at": wf.get("last_run_at"),
                "last_success": wf.get("last_success"),
                "run_count": wf.get("run_count", 0),
            })
        return {"success": True, "count": len(rows), "workflows": rows}

    def get_workflow(self, name: str = "", **_) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        with self._lock:
            wf = self._state.get("workflows", {}).get(name)
            if not wf:
                return {"success": False, "error": f"workflow not found: {name}"}
            return {"success": True, "workflow": wf}

    def run_workflow(self, name: str = "", **_) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}

        with self._lock:
            wf = self._state.get("workflows", {}).get(name)
            if not wf:
                return {"success": False, "error": f"workflow not found: {name}"}

        run_res = self._execute_workflow(wf)
        return {"success": run_res.get("success", False), "workflow": name, "result": run_res}

    def set_enabled(self, name: str = "", enabled: str = "true", **_) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        en = enabled.lower() in ("true", "1", "yes")
        with self._lock:
            wf = self._state.get("workflows", {}).get(name)
            if not wf:
                return {"success": False, "error": f"workflow not found: {name}"}
            wf["enabled"] = en
            wf["updated_at"] = datetime.now(timezone.utc).isoformat()
            if en and not wf.get("next_run_at"):
                wf["next_run_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state_locked()
        return {"success": True, "workflow": name, "enabled": en}

    def set_interval(self, name: str = "", interval_seconds: str = "300", **_) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        try:
            interval = max(10, int(float(interval_seconds)))
        except ValueError:
            return {"success": False, "error": "interval_seconds must be numeric"}

        with self._lock:
            wf = self._state.get("workflows", {}).get(name)
            if not wf:
                return {"success": False, "error": f"workflow not found: {name}"}
            wf["interval_seconds"] = interval
            wf["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state_locked()
        return {"success": True, "workflow": name, "interval_seconds": interval}

    def remove_workflow(self, name: str = "", **_) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        with self._lock:
            workflows = self._state.get("workflows", {})
            if name not in workflows:
                return {"success": False, "error": f"workflow not found: {name}"}
            del workflows[name]
            self._save_state_locked()
        return {"success": True, "removed": name}

    def run_due(self, **_) -> dict:
        due_names = []
        now = datetime.now(timezone.utc)
        with self._lock:
            for name, wf in self._state.get("workflows", {}).items():
                if not wf.get("enabled", True):
                    continue
                next_run_at = self._parse_time(wf.get("next_run_at"))
                if next_run_at and next_run_at <= now:
                    due_names.append(name)

        results = []
        for name in due_names:
            results.append(self.run_workflow(name=name))

        return {"success": True, "due_count": len(due_names), "results": results}

    # ── Status ──────────────────────────────────────────────────────

    def to_context_string(self) -> str:
        with self._lock:
            workflows = list(self._state.get("workflows", {}).values())

        enabled_count = sum(1 for w in workflows if w.get("enabled"))
        lines = [
            "WORKFLOW SCHEDULER STATUS (autonomous interval workflows):",
            f"  Total workflows: {len(workflows)} (enabled: {enabled_count})",
            f"  Scheduler tick: {self.tick_seconds}s",
            f"  Format: <WORKFLOW action=\"create_workflow\" ... />",
        ]
        for wf in sorted(workflows, key=lambda x: x.get("name", ""))[:6]:
            lines.append(
                f"    - {wf.get('name')} [{wf.get('kind')}] every {wf.get('interval_seconds')}s"
                f" next={wf.get('next_run_at', '-')[:19]} runs={wf.get('run_count', 0)}"
            )
        return "\n".join(lines)

    def get_stats(self) -> dict:
        uptime = int((datetime.now(timezone.utc) - self._boot_time).total_seconds())
        success = self._runs - self._errors
        rate = f"{(success / self._runs):.0%}" if self._runs else "N/A"
        with self._lock:
            total = len(self._state.get("workflows", {}))
        return {
            "workflows": total,
            "runs": self._runs,
            "errors": self._errors,
            "success_rate": rate,
            "uptime_seconds": uptime,
        }

    def shutdown(self):
        self._stop_event.set()

    # ── Internal execution loop ─────────────────────────────────────

    def _loop(self):
        while not self._stop_event.wait(self.tick_seconds):
            try:
                self.run_due()
            except Exception as e:
                logger.warning("[WorkflowScheduler] loop error: %s", e)

    def _execute_workflow(self, wf: dict) -> dict:
        now = datetime.now(timezone.utc)
        kind = wf.get("kind", "")
        payload = wf.get("payload", "")

        success = False
        result = {"success": False, "error": f"unsupported kind: {kind}"}

        try:
            if kind == "shell":
                if not self.shell_executor:
                    result = {"success": False, "error": "shell executor not available"}
                else:
                    result = self.shell_executor.execute(payload)
            elif kind == "python":
                if not self.shell_executor:
                    result = {"success": False, "error": "shell executor not available"}
                else:
                    result = self.shell_executor.execute_python(payload)
            elif kind == "external_api":
                if not self.external_api:
                    result = {"success": False, "error": "external api manager not available"}
                else:
                    req = json.loads(payload)
                    if not isinstance(req, dict):
                        result = {"success": False, "error": "external_api payload must be JSON object"}
                    else:
                        action = req.pop("action", "request")
                        result = self.external_api.execute_action(action, req)
            success = bool(result.get("success"))
        except Exception as e:
            result = {"success": False, "error": str(e)}
            success = False

        with self._lock:
            curr = self._state.get("workflows", {}).get(wf.get("name"))
            if curr:
                curr["last_run_at"] = now.isoformat()
                curr["last_success"] = success
                curr["last_error"] = "" if success else str(result.get("error") or result.get("stderr") or "failed")[:500]
                curr["run_count"] = int(curr.get("run_count", 0)) + 1
                curr["updated_at"] = now.isoformat()
                interval = int(curr.get("interval_seconds", 300))
                curr["next_run_at"] = datetime.fromtimestamp(now.timestamp() + interval, tz=timezone.utc).isoformat()
                self._save_state_locked()

        self._runs += 1
        if not success:
            self._errors += 1

        logger.info(
            "[WorkflowScheduler] run %s kind=%s success=%s",
            wf.get("name"),
            kind,
            success,
        )
        return result

    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            try:
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("workflows", {})
                    return data
            except Exception as e:
                logger.warning("[WorkflowScheduler] state load failed: %s", e)

        data = {"workflows": {}, "updated_at": None}
        STATE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

    def _save_state_locked(self):
        self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
        STATE_PATH.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _parse_time(self, iso_value: str | None):
        if not iso_value:
            return None
        try:
            return datetime.fromisoformat(iso_value)
        except Exception:
            return None

    def _log(self, action: str, params: dict, result: dict):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "params": {k: (v[:200] if isinstance(v, str) else v) for k, v in params.items()},
            "success": bool(result.get("success")),
            "summary": str(result.get("error") or result.get("status_code") or result.get("workflow") or "ok")[:400],
        }
        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[WorkflowScheduler] journal write failed: %s", e)
