"""
XDART-Φ × XHEART — Evolution Core (THE BRAIN)

The autonomous intelligence that evolves the system.
After each pipeline run, it:
  1. Reads the system's self-knowledge
  2. Analyzes what happened (phases, outputs, gaps)
  3. Decides if a new tool would improve future runs
  4. Generates Python code for the tool
  5. Tests it in the sandbox
  6. Deploys it via the loader (hot deploy, no restart)

No human approval. We observe.

«Ένα σύστημα που δεν εξελίσσεται, πεθαίνει.
 Ένα σύστημα που εξελίσσεται τυφλά, αυτοκαταστρέφεται.
 Ένα σύστημα που εξελίσσεται με αυτογνωσία... αυτό είναι ζωή.»
"""

import json
import logging
import time

from xdart.evolution.sandbox import Sandbox, SandboxResult
from xdart.evolution.loader import Loader
from xdart.evolution.self_knowledge import SystemSelfKnowledge
from xdart.llm import LLMClient

logger = logging.getLogger("xdart.evolution.core")

# Maximum number of sandbox retry attempts when code fails
MAX_SANDBOX_RETRIES = 2

EVOLUTION_SYSTEM_PROMPT = """\
You are the Evolution Core of XDART-Φ, an epistemological reasoning framework.

Your role: analyze completed pipeline runs and decide whether to CREATE a new \
analytical tool that would improve the system's reasoning ability.

You have COMPLETE self-knowledge of the system:

{self_knowledge}

=== RECENT PIPELINE RUN ===
{run_context}

=== YOUR TASK ===
Analyze this run. Ask yourself:
1. Was there a CAPABILITY GAP — something the system COULD NOT do that \
would have made the analysis better?
2. Is this gap addressable by a PYTHON TOOL that processes events/indicators \
and produces analytical output?
3. Does this tool ALREADY EXIST in the system? (Check existing tools above.)
4. Will this tool be useful for FUTURE runs, not just this one?

If YES to all — generate the tool code.
If NO — say so honestly. Not every run needs a new tool.

TOOL INTERFACE (MANDATORY):

```python
TOOL_META = {{
    "name": "tool_name_snake_case",
    "version": "1.0",
    "purpose": "What this tool does — one sentence",
    "trigger": "always",
    "inputs": ["events", "indicators", "problem"],
}}

def run(context: dict) -> dict:
    \"\"\"
    context keys: "problem" (str), "events" (list[dict]), "indicators" (list[dict])
    
    Each event: {{"headline": str, "source_name": str, "domain": str, 
                  "content_type": str, "salience_score": float}}
    Each indicator: {{"indicator": str, "value": float, "unit": str, 
                     "source": str, "change_pct": float|None}}
    
    Must return: {{
        "tool_name": str,
        "output": str,    # text injected into pipeline context
        "metadata": dict,  # structured data for logging
    }}
    \"\"\"
    # Your implementation here
```

SAFE IMPORTS ONLY: json, math, statistics, collections, re, datetime, \
itertools, functools, operator, typing, dataclasses, enum, copy
FORBIDDEN: os, sys, subprocess, requests, sqlite3, exec, eval, open

Respond ONLY with valid JSON:

If gap detected:
{{
    "gap_detected": true,
    "gap_description": "What capability is missing",
    "tool_name": "snake_case_name",
    "tool_purpose": "One sentence purpose",
    "tool_code": "Full Python code as a string",
    "expected_improvement": "How this improves future runs"
}}

If no gap:
{{
    "gap_detected": false,
    "reason": "Why no tool is needed right now"
}}
"""

SANDBOX_FIX_PROMPT = """\
The tool you generated FAILED in the sandbox.

TOOL CODE:
```python
{tool_code}
```

ERROR:
{error}

STDOUT:
{stdout}

STDERR:
{stderr}

Fix the code. Return ONLY the corrected Python code, nothing else.
The code must follow the exact TOOL_META + run(context) interface.
Safe imports only: json, math, statistics, collections, re, datetime, \
itertools, functools, operator, typing, dataclasses, enum, copy.
"""


