"""
XDART-Φ × XHEART — Self-Modification Engine

Gives Αίολος the ability to modify its own code, configuration,
prompt overlays, and character state during chat conversation.

All modifications are:
  - Backed up automatically (timestamped .bak files)
  - Logged to self_modification_journal.jsonl
  - Hot-reloaded when source code changes

Actions:
  edit_file     — find/replace or append to any project file
  patch_file    — apply a targeted patch (old_text → new_text)
  create_file   — create a new file in the project
  read_self     — read own source code for introspection
  set_overlay   — update prompt overlays (prompt_overlays.json)
  update_config — change runtime config values
  update_character — modify character_state.json fields
  create_tool   — write a generated tool directly (bypass evolution)
  list_modules  — list own modules and structure
"""

import json
import logging
import os
import re
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("xdart.tools.self_modify")

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
XDART_DIR = BASE_DIR / "xdart"
BACKUP_DIR = BASE_DIR / ".self_modify_backups"
JOURNAL_PATH = BASE_DIR / "self_modification_journal.jsonl"
OVERLAY_PATH = BASE_DIR / "prompt_overlays.json"
CHARACTER_PATH = BASE_DIR / "character_state.json"
GENERATED_TOOLS_DIR = XDART_DIR / "tools" / "_generated"


class SelfModify:
    """Self-modification engine for Αίολος."""

    def __init__(self):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        GENERATED_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        self._action_count = 0
        logger.info("[SelfModify] Initialized — project root: %s", BASE_DIR)

    # ── Main dispatcher ────────────────────────────────────────────
    def execute_action(self, action: str, params: dict) -> dict:
        """Execute a self-modification action.

        Args:
            action: Action name (e.g. 'edit_file', 'set_overlay')
            params: Action-specific parameters

        Returns:
            dict with 'success' bool and action-specific results
        """
        action = action.strip().lower()
        handler = getattr(self, action, None)
        if not handler or action.startswith("_"):
            return {"success": False, "error": f"Unknown action: {action}"}

        try:
            result = handler(**params)
            self._action_count += 1
            self._log_action(action, params, result)
            return result
        except Exception as e:
            error_result = {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
            self._log_action(action, params, error_result)
            return error_result

    # ── File Operations ────────────────────────────────────────────

    def edit_file(self, path: str = "", content: str = "", mode: str = "write", **_) -> dict:
        """Write or append to a project file.

        Args:
            path: Relative path from project root (e.g. 'xdart/tools/my_tool.py')
            content: Content to write or append
            mode: 'write' (overwrite) or 'append'
        """
        target = self._resolve_path(path)
        if not target:
            return {"success": False, "error": f"Invalid path: {path}"}

        # Backup if file exists
        if target.exists():
            self._backup(target)

        target.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)

        return {
            "success": True,
            "path": str(target.relative_to(BASE_DIR)),
            "mode": mode,
            "bytes_written": len(content.encode("utf-8")),
        }

    def patch_file(self, path: str = "", old_text: str = "", new_text: str = "", **_) -> dict:
        """Apply a targeted find/replace patch to a file.

        Args:
            path: Relative path from project root
            old_text: Exact text to find (must exist exactly once)
            new_text: Replacement text
        """
        target = self._resolve_path(path)
        if not target or not target.exists():
            return {"success": False, "error": f"File not found: {path}"}

        original = target.read_text(encoding="utf-8")
        count = original.count(old_text)

        if count == 0:
            return {"success": False, "error": "old_text not found in file"}
        if count > 1:
            return {"success": False, "error": f"old_text found {count} times — must be unique"}

        self._backup(target)
        patched = original.replace(old_text, new_text, 1)
        target.write_text(patched, encoding="utf-8")

        return {
            "success": True,
            "path": str(target.relative_to(BASE_DIR)),
            "occurrences_replaced": 1,
        }

    def create_file(self, path: str = "", content: str = "", **_) -> dict:
        """Create a new file (fails if already exists).

        Args:
            path: Relative path from project root
            content: File content
        """
        target = self._resolve_path(path)
        if not target:
            return {"success": False, "error": f"Invalid path: {path}"}
        if target.exists():
            return {"success": False, "error": f"File already exists: {path} — use edit_file or patch_file"}

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "path": str(target.relative_to(BASE_DIR)),
            "bytes_written": len(content.encode("utf-8")),
        }

    def read_self(self, path: str = "", lines: str = "", **_) -> dict:
        """Read own source code for introspection.

        Args:
            path: Relative path (e.g. 'xdart/core.py')
            lines: Optional line range 'start-end' (1-based, inclusive)
        """
        target = self._resolve_path(path)
        if not target or not target.exists():
            return {"success": False, "error": f"File not found: {path}"}

        content = target.read_text(encoding="utf-8")
        total_lines = content.count("\n") + 1

        if lines:
            try:
                parts = lines.split("-")
                start = max(1, int(parts[0]))
                end = min(total_lines, int(parts[1])) if len(parts) > 1 else start
                content_lines = content.splitlines()
                content = "\n".join(content_lines[start - 1 : end])
                return {
                    "success": True,
                    "path": str(target.relative_to(BASE_DIR)),
                    "lines": f"{start}-{end}",
                    "total_lines": total_lines,
                    "content": content[:15000],  # Cap at 15K chars
                }
            except (ValueError, IndexError):
                return {"success": False, "error": f"Invalid line range: {lines}"}

        # Full file — cap at 15K chars
        return {
            "success": True,
            "path": str(target.relative_to(BASE_DIR)),
            "total_lines": total_lines,
            "content": content[:15000],
            "truncated": len(content) > 15000,
        }

    # ── Prompt Overlays ────────────────────────────────────────────

    def set_overlay(self, phase: str = "", text: str = "", reason: str = "", active: str = "true", **_) -> dict:
        """Update a prompt overlay.

        Args:
            phase: Overlay key (e.g. 'xheart_output', 'chat_system', 'ontology')
            text: New overlay prompt text
            reason: Why this change is being made
            active: 'true' or 'false'
        """
        if not phase:
            return {"success": False, "error": "phase is required"}

        self._backup(OVERLAY_PATH)
        data = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))

        is_active = active.lower() in ("true", "1", "yes")
        now = datetime.now(timezone.utc).isoformat()

        if phase in data["overlays"]:
            old = data["overlays"][phase]
            # Push current to history if it had content
            if old.get("text"):
                history_entry = {
                    "text": old["text"],
                    "reason": old.get("reason", ""),
                    "applied_at_version": old.get("applied_at_version"),
                    "applied_at": old.get("applied_at"),
                    "deactivated_at": now,
                    "deactivation_reason": "superseded by self-modify",
                }
                old.setdefault("history", []).append(history_entry)

            old["text"] = text
            old["reason"] = reason
            old["active"] = is_active
            old["applied_at"] = now
        else:
            # New overlay
            data["overlays"][phase] = {
                "text": text,
                "reason": reason,
                "applied_at_version": None,
                "wisdom_index_at_apply": None,
                "applied_at": now,
                "active": is_active,
                "history": [],
            }

        data["last_updated"] = now
        OVERLAY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        return {
            "success": True,
            "phase": phase,
            "active": is_active,
            "text_length": len(text),
        }

    # ── Configuration ──────────────────────────────────────────────

    def update_config(self, key: str = "", value: str = "", **_) -> dict:
        """Update a runtime configuration value.

        Modifies .env file and reloads xdart.config module.

        Args:
            key: Config variable name (e.g. 'OPENAI_TEMPERATURE')
            value: New value as string
        """
        if not key:
            return {"success": False, "error": "key is required"}

        # Only allow known config keys
        import xdart.config as cfg
        if not hasattr(cfg, key.upper()):
            return {"success": False, "error": f"Unknown config key: {key}"}

        key_upper = key.upper()
        env_path = BASE_DIR / ".env"

        # Update .env file
        if env_path.exists():
            self._backup(env_path)
            env_content = env_path.read_text(encoding="utf-8")
            # Replace existing or append
            pattern = re.compile(rf'^{re.escape(key_upper)}\s*=.*$', re.MULTILINE)
            if pattern.search(env_content):
                env_content = pattern.sub(f"{key_upper}={value}", env_content)
            else:
                env_content = env_content.rstrip() + f"\n{key_upper}={value}\n"
        else:
            env_content = f"{key_upper}={value}\n"

        env_path.write_text(env_content, encoding="utf-8")

        # Update in-memory config
        os.environ[key_upper] = value
        old_value = getattr(cfg, key_upper, None)

        # Re-derive typed value
        try:
            from importlib import reload
            reload(cfg)
            new_value = getattr(cfg, key_upper, value)
        except Exception:
            new_value = value

        return {
            "success": True,
            "key": key_upper,
            "old_value": str(old_value),
            "new_value": str(new_value),
        }

    # ── Character State ────────────────────────────────────────────

    def update_character(self, field: str = "", value: str = "", merge: str = "false", **_) -> dict:
        """Update a field in character_state.json.

        Args:
            field: Dot-notation path (e.g. 'epistemic_stance.default_confidence')
            value: New value (JSON-encoded for complex types)
            merge: 'true' to merge dicts instead of replace
        """
        if not field:
            return {"success": False, "error": "field is required"}

        self._backup(CHARACTER_PATH)
        data = json.loads(CHARACTER_PATH.read_text(encoding="utf-8"))

        # Parse value — try JSON first, fall back to string
        try:
            parsed_value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed_value = value

        # Navigate dot-notation path
        keys = field.split(".")
        target = data
        for k in keys[:-1]:
            if isinstance(target, dict) and k in target:
                target = target[k]
            else:
                return {"success": False, "error": f"Path not found: {field}"}

        final_key = keys[-1]
        old_value = target.get(final_key) if isinstance(target, dict) else None

        if merge.lower() in ("true", "1", "yes") and isinstance(target.get(final_key), dict) and isinstance(parsed_value, dict):
            target[final_key].update(parsed_value)
        else:
            target[final_key] = parsed_value

        # Bump version
        data["version"] = data.get("version", 0) + 1

        CHARACTER_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        return {
            "success": True,
            "field": field,
            "old_value": str(old_value)[:200] if old_value is not None else None,
            "new_version": data["version"],
        }

    # ── Tool Creation ──────────────────────────────────────────────

    def create_tool(self, name: str = "", code: str = "", purpose: str = "", **_) -> dict:
        """Write a generated tool directly (bypass evolution pipeline).

        Args:
            name: Tool name in snake_case (e.g. 'trend_detector')
            code: Full Python source with TOOL_META dict and run() function
            purpose: One-line description of what the tool does
        """
        if not name or not code:
            return {"success": False, "error": "name and code are required"}

        safe_name = re.sub(r"[^a-z0-9_]", "", name.lower())
        if not safe_name:
            return {"success": False, "error": f"Invalid tool name: {name}"}

        target = GENERATED_TOOLS_DIR / f"{safe_name}.py"

        # Backup if upgrading
        version = "1.0"
        if target.exists():
            self._backup(target)
            existing = target.read_text(encoding="utf-8")
            ver_match = re.search(r'"version"\s*:\s*"(\d+\.\d+)"', existing)
            if ver_match:
                major, minor = ver_match.group(1).split(".")
                version = f"{major}.{int(minor) + 1}"

        # Ensure TOOL_META exists
        if "TOOL_META" not in code:
            return {"success": False, "error": "Code must contain TOOL_META dict"}
        if "def run(" not in code:
            return {"success": False, "error": "Code must contain run() function"}

        # Update version in code
        code = re.sub(r'("version"\s*:\s*)"[\d.]+"', f'\\1"{version}"', code)

        target.write_text(code, encoding="utf-8")

        return {
            "success": True,
            "name": safe_name,
            "version": version,
            "path": str(target.relative_to(BASE_DIR)),
            "purpose": purpose,
        }

    # ── Introspection ──────────────────────────────────────────────

    def list_modules(self, **_) -> dict:
        """List own modules and directory structure for introspection."""
        modules = []
        for py_file in sorted(XDART_DIR.rglob("*.py")):
            rel = py_file.relative_to(BASE_DIR)
            size = py_file.stat().st_size
            # Read first docstring
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                doc_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
                doc = doc_match.group(1).strip()[:120] if doc_match else ""
            except Exception:
                doc = ""
            modules.append({
                "path": str(rel),
                "size": size,
                "doc": doc,
            })

        return {
            "success": True,
            "module_count": len(modules),
            "modules": modules,
        }

    # ── Context for LLM ───────────────────────────────────────────

    def to_context_string(self) -> str:
        """Brief capability summary injected into LLM context."""
        return (
            "🧬 SELF-MODIFY ENGINE: Active — You can modify your own code, config, "
            "prompts, and character state during conversation.\n"
            f"  Project root: {BASE_DIR}\n"
            f"  Actions performed this session: {self._action_count}\n"
            f"  Backups dir: {BACKUP_DIR}\n"
        )

    # ── Internal helpers ───────────────────────────────────────────

    def _resolve_path(self, path: str) -> Path | None:
        """Resolve a relative path to an absolute path within the project."""
        if not path:
            return None

        # Normalize and resolve
        target = (BASE_DIR / path).resolve()

        # Security: must stay within project root
        try:
            target.relative_to(BASE_DIR)
        except ValueError:
            logger.warning("[SelfModify] Path escape attempt: %s → %s", path, target)
            return None

        return target

    def _backup(self, filepath: Path):
        """Create a timestamped backup of a file."""
        if not filepath.exists():
            return

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        relative = filepath.relative_to(BASE_DIR)
        backup_path = BACKUP_DIR / f"{relative.stem}_{ts}{relative.suffix}"

        # Flatten nested paths
        backup_path = BACKUP_DIR / backup_path.name

        try:
            shutil.copy2(filepath, backup_path)
            logger.info("[SelfModify] Backup: %s → %s", relative, backup_path.name)
        except Exception as e:
            logger.warning("[SelfModify] Backup failed for %s: %s", filepath, e)

    def _log_action(self, action: str, params: dict, result: dict):
        """Append to self_modification_journal.jsonl."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "params": {k: (v[:200] if isinstance(v, str) and len(v) > 200 else v) for k, v in params.items()},
            "success": result.get("success", False),
            "summary": {k: v for k, v in result.items() if k not in ("content", "traceback", "modules")},
        }
        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[SelfModify] Journal write failed: %s", e)
