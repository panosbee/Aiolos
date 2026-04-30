"""
XDART-Φ × XHEART — External API Manager

Gives Αίολος structured external API management during chat:
  - Register API profiles (name -> base URL, defaults)
  - Register auth profiles (env-backed tokens)
  - Execute HTTP requests with JSON parsing and diagnostics
  - Keep audit logs of all external calls

This is a real networking tool based on httpx.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("xdart.tools.external_api")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROFILE_PATH = BASE_DIR / "external_api_profiles.json"
JOURNAL_PATH = BASE_DIR / "external_api_journal.jsonl"

DEFAULT_TIMEOUT = 25.0
MAX_BODY_CHARS = 12000
AUDIT_MAX = 300


class ExternalAPIManager:
    """Manage external API integrations for chat-time execution."""

    def __init__(self):
        self._lock = threading.Lock()
        self._audit_log: list[dict] = []
        self._calls = 0
        self._errors = 0
        self._boot_time = datetime.now(timezone.utc)
        self._profiles = self._load_profiles()
        logger.info(
            "[ExternalAPI] Initialized (%d apis, %d auth profiles)",
            len(self._profiles.get("apis", {})),
            len(self._profiles.get("auth_profiles", {})),
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

        self._calls += 1
        if not result.get("success"):
            self._errors += 1
        self._log_action(action, params, result)
        return result

    # ── Auth Profiles ───────────────────────────────────────────────

    def set_auth_profile(
        self,
        name: str = "",
        token_env: str = "",
        header: str = "Authorization",
        prefix: str = "Bearer ",
        **_,
    ) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        if not token_env:
            return {"success": False, "error": "token_env is required"}

        profile = {
            "token_env": token_env,
            "header": header or "Authorization",
            "prefix": prefix,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._profiles.setdefault("auth_profiles", {})[name] = profile
        self._save_profiles()

        token_present = bool(os.getenv(token_env, ""))
        return {
            "success": True,
            "name": name,
            "token_env": token_env,
            "token_present": token_present,
            "header": profile["header"],
        }

    def remove_auth_profile(self, name: str = "", **_) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        auth = self._profiles.setdefault("auth_profiles", {})
        if name not in auth:
            return {"success": False, "error": f"auth profile not found: {name}"}
        del auth[name]
        self._save_profiles()
        return {"success": True, "removed": name}

    def list_auth_profiles(self, **_) -> dict:
        auth = self._profiles.get("auth_profiles", {})
        rows = []
        for name, profile in sorted(auth.items()):
            env_name = profile.get("token_env", "")
            rows.append({
                "name": name,
                "token_env": env_name,
                "token_present": bool(os.getenv(env_name, "")),
                "header": profile.get("header", "Authorization"),
            })
        return {"success": True, "count": len(rows), "profiles": rows}

    # ── API Profiles ────────────────────────────────────────────────

    def register_api(
        self,
        name: str = "",
        base_url: str = "",
        default_method: str = "GET",
        auth_profile: str = "",
        timeout: str = "25",
        headers_json: str = "",
        **_,
    ) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        if not base_url:
            return {"success": False, "error": "base_url is required"}

        headers = self._parse_json_obj(headers_json, "headers_json")
        if isinstance(headers, dict) and headers.get("__error__"):
            return {"success": False, "error": headers["__error__"]}

        try:
            timeout_f = max(1.0, min(180.0, float(timeout or "25")))
        except ValueError:
            return {"success": False, "error": "invalid timeout"}

        api_def = {
            "base_url": base_url.rstrip("/"),
            "default_method": (default_method or "GET").upper(),
            "auth_profile": auth_profile,
            "timeout": timeout_f,
            "headers": headers or {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._profiles.setdefault("apis", {})[name] = api_def
        self._save_profiles()

        return {
            "success": True,
            "name": name,
            "base_url": api_def["base_url"],
            "default_method": api_def["default_method"],
            "auth_profile": auth_profile,
            "timeout": timeout_f,
        }

    def remove_api(self, name: str = "", **_) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}
        apis = self._profiles.setdefault("apis", {})
        if name not in apis:
            return {"success": False, "error": f"api profile not found: {name}"}
        del apis[name]
        self._save_profiles()
        return {"success": True, "removed": name}

    def list_apis(self, **_) -> dict:
        apis = self._profiles.get("apis", {})
        rows = []
        for name, api in sorted(apis.items()):
            rows.append({
                "name": name,
                "base_url": api.get("base_url", ""),
                "default_method": api.get("default_method", "GET"),
                "auth_profile": api.get("auth_profile", ""),
                "timeout": api.get("timeout", DEFAULT_TIMEOUT),
            })
        return {"success": True, "count": len(rows), "apis": rows}

    # ── HTTP Calls ──────────────────────────────────────────────────

    def call_api(
        self,
        name: str = "",
        path: str = "",
        method: str = "",
        params_json: str = "",
        headers_json: str = "",
        json_body: str = "",
        data: str = "",
        timeout: str = "",
        **_,
    ) -> dict:
        if not name:
            return {"success": False, "error": "name is required"}

        api = self._profiles.get("apis", {}).get(name)
        if not api:
            return {"success": False, "error": f"api profile not found: {name}"}

        url = self._join_url(api.get("base_url", ""), path)
        eff_method = (method or api.get("default_method", "GET")).upper()
        eff_timeout = timeout or str(api.get("timeout", DEFAULT_TIMEOUT))

        merged_headers = dict(api.get("headers", {}))
        extra_headers = self._parse_json_obj(headers_json, "headers_json")
        if isinstance(extra_headers, dict) and extra_headers.get("__error__"):
            return {"success": False, "error": extra_headers["__error__"]}
        merged_headers.update(extra_headers or {})

        return self.request(
            method=eff_method,
            url=url,
            params_json=params_json,
            headers_json=json.dumps(merged_headers),
            json_body=json_body,
            data=data,
            auth_profile=api.get("auth_profile", ""),
            timeout=eff_timeout,
        )

    def request(
        self,
        method: str = "GET",
        url: str = "",
        params_json: str = "",
        headers_json: str = "",
        json_body: str = "",
        data: str = "",
        auth_profile: str = "",
        timeout: str = "25",
        **_,
    ) -> dict:
        if not url:
            return {"success": False, "error": "url is required"}

        params = self._parse_json_obj(params_json, "params_json")
        if isinstance(params, dict) and params.get("__error__"):
            return {"success": False, "error": params["__error__"]}

        headers = self._parse_json_obj(headers_json, "headers_json")
        if isinstance(headers, dict) and headers.get("__error__"):
            return {"success": False, "error": headers["__error__"]}

        payload = self._parse_json_value(json_body, "json_body")
        if isinstance(payload, dict) and payload.get("__error__"):
            return {"success": False, "error": payload["__error__"]}

        try:
            timeout_f = max(1.0, min(180.0, float(timeout or "25")))
        except ValueError:
            return {"success": False, "error": "invalid timeout"}

        req_headers = dict(headers or {})
        auth_result = self._inject_auth(req_headers, auth_profile)
        if auth_result.get("error"):
            return {"success": False, "error": auth_result["error"]}

        t0 = datetime.now(timezone.utc)
        try:
            with httpx.Client(timeout=timeout_f, follow_redirects=True) as client:
                response = client.request(
                    method=(method or "GET").upper(),
                    url=url,
                    params=params or None,
                    headers=req_headers or None,
                    json=payload if json_body else None,
                    content=data.encode("utf-8") if data else None,
                )
        except Exception as e:
            return {"success": False, "error": f"request failed: {e}"}

        elapsed_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
        body = response.text or ""
        truncated = False
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + f"\n... [TRUNCATED total={len(response.text)} chars]"
            truncated = True

        content_type = response.headers.get("content-type", "")
        parsed_json = None
        if "application/json" in content_type.lower():
            try:
                parsed_json = response.json()
            except Exception:
                parsed_json = None

        result = {
            "success": 200 <= response.status_code < 300,
            "method": (method or "GET").upper(),
            "url": str(response.url),
            "status_code": response.status_code,
            "reason": response.reason_phrase,
            "elapsed_ms": elapsed_ms,
            "content_type": content_type,
            "headers": dict(response.headers),
            "body": body,
            "json": parsed_json,
            "truncated": truncated,
            "auth_profile": auth_profile,
        }
        return result

    # ── Context ─────────────────────────────────────────────────────

    def to_context_string(self) -> str:
        stats = self.get_stats()
        api_count = len(self._profiles.get("apis", {}))
        auth_count = len(self._profiles.get("auth_profiles", {}))
        lines = [
            "EXTERNAL API STATUS (real HTTP integrations):",
            f"  Calls this session: {stats['total_calls']} ({stats['success_rate']} success)",
            f"  Registered APIs: {api_count}",
            f"  Auth profiles: {auth_count}",
            "  Format: <EXTERNAL_API action=\"request\" method=\"GET\" url=\"...\" />",
        ]
        recent = self._audit_log[-4:]
        if recent:
            lines.append("  Recent calls:")
            for r in recent:
                status = "✓" if r.get("success") else "✗"
                lines.append(f"    {status} {r.get('action')} {r.get('summary', '')[:120]}")
        return "\n".join(lines)

    def get_stats(self) -> dict:
        uptime = int((datetime.now(timezone.utc) - self._boot_time).total_seconds())
        success = self._calls - self._errors
        rate = f"{(success / self._calls):.0%}" if self._calls else "N/A"
        return {
            "total_calls": self._calls,
            "total_errors": self._errors,
            "success_rate": rate,
            "uptime_seconds": uptime,
            "audit_size": len(self._audit_log),
        }

    # ── Internal ────────────────────────────────────────────────────

    def _load_profiles(self) -> dict:
        if PROFILE_PATH.exists():
            try:
                data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("apis", {})
                    data.setdefault("auth_profiles", {})
                    return data
            except Exception as e:
                logger.warning("[ExternalAPI] Failed to load profiles: %s", e)
        data = {"apis": {}, "auth_profiles": {}, "updated_at": None}
        PROFILE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

    def _save_profiles(self):
        with self._lock:
            self._profiles["updated_at"] = datetime.now(timezone.utc).isoformat()
            PROFILE_PATH.write_text(
                json.dumps(self._profiles, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def _inject_auth(self, headers: dict, auth_profile: str) -> dict:
        if not auth_profile:
            return {"ok": True}

        profile = self._profiles.get("auth_profiles", {}).get(auth_profile)
        if not profile:
            return {"error": f"auth profile not found: {auth_profile}"}

        env_name = profile.get("token_env", "")
        token = os.getenv(env_name, "")
        if not token:
            return {"error": f"token env var is empty: {env_name}"}

        header_name = profile.get("header", "Authorization")
        prefix = profile.get("prefix", "")
        headers[header_name] = f"{prefix}{token}"
        return {"ok": True}

    def _parse_json_obj(self, raw: str, field_name: str) -> dict:
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                return {"__error__": f"{field_name} must be a JSON object"}
            return obj
        except Exception as e:
            return {"__error__": f"invalid {field_name}: {e}"}

    def _parse_json_value(self, raw: str, field_name: str):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception as e:
            return {"__error__": f"invalid {field_name}: {e}"}

    def _join_url(self, base_url: str, path: str) -> str:
        if not path:
            return base_url
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    def _log_action(self, action: str, params: dict, result: dict):
        safe_params = {}
        for k, v in params.items():
            if not isinstance(v, str):
                safe_params[k] = v
                continue
            if "token" in k.lower() or "authorization" in k.lower():
                safe_params[k] = "[REDACTED]"
            else:
                safe_params[k] = v[:300]

        summary = ""
        if result.get("success"):
            summary = f"{result.get('status_code', '')} {result.get('method', '')} {result.get('url', '')}"
        else:
            summary = str(result.get("error", "failed"))

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "params": safe_params,
            "success": result.get("success", False),
            "summary": summary,
        }

        with self._lock:
            self._audit_log.append(entry)
            if len(self._audit_log) > AUDIT_MAX:
                self._audit_log = self._audit_log[-AUDIT_MAX:]

        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[ExternalAPI] Journal write failed: %s", e)
