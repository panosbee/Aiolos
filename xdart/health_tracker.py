"""
XDART-Φ — System Health Tracker

Centralized error/status registry so Αίολος knows what's working
and what's broken at any moment. Background tasks report their state
here; the Wakeup protocol and /xdart/system/errors expose it.

Architecture:
  - Each subsystem registers via record_ok() or record_error()
  - Tracker keeps the last N events per subsystem (ring buffer)
  - get_summary() returns a one-glance health report
  - get_wakeup_context() returns a compact string for Wakeup injection
"""

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum error events kept per subsystem
_MAX_EVENTS_PER_SYSTEM = 10


class _SubsystemState:
    __slots__ = ("name", "status", "last_ok", "last_error", "error_count",
                 "ok_count", "recent_errors", "last_message")

    def __init__(self, name: str):
        self.name = name
        self.status: str = "unknown"  # ok | error | degraded
        self.last_ok: Optional[datetime] = None
        self.last_error: Optional[datetime] = None
        self.error_count: int = 0
        self.ok_count: int = 0
        self.recent_errors: deque = deque(maxlen=_MAX_EVENTS_PER_SYSTEM)
        self.last_message: str = ""


class SystemHealthTracker:
    """Thread-safe singleton health tracker for all XDART-Φ subsystems."""

    _instance: Optional["SystemHealthTracker"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._subsystems: dict[str, _SubsystemState] = {}
                cls._instance._boot_time = datetime.now(timezone.utc)
        return cls._instance

    def _get_or_create(self, name: str) -> _SubsystemState:
        if name not in self._subsystems:
            self._subsystems[name] = _SubsystemState(name)
        return self._subsystems[name]

    def record_ok(self, subsystem: str, message: str = ""):
        """Record a successful operation for a subsystem."""
        with self._lock:
            state = self._get_or_create(subsystem)
            state.status = "ok"
            state.last_ok = datetime.now(timezone.utc)
            state.ok_count += 1
            if message:
                state.last_message = message

    def record_error(self, subsystem: str, error: str, exc: Optional[Exception] = None):
        """Record an error for a subsystem."""
        now = datetime.now(timezone.utc)
        with self._lock:
            state = self._get_or_create(subsystem)
            state.status = "error"
            state.last_error = now
            state.error_count += 1
            state.last_message = error
            state.recent_errors.append({
                "time": now.isoformat(),
                "error": error,
                "exception": str(exc) if exc else None,
            })

    def record_startup(self, subsystem: str, success: bool, message: str = ""):
        """Record whether a subsystem started successfully."""
        if success:
            self.record_ok(subsystem, message or "started")
        else:
            self.record_error(subsystem, message or "failed to start")

    def get_summary(self) -> dict:
        """Full health summary for API endpoint."""
        with self._lock:
            systems = {}
            for name, state in sorted(self._subsystems.items()):
                systems[name] = {
                    "status": state.status,
                    "ok_count": state.ok_count,
                    "error_count": state.error_count,
                    "last_ok": state.last_ok.isoformat() if state.last_ok else None,
                    "last_error": state.last_error.isoformat() if state.last_error else None,
                    "last_message": state.last_message,
                    "recent_errors": list(state.recent_errors),
                }

            total_errors = sum(s.error_count for s in self._subsystems.values())
            broken = [n for n, s in self._subsystems.items() if s.status == "error"]

            return {
                "boot_time": self._boot_time.isoformat(),
                "uptime_seconds": (datetime.now(timezone.utc) - self._boot_time).total_seconds(),
                "total_subsystems": len(self._subsystems),
                "healthy": len(self._subsystems) - len(broken),
                "broken": broken,
                "total_errors": total_errors,
                "subsystems": systems,
            }

    def get_wakeup_context(self) -> str:
        """Compact health string for Wakeup identity injection.

        Αίολος sees this at the start of every chat/pipeline — he knows
        which subsystems are working and which are broken.
        """
        with self._lock:
            if not self._subsystems:
                return ""

            lines = ["SYSTEM HEALTH STATUS:"]
            broken = []
            ok_systems = []

            for name, state in sorted(self._subsystems.items()):
                if state.status == "error":
                    # Show last error message for broken systems
                    ago = ""
                    if state.last_error:
                        secs = (datetime.now(timezone.utc) - state.last_error).total_seconds()
                        if secs < 60:
                            ago = f" ({int(secs)}s ago)"
                        elif secs < 3600:
                            ago = f" ({int(secs / 60)}m ago)"
                        else:
                            ago = f" ({secs / 3600:.1f}h ago)"
                    broken.append(
                        f"  ✗ {name}: ERROR — {state.last_message[:120]}{ago}"
                    )
                elif state.status == "ok":
                    ok_systems.append(name)

            if broken:
                lines.append(f"  ⚠ {len(broken)} subsystem(s) have errors:")
                lines.extend(broken)
            if ok_systems:
                lines.append(f"  ✓ Healthy: {', '.join(ok_systems)}")

            uptime = (datetime.now(timezone.utc) - self._boot_time).total_seconds()
            if uptime < 3600:
                lines.append(f"  Uptime: {int(uptime / 60)}m")
            else:
                lines.append(f"  Uptime: {uptime / 3600:.1f}h")

            return "\n".join(lines) + "\n"


# Module-level singleton
health_tracker = SystemHealthTracker()
