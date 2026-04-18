"""
XDART-Φ × XHEART — Shell Executor

Gives Αίολος hands on the local system:
  - Execute PowerShell commands
  - Run Python scripts
  - Browse the filesystem
  - Manage files and processes

Architecture:
  - subprocess.run() with timeout + output capture
  - Audit log (every command logged to journal)
  - Lightweight stability guards (timeout, output truncation)
  - No heavy security — local dev environment with git backup

© Panos Skouras — Salimov MON IKE, 2026
"""

import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("xdart.shell")

# ── Limits (stability, not security) ──
DEFAULT_TIMEOUT = 30          # seconds per command
MAX_OUTPUT_SIZE = 50_000      # chars — truncate beyond this
MAX_CONCURRENT = 3            # max simultaneous commands
AUDIT_LOG_MAX = 500           # keep last N entries in memory


class ShellExecutor:
    """Local shell executor for Αίολος — PowerShell + Python on Windows.

    Provides command execution with:
      - Timeout protection (prevents infinite loops)
      - Output truncation (prevents memory blowup)
      - Audit logging (every command tracked)
      - Concurrent execution limit
    """

    def __init__(
        self,
        working_dir: str | None = None,
        default_timeout: int = DEFAULT_TIMEOUT,
        max_output: int = MAX_OUTPUT_SIZE,
    ):
        self.working_dir = working_dir or os.getcwd()
        self.default_timeout = default_timeout
        self.max_output = max_output
        self._audit_log: list[dict] = []
        self._lock = threading.Lock()
        self._active_count = 0
        self._active_lock = threading.Lock()
        self._total_commands = 0
        self._total_errors = 0
        self._boot_time = datetime.now(timezone.utc)

        logger.info(
            "[Shell] Executor initialized (cwd=%s, timeout=%ds, max_output=%d)",
            self.working_dir, self.default_timeout, self.max_output,
        )

    # ── Core Execution ──

    def execute(
        self,
        command: str,
        timeout: int | None = None,
        working_dir: str | None = None,
        shell_type: str = "powershell",
    ) -> dict:
        """Execute a shell command and return structured result.

        Args:
            command: The command string to execute.
            timeout: Override default timeout (seconds).
            working_dir: Override default working directory.
            shell_type: "powershell" (default) or "cmd".

        Returns:
            {
                "success": bool,
                "command": str,
                "stdout": str,
                "stderr": str,
                "exit_code": int | None,
                "duration_ms": int,
                "truncated": bool,
                "error": str | None,
            }
        """
        if not command or not command.strip():
            return self._error_result(command, "Empty command")

        # Concurrency limit
        with self._active_lock:
            if self._active_count >= MAX_CONCURRENT:
                return self._error_result(
                    command,
                    f"Concurrent limit reached ({MAX_CONCURRENT}). Wait for running commands to finish.",
                )
            self._active_count += 1

        _timeout = timeout or self.default_timeout
        _cwd = working_dir or self.working_dir
        start_time = time.monotonic()

        try:
            # Build shell command
            if shell_type == "powershell":
                cmd_args = [
                    "powershell", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command", command,
                ]
            else:
                cmd_args = ["cmd", "/c", command]

            result = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=_timeout,
                cwd=_cwd,
                encoding="utf-8",
                errors="replace",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            truncated = False

            # Truncate if needed
            if len(stdout) > self.max_output:
                stdout = stdout[:self.max_output] + f"\n\n... [TRUNCATED — {len(result.stdout)} chars total, showing first {self.max_output}]"
                truncated = True
            if len(stderr) > self.max_output:
                stderr = stderr[:self.max_output] + "\n... [TRUNCATED]"
                truncated = True

            output = {
                "success": result.returncode == 0,
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": result.returncode,
                "duration_ms": duration_ms,
                "truncated": truncated,
                "error": None,
            }

        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            output = {
                "success": False,
                "command": command,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "duration_ms": duration_ms,
                "truncated": False,
                "error": f"Command timed out after {_timeout}s",
            }

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            output = {
                "success": False,
                "command": command,
                "stdout": "",
                "stderr": str(e),
                "exit_code": None,
                "duration_ms": duration_ms,
                "truncated": False,
                "error": f"Execution error: {e}",
            }

        finally:
            with self._active_lock:
                self._active_count -= 1

        # Update stats
        self._total_commands += 1
        if not output["success"]:
            self._total_errors += 1

        # Audit log
        self._log_audit(output)

        logger.info(
            "[Shell] %s | exit=%s | %dms | %s",
            "OK" if output["success"] else "FAIL",
            output["exit_code"],
            output["duration_ms"],
            command[:100],
        )

        return output

    def execute_python(
        self,
        code: str,
        timeout: int | None = None,
    ) -> dict:
        """Execute a Python code snippet.

        Args:
            code: Python code string.
            timeout: Override default timeout.

        Returns:
            Same structure as execute().
        """
        if not code or not code.strip():
            return self._error_result("python", "Empty code")

        # Use -c for short code, tempfile for longer
        if len(code) < 2000 and "\n" not in code.strip():
            # Single-line — use -c
            escaped = code.replace('"', '\\"')
            command = f'python -c "{escaped}"'
            return self.execute(command, timeout=timeout)
        else:
            # Multi-line — write temp file, execute, clean up
            import tempfile
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8"
                ) as f:
                    f.write(code)
                    tmp_path = f.name
                return self.execute(f'python "{tmp_path}"', timeout=timeout)
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

    # ── Convenience Methods ──

    def list_directory(self, path: str = ".") -> dict:
        """List contents of a directory."""
        return self.execute(f'Get-ChildItem -Path "{path}" | Format-Table Name, Length, LastWriteTime -AutoSize')

    def read_file(self, path: str, max_lines: int = 200) -> dict:
        """Read a file (first N lines)."""
        return self.execute(f'Get-Content -Path "{path}" -TotalCount {max_lines}')

    def file_info(self, path: str) -> dict:
        """Get file/directory info."""
        return self.execute(f'Get-Item -Path "{path}" | Format-List *')

    def disk_usage(self) -> dict:
        """Get disk usage summary."""
        return self.execute('Get-PSDrive -PSProvider FileSystem | Format-Table Name, Used, Free -AutoSize')

    def process_list(self, top_n: int = 20) -> dict:
        """List top processes by memory."""
        return self.execute(
            f'Get-Process | Sort-Object -Property WorkingSet64 -Descending | '
            f'Select-Object -First {top_n} Name, Id, CPU, @{{N="MemMB";E={{[math]::Round($_.WorkingSet64/1MB,1)}}}} | '
            f'Format-Table -AutoSize'
        )

    def system_info(self) -> dict:
        """Get basic system information."""
        return self.execute(
            '$os = Get-CimInstance Win32_OperatingSystem; '
            '$cpu = Get-CimInstance Win32_Processor; '
            'Write-Output "OS: $($os.Caption) $($os.Version)"; '
            'Write-Output "CPU: $($cpu.Name)"; '
            'Write-Output ("RAM: {0:N1} GB / {1:N1} GB free" -f ($os.TotalVisibleMemorySize/1MB), ($os.FreePhysicalMemory/1MB)); '
            'Write-Output "Uptime: $((Get-Date) - $os.LastBootUpTime)"'
        )

    def git_status(self, repo_path: str | None = None) -> dict:
        """Get git status of a repository."""
        return self.execute("git status --short", working_dir=repo_path)

    def pip_install(self, package: str) -> dict:
        """Install a Python package."""
        return self.execute(f'pip install {package}', timeout=120)

    def web_request(self, url: str) -> dict:
        """Make a simple HTTP GET request."""
        return self.execute(
            f'(Invoke-WebRequest -Uri "{url}" -UseBasicParsing).Content | Select-Object -First 100',
            timeout=30,
        )

    # ── Status & Audit ──

    def get_stats(self) -> dict:
        """Return executor statistics."""
        uptime = (datetime.now(timezone.utc) - self._boot_time).total_seconds()
        return {
            "total_commands": self._total_commands,
            "total_errors": self._total_errors,
            "success_rate": (
                f"{(self._total_commands - self._total_errors) / self._total_commands:.0%}"
                if self._total_commands > 0 else "N/A"
            ),
            "active_commands": self._active_count,
            "uptime_seconds": int(uptime),
            "audit_log_size": len(self._audit_log),
            "working_dir": self.working_dir,
            "default_timeout": self.default_timeout,
        }

    def get_audit_log(self, last_n: int = 20) -> list[dict]:
        """Return last N audit log entries."""
        return self._audit_log[-last_n:]

    def to_context_string(self) -> str:
        """Format shell status for LLM context injection."""
        stats = self.get_stats()
        recent = self._audit_log[-3:] if self._audit_log else []
        lines = [
            f"SHELL EXECUTOR STATUS (local PowerShell + Python):",
            f"  Commands executed: {stats['total_commands']} ({stats['success_rate']} success)",
            f"  Working directory: {stats['working_dir']}",
            f"  Timeout: {stats['default_timeout']}s per command",
        ]
        if recent:
            lines.append("  Recent commands:")
            for entry in recent:
                status = "✓" if entry.get("success") else "✗"
                lines.append(
                    f"    {status} [{entry.get('timestamp', '?')[:19]}] "
                    f"{entry.get('command', '?')[:80]} ({entry.get('duration_ms', '?')}ms)"
                )
        return "\n".join(lines)

    # ── Internal ──

    def _log_audit(self, result: dict) -> None:
        """Append to audit log (thread-safe, bounded)."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": result["command"][:200],
            "success": result["success"],
            "exit_code": result["exit_code"],
            "duration_ms": result["duration_ms"],
            "stdout_len": len(result.get("stdout", "")),
            "stderr_len": len(result.get("stderr", "")),
            "error": result.get("error"),
        }
        with self._lock:
            self._audit_log.append(entry)
            if len(self._audit_log) > AUDIT_LOG_MAX:
                self._audit_log = self._audit_log[-AUDIT_LOG_MAX:]

    def _error_result(self, command: str, error: str) -> dict:
        """Build an error result dict."""
        return {
            "success": False,
            "command": command or "",
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "duration_ms": 0,
            "truncated": False,
            "error": error,
        }
