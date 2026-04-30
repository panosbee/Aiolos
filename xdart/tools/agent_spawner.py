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
import re
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
MAX_TOOL_ITERATIONS = 3          # max tool-use loops per agent
MAX_SHELL_ACTIONS_PER_ITER = 12  # cap shell actions executed per iteration


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

# ── Tool instructions injected into every sub-agent that has shell access ──
_TOOL_INSTRUCTIONS = (
    "\n\n--- TOOLS AVAILABLE ---\n"
    "You have access to the local file system via SELF-CLOSING XML tags.\n"
    "Working directory: project root (XDART-Φ).\n\n"

    "=== ACTIONS ===\n\n"

    "1. READ FILE (preferred for inspecting code):\n"
    '   <SHELL_ACTION action="read_file" path="xdart/proactive.py" />\n\n'

    "2. LIST DIRECTORY (always do this BEFORE guessing filenames):\n"
    '   <SHELL_ACTION action="list_dir" path="xdart" />\n'
    '   <SHELL_ACTION action="list_dir" path="xdart/tools" />\n\n'

    "3. RUN PYTHON (preferred for search and data processing):\n"
    '   <SHELL_ACTION action="python" code="import os; print(os.listdir(\'xdart\'))" />\n\n'
    "   Search inside files (BEST method — use this instead of PowerShell grep):\n"
    '   <SHELL_ACTION action="python" code="'
    "import pathlib; [print(f'{p}:{i+1}: {l.strip()}') "
    "for p in pathlib.Path('xdart').rglob('*.py') "
    "for i,l in enumerate(p.read_text(encoding='utf-8').splitlines()) "
    "if 'hypothesis' in l.lower()]"
    '" />\n\n'

    "4. RUN POWERSHELL:\n"
    "   Search in specific folder (use -Path with folder\\*.ext, NEVER .\\*):\n"
    '   <SHELL_ACTION action="execute" command="Select-String -Path xdart\\*.py -Pattern \'prophecy\' -CaseSensitive:$false" />\n\n'
    "   Search recursively (use Get-ChildItem piped to Select-String):\n"
    '   <SHELL_ACTION action="execute" command="Get-ChildItem -Path xdart -Recurse -Filter *.py | Select-String -Pattern \'hypothesis\' | Select-Object -First 20" />\n\n'
    "   Read first N lines of a file:\n"
    '   <SHELL_ACTION action="execute" command="Get-Content -Path xdart\\proactive.py -TotalCount 50" />\n\n'
    "   Read last N lines of a file:\n"
    '   <SHELL_ACTION action="execute" command="Get-Content -Path logs.txt -Tail 30" />\n\n'
    "   Count lines matching a pattern:\n"
    '   <SHELL_ACTION action="execute" command="(Get-ChildItem -Path xdart -Recurse -Filter *.py | Select-String -Pattern \'def \').Count" />\n\n'
    "   List files by size:\n"
    '   <SHELL_ACTION action="execute" command="Get-ChildItem -Path xdart -Recurse -Filter *.py | Sort-Object Length -Descending | Select-Object Name, Length -First 10" />\n\n'
    "   POWERSHELL PITFALLS:\n"
    "   - Select-String returns exit=1 when NO matches found. This is NORMAL, not an error.\n"
    "   - NEVER search .\\* (all files) — too slow, will timeout. Target specific folders.\n"
    "   - Use -First N to limit output. Unbounded searches can be huge.\n"
    "   - Use backslash \\ for paths, not forward slash.\n"
    "   - Wrap patterns in single quotes, not double quotes.\n\n"

    "=== PROJECT STRUCTURE (working directory = project root) ===\n"
    "\n"
    "── ROOT FILES ──\n"
    "run.py                          — entry point (python run.py -s --reload)\n"
    ".env                            — API keys and secrets\n"
    "requirements.txt                — Python dependencies\n"
    "logs.txt                        — live server log\n"
    "ui.html                         — main chat UI\n"
    "dashboard.html                  — analytics dashboard\n"
    "\n"
    "── STATE FILES (JSON, root) ──\n"
    "character_state.json            — Αίολος personality & cognitive state\n"
    "entity_graph.json               — 19K+ entities, 70K+ edges (NetworkX DiGraph)\n"
    "hypothesis_state.json           — persistent hypotheses\n"
    "curiosity_state.json            — curiosity loop state\n"
    "logic_sandbox_state.json        — logic sandbox state\n"
    "temporal_state.json             — temporal reasoning state\n"
    "cross_system_cache.json         — cross-system learning cache\n"
    "immediate_memory.json           — short-term memory buffer\n"
    "prompt_overlays.json            — prompt overlay configs\n"
    "cognitive_strategies.json       — cognitive strategy configs\n"
    "principle_registry.json         — principle registry\n"
    "wisdom_calibration.json         — calibration data\n"
    "self_awareness_brief.json       — self-awareness snapshot\n"
    "visual_predictions.json         — visual prediction state\n"
    "face_name_registry.json         — known faces\n"
    "\n"
    "── JOURNALS (JSONL, root) ──\n"
    "proactive_log.jsonl             — proactive engine events\n"
    "hypothesis_journal.jsonl        — hypothesis lifecycle events\n"
    "curiosity_journal.jsonl         — curiosity exploration logs\n"
    "introspection_log.jsonl         — introspection reports\n"
    "core_change_log.jsonl           — character state changes\n"
    "self_evolution_journal.jsonl    — evolution events\n"
    "reflection_journal.jsonl        — reflection loop logs\n"
    "agent_spawn_journal.jsonl       — sub-agent spawn audit\n"
    "shell_action_journal.jsonl      — shell command audit\n"
    "\n"
    "── xdart/ (main package) ──\n"
    "xdart/core.py                   — XDARTEngine: pipeline, chat, background loops\n"
    "xdart/proactive.py              — PatternAccumulator, DeepFusion, HypothesisEngine, CompoundAlerts, ThematicBridges\n"
    "xdart/api.py                    — FastAPI endpoints (all /xdart/* routes)\n"
    "xdart/llm.py                    — LLM client (DeepSeek chat + embeddings)\n"
    "xdart/models.py                 — Pydantic data models\n"
    "xdart/config.py                 — Settings (from .env)\n"
    "xdart/adversarial.py            — adversarial analysis\n"
    "xdart/health_tracker.py         — health monitoring\n"
    "\n"
    "── xdart/knowledge/ ──\n"
    "xdart/knowledge/entity_graph.py — EntityGraph (NetworkX), entity resolution, alias matching\n"
    "xdart/knowledge/patterns.py     — pattern detection & storage\n"
    "xdart/knowledge/axioms.py       — axiom system\n"
    "xdart/knowledge/views_catalog.py — analytical views\n"
    "xdart/knowledge/historical_kb.py — historical knowledge base\n"
    "xdart/knowledge/cross_system_learning.py — cross-system transfer\n"
    "xdart/knowledge/sanctions.py    — sanctions data\n"
    "xdart/knowledge/event_calendar.py — event calendar\n"
    "xdart/knowledge/mongo.py        — MongoDB helpers\n"
    "\n"
    "── xdart/perception/ ──\n"
    "xdart/perception/collector.py   — DataCollector (RSS + API ingestion)\n"
    "xdart/perception/filter.py      — signal filtering & dedup\n"
    "xdart/perception/feed_catalog.py — RSS feed definitions\n"
    "xdart/perception/financial_feeds.py — financial data feeds\n"
    "xdart/perception/realtime_feeds.py — realtime data sources\n"
    "xdart/perception/context_retriever.py — context retrieval for chat\n"
    "xdart/perception/correlation.py — signal correlation\n"
    "xdart/perception/keyword_spikes.py — keyword spike detection\n"
    "xdart/perception/country_risk.py — country risk scoring\n"
    "xdart/perception/infrastructure.py — infrastructure monitoring\n"
    "xdart/perception/multimodal.py  — multimodal perception\n"
    "xdart/perception/db.py          — SQLite perception DB (perception.db)\n"
    "\n"
    "── xdart/phases/ (pipeline phases) ──\n"
    "xdart/phases/curiosity.py       — curiosity exploration loop\n"
    "xdart/phases/prophecy_resolver.py — prophecy/prediction tracking\n"
    "xdart/phases/prophetic_loop.py  — prophetic scenario generation\n"
    "xdart/phases/scenario_genesis.py — scenario creation\n"
    "xdart/phases/scenario_simulation.py — scenario simulation\n"
    "xdart/phases/scenario_tribunal.py — scenario evaluation\n"
    "xdart/phases/reflection_loop.py — reflection & self-assessment\n"
    "xdart/phases/introspection.py   — introspection reports\n"
    "xdart/phases/xheart.py          — XHEART emotional state\n"
    "xdart/phases/memory.py          — memory management\n"
    "xdart/phases/memory_architecture.py — memory architecture\n"
    "xdart/phases/bayesian_fuzzy.py  — Bayesian fuzzy logic\n"
    "xdart/phases/meta_orchestrator.py — phase orchestration\n"
    "xdart/phases/creative_synthesis.py — creative synthesis\n"
    "xdart/phases/cross_domain.py    — cross-domain analysis\n"
    "xdart/phases/strategic_foresight.py — strategic foresight\n"
    "xdart/phases/executive_brief.py — executive brief generation\n"
    "xdart/phases/wisdom_tracker.py  — wisdom tracking\n"
    "\n"
    "── xdart/tools/ ──\n"
    "xdart/tools/agent_spawner.py    — sub-agent spawner (THIS file)\n"
    "xdart/tools/shell_executor.py   — PowerShell/Python command execution\n"
    "xdart/tools/web_agent.py        — web search agent\n"
    "\n"
    "── xdart/vision/ ──\n"
    "xdart/vision/service.py         — vision analysis service\n"
    "xdart/vision/integration.py     — vision integration\n"
    "\n"
    "── xdart/evolution/ ──\n"
    "xdart/evolution/core.py         — self-evolution engine\n"
    "xdart/evolution/sandbox.py      — evolution sandbox\n"
    "xdart/evolution/self_knowledge.py — self-knowledge\n"
    "\n"
    "── static/ ──\n"
    "static/page-agent.js            — frontend JavaScript\n\n"

    "=== RULES ===\n"
    "- All tags MUST be SELF-CLOSING: <SHELL_ACTION ... />\n"
    "- ALWAYS list_dir BEFORE reading a file you haven't confirmed exists.\n"
    "- NEVER guess filenames — verify first.\n"
    "- For searching code, prefer Python over PowerShell Select-String.\n"
    "- Keep commands focused: search specific directories, not the whole tree.\n"
    "- Python code in the 'code' attribute must be a SINGLE LINE (use ; to chain).\n"
    "- If a command fails, do NOT retry the same command — try a different approach.\n"
    "- After receiving tool results, analyze and continue your task.\n"
    "- IMPORTANT: Use AT MOST 10 SHELL_ACTIONs per response. Be selective.\n"
    "  Too many commands = response gets cut off = wasted work. Plan carefully.\n"
    "--- END TOOLS ---\n"
)

