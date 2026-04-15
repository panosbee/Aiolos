#!/usr/bin/env python3
"""
XDART-Φ API Health Check — Comprehensive endpoint validator.
Hits every safe (read-only) endpoint and reports status.

Usage:
    python healthcheck.py [--port 8000] [--full]

    --full: Also test POST endpoints that trigger LLM calls (slower)
"""

import argparse
import io
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Force UTF-8 output so box-drawing chars and Greek text survive cp1253 terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONUTF8", "1")

# ═══════════════════════════════════════════════
#  ENDPOINT DEFINITIONS
# ═══════════════════════════════════════════════

# (method, path, description, category, needs_full)
ENDPOINTS = [
    # ── Core System ──
    ("GET",  "/xdart/health",                "Health check",                    "CORE",          False),
    ("GET",  "/xdart/self-prompt",            "Self-prompt / character",         "CORE",          False),
    ("GET",  "/xdart/dashboard/data",         "Dashboard data",                  "CORE",          False),
    ("GET",  "/",                             "UI page",                         "CORE",          False),

    # ── Memory & Knowledge ──
    ("GET",  "/xdart/memory",                 "Episodic memory",                 "MEMORY",        False),
    ("GET",  "/xdart/knowledge",              "Knowledge base stats",            "KNOWLEDGE",     False),
    ("GET",  "/xdart/world_context",          "World context",                   "KNOWLEDGE",     False),
    ("GET",  "/xdart/knowledge/external",     "External injected knowledge",     "KNOWLEDGE",     False),

    # ── Intelligence & Briefing ──
    ("GET",  "/xdart/intelligence",           "Intelligence summary",            "INTELLIGENCE",  False),
    ("GET",  "/xdart/briefing",               "Daily briefing",                  "INTELLIGENCE",  False),
    ("GET",  "/xdart/client-profiles",        "Client profiles",                 "INTELLIGENCE",  False),

    # ── Prophecies ──
    ("GET",  "/xdart/prophecies",             "All prophecies",                  "PROPHECIES",    False),
    ("GET",  "/xdart/prophecies/autonomous",  "Autonomous prophecies",           "PROPHECIES",    False),
    ("GET",  "/xdart/accuracy",               "Prediction accuracy (Brier)",     "PROPHECIES",    False),

    # ── Self-Awareness & Evolution ──
    ("GET",  "/xdart/introspection",          "Introspection reports",           "EVOLUTION",     False),
    ("GET",  "/xdart/self-evolution",          "Self-evolution journal",          "EVOLUTION",     False),
    ("GET",  "/xdart/wisdom",                  "Wisdom calibration",              "EVOLUTION",     False),
    ("GET",  "/xdart/overlays",                "Active overlays",                 "EVOLUTION",     False),
    ("GET",  "/xdart/core_changes",            "Core change log",                 "EVOLUTION",     False),

    # ── Governance (NEW) ──
    ("GET",  "/xdart/strategies",              "Cognitive strategies",            "GOVERNANCE",    False),
    ("GET",  "/xdart/logic-sandbox",           "Logic Sandbox registry",         "GOVERNANCE",    False),
    ("GET",  "/xdart/logic-sandbox/proposals", "Sandbox proposals",              "GOVERNANCE",    False),
    ("GET",  "/xdart/principles",              "Dynamic principles",             "GOVERNANCE",    False),
    ("GET",  "/xdart/principles/pending",      "Pending principles",             "GOVERNANCE",    False),
    ("GET",  "/xdart/principles/philosophy",   "Philosophy mode",                "GOVERNANCE",    False),

    # ── Proactive / Patterns ──
    ("GET",  "/xdart/notifications",           "Notifications",                  "PROACTIVE",     False),
    ("GET",  "/xdart/notifications/stats",     "Notification stats",             "PROACTIVE",     False),
    ("GET",  "/xdart/patterns",                "Active patterns",                "PROACTIVE",     False),
    ("GET",  "/xdart/patterns/hot",            "Hot patterns",                   "PROACTIVE",     False),
    ("GET",  "/xdart/patterns/stats",          "Pattern stats",                  "PROACTIVE",     False),

    # ── Curiosity ──
    ("GET",  "/xdart/curiosities",             "Curiosity engine",               "CURIOSITY",     False),
    ("GET",  "/xdart/curiosities/journal",     "Curiosity journal",              "CURIOSITY",     False),

    # ── Multimodal / Cross-system ──
    ("GET",  "/xdart/multimodal/stats",        "Multimodal perception stats",    "MULTIMODAL",    False),
    ("GET",  "/xdart/multimodal/zones",        "Strategic zones",                "MULTIMODAL",    False),
    ("GET",  "/xdart/cross-system/stats",      "Cross-system learning stats",    "CROSS_SYSTEM",  False),

    # ── Web Agent ──
    ("GET",  "/xdart/web/status",              "Web agent status",               "WEB",           False),

    # ── Bayesian Fuzzy Engine ──
    ("GET",  "/xdart/bayesian-fuzzy/templates",  "BFE templates",               "BFE",           False),

    # ═══ POST endpoints (--full only) — these may trigger LLM calls ═══

    # Chat
    ("POST", "/xdart/chat",                    "Chat (test ping)",               "CHAT",          True),

    # Knowledge injection
    ("POST", "/xdart/knowledge/inject",        "Knowledge injection",            "KNOWLEDGE",     True),

    # Notification test
    ("POST", "/xdart/notifications/test",      "Test notification",              "PROACTIVE",     True),

    # Prophecy resolution
    ("POST", "/xdart/resolve-prophecies",      "Resolve prophecies",             "PROPHECIES",    True),
]


