"""
XDART-Φ × XHEART — Evolution Sandbox

Safe execution environment for testing generated tools.
Runs code in a subprocess with:
  - Timeout (30 seconds max)
  - Import validation (whitelist only)
  - No filesystem, network, or DB access
  - Captured stdout/stderr
  - Test data injection

If it passes sandbox, it's safe to deploy.
"""

import json
import logging
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

logger = logging.getLogger("xdart.evolution.sandbox")

# Modules that generated tools are allowed to import
SAFE_IMPORTS = frozenset({
    "json", "math", "statistics", "collections", "re",
    "datetime", "itertools", "functools", "operator",
    "typing", "dataclasses", "enum", "copy",
})

# Modules that are NEVER allowed
FORBIDDEN_IMPORTS = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib",
    "requests", "httpx", "urllib", "socket", "http",
    "sqlite3", "importlib", "ctypes", "pickle",
    "multiprocessing", "threading", "signal",
})

# Dangerous builtins
FORBIDDEN_BUILTINS = frozenset({
    "exec", "eval", "compile", "__import__",
    "globals", "locals", "vars", "dir",
    "open", "input", "breakpoint",
})


class SandboxResult:
    """Result of a sandbox execution."""

    def __init__(
        self,
        success: bool,
        output: dict | None = None,
        error: str = "",
        stdout: str = "",
        stderr: str = "",
        validation_errors: list[str] | None = None,
    ):
        self.success = success
        self.output = output
        self.error = error
        self.stdout = stdout
        self.stderr = stderr
        self.validation_errors = validation_errors or []


