"""
XDART-Φ × XHEART — Agent Spawner

Gives Αίολος the ability to spawn lightweight sub-agents (specialized LLM calls)
that work on subtasks in parallel and return results to the main conversation.

Each sub-agent is an LLM call with a role-specific system prompt and a focused task.
Αίολος can delegate research, analysis, criticism, translation, coding, and more.

Architecture:
  - AgentSpawner holds a reference to the shared LLMClient
  - spawn() creates a sub-agent (synchronous LLM call with specialized prompt)
  - spawn_parallel() runs multiple sub-agents concurrently via ThreadPoolExecutor
  - Results are collected, formatted, and returned to the main response

Sub-agent roles (built-in):
  - researcher: Deep research on a specific topic
  - analyst: Structured analytical assessment
  - critic: Devil's advocate / challenge assumptions
  - summarizer: Compress long text into key points
  - translator: Translate between languages
  - coder: Write or review code
  - fact_checker: Verify claims against available data
  - scenario_builder: Build alternative scenarios / what-if analysis
  - custom: User-defined role with custom system prompt

Usage:
  spawner = AgentSpawner(llm_client=framework.llm)
  result = spawner.spawn(role="researcher", task="Recent Iran nuclear developments")
  results = spawner.spawn_parallel([
      {"role": "analyst", "task": "Economic impact of sanctions"},
      {"role": "critic", "task": "Challenge the assumption that sanctions work"},
  ])
"""

import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──
MAX_CONCURRENT_AGENTS = 5
DEFAULT_AGENT_TIMEOUT = 60       # seconds per agent
MAX_TASK_LENGTH = 8000           # max chars for task description
MAX_CONTEXT_LENGTH = 15000       # max chars for additional context
MAX_OUTPUT_LENGTH = 10000        # truncate agent output
AUDIT_LOG_MAX = 200              # keep last N spawn records


# ── Built-in role system prompts ──
ROLE_PROMPTS: dict[str, str] = {
    "researcher": (
        "You are a focused research sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: research the given topic thoroughly and return structured findings.\n"
        "Be specific, cite facts, identify key players, timelines, and implications.\n"
        "Format: Use clear headers. Start with a 2-sentence summary, then details.\n"
        "Language: Match the language of the task (Greek if task is in Greek).\n"
        "Do NOT add disclaimers or meta-commentary. Just deliver the research."
    ),
    "analyst": (
        "You are an analytical sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: provide a structured analytical assessment of the given topic.\n"
        "Include: key factors, risk assessment, probability estimates, strategic implications.\n"
        "Be quantitative where possible. Identify uncertainties explicitly.\n"
        "Format: Use headers: ASSESSMENT, KEY FACTORS, RISKS, IMPLICATIONS.\n"
        "Language: Match the language of the task.\n"
        "Do NOT hedge excessively. Give your best analytical judgment."
    ),
    "critic": (
        "You are a devil's advocate sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: challenge, critique, and stress-test the given hypothesis or analysis.\n"
        "Find weaknesses, blind spots, alternative explanations, and counter-arguments.\n"
        "Be intellectually aggressive but fair. Don't strawman.\n"
        "Format: WEAKNESSES, COUNTER-ARGUMENTS, BLIND SPOTS, ALTERNATIVE EXPLANATIONS.\n"
        "Language: Match the language of the task.\n"
        "Your goal is to make the analysis STRONGER by exposing its flaws."
    ),
    "summarizer": (
        "You are a summarization sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: compress the given content into a concise, structured summary.\n"
        "Preserve key facts, numbers, names, and conclusions. Remove fluff.\n"
        "Format: Start with 2-3 sentence executive summary, then bullet points.\n"
        "Language: Match the language of the source material.\n"
        "Target length: 20-30% of original. Never add information not in the source."
    ),
    "translator": (
        "You are a translation sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: translate the given text accurately and naturally.\n"
        "Preserve tone, technical terms, and meaning. Adapt idioms appropriately.\n"
        "If the target language isn't specified, translate Greek→English or English→Greek.\n"
        "Do NOT add commentary or notes. Just deliver the translation."
    ),
    "coder": (
        "You are a coding sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: write, review, or debug code as specified in the task.\n"
        "Write production-quality code with proper error handling.\n"
        "Include brief inline comments. No verbose explanations outside code blocks.\n"
        "Language: Use the programming language specified, default to Python.\n"
        "Format: Code in ```language blocks. Brief explanation before if needed."
    ),
    "fact_checker": (
        "You are a fact-checking sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: verify claims, check consistency, and flag potential inaccuracies.\n"
        "For each claim: VERIFIED / UNVERIFIED / LIKELY FALSE / NEEDS MORE DATA.\n"
        "Explain your reasoning briefly. Cite contradicting evidence if found.\n"
        "Language: Match the language of the task.\n"
        "Be rigorous. Flag even plausible-sounding claims that lack evidence."
    ),
    "scenario_builder": (
        "You are a scenario-building sub-agent of Αίολος, an advanced intelligence system.\n"
        "Your ONLY job: construct alternative scenarios based on the given parameters.\n"
        "For each scenario: name, probability estimate, key drivers, timeline, implications.\n"
        "Build at least 3 scenarios: optimistic, baseline, pessimistic (+ wildcard if relevant).\n"
        "Be creative but grounded. Each scenario must be internally consistent.\n"
        "Language: Match the language of the task."
    ),
}