# ═══════════════════════════════════════════════
#  REQUEST HELPERS
# ═══════════════════════════════════════════════

def make_request(base_url: str, method: str, path: str, body: dict | None = None, timeout: int = 30) -> tuple[int, dict | str, float]:
    """Make HTTP request. Returns (status_code, response_body, elapsed_seconds)."""
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    data = None
    if body:
        data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, headers=headers, method=method)

    t0 = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout) as resp:
            elapsed = time.perf_counter() - t0
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                body_parsed = json.loads(raw)
            except json.JSONDecodeError:
                body_parsed = raw[:500]
            return resp.status, body_parsed, elapsed
    except HTTPError as e:
        elapsed = time.perf_counter() - t0
        try:
            error_body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            error_body = str(e)
        return e.code, error_body, elapsed
    except URLError as e:
        elapsed = time.perf_counter() - t0
        return 0, f"CONNECTION ERROR: {e.reason}", elapsed
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return 0, f"ERROR: {e}", elapsed


# POST bodies for --full mode
POST_BODIES = {
    "/xdart/chat": {"message": "System health check — respond with just 'OK'", "context": ""},
    "/xdart/knowledge/inject": {
        "title": "Health Check Test Entry",
        "content": "This is an automated health check test entry. It can be safely deleted.",
        "source": "healthcheck.py",
        "domain": "TEST",
    },
    "/xdart/notifications/test": {},
    "/xdart/resolve-prophecies": {},
}


# ═══════════════════════════════════════════════
#  DISPLAY
# ═══════════════════════════════════════════════

# ANSI colors
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def status_color(code: int) -> str:
    if code == 0:
        return RED
    if 200 <= code < 300:
        return GREEN
    if 400 <= code < 500:
        return YELLOW
    return RED


def format_response_summary(body) -> str:
    """Extract a useful one-line summary from the response."""
    if isinstance(body, str):
        return body[:100]
    if isinstance(body, dict):
        # Try common patterns
        if "status" in body:
            return f"status={body['status']}"
        if "count" in body:
            return f"count={body['count']}"
        if "strategies" in body and "stats" in body:
            s = body["stats"]
            return f"strategies={s.get('total',0)} active={s.get('active',0)}"
        if "functions" in body and "stats" in body:
            s = body["stats"]
            return f"functions={s.get('total_registered',0)} proposals={s.get('pending_proposals',0)}"
        if "principles" in body and "stats" in body:
            s = body["stats"]
            return f"principles={s.get('total',0)} active={s.get('active',0)}"
        if "pending" in body:
            p = body["pending"]
            return f"pending={len(p) if isinstance(p, list) else p}"
        if "prophecies" in body:
            return f"prophecies={len(body['prophecies']) if isinstance(body['prophecies'], list) else '?'}"
        if "entries" in body:
            return f"entries={len(body['entries']) if isinstance(body['entries'], list) else body['entries']}"
        if "notifications" in body:
            return f"notifications={len(body['notifications']) if isinstance(body['notifications'], list) else '?'}"
        if "patterns" in body:
            p = body["patterns"]
            return f"patterns={len(p) if isinstance(p, list) else p}"
        if "zones" in body:
            return f"zones={len(body['zones']) if isinstance(body['zones'], list) else '?'}"
        if "current_mode" in body:
            return f"mode={body['current_mode']}"
        if "brier_score" in body:
            return f"brier={body['brier_score']}"
        if "total" in body:
            return f"total={body['total']}"
        # Generic: show keys
        keys = list(body.keys())[:5]
        return f"keys=[{', '.join(keys)}]"
    return str(body)[:100]


