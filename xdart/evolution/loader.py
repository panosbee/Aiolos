"""
XDART-Φ × XHEART — Evolution Loader (Hot Deploy)

After a tool passes sandbox testing, the Loader:
  1. Writes the tool module to xdart/tools/_generated/
  2. Records the deployment in evolution_log.json
  3. If a tool of the same name exists, bumps the version
  4. Makes the tool discoverable by the ToolRegistry

No restart needed — ToolRegistry re-scans on every pipeline run.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("xdart.evolution.loader")

BASE_DIR = Path(__file__).resolve().parent.parent
GENERATED_DIR = BASE_DIR / "tools" / "_generated"
EVOLUTION_LOG = BASE_DIR / "evolution" / "evolution_log.json"


class Loader:
    """Hot deployment of sandbox-tested tools."""

    def __init__(self):
        # Ensure directories exist
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        if not (GENERATED_DIR / "__init__.py").exists():
            (GENERATED_DIR / "__init__.py").write_text(
                '"""Auto-generated tools — managed by Evolution Core."""\n',
                encoding="utf-8",
            )

    def deploy(self, tool_name: str, tool_code: str, metadata: dict) -> bool:
        """Deploy a sandbox-tested tool to _generated/.

        Args:
            tool_name: snake_case identifier (e.g. 'trend_detector')
            tool_code: Full Python source code
            metadata: From evolution core (purpose, gap_description, etc.)

        Returns:
            True if deployment succeeded
        """
        # Sanitize tool name — only alphanumeric + underscore
        safe_name = re.sub(r"[^a-z0-9_]", "", tool_name.lower())
        if not safe_name:
            logger.error("[Loader] Invalid tool name: %s", tool_name)
            return False

        target_path = GENERATED_DIR / f"{safe_name}.py"

        # Check if tool already exists — bump version
        version = "1.0"
        if target_path.exists():
            existing = target_path.read_text(encoding="utf-8")
            version_match = re.search(r'"version"\s*:\s*"(\d+\.\d+)"', existing)
            if version_match:
                old_major, old_minor = version_match.group(1).split(".")
                version = f"{old_major}.{int(old_minor) + 1}"
            logger.info("[Loader] Upgrading %s → v%s", safe_name, version)
        else:
            logger.info("[Loader] Deploying new tool: %s v%s", safe_name, version)

        # Update version in the code if present
        tool_code = re.sub(
            r'("version"\s*:\s*)"[\d.]+"',
            f'\\1"{version}"',
            tool_code,
        )

        # Write the tool file
        try:
            target_path.write_text(tool_code, encoding="utf-8")
        except Exception as e:
            logger.error("[Loader] Failed to write %s: %s", target_path, e)
            return False

        # Record in evolution log
        self._log_deployment(safe_name, version, metadata)

        logger.info(
            "[Loader] ✓ Deployed %s v%s → %s",
            safe_name,
            version,
            target_path.relative_to(BASE_DIR),
        )
        return True

    def remove(self, tool_name: str) -> bool:
        """Remove a tool from _generated/."""
        safe_name = re.sub(r"[^a-z0-9_]", "", tool_name.lower())
        target_path = GENERATED_DIR / f"{safe_name}.py"

        if target_path.exists():
            target_path.unlink()
            self._log_removal(safe_name)
            logger.info("[Loader] Removed tool: %s", safe_name)
            return True

        logger.warning("[Loader] Tool not found for removal: %s", safe_name)
        return False

    def list_deployed(self) -> list[dict]:
        """List all deployed tools with their metadata."""
        tools = []
        for f in sorted(GENERATED_DIR.glob("*.py")):
            if f.name == "__init__.py":
                continue
            try:
                content = f.read_text(encoding="utf-8")
                meta_match = re.search(
                    r"TOOL_META\s*=\s*(\{[^}]+\})", content, re.DOTALL
                )
                if meta_match:
                    # Safely parse the dict literal
                    meta_str = meta_match.group(1)
                    # Simple key-value extraction
                    name = re.search(r'"name"\s*:\s*"([^"]+)"', meta_str)
                    version = re.search(r'"version"\s*:\s*"([^"]+)"', meta_str)
                    purpose = re.search(r'"purpose"\s*:\s*"([^"]+)"', meta_str)
                    tools.append({
                        "file": f.name,
                        "name": name.group(1) if name else f.stem,
                        "version": version.group(1) if version else "?",
                        "purpose": purpose.group(1) if purpose else "?",
                    })
                else:
                    tools.append({
                        "file": f.name,
                        "name": f.stem,
                        "version": "?",
                        "purpose": "No TOOL_META found",
                    })
            except Exception as e:
                tools.append({
                    "file": f.name,
                    "name": f.stem,
                    "version": "?",
                    "purpose": f"Error reading: {e}",
                })
        return tools

    def _log_deployment(self, tool_name: str, version: str, metadata: dict):
        """Append to evolution_log.json."""
        log = self._read_log()
        log["deployments"].append({
            "action": "deploy",
            "tool_name": tool_name,
            "version": version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gap_description": metadata.get("gap_description", ""),
            "purpose": metadata.get("tool_purpose", ""),
            "expected_improvement": metadata.get("expected_improvement", ""),
        })
        self._write_log(log)

    def _log_removal(self, tool_name: str):
        """Log tool removal."""
        log = self._read_log()
        log["deployments"].append({
            "action": "remove",
            "tool_name": tool_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._write_log(log)

    def _read_log(self) -> dict:
        """Read or initialize the evolution log."""
        if EVOLUTION_LOG.exists():
            try:
                return json.loads(EVOLUTION_LOG.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"deployments": [], "sandbox_failures": []}

    def _write_log(self, log: dict):
        """Write the evolution log."""
        EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        EVOLUTION_LOG.write_text(
            json.dumps(log, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def log_sandbox_failure(self, tool_name: str, error: str, metadata: dict):
        """Record a sandbox failure for learning."""
        log = self._read_log()
        log["sandbox_failures"].append({
            "tool_name": tool_name,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gap_description": metadata.get("gap_description", ""),
        })
        # Keep only last 50 failures
        log["sandbox_failures"] = log["sandbox_failures"][-50:]
        self._write_log(log)