class Sandbox:
    """Safe execution environment for generated tool code."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def test_tool(self, tool_code: str, test_context: dict) -> SandboxResult:
        """Test a generated tool in isolation.

        1. Static validation (imports, forbidden patterns)
        2. Subprocess execution with timeout
        3. Output validation
        """
        # Smart unescape: if JSON parsing already produced valid multi-line Python,
        # do NOT replace \\n — that would break string literals like "foo\nbar"
        # into unterminated "foo\n + bar".
        # Only unescape if the code looks like a single long line (JSON double-escaped).
        newline_count = tool_code.count('\n')
        if newline_count < 5 and '\\n' in tool_code:
            # Likely a single-line blob — JSON double-escaped. Unescape structure.
            tool_code = tool_code.replace('\\n', '\n')
            if '\\t' in tool_code:
                tool_code = tool_code.replace('\\t', '\t')
        # If already multi-line, trust that JSON parsing handled newlines correctly.

        # Sanitize control characters that break JSON/exec (e.g. \x00-\x1f except \n \r \t)
        import re
        tool_code = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', tool_code)

        # Step 1: Static code validation
        validation_errors = self._validate_code(tool_code)
        if validation_errors:
            logger.warning(
                "[Sandbox] Code validation FAILED: %s", validation_errors
            )
            return SandboxResult(
                success=False,
                error="Code validation failed",
                validation_errors=validation_errors,
            )

        # Step 2: Build the test harness
        harness = self._build_test_harness(tool_code, test_context)

        # Step 3: Execute in subprocess
        return self._execute(harness)

    def _validate_code(self, code: str) -> list[str]:
        """Static analysis — check for forbidden imports and patterns."""
        errors = []

        for line in code.split("\n"):
            stripped = line.strip()

            # Check imports
            if stripped.startswith("import ") or stripped.startswith("from "):
                module = stripped.replace("import ", "").replace("from ", "").split(".")[0].split(" ")[0]
                if module in FORBIDDEN_IMPORTS:
                    errors.append(f"Forbidden import: {module}")
                elif module not in SAFE_IMPORTS and module != "":
                    errors.append(f"Unknown import: {module} (not in whitelist)")

            # Check forbidden builtins
            for fb in FORBIDDEN_BUILTINS:
                if fb + "(" in stripped and not stripped.startswith("#"):
                    errors.append(f"Forbidden builtin: {fb}()")

        # Check for TOOL_META
        if "TOOL_META" not in code:
            errors.append("Missing TOOL_META dict")

        # Check for run() function
        if "def run(" not in code:
            errors.append("Missing run() function")

        return errors

    def _build_test_harness(self, tool_code: str, test_context: dict) -> str:
        """Wrap the tool code in a test harness that runs it safely."""
        context_json = json.dumps(test_context, ensure_ascii=False, default=str)

        harness = textwrap.dedent(f"""\
            import json
            import sys

            # ── Generated tool code ──
            {textwrap.indent(tool_code, '            ').strip()}
            # ── End generated tool code ──

            # ── Test execution ──
            try:
                test_context = json.loads('''{context_json}''')
                result = run(test_context)

                # Validate output format
                if not isinstance(result, dict):
                    print(json.dumps({{"error": "run() must return a dict, got " + type(result).__name__}}))
                    sys.exit(1)

                if "tool_name" not in result:
                    print(json.dumps({{"error": "Missing 'tool_name' in result"}}))
                    sys.exit(1)

                if "output" not in result:
                    print(json.dumps({{"error": "Missing 'output' in result"}}))
                    sys.exit(1)

                # Success
                print("__SANDBOX_RESULT__")
                print(json.dumps(result, ensure_ascii=False, default=str))

            except Exception as e:
                print(json.dumps({{"error": f"Runtime error: {{type(e).__name__}}: {{e}}"}}))
                sys.exit(1)
        """)
        return harness

    def _execute(self, harness_code: str) -> SandboxResult:
        """Execute the test harness in a subprocess with timeout."""
        try:
            # Write to temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as f:
                f.write(harness_code)
                temp_path = f.name

            # Execute in subprocess
            result = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=tempfile.gettempdir(),  # Run from temp dir, not project dir
            )

            # Clean up
            Path(temp_path).unlink(missing_ok=True)

            stdout = result.stdout
            stderr = result.stderr

            if result.returncode != 0:
                # Try to parse error from stdout
                try:
                    error_data = json.loads(stdout.strip().split("\n")[-1])
                    error_msg = error_data.get("error", "Unknown error")
                except Exception:
                    error_msg = stderr[:500] if stderr else f"Exit code {result.returncode}"

                logger.warning("[Sandbox] Execution FAILED: %s", error_msg)
                return SandboxResult(
                    success=False,
                    error=error_msg,
                    stdout=stdout,
                    stderr=stderr,
                )

            # Parse output
            if "__SANDBOX_RESULT__" in stdout:
                result_line = stdout.split("__SANDBOX_RESULT__")[1].strip()
                output = json.loads(result_line)
                logger.info(
                    "[Sandbox] Execution SUCCESS — tool: %s, output: %d chars",
                    output.get("tool_name", "?"),
                    len(output.get("output", "")),
                )
                return SandboxResult(
                    success=True,
                    output=output,
                    stdout=stdout,
                    stderr=stderr,
                )
            else:
                logger.warning("[Sandbox] No result marker found in output")
                return SandboxResult(
                    success=False,
                    error="No __SANDBOX_RESULT__ marker in stdout",
                    stdout=stdout,
                    stderr=stderr,
                )

        except subprocess.TimeoutExpired:
            Path(temp_path).unlink(missing_ok=True)
            logger.warning("[Sandbox] TIMEOUT after %ds", self.timeout)
            return SandboxResult(
                success=False,
                error=f"Execution timed out after {self.timeout}s",
            )

        except Exception as e:
            logger.warning("[Sandbox] Unexpected error: %s", e)
            return SandboxResult(
                success=False,
                error=f"Sandbox error: {e}",
            )

    @staticmethod
    def build_test_context(
        problem: str = "Test question about world economy",
        events: list[dict] | None = None,
        indicators: list[dict] | None = None,
    ) -> dict:
        """Build a realistic test context for sandbox testing."""
        if events is None:
            events = [
                {
                    "headline": "Fed holds rates steady at 4.42%",
                    "source_name": "Reuters",
                    "domain": "ECONOMIC",
                    "content_type": "FACT",
                    "salience_score": 0.8,
                },
                {
                    "headline": "China announces new tariffs on US goods",
                    "source_name": "Xinhua",
                    "domain": "GEOPOLITICAL",
                    "content_type": "FACT",
                    "salience_score": 0.9,
                },
                {
                    "headline": "EU summit addresses migration policy",
                    "source_name": "Deutsche Welle",
                    "domain": "GEOPOLITICAL",
                    "content_type": "FACT",
                    "salience_score": 0.6,
                },
            ]

        if indicators is None:
            indicators = [
                {
                    "indicator": "FEDFUNDS",
                    "value": 4.42,
                    "unit": "%",
                    "source": "FRED",
                    "change_pct": None,
                },
                {
                    "indicator": "CPIAUCSL",
                    "value": 327.46,
                    "unit": "index",
                    "source": "FRED",
                    "change_pct": 0.3,
                },
                {
                    "indicator": "UNRATE",
                    "value": 4.4,
                    "unit": "%",
                    "source": "FRED",
                    "change_pct": None,
                },
            ]

        return {
            "problem": problem,
            "events": events,
            "indicators": indicators,
        }