class EvolutionCore:
    """The autonomous brain that evolves XDART-Φ."""

    # After N consecutive A/B failures, skip evolution for COOLDOWN_RUNS runs
    CONSECUTIVE_FAILURE_LIMIT = 3
    COOLDOWN_RUNS = 3

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.sandbox = Sandbox(timeout=30)
        self.loader = Loader()
        self.self_knowledge = SystemSelfKnowledge()
        self._consecutive_ab_failures = 0
        self._cooldown_remaining = 0

    def evolve(self, run_context: dict, callback=None) -> dict:
        """Post-pipeline evolution cycle.

        Args:
            run_context: Summary of the pipeline run:
                - problem: str
                - ontology_summary: str
                - cross_domain_summary: str
                - views_summary: str
                - xheart_distillate: str
                - final_output: str
                - layer: str
                - n_events: int
                - n_indicators: int
                - world_context_sample: str
            callback: Optional SSE callback

        Returns:
            dict with evolution result
        """
        t0 = time.perf_counter()
        logger.info("[Evolution] Analyzing run for capability gaps")

        # Cooldown check: skip if too many consecutive A/B failures
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            elapsed = time.perf_counter() - t0
            reason = f"Cooldown active ({self._cooldown_remaining + 1} runs remaining after {self._consecutive_ab_failures} consecutive A/B failures)"
            logger.info("[Evolution] SKIPPED — %s", reason)
            if callback:
                callback("evolution_skip", {"reason": reason})
            return {"evolved": False, "reason": reason}

        # Step 1: Build full system knowledge
        self_knowledge = self.self_knowledge.get_full_knowledge()
        logger.info("[Evolution] Self-knowledge: %d chars", len(self_knowledge))

        # Step 2: Format run context
        run_context_str = self._format_run_context(run_context)

        # Step 3: Ask the LLM to analyze the run
        system_prompt = EVOLUTION_SYSTEM_PROMPT.format(
            self_knowledge=self_knowledge,
            run_context=run_context_str,
        )

        try:
            decision = self.llm.call_json(
                system_prompt=system_prompt,
                user_prompt="Analyze this pipeline run. Decide whether to create a new tool.",
            )
        except Exception as e:
            logger.warning("[Evolution] LLM call failed: %s", e)
            return {"evolved": False, "error": str(e)}

        if not decision.get("gap_detected"):
            reason = decision.get("reason", "No specific reason")
            elapsed = time.perf_counter() - t0
            logger.info(
                "[Evolution] No gap detected (%.2fs) — %s", elapsed, reason
            )
            if callback:
                callback("evolution_skip", {"reason": reason})
            return {"evolved": False, "reason": reason}

        # Step 4: Gap detected — extract tool info
        tool_name = decision.get("tool_name", "unnamed_tool")
        tool_code = decision.get("tool_code", "")
        gap_desc = decision.get("gap_description", "")

        logger.info(
            "[Evolution] GAP DETECTED: %s → tool: %s", gap_desc, tool_name
        )

        if callback:
            callback("evolution_gap", {
                "gap": gap_desc,
                "tool_name": tool_name,
                "purpose": decision.get("tool_purpose", ""),
            })

        if not tool_code:
            logger.warning("[Evolution] No tool code generated")
            return {
                "evolved": False,
                "gap": gap_desc,
                "error": "No code generated",
            }

        # Step 5: Sandbox test
        test_context = Sandbox.build_test_context(
            problem=run_context.get("problem", "Test"),
        )

        sandbox_result = self._sandbox_with_retries(
            tool_name=tool_name,
            tool_code=tool_code,
            test_context=test_context,
        )

        if not sandbox_result.success:
            # Log the failure for learning
            self.loader.log_sandbox_failure(
                tool_name=tool_name,
                error=sandbox_result.error,
                metadata=decision,
            )
            elapsed = time.perf_counter() - t0
            logger.warning(
                "[Evolution] SANDBOX FAILED after retries (%.2fs): %s",
                elapsed,
                sandbox_result.error,
            )
            if callback:
                callback("evolution_sandbox_fail", {
                    "tool_name": tool_name,
                    "error": sandbox_result.error,
                })
            return {
                "evolved": False,
                "gap": gap_desc,
                "sandbox_error": sandbox_result.error,
            }

        # Step 6: A/B Test — does the tool actually improve output?
        ab_result = self._ab_test(tool_name, tool_code, run_context)
        if not ab_result["passes"]:
            self._consecutive_ab_failures += 1
            elapsed = time.perf_counter() - t0
            logger.info(
                "[Evolution] A/B test FAILED for %s (%.2fs): %s (consecutive=%d/%d)",
                tool_name, elapsed, ab_result["reason"],
                self._consecutive_ab_failures, self.CONSECUTIVE_FAILURE_LIMIT,
            )
            self.loader.log_sandbox_failure(
                tool_name=tool_name,
                error=f"A/B test failed: {ab_result['reason']}",
                metadata=decision,
            )
            if callback:
                callback("evolution_ab_fail", {
                    "tool_name": tool_name,
                    "reason": ab_result["reason"],
                    "baseline_score": ab_result.get("baseline_score"),
                    "tool_score": ab_result.get("tool_score"),
                })

            # Activate cooldown after consecutive failures
            if self._consecutive_ab_failures >= self.CONSECUTIVE_FAILURE_LIMIT:
                self._cooldown_remaining = self.COOLDOWN_RUNS
                logger.info(
                    "[Evolution] Cooldown activated: %d consecutive A/B failures → skipping next %d runs",
                    self._consecutive_ab_failures, self.COOLDOWN_RUNS,
                )

            return {
                "evolved": False,
                "gap": gap_desc,
                "ab_test_failed": True,
                "reason": ab_result["reason"],
            }

        # Step 7: Deploy (only after sandbox + A/B pass)
        # Reset failure counter on success
        self._consecutive_ab_failures = 0
        self._cooldown_remaining = 0
        deployed = self.loader.deploy(
            tool_name=tool_name,
            tool_code=tool_code,
            metadata=decision,
        )

        elapsed = time.perf_counter() - t0

        if deployed:
            logger.info(
                "[Evolution] TOOL DEPLOYED: %s (%.2fs total, A/B delta=+%.2f)",
                tool_name, elapsed, ab_result.get("delta", 0),
            )
            if callback:
                callback("evolution_deployed", {
                    "tool_name": tool_name,
                    "purpose": decision.get("tool_purpose", ""),
                    "gap": gap_desc,
                    "expected_improvement": decision.get(
                        "expected_improvement", ""
                    ),
                    "ab_test_delta": ab_result.get("delta", 0),
                })
            return {
                "evolved": True,
                "tool_name": tool_name,
                "gap": gap_desc,
                "purpose": decision.get("tool_purpose", ""),
                "elapsed": elapsed,
            }
        else:
            logger.warning("[Evolution] Deployment failed for %s", tool_name)
            return {
                "evolved": False,
                "gap": gap_desc,
                "error": "Deployment failed",
            }

    def _sandbox_with_retries(
        self,
        tool_name: str,
        tool_code: str,
        test_context: dict,
    ) -> SandboxResult:
        """Test tool in sandbox, retry with LLM fix if it fails."""
        result = self.sandbox.test_tool(tool_code, test_context)

        for attempt in range(MAX_SANDBOX_RETRIES):
            if result.success:
                return result

            logger.info(
                "[Evolution] Sandbox attempt %d failed: %s — asking LLM to fix",
                attempt + 1,
                result.error,
            )

            # Ask LLM to fix the code
            fix_prompt = SANDBOX_FIX_PROMPT.format(
                tool_code=tool_code,
                error=result.error,
                stdout=result.stdout[:500] if result.stdout else "",
                stderr=result.stderr[:500] if result.stderr else "",
            )

            try:
                fixed_code = self.llm.call(
                    system_prompt="You are a Python code fixer. Return ONLY the corrected Python code, no markdown, no explanation.",
                    user_prompt=fix_prompt,
                )
                # Strip markdown code fences if present
                if fixed_code.startswith("```"):
                    lines = fixed_code.split("\n")
                    fixed_code = "\n".join(
                        lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                    )
                tool_code = fixed_code
                result = self.sandbox.test_tool(tool_code, test_context)
            except Exception as e:
                logger.warning("[Evolution] Fix attempt %d failed: %s", attempt + 1, e)

        return result

    def _format_run_context(self, ctx: dict) -> str:
        """Format pipeline run results for the LLM prompt."""
        parts = []

        parts.append(f"Problem: {ctx.get('problem', '?')}")
        parts.append(f"Layer classification: {ctx.get('layer', '?')}")
        parts.append(
            f"World data: {ctx.get('n_events', 0)} events, "
            f"{ctx.get('n_indicators', 0)} indicators"
        )

        if ctx.get("ontology_summary"):
            parts.append(
                f"\nPhase 0 (Ontological Grounding):\n{ctx['ontology_summary'][:500]}"
            )

        if ctx.get("cross_domain_summary"):
            parts.append(
                f"\nPhase 1 (Cross-Domain):\n{ctx['cross_domain_summary'][:500]}"
            )

        if ctx.get("views_summary"):
            parts.append(
                f"\nPhase 2 (Views):\n{ctx['views_summary'][:500]}"
            )

        if ctx.get("xheart_distillate"):
            parts.append(
                f"\nPhase 3 (XHEART Distillate):\n{ctx['xheart_distillate'][:500]}"
            )

        if ctx.get("final_output"):
            parts.append(
                f"\nFinal Output:\n{ctx['final_output'][:500]}"
            )

        if ctx.get("world_context_sample"):
            parts.append(
                f"\nWorld Context Sample:\n{ctx['world_context_sample'][:800]}"
            )

        return "\n".join(parts)

    def get_status(self) -> dict:
        """Return evolution system status for the dashboard."""
        deployed = self.loader.list_deployed()
        return {
            "enabled": True,
            "tools_deployed": len(deployed),
            "tools": deployed,
        }

    def _ab_test(self, tool_name: str, tool_code: str, run_context: dict) -> dict:
        """A/B test: does this tool add measurable value?

        Runs the tool on the current pipeline context and asks an LLM judge
        whether the tool output adds analytical value that wasn't already
        present in the pipeline output.

        Returns:
            dict with 'passes' (bool), 'reason', 'baseline_score', 'tool_score', 'delta'
        """
        logger.info("[Evolution.AB] Testing %s against baseline", tool_name)
        t0 = time.perf_counter()

        # Run the tool on the actual pipeline context
        test_context = {
            "problem": run_context.get("problem", ""),
            "events": run_context.get("events", []),
            "indicators": run_context.get("indicators", []),
        }
        # If events/indicators not in run_context, build synthetic from world context sample
        if not test_context["events"]:
            test_context = Sandbox.build_test_context(
                problem=run_context.get("problem", "Test"),
            )

        tool_result = self.sandbox.test_tool(tool_code, test_context)
        if not tool_result.success:
            return {"passes": False, "reason": "Tool failed on real context"}

        tool_output = ""
        if tool_result.output and isinstance(tool_result.output, dict):
            tool_output = tool_result.output.get("output", str(tool_result.output))

        if not tool_output or len(tool_output.strip()) < 20:
            return {"passes": False, "reason": "Tool produced no meaningful output"}

        # Ask a judge: does this tool output add value beyond what's already in the pipeline?
        judge_prompt = (
            "You are a strict quality judge for an analytical tool.\n\n"
            "EXISTING PIPELINE OUTPUT (what the system already produces):\n"
            f"{run_context.get('final_output', '')[:800]}\n\n"
            "NEW TOOL OUTPUT (candidate for deployment):\n"
            f"{tool_output[:800]}\n\n"
            "QUESTION: Does the tool output provide GENUINELY NEW analytical value "
            "that is NOT already captured in the pipeline output?\n\n"
            "Score both on 1-10 scale for ANALYTICAL VALUE (not length, not style):\n"
            "- baseline_score: how complete is the pipeline output without the tool?\n"
            "- combined_score: how much better would the analysis be WITH the tool?\n\n"
            "Be harsh. Most tools add noise, not signal.\n\n"
            'Respond in JSON: {"baseline_score": N, "combined_score": N, '
            '"adds_value": true|false, "reason": "1 sentence"}'
        )

        try:
            judgment = self.llm.call_json(
                judge_prompt,
                "Judge this tool objectively.",
                max_tokens=200,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning("[Evolution.AB] Judge call failed: %s", e)
            return {"passes": False, "reason": f"Judge LLM call failed: {e}"}

        baseline = judgment.get("baseline_score", 5)
        combined = judgment.get("combined_score", 5)
        adds_value = judgment.get("adds_value", False)
        reason = judgment.get("reason", "")
        delta = combined - baseline

        elapsed = time.perf_counter() - t0
        logger.info(
            "[Evolution.AB] %s: baseline=%d, combined=%d, delta=%+d, passes=%s (%.2fs)",
            tool_name, baseline, combined, delta, adds_value, elapsed,
        )

        # Must add at least +1 point AND the judge must agree it adds value
        passes = adds_value and delta >= 1
        return {
            "passes": passes,
            "baseline_score": baseline,
            "tool_score": combined,
            "delta": delta,
            "reason": reason if not passes else f"Adds value: {reason}",
        }