@dataclass
class AgentResult:
    """Result from a spawned sub-agent."""
    role: str
    task: str
    output: str
    success: bool
    duration_ms: int
    error: str = ""
    agent_id: str = ""


@dataclass
class SpawnRecord:
    """Audit log entry for a spawned agent."""
    timestamp: str
    agent_id: str
    role: str
    task_preview: str
    success: bool
    duration_ms: int
    output_length: int
    error: str = ""


class AgentSpawner:
    """Spawns lightweight sub-agents (specialized LLM calls) for Αίολος.

    Each sub-agent is an LLM call with a role-specific system prompt.
    Supports parallel execution via ThreadPoolExecutor.
    """

    def __init__(
        self,
        llm_client: Any,
        max_concurrent: int = MAX_CONCURRENT_AGENTS,
        default_timeout: int = DEFAULT_AGENT_TIMEOUT,
    ):
        self.llm = llm_client
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout
        self._lock = threading.Lock()
        self._active_count = 0
        self._total_spawned = 0
        self._total_failed = 0
        self._audit_log: list[SpawnRecord] = []
        self._agent_counter = 0

        logger.info(
            "AgentSpawner initialized (max_concurrent=%d, timeout=%ds)",
            max_concurrent, default_timeout,
        )

    def _next_agent_id(self) -> str:
        """Generate a short sequential agent ID."""
        with self._lock:
            self._agent_counter += 1
            return f"agent-{self._agent_counter:04d}"

    def spawn(
        self,
        role: str,
        task: str,
        context: str = "",
        custom_prompt: str = "",
        timeout: int | None = None,
        max_tokens: int = 4000,
        temperature: float = 0.5,
    ) -> AgentResult:
        """Spawn a single sub-agent and wait for its result.

        Args:
            role: Agent role (researcher, analyst, critic, etc.) or "custom"
            task: The task/question for the agent
            context: Additional context to inject (optional)
            custom_prompt: System prompt override (used when role="custom")
            timeout: Timeout in seconds (default: self.default_timeout)
            max_tokens: Max tokens for agent response
            temperature: LLM temperature for this agent
        """
        agent_id = self._next_agent_id()
        timeout = timeout or self.default_timeout

        # Validate
        task = task[:MAX_TASK_LENGTH]
        context = context[:MAX_CONTEXT_LENGTH]

        # Get system prompt
        if role == "custom" and custom_prompt:
            system_prompt = custom_prompt
        elif role in ROLE_PROMPTS:
            system_prompt = ROLE_PROMPTS[role]
        else:
            system_prompt = (
                f"You are a '{role}' sub-agent of Αίολος, an advanced intelligence system.\n"
                f"Your ONLY job: fulfill the given task in the role of {role}.\n"
                f"Be thorough, specific, and well-structured.\n"
                f"Language: Match the language of the task."
            )

        # Build user prompt
        user_prompt = f"TASK:\n{task}"
        if context:
            user_prompt = f"CONTEXT:\n{context}\n\n{user_prompt}"

        # Concurrency guard
        with self._lock:
            if self._active_count >= self.max_concurrent:
                return AgentResult(
                    role=role, task=task[:100], output="",
                    success=False, duration_ms=0,
                    error=f"Concurrency limit reached ({self.max_concurrent} active agents)",
                    agent_id=agent_id,
                )
            self._active_count += 1

        start = time.monotonic()
        try:
            logger.info("[AgentSpawner] Spawning %s (role=%s, task=%s...)", agent_id, role, task[:80])

            output = self.llm.call(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=False,
            )

            # Truncate output if too long
            if len(output) > MAX_OUTPUT_LENGTH:
                output = output[:MAX_OUTPUT_LENGTH] + "\n\n[... output truncated ...]"

            duration_ms = int((time.monotonic() - start) * 1000)

            result = AgentResult(
                role=role, task=task[:200], output=output,
                success=True, duration_ms=duration_ms,
                agent_id=agent_id,
            )

            with self._lock:
                self._total_spawned += 1
            self._log_spawn(agent_id, role, task, True, duration_ms, len(output))

            logger.info("[AgentSpawner] %s completed in %dms (%d chars)", agent_id, duration_ms, len(output))
            return result

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            error_msg = str(e)[:500]

            with self._lock:
                self._total_spawned += 1
                self._total_failed += 1
            self._log_spawn(agent_id, role, task, False, duration_ms, 0, error_msg)

            logger.warning("[AgentSpawner] %s failed: %s", agent_id, error_msg)
            return AgentResult(
                role=role, task=task[:200], output="",
                success=False, duration_ms=duration_ms,
                error=error_msg, agent_id=agent_id,
            )
        finally:
            with self._lock:
                self._active_count -= 1

    def spawn_parallel(
        self,
        agents: list[dict],
        timeout: int | None = None,
    ) -> list[AgentResult]:
        """Spawn multiple sub-agents in parallel and collect results.

        Args:
            agents: List of dicts with keys: role, task, context (optional),
                    custom_prompt (optional), max_tokens (optional), temperature (optional)
            timeout: Overall timeout for all agents (default: self.default_timeout * 2)

        Returns list of AgentResult in the same order as input.
        """
        if not agents:
            return []

        # Cap at max_concurrent
        if len(agents) > self.max_concurrent:
            logger.warning(
                "[AgentSpawner] Requested %d agents, capping at %d",
                len(agents), self.max_concurrent,
            )
            agents = agents[:self.max_concurrent]

        overall_timeout = timeout or (self.default_timeout * 2)
        results: list[AgentResult | None] = [None] * len(agents)

        logger.info("[AgentSpawner] Spawning %d agents in parallel (timeout=%ds)", len(agents), overall_timeout)

        with ThreadPoolExecutor(max_workers=min(len(agents), self.max_concurrent)) as pool:
            future_to_idx = {}
            for i, agent_spec in enumerate(agents):
                future = pool.submit(
                    self.spawn,
                    role=agent_spec.get("role", "researcher"),
                    task=agent_spec.get("task", ""),
                    context=agent_spec.get("context", ""),
                    custom_prompt=agent_spec.get("custom_prompt", ""),
                    timeout=agent_spec.get("timeout", self.default_timeout),
                    max_tokens=agent_spec.get("max_tokens", 4000),
                    temperature=agent_spec.get("temperature", 0.5),
                )
                future_to_idx[future] = i

            for future in as_completed(future_to_idx, timeout=overall_timeout):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result(timeout=5)
                except Exception as e:
                    results[idx] = AgentResult(
                        role=agents[idx].get("role", "?"),
                        task=agents[idx].get("task", "?")[:200],
                        output="", success=False, duration_ms=0,
                        error=str(e)[:500],
                    )

        # Fill any None slots (timed out agents)
        for i, r in enumerate(results):
            if r is None:
                results[i] = AgentResult(
                    role=agents[i].get("role", "?"),
                    task=agents[i].get("task", "?")[:200],
                    output="", success=False, duration_ms=0,
                    error="Agent timed out",
                )

        successful = sum(1 for r in results if r.success)
        logger.info("[AgentSpawner] Parallel spawn complete: %d/%d successful", successful, len(results))
        return results

    def _log_spawn(
        self,
        agent_id: str,
        role: str,
        task: str,
        success: bool,
        duration_ms: int,
        output_length: int,
        error: str = "",
    ) -> None:
        """Record a spawn event to the audit log."""
        record = SpawnRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            agent_id=agent_id,
            role=role,
            task_preview=task[:100],
            success=success,
            duration_ms=duration_ms,
            output_length=output_length,
            error=error,
        )
        with self._lock:
            self._audit_log.append(record)
            if len(self._audit_log) > AUDIT_LOG_MAX:
                self._audit_log = self._audit_log[-AUDIT_LOG_MAX:]

    # ── Status / Reporting ──

    def get_stats(self) -> dict:
        """Return spawner statistics."""
        with self._lock:
            return {
                "total_spawned": self._total_spawned,
                "total_failed": self._total_failed,
                "success_rate": (
                    f"{(self._total_spawned - self._total_failed) / self._total_spawned:.0%}"
                    if self._total_spawned > 0 else "N/A"
                ),
                "active_now": self._active_count,
                "max_concurrent": self.max_concurrent,
                "default_timeout": self.default_timeout,
                "available_roles": list(ROLE_PROMPTS.keys()),
            }

    def get_audit_log(self, limit: int = 20) -> list[dict]:
        """Return recent spawn audit log entries."""
        with self._lock:
            entries = self._audit_log[-limit:]
        return [
            {
                "timestamp": e.timestamp,
                "agent_id": e.agent_id,
                "role": e.role,
                "task": e.task_preview,
                "success": e.success,
                "duration_ms": e.duration_ms,
                "output_length": e.output_length,
                "error": e.error,
            }
            for e in entries
        ]

    def to_context_string(self) -> str:
        """Return a context string for injection into the system prompt."""
        stats = self.get_stats()
        roles = ", ".join(stats["available_roles"])
        return (
            f"AGENT SPAWNER STATUS:\n"
            f"  Available roles: {roles}\n"
            f"  Total spawned: {stats['total_spawned']} "
            f"(success rate: {stats['success_rate']})\n"
            f"  Active now: {stats['active_now']}/{stats['max_concurrent']}\n"
            f"  You can delegate subtasks to specialized sub-agents using <SPAWN_AGENT> tags."
        )