# ── Regex for parsing SHELL_ACTION tags from agent output ──
_SHELL_PATTERN = re.compile(
    r'<SHELL_ACTION\s+((?:[^">/]|"[^"]*")*)\s*/?>',
    re.IGNORECASE | re.DOTALL,
)


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
        shell_executor: Any = None,
    ):
        self.llm = llm_client
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout
        self.shell_executor = shell_executor  # ShellExecutor — gives sub-agents tool access
        self._lock = threading.Lock()
        self._active_count = 0
        self._total_spawned = 0
        self._total_failed = 0
        self._audit_log: list[SpawnRecord] = []
        self._agent_counter = 0

        logger.info(
            "AgentSpawner initialized (max_concurrent=%d, timeout=%ds, shell=%s)",
            max_concurrent, default_timeout, "YES" if shell_executor else "NO",
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
        max_tokens: int = 8000,
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

        # Inject tool instructions if shell_executor is available
        if self.shell_executor:
            system_prompt += _TOOL_INSTRUCTIONS

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

            # ── Tool loop: execute SHELL_ACTION tags and feed results back ──
            if self.shell_executor:
                output = self._run_tool_loop(
                    agent_id, output, system_prompt, user_prompt,
                    temperature, max_tokens,
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

    # ── Tool Loop: execute SHELL_ACTION tags and feed results back ──

    def _run_tool_loop(
        self,
        agent_id: str,
        output: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Parse SHELL_ACTION tags from agent output, execute them,
        and re-prompt the agent with results. Max MAX_TOOL_ITERATIONS rounds."""
        for iteration in range(MAX_TOOL_ITERATIONS):
            matches = list(_SHELL_PATTERN.finditer(output))
            if not matches:
                break  # no tool calls — done

            # Cap shell actions per iteration to avoid massive batches from
            # cut-off responses where the model emitted hundreds of tags.
            if len(matches) > MAX_SHELL_ACTIONS_PER_ITER:
                logger.warning(
                    "[AgentSpawner] %s: %d SHELL_ACTION(s) in iteration %d — "
                    "capping to %d to prevent overload",
                    agent_id, len(matches), iteration + 1, MAX_SHELL_ACTIONS_PER_ITER,
                )
                matches = matches[:MAX_SHELL_ACTIONS_PER_ITER]

            logger.info(
                "[AgentSpawner] %s tool iteration %d: %d SHELL_ACTION(s)",
                agent_id, iteration + 1, len(matches),
            )

            # Execute each SHELL_ACTION and collect results
            tool_results = []
            for match in matches:
                attrs_str = match.group(1)
                attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))
                action = attrs.pop("action", "").strip().lower()
                if not action:
                    continue
                result_text = self._execute_agent_shell_action(action, attrs)
                tool_results.append(f"[{action}] {result_text}")

            if not tool_results:
                break

            # Strip SHELL_ACTION tags from the output
            clean_output = _SHELL_PATTERN.sub("", output)
            clean_output = re.sub(r'\n{3,}', '\n\n', clean_output).strip()

            # Build continuation prompt with tool results
            tool_results_text = "\n\n".join(tool_results)
            continuation = (
                f"Your previous response:\n{clean_output}\n\n"
                f"TOOL RESULTS:\n{tool_results_text}\n\n"
                f"Now continue your analysis using the actual data above. "
                f"Do NOT speculate — use only what the tools returned. "
                f"If you need more data, use another <SHELL_ACTION> tag. "
                f"Otherwise, provide your final answer."
            )

            # Re-prompt the LLM with tool results
            output = self.llm.call(
                system_prompt=system_prompt,
                user_prompt=continuation,
                temperature=temperature,
                max_tokens=max(max_tokens, 16000),  # tool-result responses need more room
                thinking=False,
            )
            logger.info(
                "[AgentSpawner] %s tool iteration %d → %d chars response",
                agent_id, iteration + 1, len(output),
            )

        # Final cleanup: strip any remaining SHELL_ACTION tags
        output = _SHELL_PATTERN.sub("", output)
        return re.sub(r'\n{3,}', '\n\n', output).strip()

    def _execute_agent_shell_action(self, action: str, attrs: dict) -> str:
        """Execute a single SHELL_ACTION for a sub-agent. Returns result text."""
        se = self.shell_executor
        if not se:
            return "✗ shell executor not available"

        try:
            if action == "read_file":
                path = attrs.get("path", "")
                if not path:
                    return "✗ no path specified"
                result = se.read_file(path)
                if result["success"]:
                    return f"📄 {path}:\n{result['stdout'].strip()}"
                return f"✗ read_file({path}): {result.get('stderr', 'failed')}"

            elif action == "list_dir":
                path = attrs.get("path", se.working_dir)
                result = se.list_directory(path)
                if result["success"]:
                    return f"📁 {path}:\n{result['stdout'].strip()}"
                return f"✗ list_dir({path}): {result.get('stderr', 'failed')}"

            elif action == "python":
                code = attrs.get("code", "")
                if not code:
                    return "✗ no code specified"
                timeout = int(attrs.get("timeout", min(se.default_timeout, 30)))
                result = se.execute_python(code, timeout=timeout)
                if result["success"]:
                    return f"🐍 Python:\n{result['stdout'].strip()}"
                return f"✗ Python: {result.get('stderr', result.get('error', 'failed'))}"

            elif action == "execute":
                command = attrs.get("command", "")
                if not command:
                    return "✗ no command specified"
                timeout = int(attrs.get("timeout", min(se.default_timeout, 30)))
                result = se.execute(command, timeout=timeout)
                if result["success"]:
                    return f"🖥️ {command}:\n{result['stdout'].strip()}"
                return f"✗ {command}: {result.get('stderr', result.get('error', 'failed'))}"

            elif action == "system_info":
                result = se.system_info()
                if result["success"]:
                    return f"💻 System Info:\n{result['stdout'].strip()}"
                return f"✗ system_info: {result.get('stderr', 'failed')}"

            else:
                return f"✗ Unknown action: {action}"

        except Exception as e:
            return f"✗ shell({action}) error: {e}"

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
                    max_tokens=agent_spec.get("max_tokens", 8000),
                    temperature=agent_spec.get("temperature", 0.5),
                )
                future_to_idx[future] = i

            try:
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
            except TimeoutError as te:
                # Some agents did not finish within overall_timeout — log and continue.
                # The "fill None slots" block below will mark them as timed out.
                finished = sum(1 for r in results if r is not None)
                logger.warning(
                    "[AgentSpawner] Parallel timeout — %d/%d agents finished (%s)",
                    finished, len(agents), te,
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
        tool_status = "WITH SHELL ACCESS (can read files, run code, grep)" if self.shell_executor else "LLM-only"
        lines = [
            f"AGENT SPAWNER STATUS (sub-agent delegation — REAL tool, you use it regularly):",
            f"  Available roles: {roles}",
            f"  Sub-agent capabilities: {tool_status}",
            f"  Total spawned this session: {stats['total_spawned']} "
            f"(success rate: {stats['success_rate']})",
            f"  Active now: {stats['active_now']}/{stats['max_concurrent']}",
            f"  Format: <SPAWN_AGENT role=\"researcher\" task=\"...\" />",
        ]
        # Show recent spawns so Αίολος remembers what it delegated
        recent = self.get_audit_log(limit=5)
        if recent:
            lines.append("  Your recent agent delegations (these are REAL — you spawned them):")
            for entry in recent:
                status = "✓" if entry.get("success") else "✗"
                lines.append(
                    f"    {status} [{entry.get('timestamp', '?')[:19]}] "
                    f"{entry.get('role', '?')}: {entry.get('task', '?')[:80]} "
                    f"({entry.get('duration_ms', '?')}ms, {entry.get('output_length', 0)} chars)"
                )
        else:
            lines.append("  No agents spawned yet this session — but the tool is ready.")
        return "\n".join(lines)