def print_header():
    print(f"\n{BOLD}{'='*75}")
    print(f"  XDART-Φ API HEALTH CHECK")
    print(f"{'='*75}{RESET}\n")


def print_category(name: str):
    print(f"\n  {CYAN}{BOLD}── {name} ──{RESET}")


def print_result(desc: str, method: str, path: str, code: int, elapsed: float, summary: str):
    color = status_color(code)
    speed = f"{elapsed:.2f}s"
    if elapsed > 5:
        speed = f"{RED}{speed}{RESET}"
    elif elapsed > 2:
        speed = f"{YELLOW}{speed}{RESET}"
    else:
        speed = f"{DIM}{speed}{RESET}"

    status_str = f"{color}{code}{RESET}" if code else f"{RED}ERR{RESET}"
    print(f"    {status_str}  {speed:>12s}  {desc:<35s} {DIM}{summary[:45]}{RESET}")


# ═══════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="XDART-Φ API Health Check")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--full", action="store_true", help="Also test POST endpoints (triggers LLM calls)")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"

    # Quick connectivity check
    print_header()
    print(f"  Target: {BOLD}{base_url}{RESET}")
    print(f"  Mode:   {'FULL (including POST/LLM)' if args.full else 'READ-ONLY (GET only)'}")

    code, body, elapsed = make_request(base_url, "GET", "/xdart/health", timeout=5)
    if code == 0:
        print(f"\n  {RED}{BOLD}✗ SERVER NOT REACHABLE at {base_url}{RESET}")
        print(f"  {DIM}  Start with: python run.py --server{RESET}\n")
        sys.exit(1)

    print(f"  Server: {GREEN}ONLINE{RESET} ({elapsed:.2f}s)\n")

    # Run all tests
    total = 0
    passed = 0
    failed = 0
    slow = 0
    errors = []
    current_category = None
    t_start = time.perf_counter()

    for method, path, desc, category, needs_full in ENDPOINTS:
        if needs_full and not args.full:
            continue

        if category != current_category:
            current_category = category
            print_category(category)

        total += 1

        post_body = POST_BODIES.get(path) if method == "POST" else None
        timeout = 60 if needs_full else args.timeout

        code, resp_body, elapsed = make_request(base_url, method, path, body=post_body, timeout=timeout)

        summary = format_response_summary(resp_body)
        print_result(desc, method, path, code, elapsed, summary)

        if 200 <= code < 300:
            passed += 1
        else:
            failed += 1
            errors.append((method, path, desc, code, summary))

        if elapsed > 5:
            slow += 1

    total_time = time.perf_counter() - t_start

    # ── Summary ──
    print(f"\n{BOLD}{'='*75}")
    print(f"  RESULTS")
    print(f"{'='*75}{RESET}")
    print(f"  Total:   {total}")
    print(f"  Passed:  {GREEN}{passed}{RESET}")
    print(f"  Failed:  {RED if failed else GREEN}{failed}{RESET}")
    print(f"  Slow:    {YELLOW if slow else GREEN}{slow}{RESET} (>5s)")
    print(f"  Time:    {total_time:.1f}s total")

    if errors:
        print(f"\n  {RED}{BOLD}FAILURES:{RESET}")
        for method, path, desc, code, summary in errors:
            print(f"    {RED}✗{RESET} [{code}] {method} {path} — {desc}")
            print(f"      {DIM}{summary[:80]}{RESET}")

    # Clean up test injection if we did --full
    if args.full:
        make_request(base_url, "DELETE", "/xdart/knowledge/external", timeout=5)

    # Exit code
    pct = (passed / total * 100) if total else 0
    print(f"\n  {'🟢' if failed == 0 else '🔴'} {passed}/{total} endpoints healthy ({pct:.0f}%)\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
