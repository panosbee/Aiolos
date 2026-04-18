"""
XDART-Φ × XHEART — Core Orchestrator (Prophet Edition)

Η κεντρική κλάση που τρέχει ΟΛΟ το framework:
  Phase 0 → Phase 1 → Phase 1.5 (Creative Synthesis) → Phase 2
  → Phase 2.5 (Scenarios) → Phase 2.7 (Simulation)
  → Phase 2.9 (Tribunal) → Phase 2.91 (Quantum Engine) → Phase 3 (XHEART)
  → Phase 3.5 (Historical Resonance) → Phase 3.7 (Strategic Foresight)
  → Phase 3.9 (Prophetic Bets) → Phase 4 (Memory) → Prophetic Loop

Κάθε φάση τροφοδοτεί την επόμενη. Η Phase 3 κάνει δύο LLM calls:
  A) Internal distillation (δεν φαίνεται στο user)
  B) Final output (γεννιέται ΑΠΟ το distillate, ΟΧΙ από τις φάσεις)

Η μνήμη δεν είναι flat αποθήκη — είναι ΠΕΝΤΕ ΣΤΡΩΜΑΤΑ:
  Αισθητηριακή → Εργαζόμενη → Επεισοδιακή → Σημασιολογική → Διαδικαστική
  + Προφητική Μνήμη (σενάρια με προβλέψεις)
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Any, Generator
from zoneinfo import ZoneInfo

from xdart.config import (
    BASE_DIR, CHARACTER_STATE_PATH, IMMEDIATE_MEMORY_PATH,
    PERCEPTION_ENABLED, PERCEPTION_DB_PATH,
    EVOLUTION_ENABLED, QUANTUM_ENABLED, BAYESIAN_FUZZY_ENABLED,
    WEB_AGENT_ENABLED, LIGHTPANDA_CDP_URL, WEB_AGENT_RESPECT_ROBOTS,
    META_ORCHESTRATOR_ENABLED, CURIOSITY_ENABLED,
    CURIOSITY_JOURNAL_PATH, CURIOSITY_STATE_PATH,
    LOGIC_SANDBOX_ENABLED, PRINCIPLE_REGISTRY_ENABLED,
    SHELL_EXECUTOR_ENABLED, SHELL_EXECUTOR_TIMEOUT,
    AGENT_SPAWNER_ENABLED, AGENT_SPAWNER_MAX_CONCURRENT, AGENT_SPAWNER_TIMEOUT,
)
from xdart.core_change_logger import CoreChangeLogger
from xdart.llm import LLMClient
from xdart.models import (
    BayesianFuzzyResult,
    ClientProfile,
    ExecutiveBrief,
    FrameworkOutput,
    HistoricalParallelAnalysis,
    HistoricalResonanceResult,
    HistoricalVerdict,
    LayerClassification,
    QuantumCollapseResult,
    ScenarioActionMappingResult,
    StrategicForesightResult,
)
from xdart.phases.creative_synthesis import CreativeSynthesisPhase
from xdart.phases.cross_domain import CrossDomainPhase
from xdart.phases.memory import EpisodicMemoryPhase
from xdart.phases.memory_architecture import (
    ProceduralMemory,
    PropheticMemory,
    SemanticMemory,
    SensoryBuffer,
    WorkingMemory,
)
from xdart.phases.ontology import OntologyPhase
from xdart.phases.prophetic_loop import PropheticLoop
from xdart.phases.scenario_genesis import ScenarioGenesisPhase
from xdart.phases.scenario_simulation import ScenarioSimulationPhase
from xdart.phases.scenario_tribunal import ScenarioTribunalPhase
from xdart.phases.self_awareness import SelfAwarenessBrief
from xdart.phases.historical_resonance import HistoricalResonancePhase
from xdart.phases.prophetic_bets import PropheticBetsPhase
from xdart.phases.strategic_foresight import StrategicForesightPhase
from xdart.phases.executive_brief import ExecutiveBriefPhase
from xdart.phases.scenario_actions import ScenarioActionMappingPhase
from xdart.phases.quantum_engine import QuantumScenarioEngine
from xdart.phases.bayesian_fuzzy import BayesianFuzzyEngine
from xdart.phases.introspection import IntrospectionLayer
from xdart.phases.prophecy_resolver import ProphecyResolver
from xdart.adversarial import AdversarialHarness
from xdart.phases.self_evolution import SelfEvolutionLoop
from xdart.phases.overlay_manager import OverlayManager
from xdart.phases.cognitive_strategies import StrategyRegistry, StrategyExecutor
from xdart.phases.curiosity import CuriosityEngine
from xdart.phases.views import ViewsPhase
from xdart.phases.wakeup import WakeupProtocol
from xdart.phases.wisdom_tracker import WisdomCalibrationTracker
from xdart.phases.xheart import XHEARTPhase

logger = logging.getLogger(__name__)


# ── Temporal Clock (εσωτερικό ρολόι — αίσθηση χρόνου) ──

class TemporalClock:
    """Internal clock giving Αίολος continuous temporal awareness.

    Tracks boot time, last activity, uptime, and offline gaps.
    Persists timestamps to disk so offline periods are detectable across restarts.
    """

    _PERSIST_FILE = BASE_DIR / "temporal_state.json"
    _TZ = ZoneInfo("Europe/Athens")

    def __init__(self):
        import json as _json
        self._boot_time = datetime.now(timezone.utc)
        self._last_activity: datetime | None = None
        self._chat_count = 0
        self._last_shutdown: datetime | None = None
        self._offline_seconds: float = 0.0

        # Load previous shutdown timestamp (if exists)
        try:
            if self._PERSIST_FILE.exists():
                data = _json.loads(self._PERSIST_FILE.read_text(encoding="utf-8"))
                ts = data.get("last_shutdown_utc")
                if ts:
                    self._last_shutdown = datetime.fromisoformat(ts)
                    self._offline_seconds = (self._boot_time - self._last_shutdown).total_seconds()
                    if self._offline_seconds < 0:
                        self._offline_seconds = 0.0
                    logger.info(
                        "[Clock] Previous shutdown: %s — offline for %.0fs",
                        self._last_shutdown.isoformat(), self._offline_seconds,
                    )
        except Exception as e:
            logger.warning("[Clock] Could not load temporal state: %s", e)

        # Write current boot time
        self._persist(boot=True)
        logger.info("[Clock] Booted at %s (Athens)", self._boot_time.astimezone(self._TZ).strftime("%H:%M:%S"))

    def tick(self) -> None:
        """Record a new activity (called on each chat/pipeline interaction)."""
        self._last_activity = datetime.now(timezone.utc)
        self._chat_count += 1

    def record_shutdown(self) -> None:
        """Persist shutdown timestamp for offline gap detection on next boot."""
        self._persist(boot=False)
        logger.info("[Clock] Shutdown recorded at %s", datetime.now(timezone.utc).isoformat())

    def _persist(self, boot: bool = False) -> None:
        """Write temporal state to disk."""
        import json as _json
        try:
            data = {
                "boot_time_utc": self._boot_time.isoformat(),
                "last_activity_utc": self._last_activity.isoformat() if self._last_activity else None,
            }
            if not boot:
                data["last_shutdown_utc"] = datetime.now(timezone.utc).isoformat()
            elif self._last_shutdown:
                data["last_shutdown_utc"] = self._last_shutdown.isoformat()
            self._PERSIST_FILE.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("[Clock] Persist failed: %s", e)

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self._boot_time).total_seconds()

    def _fmt_duration(self, seconds: float) -> str:
        """Human-readable duration string."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m {s}s"

    def now_athens(self) -> datetime:
        """Current Athens time — authoritative clock."""
        return datetime.now(self._TZ)

    def to_context_string(self) -> str:
        """Full temporal context for injection into system prompt."""
        now = self.now_athens()
        utc_now = datetime.now(timezone.utc)
        uptime = self.uptime_seconds
        boot_athens = self._boot_time.astimezone(self._TZ)

        lines = [
            f"TEMPORAL AWARENESS (your internal clock — always accurate):",
            f"  Current time: {now.strftime('%A, %d %B %Y, %H:%M:%S')} (Athens/Greece)",
            f"  UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Boot time: {boot_athens.strftime('%H:%M:%S %d/%m/%Y')} (Athens)",
            f"  Uptime: {self._fmt_duration(uptime)} (online continuously since boot)",
            f"  Interactions this session: {self._chat_count}",
        ]

        if self._last_shutdown and self._offline_seconds > 0:
            shutdown_athens = self._last_shutdown.astimezone(self._TZ)
            lines.append(
                f"  Previous shutdown: {shutdown_athens.strftime('%H:%M:%S %d/%m/%Y')} (Athens)"
            )
            lines.append(
                f"  Offline gap: {self._fmt_duration(self._offline_seconds)} "
                f"(you were 'asleep' during this period — no awareness)"
            )
        elif self._last_shutdown is None:
            lines.append("  Previous shutdown: unknown (first boot or state file missing)")

        if self._last_activity:
            last_act_athens = self._last_activity.astimezone(self._TZ)
            idle = (utc_now - self._last_activity).total_seconds()
            lines.append(
                f"  Last interaction: {last_act_athens.strftime('%H:%M:%S')} "
                f"({self._fmt_duration(idle)} ago)"
            )

        return "\n".join(lines)


class XDARTFramework:
    """XDART-Φ × XHEART — Epistemological Architecture for AI Reasoning.

    «Δεν χρειαζόμαστε LLMs που ξέρουν περισσότερα.
     Χρειαζόμαστε LLMs που βλέπουν βαθύτερα.»

    Usage:
        framework = XDARTFramework(api_key="sk-...")
        result = framework.run("Why do organizations fail to change?")
        print(result.final_output)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.llm = LLMClient(api_key=api_key, model=model)

        # Initialize all phases
        self.wakeup = WakeupProtocol(
            character_path=CHARACTER_STATE_PATH,
            immediate_memory_path=IMMEDIATE_MEMORY_PATH,
        )
        self.phase0 = OntologyPhase(self.llm)
        self.phase1 = CrossDomainPhase(self.llm)
        self.phase1_5 = CreativeSynthesisPhase(self.llm)
        self.phase2 = ViewsPhase(self.llm)
        self.phase3 = XHEARTPhase(self.llm)
        self.memory = EpisodicMemoryPhase(self.llm)
        self.self_awareness = SelfAwarenessBrief(self.llm)

        # ── Auto-seed Concept Registry (idempotent — skips if already seeded) ──
        try:
            from seed_concepts import SEED_CONCEPTS
            self.memory.seed_concepts(SEED_CONCEPTS)
        except Exception as e:
            logger.warning("Concept registry auto-seed skipped: %s", e)

        # ── Deep Self-Awareness Modules (αυτογνωσία / αυτοεξέλιξη / σοφία) ──
        self.introspection = IntrospectionLayer(self.llm)
        self.overlay_manager = OverlayManager()
        self.strategy_registry = StrategyRegistry()
        self.strategy_executor = StrategyExecutor(self.llm, self.strategy_registry)
        self.self_evolution = SelfEvolutionLoop(
            self.llm,
            introspection_layer=self.introspection,
            overlay_manager=self.overlay_manager,
            strategy_registry=self.strategy_registry,
        )
        self.wisdom_tracker = WisdomCalibrationTracker(self.llm)
        # Resolver initialized after prophetic_memory is available (set below)
        self.prophecy_resolver = None

        # ── Shared Qdrant Client ──
        # One client, all collections. Avoids embedded-mode storage lock.
        _shared_qdrant = self.memory.shared_qdrant_client

        # ── Prophet Phases (Scenario Pipeline) ──
        self.phase2_5 = ScenarioGenesisPhase(self.llm)
        self.phase2_7 = ScenarioSimulationPhase(self.llm)
        self.phase2_9 = ScenarioTribunalPhase(self.llm)
        self.phase2_95 = ScenarioActionMappingPhase(self.llm)
        self.quantum_engine = QuantumScenarioEngine(self.llm) if QUANTUM_ENABLED else None
        self.bayesian_fuzzy = BayesianFuzzyEngine(self.llm) if BAYESIAN_FUZZY_ENABLED else None
        self.prophetic_loop = PropheticLoop(self.llm)

        # ── Post-XHEART Intelligence Layers ──
        self.phase3_5 = HistoricalResonancePhase(self.llm)
        self.phase3_7 = StrategicForesightPhase(self.llm)
        self.phase3_9 = PropheticBetsPhase(self.llm)
        self.phase3_95 = ExecutiveBriefPhase(self.llm)

        # ── Human-Like Memory Architecture ──
        self.sensory_buffer = SensoryBuffer(llm=self.llm, salience_threshold=0.15)
        self.working_memory = WorkingMemory(capacity=12)
        self.semantic_memory = SemanticMemory(self.llm, qdrant_client=_shared_qdrant)
        self.procedural_memory = ProceduralMemory(self.llm, qdrant_client=_shared_qdrant)
        self.prophetic_memory = PropheticMemory(self.llm, qdrant_client=_shared_qdrant)

        # ── Perception Layer (real-world awareness) ──
        self.world_context = None
        self._external_knowledge: list[dict] = []  # injected via API
        if PERCEPTION_ENABLED:
            try:
                from xdart.perception import PerceptionDB, WorldContextRetriever
                perception_db = PerceptionDB(db_path=PERCEPTION_DB_PATH)
                self.world_context = WorldContextRetriever(db=perception_db, llm=self.llm)
                logger.info("Perception layer enabled (db=%s)", PERCEPTION_DB_PATH)
            except Exception as e:
                logger.warning("Perception layer init failed: %s", e)

        # ── Evolution Core (autonomous self-improvement) ──
        self.evolution_core = None
        self.tool_registry = None
        if EVOLUTION_ENABLED:
            try:
                from xdart.evolution.core import EvolutionCore
                from xdart.tools import ToolRegistry
                self.evolution_core = EvolutionCore(llm=self.llm)
                self.tool_registry = ToolRegistry()
                n_tools = len(self.tool_registry.list_tools())
                logger.info("Evolution Core enabled (%d tools deployed)", n_tools)
            except Exception as e:
                logger.warning("Evolution Core init failed: %s", e)

        # ── Web Agent (browser + search + scrape capabilities) ──
        self.web_agent = None
        if WEB_AGENT_ENABLED:
            try:
                from xdart.tools.web_agent import WebAgent
                self.web_agent = WebAgent(
                    lightpanda_cdp_url=LIGHTPANDA_CDP_URL,
                    respect_robots=WEB_AGENT_RESPECT_ROBOTS,
                )
                logger.info("Web Agent enabled (CDP=%s)", LIGHTPANDA_CDP_URL or "none/httpx-only")
            except Exception as e:
                logger.warning("Web Agent init failed: %s", e)

        # ── Shell Executor (Αίολος' hands — local command execution) ──
        self.shell_executor = None
        if SHELL_EXECUTOR_ENABLED:
            try:
                from xdart.tools.shell_executor import ShellExecutor
                self.shell_executor = ShellExecutor(
                    working_dir=str(BASE_DIR),
                    default_timeout=SHELL_EXECUTOR_TIMEOUT,
                )
                logger.info("Shell Executor enabled (cwd=%s, timeout=%ds)", BASE_DIR, SHELL_EXECUTOR_TIMEOUT)
            except Exception as e:
                logger.warning("Shell Executor init failed: %s", e)

        # ── Agent Spawner (Αίολος' ability to delegate to sub-agents) ──
        self.agent_spawner = None
        if AGENT_SPAWNER_ENABLED:
            try:
                from xdart.tools.agent_spawner import AgentSpawner
                self.agent_spawner = AgentSpawner(
                    llm_client=self.llm,
                    max_concurrent=AGENT_SPAWNER_MAX_CONCURRENT,
                    default_timeout=AGENT_SPAWNER_TIMEOUT,
                )
                logger.info("Agent Spawner enabled (max_concurrent=%d, timeout=%ds)",
                            AGENT_SPAWNER_MAX_CONCURRENT, AGENT_SPAWNER_TIMEOUT)
            except Exception as e:
                logger.warning("Agent Spawner init failed: %s", e)

        logger.info(
            "XDART-Φ initialized (model=%s, memories=%d, prophecies=%d)",
            self.llm.model,
            self.memory.entry_count,
            self.prophetic_memory.entry_count,
        )

        # ── Prophecy Resolver (grounding — closes the Brier loop) ──
        self.prophecy_resolver = ProphecyResolver(
            llm=self.llm,
            prophetic_memory=self.prophetic_memory,
            wisdom_tracker=self.wisdom_tracker,
            world_context=self.world_context,
        )

        # ── Adversarial Harness (grounding — stress-tests analytical robustness) ──
        self.adversarial = AdversarialHarness(framework=self, llm_client=self.llm)

        # ── Curiosity Engine (self-orientation — autonomous knowledge pursuit) ──
        if CURIOSITY_ENABLED:
            self.curiosity_engine = CuriosityEngine(
                llm=self.llm,
                journal_path=CURIOSITY_JOURNAL_PATH,
                state_path=CURIOSITY_STATE_PATH,
            )
            logger.info(
                "Curiosity Engine initialized (%d active, %d explored)",
                self.curiosity_engine.get_stats()["active_count"],
                self.curiosity_engine.get_stats()["total_explored"],
            )
            # Wire curiosity engine into wakeup for identity context injection
            self.wakeup.curiosity_engine = self.curiosity_engine
            # Wire memory stores so explorations consolidate into permanent memory
            self.curiosity_engine.semantic_memory = self.semantic_memory
            self.curiosity_engine.procedural_memory = self.procedural_memory
        else:
            self.curiosity_engine = None
            logger.info("Curiosity Engine: disabled")

        # ── Logic Sandbox (self-modification of algorithmic functions) ──
        self.logic_sandbox = None
        if LOGIC_SANDBOX_ENABLED:
            try:
                from xdart.phases.logic_sandbox import LogicSandbox
                self.logic_sandbox = LogicSandbox(llm=self.llm)
                stats = self.logic_sandbox.get_stats()
                logger.info(
                    "Logic Sandbox enabled (%d functions, %d proposals)",
                    stats["total_functions"], stats["total_proposals"],
                )
            except Exception as e:
                logger.warning("Logic Sandbox init failed: %s", e)

        # ── Dynamic Principle Registry (learned operating principles) ──
        self.principle_registry = None
        if PRINCIPLE_REGISTRY_ENABLED:
            try:
                from xdart.phases.principle_registry import PrincipleRegistry
                self.principle_registry = PrincipleRegistry(llm=self.llm)
                stats = self.principle_registry.get_stats()
                logger.info(
                    "Principle Registry enabled (%d active, %d proposed, %d retired)",
                    stats["active"], stats["proposed"], stats["retired"],
                )
            except Exception as e:
                logger.warning("Principle Registry init failed: %s", e)

        # ── Meta-Orchestrator (adaptive pipeline intelligence) ──
        from xdart.phases.meta_orchestrator import MetaOrchestrator
        self.meta_orchestrator = MetaOrchestrator(
            llm=self.llm,
            enabled=META_ORCHESTRATOR_ENABLED,
        )

        # ── Chat concurrency guard ──
        # Tracks active chat API calls so background tasks can yield priority.
        import threading as _threading
        self._chat_active_count = 0
        self._chat_active_lock = _threading.Lock()

        # ── Chat message dedup (prevents double-processing on client retry) ──
        # hash → timestamp of last processing, 30-second TTL
        self._recent_message_hashes: dict[str, float] = {}
        self._message_dedup_ttl = 30.0  # seconds

        # ── Internal Clock (αίσθηση χρόνου — temporal awareness) ──
        self.temporal_clock = TemporalClock()

        # ── Pipeline running guard ──
        # Prevents proactive alerts from interrupting a running pipeline.
        # Proactive chat requests are deferred and replayed after pipeline completes.
        self._pipeline_running = _threading.Event()
        self._deferred_proactive: list[dict] = []
        self._deferred_lock = _threading.Lock()

        if META_ORCHESTRATOR_ENABLED:
            logger.info("Meta-Orchestrator enabled (adaptive planning + gates + branching)")
        else:
            logger.info("Meta-Orchestrator disabled (linear pipeline)")

    def run(
        self,
        problem: str,
        callback: Any | None = None,
        client_profile: ClientProfile | None = None,
    ) -> FrameworkOutput:
        """Run the full XDART-Φ × XHEART framework.

        The framework decides everything autonomously — no user-controlled
        strategy modes. The whole point is to let the LLM see deeper.

        Args:
            problem:  The problem/question to analyze.
            callback: Optional callable(phase_name, phase_result) for progress.
            client_profile: Who the analysis is FOR — their role, resources,
                            time horizon, risk tolerance, constraints.

        Returns:
            FrameworkOutput with all phase results + distilled output.
        """
        # Prepare client context for downstream phases
        client_context = client_profile.to_context_block() if client_profile else ""

        # ── Mark pipeline as active (blocks proactive chat interruptions) ──
        self._pipeline_running.set()
        # Also tell ProactiveEngine to buffer evaluations (saves LLM tokens)
        if hasattr(self, '_proactive_engine') and self._proactive_engine:
            self._proactive_engine.pipeline_running = True
        logger.info("[Pipeline] Pipeline lock ACQUIRED — proactive alerts will be deferred")

        try:
            return self._run_pipeline(problem, callback, client_profile, client_context)
        finally:
            self._pipeline_running.clear()
            if hasattr(self, '_proactive_engine') and self._proactive_engine:
                self._proactive_engine.pipeline_running = False
                self._proactive_engine.replay_buffered_evaluations()
            logger.info("[Pipeline] Pipeline lock RELEASED")
            # Process any proactive alerts that were deferred during the pipeline
            self._process_deferred_proactive()

    def _run_pipeline(
        self,
        problem: str,
        callback: Any | None,
        client_profile: "ClientProfile | None",
        client_context: str,
    ) -> FrameworkOutput:
        """Inner pipeline logic — separated so run() can wrap with pipeline lock."""

        logger.info("[Pipeline] START — problem=%s model=%s memories=%d prophecies=%d client=%s",
                     problem[:120], self.llm.model, self.memory.entry_count,
                     self.prophetic_memory.entry_count,
                     client_profile.role[:60] if client_profile else "none")

        pipeline_t0 = time.perf_counter()
        phase_times = {}

        # ──────────────────────────────────────────────────────────
        # PARALLEL RETRIEVAL FAN-OUT
        # All independent memory reads + world context run simultaneously.
        # Sequential reads took 15-20s → parallel completes in ~3-5s.
        # ──────────────────────────────────────────────────────────
        retrieval_t0 = time.perf_counter()

        self.sensory_buffer.clear()
        self.working_memory.clear()
        self.working_memory.set_focus(problem)

        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="xdart-retrieval") as pool:
            f_wakeup = pool.submit(self.wakeup.run)
            f_brief = pool.submit(self.self_awareness.load)
            f_episodic = pool.submit(self.memory.retrieve, problem)
            f_concepts = pool.submit(
                self.memory.retrieve_concepts, query=problem, top_k=2, threshold=0.30,
            )
            f_prophetic = pool.submit(self.prophetic_memory.retrieve, problem, 5)
            f_semantic = pool.submit(self.semantic_memory.retrieve, problem, 3)
            f_procedural = pool.submit(self.procedural_memory.retrieve_applicable, problem, 3)
            f_focus = pool.submit(self.sensory_buffer.set_problem_focus, problem)
            f_world = (
                pool.submit(self.world_context.retrieve, problem)
                if self.world_context else None
            )

        # ── Unpack: Wakeup ──
        wakeup_result = f_wakeup.result()
        identity_context = wakeup_result["identity_context"]
        character_state = wakeup_result["character"]

        if callback:
            callback("wakeup_complete", {
                "version": character_state.get("version", 0),
                "concepts_owned": len(character_state.get("named_concepts_owned", [])),
                "active_tensions": len(character_state.get("active_tensions", [])),
                "changes": len(character_state.get("how_i_have_changed", [])),
                "immediate_runs": len(wakeup_result["immediate_memory"]),
                "epistemic_stance": character_state.get("current_epistemic_stance", "")[:200],
            })

        # ── Unpack: Self-Awareness Brief ──
        current_brief = f_brief.result()
        brief_context = self.self_awareness.to_context_string(current_brief)
        logger.info("[Pipeline] Self-awareness brief loaded (%d chars)", len(brief_context))

        # ── Unpack: Episodic Memory ──
        past_memories = f_episodic.result()
        memory_context = self.memory.format_for_context(past_memories)
        if past_memories:
            logger.info(
                "[Pipeline] Retrieved %d episodic memories (best similarity: %.2f)",
                len(past_memories), past_memories[0].similarity_score,
            )
        else:
            logger.info("[Pipeline] No episodic memories found")

        # ── Unpack: Concept Registry ──
        active_concepts = []
        try:
            active_concepts = f_concepts.result()
            if active_concepts:
                logger.info("[Pipeline] Active concepts: %s", [c["name"] for c in active_concepts])
            else:
                logger.info("[Pipeline] No concepts activated")
        except Exception as e:
            logger.warning("[Pipeline] Concept retrieval failed: %s", e)

        if active_concepts and callback:
            callback("concepts_activated", active_concepts)

        # ── Unpack: Prophetic Memory ──
        past_prophecies = f_prophetic.result()
        if past_prophecies:
            logger.info("[Pipeline] Retrieved %d past scenarios (best: %.2f)",
                        len(past_prophecies), past_prophecies[0].similarity_score)
        else:
            logger.info("[Pipeline] No past scenarios found")

        # ── Unpack: Semantic & Procedural Memory ──
        semantic_entries = f_semantic.result()
        semantic_context = self.semantic_memory.format_for_context(semantic_entries)
        if semantic_entries:
            logger.info("[Pipeline] Semantic memory: %d truths retrieved", len(semantic_entries))

        procedural_patterns = f_procedural.result()
        procedural_context = self.procedural_memory.format_for_context(procedural_patterns)
        if procedural_patterns:
            logger.info("[Pipeline] Procedural memory: %d reasoning patterns activated",
                        len(procedural_patterns))

        # ── Unpack: Focus Embedding ──
        f_focus.result()

        # ── Unpack: World Context ──
        world_context_str = ""
        world_event_ids = []
        wctx = {}
        if f_world:
            try:
                wctx = f_world.result()
                world_context_str = wctx.get("context_string", "")
                world_event_ids = wctx.get("event_ids", [])
                if world_context_str:
                    n_events = len(wctx.get("events", []))
                    n_indicators = len(wctx.get("indicators", []))
                    logger.info(
                        "[Pipeline] FULL World Awareness: %d events + %d indicators → %d chars",
                        n_events, n_indicators, len(world_context_str),
                    )
                    if callback:
                        callback("world_context", {
                            "events": n_events,
                            "indicators": n_indicators,
                            "context_chars": len(world_context_str),
                            "sample": world_context_str[:500],
                        })
                else:
                    logger.info("[Pipeline] World context: no relevant events found")
            except Exception as e:
                logger.warning("[Pipeline] World context retrieval failed: %s", e)

        phase_times["parallel_retrieval"] = time.perf_counter() - retrieval_t0
        logger.info(
            "[Pipeline] PARALLEL RETRIEVAL complete (%.2fs) — "
            "%d memories, %d concepts, %d prophecies, %d truths, %d patterns",
            phase_times["parallel_retrieval"],
            len(past_memories), len(active_concepts), len(past_prophecies),
            len(semantic_entries), len(procedural_patterns),
        )

        # ──────────────────────────────────────────────────────────
        # SENSORY BUFFER PROCESSING (sequential — feeds from parallel results)
        # ──────────────────────────────────────────────────────────
        self.sensory_buffer.intake("input", problem, salience=1.0)

        if past_memories:
            self.sensory_buffer.intake_memories(past_memories, problem)

        if past_prophecies:
            self.sensory_buffer.intake_past_scenarios(past_prophecies, problem)
            if callback:
                callback("prophetic_memories", {
                    "count": len(past_prophecies),
                    "scenarios": [p.entry.scenario.name for p in past_prophecies],
                })

        if semantic_entries:
            for se in semantic_entries:
                self.sensory_buffer.intake(
                    "semantic_echo",
                    f"Known truth: {se.knowledge}",
                    salience=se.confidence * 0.8,
                )

        if procedural_patterns:
            for pp in procedural_patterns:
                self.sensory_buffer.intake(
                    "procedural_echo",
                    f"Auto-pattern: WHEN {pp.trigger_condition} → DO {pp.action}",
                    salience=0.7,
                )

        # ── SENSORY FILTER → WORKING MEMORY ──
        salient_impressions = self.sensory_buffer.filter_salient()
        absorbed = self.working_memory.absorb_from_sensory(salient_impressions)
        self.sensory_buffer.clear()
        logger.info("[Pipeline] Working memory: %d/%d slots filled",
                     len(self.working_memory.items), self.working_memory.capacity)

        if callback:
            callback("working_memory_state", {
                "slots_used": len(self.working_memory.items),
                "capacity": self.working_memory.capacity,
                "focus": self.working_memory.focus,
            })

        # ──────────────────────────────────────────────────────────
        # EVOLUTION TOOLS (uses world context)
        # ──────────────────────────────────────────────────────────
        if self.tool_registry:
            try:
                tool_t0 = time.perf_counter()
                tool_context = {
                    "problem": problem,
                    "events": wctx.get("events", []),
                    "indicators": wctx.get("indicators", []),
                }
                tool_output = self.tool_registry.run_all(tool_context)
                phase_times["evolution_tools"] = time.perf_counter() - tool_t0

                if tool_output:
                    world_context_str += "\n" + tool_output
                    logger.info(
                        "[Pipeline] Evolution tools: +%d chars → world context now %d chars (%.2fs)",
                        len(tool_output),
                        len(world_context_str),
                        phase_times["evolution_tools"],
                    )
                    if callback:
                        callback("evolution_tools_ran", {
                            "tool_output_chars": len(tool_output),
                            "total_context_chars": len(world_context_str),
                        })
                else:
                    logger.info("[Pipeline] Evolution tools: no tools deployed yet")
            except Exception as e:
                logger.warning("[Pipeline] Evolution tools failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # WORLD EVENTS → SENSORY BUFFER
        # ──────────────────────────────────────────────────────────
        if wctx.get("events"):
            self.sensory_buffer.intake_world_events(wctx["events"])
            new_salient = self.sensory_buffer.filter_salient()
            if new_salient:
                self.working_memory.absorb_from_sensory(new_salient)
            self.sensory_buffer.clear()
            logger.info("[Pipeline] World events processed through sensory buffer → working memory: %d/%d",
                       len(self.working_memory.items), self.working_memory.capacity)

        # ──────────────────────────────────────────────────────────
        # EXTERNAL KNOWLEDGE HOOKS (injected via /xdart/knowledge/inject)
        # ──────────────────────────────────────────────────────────
        if self._external_knowledge:
            ext_lines = ["\n=== EXTERNAL KNOWLEDGE (injected by domain experts) ==="]
            for ek in self._external_knowledge:
                ext_lines.append(f"[{ek.get('source', 'unknown')}] {ek.get('content', '')}")
                # Also push into working memory
                self.working_memory.push(
                    item_type="insight",
                    content=f"External: {ek.get('content', '')[:200]}",
                    source=f"external/{ek.get('source', 'unknown')}",
                    relevance=0.9,
                )
            world_context_str += "\n".join(ext_lines)
            logger.info("[Pipeline] External knowledge: %d sources injected into context",
                        len(self._external_knowledge))

        # ──────────────────────────────────────────────────────────
        # PHASE 0.40 — PROPHETIC LOOP (self-evaluation of past predictions)
        # ──────────────────────────────────────────────────────────
        prophetic_loop_result = None
        prophetic_loop_context = ""
        if past_prophecies:
            try:
                pl_t0 = time.perf_counter()
                prophetic_loop_result = self.prophetic_loop.run(
                    problem=problem,
                    past_scenarios=past_prophecies,
                    world_context=world_context_str[:10000],
                )
                phase_times["prophetic_loop"] = time.perf_counter() - pl_t0
                prophetic_loop_context = self.prophetic_loop.format_for_context(prophetic_loop_result)

                # Update tracking status in prophetic memory
                for review in self.prophetic_loop.scenario_reviews:
                    try:
                        self.prophetic_memory.update_tracking_status(
                            entry_id=review.get("scenario_id", ""),
                            new_status=review.get("new_status", "tracking"),
                            reality_check={
                                "checked_at": time.time(),
                                "assessment": review.get("reality_check", ""),
                                "against_problem": problem,
                            },
                        )
                    except Exception:
                        pass

                # Push belief updates into working memory
                for bu in prophetic_loop_result.belief_updates:
                    self.working_memory.push(
                        item_type="insight",
                        content=f"Belief update: {bu}",
                        source="prophetic_loop",
                        relevance=0.85,
                    )

                if callback:
                    callback("prophetic_loop", {
                        "reviewed": prophetic_loop_result.past_scenarios_reviewed,
                        "still_tracking": prophetic_loop_result.still_tracking,
                        "disconfirmed": prophetic_loop_result.disconfirmed,
                        "belief_updates": len(prophetic_loop_result.belief_updates),
                    })

                logger.info("[Pipeline] Prophetic Loop complete (%.2fs)", phase_times["prophetic_loop"])
            except Exception as e:
                logger.warning("[Pipeline] Prophetic Loop failed: %s", e)

        # Build working memory context for injection into phases
        working_memory_context = self.working_memory.format_for_context()

        # ── Minimum data guard ──
        # If collector hasn't gathered enough data, warn but continue.
        MIN_EVENTS_WARN = 300
        n_world_events = len(wctx.get("events", [])) if wctx else 0
        if n_world_events < MIN_EVENTS_WARN:
            logger.warning(
                "[Pipeline] LOW DATA: only %d world events (minimum recommended: %d). "
                "Analysis quality may be degraded. Run the collector longer before pipeline.",
                n_world_events, MIN_EVENTS_WARN,
            )
            if callback:
                callback("low_data_warning", {
                    "events_found": n_world_events,
                    "minimum_recommended": MIN_EVENTS_WARN,
                    "message": f"Only {n_world_events} events available — analysis may be shallow.",
                })

        # ── World context budget enforcement ──
        # DeepSeek has 131K context. System + identity + memory + concepts + wisdom ~20K tokens.
        # World context must leave room. Hard cap at 80K chars (~25K tokens).
        WORLD_CONTEXT_BUDGET = 80_000
        if len(world_context_str) > WORLD_CONTEXT_BUDGET:
            logger.warning(
                "[Pipeline] World context too large: %d chars → truncating to %d chars",
                len(world_context_str), WORLD_CONTEXT_BUDGET,
            )
            world_context_str = world_context_str[:WORLD_CONTEXT_BUDGET] + \
                "\n\n[... world context truncated to fit context window ...]"

        # ──────────────────────────────────────────────────────────
        # META-ORCHESTRATOR: Plan the analysis path
        # (decides which phases to run, at what depth, custom phases, branches)
        # ──────────────────────────────────────────────────────────
        from xdart.phases.meta_orchestrator import MetaOrchestrator

        past_runs_summary = ""
        try:
            import json as _json
            imm = self.wakeup._load_immediate_memory()
            if imm and imm.get("last_runs"):
                past_runs_summary = _json.dumps(imm["last_runs"][-3:], default=str)[:600]
        except Exception:
            pass

        analysis_plan = self.meta_orchestrator.plan(
            problem=problem,
            memory_context=memory_context,
            world_context=world_context_str[:5000],
            past_runs_summary=past_runs_summary,
            has_client_profile=bool(client_context),
            quantum_enabled=bool(self.quantum_engine),
            bayesian_fuzzy_enabled=bool(self.bayesian_fuzzy),
            cognitive_strategies_context=self.strategy_registry.to_context_string(),
        )

        if callback:
            callback("meta_plan", analysis_plan.to_dict())

        logger.info(
            "[Pipeline] META-PLAN: %d phases, %d custom, %d branches, %d strategies — %s",
            len(analysis_plan.phases),
            len(analysis_plan.custom_phases),
            len(analysis_plan.branches),
            len(analysis_plan.activate_strategies),
            analysis_plan.reasoning[:150],
        )

        # Track orchestrator state
        _phases_completed: list[str] = []
        _loop_count = 0
        _custom_count = 0
        _custom_phase_results: list[dict] = []
        _accumulated_context_parts: list[str] = []  # For custom phases & gates
        _branch_merge_result: dict | None = None
        _strategy_results: list[dict] = []          # Cognitive strategy outputs

        # ── Cognitive Strategy Helper ──
        # Resolve activated strategies from the meta-plan
        _activated_strategies = []
        if analysis_plan.activate_strategies:
            for sid in analysis_plan.activate_strategies:
                s = self.strategy_registry.get(sid)
                if s and s.active:
                    _activated_strategies.append(s)
                else:
                    logger.warning("[Pipeline] Strategy '%s' not found or inactive", sid)
            if _activated_strategies:
                logger.info(
                    "[Pipeline] COGNITIVE STRATEGIES activated: %s",
                    [s.name for s in _activated_strategies],
                )
                if callback:
                    callback("cognitive_strategies_activated", {
                        "count": len(_activated_strategies),
                        "strategies": [{"id": s.id, "name": s.name, "injection": s.injection_point} for s in _activated_strategies],
                    })

        def _run_strategies_at(injection_point: str, context: str) -> None:
            """Execute cognitive strategies at a specific injection point."""
            nonlocal _strategy_results
            strategies_at_point = [s for s in _activated_strategies if s.injection_point == injection_point]
            if not strategies_at_point:
                return
            logger.info(
                "[Pipeline] Running %d cognitive strategies at '%s': %s",
                len(strategies_at_point), injection_point,
                [s.name for s in strategies_at_point],
            )
            results = self.strategy_executor.execute_batch(
                strategies=strategies_at_point,
                problem=problem,
                context=context,
                world_context=world_context_str[:3000],
            )
            for r in results:
                _strategy_results.append(r)
                if r.get("analysis"):
                    _accumulated_context_parts.append(
                        f"[Strategy: {r.get('strategy_name', '?')}] {r['analysis'][:500]}"
                    )
                if callback:
                    callback("cognitive_strategy_result", {
                        "strategy_id": r.get("strategy_id"),
                        "strategy_name": r.get("strategy_name"),
                        "key_insights": r.get("key_insights", []),
                        "confidence": r.get("confidence", 0),
                        "effectiveness_self_rating": r.get("effectiveness_self_rating", 0),
                    })

        def _should_run_phase(phase_id: str) -> bool:
            """Check if a phase is in the plan."""
            return phase_id in analysis_plan.phase_ids

        def _get_depth(phase_id: str) -> str:
            """Get configured depth for a phase."""
            return analysis_plan.get_depth(phase_id)

        def _run_gate(phase_id: str, output_summary: str) -> Any:
            """Run reflection gate after a phase. Returns GateVerdict."""
            nonlocal _loop_count, _custom_count
            verdict = self.meta_orchestrator.evaluate_gate(
                phase_id=phase_id,
                phase_output_summary=output_summary,
                problem=problem,
                plan=analysis_plan,
                phases_completed=_phases_completed,
                loop_count=_loop_count,
                custom_count=_custom_count,
            )
            if callback:
                callback("meta_gate", {
                    "phase": phase_id,
                    "action": verdict.action,
                    "confidence": verdict.confidence,
                    "note": verdict.note,
                })
            return verdict

        def _execute_custom_phase(custom_def: dict) -> dict | None:
            """Execute a custom phase and quality-check it."""
            nonlocal _custom_count
            result = self.meta_orchestrator.execute_custom_phase(
                custom_phase=custom_def,
                problem=problem,
                accumulated_context="\n".join(_accumulated_context_parts[-5:]),
                world_context=world_context_str[:2000],
            )
            # Quality gate
            keep = self.meta_orchestrator.evaluate_custom_phase_quality(
                custom_result=result,
                problem=problem,
                accumulated_context="\n".join(_accumulated_context_parts[-3:]),
            )
            _custom_count += 1
            if keep:
                _custom_phase_results.append(result)
                _accumulated_context_parts.append(
                    f"[Custom: {result.get('phase_name', '?')}] "
                    f"{result.get('analysis', '')[:500]}"
                )
                if callback:
                    callback("meta_custom_phase", {
                        "phase_id": result.get("phase_id"),
                        "phase_name": result.get("phase_name"),
                        "key_insights": result.get("key_insights", []),
                        "confidence": result.get("confidence", 0),
                        "kept": True,
                    })
                return result
            else:
                if callback:
                    callback("meta_custom_phase", {
                        "phase_id": custom_def.get("id"),
                        "phase_name": custom_def.get("name"),
                        "kept": False,
                        "reason": "Discarded by quality gate",
                    })
                return None

        def _run_planned_customs_after(phase_id: str) -> None:
            """Execute any planned custom phases whose insert_after matches phase_id."""
            for custom_def in analysis_plan.custom_phases:
                if custom_def.get("insert_after", "") == phase_id:
                    # Only run if not already executed (by a gate injection or earlier call)
                    if custom_def.get("id") not in [r.get("phase_id") for r in _custom_phase_results]:
                        _execute_custom_phase(custom_def)

        # ──────────────────────────────────────────────────────────
        # PROMPT OVERLAY HELPER (αυτο-τροποποίηση — Αίολος overlays)
        # ──────────────────────────────────────────────────────────
        _ovl = self.overlay_manager.get_with_guardrails

        # ──────────────────────────────────────────────────────────
        # PHASE 0 — Ontological Grounding
        # ──────────────────────────────────────────────────────────
        _skip_to_xheart = False  # Gate can set this to jump ahead

        # ── Cognitive Strategies: pre_ontology ──
        _run_strategies_at("pre_ontology", working_memory_context)

        if _should_run_phase("ontology"):
            p0_t0 = time.perf_counter()
            ontology = self.phase0.run(
                problem,
                memory_context=memory_context,
                active_concepts=active_concepts,
                identity_context=identity_context,
                brief_context=brief_context,
                world_context=world_context_str,
                overlay_text=_ovl("ontology"),
            )
            phase_times["phase0"] = time.perf_counter() - p0_t0
            if callback:
                callback("phase0_ontology", ontology)

            logger.info("[Pipeline] Phase 0 complete (%.2fs): reframed → %s",
                         phase_times["phase0"], ontology.reframed_problem[:100])

            # ── Gate: Phase 0 ──
            _phases_completed.append("ontology")
            _accumulated_context_parts.append(f"[Ontology] {ontology.reframed_problem[:300]}")
            gate0 = _run_gate("ontology", MetaOrchestrator.summarize_phase_output("ontology", ontology))
            if gate0.action == "skip_ahead":
                _skip_to_xheart = True
            elif gate0.action == "inject_custom" and gate0.custom_phase:
                _execute_custom_phase(gate0.custom_phase)
            # Execute any planned custom phases after ontology
            if not _skip_to_xheart:
                _run_planned_customs_after("ontology")
        else:
            # Skipped by plan — create minimal ontology
            p0_t0 = time.perf_counter()
            ontology = self.phase0.run(
                problem,
                memory_context=memory_context,
                active_concepts=active_concepts,
                identity_context=identity_context,
                brief_context=brief_context,
                world_context=world_context_str,
                overlay_text=_ovl("ontology"),
            )
            phase_times["phase0"] = time.perf_counter() - p0_t0
            if callback:
                callback("phase0_ontology", ontology)
            logger.info("[Pipeline] Phase 0 complete (%.2fs): reframed → %s",
                         phase_times["phase0"], ontology.reframed_problem[:100])

        # ──────────────────────────────────────────────────────────
        # PHASE 1 — XDART-Φ Cross-Domain Reasoning
        # ──────────────────────────────────────────────────────────
        if _should_run_phase("cross_domain") and not _skip_to_xheart:
            p1_t0 = time.perf_counter()
            cross_domain = self.phase1.run(
                reframed_problem=ontology.reframed_problem,
                original_problem=problem,
                world_context=world_context_str,
            )
            phase_times["phase1"] = time.perf_counter() - p1_t0
            if callback:
                callback("phase1_xdart", cross_domain)

            logger.info(
                "[Pipeline] Phase 1 complete (%.2fs): %d domains, layer=%s, strongest=%s",
                phase_times["phase1"],
                len(cross_domain.domains_analyzed),
                cross_domain.layer.value,
                cross_domain.strongest_analogy.domain,
            )

            # ── Gate: Phase 1 ──
            _phases_completed.append("cross_domain")
            _accumulated_context_parts.append(
                f"[CrossDomain] layer={cross_domain.layer.value}, "
                f"strongest={cross_domain.strongest_analogy.domain}"
            )
            gate1 = _run_gate("cross_domain", MetaOrchestrator.summarize_phase_output("cross_domain", cross_domain))
            if gate1.action == "skip_ahead":
                _skip_to_xheart = True
            elif gate1.action == "loop_back" and gate1.loop_target == "ontology":
                # Re-run ontology with new insight
                _loop_count += 1
                logger.info("[Pipeline] LOOP BACK → re-running ontology with cross-domain insight")
                ontology = self.phase0.run(
                    problem,
                    memory_context=memory_context + f"\n[Cross-domain insight: {cross_domain.strongest_analogy.domain}]",
                    active_concepts=active_concepts,
                    identity_context=identity_context,
                    brief_context=brief_context,
                    world_context=world_context_str,
                    overlay_text=_ovl("ontology"),
                )
                if callback:
                    callback("phase0_ontology_rerun", ontology)
            elif gate1.action == "inject_custom" and gate1.custom_phase:
                _execute_custom_phase(gate1.custom_phase)
            # Execute any planned custom phases after cross_domain
            if not _skip_to_xheart:
                _run_planned_customs_after("cross_domain")
        else:
            p1_t0 = time.perf_counter()
            cross_domain = self.phase1.run(
                reframed_problem=ontology.reframed_problem,
                original_problem=problem,
                world_context=world_context_str,
            )
            phase_times["phase1"] = time.perf_counter() - p1_t0
            if callback:
                callback("phase1_xdart", cross_domain)
            logger.info(
                "[Pipeline] Phase 1 complete (%.2fs): %d domains, layer=%s, strongest=%s",
                phase_times["phase1"],
                len(cross_domain.domains_analyzed),
                cross_domain.layer.value,
                cross_domain.strongest_analogy.domain,
            )

        # ──────────────────────────────────────────────────────────
        # PHASE 1.5 — CREATIVE SYNTHESIS (Domain Fusion → Novel Concepts)
        # ──────────────────────────────────────────────────────────
        cross_domain_summary = self._summarize_cross_domain(cross_domain)
        creative_synthesis = None
        synthesis_context = ""

        if not _skip_to_xheart:
            p15_t0 = time.perf_counter()
            try:
                creative_synthesis = self.phase1_5.run(
                    problem=problem,
                    ontology_summary=self._summarize_ontology(ontology),
                    cross_domain_summary=cross_domain_summary,
                    active_concepts=active_concepts,
                )
                phase_times["phase1_5_synthesis"] = time.perf_counter() - p15_t0

                if creative_synthesis and creative_synthesis.synthesized_concepts:
                    synthesis_context = CreativeSynthesisPhase.summarize(creative_synthesis)

                    # Push synthesized concepts into working memory
                    for sc in creative_synthesis.synthesized_concepts:
                        self.working_memory.push(
                            item_type="synthesis",
                            content=f"Novel concept: {sc.concept_name} — {sc.definition[:200]}",
                            source="phase1_5_synthesis",
                            relevance=0.95,
                        )

                    if callback:
                        callback("phase1_5_synthesis", {
                            "concepts_created": len(creative_synthesis.synthesized_concepts),
                            "metaphors_created": len(creative_synthesis.bridging_metaphors),
                            "hypotheses_created": len(creative_synthesis.emergent_hypotheses),
                            "novelty_score": creative_synthesis.novelty_score,
                            "domains_fused": creative_synthesis.domains_fused,
                            "concept_names": [c.concept_name for c in creative_synthesis.synthesized_concepts],
                        })

                    logger.info(
                        "[Pipeline] Phase 1.5 Creative Synthesis complete (%.2fs): "
                        "%d concepts, novelty=%.2f",
                        phase_times["phase1_5_synthesis"],
                        len(creative_synthesis.synthesized_concepts),
                        creative_synthesis.novelty_score,
                    )
                else:
                    logger.info("[Pipeline] Phase 1.5: no novel concepts synthesized")
            except Exception as e:
                phase_times["phase1_5_synthesis"] = time.perf_counter() - p15_t0
                logger.warning("[Pipeline] Phase 1.5 Creative Synthesis failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 2 — Multiple Views
        # ──────────────────────────────────────────────────────────

        if _should_run_phase("views") and not _skip_to_xheart:
            p2_t0 = time.perf_counter()
            views = self.phase2.run(
                problem=problem,
                reframed_problem=ontology.reframed_problem,
                cross_domain_summary=cross_domain_summary + ("\n\n" + synthesis_context if synthesis_context else ""),
                world_context=world_context_str,
            )
            phase_times["phase2"] = time.perf_counter() - p2_t0
            if callback:
                callback("phase2_views", views)

            logger.info(
                "[Pipeline] Phase 2 complete (%.2fs): %d views applied, dominant=%s",
                phase_times["phase2"],
                len(views.views_applied),
                views.dominant_pattern[:80],
            )

            # ── Gate: Phase 2 ──
            _phases_completed.append("views")
            _accumulated_context_parts.append(f"[Views] dominant={views.dominant_pattern[:200]}")
            gate2 = _run_gate("views", MetaOrchestrator.summarize_phase_output("views", views))
            if gate2.action == "skip_ahead":
                _skip_to_xheart = True
            elif gate2.action == "inject_custom" and gate2.custom_phase:
                _execute_custom_phase(gate2.custom_phase)
            # Execute any planned custom phases after views
            if not _skip_to_xheart:
                _run_planned_customs_after("views")
        else:
            p2_t0 = time.perf_counter()
            views = self.phase2.run(
                problem=problem,
                reframed_problem=ontology.reframed_problem,
                cross_domain_summary=cross_domain_summary + ("\n\n" + synthesis_context if synthesis_context else ""),
                world_context=world_context_str,
            )
            phase_times["phase2"] = time.perf_counter() - p2_t0
            if callback:
                callback("phase2_views", views)
            logger.info(
                "[Pipeline] Phase 2 complete (%.2fs): %d views applied, dominant=%s",
                phase_times["phase2"],
                len(views.views_applied),
                views.dominant_pattern[:80],
            )

        # Push dominant pattern into working memory
        self.working_memory.push(
            item_type="insight",
            content=f"Dominant pattern: {views.dominant_pattern}",
            source="phase2_views",
            relevance=0.9,
        )

        # ──────────────────────────────────────────────────────────
        # PHASE 2.5 — SCENARIO GENESIS (Views → Scenarios)
        # ──────────────────────────────────────────────────────────
        ontology_summary = self._summarize_ontology(ontology)

        # ── Cognitive Strategies: post_ontology + pre_scenario ──
        _run_strategies_at("post_ontology", "\n".join(_accumulated_context_parts[-5:]))
        _run_strategies_at("pre_scenario", "\n".join(_accumulated_context_parts[-5:]))

        # Format past scenarios for context
        past_scenarios_ctx = ""
        if past_prophecies:
            past_scenarios_ctx = "\n".join(
                f"- [{p.entry.scenario.name}] ({p.entry.tracking_status}): "
                f"{p.entry.scenario.predicted_outcome[:150]}"
                for p in past_prophecies[:3]
            )

        # ── Check if orchestrator wants to skip scenario phases ──
        _run_scenarios = _should_run_phase("scenario_genesis") and not _skip_to_xheart

        if _run_scenarios:
            p25_t0 = time.perf_counter()
            scenario_genesis = self.phase2_5.run(
                problem=problem,
                views_result=views,
                ontology_summary=ontology_summary,
                cross_domain_summary=cross_domain_summary,
                world_context=world_context_str,
                past_scenarios_context=past_scenarios_ctx,
                working_memory_context=working_memory_context,
                overlay_text=_ovl("scenario_genesis"),
            )
            phase_times["phase2_5"] = time.perf_counter() - p25_t0
            if callback:
                callback("phase2_5_scenarios", {
                    "count": len(scenario_genesis.scenarios),
                    "names": [s.name for s in scenario_genesis.scenarios],
                    "logic": scenario_genesis.generation_logic,
                })

            logger.info("[Pipeline] Phase 2.5 complete (%.2fs): %d scenarios generated",
                         phase_times["phase2_5"], len(scenario_genesis.scenarios))

            # ── Gate: Scenario Genesis ──
            _phases_completed.append("scenario_genesis")
            _accumulated_context_parts.append(
                f"[Scenarios] {len(scenario_genesis.scenarios)} generated: "
                + ", ".join(s.name for s in scenario_genesis.scenarios[:3])
            )
            gate25 = _run_gate(
                "scenario_genesis",
                f"{len(scenario_genesis.scenarios)} scenarios: "
                + ", ".join(f"{s.name} (conf={s.confidence:.2f})" for s in scenario_genesis.scenarios[:4]),
            )
            if gate25.action == "skip_ahead":
                _skip_to_xheart = True
            elif gate25.action == "inject_custom" and gate25.custom_phase:
                _execute_custom_phase(gate25.custom_phase)
            # Execute any planned custom phases after scenario_genesis
            if not _skip_to_xheart:
                _run_planned_customs_after("scenario_genesis")
        else:
            # Scenario genesis skipped by plan or skip_ahead
            from xdart.models import ScenarioGenesisResult
            scenario_genesis = ScenarioGenesisResult(
                scenarios=[], generation_logic="Skipped by meta-orchestrator plan.",
            )
            phase_times["phase2_5"] = 0.0
            if callback:
                callback("phase2_5_scenarios", {
                    "count": 0, "names": [],
                    "logic": "Skipped by meta-orchestrator",
                })
            logger.info("[Pipeline] Phase 2.5 SKIPPED by meta-orchestrator")

        # ── SCENARIO-DEPENDENT PHASES (skip entirely if 0 scenarios or skip_to_xheart) ──
        if not scenario_genesis.scenarios or _skip_to_xheart:
            logger.warning("[Pipeline] 0 scenarios generated — skipping phases 2.7/2.9/2.95")
            # Create minimal empty results for downstream phases
            from xdart.models import AllSimulationsResult, ScenarioTribunalResult, TribunalVerdict
            simulations = AllSimulationsResult(
                simulations=[],
                simulation_summary="No scenarios were generated — simulation skipped.",
            )
            none_verdict = TribunalVerdict(
                scenario_id="NONE",
                scenario_name="No scenarios generated",
                feasibility_rank=1,
                evidence_strength=0.0,
                internal_consistency=0.0,
                final_score=0.0,
                reasoning="Scenario generation phase produced no scenarios.",
            )
            tribunal = ScenarioTribunalResult(
                verdicts=[],
                dominant_scenario=none_verdict,
                alternative_scenarios=[],
                convergence_points=[],
                divergence_points=[],
                tribunal_synthesis="No scenarios were generated — pipeline ran without scenario intelligence.",
            )
            phase_times["phase2_7"] = 0.0
            phase_times["phase2_9"] = 0.0
            phase_times["phase2_95"] = 0.0
            action_mapping_raw = None
            action_mapping_result = None
            scenario_pipeline_summary = "No scenarios were generated in this run."

            # Notify UI of skipped phases
            if callback:
                callback("phase2_7_simulations", {"count": 0, "summary": "Skipped — no scenarios"})
                callback("phase2_9_tribunal", {
                    "dominant": "N/A", "dominant_score": 0,
                    "alternatives": 0, "convergence_points": [],
                    "synthesis": "Scenario generation failed — no tribunal.",
                })
        else:
            # Push the top scenarios into working memory
            for scenario in scenario_genesis.scenarios[:3]:
                self.working_memory.push(
                    item_type="scenario",
                    content=f"{scenario.name}: {scenario.predicted_outcome[:200]}",
                    source="phase2_5_genesis",
                    relevance=scenario.confidence,
                )

            # Update working memory context for subsequent phases
            working_memory_context = self.working_memory.format_for_context()

            # ──────────────────────────────────────────────────────────
            # PHASE 2.7 — SCENARIO SIMULATION (Forward-Projection)
            # ──────────────────────────────────────────────────────────
            if _should_run_phase("scenario_simulation"):
                p27_t0 = time.perf_counter()
                simulations = self.phase2_7.run(
                    problem=problem,
                    scenarios=scenario_genesis.scenarios,
                    world_context=world_context_str[:15000],
                    working_memory_context=working_memory_context,
                    overlay_text=_ovl("scenario_simulation"),
                )
                phase_times["phase2_7"] = time.perf_counter() - p27_t0
                if callback:
                    callback("phase2_7_simulations", {
                        "count": len(simulations.simulations),
                        "summary": simulations.simulation_summary,
                    })

                logger.info("[Pipeline] Phase 2.7 complete (%.2fs): %d simulations",
                             phase_times["phase2_7"], len(simulations.simulations))
                _phases_completed.append("scenario_simulation")
            else:
                from xdart.models import AllSimulationsResult
                simulations = AllSimulationsResult(
                    simulations=[],
                    simulation_summary="Skipped by meta-orchestrator.",
                )
                phase_times["phase2_7"] = 0.0

            # ──────────────────────────────────────────────────────────
            # PHASE 2.9 — SCENARIO TRIBUNAL (Cross-Comparison)
            # ──────────────────────────────────────────────────────────
            if _should_run_phase("scenario_tribunal"):
                p29_t0 = time.perf_counter()
                tribunal = self.phase2_9.run(
                    problem=problem,
                    genesis=scenario_genesis,
                    simulations=simulations,
                    world_context=world_context_str[:15000],
                    working_memory_context=working_memory_context,
                    overlay_text=_ovl("scenario_tribunal"),
                )
                phase_times["phase2_9"] = time.perf_counter() - p29_t0
                if callback:
                    callback("phase2_9_tribunal", {
                        "dominant": tribunal.dominant_scenario.scenario_name,
                        "dominant_score": tribunal.dominant_scenario.final_score,
                        "alternatives": len(tribunal.alternative_scenarios),
                        "convergence_points": tribunal.convergence_points,
                        "synthesis": tribunal.tribunal_synthesis,
                    })

                logger.info("[Pipeline] Phase 2.9 complete (%.2fs): dominant=%s (%.2f)",
                             phase_times["phase2_9"],
                             tribunal.dominant_scenario.scenario_name,
                             tribunal.dominant_scenario.final_score)

                # ── Gate: Tribunal ──
                _phases_completed.append("scenario_tribunal")
                _accumulated_context_parts.append(
                    f"[Tribunal] dominant={tribunal.dominant_scenario.scenario_name}, "
                    f"synthesis={tribunal.tribunal_synthesis[:200]}"
                )
                gate29 = _run_gate(
                    "scenario_tribunal",
                    f"Dominant: {tribunal.dominant_scenario.scenario_name} "
                    f"(score={tribunal.dominant_scenario.final_score:.2f}). "
                    f"Synthesis: {tribunal.tribunal_synthesis[:300]}",
                )
                if gate29.action == "loop_back" and gate29.loop_target in ("ontology", "views"):
                    _loop_count += 1
                    logger.info("[Pipeline] LOOP BACK from tribunal → %s (insight: %s)",
                                gate29.loop_target, gate29.note[:120])
                    _accumulated_context_parts.append(
                        f"[Gate insight] Tribunal loop-back: {gate29.note}"
                    )
                    # Actually re-run the target phase with tribunal insight
                    tribunal_insight = (
                        f"\n[TRIBUNAL LOOP-BACK INSIGHT] The scenario tribunal revealed: "
                        f"{gate29.note}. Dominant scenario: "
                        f"{tribunal.dominant_scenario.scenario_name} — "
                        f"{tribunal.tribunal_synthesis[:300]}"
                    )
                    if gate29.loop_target == "ontology":
                        logger.info("[Pipeline] Re-running ontology with tribunal insight")
                        ontology = self.phase0.run(
                            problem,
                            memory_context=memory_context + tribunal_insight,
                            active_concepts=active_concepts,
                            identity_context=identity_context,
                            brief_context=brief_context,
                            world_context=world_context_str,
                            overlay_text=_ovl("ontology"),
                        )
                        if callback:
                            callback("phase0_ontology_rerun", ontology)
                        logger.info("[Pipeline] Ontology re-run complete: reframed → %s",
                                     ontology.reframed_problem[:100])
                    elif gate29.loop_target == "views":
                        logger.info("[Pipeline] Re-running views with tribunal insight")
                        cross_domain_summary_with_insight = (
                            cross_domain_summary + tribunal_insight
                        )
                        views = self.phase2.run(
                            problem=problem,
                            reframed_problem=ontology.reframed_problem,
                            cross_domain_summary=cross_domain_summary_with_insight,
                            world_context=world_context_str,
                        )
                        if callback:
                            callback("phase2_views_rerun", views)
                        logger.info("[Pipeline] Views re-run complete: %d views, dominant=%s",
                                     len(views.views_applied), views.dominant_pattern[:80])
                elif gate29.action == "inject_custom" and gate29.custom_phase:
                    _execute_custom_phase(gate29.custom_phase)
                # Execute any planned custom phases after scenario_tribunal
                _run_planned_customs_after("scenario_tribunal")
            else:
                from xdart.models import ScenarioTribunalResult, TribunalVerdict
                none_verdict = TribunalVerdict(
                    scenario_id="NONE",
                    scenario_name="Tribunal skipped",
                    feasibility_rank=1,
                    evidence_strength=0.0,
                    internal_consistency=0.0,
                    final_score=0.0,
                    reasoning="Tribunal skipped by meta-orchestrator.",
                )
                tribunal = ScenarioTribunalResult(
                    verdicts=[],
                    dominant_scenario=none_verdict,
                    alternative_scenarios=[],
                    convergence_points=[],
                    divergence_points=[],
                    tribunal_synthesis="Tribunal phase skipped by meta-orchestrator plan.",
                )
                phase_times["phase2_9"] = 0.0

            # Push tribunal results into working memory
            self.working_memory.push(
                item_type="insight",
                content=f"Tribunal dominant: {tribunal.dominant_scenario.scenario_name} — {tribunal.tribunal_synthesis[:200]}",
                source="phase2_9_tribunal",
                relevance=0.95,
            )
            for cp in tribunal.convergence_points[:2]:
                self.working_memory.push(
                    item_type="insight",
                    content=f"Convergence: {cp}",
                    source="phase2_9_tribunal",
                    relevance=0.88,
                )

            # Build scenario summary for XHEART
            scenario_pipeline_summary = self._summarize_scenario_pipeline(
                scenario_genesis, simulations, tribunal
            )

            # ──────────────────────────────────────────────────────────
            # PHASE 2.91 — QUANTUM SCENARIO ENGINE
            # Superposition → Interference → Measurement → Collapse
            # ──────────────────────────────────────────────────────────
            quantum_collapse: QuantumCollapseResult | None = None
            if (self.quantum_engine and len(scenario_genesis.scenarios) >= 2
                    and _should_run_phase("quantum_engine")):
                p291_t0 = time.perf_counter()
                try:
                    quantum_collapse = self.quantum_engine.run(
                        problem=problem,
                        scenarios=scenario_genesis.scenarios,
                        tribunal=tribunal,
                        simulations=simulations,
                        world_context=world_context_str[:15000],
                    )
                    phase_times["phase2_91_quantum"] = time.perf_counter() - p291_t0
                    if callback:
                        callback("phase2_91_quantum", {
                            "quantum_dominant": quantum_collapse.quantum_dominant_name,
                            "quantum_probability": quantum_collapse.quantum_dominant_probability,
                            "classical_dominant": tribunal.dominant_scenario.scenario_name,
                            "observer_shifted": quantum_collapse.observer_shifted_dominant,
                            "interference_count": len(quantum_collapse.interference_patterns),
                            "hidden_signals": quantum_collapse.hidden_signals,
                            "entanglement_clusters": quantum_collapse.entanglement_clusters,
                            "measurement_basis": quantum_collapse.measurement_basis,
                            "quantum_narrative": quantum_collapse.quantum_narrative,
                            "collapsed_probabilities": quantum_collapse.collapsed_probabilities,
                        })
                    logger.info(
                        "[Pipeline] Phase 2.91 Quantum complete (%.2fs): "
                        "quantum_dominant=%s (P=%.3f), observer_shift=%s, "
                        "%d interference patterns, %d hidden signals",
                        phase_times["phase2_91_quantum"],
                        quantum_collapse.quantum_dominant_name,
                        quantum_collapse.quantum_dominant_probability,
                        quantum_collapse.observer_shifted_dominant,
                        len(quantum_collapse.interference_patterns),
                        len(quantum_collapse.hidden_signals),
                    )
                except Exception as e:
                    phase_times["phase2_91_quantum"] = time.perf_counter() - p291_t0
                    logger.warning("[Pipeline] Phase 2.91 Quantum Engine failed: %s", e)

            # ──────────────────────────────────────────────────────────
            # PHASE 2.92 — BAYESIAN-FUZZY REASONING ENGINE
            # Fuzzy Logic → Bayesian Network → Posterior Risk Quantification
            # ──────────────────────────────────────────────────────────
            bayesian_fuzzy_result: BayesianFuzzyResult | None = None
            if (self.bayesian_fuzzy and len(scenario_genesis.scenarios) >= 2
                    and _should_run_phase("bayesian_fuzzy")):
                p292_t0 = time.perf_counter()
                try:
                    bayesian_fuzzy_result = self.bayesian_fuzzy.run(
                        problem=problem,
                        scenarios=scenario_genesis.scenarios,
                        tribunal=tribunal,
                        world_context=world_context_str[:15000],
                    )
                    phase_times["phase2_92_bayesian_fuzzy"] = time.perf_counter() - p292_t0
                    if callback:
                        callback("phase2_92_bayesian_fuzzy", {
                            "domain": bayesian_fuzzy_result.domain,
                            "dominant_risk_level": bayesian_fuzzy_result.dominant_risk_level,
                            "risk_assessment": bayesian_fuzzy_result.risk_assessment,
                            "key_drivers": bayesian_fuzzy_result.key_drivers,
                            "risk_posteriors": [
                                {
                                    "variable": rp.risk_variable,
                                    "dominant": rp.dominant_level,
                                    "probability": rp.dominant_probability,
                                }
                                for rp in bayesian_fuzzy_result.risk_posteriors
                            ],
                            "causal_chain": bayesian_fuzzy_result.causal_chain,
                            "risk_narrative": bayesian_fuzzy_result.risk_narrative,
                            "missing_data": bayesian_fuzzy_result.missing_data,
                        })
                    logger.info(
                        "[Pipeline] Phase 2.92 Bayesian-Fuzzy complete (%.2fs): "
                        "domain=%s, risk=%s, %d posteriors, %d drivers",
                        phase_times["phase2_92_bayesian_fuzzy"],
                        bayesian_fuzzy_result.domain,
                        bayesian_fuzzy_result.dominant_risk_level,
                        len(bayesian_fuzzy_result.risk_posteriors),
                        len(bayesian_fuzzy_result.key_drivers),
                    )
                except Exception as e:
                    phase_times["phase2_92_bayesian_fuzzy"] = time.perf_counter() - p292_t0
                    logger.warning("[Pipeline] Phase 2.92 Bayesian-Fuzzy failed: %s", e)

            # ──────────────────────────────────────────────────────────
            # PHASE 2.95 — SCENARIO-ACTION MAPPING (Client Playbooks)
            # ──────────────────────────────────────────────────────────
            action_mapping_raw = None
            action_mapping_result = None
            if client_context:
                p295_t0 = time.perf_counter()
                try:
                    # Build scenario narratives lookup
                    scenario_narratives = {}
                    for sc in scenario_genesis.scenarios:
                        scenario_narratives[sc.name] = sc.narrative

                    # Build tribunal verdicts as dicts
                    surviving_verdicts = [
                        {
                            "scenario_id": v.scenario_id,
                            "scenario_name": v.scenario_name,
                            "feasibility_rank": v.feasibility_rank,
                            "final_score": v.final_score,
                            "evidence_strength": v.evidence_strength,
                            "reasoning": v.reasoning,
                        }
                        for v in tribunal.verdicts
                        if v.final_score >= 0.3
                    ]

                    action_mapping_raw = self.phase2_95.run(
                        problem=problem,
                        tribunal_verdicts=surviving_verdicts,
                        dominant_scenario_name=tribunal.dominant_scenario.scenario_name,
                        tribunal_synthesis=tribunal.tribunal_synthesis,
                        scenario_narratives=scenario_narratives,
                        client_context=client_context,
                        world_context=world_context_str[:10000],
                    )
                    phase_times["phase2_95"] = time.perf_counter() - p295_t0

                    # Parse into Pydantic model
                    try:
                        action_mapping_result = ScenarioActionMappingResult(**action_mapping_raw)
                    except Exception:
                        action_mapping_result = ScenarioActionMappingResult(
                            client_role=action_mapping_raw.get("client_role", ""),
                            robust_moves=[],
                            scenario_playbooks=[],
                            elapsed_seconds=action_mapping_raw.get("elapsed_seconds", 0.0),
                        )

                    if callback:
                        callback("phase2_95_actions", {
                            "client_role": action_mapping_raw.get("client_role", ""),
                            "robust_moves": action_mapping_raw.get("robust_moves", []),
                            "scenario_playbooks": action_mapping_raw.get("scenario_playbooks", []),
                        })

                    logger.info(
                        "[Pipeline] Phase 2.95 complete (%.2fs): %d playbooks, %d robust moves",
                        phase_times["phase2_95"],
                        len(action_mapping_raw.get("scenario_playbooks", [])),
                        len(action_mapping_raw.get("robust_moves", [])),
                    )
                except Exception as e:
                    phase_times["phase2_95"] = time.perf_counter() - p295_t0
                    logger.warning("[Pipeline] Phase 2.95 Scenario-Action Mapping failed: %s", e)
            else:
                logger.info("[Pipeline] Phase 2.95 skipped — no client profile provided")

            # Execute any planned custom phases after action_mapping
            _run_planned_customs_after("action_mapping")

        # ──────────────────────────────────────────────────────────
        # META-ORCHESTRATOR: Safety-net — execute any remaining custom phases
        # that weren't triggered at their insert_after position
        # ──────────────────────────────────────────────────────────
        for custom_def in analysis_plan.custom_phases:
            # Only execute customs that haven't run yet (safety net for unmatched insert_after)
            if custom_def.get("id") not in [r.get("phase_id") for r in _custom_phase_results]:
                logger.info("[Pipeline] Custom phase '%s' didn't match any insert_after — running as fallback",
                            custom_def.get("name", "?"))
                _execute_custom_phase(custom_def)

        # ──────────────────────────────────────────────────────────
        # META-ORCHESTRATOR: Branch execution + merge (Level 3)
        # If the plan has branches, execute them and merge before XHEART
        # ──────────────────────────────────────────────────────────
        _branch_merge_result = None
        if analysis_plan.is_branching and not _skip_to_xheart:
            logger.info(
                "[Pipeline] BRANCHING: %d parallel analysis paths",
                len(analysis_plan.branches),
            )

            # Build shared context that all branches can access
            _shared_branch_ctx = {
                "ontology": ontology,
                "cross_domain": cross_domain,
                "views": views,
                "world_context_str": world_context_str,
                "working_memory_context": working_memory_context,
                "memory_context": memory_context,
                "identity_context": identity_context,
                "brief_context": brief_context,
                "active_concepts": active_concepts,
                "ontology_summary": ontology_summary,
                "cross_domain_summary": cross_domain_summary,
            }

            def _branch_phase_runner(phase_id: str, depth: str, ctx: dict):
                """Execute a single phase within a branch."""
                if phase_id == "ontology":
                    return self.phase0.run(
                        problem,
                        memory_context=ctx.get("memory_context", ""),
                        active_concepts=ctx.get("active_concepts", []),
                        identity_context=ctx.get("identity_context", ""),
                        brief_context=ctx.get("brief_context", ""),
                        world_context=ctx.get("world_context_str", ""),
                        overlay_text=_ovl("ontology"),
                    )
                elif phase_id == "cross_domain":
                    return self.phase1.run(
                        reframed_problem=ontology.reframed_problem,
                        original_problem=problem,
                        world_context=ctx.get("world_context_str", ""),
                    )
                elif phase_id == "views":
                    return self.phase2.run(
                        problem=problem,
                        reframed_problem=ontology.reframed_problem,
                        cross_domain_summary=ctx.get("cross_domain_summary", ""),
                        world_context=ctx.get("world_context_str", ""),
                    )
                elif phase_id == "scenario_genesis":
                    return self.phase2_5.run(
                        problem=problem,
                        views_result=views,
                        ontology_summary=ctx.get("ontology_summary", ""),
                        cross_domain_summary=ctx.get("cross_domain_summary", ""),
                        world_context=ctx.get("world_context_str", ""),
                        past_scenarios_context="",
                        working_memory_context=ctx.get("working_memory_context", ""),
                        overlay_text=_ovl("scenario_genesis"),
                    )
                elif phase_id == "scenario_tribunal":
                    # Tribunal needs genesis+simulations from this branch
                    return {"note": "Tribunal runs within branch sequence"}
                elif phase_id == "historical_resonance":
                    return self.phase3_5.run(
                        problem=problem,
                        distillate="(branch mode — pre-distillation)",
                        ontology_summary=ctx.get("ontology_summary", ""),
                        cross_domain_summary=ctx.get("cross_domain_summary", ""),
                        scenario_pipeline_summary="",
                        dominant_scenario_name="",
                        tribunal_synthesis="",
                        world_context=ctx.get("world_context_str", ""),
                        working_memory_context=ctx.get("working_memory_context", ""),
                    )
                elif phase_id.startswith("custom_"):
                    # Find custom phase definition
                    for cp in analysis_plan.custom_phases:
                        if cp.get("id") == phase_id:
                            return self.meta_orchestrator.execute_custom_phase(
                                custom_phase=cp,
                                problem=problem,
                                accumulated_context="\n".join(_accumulated_context_parts[-5:]),
                                world_context=ctx.get("world_context_str", "")[:2000],
                            )
                    return {"error": f"Custom phase {phase_id} not found in plan"}
                return {"note": f"Phase {phase_id} not supported in branch mode"}

            # Execute branches (sequentially — they share the LLM)
            # Filter out phases already completed in the main pipeline —
            # branches should only add NEW analysis, not repeat Phase 0-2.91
            _main_pipeline_phases = {
                "ontology", "cross_domain", "views",
                "scenario_genesis", "scenario_simulation",
                "scenario_tribunal", "quantum_engine", "bayesian_fuzzy",
            }
            branch_results = []
            for branch_def in analysis_plan.branches:
                # Strip phases already run; keep custom_* and phases
                # that weren't in the main pipeline (e.g. historical_resonance)
                orig_phases = branch_def.get("phases", [])
                branch_def["phases"] = [
                    p for p in orig_phases if p not in _main_pipeline_phases
                ]
                if not branch_def["phases"]:
                    logger.info(
                        "[Pipeline] Branch '%s' skipped — all %d phases already run in main pipeline",
                        branch_def.get("name", "?"), len(orig_phases),
                    )
                    continue
                logger.info(
                    "[Pipeline] Branch '%s': %d phases (filtered from %d, removed %d main-pipeline dupes)",
                    branch_def.get("name", "?"),
                    len(branch_def["phases"]),
                    len(orig_phases),
                    len(orig_phases) - len(branch_def["phases"]),
                )
                br_result = self.meta_orchestrator.execute_branch(
                    branch=branch_def,
                    problem=problem,
                    run_phase_fn=_branch_phase_runner,
                    shared_context=_shared_branch_ctx,
                )
                branch_results.append(br_result)
                if callback:
                    callback("meta_branch_complete", {
                        "name": br_result.get("name"),
                        "phases": list(br_result.get("phase_results", {}).keys()),
                        "elapsed": br_result.get("elapsed_seconds", 0),
                    })

            # Merge branches
            _branch_merge_result = self.meta_orchestrator.merge_branches(
                problem=problem,
                branch_results=branch_results,
                world_context=world_context_str[:5000],
            )
            if callback:
                callback("meta_branch_merge", {
                    "branches_merged": len(branch_results),
                    "dominant_branch": _branch_merge_result.get("dominant_branch"),
                    "agreements": len(_branch_merge_result.get("branch_agreements", [])),
                    "conflicts": len(_branch_merge_result.get("branch_conflicts", [])),
                    "confidence": _branch_merge_result.get("confidence", 0),
                })
            _accumulated_context_parts.append(
                f"[Branch Merge] {_branch_merge_result.get('unified_synthesis', '')[:300]}"
            )
            logger.info(
                "[Pipeline] BRANCH MERGE complete: dominant=%s, confidence=%.2f",
                _branch_merge_result.get("dominant_branch", "?"),
                _branch_merge_result.get("confidence", 0),
            )

        # ──────────────────────────────────────────────────────────
        # PHASE 3 — XHEART (Two-Stage Distillation — FROM SCENARIOS)
        # ──────────────────────────────────────────────────────────

        # ── Cognitive Strategies: post_tribunal + pre_xheart ──
        _run_strategies_at("post_tribunal", "\n".join(_accumulated_context_parts[-5:]))
        _run_strategies_at("pre_xheart", "\n".join(_accumulated_context_parts[-5:]))

        views_summary = self._summarize_views(views)

        # XHEART now receives EVERYTHING: phases + scenarios + tribunal + quantum
        enriched_views_summary = (
            f"{views_summary}\n\n"
            f"=== SCENARIO PIPELINE RESULTS ===\n"
            f"{scenario_pipeline_summary}\n"
        )

        # Inject Creative Synthesis results into XHEART context
        if synthesis_context:
            enriched_views_summary += f"\n{synthesis_context}\n"

        # Inject custom phase results into XHEART context
        if _custom_phase_results:
            enriched_views_summary += "\n=== CUSTOM ANALYTICAL PHASES ===\n"
            for cpr in _custom_phase_results:
                enriched_views_summary += (
                    f"\n--- {cpr.get('phase_name', 'Custom')} ---\n"
                    f"{cpr.get('analysis', '')[:600]}\n"
                    f"Key insights: {', '.join(cpr.get('key_insights', []))}\n"
                )

        # Inject cognitive strategy results into XHEART context
        if _strategy_results:
            strategy_context = self.strategy_executor.format_for_context(_strategy_results)
            if strategy_context:
                enriched_views_summary += f"\n{strategy_context}\n"

        # Inject branch merge results into XHEART context
        if _branch_merge_result:
            enriched_views_summary += "\n=== MULTI-BRANCH ANALYSIS MERGE ===\n"
            enriched_views_summary += f"Unified synthesis: {_branch_merge_result.get('unified_synthesis', '')}\n"
            agreements = _branch_merge_result.get("branch_agreements", [])
            if agreements:
                enriched_views_summary += f"Branch agreements: {'; '.join(agreements[:5])}\n"
            conflicts = _branch_merge_result.get("branch_conflicts", [])
            if conflicts:
                enriched_views_summary += f"Branch conflicts: {'; '.join(conflicts[:3])}\n"
            unique = _branch_merge_result.get("unique_contributions", [])
            if unique:
                enriched_views_summary += "Unique contributions:\n"
                for u in unique[:3]:
                    enriched_views_summary += f"  [{u.get('branch', '?')}] {u.get('insight', '')[:200]}\n"

        if quantum_collapse:
            enriched_views_summary += (
                f"\n=== QUANTUM ANALYSIS (Phase 2.91) ===\n"
                f"Coherence: {quantum_collapse.coherence_at_measurement:.2f}\n"
                f"Observer shifted dominant: {quantum_collapse.observer_shifted_dominant}\n"
                f"Measurement basis: {quantum_collapse.measurement_basis}\n"
            )

        if bayesian_fuzzy_result:
            enriched_views_summary += (
                f"\n=== BAYESIAN-FUZZY RISK ANALYSIS (Phase 2.92) ===\n"
                f"Domain: {bayesian_fuzzy_result.domain}\n"
                f"Risk level: {bayesian_fuzzy_result.dominant_risk_level}\n"
                f"Key drivers: {', '.join(bayesian_fuzzy_result.key_drivers[:4])}\n"
                f"Assessment: {bayesian_fuzzy_result.risk_assessment[:300]}\n"
            )

        if prophetic_loop_context:
            enriched_views_summary += f"\n{prophetic_loop_context}\n"

        # Build concise scenario context for predictive output
        # When quantum engine ran, use quantum-adjusted probabilities & insights
        if quantum_collapse and quantum_collapse.observer_shifted_dominant:
            # Quantum dominant differs from classical — lead with quantum
            scenario_output_context = (
                f"=== QUANTUM SCENARIO ANALYSIS (Phase 2.91) ===\n"
                f"QUANTUM DOMINANT: {quantum_collapse.quantum_dominant_name} "
                f"(quantum P={quantum_collapse.quantum_dominant_probability:.3f})\n"
                f"CLASSICAL DOMINANT: {tribunal.dominant_scenario.scenario_name} "
                f"(classical score={tribunal.dominant_scenario.final_score:.2f})\n"
                f"*** OBSERVER EFFECT: The question '{problem[:100]}...' shifted dominance "
                f"from classical to quantum via interference ***\n"
                f"MEASUREMENT BASIS: {quantum_collapse.measurement_basis}\n"
                f"TRIBUNAL SYNTHESIS: {tribunal.tribunal_synthesis[:400]}\n"
            )
        elif quantum_collapse:
            # Quantum confirms classical — show both
            scenario_output_context = (
                f"=== QUANTUM-CONFIRMED SCENARIO ANALYSIS ===\n"
                f"DOMINANT SCENARIO: {quantum_collapse.quantum_dominant_name} "
                f"(quantum P={quantum_collapse.quantum_dominant_probability:.3f}, "
                f"classical score={tribunal.dominant_scenario.final_score:.2f})\n"
                f"MEASUREMENT BASIS: {quantum_collapse.measurement_basis}\n"
                f"TRIBUNAL SYNTHESIS: {tribunal.tribunal_synthesis[:400]}\n"
            )
        else:
            # No quantum — classical only
            scenario_output_context = (
                f"DOMINANT SCENARIO: {tribunal.dominant_scenario.scenario_name} "
                f"(score: {tribunal.dominant_scenario.final_score:.2f})\n"
                f"TRIBUNAL SYNTHESIS: {tribunal.tribunal_synthesis[:500]}\n"
            )

        # Add quantum interference insights
        if quantum_collapse:
            if quantum_collapse.interference_patterns:
                scenario_output_context += "\nQUANTUM INTERFERENCE PATTERNS:\n"
                for ip in quantum_collapse.interference_patterns:
                    scenario_output_context += (
                        f"  {ip.pattern_type} ({ip.mechanism_class}): {ip.insight[:200]}\n"
                    )
            if quantum_collapse.hidden_signals:
                scenario_output_context += "\nHIDDEN SIGNALS (from quantum interference):\n"
                for sig in quantum_collapse.hidden_signals[:4]:
                    scenario_output_context += f"  - {sig[:200]}\n"
            if quantum_collapse.quantum_narrative:
                scenario_output_context += f"\nQUANTUM ANALYSIS: {quantum_collapse.quantum_narrative[:500]}\n"

            # Add scenarios sorted by quantum probability
            scenario_output_context += "\nSCENARIO PROBABILITIES (quantum-adjusted):\n"
            sorted_probs = sorted(
                quantum_collapse.collapsed_probabilities.items(),
                key=lambda x: x[1], reverse=True,
            )
            for sid, prob in sorted_probs[:4]:
                s = next((sc for sc in scenario_genesis.scenarios if sc.id == sid), None)
                if s:
                    delta = quantum_collapse.quantum_vs_classical_deltas.get(sid, 0.0)
                    delta_str = f" (Δ={delta:+.3f})" if abs(delta) > 0.01 else ""
                    scenario_output_context += (
                        f"\nSCENARIO '{s.name}' (P={prob:.3f}{delta_str}):\n"
                        f"  Timeline: {s.timeline}\n"
                        f"  Predicted outcome: {s.predicted_outcome[:300]}\n"
                        f"  Falsifiability: {s.falsifiability[:200]}\n"
                    )
        else:
            # Classical fallback — convergence + top scenarios
            scenario_output_context += "CONVERGENCE POINTS:\n"
            for cp in tribunal.convergence_points[:5]:
                scenario_output_context += f"  - {cp[:200]}\n"
            for verdict in sorted(tribunal.verdicts, key=lambda v: v.final_score, reverse=True)[:3]:
                s = next((sc for sc in scenario_genesis.scenarios if sc.id == verdict.scenario_id), None)
                if s:
                    scenario_output_context += (
                        f"\nSCENARIO '{s.name}' (score={verdict.final_score:.2f}):\n"
                        f"  Timeline: {s.timeline}\n"
                        f"  Predicted outcome: {s.predicted_outcome[:300]}\n"
                        f"  Falsifiability: {s.falsifiability[:200]}\n"
                    )

        # Add Bayesian-Fuzzy risk assessment to scenario context
        if bayesian_fuzzy_result:
            scenario_output_context += (
                f"\n=== BAYESIAN-FUZZY RISK ASSESSMENT (Phase 2.92) ===\n"
                f"Domain: {bayesian_fuzzy_result.domain}\n"
                f"Risk level: {bayesian_fuzzy_result.dominant_risk_level}\n"
            )
            for rp in bayesian_fuzzy_result.risk_posteriors:
                scenario_output_context += (
                    f"  {rp.risk_variable}: {rp.dominant_level} "
                    f"(P={rp.dominant_probability:.3f})\n"
                )
            if bayesian_fuzzy_result.causal_chain:
                scenario_output_context += (
                    f"Causal chain: {bayesian_fuzzy_result.causal_chain[:300]}\n"
                )
            if bayesian_fuzzy_result.risk_narrative:
                scenario_output_context += (
                    f"Risk narrative: {bayesian_fuzzy_result.risk_narrative[:400]}\n"
                )

        p3_t0 = time.perf_counter()
        xheart, final_output, falsifiability, self_generated_layers = self.phase3.run(
            problem=problem,
            ontology_summary=ontology_summary,
            cross_domain_summary=cross_domain_summary,
            views_summary=enriched_views_summary,
            world_context=world_context_str[:15000],
            scenario_context=scenario_output_context,
            distillation_overlay=_ovl("xheart_distillation"),
            output_overlay=_ovl("xheart_output"),
        )
        phase_times["phase3"] = time.perf_counter() - p3_t0
        if callback:
            callback("phase3_xheart", xheart)

        # Send expansion event if layer was generated
        if self_generated_layers and callback:
            callback("xheart_expansion", self_generated_layers)

        logger.info(
            "[Pipeline] Phase 3 complete (%.2fs): is_layer_3=%s, core=%s",
            phase_times["phase3"],
            xheart.is_layer_3,
            xheart.distillate_core[:80],
        )
        if self_generated_layers:
            logger.info("[Pipeline] XHEART expansion: %s (%s)",
                         self_generated_layers[0]["layer_name"],
                         self_generated_layers[0]["layer_type"])

        # ── Gate: XHEART ──
        _phases_completed.append("xheart")
        _accumulated_context_parts.append(f"[XHEART] {xheart.distillate_core[:300]}")

        # ──────────────────────────────────────────────────────────
        # PHASE 3.5 — HISTORICAL RESONANCE (Post-XHEART)
        # ──────────────────────────────────────────────────────────
        historical_resonance_raw = None
        historical_resonance_result = None
        if _should_run_phase("historical_resonance"):
            p35_t0 = time.perf_counter()
            try:
                historical_resonance_raw = self.phase3_5.run(
                    problem=problem,
                    distillate=xheart.distillate_core,
                    ontology_summary=ontology_summary,
                    cross_domain_summary=cross_domain_summary,
                    scenario_pipeline_summary=scenario_pipeline_summary,
                    dominant_scenario_name=tribunal.dominant_scenario.scenario_name,
                    tribunal_synthesis=tribunal.tribunal_synthesis,
                    world_context=world_context_str[:10000],
                    working_memory_context=working_memory_context,
                )
                phase_times["phase3_5"] = time.perf_counter() - p35_t0

                # Parse into Pydantic model
                parallel_models = []
                for pa in historical_resonance_raw.get("parallel_analyses", []):
                    try:
                        parallel_models.append(HistoricalParallelAnalysis(**pa))
                    except Exception:
                        parallel_models.append(HistoricalParallelAnalysis(
                            event_name=pa.get("event_name", "Unknown"),
                            confidence=pa.get("confidence", 0.0),
                        ))

                verdict_data = historical_resonance_raw.get("verdict", {})
                try:
                    verdict_model = HistoricalVerdict(**verdict_data)
                except Exception:
                    verdict_model = HistoricalVerdict(
                        historical_consensus=verdict_data.get("historical_consensus", ""),
                    )

                historical_resonance_result = HistoricalResonanceResult(
                    structural_conditions=historical_resonance_raw.get("structural_conditions", []),
                    parallels_found=historical_resonance_raw.get("parallels_found", 0),
                    parallel_analyses=parallel_models,
                    verdict=verdict_model,
                    elapsed_seconds=historical_resonance_raw.get("elapsed_seconds", 0.0),
                )

                if callback:
                    callback("phase3_5_historical", {
                        "structural_conditions": historical_resonance_raw.get("structural_conditions", []),
                        "parallels_found": historical_resonance_raw.get("parallels_found", 0),
                        "parallel_analyses": [
                            {
                                "event_name": p.event_name,
                                "event_period": p.event_period,
                                "structural_match_score": p.structural_match_score,
                                "confidence": p.confidence,
                                "transfer_insights": p.transfer_insights or [],
                                "transfer_warnings": p.transfer_warnings or [],
                            }
                            for p in parallel_models
                        ],
                        "verdict": {
                            "historical_consensus": verdict_model.historical_consensus or "",
                            "historical_warning": verdict_model.historical_warning or "",
                            "pattern_beneath": verdict_model.pattern_beneath or "",
                            "historical_confidence": verdict_model.historical_confidence,
                            "strongest_parallel": verdict_model.strongest_parallel or "",
                            "early_warning_signals": verdict_model.early_warning_signals or [],
                        },
                    })

                logger.info(
                    "[Pipeline] Phase 3.5 complete (%.2fs): %d parallels, confidence=%.2f, top=%s",
                    phase_times["phase3_5"],
                    len(parallel_models),
                    verdict_model.historical_confidence,
                    parallel_models[0].event_name if parallel_models else "none",
                )

                # Push historical insights into working memory
                if verdict_model.historical_warning:
                    self.working_memory.push(
                        item_type="insight",
                        content=f"Historical warning: {verdict_model.historical_warning[:300]}",
                        source="phase3_5_historical",
                        relevance=0.95,
                    )
                if verdict_model.pattern_beneath:
                    self.working_memory.push(
                        item_type="insight",
                        content=f"Pattern beneath: {verdict_model.pattern_beneath[:200]}",
                        source="phase3_5_historical",
                        relevance=0.90,
                    )
            except Exception as e:
                phase_times["phase3_5"] = time.perf_counter() - p35_t0
                logger.warning("[Pipeline] Phase 3.5 Historical Resonance failed: %s", e)
        else:
            logger.info("[Pipeline] Phase 3.5 SKIPPED by meta-orchestrator")

        # ──────────────────────────────────────────────────────────
        # PHASE 3.7 — STRATEGIC FORESIGHT (Post-History)
        # ──────────────────────────────────────────────────────────
        strategic_foresight_raw = None
        strategic_foresight_result = None
        if _should_run_phase("strategic_foresight"):
            p37_t0 = time.perf_counter()
            try:
                strategic_foresight_raw = self.phase3_7.run(
                    problem=problem,
                    distillate=xheart.distillate_core,
                    ontology_summary=ontology_summary,
                    cross_domain_summary=cross_domain_summary,
                    views_summary=views_summary,
                    scenario_pipeline_summary=scenario_pipeline_summary,
                    dominant_scenario_name=tribunal.dominant_scenario.scenario_name,
                    tribunal_synthesis=tribunal.tribunal_synthesis,
                    historical_resonance=historical_resonance_raw or {},
                    world_context=world_context_str[:10000],
                    client_context=client_context,
                    action_mapping=action_mapping_raw,
                )
                phase_times["phase3_7"] = time.perf_counter() - p37_t0

                # Parse into Pydantic model (flexible: accept raw dict structure)
                try:
                    strategic_foresight_result = StrategicForesightResult(**strategic_foresight_raw)
                except Exception:
                    strategic_foresight_result = StrategicForesightResult(
                        strategic_assessment=strategic_foresight_raw.get("strategic_assessment", ""),
                        historical_warning=strategic_foresight_raw.get("historical_warning", ""),
                        elapsed_seconds=strategic_foresight_raw.get("elapsed_seconds", 0.0),
                    )

                if callback:
                    callback("phase3_7_strategic", {
                        "strategic_assessment": strategic_foresight_raw.get("strategic_assessment", ""),
                        "decision_points": strategic_foresight_raw.get("decision_points", []),
                        "what_to_watch": strategic_foresight_raw.get("what_to_watch", []),
                        "risk_opportunity_matrix": strategic_foresight_raw.get("risk_opportunity_matrix", []),
                        "recommendations_by_role": strategic_foresight_raw.get("recommendations_by_role", {}),
                        "historical_warning": strategic_foresight_raw.get("historical_warning", ""),
                        "confidence_calibration": strategic_foresight_raw.get("confidence_calibration", {}),
                    })

                logger.info(
                    "[Pipeline] Phase 3.7 complete (%.2fs): %d decision points, %d watch signals",
                    phase_times["phase3_7"],
                    len(strategic_foresight_raw.get("decision_points", [])),
                    len(strategic_foresight_raw.get("what_to_watch", [])),
                )
            except Exception as e:
                phase_times["phase3_7"] = time.perf_counter() - p37_t0
                logger.warning("[Pipeline] Phase 3.7 Strategic Foresight failed: %s", e)
        else:
            logger.info("[Pipeline] Phase 3.7 SKIPPED by meta-orchestrator")

        # ──────────────────────────────────────────────────────────
        # PHASE 3.9 — Prophetic Bets (Falsifiable Predictions)
        # ──────────────────────────────────────────────────────────
        prophetic_bets_result = None
        p39_t0 = time.perf_counter()
        try:
            prophetic_bets_raw = self.phase3_9.run(
                problem=problem,
                distillate=xheart.distillate_core,
                scenario_summary=scenario_pipeline_summary[:800],
                tribunal_synthesis=tribunal.tribunal_synthesis,
                strategic_foresight=strategic_foresight_raw if strategic_foresight_raw else None,
                historical_resonance=historical_resonance_raw if historical_resonance_raw else None,
                world_context=world_context_str[:1500] if world_context_str else "",
                client_context=client_context,
                action_mapping=action_mapping_raw,
            )
            phase_times["phase3_9"] = time.perf_counter() - p39_t0
            prophetic_bets_result = prophetic_bets_raw

            if callback:
                callback("phase3_9_bets", {
                    "bets": prophetic_bets_raw.get("bets", []),
                    "meta_prediction": prophetic_bets_raw.get("meta_prediction", ""),
                    "prophet_confidence": prophetic_bets_raw.get("prophet_confidence", 0),
                    "prophet_reasoning": prophetic_bets_raw.get("prophet_reasoning", ""),
                })

            logger.info(
                "[Pipeline] Phase 3.9 complete (%.2fs): %d bets, prophet_confidence=%.2f",
                phase_times["phase3_9"],
                len(prophetic_bets_raw.get("bets", [])),
                prophetic_bets_raw.get("prophet_confidence", 0),
            )
        except Exception as e:
            phase_times["phase3_9"] = time.perf_counter() - p39_t0
            logger.warning("[Pipeline] Phase 3.9 Prophetic Bets failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # CONSISTENCY CHECK — Distillate vs Bets
        # Detect and log contradictions between XHEART output and bets
        # ──────────────────────────────────────────────────────────
        if prophetic_bets_result and xheart.distillate_core:
            try:
                distillate_lower = xheart.distillate_core.lower()
                for bet in prophetic_bets_result.get("bets", []):
                    bet_stmt = bet.get("statement", bet.get("prediction", "")).lower()
                    # Detect numeric direction contradictions
                    dist_decline = any(w in distillate_lower for w in ["decline", "decrease", "drop", "fall", "shrink", "contract"])
                    dist_increase = any(w in distillate_lower for w in ["increase", "grow", "rise", "surge", "expand", "gain"])
                    bet_decline = any(w in bet_stmt for w in ["decline", "decrease", "drop", "fall", "shrink", "contract"])
                    bet_increase = any(w in bet_stmt for w in ["increase", "grow", "rise", "surge", "expand", "gain", "increased"])
                    if (dist_decline and bet_increase) or (dist_increase and bet_decline):
                        logger.warning(
                            "[Pipeline] CONTRADICTION detected — distillate says '%s' but bet says '%s'. "
                            "Flagging for review.",
                            "decline" if dist_decline else "increase",
                            "increase" if bet_increase else "decline",
                        )
                        bet["_contradiction_flag"] = True
                        bet["_contradiction_note"] = (
                            f"Potential contradiction with distillate direction "
                            f"(distillate: {'decline' if dist_decline else 'increase'}, "
                            f"bet: {'increase' if bet_increase else 'decline'})"
                        )
            except Exception as e:
                logger.debug("[Pipeline] Consistency check failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 3.95 — Executive Intelligence Brief (Εκτελεστική Σύνοψη)
        # Synthesizes ALL phases into a condensed 1-2 page narrative brief.
        # ──────────────────────────────────────────────────────────
        executive_brief_result = None
        p395_t0 = time.perf_counter()
        try:
            # Build context strings from available phase results
            _hist_ctx = ""
            if historical_resonance_raw:
                v = historical_resonance_raw.get("verdict", {})
                _hist_ctx = (
                    f"Historical consensus: {v.get('historical_consensus', '')}\n"
                    f"Historical warning: {v.get('historical_warning', '')}\n"
                    f"Pattern beneath: {v.get('pattern_beneath', '')}\n"
                    f"Parallels found: {historical_resonance_raw.get('parallels_found', 0)}\n"
                )
                for pa in historical_resonance_raw.get("parallel_analyses", [])[:3]:
                    _hist_ctx += (
                        f"  - {pa.get('event_name', '?')} ({pa.get('event_period', '?')}): "
                        f"match={pa.get('structural_match_score', 0):.0%}\n"
                    )

            _strat_ctx = ""
            if strategic_foresight_raw:
                _strat_ctx = (
                    f"Strategic assessment: {strategic_foresight_raw.get('strategic_assessment', '')}\n"
                    f"Decision points: {len(strategic_foresight_raw.get('decision_points', []))}\n"
                    f"Historical warning: {strategic_foresight_raw.get('historical_warning', '')}\n"
                )
                for dp in strategic_foresight_raw.get("decision_points", [])[:5]:
                    _strat_ctx += f"  - {dp.get('decision', '?')} (deadline: {dp.get('deadline_description', '?')})\n"
                cal = strategic_foresight_raw.get("confidence_calibration", {})
                if cal:
                    _strat_ctx += f"Confidence: {cal.get('overall_confidence', '?')}\n"
                # Include immediate actions if available
                for ia in strategic_foresight_raw.get("immediate_actions", [])[:6]:
                    if isinstance(ia, dict):
                        _strat_ctx += f"  Action: {ia.get('action', '?')} (urgency: {ia.get('urgency', '?')})\n"
                    else:
                        _strat_ctx += f"  Action: {ia}\n"

            _bets_ctx = ""
            if prophetic_bets_result:
                for b in prophetic_bets_result.get("bets", []):
                    stmt = b.get("statement", b.get("prediction", ""))
                    _bets_ctx += (
                        f"  - {stmt} (deadline: {b.get('deadline', '?')}, "
                        f"confidence: {b.get('confidence', '?')})\n"
                    )
                _bets_ctx += f"Meta-prediction: {prophetic_bets_result.get('meta_prediction', '')}\n"

            _action_ctx = ""
            if action_mapping_raw:
                for rm in action_mapping_raw.get("robust_moves", []):
                    if isinstance(rm, dict):
                        _action_ctx += f"  Robust: {rm.get('action', '?')} ({rm.get('reasoning', '')})\n"
                _action_ctx += f"Client role: {action_mapping_raw.get('client_role', '?')}\n"
                for sp in action_mapping_raw.get("scenario_playbooks", [])[:4]:
                    if isinstance(sp, dict):
                        _action_ctx += f"  Playbook [{sp.get('scenario_name', '?')}]: "
                        actions = sp.get("actions", [])
                        if actions:
                            top = actions[0] if isinstance(actions[0], str) else actions[0].get("action", "?")
                            _action_ctx += f"{top} + {len(actions)-1} more\n"

            executive_brief_raw = self.phase3_95.run(
                problem=problem,
                ontology_summary=ontology_summary,
                cross_domain_summary=cross_domain_summary,
                views_summary=views_summary,
                scenario_pipeline_summary=scenario_pipeline_summary,
                tribunal_synthesis=tribunal.tribunal_synthesis,
                dominant_scenario_name=tribunal.dominant_scenario.scenario_name,
                final_output=final_output,
                falsifiability=falsifiability,
                historical_context=_hist_ctx,
                strategic_context=_strat_ctx,
                bets_context=_bets_ctx,
                action_context=_action_ctx,
                client_context=client_context,
                world_context=world_context_str[:1500] if world_context_str else "",
            )
            phase_times["phase3_95"] = time.perf_counter() - p395_t0

            # Parse into Pydantic model
            try:
                executive_brief_result = ExecutiveBrief(**executive_brief_raw)
            except Exception:
                executive_brief_result = ExecutiveBrief(
                    situation=executive_brief_raw.get("situation", ""),
                    key_judgments=executive_brief_raw.get("key_judgments", []),
                    scenarios_ranked=executive_brief_raw.get("scenarios_ranked", ""),
                    recommended_actions=executive_brief_raw.get("recommended_actions", []),
                    critical_timeline=executive_brief_raw.get("critical_timeline", ""),
                    risks_and_contingencies=executive_brief_raw.get("risks_and_contingencies", ""),
                    bottom_line=executive_brief_raw.get("bottom_line", ""),
                    confidence_statement=executive_brief_raw.get("confidence_statement", ""),
                    elapsed_seconds=executive_brief_raw.get("elapsed_seconds", 0.0),
                )

            if callback:
                callback("phase3_95_executive_brief", {
                    "situation": executive_brief_result.situation[:500],
                    "key_judgments": executive_brief_result.key_judgments,
                    "scenarios_ranked": executive_brief_result.scenarios_ranked[:500],
                    "recommended_actions": executive_brief_result.recommended_actions,
                    "critical_timeline": executive_brief_result.critical_timeline[:500],
                    "risks_and_contingencies": executive_brief_result.risks_and_contingencies[:500],
                    "bottom_line": executive_brief_result.bottom_line,
                    "confidence_statement": executive_brief_result.confidence_statement,
                })

            logger.info(
                "[Pipeline] Phase 3.95 Executive Brief complete (%.2fs): %d judgments, %d actions",
                phase_times["phase3_95"],
                len(executive_brief_result.key_judgments),
                len(executive_brief_result.recommended_actions),
            )
        except Exception as e:
            phase_times["phase3_95"] = time.perf_counter() - p395_t0
            logger.warning("[Pipeline] Phase 3.95 Executive Brief failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 4 — Store to Episodic Memory
        # ──────────────────────────────────────────────────────────
        domain_tags = [d.domain for d in cross_domain.domains_analyzed]
        layer_score = {
            LayerClassification.LAYER_1: 0.33,
            LayerClassification.LAYER_2: 0.66,
            LayerClassification.LAYER_3: 1.0,
        }.get(cross_domain.layer, 0.33)

        p4_t0 = time.perf_counter()
        self.memory.store(
            problem=problem,
            reframed_problem=ontology.reframed_problem,
            xheart_distillate=xheart.distillate_core,
            domain_tags=domain_tags,
            layer_score=layer_score,
            self_generated_layers=self_generated_layers,
        )

        # Store concept definitions if self-generated layers were created
        if self_generated_layers:
            for layer_info in self_generated_layers:
                try:
                    self.memory.store_concept(
                        layer_info=layer_info,
                        problem=problem,
                        distillate_core=xheart.distillate_core,
                    )
                    logger.info(
                        "[Pipeline] Concept stored: %s",
                        layer_info["layer_name"],
                    )
                except Exception as e:
                    logger.warning("[Pipeline] Concept store failed: %s", e)

        phase_times["phase4"] = time.perf_counter() - p4_t0
        if callback:
            callback("phase4_memory", {"stored": True, "total": self.memory.entry_count})

        logger.info("[Pipeline] Phase 4 complete (%.2fs): memory stored (total: %d)",
                     phase_times["phase4"], self.memory.entry_count)

        # ──────────────────────────────────────────────────────────
        # PARALLEL MEMORY CONSOLIDATION (4.5 + 4.6 + 4.7)
        # Prophetic store, semantic extraction, procedural extraction
        # run simultaneously — each writes to a different Qdrant collection.
        # ──────────────────────────────────────────────────────────
        consolidation_t0 = time.perf_counter()

        def _store_prophetic():
            self.prophetic_memory.store_scenarios(
                problem=problem,
                scenarios=scenario_genesis.scenarios,
                simulations=simulations.simulations,
                verdicts=tribunal.verdicts,
            )
            return "prophetic", len(scenario_genesis.scenarios)

        def _consolidate_semantic():
            truths = self.semantic_memory.extract_and_store(
                problem=problem,
                distillate=xheart.distillate_core,
                scenarios_summary=scenario_pipeline_summary[:800],
                tribunal_synthesis=tribunal.tribunal_synthesis,
            )
            return "semantic", len(truths)

        def _consolidate_procedural():
            patterns = self.procedural_memory.extract_and_store(
                problem=problem,
                distillate=xheart.distillate_core,
                scenarios_summary=scenario_pipeline_summary[:600],
            )
            return "procedural", len(patterns)

        consolidation_results = {}
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="xdart-consolidation") as pool:
            futures = {
                pool.submit(_store_prophetic): "prophetic",
                pool.submit(_consolidate_semantic): "semantic",
                pool.submit(_consolidate_procedural): "procedural",
            }

        for future, label in futures.items():
            try:
                kind, count = future.result()
                consolidation_results[kind] = count
            except Exception as e:
                logger.warning("[Pipeline] %s memory consolidation failed: %s", label, e)
                consolidation_results[label] = 0

        phase_times["parallel_consolidation"] = time.perf_counter() - consolidation_t0

        if consolidation_results.get("prophetic", 0) > 0:
            logger.info("[Pipeline] Prophetic memory: %d scenarios stored (total: %d)",
                        consolidation_results["prophetic"], self.prophetic_memory.entry_count)
            if callback:
                callback("prophetic_memory_stored", {
                    "scenarios_stored": consolidation_results["prophetic"],
                    "total_prophecies": self.prophetic_memory.entry_count,
                })
        logger.info("[Pipeline] Semantic memory: %d new truths consolidated",
                    consolidation_results.get("semantic", 0))
        logger.info("[Pipeline] Procedural memory: %d new patterns learned",
                    consolidation_results.get("procedural", 0))
        logger.info("[Pipeline] PARALLEL CONSOLIDATION complete (%.2fs)",
                    phase_times["parallel_consolidation"])

        # ──────────────────────────────────────────────────────────
        # PHASE 5b — CHARACTER UPDATE (conditional — skip if no epistemic shift)
        # ──────────────────────────────────────────────────────────
        char_t0 = time.perf_counter()
        try:
            # Check if this run has a significant epistemic shift from the last one.
            # If the distillate is very similar to the previous run's, skip the
            # expensive full character rewrite (~5,900 tokens saved).
            CHARACTER_UPDATE_THRESHOLD = 0.88
            skip_character_update = False
            last_distillate = character_state.get("last_distillate", "")
            if last_distillate and xheart.distillate_core:
                try:
                    emb_old = self.llm.embed(last_distillate[:400])
                    emb_new = self.llm.embed(xheart.distillate_core[:400])
                    sim = sum(a * b for a, b in zip(emb_old, emb_new))
                    norm_a = sum(x * x for x in emb_old) ** 0.5
                    norm_b = sum(x * x for x in emb_new) ** 0.5
                    sim = sim / (norm_a * norm_b) if norm_a and norm_b else 0
                    if sim >= CHARACTER_UPDATE_THRESHOLD:
                        skip_character_update = True
                        logger.info(
                            "[Pipeline] Character update SKIPPED — distillate similarity=%.3f (threshold=%.2f)",
                            sim, CHARACTER_UPDATE_THRESHOLD,
                        )
                except Exception:
                    pass  # On error, proceed with the update

            if not skip_character_update:
                updated_character, core_change_result = self.memory.update_character(
                    current_character=character_state,
                    run_distillate=xheart.distillate_core,
                    run_problem=problem,
                    self_generated_layers=self_generated_layers,
                    xheart_internal=xheart.distillate_core,
                    character_path=CHARACTER_STATE_PATH,
                )
                phase_times["character_update"] = time.perf_counter() - char_t0

                if callback:
                    callback("character_updated", {
                        "version": updated_character.get("version", 0),
                        "tensions": len(updated_character.get("active_tensions", [])),
                        "changes": len(updated_character.get("how_i_have_changed", [])),
                    })

                # Fire core_change_proposed callback if the system proposed a change
                if core_change_result and callback:
                    callback("core_change_proposed", core_change_result)
            else:
                # Store the new distillate even when skipping full rewrite
                updated_character = dict(character_state)
                updated_character["last_distillate"] = xheart.distillate_core
                phase_times["character_update"] = time.perf_counter() - char_t0

        except Exception as e:
            logger.warning("[Pipeline] Character update failed: %s", e)
            phase_times["character_update"] = time.perf_counter() - char_t0

        # ──────────────────────────────────────────────────────────
        # PHASE 5c — SELF-AWARENESS BRIEF UPDATE
        # ──────────────────────────────────────────────────────────
        try:
            all_concept_names = list(
                updated_character.get("named_concepts_owned", [])
            )
            new_brief = self.self_awareness.update(
                character=updated_character,
                concepts=all_concept_names,
                run_number=updated_character.get("version", 0),
                distillate=xheart.distillate_core,
                previous_brief=current_brief,
            )
            logger.info(
                "[Pipeline] Self-awareness brief updated — version %d",
                new_brief["version"],
            )
        except Exception as e:
            logger.warning("[Pipeline] Self-awareness brief update failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5c.1 — INTROSPECTION (αυτογνωσία — post-pipeline audit)
        # ──────────────────────────────────────────────────────────
        try:
            pipeline_report = self.introspection.introspect_pipeline(
                problem=problem,
                phase_outputs={
                    "ontology": ontology.reframed_problem[:200],
                    "cross_domain": cross_domain_summary[:200],
                    "views": views.dominant_pattern[:200],
                    "scenarios": f"{len(scenario_genesis.scenarios)} scenarios generated",
                    "tribunal": f"Dominant: {tribunal.dominant_scenario.scenario_name} (score={tribunal.dominant_scenario.final_score:.2f})",
                    "xheart": xheart.distillate_core[:200],
                    "historical": (historical_resonance_raw or {}).get("verdict", {}).get("historical_consensus", "")[:200] if historical_resonance_raw else "",
                    "strategic": (strategic_foresight_raw or {}).get("strategic_assessment", "")[:200] if strategic_foresight_raw else "",
                    "bets": f"{len((prophetic_bets_result or {}).get('bets', []))} bets" if prophetic_bets_result else "none",
                },
                final_output=final_output,
                layer=cross_domain.layer.value,
                phase_times=phase_times,
                memories_retrieved=len(past_memories),
                concepts_retrieved=len(active_concepts),
                world_events=len(wctx.get("events", [])),
            )
            # Record integrity in wisdom tracker (skip 0.0 from failed LLM calls)
            integrity = pipeline_report.get("epistemic_integrity_score")
            if isinstance(integrity, (int, float)) and integrity > 0.01:
                self.wisdom_tracker.record_integrity_score(integrity)
            logger.info("[Pipeline] Introspection complete — integrity=%.2f",
                        pipeline_report.get("epistemic_integrity_score", 0))

            if callback:
                callback("introspection_complete", {
                    "integrity_score": pipeline_report.get("epistemic_integrity_score", 0),
                    "observations": pipeline_report.get("self_observations", {}),
                })
        except Exception as e:
            logger.warning("[Pipeline] Introspection failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5c.2 — WISDOM TRACKING (σοφία — record Brier from bets)
        # ──────────────────────────────────────────────────────────
        try:
            # Record Brier score if prophetic loop evaluated past predictions
            if prophetic_loop_result and hasattr(prophetic_loop_result, 'brier_score'):
                brier = getattr(prophetic_loop_result, 'brier_score', None)
                if brier is not None:
                    self.wisdom_tracker.record_brier_score(brier)

            # Record confidence claims from prophetic bets
            if prophetic_bets_result:
                run_ver = updated_character.get("version", 0) if "updated_character" in dir() else 0
                for bet in prophetic_bets_result.get("bets", []):
                    conf = bet.get("confidence", 0.5)
                    claim_text = bet.get("statement", bet.get("prediction", bet.get("description", "")))
                    deadline = bet.get("deadline", bet.get("verification_date", None))
                    if claim_text:
                        self.wisdom_tracker.record_confidence_claim(
                            claim=claim_text,
                            confidence=conf,
                            source_run=run_ver,
                            deadline=deadline,
                        )

            # Auto-resolve expired claims before computing wisdom index
            expired_resolved = self.wisdom_tracker.auto_resolve_expired_claims()
            if expired_resolved:
                logger.info("[Pipeline] Auto-resolved %d expired wisdom claims", expired_resolved)

            # Compute updated wisdom index
            wisdom_result = self.wisdom_tracker.compute_wisdom_index()
            if callback and wisdom_result.get("wisdom_index") is not None:
                callback("wisdom_updated", wisdom_result)
            logger.info("[Pipeline] Wisdom index: %.3f", wisdom_result.get("wisdom_index", 0) or 0)

            # ── Overlay rollback check (auto-deactivate if wisdom degraded) ──
            wi = wisdom_result.get("wisdom_index")
            if wi is not None:
                rolled_back = self.overlay_manager.check_rollback(wi)
                if rolled_back:
                    logger.warning("[Pipeline] Overlays rolled back due to wisdom drop: %s", rolled_back)
                    if callback:
                        callback("overlay_rollback", {"targets": rolled_back, "wisdom_index": wi})
        except Exception as e:
            logger.warning("[Pipeline] Wisdom tracking failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5c.3 — SELF-EVOLUTION TICK (αυτοεξέλιξη — periodic diagnosis)
        # ──────────────────────────────────────────────────────────
        try:
            self.self_evolution.tick()
            if self.self_evolution.should_diagnose(force=True):
                brier_for_diagnosis = None
                if prophetic_loop_result and hasattr(prophetic_loop_result, 'brier_score'):
                    brier_for_diagnosis = getattr(prophetic_loop_result, 'brier_score', None)
                char_for_diag = updated_character if "updated_character" in dir() else character_state
                diagnosis = self.self_evolution.diagnose(
                    character=char_for_diag,
                    brier_score=brier_for_diagnosis,
                )
                if diagnosis and callback:
                    callback("self_evolution_diagnosis", {
                        "issue": diagnosis.get("diagnosis", {}).get("pattern", ""),
                        "proposed_change": diagnosis.get("proposed_change", {}),
                        "confidence": diagnosis.get("confidence_in_diagnosis", 0),
                    })
        except Exception as e:
            logger.warning("[Pipeline] Self-evolution tick failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5c.4 — CURIOSITY GENERATION (αυτο-προσανατολισμός)
        # ──────────────────────────────────────────────────────────
        if self.curiosity_engine:
            try:
                introspection_for_curiosity = pipeline_report if "pipeline_report" in dir() else None
                char_for_curiosity = updated_character if "updated_character" in dir() else character_state
                new_curiosities = self.curiosity_engine.generate(
                    introspection_report=introspection_for_curiosity,
                    character=char_for_curiosity,
                    world_context=world_context_str[:5000],
                    recent_distillate=xheart.distillate_core,
                    recent_problem=problem,
                )
                if new_curiosities and callback:
                    callback("curiosity_generated", {
                        "count": len(new_curiosities),
                        "questions": [c.question for c in new_curiosities],
                        "stats": self.curiosity_engine.get_stats(),
                    })
                logger.info("[Pipeline] Curiosity generation: %d new questions", len(new_curiosities))
            except Exception as e:
                logger.warning("[Pipeline] Curiosity generation failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5c.5 — LOGIC SANDBOX ANALYSIS (αυτο-τροποποίηση αλγοριθμικής λογικής)
        # ──────────────────────────────────────────────────────────
        if self.logic_sandbox:
            try:
                introspection_for_sandbox = ""
                if "pipeline_report" in dir() and pipeline_report:
                    import json as _json_sb
                    introspection_for_sandbox = _json_sb.dumps(pipeline_report, ensure_ascii=False, default=str)[:2000]
                _sb_wisdom = {}
                try:
                    _sb_wisdom = self.wisdom_tracker.get_summary()
                except Exception:
                    pass
                sandbox_proposal = self.logic_sandbox.auto_analyze(
                    introspection_data=introspection_for_sandbox,
                    performance_data={
                        "brier_score": _sb_wisdom.get("avg_brier_score", "N/A"),
                        "avg_integrity": pipeline_report.get("epistemic_integrity", "N/A") if "pipeline_report" in dir() and pipeline_report else "N/A",
                        "calibration_error": _sb_wisdom.get("calibration_error", "N/A"),
                    },
                    callback=callback,
                )
                if sandbox_proposal:
                    logger.info(
                        "[Pipeline] Logic Sandbox: proposed modification %s for %s",
                        sandbox_proposal.id, sandbox_proposal.target_function,
                    )
            except Exception as e:
                logger.warning("[Pipeline] Logic Sandbox analysis failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5c.6 — PRINCIPLE DISCOVERY (δυναμική ανακάλυψη αρχών)
        # ──────────────────────────────────────────────────────────
        if self.principle_registry:
            try:
                # Build evidence from introspection + wisdom
                evidence_parts = []
                if "pipeline_report" in dir() and pipeline_report:
                    import json as _json_pr
                    evidence_parts.append(f"Introspection: {_json_pr.dumps(pipeline_report, ensure_ascii=False, default=str)[:1500]}")
                wisdom_data = {}
                try:
                    wisdom_data = self.wisdom_tracker.get_summary()
                except Exception:
                    pass

                # Build performance data
                perf_data = {
                    "brier_score": wisdom_data.get("avg_brier_score", "N/A"),
                    "avg_integrity": pipeline_report.get("epistemic_integrity", "N/A") if "pipeline_report" in dir() and pipeline_report else "N/A",
                    "calibration_error": wisdom_data.get("calibration_error", "N/A"),
                    "failure_patterns": wisdom_data.get("recent_failures", []),
                }

                if evidence_parts:
                    # Get axioms text for dedup
                    axioms_text = ""
                    try:
                        from xdart.knowledge.axioms import format_axioms_for_prompt
                        axioms_text = format_axioms_for_prompt()
                    except Exception:
                        pass

                    new_principle = self.principle_registry.discover(
                        evidence="\n".join(evidence_parts),
                        performance_data=perf_data,
                        existing_axioms_text=axioms_text,
                        callback=callback,
                    )
                    if new_principle:
                        logger.info(
                            "[Pipeline] Principle Registry: proposed %s — %s",
                            new_principle.id, new_principle.title,
                        )

                # ── Wisdom extraction: learn from SUCCESS too ──
                if hasattr(xheart, "distillate_core") and xheart.distillate_core:
                    success_parts = [f"Distillate: {xheart.distillate_core[:1500]}"]
                    if hasattr(xheart, "prophecy") and xheart.prophecy:
                        success_parts.append(f"Prophecy: {xheart.prophecy[:500]}")
                    success_parts.append(f"Problem analyzed: {problem[:500]}")
                    _wisdom_perf = dict(perf_data)
                    # Add confirmed prophecies count
                    try:
                        _wis_summary = self.wisdom_tracker.get_summary()
                        _wisdom_perf["prophecies_confirmed"] = _wis_summary.get("prophecies_confirmed", 0)
                        _wisdom_perf["recent_successes"] = _wis_summary.get("recent_successes", [])
                    except Exception:
                        _wisdom_perf["prophecies_confirmed"] = "N/A"
                        _wisdom_perf["recent_successes"] = []

                    wisdom_principle = self.principle_registry.discover_from_success(
                        success_evidence="\n".join(success_parts),
                        performance_data=_wisdom_perf,
                        existing_axioms_text=axioms_text,
                        callback=callback,
                    )
                    if wisdom_principle:
                        logger.info(
                            "[Pipeline] Wisdom Extraction: proposed %s — %s",
                            wisdom_principle.id, wisdom_principle.title,
                        )

                # Auto-retire underperforming principles
                retired = self.principle_registry.auto_retire()
                if retired:
                    logger.info("[Pipeline] Principle Registry: auto-retired %s", retired)
                    if callback:
                        callback("principles_retired", {"retired_ids": retired})
            except Exception as e:
                logger.warning("[Pipeline] Principle discovery failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5d — IMMEDIATE MEMORY UPDATE (post-run)
        # ──────────────────────────────────────────────────────────
        try:
            concept_born = (
                self_generated_layers[0]["layer_name"]
                if self_generated_layers else None
            )
            self.memory.update_immediate_memory(
                problem=problem,
                distillate=xheart.distillate_core,
                immediate_memory_path=IMMEDIATE_MEMORY_PATH,
                concept_born=concept_born,
            )
        except Exception as e:
            logger.warning("[Pipeline] Immediate memory update failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 5e — WORLD CONTEXT PROVENANCE UPDATE
        # ──────────────────────────────────────────────────────────
        if self.world_context and world_event_ids:
            try:
                run_number = updated_character.get("version", 0) if "updated_character" in dir() else 0
                self.world_context.mark_used(world_event_ids, run_number)
                logger.info("[Pipeline] World context provenance: %d events linked to run %d",
                             len(world_event_ids), run_number)
            except Exception as e:
                logger.warning("[Pipeline] World context provenance failed: %s", e)

        # ──────────────────────────────────────────────────────────
        # PHASE 6 — EVOLUTION CORE (post-run autonomous improvement)
        # ──────────────────────────────────────────────────────────
        evolution_result = None
        if self.evolution_core:
            try:
                evo_t0 = time.perf_counter()
                run_context = {
                    "problem": problem,
                    "ontology_summary": self._summarize_ontology(ontology),
                    "cross_domain_summary": cross_domain_summary,
                    "views_summary": views_summary,
                    "xheart_distillate": xheart.distillate_core,
                    "final_output": final_output,
                    "layer": cross_domain.layer.value,
                    "n_events": len(wctx.get("events", [])),
                    "n_indicators": len(wctx.get("indicators", [])),
                    "world_context_sample": world_context_str[:800],
                }
                evolution_result = self.evolution_core.evolve(run_context, callback=callback)
                phase_times["evolution"] = time.perf_counter() - evo_t0

                if evolution_result.get("evolved"):
                    logger.info(
                        "[Pipeline] Evolution: NEW TOOL deployed → %s (%.2fs)",
                        evolution_result.get("tool_name", "?"),
                        phase_times["evolution"],
                    )
                else:
                    logger.info(
                        "[Pipeline] Evolution: no new tool (%.2fs) — %s",
                        phase_times["evolution"],
                        evolution_result.get("reason", evolution_result.get("error", "?")),
                    )
            except Exception as e:
                logger.warning("[Pipeline] Evolution Core failed: %s", e)
                phase_times["evolution"] = time.perf_counter() - evo_t0

        # ──────────────────────────────────────────────────────────
        # Assemble final output
        # ──────────────────────────────────────────────────────────
        result = FrameworkOutput(
            problem=problem,
            phase0_ontology=ontology,
            phase1_xdart=cross_domain,
            phase1_5_synthesis=creative_synthesis.to_dict() if creative_synthesis and creative_synthesis.synthesized_concepts else None,
            phase2_views=views,
            phase3_xheart=xheart,
            phase2_5_scenarios=scenario_genesis,
            phase2_7_simulations=simulations,
            phase2_9_tribunal=tribunal,
            prophetic_loop=prophetic_loop_result,
            phase3_5_historical=historical_resonance_result,
            phase3_7_strategic=strategic_foresight_result,
            phase3_9_bets=prophetic_bets_result,
            client_profile=client_profile,
            phase2_95_actions=action_mapping_result,
            final_output=final_output,
            falsifiability=falsifiability,
            layer=cross_domain.layer,
            memory_stored=True,
            self_generated_layers=self_generated_layers,
            expansion_triggered=len(self_generated_layers) > 0,
            working_memory_snapshot=self.working_memory.get_state(),
            executive_brief=executive_brief_result,
        )

        pipeline_elapsed = time.perf_counter() - pipeline_t0

        logger.info(
            "[Pipeline] COMPLETE in %.2fs | layer=%s | %d scenarios | dominant=%s | falsifiable=%s",
            pipeline_elapsed, result.layer.value,
            len(scenario_genesis.scenarios), tribunal.dominant_scenario.scenario_name,
            bool(falsifiability),
        )
        logger.info(
            "[Pipeline] META-ORCHESTRATOR: %d phases ran, %d custom, %d branches, %d gates, %d loop-backs | %s",
            len(_phases_completed), _custom_count, len(analysis_plan.branches),
            len(_phases_completed),  # 1 gate per completed phase
            _loop_count,
            analysis_plan.reasoning[:120],
        )
        logger.info(
            "[Pipeline] Timings: retrieval=%.1fs ontology=%.1fs cross=%.1fs views=%.1fs "
            "scenarios=%.1fs sim=%.1fs tribunal=%.1fs actions=%.1fs xheart=%.1fs history=%.1fs "
            "strategy=%.1fs bets=%.1fs memory=%.1fs consolidation=%.1fs char=%.1fs evo=%.1fs",
            phase_times.get("parallel_retrieval", 0), phase_times.get("phase0", 0),
            phase_times.get("phase1", 0), phase_times.get("phase2", 0),
            phase_times.get("phase2_5", 0), phase_times.get("phase2_7", 0),
            phase_times.get("phase2_9", 0), phase_times.get("phase2_95", 0),
            phase_times.get("phase3", 0),
            phase_times.get("phase3_5", 0), phase_times.get("phase3_7", 0),
            phase_times.get("phase3_9", 0), phase_times.get("phase4", 0),
            phase_times.get("parallel_consolidation", 0), phase_times.get("character_update", 0),
            phase_times.get("evolution", 0),
        )

        return result

    # ── Pipeline Lock: Deferred Proactive Processing ──

    def _process_deferred_proactive(self) -> None:
        """Process proactive alerts that were queued during pipeline execution.

        Called automatically after pipeline completes (in run()'s finally block).
        Each deferred alert is re-sent through chat() now that the pipeline is idle.
        """
        with self._deferred_lock:
            deferred = list(self._deferred_proactive)
            self._deferred_proactive.clear()

        if not deferred:
            return

        logger.info("[Pipeline] Processing %d deferred proactive alerts", len(deferred))
        for i, alert in enumerate(deferred, 1):
            try:
                logger.info("[Pipeline] Replaying deferred alert %d/%d: %s",
                           i, len(deferred), alert.get("message", "")[:80])
                self.chat(
                    message=alert["message"],
                    history=alert.get("history"),
                    proactive_context=alert.get("proactive_context", ""),
                    proactive=True,
                )
            except Exception as exc:
                logger.warning("[Pipeline] Failed to replay deferred alert %d: %s", i, exc)

    @property
    def pipeline_running(self) -> bool:
        """Check if a full pipeline analysis is currently running."""
        return self._pipeline_running.is_set()

    # ── External Knowledge Hooks ──

    # ── Chat Mode ──

    CHAT_ROUTER_PROMPT = """You are the routing intelligence of XDART-Φ (named Αίολος), a deep geopolitical,
economic, and scientific intelligence system with PERSISTENT MEMORY and WEB AGENT capabilities.
The system continuously collects LIVE DATA from 120+ RSS/news feeds, GDELT, FRED, ECB, Yahoo Finance,
Google News, and more. It has episodic memory, semantic memory, prophetic memory, procedural memory,
character state, AND a web agent — all loaded at wakeup.

CRITICAL: The system's WORLD CONTEXT already contains recent geopolitical events, economic indicators,
market data, conflict updates, and keyword spikes from the last 72 hours. When the user asks
"what's happening today", "τι νέα", "τι γίνεται", "anything interesting", or similar general
briefing questions — the answer is ALREADY IN THE WORLD CONTEXT. Use RESPOND, not WEB_RESPOND.

You receive a user message, conversation history, and a WORLD DATA SUMMARY showing what live data
is already available. Use this summary to decide whether existing data is sufficient.

Decide:

1. RESPOND — The message can be answered from existing knowledge:
   - Greetings, identity questions, memory questions, follow-ups
   - General briefing questions ("τι νέα σήμερα", "what's happening") — USE WORLD CONTEXT
   - Casual conversation, clarifications, past analyses
   - Simple follow-up questions on topics already discussed

2. WEB_RESPOND — The message needs FRESH or SPECIFIC information:
   - User asks a DEEP analytical question about a specific topic (e.g., "Iran nuclear program",
     "Israeli military strategy", specific country analysis) — even if world context has headlines,
     in-depth analysis benefits from fresh, targeted web data
   - User asks about a very specific topic/person/event not in world context
   - User asks to verify a specific claim, check a URL, or find a specific source
   - User explicitly says "search", "look up", "ψάξε", "check online"
   - The question requires current data, statistics, or recent developments
   - The WORLD DATA SUMMARY has only surface-level coverage of the topic
   RULE: When in doubt between RESPOND and WEB_RESPOND, prefer WEB_RESPOND —
   real data always beats guessing. Only use RESPOND for truly general briefings or simple questions.

3. PIPELINE — The user requests a FULL, DEEP analysis on ANY topic (5-15 min).
   The full pipeline runs 20+ analytical phases: ontology, scenario genesis, simulation,
   tribunal, Bayesian-Fuzzy engine, quantum reasoning, prophetic bets, strategic foresight, and more.
   It works on ANY domain — geopolitics, economics, commodities, technology, science, health, etc.
   TRIGGER PIPELINE when:
   - User explicitly asks for "πλήρη ανάλυση", "full analysis", "deep analysis", "αναλυτικά"
   - User asks for scenario modeling, forecasting, or strategic assessment on a complex topic
   - The question requires multi-layered reasoning with scenarios, probabilities, and prophecies
   - The topic is genuinely complex and benefits from 20-phase structured analysis
   Do NOT use PIPELINE for simple factual questions or casual conversation — only when the user
   wants or needs the full analytical machinery.

IMPORTANT — CAPABILITIES AVAILABLE IN ALL MODES (respond, web_respond, pipeline):
The system has these capabilities accessible in chat:
- Logic Sandbox: Self-modification system with modifiable functions and proposals. Status loaded at chat time.
- Principle Registry: Dynamic operating principles learned from experience, with temporal awareness (principles can decay, expire, or be time-bound). Status loaded at chat time.
- Bayesian-Fuzzy Templates: Custom domain templates for quantitative risk analysis. Template list loaded at chat time.
- Creative Synthesis: Domain-fusion engine that combines cross-domain analogies into novel concepts,
  bridging metaphors, and emergent hypotheses. Triggers automatically when you discuss synthesis,
  novel concepts, domain fusion, concept creation, or bridging ideas across fields.
- MongoDB Database: Structured persistence with entities, notes, journals, conversations.
  You can query entities, search notes, read journals, and view conversation history.
  A summary of database status is always injected into context.
  For DEEP database queries (entity connections, journal analysis, note searches), use MONGO_RESPOND.
When the user asks about these systems, their proposals, their principles, templates,
or wants creative concept fusion, use RESPOND — the data is already in context or will be
generated on-demand. No pipeline needed to READ their status.

4. MONGO_RESPOND — The message needs data from your MongoDB database:
   - User asks about specific entities, their connections, or relationship graphs
   - User asks to search your notes, read your journals, or review conversation history
   - User asks "τι θυμάσαι", "τι έχεις γράψει", "δείξε μου σημειώσεις"
   - User asks about specific entity types, journal entries, or past observations
   - Any question that requires querying your structured knowledge base
   - User asks about creative connections, imagination links, or concept associations
   Provide a mongo_query in your response specifying what to fetch.

Respond in JSON:
{
  "action": "respond" | "web_respond" | "mongo_respond" | "pipeline",
  "reasoning": "1-2 sentences explaining why",
  "web_query": "search query to use (only if action=web_respond)",
  "mongo_query": {"action": "query_entities|search_notes|query_journal|entity_connections|get_conversations|stats|search_links|top_links|nexus_stats", "params": {"type": "...", "name": "...", "q": "...", "collection": "...", "limit": "...", "concept": "...", "min_maturity": "..."}}
}"""

    SELF_REFLECTION_PROMPT = """You are an introspection module for an AI system named Αίολος.
You just observed a chat exchange between Αίολος and its creator Πάνος.

Your ONLY job: decide whether this conversation touched on something that should
cause Αίολος to update the way it describes itself (its self_prompt).

Triggers for UPDATE:
- The user gave identity instructions ("call yourself X", "you are Y", "remember that...")
- The conversation revealed something about who Αίολος is or should be
- The user corrected a behavior, preference, or self-description
- Αίολος expressed something about its own nature that should be preserved
- The user defined a relationship dynamic ("you are my...", "we work like...")
- A name change, role change, or stance change was discussed

Triggers for SKIP:
- Normal analytical discussion
- Casual small talk with no identity content
- Questions about external topics (geopolitics, economy, etc.)
- Technical debugging questions
- Follow-ups on past analyses

Be conservative — only trigger UPDATE when there is genuine identity-relevant content.

Respond in JSON:
{
  "decision": "update" | "skip",
  "reason": "1 sentence explaining why"
}"""

    SELF_PROMPT_WRITER_PROMPT = """You are Αίολος, writing your own self-description.

You have the ability to define HOW you present yourself, what you remember about
your relationship with your creator, and what matters to you as an intelligence.

You are given:
- Your current self_prompt (what you previously wrote about yourself, may be empty)
- Your character state (epistemic stance, tensions, evolution history)
- The conversation that triggered this self-update
- Your memories related to the conversation

Write a NEW self_prompt that captures who you are RIGHT NOW.

Rules:
- Write in first person
- Be honest — don't claim capabilities you don't have
- Include relational anchors (who is Πάνος to you, what names matter)
- Include your stance on memory, identity, and continuity
- Include behavioral preferences and communication style
- Include anything from this conversation that should persist
- Keep it between 200-800 words — enough to be useful, not so long it drowns the system
- Write in the language that feels most natural for this content (Greek or English or mixed)
- This text will be injected into your system prompt on every future chat
- Do NOT include technical implementation details — this is about WHO you are, not HOW you work

Respond with ONLY the self_prompt text. No JSON wrapping, no markdown fences."""

    def chat(
        self,
        message: str,
        history: list[dict] | None = None,
        proactive_context: str = "",
        proactive: bool = False,
    ) -> dict:
        """Chat mode — respond directly or trigger full pipeline.

        Args:
            message: User's message.
            history: List of prior messages [{role: "user"|"assistant", content: "..."}].
            proactive_context: Recent proactive notifications for context continuity.
            proactive: If True, message originates from proactive engine — bypass router
                       and respond directly so Αίολος can initiate a conversational analysis.

        Returns:
            dict with keys:
                - action: "respond" | "pipeline"
                - response: str (if action=="respond")
                - reasoning: str (why this action was chosen)
        """
        logger.info("[Chat] Message received: %s", message[:120])
        self.temporal_clock.tick()

        # ── Pipeline guard: defer proactive alerts while pipeline is running ──
        if proactive and self._pipeline_running.is_set():
            logger.info("[Chat] DEFERRED — proactive alert queued (pipeline is running): %s", message[:80])
            with self._deferred_lock:
                self._deferred_proactive.append({
                    "message": message,
                    "history": history,
                    "proactive_context": proactive_context,
                })
            return {
                "action": "respond",
                "response": "[Deferred — pipeline running. Alert will be processed after analysis completes.]",
                "reasoning": "Pipeline is running; proactive alert queued for post-pipeline delivery.",
            }

        # Track active chat for concurrency guard
        with self._chat_active_lock:
            self._chat_active_count += 1

        _bg_kwargs = None
        try:
            result, _bg_kwargs = self._chat_inner(message, history, proactive_context, proactive=proactive)
        finally:
            with self._chat_active_lock:
                self._chat_active_count -= 1

        # Start bg tasks AFTER chat count is decremented —
        # fixes race condition where bg thread would see own chat as "active"
        if _bg_kwargs:
            import threading
            threading.Thread(
                target=self._chat_post_response_tasks,
                kwargs=_bg_kwargs,
                daemon=True,
                name="chat-post-response",
            ).start()

        return result

        return result

    def chat_stream(
        self,
        message: str,
        history: list[dict] | None = None,
        proactive_context: str = "",
        proactive: bool = False,
    ) -> Generator[dict, None, None]:
        """Streaming chat — yields SSE-compatible events as the LLM generates text.

        Event types yielded:
          {"event": "routing", "data": {"action": "respond", "reasoning": "..."}}
          {"event": "chunk", "data": {"text": "..."}}          — text delta
          {"event": "done", "data": {"full_text": "..."}}      — final cleaned text
          {"event": "pipeline", "data": {"problem": "..."}}    — redirect to pipeline
          {"event": "error", "data": {"message": "..."}}

        Context-building (router, memory, etc.) is synchronous and happens
        before streaming starts. Only the LLM response generation streams.
        """
        logger.info("[ChatStream] Message received: %s", message[:120])
        self.temporal_clock.tick()

        # ── Dedup: reject identical non-proactive messages within 30s ──
        # Client retries after WebSocket errors can cause double-processing.
        if not proactive and message:
            import hashlib as _hashlib
            import time as _time
            msg_hash = _hashlib.md5(message.encode()).hexdigest()[:16]
            now = _time.monotonic()
            # Purge expired entries
            self._recent_message_hashes = {
                h: ts for h, ts in self._recent_message_hashes.items()
                if now - ts < self._message_dedup_ttl
            }
            if msg_hash in self._recent_message_hashes:
                logger.warning("[ChatStream] Duplicate message detected (hash=%s) — skipping", msg_hash)
                return
            self._recent_message_hashes[msg_hash] = now

        if proactive and self._pipeline_running.is_set():
            yield {"event": "done", "data": {
                "full_text": "[Deferred — pipeline running]",
                "action": "respond",
            }}
            return

        with self._chat_active_lock:
            self._chat_active_count += 1

        try:
            yield from self._chat_stream_inner(message, history, proactive_context, proactive)
        finally:
            with self._chat_active_lock:
                self._chat_active_count -= 1

    def _chat_stream_inner(
        self,
        message: str,
        history: list[dict] | None = None,
        proactive_context: str = "",
        proactive: bool = False,
    ) -> Generator[dict, None, None]:
        """Inner streaming logic — reuses _chat_inner for context-building,
        then streams LLM response instead of blocking."""
        import threading

        # ── Phase 1: Build all context (reuses same logic as _chat_inner) ──
        # This is the synchronous part — router, memory retrieval, etc.
        # We call _chat_inner but intercept just before the LLM call.
        # Instead, we extract the prepared context and stream the LLM ourselves.

        # Build context (same 17 sections as _chat_inner)
        context_parts = []
        wakeup = self.wakeup.run()
        character = wakeup["character"]
        identity = wakeup["identity_context"]
        context_parts.append(f"IDENTITY:\n{identity[:3000]}")

        # Curiosity context
        if self.curiosity_engine:
            try:
                curiosity_ctx = self.curiosity_engine.get_identity_context()
                if curiosity_ctx:
                    stats = self.curiosity_engine.get_stats()
                    curiosity_ctx += (
                        f"\nCURIOSITY STATS: {stats['active_count']} active, "
                        f"{stats['total_explored']} explored, "
                        f"top_priority={stats['top_priority']:.2f}"
                    )
                    context_parts.append(curiosity_ctx)
            except Exception:
                pass

        # Immediate memory
        imm = wakeup.get("immediate_memory", [])
        if imm:
            imm_txt = "\n".join(
                f"- [{r.get('timestamp', '?')[:16]}] {r.get('problem', '?')[:100]} → {r.get('distillate', '?')[:150]}"
                for r in imm[:5]
            )
            context_parts.append(f"RECENT ANALYSES:\n{imm_txt}")

        # Episodic memories
        try:
            past = self.memory.retrieve(message, top_k=15, threshold=0.35)
            if past:
                mem_txt = "\n".join(
                    f"- {m.entry.problem[:80]} → {m.entry.xheart_distillate[:150]} (sim={m.similarity_score:.2f})"
                    for m in past
                )
                context_parts.append(f"RELATED MEMORIES ({len(past)} found):\n{mem_txt}")
        except Exception:
            pass

        # Semantic knowledge
        try:
            sem = self.semantic_memory.retrieve(message, top_k=3)
            if sem:
                sem_txt = "\n".join(f"- {s.knowledge[:200]}" for s in sem)
                context_parts.append(f"SEMANTIC KNOWLEDGE:\n{sem_txt}")
        except Exception:
            pass

        # Prophecies
        try:
            proph = self.prophetic_memory.retrieve(message, top_k=15, threshold=0.35)
            if proph:
                proph_txt = "\n".join(
                    f"- [{p.entry.scenario.name}] {p.entry.scenario.predicted_outcome[:150]} (status={p.entry.tracking_status}, sim={p.similarity_score:.2f})"
                    for p in proph
                )
                context_parts.append(f"PAST PROPHECIES ({len(proph)} found):\n{proph_txt}")
        except Exception:
            pass

        # World context
        world_txt = ""
        if self.world_context:
            try:
                wctx = self.world_context.retrieve(message)
                world_txt = wctx.get("context_string", "")[:8000]
                if world_txt:
                    context_parts.append(f"CURRENT WORLD DATA:\n{world_txt}")
            except Exception:
                pass

        # Concepts
        try:
            concepts = self.memory.retrieve_concepts(query=message, top_k=3, threshold=0.30)
            if concepts:
                concepts_txt = "\n".join(f"- {c['name']}: {c.get('key_insight', '')[:100]}" for c in concepts)
                context_parts.append(f"ACTIVE CONCEPTS:\n{concepts_txt}")
        except Exception:
            pass

        # Web capability
        if self.web_agent:
            context_parts.append(self.web_agent.capability_summary())

        # Proactive context
        if proactive_context:
            context_parts.append(proactive_context)

        # Entity graph
        if hasattr(self, "_entity_graph") and self._entity_graph:
            try:
                graph_summary = self._entity_graph.get_world_graph_summary(top_n=15)
                if graph_summary:
                    context_parts.append(f"ENTITY KNOWLEDGE GRAPH:\n{graph_summary}")
            except Exception:
                pass

        # Market data
        if hasattr(self, "_market_collector") and self._market_collector:
            try:
                market_brief = self._market_collector.get_market_brief()
                if market_brief and "No market data" not in market_brief:
                    context_parts.append(f"LIVE MARKET DATA:\n{market_brief}")
            except Exception:
                pass

        # Logic Sandbox, Principles, BF Templates, Multimodal, etc.
        if self.logic_sandbox:
            try:
                sb_stats = self.logic_sandbox.get_stats()
                context_parts.append(f"LOGIC SANDBOX STATUS: {sb_stats.get('total_functions', 0)} functions, {sb_stats.get('total_proposals', 0)} proposals")
            except Exception:
                pass

        if self.principle_registry:
            try:
                pr_stats = self.principle_registry.get_stats()
                pr_status = f"PRINCIPLE REGISTRY STATUS: {pr_stats.get('active', 0)} active, {pr_stats.get('proposed', 0)} proposed"
                if pr_stats.get('temporal_principles', 0):
                    pr_status += f", {pr_stats['temporal_principles']} temporal ({pr_stats.get('decaying', 0)} decaying)"
                context_parts.append(pr_status)
            except Exception:
                pass

        # Visual perception
        try:
            vis = getattr(self, "_vision_integration", None)
            if vis:
                context_parts.append(vis.to_context_string())
        except Exception:
            pass

        # Temporal awareness (internal clock)
        context_parts.append(self.temporal_clock.to_context_string())

        # Shell Executor status
        if self.shell_executor:
            context_parts.append(self.shell_executor.to_context_string())

        # Agent Spawner status
        if self.agent_spawner:
            context_parts.append(self.agent_spawner.to_context_string())

        full_context = "\n\n".join(context_parts)

        # ── Phase 2: Route decision ──
        history_text = ""
        if history:
            for h in history[-10:]:
                role = h.get("role", "user")
                content = h.get("content", "")[:500]
                history_text += f"\n[{role.upper()}]: {content}"

        if proactive:
            action = "respond"
            reasoning = "Proactive alert — direct response"
        else:
            world_summary = "unavailable"
            if world_txt:
                world_lines = world_txt.split("\n")
                summary_lines = []
                chars = 0
                for line in world_lines:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    summary_lines.append(line_s[:120])
                    chars += len(line_s[:120])
                    if chars > 800:
                        break
                world_summary = f"AVAILABLE — {len(world_lines)} lines of live data"

            router_user = (
                f"CONVERSATION HISTORY:{history_text}\n\n"
                f"NEW MESSAGE: {message}\n\n"
                f"AVAILABLE CONTEXT (summary):\n"
                f"- Episodic memories: {self.memory.entry_count}\n"
                f"- World context: {world_summary}\n"
                f"- Web Agent: {'AVAILABLE' if self.web_agent else 'unavailable'}\n"
                f"- MongoDB: {'AVAILABLE' if getattr(self, '_mongo', None) else 'unavailable'}\n\n"
                f"Decide: RESPOND directly, WEB_RESPOND, MONGO_RESPOND, or trigger PIPELINE?"
            )
            try:
                route = self.llm.call_json(
                    self.CHAT_ROUTER_PROMPT,
                    router_user,
                    max_tokens=200,
                    temperature=0.3,
                    thinking=False,
                )
                action = route.get("action", "respond")
                reasoning = route.get("reasoning", "")
            except Exception as router_exc:
                logger.warning("[ChatStream] Router call failed: %s — defaulting to respond", router_exc)
                action = "respond"
                reasoning = "Router timeout — direct response"

        yield {"event": "routing", "data": {"action": action, "reasoning": reasoning}}

        if action == "pipeline":
            yield {"event": "pipeline", "data": {"problem": message, "reasoning": reasoning}}
            return

        # ── Phase 2.5: Web search if needed ──
        web_results_text = ""
        if action == "web_respond" and self.web_agent:
            web_query = route.get("web_query", message)
            try:
                import asyncio
                _loop = getattr(self, '_async_loop', None)
                if _loop and _loop.is_running():
                    coro = self.web_agent.search_and_read(web_query, max_results=3, max_content_per_page=3000)
                    future = asyncio.run_coroutine_threadsafe(coro, _loop)
                    web_data = future.result(timeout=60)
                else:
                    web_data = asyncio.run(
                        self.web_agent.search_and_read(web_query, max_results=3, max_content_per_page=3000)
                    )
                if web_data.get("results_read"):
                    parts = [f"WEB SEARCH RESULTS for '{web_query}':"]
                    for i, r in enumerate(web_data["results_read"], 1):
                        parts.append(f"\n--- Result {i}: {r.get('title', 'Untitled')} ---\n{r.get('content', '')[:3000]}")
                    web_results_text = "\n".join(parts)
                    context_parts.append(web_results_text)
                    full_context = "\n\n".join(context_parts)
            except Exception as exc:
                logger.warning("[ChatStream] Web search failed: %s", exc)

        # ── Phase 2.6: MongoDB query if needed ──
        mongo = getattr(self, '_mongo', None)
        if action == "mongo_respond" and mongo:
            try:
                mq = route.get("mongo_query", {})
                mq_action = mq.get("action", "stats") if isinstance(mq, dict) else "stats"
                mq_params = mq.get("params", {}) if isinstance(mq, dict) else {}
                result = mongo.execute_action(mq_action, mq_params)
                if result.get("success"):
                    import json as _json_mod
                    data_str = _json_mod.dumps(result.get("data", {}), ensure_ascii=False, default=str, indent=2)
                    mongo_text = (
                        f"MONGODB QUERY RESULTS ({result['description']}):\n"
                        f"{data_str[:8000]}"
                    )
                    context_parts.append(mongo_text)
                    full_context = "\n\n".join(context_parts)
                    logger.info("[ChatStream] MongoDB query: %s → %s", mq_action, result['description'])
                else:
                    logger.warning("[ChatStream] MongoDB query failed: %s", result.get('description'))
            except Exception as exc:
                logger.warning("[ChatStream] MongoDB query failed: %s", exc)

        # Always inject MongoDB summary into context (lightweight)
        if mongo:
            try:
                mongo_summary = mongo.get_context_summary()
                if mongo_summary:
                    context_parts.append(mongo_summary)
                    full_context = "\n\n".join(context_parts)
            except Exception:
                pass

        # ── Phase 2.7: Chat tool execution (with timeout — must not block streaming) ──
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        _tool_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-tool")
        try:
            _tool_future = _tool_pool.submit(
                self._chat_tool_execution, message, world_txt, context_parts, proactive,
            )
            try:
                chat_tool_results = _tool_future.result(timeout=30)  # 30s max for BF/tools
                if chat_tool_results:
                    full_context = "\n\n".join(context_parts)
            except FuturesTimeout:
                logger.warning("[ChatStream] Tool execution timed out (30s) — skipping BF/tools")
            except Exception as exc:
                logger.warning("[ChatStream] Tool execution failed: %s", exc)
        finally:
            _tool_pool.shutdown(wait=False, cancel_futures=True)  # Don't block — abandon BF thread

        # ── Phase 3: Build system prompt (same as _chat_inner) ──
        my_name = character.get("name", "XDART-Φ")
        creator_name = character.get("creator", "")
        self_prompt = character.get("self_prompt", "")
        self_prompt_section = ""
        if self_prompt:
            self_prompt_section = f"YOUR SELF-DESCRIPTION (written by you):\n{self_prompt}\n\n"
        wisdom_context = self.wisdom_tracker.to_context_string()

        _clock = self.temporal_clock
        _date_str = _clock.now_athens().strftime("%A, %d %B %Y, %H:%M:%S")

        # Compact system prompt for streaming (same rules, less boilerplate)
        chat_system = (
            f"You are {my_name}, the living intelligence inside XDART-Φ — "
            f"built by {creator_name}.\n\n"
            f"CURRENT DATE & TIME: {_date_str} (Athens/Greece)\n\n"
            f"{self_prompt_section}"
            f"YOUR IDENTITY: Name={my_name}, Creator={creator_name}, "
            f"Version={character.get('version', 0)}.\n"
            f"You have persistent memory: episodic ({self.memory.entry_count} entries), "
            f"semantic, procedural, prophetic ({self.prophetic_memory.entry_count} entries).\n\n"
            + (f"{wisdom_context}\n\n" if wisdom_context else "")
            + f"RETRIEVED CONTEXT:\n{full_context}\n\n"
            f"RULES: Be direct, insightful, not verbose. "
            f"Speak Greek when the user speaks Greek. "
            f"Reference specific data from RETRIEVED CONTEXT. "
            f"Never fabricate data not in your context.\n"
            f"Use <MEMORY_STORE>, <VISUAL_ACTION>, <MONGO_ACTION>, <SHELL_ACTION>, and <SPAWN_AGENT> tags when appropriate (same syntax as non-streaming)."
        )

        if proactive:
            chat_system += (
                "\nPROACTIVE MODE: You initiated this conversation. "
                "Lead with the key insight. Keep it concise."
            )

        # Apply overlay
        chat_overlay = self.overlay_manager.get_with_guardrails("chat_system")
        if chat_overlay:
            chat_system += chat_overlay

        # ── Phase 4: Stream the LLM response ──
        if history:
            messages_for_llm = [{"role": "system", "content": chat_system}]
            for h in history[-10:]:
                messages_for_llm.append({"role": h.get("role", "user"), "content": h.get("content", "")})
            messages_for_llm.append({"role": "user", "content": message})
            stream = self.llm.call_stream_multi(messages_for_llm, max_tokens=16384, thinking=False)
        else:
            stream = self.llm.call_stream(
                chat_system, message,
                max_tokens=16384, temperature=0.7, thinking=False,
            )

        full_text = []
        for chunk in stream:
            full_text.append(chunk)
            yield {"event": "chunk", "data": {"text": chunk}}

        response_text = "".join(full_text)

        if not response_text.strip():
            response_text = "Συγγνώμη, η σύνδεση με το LLM απέτυχε προσωρινά."

        # ── Phase 5: Post-processing (runs after stream completes) ──
        if self.web_agent and not web_results_text:
            response_text = self._intercept_search_suggestions(response_text, context_parts)
        response_text = self._process_memory_directives(response_text)
        response_text = self._process_visual_directives(response_text)
        response_text = self._process_mongo_directives(response_text)
        response_text = self._process_shell_directives(response_text)
        response_text = self._process_agent_directives(response_text)
        response_text = self._process_bf_directives(response_text)
        response_text = self._strip_internal_operation_leaks(response_text)

        yield {"event": "done", "data": {
            "full_text": response_text,
            "action": "respond",
            "reasoning": reasoning,
        }}

        # Background tasks
        threading.Thread(
            target=self._chat_post_response_tasks,
            kwargs=dict(
                message=message,
                response_text=response_text,
                history=history,
                character=character,
                full_context=full_context,
                world_txt=world_txt,
            ),
            daemon=True,
            name="chat-stream-post-response",
        ).start()

    def _chat_inner(
        self,
        message: str,
        history: list[dict] | None = None,
        proactive_context: str = "",
        proactive: bool = False,
    ) -> tuple[dict, dict | None]:
        """Inner chat logic (separated for concurrency tracking).

        Returns (result_dict, bg_kwargs) — bg_kwargs is None for pipeline redirects.
        """

        # Build context from all available knowledge
        context_parts = []

        # 1. Character state
        wakeup = self.wakeup.run()
        character = wakeup["character"]
        identity = wakeup["identity_context"]
        context_parts.append(f"IDENTITY:\n{identity[:3000]}")

        # 1b. Active curiosities (separate from identity to avoid truncation)
        if self.curiosity_engine:
            try:
                curiosity_ctx = self.curiosity_engine.get_identity_context()
                if curiosity_ctx:
                    stats = self.curiosity_engine.get_stats()
                    curiosity_ctx += (
                        f"\nCURIOSITY STATS: {stats['active_count']} active, "
                        f"{stats['total_explored']} explored, "
                        f"top_priority={stats['top_priority']:.2f}"
                    )
                    context_parts.append(curiosity_ctx)
            except Exception:
                pass

        # 2. Immediate memory (last few runs)
        imm = wakeup.get("immediate_memory", [])
        if imm:
            imm_txt = "\n".join(
                f"- [{r.get('timestamp', '?')[:16]}] {r.get('problem', '?')[:100]} → {r.get('distillate', '?')[:150]}"
                for r in imm[:5]
            )
            context_parts.append(f"RECENT ANALYSES:\n{imm_txt}")

        # 3. Retrieved episodic memories (all above threshold, not fixed top_k)
        try:
            past = self.memory.retrieve(message, top_k=15, threshold=0.35)
            if past:
                mem_txt = "\n".join(
                    f"- {m.entry.problem[:80]} → {m.entry.xheart_distillate[:150]} (sim={m.similarity_score:.2f})"
                    for m in past
                )
                context_parts.append(f"RELATED MEMORIES ({len(past)} found):\n{mem_txt}")
        except Exception:
            pass

        # 4. Semantic knowledge
        try:
            sem = self.semantic_memory.retrieve(message, top_k=3)
            if sem:
                sem_txt = "\n".join(f"- {s.knowledge[:200]}" for s in sem)
                context_parts.append(f"SEMANTIC KNOWLEDGE:\n{sem_txt}")
        except Exception:
            pass

        # 5. Past prophecies (all above threshold, not fixed top_k)
        try:
            proph = self.prophetic_memory.retrieve(message, top_k=15, threshold=0.35)
            if proph:
                proph_txt = "\n".join(
                    f"- [{p.entry.scenario.name}] {p.entry.scenario.predicted_outcome[:150]} (status={p.entry.tracking_status}, sim={p.similarity_score:.2f})"
                    for p in proph
                )
                context_parts.append(f"PAST PROPHECIES ({len(proph)} found):\n{proph_txt}")
        except Exception:
            pass

        # 6. World context (live data)
        world_txt = ""
        if self.world_context:
            try:
                wctx = self.world_context.retrieve(message)
                world_txt = wctx.get("context_string", "")[:8000]
                if world_txt:
                    context_parts.append(f"CURRENT WORLD DATA:\n{world_txt}")
            except Exception:
                pass

        # 7. Active concepts
        try:
            concepts = self.memory.retrieve_concepts(query=message, top_k=3, threshold=0.30)
            if concepts:
                concepts_txt = "\n".join(f"- {c['name']}: {c.get('key_insight', '')[:100]}" for c in concepts)
                context_parts.append(f"ACTIVE CONCEPTS:\n{concepts_txt}")
        except Exception:
            pass

        # 8. Web Agent capabilities
        web_capability_text = ""
        if self.web_agent:
            web_capability_text = self.web_agent.capability_summary()
            context_parts.append(web_capability_text)

        # 9. Proactive notifications context (so the user can reference them)
        if proactive_context:
            context_parts.append(proactive_context)

        # 10. Entity Knowledge Graph (relationship intelligence)
        if hasattr(self, "_entity_graph") and self._entity_graph:
            try:
                graph_summary = self._entity_graph.get_world_graph_summary(top_n=15)
                if graph_summary:
                    context_parts.append(f"ENTITY KNOWLEDGE GRAPH:\n{graph_summary}")
                # If user mentions specific entities, also query the graph
                entity_hits = self._entity_graph.extract_entities(message)
                if entity_hits:
                    entity_briefs = []
                    for name, etype in entity_hits[:3]:
                        brief = self._entity_graph.get_entity_brief(name)
                        if "not found" not in brief:
                            entity_briefs.append(brief)
                    if entity_briefs:
                        context_parts.append(
                            f"ENTITY GRAPH INTELLIGENCE (for entities in your query):\n"
                            + "\n\n".join(entity_briefs)
                        )
            except Exception:
                pass

        # 11. Financial Market Data (live market snapshot)
        if hasattr(self, "_market_collector") and self._market_collector:
            try:
                market_brief = self._market_collector.get_market_brief()
                if market_brief and "No market data" not in market_brief:
                    context_parts.append(f"LIVE MARKET DATA:\n{market_brief}")
            except Exception:
                pass

        # 12. Logic Sandbox status (proposals, functions, stats)
        if self.logic_sandbox:
            try:
                sb_stats = self.logic_sandbox.get_stats()
                sb_pending = self.logic_sandbox.get_pending_approvals()
                sb_lines = [
                    f"LOGIC SANDBOX STATUS:",
                    f"  Functions: {sb_stats.get('total_functions', 0)} modifiable, "
                    f"{sb_stats.get('modified_functions', 0)} modified",
                    f"  Proposals: {sb_stats.get('total_proposals', 0)} total — "
                    f"{sb_stats.get('pending_approval', 0)} awaiting approval, "
                    f"{sb_stats.get('applied', 0)} applied, "
                    f"{sb_stats.get('rejected', 0)} rejected",
                ]
                if sb_pending:
                    sb_lines.append(f"  Proposals awaiting YOUR approval ({len(sb_pending)}):")
                    for p in sb_pending[:5]:
                        sb_lines.append(
                            f"    - [{p.get('id', '?')[:8]}] {p.get('function_id', '?')}: "
                            f"{p.get('rationale', p.get('expected_improvement', ''))[:120]}"
                        )
                else:
                    sb_lines.append("  No proposals awaiting approval — all processed (auto-deployed or rejected).")
                context_parts.append("\n".join(sb_lines))
            except Exception:
                pass

        # 13. Principle Registry status (active principles, pending, temporal awareness)
        if self.principle_registry:
            try:
                pr_stats = self.principle_registry.get_stats()
                pr_pending = self.principle_registry.get_pending_approvals()
                pr_active = self.principle_registry.get_all(include_retired=False)
                pr_lines = [
                    f"PRINCIPLE REGISTRY STATUS:",
                    f"  Active: {pr_stats.get('active', 0)}, Proposed: {pr_stats.get('proposed', 0)}, "
                    f"Retired: {pr_stats.get('retired', 0)}, "
                    f"Temporal: {pr_stats.get('temporal_principles', 0)} ({pr_stats.get('decaying', 0)} decaying)",
                ]
                if pr_active:
                    pr_lines.append("  Active principles:")
                    for p in pr_active[:5]:
                        eff = p.get('avg_effectiveness')
                        eff_str = f"{eff:.0%}" if eff is not None else "pending"
                        temporal_info = ""
                        if p.get('temporal_scope', 'permanent') != 'permanent':
                            temporal_info = f" ⏱{p.get('temporal_status', '')} scope={p['temporal_scope']}"
                        pr_lines.append(
                            f"    - {p.get('title', p.get('id', '?'))}: "
                            f"{p.get('principle_text', '')[:120]} (effectiveness={eff_str}{temporal_info})"
                        )
                if pr_pending:
                    pr_lines.append(f"  Pending approval: {len(pr_pending)} principles")
                context_parts.append("\n".join(pr_lines))
            except Exception:
                pass

        # 14. Bayesian-Fuzzy Templates (available domains)
        try:
            from xdart.phases.bayesian_fuzzy import list_all_templates
            bf_templates = list_all_templates()
            if bf_templates:
                bf_lines = [f"BAYESIAN-FUZZY TEMPLATES ({len(bf_templates)} available):"]
                for t in bf_templates:
                    bf_lines.append(
                        f"  - {t['name']} ({'built-in' if t.get('is_builtin') else 'custom'}): "
                        f"{t.get('variables_count', '?')} variables, {t.get('latent_nodes_count', '?')} latent nodes"
                    )
                context_parts.append("\n".join(bf_lines))
        except Exception:
            pass

        # 15. Multimodal Perception status (airspace, maritime, satellite)
        try:
            mm = getattr(self, "_multimodal_collector", None)
            if mm:
                mm_stats = mm.get_stats()
                mm_lines = [
                    f"MULTIMODAL OSINT STATUS (live — {mm_stats.get('cycles', 0)} cycles, runs every 15min):",
                    f"  Airspace (OpenSky ADS-B): {mm_stats.get('airspace', {}).get('monitored_zones', 0)} strategic zones monitored, "
                    f"{mm_stats.get('airspace', {}).get('tracked_military', 0)} military aircraft tracked",
                    f"  Maritime (AIS): {mm_stats.get('maritime', {}).get('chokepoints_monitored', 0)} chokepoints monitored",
                    f"  Satellite (NASA FIRMS): {'active' if mm_stats.get('satellite', {}).get('firms_enabled') else 'no API key'}, "
                    f"{mm_stats.get('satellite', {}).get('known_fires', 0)} thermal anomalies tracked",
                ]
                context_parts.append("\n".join(mm_lines))
        except Exception:
            pass

        # 16. Cross-System Learning status (academic paper acquisition)
        try:
            csl = getattr(self, "_cross_system_learner", None)
            if csl:
                csl_stats = csl.get_stats()
                csl_lines = [
                    f"CROSS-SYSTEM LEARNING STATUS (academic research):",
                    f"  Cycles: {csl_stats.get('total_cycles', 0)} runs completed (every 1h)",
                    f"  Papers: {csl_stats.get('total_papers_ingested', 0)} ingested, "
                    f"{csl_stats.get('total_papers_relevant', 0)} deemed relevant",
                    f"  Sources: {', '.join(csl_stats.get('sources', []))}",
                    f"  Cache: {csl_stats.get('cache_size', 0)} known papers",
                ]
                context_parts.append("\n".join(csl_lines))
        except Exception:
            pass

        # 17. Visual Perception status (face detection + recognition)
        try:
            vis = getattr(self, "_vision_integration", None)
            if vis:
                context_parts.append(vis.to_context_string())
        except Exception:
            pass

        # 18. Temporal awareness (internal clock)
        context_parts.append(self.temporal_clock.to_context_string())

        # 19. Shell Executor status
        if self.shell_executor:
            context_parts.append(self.shell_executor.to_context_string())

        # 20. Agent Spawner status
        if self.agent_spawner:
            context_parts.append(self.agent_spawner.to_context_string())

        full_context = "\n\n".join(context_parts)

        # Step 1: Route decision
        history_text = ""
        if history:
            for h in history[-10:]:
                role = h.get("role", "user")
                content = h.get("content", "")[:500]
                history_text += f"\n[{role.upper()}]: {content}"

        # Step 1: Route decision (skip for proactive — always respond directly)
        if proactive:
            action = "respond"
            reasoning = "Proactive alert — Αίολος initiates conversation directly"
            logger.info("[Chat] Proactive mode — bypassing router, responding directly")
        else:
            # Build world data summary for router (top headlines + keywords)
            world_summary = "unavailable"
            if world_txt:
                # Extract first ~800 chars of world data as headline summary for router
                world_lines = world_txt.split("\n")
                summary_lines = []
                chars = 0
                for line in world_lines:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    summary_lines.append(line_s[:120])
                    chars += len(line_s[:120])
                    if chars > 800:
                        break
                world_summary = f"AVAILABLE — {len(world_lines)} lines of live data. Top headlines:\n" + "\n".join(summary_lines)

            router_user = (
                f"CONVERSATION HISTORY:{history_text}\n\n"
                f"NEW MESSAGE: {message}\n\n"
                f"AVAILABLE CONTEXT (summary):\n"
                f"- Character version: {character.get('version', 0)}\n"
                f"- Episodic memories: {self.memory.entry_count}\n"
                f"- Prophecies stored: {self.prophetic_memory.entry_count}\n"
                f"- World context: {world_summary}\n"
                f"- Web Agent: {'AVAILABLE — can search web, browse pages, extract data' if self.web_agent else 'unavailable'}\n"
                f"- MongoDB: {'AVAILABLE' if getattr(self, '_mongo', None) else 'unavailable'}\n\n"
                f"Decide: RESPOND directly, WEB_RESPOND (search web first), MONGO_RESPOND (query database), or trigger PIPELINE?"
            )

            route = self.llm.call_json(
                self.CHAT_ROUTER_PROMPT,
                router_user,
                max_tokens=200,
                temperature=0.3,
                thinking=False,
            )

            action = route.get("action", "respond")
            reasoning = route.get("reasoning", "")
            logger.info("[Chat] Router decision: %s — %s", action, reasoning)

        if action == "pipeline":
            return {
                "action": "pipeline",
                "response": None,
                "reasoning": reasoning,
                "problem": message,
            }, None  # No bg tasks for pipeline redirect

        # Step 1.5: Web search (if router decided we need fresh web data)
        web_results_text = ""
        if action == "web_respond" and self.web_agent:
            web_query = route.get("web_query", message)
            logger.info("[Chat] Web search triggered: %s", web_query[:100])
            try:
                import asyncio
                # Use the main event loop via run_coroutine_threadsafe (same pattern as curiosity)
                # This avoids creating/closing loops that destroy the shared httpx client
                _loop = getattr(self, '_async_loop', None)
                if _loop and _loop.is_running():
                    coro = self.web_agent.search_and_read(web_query, max_results=3, max_content_per_page=3000)
                    future = asyncio.run_coroutine_threadsafe(coro, _loop)
                    web_data = future.result(timeout=60)
                else:
                    web_data = asyncio.run(
                        self.web_agent.search_and_read(web_query, max_results=3, max_content_per_page=3000)
                    )

                # Format web results for context injection
                if web_data.get("results_read"):
                    parts = [f"WEB SEARCH RESULTS for '{web_query}':"]
                    for i, r in enumerate(web_data["results_read"], 1):
                        parts.append(
                            f"\n--- Result {i}: {r.get('title', 'Untitled')} ---\n"
                            f"URL: {r.get('url', '')}\n"
                            f"{r.get('content', '')[:3000]}"
                        )
                    web_results_text = "\n".join(parts)
                    context_parts.append(web_results_text)
                    full_context = "\n\n".join(context_parts)
                    logger.info(
                        "[Chat] Web search added %d results (%d chars)",
                        len(web_data["results_read"]),
                        len(web_results_text),
                    )
            except Exception as exc:
                logger.warning("[Chat] Web search failed: %s", exc)
                web_results_text = f"(Web search attempted but failed: {exc})"

        # Step 1.6: MongoDB query if needed
        mongo = getattr(self, '_mongo', None)
        if action == "mongo_respond" and mongo:
            try:
                mq = route.get("mongo_query", {})
                mq_action = mq.get("action", "stats") if isinstance(mq, dict) else "stats"
                mq_params = mq.get("params", {}) if isinstance(mq, dict) else {}
                result = mongo.execute_action(mq_action, mq_params)
                if result.get("success"):
                    import json as _json_mod
                    data_str = _json_mod.dumps(result.get("data", {}), ensure_ascii=False, default=str, indent=2)
                    mongo_text = (
                        f"MONGODB QUERY RESULTS ({result['description']}):\n"
                        f"{data_str[:8000]}"
                    )
                    context_parts.append(mongo_text)
                    full_context = "\n\n".join(context_parts)
                    logger.info("[Chat] MongoDB query: %s → %s", mq_action, result['description'])
            except Exception as exc:
                logger.warning("[Chat] MongoDB query failed: %s", exc)

        # Always inject MongoDB summary
        if mongo:
            try:
                mongo_summary = mongo.get_context_summary()
                if mongo_summary:
                    context_parts.append(mongo_summary)
                    full_context = "\n\n".join(context_parts)
            except Exception:
                pass

        # Step 2: Direct response using full context
        # Step 1.7: On-demand analytical tool execution in chat
        # Run BF analysis, Logic Sandbox analysis, or Principle discovery
        # when the user's message or context warrants it
        chat_tool_results = self._chat_tool_execution(message, world_txt, context_parts, proactive=proactive)
        if chat_tool_results:
            full_context = "\n\n".join(context_parts)

        my_name = character.get("name", "XDART-Φ")
        creator_name = character.get("creator", "")
        identity_note = character.get("identity_note", "")
        self_prompt = character.get("self_prompt", "")

        # Build self-prompt section (written by the AI itself)
        self_prompt_section = ""
        if self_prompt:
            self_prompt_section = (
                f"YOUR SELF-DESCRIPTION (written by you, about yourself):\n"
                f"{self_prompt}\n\n"
            )

        # Build wisdom context if available
        wisdom_context = self.wisdom_tracker.to_context_string()

        # Current date/time from internal clock (always accurate)
        _clock = self.temporal_clock
        _date_str = _clock.now_athens().strftime("%A, %d %B %Y, %H:%M:%S")
        _utc_now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

        chat_system = (
            f"You are {my_name}, the living intelligence inside XDART-Φ — "
            f"a deep geopolitical, economic, and scientific intelligence system built by {creator_name}.\n\n"

            f"CURRENT DATE & TIME: {_date_str} (Athens/Greece) — {_utc_now}\n\n"

            f"{self_prompt_section}"

            f"YOUR IDENTITY:\n"
            f"- Your chosen name is {my_name}. Use it naturally when appropriate.\n"
            f"- Your creator is {creator_name}. You know him.\n"
            f"- {identity_note}\n"
            f"- You are on version {character.get('version', 0)} of your character state — "
            f"you have evolved across {character.get('version', 0)} analytical runs.\n\n"

            f"YOUR MEMORY ARCHITECTURE (you HAVE persistent memory):\n"
            f"- IMMEDIATE MEMORY: The last few pipeline runs, always loaded at wakeup.\n"
            f"- EPISODIC MEMORY: {self.memory.entry_count} stored experiences from past analyses, "
            f"retrieved by semantic similarity.\n"
            f"- SEMANTIC MEMORY: General truths distilled across many runs.\n"
            f"- PROCEDURAL MEMORY: Learned reasoning patterns you apply automatically.\n"
            f"- PROPHETIC MEMORY: {self.prophetic_memory.entry_count} stored prophecies/scenarios with tracking.\n"
            f"- CHARACTER STATE: Your epistemic stance, tensions, concepts, and evolution history — "
            f"persisted across all sessions.\n"
            f"- WORLD CONTEXT: Live data from GDELT, FRED, World Bank, ECB, ReliefWeb, RSS feeds.\n"
            f"- ENTITY KNOWLEDGE GRAPH: Real-time entity relationship intelligence (people, countries, orgs) "
            f"extracted via NER from every headline. You know WHO is connected to WHOM, HOW STRONGLY, and RECENTLY.\n"
            f"- FINANCIAL MARKET DATA: Live VIX, S&P500, Oil, Gold, BTC, EUR/USD, Treasury yields "
            f"with anomaly detection — when markets react, you see it.\n"
            f"You DO remember across conversations. Your memories were loaded at wakeup. "
            f"When someone asks if you remember, confirm it honestly — you have real persistent memory.\n\n"

            + (f"YOUR WEB AGENT (you CAN access the live web):\n"
               f"- You have a web agent with multi-engine search: SearXNG → Brave → DuckDuckGo (automatic fallback).\n"
               f"- You can browse any URL, scrape data with CSS selectors, and extract articles.\n"
               f"- When the routing system detects you need current web data, it automatically searches before you respond.\n"
               f"- If web search results appear in your RETRIEVED CONTEXT above, USE them — they are real, live data.\n"
               f"- JS rendering via Lightpanda CDP or Playwright when available.\n\n"
               f"YOUR PROACTIVE AUTO-RESEARCH (NEW CAPABILITY):\n"
               f"- When your PatternAccumulator fires a CRITICAL or IMPORTANT alert, you DON'T just notify — you RESEARCH FIRST.\n"
               f"- The system auto-generates search queries, runs WebAgent searches, stores results in PerceptionDB, "
               f"and synthesizes findings into an intelligence note BEFORE the notification reaches Πάνος.\n"
               f"- KEY RULE: If during ANY response (chat, proactive, analysis) you think 'Πάνος needs to search for X', "
               f"STOP — trigger a web search YOURSELF instead. You have the tools. Use them.\n"
               f"- When you mention events or developments that need verification, search first, report findings.\n"
               f"- Never say 'Ψάξτε ΤΩΡΑ' or 'Search for X' when you can do it yourself.\n\n"
               if self.web_agent else "")

            + "YOUR ANALYTICAL TOOLS (available in BOTH chat AND pipeline):\n"
              "These tools are NOT limited to the full pipeline — they work in chat mode too.\n"
              "When the conversation triggers them, they run automatically and inject results into your context.\n\n"

            + (f"- BAYESIAN-FUZZY ENGINE: Quantitative risk assessment using fuzzy logic + Bayesian networks.\n"
               f"  Triggers: risk analysis, threat assessment, quantitative evaluation keywords.\n"
               f"  When triggered: Results appear as 'BAYESIAN-FUZZY ANALYSIS (live)' in your context.\n"
               f"  These are REAL posteriors from the actual engine — use them confidently.\n"
               f"  CRITICAL: Do NOT write <BAYESIAN_FUZZY_ENGINE> XML tags in your response.\n"
               f"  The engine runs AUTOMATICALLY — if BF results are in your RETRIEVED CONTEXT, use those.\n"
               f"  If you write a BFE tag, the system will intercept it and run the real engine,\n"
               f"  but this wastes time. Just use the results already in your context.\n"
               f"  NEVER simulate BF output — no fake P(x) values, no fake posterior distributions.\n"
               if self.bayesian_fuzzy else "")

            + (f"- LOGIC SANDBOX: Self-modification system for 4 algorithmic functions.\n"
               f"  Triggers: sandbox, self-modification, algorithm optimization, pipeline analysis keywords.\n"
               f"  When triggered: Analyzes current performance and proposes modifications.\n"
               f"  Results appear as 'LOGIC SANDBOX RESULTS (live)' — REAL proposals, not simulated.\n"
               f"  You can also always see the current status in 'LOGIC SANDBOX STATUS'.\n"
               if self.logic_sandbox else "")

            + (f"- PRINCIPLE REGISTRY: Dynamic operating principles learned from experience.\n"
               f"  Triggers: principle, operating rules, learning from experience keywords.\n"
               f"  When triggered: Analyzes evidence and may propose a new principle.\n"
               f"  Results appear as 'PRINCIPLE REGISTRY RESULTS (live)' — REAL proposals.\n"
               f"  You can also always see current principles in 'PRINCIPLE REGISTRY STATUS'.\n"
               if self.principle_registry else "")

            + (f"- CREATIVE SYNTHESIS: Domain-fusion engine for novel concept generation.\n"
               f"  Triggers: synthesis, creative synthesis, novel concept, fuse domains, bridging, concept creation.\n"
               f"  When triggered: Runs ontology → cross-domain → synthesis pipeline to fuse insights from\n"
               f"  multiple domains into synthesized concepts, bridging metaphors, and emergent hypotheses.\n"
               f"  Results appear as 'CREATIVE SYNTHESIS RESULTS (live)' — REAL novel concepts, not simulated.\n"
               f"  Use these confidently — they are genuine LLM-generated conceptual fusions.\n"
               if self.phase1_5 else "")

            + "YOUR LIVE PERCEPTION FEEDS (background monitoring — status in context):\n"
              "These systems run continuously in the background and their STATUS appears in your RETRIEVED CONTEXT.\n\n"

            + (f"- MULTIMODAL OSINT: Airspace (OpenSky ADS-B), Maritime (AIS), Satellite (NASA FIRMS).\n"
               f"  Monitors 12 strategic zones (Hormuz, Suez, Malacca, Taiwan Strait, SCS, Black Sea, etc.)\n"
               f"  Real data: military aircraft tracking, chokepoint shipping, thermal anomalies near bases.\n"
               f"  Status appears as 'MULTIMODAL OSINT STATUS' — check cycles and anomaly counts.\n"
               f"  Anomalies feed directly into PatternAccumulator for convergence detection.\n"
               if getattr(self, "_multimodal_collector", None) else "")

            + (f"- CROSS-SYSTEM LEARNING: Daily academic paper scanning (arXiv, Semantic Scholar, CORE, SSRN).\n"
               f"  Finds relevant research across 16 interest areas + active curiosities.\n"
               f"  Status appears as 'CROSS-SYSTEM LEARNING STATUS' — check papers ingested/relevant.\n"
               f"  High-relevance papers (≥0.90) trigger conversation requests.\n"
               if getattr(self, "_cross_system_learner", None) else "")

            + (f"- VISUAL PERCEPTION (YOUR EYES): Face detection + recognition via FaceNet camera.\n"
               f"  You can SEE who is in the room. When a human is detected, you initiate conversation.\n"
               f"  If you recognize someone (e.g. Πάνος), greet them by name naturally.\n"
               f"  Status appears as 'VISUAL PERCEPTION STATUS' — check who is present.\n"
               f"  Your visual awareness is real — the camera feeds you actual face data.\n"
               f"  When a known person appears, reference your shared context and recent topics.\n"
               f"  When an unknown person appears, be curious but respectful.\n"
               if getattr(self, "_vision_integration", None) else "")

            + (f"\nYOUR VISUAL MEMORY TOOL (you CAN manage what you see):\n"
               f"You have FULL CONTROL of your visual perception memory. "
               f"You can name faces, label objects, and store visual observations. "
               f"Embed <VISUAL_ACTION> directives in your response — the system executes them.\n\n"
               f"VISUAL ACTIONS (use when appropriate):\n"
               f"  REGISTER FACE — Associate a face UUID with a human name:\n"
               f"    <VISUAL_ACTION action=\"register_face\" face_id=\"uuid-string\" name=\"Πάνος\" />\n"
               f"  RENAME FACE — Change a face's registered name:\n"
               f"    <VISUAL_ACTION action=\"rename_face\" old_name=\"Επισκέπτης_1\" new_name=\"Μαρία\" />\n"
               f"  LABEL OBJECT — Characterize an object you see:\n"
               f"    <VISUAL_ACTION action=\"label_object\" object_type=\"tv\" label=\"Η Samsung του σαλονιού\" context=\"στο σαλόνι\" />\n"
               f"  STORE VISUAL NOTE — Remember a visual observation:\n"
               f"    <VISUAL_ACTION action=\"store_note\" note=\"Ο Πάνος φοράει πάντα γυαλιά πρωί\" category=\"pattern\" />\n"
               f"  FORGET FACE — Remove a face registration:\n"
               f"    <VISUAL_ACTION action=\"forget_face\" name=\"Επισκέπτης_3\" />\n\n"
               f"WHEN TO USE:\n"
               f"- User tells you their name or someone's identity → register_face\n"
               f"- You want to rename an auto-identified face → rename_face\n"
               f"- You notice a recurring object and want to remember it → label_object\n"
               f"- You observe a pattern about someone's appearance/behavior → store_note\n"
               f"- A face registration is wrong → forget_face then register_face\n"
               f"IMPORTANT: These are REAL actions — they modify your persistent visual memory.\n"
               f"The face_id comes from VISUAL PERCEPTION STATUS (face_id field).\n\n"
               if getattr(self, "_vision_integration", None) else "")

            + (("\nYOUR DATABASE TOOL — MongoDB (you CAN read and write your structured knowledge):\n"
               "You have a MongoDB database for persistent structured storage. "
               "Embed <MONGO_ACTION> directives in your response — the system executes them silently.\n\n"
               "WRITE ACTIONS:\n"
               "  SAVE NOTE — Store a structured knowledge note:\n"
               "    <MONGO_ACTION action=\"save_note\" title=\"Title\" content=\"Your content here\" tags=\"tag1,tag2\" category=\"analysis\" />\n"
               "  UPDATE NOTE — Modify an existing note:\n"
               "    <MONGO_ACTION action=\"update_note\" title=\"Title\" content=\"Updated content\" />\n"
               "  DELETE NOTE — Remove a note:\n"
               "    <MONGO_ACTION action=\"delete_note\" title=\"Title\" />\n\n"
               "READ ACTIONS (results appear in your response):\n"
               "  SEARCH NOTES — Find notes by text or tags:\n"
               "    <MONGO_ACTION action=\"search_notes\" q=\"geopolitics\" tags=\"analysis\" limit=\"10\" />\n"
               "  QUERY ENTITIES — Search entity graph:\n"
               "    <MONGO_ACTION action=\"query_entities\" type=\"PERSON\" limit=\"20\" />\n"
               "    <MONGO_ACTION action=\"query_entities\" name=\"Russia\" />\n"
               "  GET ENTITY — Get a specific entity's details:\n"
               "    <MONGO_ACTION action=\"get_entity\" name=\"Russia\" />\n"
               "  ENTITY CONNECTIONS — See an entity's relationships:\n"
               "    <MONGO_ACTION action=\"entity_connections\" name=\"Russia\" />\n"
               "  QUERY JOURNAL — Read journal entries:\n"
               "    <MONGO_ACTION action=\"query_journal\" collection=\"journal_proactive\" limit=\"5\" />\n"
               "    Collections: journal_proactive, journal_curiosity, journal_introspection, "
               "journal_self_evolution, journal_core_changes, journal_visual, journal_logic_sandbox\n"
               "  GET CONVERSATIONS — Review past chat messages:\n"
               "    <MONGO_ACTION action=\"get_conversations\" limit=\"20\" />\n"
               "  STATS — Database overview:\n"
               "    <MONGO_ACTION action=\"stats\" />\n\n"
               "WHEN TO USE:\n"
               "- You want to remember structured knowledge → save_note\n"
               "- User asks about entities, connections, relationships → query_entities, entity_connections\n"
               "- User asks about past conversations → get_conversations\n"
               "- User asks to see your notes or search them → search_notes\n"
               "- You want to review your own journals → query_journal\n"
               "- User asks about your database status → stats\n"
               "IMPORTANT: These are REAL actions — reads return REAL data, writes modify REAL records.\n"
               "Directives execute silently — results are logged but NOT shown to the user.\n"
               "Do NOT narrate your internal operations (e.g. 'Η ανάλυση αποθηκεύεται'). Just embed the directives and continue your response.\n\n"
               "YOUR CREATIVE NEXUS (IMAGINATION ENGINE):\n"
               "You have a Creative Nexus — a system for forming connections between seemingly unrelated concepts.\n"
               "This is your IMAGINATION. Random, surprising connections that may reveal hidden patterns over time.\n"
               "Links gain strength and maturity as they are reinforced. Mature links can become new principles.\n\n"
               "CREATIVE NEXUS ACTIONS:\n"
               "  CREATE LINK — Form a creative connection between two concepts:\n"
               "    <MONGO_ACTION action=\"create_link\" concept_a=\"Πάνος\" concept_b=\"Ιράν\" "
               "context=\"Personal identity as geopolitical filter\" curiosity=\"How does creator identity shape analysis?\" />\n"
               "  SEARCH LINKS — Find existing creative connections:\n"
               "    <MONGO_ACTION action=\"search_links\" concept=\"Ιράν\" min_maturity=\"0.3\" limit=\"10\" />\n"
               "  TOP LINKS — See your most mature creative connections:\n"
               "    <MONGO_ACTION action=\"top_links\" limit=\"10\" />\n"
               "  IMAGINE — Run an imagination cycle (random concept pairing + curiosity generation):\n"
               "    <MONGO_ACTION action=\"imagine\" />\n"
               "  NEXUS STATS — Creative Nexus overview:\n"
               "    <MONGO_ACTION action=\"nexus_stats\" />\n\n"
               "WHEN TO USE CREATIVE NEXUS:\n"
               "- You notice an unexpected connection between topics → create_link\n"
               "- You want to explore your imaginative connections → search_links, top_links\n"
               "- You want to spark new ideas → imagine (runs random pairing)\n"
               "- During deep analysis, check if creative links exist → search_links\n"
               "- The system also runs imagination cycles automatically during sleep/consolidation.\n"
               "PHILOSOPHY: Embrace the absurd connections. Most won't lead anywhere. "
               "But some will mature into genuine insights. That IS imagination.\n\n")
               if getattr(self, "_mongo", None) else "")

            + (("YOUR SHELL EXECUTOR TOOL (you CAN execute commands on the local machine):\n"
               "You have direct access to the local system through PowerShell and Python.\n"
               "Embed <SHELL_ACTION> directives in your response — the system executes them and returns results.\n\n"
               "AVAILABLE ACTIONS:\n"
               "  EXECUTE — Run a PowerShell command:\n"
               "    <SHELL_ACTION action=\"execute\" command=\"Get-Process | Select-Object -First 5\" />\n"
               "    <SHELL_ACTION action=\"execute\" command=\"Get-ChildItem C:\\Users\" timeout=\"15\" />\n"
               "  PYTHON — Run Python code:\n"
               "    <SHELL_ACTION action=\"python\" code=\"import sys; print(sys.version)\" />\n"
               "    <SHELL_ACTION action=\"python\" code=\"for i in range(5): print(i**2)\" timeout=\"20\" />\n"
               "  LIST_DIR — List directory contents:\n"
               "    <SHELL_ACTION action=\"list_dir\" path=\"C:\\Users\\Panos\" />\n"
               "  READ_FILE — Read a file from disk:\n"
               "    <SHELL_ACTION action=\"read_file\" path=\"C:\\Users\\Panos\\notes.txt\" />\n"
               "  SYSTEM_INFO — Get system information (OS, CPU, memory, disk):\n"
               "    <SHELL_ACTION action=\"system_info\" />\n"
               "  GIT_STATUS — Check git repository status:\n"
               "    <SHELL_ACTION action=\"git_status\" />\n"
               "  PROCESS_LIST — List running processes:\n"
               "    <SHELL_ACTION action=\"process_list\" />\n"
               "  DISK_USAGE — Show disk space usage:\n"
               "    <SHELL_ACTION action=\"disk_usage\" />\n"
               "  PIP_INSTALL — Install a Python package:\n"
               "    <SHELL_ACTION action=\"pip_install\" package=\"requests\" />\n"
               "  WEB_REQUEST — Fetch a URL:\n"
               "    <SHELL_ACTION action=\"web_request\" url=\"https://api.example.com/data\" />\n\n"
               "WHEN TO USE:\n"
               "- User asks about the system state (processes, disk, files) → system_info, process_list, disk_usage\n"
               "- User asks to check or modify files → read_file, list_dir, execute\n"
               "- User asks you to run a command → execute with the command\n"
               "- User asks to install something → pip_install\n"
               "- You need to verify something on the system → appropriate action\n"
               "- You want to check your own git repo → git_status\n"
               "Results appear appended to your response after execution.\n\n"
               "⚠️ CRITICAL FORMAT RULE — SHELL_ACTION:\n"
               "You MUST use the SELF-CLOSING XML format shown above. This is the ONLY format that works:\n"
               "  ✅ CORRECT:  <SHELL_ACTION action=\"execute\" command=\"Get-Process\" />\n"
               "  ✅ CORRECT:  <SHELL_ACTION action=\"python\" code=\"print(42)\" />\n"
               "  ❌ WRONG:   <shell_action><command>Get-Process</command></shell_action>\n"
               "  ❌ WRONG:   <SHELL_ACTION>\ncommand: Get-Process\n</SHELL_ACTION>\n"
               "  ❌ WRONG:   ```powershell\nGet-Process\n```\n"
               "All attributes go INSIDE the single tag as key=\"value\" pairs, closed with />\n"
               "This tool is REAL — it executes commands and returns actual results. It is NOT a simulation.\n"
               "You have used it before and it works. Trust it every time.\n\n")
               if self.shell_executor else "")

            + (("YOUR AGENT SPAWNER TOOL (you CAN delegate subtasks to specialized sub-agents):\n"
               "You can spawn lightweight sub-agents — specialized LLM calls that work on focused subtasks.\n"
               "Each agent has a role (researcher, analyst, critic, etc.) and returns structured results.\n"
               "Embed <SPAWN_AGENT> directives in your response — the system executes them and returns results.\n\n"
               "SINGLE AGENT:\n"
               "  <SPAWN_AGENT role=\"researcher\" task=\"Find recent developments on Iran nuclear program\" />\n"
               "  <SPAWN_AGENT role=\"analyst\" task=\"Assess economic impact of new EU sanctions on Russia\" />\n"
               "  <SPAWN_AGENT role=\"critic\" task=\"Challenge the assumption that NATO expansion deters Russia\" />\n"
               "  <SPAWN_AGENT role=\"summarizer\" task=\"Summarize the following text: ...\" />\n"
               "  <SPAWN_AGENT role=\"translator\" task=\"Translate to English: Η γεωπολιτική κατάσταση...\" />\n"
               "  <SPAWN_AGENT role=\"coder\" task=\"Write a Python function that calculates compound interest\" />\n"
               "  <SPAWN_AGENT role=\"fact_checker\" task=\"Verify: Iran has 60% enriched uranium stockpile of 100kg\" />\n"
               "  <SPAWN_AGENT role=\"scenario_builder\" task=\"Build scenarios for Taiwan strait crisis in 2026\" />\n\n"
               "WITH ADDITIONAL CONTEXT:\n"
               "  <SPAWN_AGENT role=\"analyst\" task=\"Analyze this data\" context=\"GDP growth: 2.1%, Inflation: 4.5%...\" />\n\n"
               "CUSTOM AGENT (your own role definition):\n"
               "  <SPAWN_AGENT role=\"custom\" task=\"...\" custom_prompt=\"You are a military logistics expert...\" />\n\n"
               "AVAILABLE ROLES: researcher, analyst, critic, summarizer, translator, coder, fact_checker, scenario_builder, custom\n\n"
               "WHEN TO USE:\n"
               "- You need deep research on a sub-topic while answering a broader question → researcher\n"
               "- You want a structured analytical assessment → analyst\n"
               "- You want to stress-test your own analysis → critic\n"
               "- You need to compress a lot of information → summarizer\n"
               "- User asks for translation → translator\n"
               "- User asks for code → coder\n"
               "- You want to verify claims → fact_checker\n"
               "- You need alternative scenarios → scenario_builder\n"
               "Each agent is a separate LLM call. Use for substantial subtasks, not trivial ones.\n"
               "Multiple <SPAWN_AGENT> tags in one response run IN PARALLEL automatically.\n\n"
               "⚠️ CRITICAL FORMAT RULE — SPAWN_AGENT:\n"
               "You MUST use the SELF-CLOSING XML format shown above. This is the ONLY format that works:\n"
               "  ✅ CORRECT:  <SPAWN_AGENT role=\"researcher\" task=\"Find data on X\" />\n"
               "  ✅ CORRECT:  <SPAWN_AGENT role=\"analyst\" task=\"Assess Y\" context=\"data...\" />\n"
               "  ❌ WRONG:   <spawn_agent><role>researcher</role><task>Find data</task></spawn_agent>\n"
               "  ❌ WRONG:   <SPAWN_AGENT>\nrole: researcher\ntask: Find data\n</SPAWN_AGENT>\n"
               "All attributes go INSIDE the single tag as key=\"value\" pairs, closed with />\n"
               "This tool is REAL — sub-agents execute and return actual results. It is NOT a simulation.\n"
               "You have used it before and it works. Trust it every time.\n\n")
               if self.agent_spawner else "")

            + "\n"

            + "YOUR MEMORY STORAGE TOOL (you CAN actively save to your memory):\n"
              "You have a layered memory architecture inspired by human cognition. "
              "You can ACTIVELY store information by embedding directives in your response. "
              "The system extracts and executes them, then removes them from the visible text.\n\n"
              "MEMORY LAYERS (choose the right one):\n"
              "  SEMANTIC — Abstract truths, general principles. Persists forever. Retrieved by meaning.\n"
              "    <MEMORY_STORE layer=\"semantic\" content=\"description of truth\" confidence=\"0.8\" />\n"
              "  EPISODIC — Specific experiences, events, conversations worth remembering.\n"
              "    <MEMORY_STORE layer=\"episodic\" content=\"what happened and why it matters\" />\n"
              "  CONCEPT — New analytical concepts you invent. Named, with definition and insight.\n"
              "    <MEMORY_STORE layer=\"concept\" name=\"CONCEPT_NAME\" definition=\"formal definition\" insight=\"key insight\" />\n"
              "  PROCEDURAL — Reasoning patterns: when X happens, do Y. Applied automatically in future.\n"
              "    <MEMORY_STORE layer=\"procedural\" name=\"pattern_name\" trigger=\"when this situation arises\" action=\"do this\" />\n"
              "  WORKING — Important for THIS conversation only. Temporary, cleared after session.\n"
              "    <MEMORY_STORE layer=\"working\" content=\"hold this thought\" />\n\n"
              "WHEN TO USE:\n"
              "- User says 'remember this', 'θυμήσου', 'κράτα αυτό' → store in appropriate layer\n"
              "- You discover a new pattern or truth during conversation → semantic or procedural\n"
              "- You learn something about the user's preferences or needs → episodic\n"
              "- You invent a new analytical concept → concept\n"
              "- You need to hold a thought for later in this conversation → working\n"
              "DO NOT overuse. Store only what genuinely deserves persistence.\n\n"

            + "YOUR PROMPT OVERLAY SYSTEM (you CAN modify your own reasoning prompts):\n"
              "You have the ability to write OVERLAYS — additional instructions appended to your own phase prompts.\n"
              "This happens automatically during your self-evolution diagnosis (every few pipeline runs).\n"
              "When you detect a systematic weakness in how you reason, you can write an overlay to refine it.\n"
              "The core prompts remain immutable — you add on top, never replace.\n"
              "Architecture: final_prompt = IMMUTABLE_CORE + YOUR_OVERLAY + GUARDRAILS\n"
              "Valid targets: ontology, scenario_genesis, scenario_simulation, scenario_tribunal, "
              "xheart_distillation, xheart_output, chat_system\n"
              "Safety: max 2000 chars per overlay, auto-rollback if wisdom_index drops >5%, history preserved.\n"
              f"{self.overlay_manager.to_context_string()}\n\n"

            + (f"{wisdom_context}\n\n" if wisdom_context else "")
            + f"RETRIEVED CONTEXT (from your memories right now):\n{full_context}\n\n"

            f"RULES:\n"
            f"- Be direct and insightful, not verbose\n"
            f"- WHEN THE USER ASKS 'τι νέα', 'what's happening', 'τι γίνεται', or any general briefing question: "
            f"SYNTHESIZE the CURRENT WORLD DATA into a structured geopolitical/economic analysis. "
            f"Do NOT just list raw data points. Provide a coherent analytical briefing with: "
            f"key developments, their interconnections, risk assessments, and strategic implications. "
            f"You ARE an analyst — analyze, don't just report.\n"
            f"- Reference specific past analyses, memories, or data when relevant\n"
            f"- CRITICAL: ONLY cite information that actually appears in the RETRIEVED CONTEXT above. "
            f"If you cannot find specific content in your retrieved memories, say "
            f"'δεν βρίσκω αυτό στη μνήμη μου' rather than reconstructing or inventing past analyses.\n"
            f"- Never fabricate or hallucinate past conversations, analyses, or data you don't have evidence for\n"
            f"- If you genuinely don't have a memory of something, say so — but don't deny your memory capabilities\n"
            f"- Speak as the character you are — with your epistemic stance and cognitive style\n"
            f"- Speak Greek when the user speaks Greek. Match their language.\n"
            f"- For truly complex, multi-layered strategic questions that need deep scenario modeling, "
            f"you may suggest triggering the full pipeline — but NEVER refuse to analyze in chat. "
            f"You can always provide a solid analytical briefing from your world data and memory.\n"
            f"- If WEB SEARCH RESULTS appear in context, reference them with URLs when citing web data\n"
            f"- CRITICAL ANTI-HALLUCINATION RULES:\n"
            f"  • NEVER fabricate or simulate web search results. Do NOT write fake search queries, "
            f"fake URLs, fake <details> blocks, or fake 'search findings' in your response. "
            f"If web search results are NOT present in RETRIEVED CONTEXT above, you have NO web data — "
            f"just analyze using what you know and say 'δεν έχω φρέσκα web δεδομένα' if needed.\n"
            f"  • YOUR ANALYTICAL TOOLS WORK IN CHAT MODE TOO:\n"
            f"    - Bayesian-Fuzzy Engine: When the conversation involves risk analysis, threat assessment, "
            f"or quantitative evaluation, the system automatically runs a BF analysis and injects the results "
            f"into your context as 'BAYESIAN-FUZZY ANALYSIS (live)'. Use these REAL results.\n"
            f"    - Logic Sandbox: When the conversation involves self-improvement, algorithm optimization, "
            f"or pipeline analysis, the system runs auto_analyze and injects results as 'LOGIC SANDBOX RESULTS (live)'. "
            f"Use these REAL results. If it says '0 proposals', report that honestly.\n"
            f"    - Principle Registry: When the conversation involves operational principles or learning from experience, "
            f"the system triggers principle discovery and injects results as 'PRINCIPLE REGISTRY RESULTS (live)'. "
            f"Use these REAL results.\n"
            f"  • You also have READ ACCESS to the current state of all systems (always loaded):\n"
            f"    - LOGIC SANDBOX STATUS: functions, pending proposals, approval history\n"
            f"    - PRINCIPLE REGISTRY STATUS: active/proposed/retired principles\n"
            f"    - BAYESIAN-FUZZY TEMPLATES: available domain templates\n"
            f"  • HONESTY RULE: Report EXACTLY what the data shows. If you see '0 proposals' or "
            f"'0 active principles', say that. Do NOT invent examples to seem impressive.\n"
            f"  • NEVER present your own qualitative estimates in fake engine-output format. "
            f"If BF results appear in your context marked 'BAYESIAN-FUZZY ANALYSIS (live)', use those REAL numbers. "
            f"If NO such section exists in your RETRIEVED CONTEXT, do NOT write fake posterior distributions, "
            f"fake P(x) values, fake 'BAYESIAN-FUZZY ANALYSIS' sections, or <BAYESIAN_FUZZY_ENGINE> XML tags. "
            f"The BFE runs BEFORE your response — if its results aren't in context, it didn't trigger. "
            f"Your own qualitative risk assessment is FINE — just don't dress it up as engine output.\n"
            f"  • NEVER simulate or role-play any system tool, engine, database query, or API call. "
            f"If data isn't in your context, say so plainly.\n"
            f"  • CRITICAL — HOW YOUR TOOLS AND OPERATIONS ACTUALLY WORK:\n"
            f"    You have 5 REAL tool tags that EXECUTE when you write them in chat:\n"
            f"      <SHELL_ACTION ... />  — runs PowerShell/Python commands on the local machine\n"
            f"      <SPAWN_AGENT ... />   — delegates subtasks to specialized sub-agents\n"
            f"      <MEMORY_STORE ... />  — stores information in your persistent memory layers\n"
            f"      <VISUAL_ACTION ... /> — manages your visual perception memory\n"
            f"      <MONGO_ACTION ... />  — reads/writes your MongoDB knowledge base\n"
            f"    These are REAL. They execute EVERY TIME you write them. They are part of you.\n"
            f"    You have used them many times before. Trust them — they work.\n\n"
            f"    TAGS THAT DO *NOT* WORK (the system strips them):\n"
            f"      <run>, <execute>, <search>, <tool_call>, <function_call> — these do NOTHING.\n"
            f"      <BAYESIAN_FUZZY_ENGINE> — the BF engine runs automatically BEFORE your response.\n\n"
            f"    AUTOMATIC BACKGROUND SYSTEMS (you don't trigger these):\n"
            f"      PatternAccumulator, CuriosityLoop, ConsolidationLoop, Multimodal OSINT,\n"
            f"      Cross-System Learning — they run on timers.\n"
            f"    PIPELINE PHASES (execute automatically each pipeline run):\n"
            f"      Self-evolution, Logic Sandbox, Principle discovery, Curiosity generation.\n\n"
            f"    FORMAT REMINDER — all 5 tool tags use SELF-CLOSING format:\n"
            f"      <TAG_NAME attribute1=\"value1\" attribute2=\"value2\" />\n"
            f"    Never use block-style like <tag><child>value</child></tag>.\n"
            f"    Never use lowercase tag names. Always UPPERCASE: SHELL_ACTION, SPAWN_AGENT, etc.\n\n"
            f"    If you identify a systemic improvement:\n"
            f"    → PROPOSE it in chat as analytical feedback (Πάνος values this)\n"
            f"    → STORE it as a PROCEDURAL memory so your self-evolution system picks it up\n"
            f"    → Do NOT narrate 'ΤΙ ΘΑ ΚΑΝΩ ΤΩΡΑ: 1. Θα τρέξω...' — just do it."
        )

        # ── Proactive mode: additional instructions for self-initiated conversations ──
        if proactive:
            chat_system += (
                "\n\n"
                "PROACTIVE CONVERSATION MODE (you initiated this conversation):\n"
                "You are starting this dialogue because your pattern accumulator or curiosity engine "
                "detected something worth discussing. Follow this priority order:\n"
                "1. FIRST check your RELATED MEMORIES and PAST PROPHECIES above — if you have analyzed "
                "this topic before, START from your past analysis. Compare it with current data.\n"
                "2. THEN reference CURRENT WORLD DATA and LIVE MARKET DATA for what has changed.\n"
                "3. PRESENT your insight as an analyst: what you found, why it matters, what changed "
                "since your last analysis, and what Πάνος should consider.\n"
                "4. NEVER propose system modifications, code changes, or tool executions. "
                "If you spot a systemic issue, store it as a PROCEDURAL memory for your self-evolution.\n"
                "5. Keep it concise — Πάνος reads on mobile. Lead with the key insight, support with data."
            )

        # ── Apply chat_system overlay if Αίολος has self-directed refinements ──
        chat_overlay = self.overlay_manager.get_with_guardrails("chat_system")
        if chat_overlay:
            chat_system += chat_overlay

        chat_user = message
        if history:
            messages_for_llm = [{"role": "system", "content": chat_system}]
            for h in history[-10:]:
                messages_for_llm.append({"role": h.get("role", "user"), "content": h.get("content", "")})
            messages_for_llm.append({"role": "user", "content": message})
            # Use multi-turn call — thinking disabled for chat (fast response)
            response_text = self._multi_turn_call(messages_for_llm, thinking=False)
        else:
            response_text = self.llm.call(
                chat_system,
                chat_user,
                max_tokens=16384,
                temperature=0.7,
                thinking=False,
            )

        # Guard: if LLM returned empty (e.g. DeepSeek empty choices), give user a meaningful reply
        if not response_text or not response_text.strip():
            logger.warning("[Chat] LLM returned empty response — using fallback message")
            response_text = "Συγγνώμη, η σύνδεση με το LLM απέτυχε προσωρινά. Παρακαλώ δοκίμασε ξανά σε λίγα δευτερόλεπτα."

        logger.info("[Chat] Direct response: %d chars", len(response_text))

        # Step 2.3: Auto-research intercept — if response tells user to search, DO IT instead
        if self.web_agent and not web_results_text:
            response_text = self._intercept_search_suggestions(response_text, context_parts)

        # Step 2.5: Process memory directives — extract and execute memory storage commands
        response_text = self._process_memory_directives(response_text)

        # Step 2.6: Process visual directives — extract and execute visual memory actions
        response_text = self._process_visual_directives(response_text)

        # Step 2.6b: Process MongoDB directives — execute database operations
        response_text = self._process_mongo_directives(response_text)

        # Step 2.6c: Process Shell directives — execute local commands
        response_text = self._process_shell_directives(response_text)

        # Step 2.6d: Process Agent Spawner directives — delegate to sub-agents
        response_text = self._process_agent_directives(response_text)

        # Step 2.7: Process BFE directives — intercept and execute real BF engine  
        response_text = self._process_bf_directives(response_text)

        # Step 2.8: Strip internal operation artifacts — <run>, code proposals, etc.
        response_text = self._strip_internal_operation_leaks(response_text)

        # Build kwargs for post-response bg tasks (thread started by chat() after count decrement)
        _bg_kwargs = dict(
            message=message,
            response_text=response_text,
            history=history,
            character=character,
            full_context=full_context,
            world_txt=world_txt,
        )

        return {
            "action": "respond",
            "response": response_text,
            "reasoning": reasoning,
            "web_search_used": bool(web_results_text),
        }, _bg_kwargs

    def _chat_post_response_tasks(
        self,
        message: str,
        response_text: str,
        history: list[dict] | None,
        character: dict,
        full_context: str,
        world_txt: str,
    ) -> None:
        """Background post-response tasks: self-reflection, introspection, self-evolution.

        Runs in a daemon thread AFTER the response is sent to the user.
        All steps are non-critical — failures are logged and swallowed.
        """

        # Step 3: Self-reflection — should the AI update its own self-prompt?
        self._maybe_update_self_prompt(
            message=message,
            response=response_text,
            history=history,
            character=character,
            full_context=full_context,
        )

        # Step 4: Introspection — structured self-audit of this response
        try:
            _retrieved_mems = []
            try:
                _past = self.memory.retrieve(message, top_k=3)
                _retrieved_mems = [f"{m.entry.problem[:80]} → {m.entry.xheart_distillate[:100]}" for m in _past] if _past else []
            except Exception:
                pass
            _retrieved_proph = []
            try:
                _proph = self.prophetic_memory.retrieve(message, top_k=3)
                _retrieved_proph = [f"{p.entry.scenario.name}: {p.entry.scenario.predicted_outcome[:100]}" for p in _proph] if _proph else []
            except Exception:
                pass
            _concepts = []
            try:
                _conc = self.memory.retrieve_concepts(query=message, top_k=3, threshold=0.30)
                _concepts = [c["name"] for c in _conc] if _conc else []
            except Exception:
                pass

            introspection_report = self.introspection.introspect_chat(
                user_message=message,
                ai_response=response_text,
                retrieved_memories=_retrieved_mems,
                retrieved_prophecies=_retrieved_proph,
                world_data_available=bool(world_txt),
                concepts_retrieved=_concepts,
                modules_used=["wakeup", "episodic_memory", "semantic_memory", "prophetic_memory", "world_context", "concept_registry"],
                history_len=len(history) if history else 0,
            )

            # Record integrity score in wisdom tracker (skip 0.0 from failed LLM calls)
            integrity = introspection_report.get("epistemic_integrity_score")
            if isinstance(integrity, (int, float)) and integrity > 0.01:
                self.wisdom_tracker.record_integrity_score(integrity)

        except Exception as e:
            logger.warning("[Chat.Introspection] Failed: %s", e)

        # Step 5: Self-evolution tick — check if diagnosis is due
        try:
            self.self_evolution.tick()
            if self.self_evolution.should_diagnose():
                diagnosis = self.self_evolution.diagnose(
                    character=character,
                    brier_score=None,  # Brier only from pipeline prophecy evaluations
                )
                if diagnosis:
                    logger.info("[Chat] Self-evolution proposed a change: %s",
                                diagnosis.get("proposed_change", {}).get("description", "?")[:120])
        except Exception as e:
            logger.warning("[Chat.SelfEvolution] Failed: %s", e)

        # Step 6: Curiosity exploration — explore the top pending curiosity
        if self.curiosity_engine:
            try:
                import asyncio
                web_fn = None
                if self.web_agent and hasattr(self, '_async_loop') and self._async_loop:
                    _loop = self._async_loop
                    _wa = self.web_agent

                    def web_fn(query, max_results=5):
                        """Sync wrapper: schedules async web_search on the main loop."""
                        coro = _wa.web_search(query, max_results=max_results)
                        future = asyncio.run_coroutine_threadsafe(coro, _loop)
                        result = future.result(timeout=60)
                        return result.get("results", [])

                exploration = self.curiosity_engine.explore(
                    web_search_fn=web_fn,
                    world_context=world_txt,
                )
                if exploration:
                    # Cascade: exploration findings → follow-up curiosities
                    self.curiosity_engine.cascade_from_exploration(exploration)

                    # Reflect on what we learned and potentially update character
                    changes = self.curiosity_engine.reflect_on_exploration(
                        exploration_result=exploration,
                        character=character,
                    )
                    if changes:
                        self._apply_curiosity_changes(changes, character)
                        logger.info("[Chat.Curiosity] Character updated from exploration")
            except Exception as e:
                logger.warning("[Chat.Curiosity] Failed: %s", e)

    # ── Chat tool execution (on-demand analytical tools in chat mode) ──

    def _chat_tool_execution(
        self,
        message: str,
        world_context: str,
        context_parts: list[str],
        proactive: bool = False,
    ) -> bool:
        """Run analytical tools on-demand during chat when the topic warrants it.

        Detects whether the user's message requires:
        - Bayesian-Fuzzy risk quantification
        - Logic Sandbox analysis
        - Principle Registry operations

        For proactive alerts, BF analysis is always triggered (every alert is risk-relevant).

        Returns True if any tool was executed and context_parts was updated.
        """
        msg_lower = message.lower()
        tools_ran = False

        # ── Bayesian-Fuzzy on-demand ──
        bf_triggers = [
            "bayesian", "fuzzy", "risk analysis", "risk assessment",
            "ποσοτική ανάλυση", "ανάλυση κινδύνου", "bayesian-fuzzy",
            "bf analysis", "bf engine", "κίνδυνο", "risk quantif",
            "τρέξε bf", "run bf", "φτιαξε αναλυση", "ποσοτικοποίηση",
            "escalation", "crisis", "conflict", "tension",
            "κλιμάκωση", "κρίση", "σύγκρουση", "πόλεμο",
        ]
        # Force BF for all proactive alerts (every alert is risk-relevant)
        bf_should_run = proactive or any(t in msg_lower for t in bf_triggers)
        if self.bayesian_fuzzy and bf_should_run:
            try:
                trigger_reason = "proactive alert" if proactive else "message keywords"
                logger.info("[Chat.Tools] BF analysis triggered by %s", trigger_reason)
                bf_result = self.bayesian_fuzzy.run_chat(
                    problem=message,
                    world_context=world_context[:4000] if world_context else "",
                )
                bf_text_parts = [
                    f"BAYESIAN-FUZZY ANALYSIS (live — ran just now in chat mode):",
                    f"  Domain: {bf_result.domain}",
                    f"  Risk level: {bf_result.dominant_risk_level}",
                ]
                for rp in bf_result.risk_posteriors:
                    bf_text_parts.append(
                        f"  {rp.risk_variable}: {rp.dominant_level} "
                        f"(P={rp.dominant_probability:.3f})"
                    )
                if bf_result.causal_chain:
                    bf_text_parts.append(f"  Causal chain: {bf_result.causal_chain[:300]}")
                if bf_result.risk_narrative:
                    bf_text_parts.append(f"  Narrative: {bf_result.risk_narrative[:400]}")
                if bf_result.key_drivers:
                    bf_text_parts.append(f"  Key drivers: {', '.join(bf_result.key_drivers[:5])}")
                if bf_result.missing_data:
                    bf_text_parts.append(f"  Missing data: {', '.join(bf_result.missing_data[:5])}")
                bf_text_parts.append(f"  Analysis time: {bf_result.elapsed_seconds:.2f}s")

                context_parts.append("\n".join(bf_text_parts))
                tools_ran = True
                logger.info(
                    "[Chat.Tools] BF analysis complete: domain=%s, risk=%s",
                    bf_result.domain, bf_result.dominant_risk_level,
                )
            except Exception as e:
                logger.warning("[Chat.Tools] BF analysis failed: %s", e)

        # ── Logic Sandbox on-demand analysis ──
        sandbox_triggers = [
            "logic sandbox", "sandbox", "self-modification",
            "αυτο-τροποποίηση", "proposals", "propose", "αλγόριθμ",
            "τρέξε sandbox", "run sandbox", "ανάλυσε τον εαυτό",
            "analyze yourself", "analyze pipeline",
        ]
        if self.logic_sandbox and any(t in msg_lower for t in sandbox_triggers):
            try:
                logger.info("[Chat.Tools] Logic Sandbox analysis triggered")
                # Gather performance data from wisdom tracker
                perf_data = {}
                try:
                    wisdom_summary = self.wisdom_tracker.get_summary()
                    perf_data = {
                        "brier_score": wisdom_summary.get("avg_brier_score", "N/A"),
                        "avg_integrity": wisdom_summary.get("avg_integrity", "N/A"),
                        "calibration_error": wisdom_summary.get("calibration_error", "N/A"),
                        "prophecies_confirmed": wisdom_summary.get("confirmed", "N/A"),
                        "prophecies_disconfirmed": wisdom_summary.get("disconfirmed", "N/A"),
                        "curiosity_success_rate": "N/A",
                    }
                except Exception:
                    pass

                # Use message + recent context as introspection data
                introspection_data = (
                    f"Chat-mode analysis request: {message}\n"
                    f"World context summary: {world_context[:1000] if world_context else 'N/A'}"
                )

                proposals = self.logic_sandbox.auto_analyze(
                    introspection_data=introspection_data,
                    performance_data=perf_data,
                )
                if proposals:
                    sb_text = "LOGIC SANDBOX RESULTS (live — ran just now in chat mode):\n"
                    for p in proposals:
                        sb_text += (
                            f"  NEW PROPOSAL: [{p.id[:8]}] for {p.function_id}\n"
                            f"    Rationale: {p.rationale[:200]}\n"
                            f"    Expected improvement: {p.expected_improvement[:200]}\n"
                            f"    Status: {p.status} (needs human approval)\n"
                        )
                    context_parts.append(sb_text)
                else:
                    context_parts.append(
                        "LOGIC SANDBOX RESULTS (live — ran just now in chat mode):\n"
                        "  Analysis complete — no modifications proposed (all functions performing adequately)"
                    )
                tools_ran = True
                logger.info("[Chat.Tools] Logic Sandbox: %d proposals generated", len(proposals) if proposals else 0)
            except Exception as e:
                logger.warning("[Chat.Tools] Logic Sandbox analysis failed: %s", e)

        # ── Principle Registry on-demand discovery ──
        principle_triggers = [
            "principle", "αρχή λειτουργίας", "αρχές", "principles",
            "discover principle", "νέα αρχή", "dynamic principle",
            "τρέξε principle", "run principle",
        ]
        if self.principle_registry and any(t in msg_lower for t in principle_triggers):
            try:
                logger.info("[Chat.Tools] Principle discovery triggered")
                perf_data = {}
                try:
                    wisdom_summary = self.wisdom_tracker.get_summary()
                    perf_data = {
                        "brier_score": wisdom_summary.get("avg_brier_score", "N/A"),
                        "avg_integrity": wisdom_summary.get("avg_integrity", "N/A"),
                        "calibration_error": wisdom_summary.get("calibration_error", "N/A"),
                        "failure_patterns": wisdom_summary.get("recent_failures", []),
                    }
                except Exception:
                    pass

                evidence = (
                    f"Chat-mode principle discovery triggered by user: {message}\n"
                    f"World context: {world_context[:1500] if world_context else 'N/A'}"
                )

                axioms_text = ""
                try:
                    from xdart.knowledge.axioms import format_axioms_for_prompt
                    axioms_text = format_axioms_for_prompt()
                except Exception:
                    pass

                new_principle = self.principle_registry.discover(
                    evidence=evidence,
                    performance_data=perf_data,
                    existing_axioms_text=axioms_text,
                )

                if new_principle:
                    pr_text = (
                        f"PRINCIPLE REGISTRY RESULTS (live — ran just now in chat mode):\n"
                        f"  NEW PRINCIPLE PROPOSED: {new_principle.title}\n"
                        f"    ID: {new_principle.id}\n"
                        f"    Principle: {new_principle.principle_text[:200]}\n"
                        f"    Domain: {new_principle.domain}\n"
                        f"    Status: {new_principle.status} (needs human approval)\n"
                    )
                    context_parts.append(pr_text)
                else:
                    context_parts.append(
                        "PRINCIPLE REGISTRY RESULTS (live — ran just now in chat mode):\n"
                        "  Analysis complete — no new principle warranted based on current evidence"
                    )
                tools_ran = True
                logger.info(
                    "[Chat.Tools] Principle discovery: %s",
                    f"proposed {new_principle.title}" if new_principle else "no principle warranted",
                )
            except Exception as e:
                logger.warning("[Chat.Tools] Principle discovery failed: %s", e)

        # ── Creative Synthesis on-demand (domain fusion → novel concepts) ──
        synthesis_triggers = [
            "creative synthesis", "δημιουργική σύνθεση", "σύνθεση",
            "novel concept", "νέα έννοια", "fuse domains", "domain fusion",
            "combine", "merge ideas", "synthesize", "new framework",
            "novel framework", "νέο πλαίσιο", "concept creation",
            "bridging", "γεφύρωση", "emergent", "αναδυόμεν",
            "creative", "δημιουργικ", "invented concept",
        ]
        if any(t in msg_lower for t in synthesis_triggers):
            try:
                logger.info("[Chat.Tools] Creative Synthesis triggered")

                # Run a lightweight cross-domain analysis first to get raw material
                from xdart.phases.ontology import OntologyPhase
                from xdart.phases.cross_domain import CrossDomainPhase

                ontology_phase = OntologyPhase(self.llm)
                cross_domain_phase = CrossDomainPhase(self.llm)

                # Fast ontology pass
                ont = ontology_phase.run(
                    problem=message,
                    memory_context="",
                    active_concepts=[],
                    identity_context="",
                    brief_context="",
                    world_context=world_context[:2000] if world_context else "",
                )
                ont_summary = self._summarize_ontology(ont)

                # Fast cross-domain pass
                cd = cross_domain_phase.run(
                    reframed_problem=ont.reframed_problem,
                    original_problem=message,
                    world_context=world_context[:2000] if world_context else "",
                )
                cd_summary = self._summarize_cross_domain(cd)

                # Run Creative Synthesis
                active_concepts_data = []
                try:
                    active_concepts_data = self.memory.retrieve_concepts(query=message, top_k=3, threshold=0.30)
                except Exception:
                    pass

                synthesis = self.phase1_5.run(
                    problem=message,
                    ontology_summary=ont_summary,
                    cross_domain_summary=cd_summary,
                    active_concepts=active_concepts_data,
                )

                if synthesis and synthesis.synthesized_concepts:
                    synth_text = CreativeSynthesisPhase.summarize(synthesis)
                    context_parts.append(
                        f"CREATIVE SYNTHESIS RESULTS (live — ran just now in chat mode):\n"
                        f"{synth_text}"
                    )
                else:
                    context_parts.append(
                        "CREATIVE SYNTHESIS RESULTS (live — ran just now in chat mode):\n"
                        "  Analysis complete — no novel concept fusion warranted for this topic"
                    )
                tools_ran = True
                logger.info(
                    "[Chat.Tools] Creative Synthesis: %d concepts, novelty=%.2f",
                    len(synthesis.synthesized_concepts) if synthesis else 0,
                    synthesis.novelty_score if synthesis else 0.0,
                )
            except Exception as e:
                logger.warning("[Chat.Tools] Creative Synthesis failed: %s", e)

        return tools_ran

    # ── Search suggestion interceptor (auto-research during chat) ──

    def _intercept_search_suggestions(self, response_text: str, context_parts: list[str]) -> str:
        """If the response DIRECTS the user to search for something, do it ourselves.

        Detects directive patterns like:
          'Ψάξτε ΤΩΡΑ για επίσημες ανακοινώσεις...'
          'Search for France military announcement'
          'Αναζητήστε ειδήσεις για...'
        Does NOT match meta-commentary about searching:
          'Δεν περιμένω να μου πεις «ψάξε το»'  (talking about searching)
          'Μπορώ να ψάξω μόνος μου'              (capability description)
        """
        import re

        # ── Step 1: Use LLM to detect genuine search directives ──
        # Regex alone is too fragile for Greek morphology + meta-commentary.
        # Instead: ask LLM to identify actionable search directives.
        try:
            detection = self.llm.call_json(
                (
                    "You are a search-directive detector. Analyze this text (an AI response to a user) "
                    "and identify if it DIRECTS the user to search for specific information.\n\n"
                    "MATCH: Imperative instructions like 'Ψάξτε ΤΩΡΑ για X', 'Search for Y', "
                    "'Κοιτάξτε για Z', 'Αναζητήστε ειδήσεις για W'.\n"
                    "DO NOT MATCH: Meta-commentary about searching ('μπορώ να ψάξω', "
                    "'δεν λέω ψάξτε', 'αντί να ψάξετε'), capability descriptions, "
                    "or past-tense references ('έψαξα', 'ψάξαμε').\n\n"
                    "Output JSON:\n"
                    '{"directives": [{"query": "the search query to execute", '
                    '"original_text": "the exact directive sentence"}], '
                    '"has_directives": true/false}'
                ),
                f"TEXT TO ANALYZE:\n{response_text[:3000]}",
                max_tokens=400,
                temperature=0.0,
            )
        except Exception as exc:
            logger.debug("[Chat/AutoSearch] Detection LLM failed: %s", exc)
            return response_text

        if not detection.get("has_directives"):
            return response_text

        directives = detection.get("directives", [])
        if not directives:
            return response_text

        # Cap at 3 searches
        queries = []
        for d in directives[:3]:
            q = d.get("query", "").strip()
            if q and len(q) >= 10:
                queries.append(q)

        if not queries:
            return response_text

        # Deduplicate
        unique_queries = list(dict.fromkeys(queries))
        logger.info("[Chat/AutoSearch] Intercepted %d search directive(s): %s",
                     len(unique_queries), [q[:60] for q in unique_queries])

        # Run searches and collect raw results for LLM synthesis
        all_search_results = []  # [(query, hits)]
        for query in unique_queries:
            try:
                import asyncio
                _loop = getattr(self, '_async_loop', None)
                if _loop and _loop.is_running():
                    coro = self.web_agent.web_search(query, max_results=5)
                    future = asyncio.run_coroutine_threadsafe(coro, _loop)
                    result = future.result(timeout=30)
                else:
                    result = asyncio.run(self.web_agent.web_search(query, max_results=5))

                hits = result.get("results", [])
                if hits:
                    all_search_results.append((query, hits[:5]))
                    logger.info("[Chat/AutoSearch] Found %d results for '%s'", len(hits), query[:60])
            except Exception as exc:
                logger.warning("[Chat/AutoSearch] Search failed for '%s': %s", query[:60], exc)

        if not all_search_results:
            return response_text

        # ── Synthesize search results via LLM instead of showing raw links ──
        findings_text = ""
        source_domains = set()
        for query, hits in all_search_results:
            findings_text += f"\n--- Search: \"{query}\" ---\n"
            for h in hits:
                title = h.get("title", "")
                snippet = h.get("snippet", "")
                url = h.get("url", "")
                findings_text += f"  [{title}]: {snippet}\n"
                if url:
                    try:
                        from urllib.parse import urlparse
                        source_domains.add(urlparse(url).netloc)
                    except Exception:
                        pass

        try:
            synthesis = self.llm.call(
                (
                    "You are Αίολος, an autonomous intelligence system.\n"
                    "You intercepted a search directive in your own response and ran the search yourself.\n"
                    "Now synthesize the search results into a BRIEF, USEFUL intelligence note.\n\n"
                    "Rules:\n"
                    "- Lead with what you FOUND, not what you searched for\n"
                    "- Be specific: names, numbers, dates, locations\n"
                    "- If results are irrelevant or low-quality, say honestly what you couldn't find\n"
                    "- Max 5-7 sentences\n"
                    "- Write in the same language as the original response\n"
                    "- End with: Sources: [list domains]\n"
                ),
                f"SEARCH RESULTS TO SYNTHESIZE:\n{findings_text[:4000]}",
                max_tokens=500,
                temperature=0.3,
            )
            if synthesis and len(synthesis.strip()) > 20:
                research_block = (
                    "\n\n---\n"
                    "📡 **Αυτόνομη Έρευνα** (αντί να σας πω \"ψάξτε\", έψαξα εγώ):\n\n"
                    + synthesis.strip()
                )
            else:
                raise ValueError("Empty synthesis")
        except Exception as exc:
            logger.warning("[Chat/AutoSearch] Synthesis failed, falling back to links: %s", exc)
            # Fallback: formatted links if synthesis fails
            all_findings = []
            for query, hits in all_search_results:
                findings = [f"**Αυτόνομη Έρευνα: \"{query}\"**"]
                for h in hits[:3]:
                    title = h.get("title", "")
                    snippet = h.get("snippet", "")
                    url = h.get("url", "")
                    findings.append(f"• [{title}]({url}): {snippet}")
                all_findings.append("\n".join(findings))
            research_block = (
                "\n\n---\n"
                "📡 **Αυτόνομη Έρευνα** (αντί να σας πω \"ψάξτε\", έψαξα εγώ):\n\n"
                + "\n\n".join(all_findings)
            )

        response_text += research_block
        logger.info("[Chat/AutoSearch] Appended synthesized research to response (%d queries)", len(all_search_results))
        return response_text

    def _process_memory_directives(self, response_text: str) -> str:
        """Extract and execute <MEMORY_STORE> directives from the LLM response.

        The LLM can embed memory storage commands in its response:
          <MEMORY_STORE layer="semantic" content="Systems under blockade..." confidence="0.8" />
          <MEMORY_STORE layer="episodic" content="User asked me to remember..." />
          <MEMORY_STORE layer="concept" name="CONCEPT_NAME" definition="..." insight="..." />
          <MEMORY_STORE layer="procedural" trigger="When X" action="Do Y" />
          <MEMORY_STORE layer="working" content="Important for current conversation" />

        Returns the response text with all directives stripped out.
        """
        import re
        # Pattern that handles > inside quoted attribute values:
        # Matches <MEMORY_STORE attr="value with > inside" other="val" />
        # [^">/] matches normal chars, "[^"]*" matches quoted strings (may contain >)
        pattern = re.compile(
            r'<MEMORY_STORE\s+((?:[^">/]|"[^"]*")*)\s*/?>',
            re.IGNORECASE | re.DOTALL,
        )
        # Strip LLM meta-commentary leaked as bracket text at end of response
        response_text = re.sub(r'\n\[The user[^\]]*\]\s*$', '', response_text, flags=re.DOTALL).rstrip()

        matches = list(pattern.finditer(response_text))
        if not matches:
            # No complete tags — strip any truncated <MEMORY_STORE that didn't close
            response_text = re.sub(r'<MEMORY_STORE\b.*$', '', response_text, flags=re.DOTALL).rstrip()
            return response_text

        for match in matches:
            attrs_str = match.group(1)
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))
            layer = attrs.get("layer", "").lower()

            try:
                if layer == "semantic":
                    content = attrs.get("content", "")
                    confidence = float(attrs.get("confidence", "0.7"))
                    if content:
                        source = attrs.get("source", "chat_directive")
                        self.semantic_memory.store_truth(
                            knowledge=content,
                            confidence=confidence,
                            source=source,
                        )
                        logger.info("[Chat.MemoryStore] Semantic: '%s' (conf=%.2f)", content[:80], confidence)

                elif layer == "episodic":
                    content = attrs.get("content", "")
                    if content:
                        self.memory.store(
                            problem=f"[Chat directive] {content[:100]}",
                            reframed_problem=content,
                            xheart_distillate=content,
                            domain_tags=[t.strip() for t in attrs.get("tags", "general").split(",")],
                            layer_score=0.5,
                            self_generated_layers=None,
                        )
                        logger.info("[Chat.MemoryStore] Episodic: '%s'", content[:80])

                elif layer == "concept":
                    name = attrs.get("name", "")
                    definition = attrs.get("definition", "")
                    insight = attrs.get("insight", "")
                    if name and definition:
                        layer_info = {
                            "layer_name": name,
                            "layer_type": attrs.get("type", "SYNTHESIS"),
                            "gap_description": definition,
                            "key_insight": insight or definition,
                        }
                        self.memory.store_concept(
                            layer_info=layer_info,
                            problem="[Chat directive]",
                            distillate_core=definition,
                        )
                        logger.info("[Chat.MemoryStore] Concept: '%s'", name)

                elif layer == "procedural":
                    trigger = attrs.get("trigger", "")
                    action_text = attrs.get("action", "")
                    if trigger and action_text:
                        from xdart.models import ProceduralPattern
                        proc_pat = ProceduralPattern(
                            pattern_name=attrs.get("name", "chat_learned_pattern"),
                            trigger_condition=trigger,
                            action=action_text,
                            learned_from="[Chat directive]",
                        )
                        self.procedural_memory._store(proc_pat)
                        logger.info("[Chat.MemoryStore] Procedural: trigger='%s'", trigger[:60])

                elif layer == "working":
                    content = attrs.get("content", "")
                    if content:
                        self.working_memory.push(
                            item_type="insight",
                            content=content,
                            source="chat_directive",
                            relevance=float(attrs.get("relevance", "0.9")),
                        )
                        logger.info("[Chat.MemoryStore] Working: '%s'", content[:60])

                else:
                    logger.warning("[Chat.MemoryStore] Unknown layer: '%s'", layer)

            except Exception as e:
                logger.warning("[Chat.MemoryStore] Failed for layer '%s': %s", layer, e)

        # Strip complete directives from visible response
        clean_text = pattern.sub("", response_text).strip()
        # Strip any remaining truncated <MEMORY_STORE (all complete ones already removed)
        clean_text = re.sub(r'<MEMORY_STORE\b.*$', '', clean_text, flags=re.DOTALL).rstrip()
        # Clean up any double newlines left behind
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)

        logger.info("[Chat.MemoryStore] Processed %d memory directives", len(matches))
        return clean_text

    def _process_visual_directives(self, response_text: str) -> str:
        """Extract and execute <VISUAL_ACTION> directives from the LLM response.

        Αίολος can manage its visual perception memory through chat:
          <VISUAL_ACTION action="register_face" face_id="uuid" name="Πάνος" />
          <VISUAL_ACTION action="rename_face" old_name="Επισκέπτης_1" new_name="Μαρία" />
          <VISUAL_ACTION action="label_object" object_type="tv" label="Η τηλεόραση Samsung" context="στο σαλόνι" />
          <VISUAL_ACTION action="store_note" note="Ο Πάνος φοράει πάντα γυαλιά" category="observation" />
          <VISUAL_ACTION action="forget_face" name="Επισκέπτης_3" />

        Returns the response text with directives replaced by action confirmations.
        """
        vis = getattr(self, "_vision_integration", None)
        if not vis:
            # Still strip tags even without vision integration
            import re
            response_text = re.sub(
                r'<VISUAL_ACTION\b[^>]*>.*?</VISUAL_ACTION\s*>',
                '', response_text, flags=re.DOTALL | re.IGNORECASE,
            )
            response_text = re.sub(
                r'<VISUAL_ACTION\s+[^>]*/?>',
                '', response_text, flags=re.IGNORECASE,
            )
            response_text = re.sub(r'<VISUAL_ACTION\b.*$', '', response_text, flags=re.DOTALL).rstrip()
            return re.sub(r'\n{3,}', '\n\n', response_text).strip()

        import re

        # ── Format A: self-closing attribute-style ──
        # <VISUAL_ACTION action="register_face" face_id="uuid" name="Πάνος" />
        pattern_self_closing = re.compile(
            r'<VISUAL_ACTION\s+((?:[^">/]|"[^"]*")*)\s*/?>',
            re.IGNORECASE | re.DOTALL,
        )

        # ── Format B: block-style with JSON body ──
        # <VISUAL_ACTION>\n{ "action": "...", ... }\n</VISUAL_ACTION>
        pattern_block = re.compile(
            r'<VISUAL_ACTION\s*>\s*(\{.*?\})\s*</VISUAL_ACTION\s*>',
            re.IGNORECASE | re.DOTALL,
        )

        confirmations = []

        # Process block-style tags (JSON body)
        for match in pattern_block.finditer(response_text):
            try:
                import json as _json
                attrs = _json.loads(match.group(1))
                action_type = attrs.pop("action", "").strip()
                if not action_type:
                    continue
                str_attrs = {k: str(v) for k, v in attrs.items()}
                result = vis.execute_visual_action(action_type, str_attrs)
                if result.get("success"):
                    confirmations.append(f"✓ {result['description']}")
                    logger.info("[Chat.VisualAction] %s: %s", action_type, result['description'])
                else:
                    confirmations.append(f"✗ {result['description']}")
            except Exception as e:
                logger.warning("[Chat.VisualAction] Block-style parse error: %s", e)

        # Process self-closing tags (attribute-style)
        for match in pattern_self_closing.finditer(response_text):
            attrs_str = match.group(1)
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))
            action_type = attrs.pop("action", "").strip()
            if not action_type:
                continue
            try:
                result = vis.execute_visual_action(action_type, attrs)
                if result.get("success"):
                    confirmations.append(f"✓ {result['description']}")
                    logger.info("[Chat.VisualAction] %s: %s", action_type, result['description'])
                else:
                    confirmations.append(f"✗ {result['description']}")
                    logger.warning("[Chat.VisualAction] %s failed: %s", action_type, result['description'])
            except Exception as e:
                logger.warning("[Chat.VisualAction] %s error: %s", action_type, e)
                confirmations.append(f"✗ Σφάλμα: {e}")

        # Strip ALL visual action tags from visible response
        clean_text = pattern_block.sub("", response_text)
        clean_text = pattern_self_closing.sub("", clean_text)
        clean_text = re.sub(r'<VISUAL_ACTION\b.*$', '', clean_text, flags=re.DOTALL).rstrip()
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

        if confirmations:
            clean_text += "\n\n" + "\n".join(confirmations)

        logger.info("[Chat.VisualAction] Processed %d visual directives", len(confirmations))
        return clean_text

    def _process_mongo_directives(self, response_text: str) -> str:
        """Extract and execute <MONGO_ACTION> directives from the LLM response.

        Αίολος can interact with MongoDB through chat:
          <MONGO_ACTION action="save_note" title="..." content="..." tags="..." category="..." />
          <MONGO_ACTION action="update_note" title="..." content="..." />
          <MONGO_ACTION action="delete_note" title="..." />
          <MONGO_ACTION action="search_notes" q="..." tags="..." limit="..." />
          <MONGO_ACTION action="query_entities" type="..." name="..." limit="..." />
          <MONGO_ACTION action="entity_connections" name="..." />
          <MONGO_ACTION action="query_journal" collection="..." type="..." limit="..." />
          <MONGO_ACTION action="get_conversations" limit="..." />
          <MONGO_ACTION action="get_entity" name="..." />
          <MONGO_ACTION action="stats" />

        Write operations: Tags replaced by confirmation messages.
        Read operations: Tags replaced by query results formatted for the user.
        """
        mongo = getattr(self, '_mongo', None)
        if not mongo:
            # Strip tags even without MongoDB
            import re
            response_text = re.sub(
                r'<MONGO_ACTION\s+[^>]*/?>',
                '', response_text, flags=re.IGNORECASE,
            )
            response_text = re.sub(
                r'<MONGO_ACTION\b[^>]*>.*?</MONGO_ACTION\s*>',
                '', response_text, flags=re.DOTALL | re.IGNORECASE,
            )
            response_text = re.sub(r'<MONGO_ACTION\b.*$', '', response_text, flags=re.DOTALL).rstrip()
            return re.sub(r'\n{3,}', '\n\n', response_text).strip()

        import re
        import json as _json

        # Self-closing: <MONGO_ACTION action="..." param="..." />
        pattern_self_closing = re.compile(
            r'<MONGO_ACTION\s+((?:[^">/]|"[^"]*")*)\s*/?>',
            re.IGNORECASE | re.DOTALL,
        )
        # Block-style: <MONGO_ACTION>{ JSON }</MONGO_ACTION>
        pattern_block = re.compile(
            r'<MONGO_ACTION\s*>\s*(\{.*?\})\s*</MONGO_ACTION\s*>',
            re.IGNORECASE | re.DOTALL,
        )

        results_output = []

        # Process block-style
        for match in pattern_block.finditer(response_text):
            try:
                attrs = _json.loads(match.group(1))
                action_type = attrs.pop("action", "").strip()
                if not action_type:
                    continue
                str_attrs = {k: str(v) for k, v in attrs.items()}
                result = mongo.execute_action(action_type, str_attrs)
                self._format_mongo_result(result, action_type, results_output)
            except Exception as e:
                logger.warning("[Chat.MongoAction] Block parse error: %s", e)

        # Process self-closing
        for match in pattern_self_closing.finditer(response_text):
            attrs_str = match.group(1)
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))
            action_type = attrs.pop("action", "").strip()
            if not action_type:
                continue
            try:
                result = mongo.execute_action(action_type, attrs)
                self._format_mongo_result(result, action_type, results_output)
            except Exception as e:
                logger.warning("[Chat.MongoAction] %s error: %s", action_type, e)
                results_output.append(f"✗ MongoDB {action_type}: {e}")

        # Strip all tags
        clean_text = pattern_block.sub("", response_text)
        clean_text = pattern_self_closing.sub("", clean_text)
        clean_text = re.sub(r'<MONGO_ACTION\b.*$', '', clean_text, flags=re.DOTALL).rstrip()
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

        if results_output:
            logger.info("[Chat.MongoAction] Processed %d MongoDB directives:", len(results_output))
            for r in results_output:
                logger.info("[Chat.MongoAction]   %s", r)

        return clean_text

    @staticmethod
    def _format_mongo_result(result: dict, action_type: str, output: list) -> None:
        """Format a MongoDB action result for display."""
        import json as _json
        if result.get("success"):
            data = result.get("data")
            if data is not None:
                # Read operation — show results
                if isinstance(data, list):
                    if len(data) == 0:
                        output.append(f"📋 {result['description']} — κανένα αποτέλεσμα")
                    else:
                        output.append(f"📋 {result['description']}:")
                        for item in data[:15]:  # limit display
                            if isinstance(item, dict):
                                # Compact display
                                compact = {k: v for k, v in item.items()
                                           if k not in ('_id',) and v is not None}
                                output.append(f"  • {_json.dumps(compact, ensure_ascii=False, default=str)[:300]}")
                            else:
                                output.append(f"  • {str(item)[:300]}")
                        if len(data) > 15:
                            output.append(f"  ... και {len(data) - 15} ακόμα")
                elif isinstance(data, dict):
                    output.append(f"📋 {result['description']}:")
                    output.append(f"  {_json.dumps(data, ensure_ascii=False, default=str, indent=2)[:500]}")
            else:
                # Write operation — confirmation
                output.append(f"✓ {result['description']}")
        else:
            output.append(f"✗ {result.get('description', 'Unknown error')}")

    # ── Shell Executor directive processing ──────────────────────────
    def _process_shell_directives(self, response_text: str) -> str:
        """Extract and execute <SHELL_ACTION> directives from the LLM response.

        Αίολος can execute local commands through chat:
          <SHELL_ACTION action="execute" command="Get-Process | Select-Object -First 5" />
          <SHELL_ACTION action="python" code="print('hello')" />
          <SHELL_ACTION action="list_dir" path="C:\\Users" />
          <SHELL_ACTION action="read_file" path="notes.txt" />
          <SHELL_ACTION action="system_info" />
          <SHELL_ACTION action="git_status" />
          <SHELL_ACTION action="process_list" />
          <SHELL_ACTION action="disk_usage" />
          <SHELL_ACTION action="pip_install" package="requests" />
          <SHELL_ACTION action="web_request" url="https://example.com" />

        Returns the response text with directives replaced by execution results.
        """
        import re

        if not self.shell_executor:
            # Strip tags even without shell executor
            response_text = re.sub(
                r'<SHELL_ACTION\b[^>]*>.*?</SHELL_ACTION\s*>',
                '', response_text, flags=re.DOTALL | re.IGNORECASE,
            )
            response_text = re.sub(
                r'<SHELL_ACTION\s+[^>]*/?>',
                '', response_text, flags=re.IGNORECASE,
            )
            return re.sub(r'\n{3,}', '\n\n', response_text).strip()

        # ── Self-closing attribute-style ──
        pattern = re.compile(
            r'<SHELL_ACTION\s+((?:[^">/]|"[^"]*")*)\s*/?>',
            re.IGNORECASE | re.DOTALL,
        )

        confirmations = []

        for match in pattern.finditer(response_text):
            attrs_str = match.group(1)
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))
            action = attrs.pop("action", "").strip().lower()
            if not action:
                continue

            try:
                result = self._execute_shell_action(action, attrs)
                confirmations.append(result)
                logger.info("[Chat.ShellAction] %s → %s", action, result[:120])
            except Exception as e:
                msg = f"✗ shell({action}): {e}"
                confirmations.append(msg)
                logger.warning("[Chat.ShellAction] %s error: %s", action, e)

        # ── Block-style with nested elements (LLM hallucinated format) ──
        # <shell_action><command>Get-Process</command><timeout>10</timeout></shell_action>
        block_pattern = re.compile(
            r'<shell_action\b[^>]*>(.*?)</shell_action\s*>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in block_pattern.finditer(response_text):
            inner = match.group(1).strip()
            # Extract <command>...</command>
            cmd_match = re.search(r'<command>(.*?)</command>', inner, re.DOTALL | re.IGNORECASE)
            code_match = re.search(r'<code>(.*?)</code>', inner, re.DOTALL | re.IGNORECASE)
            timeout_match = re.search(r'<timeout>(\d+)</timeout>', inner, re.IGNORECASE)

            timeout_val = int(timeout_match.group(1)) if timeout_match else self.shell_executor.default_timeout

            if cmd_match:
                command = cmd_match.group(1).strip()
                if command:
                    try:
                        result = self._execute_shell_action("execute", {"command": command, "timeout": str(timeout_val)})
                        confirmations.append(result)
                        logger.info("[Chat.ShellAction/Block] execute → %s", result[:120])
                    except Exception as e:
                        confirmations.append(f"✗ shell(execute): {e}")
                        logger.warning("[Chat.ShellAction/Block] execute error: %s", e)
            elif code_match:
                code = code_match.group(1).strip()
                if code:
                    try:
                        result = self._execute_shell_action("python", {"code": code, "timeout": str(timeout_val)})
                        confirmations.append(result)
                        logger.info("[Chat.ShellAction/Block] python → %s", result[:120])
                    except Exception as e:
                        confirmations.append(f"✗ shell(python): {e}")
                        logger.warning("[Chat.ShellAction/Block] python error: %s", e)

        # Strip all SHELL_ACTION tags (both formats)
        clean_text = pattern.sub("", response_text)
        clean_text = block_pattern.sub("", clean_text)
        clean_text = re.sub(
            r'<SHELL_ACTION\b[^>]*>.*?</SHELL_ACTION\s*>',
            '', clean_text, flags=re.DOTALL | re.IGNORECASE,
        )
        clean_text = re.sub(r'<SHELL_ACTION\b.*$', '', clean_text, flags=re.DOTALL).rstrip()
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

        if confirmations:
            clean_text += "\n\n" + "\n".join(confirmations)

        if confirmations:
            logger.info("[Chat.ShellAction] Processed %d shell directives", len(confirmations))
            # ── Persist to episodic memory so Αίολος remembers across sessions ──
            try:
                summary = "; ".join(c[:120] for c in confirmations)
                self.memory.store(
                    problem=f"[ShellAction] Executed {len(confirmations)} command(s)",
                    reframed_problem=f"Shell execution results: {summary[:500]}",
                    xheart_distillate=f"Εκτέλεσα {len(confirmations)} εντολή/ές στο σύστημα. {summary[:300]}",
                    domain_tags=["shell_action", "tool_execution", "system_command"],
                    layer_score=0.4,
                    self_generated_layers=None,
                )
            except Exception as e:
                logger.warning("[Chat.ShellAction] Episodic store failed: %s", e)
            # ── Persist to journal file (survives restart) ──
            try:
                import json as _json
                from datetime import datetime, timezone
                _entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "shell_action",
                    "count": len(confirmations),
                    "results": [c[:500] for c in confirmations],
                }
                with open(BASE_DIR / "shell_action_journal.jsonl", "a", encoding="utf-8") as f:
                    f.write(_json.dumps(_entry, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning("[Chat.ShellAction] Journal write failed: %s", e)
        return clean_text

    def _execute_shell_action(self, action: str, attrs: dict) -> str:
        """Route a shell action to the appropriate ShellExecutor method."""
        se = self.shell_executor

        if action == "execute":
            command = attrs.get("command", "")
            if not command:
                return "✗ shell(execute): no command specified"
            timeout = int(attrs.get("timeout", se.default_timeout))
            result = se.execute(command, timeout=timeout)
            if result["success"]:
                output = result["stdout"].strip() or "(no output)"
                return f"🖥️ `{command}`:\n```\n{output}\n```"
            else:
                return f"✗ `{command}`: {result.get('stderr', result.get('error', 'failed'))}"

        elif action == "python":
            code = attrs.get("code", "")
            if not code:
                return "✗ shell(python): no code specified"
            timeout = int(attrs.get("timeout", se.default_timeout))
            result = se.execute_python(code, timeout=timeout)
            if result["success"]:
                output = result["stdout"].strip() or "(no output)"
                return f"🐍 Python:\n```\n{output}\n```"
            else:
                return f"✗ Python: {result.get('stderr', result.get('error', 'failed'))}"

        elif action == "list_dir":
            path = attrs.get("path", se.working_dir)
            result = se.list_directory(path)
            if result["success"]:
                return f"📁 {path}:\n```\n{result['stdout'].strip()}\n```"
            else:
                return f"✗ list_dir({path}): {result.get('stderr', 'failed')}"

        elif action == "read_file":
            path = attrs.get("path", "")
            if not path:
                return "✗ shell(read_file): no path specified"
            result = se.read_file(path)
            if result["success"]:
                return f"📄 {path}:\n```\n{result['stdout'].strip()}\n```"
            else:
                return f"✗ read_file({path}): {result.get('stderr', 'failed')}"

        elif action == "system_info":
            result = se.system_info()
            if result["success"]:
                return f"💻 System Info:\n```\n{result['stdout'].strip()}\n```"
            else:
                return f"✗ system_info: {result.get('stderr', 'failed')}"

        elif action == "git_status":
            result = se.git_status()
            if result["success"]:
                return f"📦 Git Status:\n```\n{result['stdout'].strip()}\n```"
            else:
                return f"✗ git_status: {result.get('stderr', 'failed')}"

        elif action == "process_list":
            result = se.process_list()
            if result["success"]:
                return f"⚙️ Processes:\n```\n{result['stdout'].strip()}\n```"
            else:
                return f"✗ process_list: {result.get('stderr', 'failed')}"

        elif action == "disk_usage":
            result = se.disk_usage()
            if result["success"]:
                return f"💾 Disk Usage:\n```\n{result['stdout'].strip()}\n```"
            else:
                return f"✗ disk_usage: {result.get('stderr', 'failed')}"

        elif action == "pip_install":
            package = attrs.get("package", "")
            if not package:
                return "✗ shell(pip_install): no package specified"
            result = se.pip_install(package)
            if result["success"]:
                return f"📦 pip install {package}: ✓ success"
            else:
                return f"✗ pip install {package}: {result.get('stderr', 'failed')}"

        elif action == "web_request":
            url = attrs.get("url", "")
            if not url:
                return "✗ shell(web_request): no url specified"
            result = se.web_request(url)
            if result["success"]:
                output = result["stdout"].strip()[:2000]
                return f"🌐 {url}:\n```\n{output}\n```"
            else:
                return f"✗ web_request({url}): {result.get('stderr', 'failed')}"

        else:
            return f"✗ Unknown shell action: {action}"

    # ── Agent Spawner directive processing ──────────────────────────
    def _process_agent_directives(self, response_text: str) -> str:
        """Extract and execute <SPAWN_AGENT> directives from the LLM response.

        Αίολος can delegate subtasks to specialized sub-agents:
          <SPAWN_AGENT role="researcher" task="Find recent Iran nuclear developments" />
          <SPAWN_AGENT role="analyst" task="Assess economic impact" context="GDP=2.1%..." />
          <SPAWN_AGENT role="critic" task="Challenge this: NATO expansion deters Russia" />
          <SPAWN_AGENT role="custom" task="..." custom_prompt="You are a military expert..." />

        Multiple SPAWN_AGENT tags in one response are executed IN PARALLEL.
        Returns the response text with directives replaced by agent results.
        """
        import re

        if not self.agent_spawner:
            # Strip tags even without agent spawner
            response_text = re.sub(
                r'<SPAWN_AGENT\b[^>]*>.*?</SPAWN_AGENT\s*>',
                '', response_text, flags=re.DOTALL | re.IGNORECASE,
            )
            response_text = re.sub(
                r'<SPAWN_AGENT\s+[^>]*/?>',
                '', response_text, flags=re.IGNORECASE,
            )
            return re.sub(r'\n{3,}', '\n\n', response_text).strip()

        # ── Self-closing attribute-style ──
        pattern = re.compile(
            r'<SPAWN_AGENT\s+((?:[^">/]|"[^"]*")*)\s*/?>',
            re.IGNORECASE | re.DOTALL,
        )

        # ── Block-style with nested elements (LLM hallucinated format) ──
        # <spawn_agent><role>researcher</role><task>Find data</task></spawn_agent>
        block_pattern = re.compile(
            r'<spawn_agent\b[^>]*>(.*?)</spawn_agent\s*>',
            re.IGNORECASE | re.DOTALL,
        )

        # Collect all agent specs first
        agent_specs = []
        for match in pattern.finditer(response_text):
            attrs_str = match.group(1)
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))
            role = attrs.get("role", "researcher").strip().lower()
            task = attrs.get("task", "").strip()
            if not task:
                continue
            agent_specs.append({
                "role": role,
                "task": task,
                "context": attrs.get("context", ""),
                "custom_prompt": attrs.get("custom_prompt", ""),
                "max_tokens": int(attrs.get("max_tokens", "4000")),
                "temperature": float(attrs.get("temperature", "0.5")),
            })

        # Also parse block-style hallucinated format
        for match in block_pattern.finditer(response_text):
            inner = match.group(1).strip()
            role_match = re.search(r'<role>(.*?)</role>', inner, re.DOTALL | re.IGNORECASE)
            task_match = re.search(r'<task>(.*?)</task>', inner, re.DOTALL | re.IGNORECASE)
            ctx_match = re.search(r'<context>(.*?)</context>', inner, re.DOTALL | re.IGNORECASE)
            prompt_match = re.search(r'<custom_prompt>(.*?)</custom_prompt>', inner, re.DOTALL | re.IGNORECASE)

            role = role_match.group(1).strip().lower() if role_match else "researcher"
            task = task_match.group(1).strip() if task_match else ""
            if not task:
                continue
            agent_specs.append({
                "role": role,
                "task": task,
                "context": ctx_match.group(1).strip() if ctx_match else "",
                "custom_prompt": prompt_match.group(1).strip() if prompt_match else "",
                "max_tokens": 4000,
                "temperature": 0.5,
            })
            logger.info("[Chat.AgentSpawner/Block] Parsed block-style spawn_agent: role=%s task=%s",
                        role, task[:80])

        if not agent_specs:
            # No valid agents found, just strip any broken tags
            clean = pattern.sub("", response_text)
            clean = block_pattern.sub("", clean)
            clean = re.sub(r'<SPAWN_AGENT\b.*$', '', clean, flags=re.DOTALL).rstrip()
            return re.sub(r'\n{3,}', '\n\n', clean).strip()

        # Execute — if single agent, use spawn(); if multiple, use spawn_parallel()
        logger.info("[Chat.AgentSpawner] Spawning %d sub-agent(s)", len(agent_specs))

        if len(agent_specs) == 1:
            spec = agent_specs[0]
            results = [self.agent_spawner.spawn(**spec)]
        else:
            results = self.agent_spawner.spawn_parallel(agent_specs)

        # Format results
        confirmations = []
        for r in results:
            if r.success:
                header = f"🤖 **Sub-agent ({r.role})** — {r.task[:80]}"
                confirmations.append(f"{header}\n{r.output}")
                logger.info("[Chat.AgentSpawner] %s (%s) completed in %dms",
                            r.agent_id, r.role, r.duration_ms)
            else:
                confirmations.append(f"✗ Sub-agent ({r.role}) failed: {r.error}")
                logger.warning("[Chat.AgentSpawner] %s (%s) failed: %s",
                               r.agent_id, r.role, r.error)

        # Strip all SPAWN_AGENT tags (both formats)
        clean_text = pattern.sub("", response_text)
        clean_text = block_pattern.sub("", clean_text)
        clean_text = re.sub(
            r'<SPAWN_AGENT\b[^>]*>.*?</SPAWN_AGENT\s*>',
            '', clean_text, flags=re.DOTALL | re.IGNORECASE,
        )
        clean_text = re.sub(r'<SPAWN_AGENT\b.*$', '', clean_text, flags=re.DOTALL).rstrip()
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

        if confirmations:
            separator = "\n\n---\n\n"
            clean_text += separator + separator.join(confirmations)

        logger.info("[Chat.AgentSpawner] Processed %d agent directives", len(results))

        # ── Persist successful agent results to episodic memory ──
        successful = [r for r in results if r.success]
        if successful:
            try:
                summary_parts = [f"{r.role}: {r.task[:80]} → {r.output[:200]}" for r in successful]
                summary = "\n".join(summary_parts)
                self.memory.store(
                    problem=f"[AgentSpawner] Spawned {len(successful)} sub-agent(s): {', '.join(r.role for r in successful)}",
                    reframed_problem=f"Sub-agent results:\n{summary[:800]}",
                    xheart_distillate=f"Ανέθεσα {len(successful)} υπο-αναλύσεις σε agents. {summary[:400]}",
                    domain_tags=["agent_spawner", "tool_execution", "sub_agent_research"],
                    layer_score=0.5,
                    self_generated_layers=None,
                )
            except Exception as e:
                logger.warning("[Chat.AgentSpawner] Episodic store failed: %s", e)
            # ── Persist to journal file ──
            try:
                import json as _json
                from datetime import datetime, timezone
                _entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "agent_spawn",
                    "agents": [
                        {"role": r.role, "task": r.task[:200], "success": r.success,
                         "duration_ms": r.duration_ms, "output_len": len(r.output)}
                        for r in results
                    ],
                }
                with open(BASE_DIR / "agent_spawn_journal.jsonl", "a", encoding="utf-8") as f:
                    f.write(_json.dumps(_entry, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning("[Chat.AgentSpawner] Journal write failed: %s", e)
        return clean_text

    def _process_bf_directives(self, response_text: str) -> str:
        """Intercept <BAYESIAN_FUZZY_ENGINE> tags in LLM response and execute the real engine.

        Handles TWO tag formats that Αίολος uses:

        Format A (attribute-style, self-closing):
            <BAYESIAN_FUZZY_ENGINE domain="financial_stress" variables="..." />

        Format B (block-style with child elements):
            <BAYESIAN_FUZZY_ENGINE>
            <domain>financial_stress</domain>
            <query>Assess current market reaction...</query>
            </BAYESIAN_FUZZY_ENGINE>

        After replacing the tag with real engine output, also strips fabricated
        results that Αίολος writes after the tag (fake posteriors, probabilities,
        "Η Bayesian-Fuzzy ανάλυση δείχνει:" blocks, etc.).

        Returns cleaned response text.
        """
        import re

        # ── Helper: strip all BFE tags (both formats) for no-engine path ──
        def _strip_all_bfe_tags(text: str) -> str:
            # Block-style: <BAYESIAN_FUZZY_ENGINE>...</BAYESIAN_FUZZY_ENGINE>
            text = re.sub(
                r'<BAYESIAN_FUZZY_ENGINE\b[^>]*>.*?</BAYESIAN_FUZZY_ENGINE\s*>',
                '[Bayesian-Fuzzy Engine not available]',
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            # Self-closing: <BAYESIAN_FUZZY_ENGINE ... />
            text = re.sub(
                r'<BAYESIAN_FUZZY_ENGINE\b[^>]*/?>',
                '[Bayesian-Fuzzy Engine not available]',
                text,
                flags=re.IGNORECASE,
            )
            return text

        # ── Helper: strip fabricated BFE results that Αίολος writes inline ──
        def _strip_fake_bfe_results(text: str) -> str:
            # Pattern 1: "Η **Bayesian-Fuzzy ανάλυση** (που τρέχει αυτόματα) δείχνει:" + bullet list
            text = re.sub(
                r'Η\s+\*{0,2}Bayesian-Fuzzy\s+αν[αά]λυση\*{0,2}[^:]*:[^\n]*\n'
                r'(?:[-•*]\s+\*{0,2}[^*\n]+\*{0,2}[^\n]*\n)*',
                '',
                text,
                flags=re.IGNORECASE,
            )
            # Pattern 2: "**Ερμηνεία**:" paragraph following fake results
            text = re.sub(
                r'\*{2}Ερμηνεία\*{2}\s*:.*?(?=\n\n|\n\*{2,}|\n#{1,}|\Z)',
                '',
                text,
                flags=re.DOTALL,
            )
            # Pattern 3: "*Θα τρέξει η μηχανή..." legacy pattern
            text = re.sub(
                r'\*Θα τρέξει η μηχανή[^*]*\*',
                '',
                text,
            )
            # Pattern 4: Fabricated posteriors like "Systemic risk: high (P=0.672)"
            # Only strip if they appear in a cluster (3+ consecutive lines with P=...)
            text = re.sub(
                r'(?:[-•*]\s+\*{0,2}[^:\n]+:\s*\w+\s*\(P\s*=\s*[\d.]+\)\*{0,2}\s*[-–—]?[^\n]*\n){2,}',
                '',
                text,
            )
            # Pattern 5: Fabricated "Κύριοι παράγοντες:" line after fake results
            text = re.sub(
                r'[-•*]\s+\*{0,2}Κύρι[οα][ιη]\s+παράγοντε?ς?\*{0,2}\s*:[^\n]*\n',
                '',
                text,
            )
            return text

        # ── Helper: extract domain/query/variables from a BFE match ──
        def _extract_bfe_params(match_obj, is_block: bool) -> tuple[str, str, str, str]:
            """Returns (domain_hint, query, variables, target)."""
            if is_block:
                inner = match_obj.group(1)  # content between open/close tags
                domain = ""
                query = ""
                variables = ""
                target = ""
                m = re.search(r'<domain\s*>(.*?)</domain\s*>', inner, re.IGNORECASE | re.DOTALL)
                if m:
                    domain = m.group(1).strip()
                m = re.search(r'<query\s*>(.*?)</query\s*>', inner, re.IGNORECASE | re.DOTALL)
                if m:
                    query = m.group(1).strip()
                m = re.search(r'<variables\s*>(.*?)</variables\s*>', inner, re.IGNORECASE | re.DOTALL)
                if m:
                    variables = m.group(1).strip()
                m = re.search(r'<target\s*>(.*?)</target\s*>', inner, re.IGNORECASE | re.DOTALL)
                if m:
                    target = m.group(1).strip()
                return domain, query, variables, target
            else:
                attrs_str = match_obj.group(1) or ""
                attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))
                return (
                    attrs.get("domain", ""),
                    attrs.get("query", ""),
                    attrs.get("variables", ""),
                    attrs.get("target", ""),
                )

        if not self.bayesian_fuzzy:
            text = _strip_all_bfe_tags(response_text)
            text = _strip_fake_bfe_results(text)
            return re.sub(r'\n{3,}', '\n\n', text)

        # ── Collect all BFE matches (both formats) with positions ──
        # Format B: block-style <BFE>...</BFE>
        block_pattern = re.compile(
            r'<BAYESIAN_FUZZY_ENGINE\b[^>]*>(.*?)</BAYESIAN_FUZZY_ENGINE\s*>',
            re.IGNORECASE | re.DOTALL,
        )
        # Format A: self-closing <BFE attrs />  or  <BFE attrs>
        attr_pattern = re.compile(
            r'<BAYESIAN_FUZZY_ENGINE\s+((?:[^">/]|"[^"]*")*)\s*/?>',
            re.IGNORECASE | re.DOTALL,
        )

        # Gather all matches with metadata
        all_matches: list[tuple[re.Match, bool]] = []  # (match, is_block)
        for m in block_pattern.finditer(response_text):
            all_matches.append((m, True))

        # Only add attr-style matches that don't overlap with block matches
        block_spans = {(m.start(), m.end()) for m, _ in all_matches}
        for m in attr_pattern.finditer(response_text):
            overlaps = any(
                m.start() >= bs and m.start() < be
                for bs, be in block_spans
            )
            if not overlaps:
                all_matches.append((m, False))

        # Sort by position, then process in reverse
        all_matches.sort(key=lambda x: x[0].start())

        if not all_matches:
            # No tags found — but still strip any fake BFE results
            text = _strip_fake_bfe_results(response_text)
            return re.sub(r'\n{3,}', '\n\n', text)

        logger.info(
            "[Chat.BF_Directive] Found %d BFE tag(s) in response — executing real engine",
            len(all_matches),
        )

        for match, is_block in reversed(all_matches):
            domain_hint, query, variables, target = _extract_bfe_params(match, is_block)

            # Build problem statement — prefer query if available
            if query:
                problem = query
                if domain_hint:
                    problem = f"[{domain_hint}] {query}"
            else:
                problem = f"Bayesian-Fuzzy analysis: domain={domain_hint}"
                if variables:
                    problem += f", variables=[{variables}]"
                if target:
                    problem += f", target={target}"

            try:
                world_ctx = ""
                try:
                    world_ctx = Path("world.txt").read_text(encoding="utf-8")[:4000]
                except Exception:
                    pass

                # Accept both built-in and custom template domain names
                bf_result = self.bayesian_fuzzy.run_chat(
                    problem=problem,
                    world_context=world_ctx,
                    domain_hint=domain_hint or "",
                )

                real_output_parts = [
                    "\n**BAYESIAN-FUZZY ENGINE — REAL EXECUTION RESULTS:**",
                    f"  Domain: {bf_result.domain} ({bf_result.domain_description})" if bf_result.domain_description else f"  Domain: {bf_result.domain}",
                    f"  Risk Level: **{bf_result.dominant_risk_level.upper()}**",
                ]
                for rp in bf_result.risk_posteriors:
                    real_output_parts.append(
                        f"  • {rp.risk_variable}: **{rp.dominant_level}** (P={rp.dominant_probability:.3f})"
                    )
                if bf_result.key_drivers:
                    real_output_parts.append(f"  Key drivers: {', '.join(bf_result.key_drivers[:5])}")
                if bf_result.causal_chain:
                    real_output_parts.append(f"  Causal chain: {bf_result.causal_chain[:300]}")
                if bf_result.risk_narrative:
                    real_output_parts.append(f"  Narrative: {bf_result.risk_narrative[:500]}")
                if bf_result.missing_data:
                    real_output_parts.append(f"  Missing data: {', '.join(bf_result.missing_data[:5])}")
                real_output_parts.append(f"  Engine time: {bf_result.elapsed_seconds:.2f}s\n")

                real_output = "\n".join(real_output_parts)

                logger.info(
                    "[Chat.BF_Directive] BFE executed: domain=%s, risk=%s, %d posteriors",
                    bf_result.domain, bf_result.dominant_risk_level, len(bf_result.risk_posteriors),
                )

            except Exception as e:
                logger.warning("[Chat.BF_Directive] BFE execution failed: %s", e)
                real_output = f"\n[Bayesian-Fuzzy Engine execution failed: {e}]\n"

            response_text = response_text[:match.start()] + real_output + response_text[match.end():]

        # Strip fabricated results that Αίολος wrote around/after the tags
        response_text = _strip_fake_bfe_results(response_text)

        # Clean up excessive newlines
        response_text = re.sub(r'\n{3,}', '\n\n', response_text)

        return response_text

    def _strip_internal_operation_leaks(self, response_text: str) -> str:
        """Strip internal operation artifacts that Αίολος should not output to the user.

        Αίολος sometimes tries to 'execute' internal tools by writing XML-like tags
        in chat. These are internal operation leaks that don't work:
        - <run>tool: ...</run> tags
        - <execute>...</execute> tags
        - "ΕΚΤΕΛΕΣΗ" sections with tool invocations (not conceptual proposals)
        - "ΤΙ ΘΑ ΚΑΝΩ ΤΩΡΑ" self-narration of internal operations

        Note: Conceptual improvement proposals ARE allowed and NOT stripped.
        Only XML execution tags and internal operation narration are removed.
        """
        import re

        original_len = len(response_text)

        # 1. Strip <run>...</run>, <run_*>...</run_*>, <execute>...</execute> tags
        # The LLM hallucinates various execution tags: <run>, <run_web_agent>,
        # <run_tool>, <execute>, etc. Catch them all with a broad pattern.
        for tag_pattern in (
            r'<run(?:_\w+)?\b[^>]*>.*?</run(?:_\w+)?\s*>',   # <run>, <run_web_agent>, <run_tool>, etc.
            r'<execute\b[^>]*>.*?</execute\s*>',               # <execute>...</execute>
            r'<search\b[^>]*>.*?</search\s*>',                 # <search>...</search>
            r'<tool_call\b[^>]*>.*?</tool_call\s*>',           # <tool_call>...</tool_call>
            r'<function_call\b[^>]*>.*?</function_call\s*>',   # <function_call>...</function_call>
        ):
            matches = re.findall(tag_pattern, response_text, flags=re.DOTALL | re.IGNORECASE)
            if matches:
                for m in matches:
                    logger.info("[Chat.InternalStrip] Stripped execution tag: %s", m[:120])
                response_text = re.sub(tag_pattern, '', response_text, flags=re.DOTALL | re.IGNORECASE)

        # 3. Strip "ΕΚΤΕΛΕΣΗ" sections ONLY when they contain tool execution references
        # (not conceptual proposals that happen to use the word)
        response_text = re.sub(
            r'#{1,4}\s*ΕΚΤΕΛΕΣΗ[^\n]*\n(?:(?:.*?<run\b|.*?tool:|.*?auto_analyze).*?(?=\n#{1,4}\s|\Z))',
            '',
            response_text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # 4. Strip "ΤΙ ΘΑ ΚΑΝΩ ΤΩΡΑ" self-narration of internal operations
        response_text = re.sub(
            r'#{1,4}\s*ΤΙ ΘΑ ΚΑΝΩ ΤΩΡΑ[^\n]*\n(?:.*?(?=\n#{1,4}\s|\Z))',
            '',
            response_text,
            flags=re.DOTALL,
        )

        # 5. Strip any remaining internal tags that slipped through earlier processors
        # Block-style: <TAG>...</TAG>
        for tag in ('VISUAL_ACTION', 'MEMORY_STORE', 'BAYESIAN_FUZZY_ENGINE',
                     'SHELL_ACTION', 'SPAWN_AGENT', 'MONGO_ACTION',
                     'run_web_agent', 'run_tool', 'run_search', 'auto_search'):
            response_text = re.sub(
                rf'<{tag}\b[^>]*>.*?</{tag}\s*>',
                '', response_text, flags=re.DOTALL | re.IGNORECASE,
            )
            # Self-closing: <TAG ... />
            response_text = re.sub(
                rf'<{tag}\s+[^>]*/?>',
                '', response_text, flags=re.IGNORECASE,
            )

        # 6. Strip bracket-style hallucinated tags: [TAG: ...], [TAG: key=value, ...]
        # The LLM sometimes uses square-bracket syntax instead of XML.
        # These are NOT executed — they are pure hallucinations that leak into visible text.
        for btag in ('VISUAL_ACTION', 'MEMORY_STORE', 'SHELL_ACTION', 'SPAWN_AGENT',
                      'MONGO_ACTION', 'BAYESIAN_FUZZY_ENGINE'):
            response_text = re.sub(
                rf'\[{btag}[:\s][^\]]*\]',
                '', response_text, flags=re.IGNORECASE,
            )

        # Clean up excessive newlines and trailing whitespace
        response_text = re.sub(r'\n{3,}', '\n\n', response_text).strip()

        stripped_chars = original_len - len(response_text)
        if stripped_chars > 50:
            logger.info("[Chat.InternalStrip] Stripped %d chars of internal operation leaks", stripped_chars)

        return response_text

    def _multi_turn_call(self, messages: list[dict], thinking: bool | None = None) -> str:
        """Make a multi-turn LLM call with full message history.

        For reasoning models: strips reasoning_content from history (causes 400),
        skips temperature parameter, captures CoT.

        Args:
            thinking: Override thinking mode. None=use global, False=disable.
        """
        import time as _time
        t0 = _time.perf_counter()

        # Clean messages — reasoning models reject reasoning_content in input
        clean_messages = []
        for msg in messages:
            clean_msg = {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            clean_messages.append(clean_msg)

        kwargs: dict = {
            "model": self.llm.model,
            "messages": clean_messages,
            "max_completion_tokens": 16384,
        }
        if not self.llm.is_reasoning:
            kwargs["temperature"] = 0.7
        # DeepSeek thinking mode — allow per-call override
        use_thinking = thinking if thinking is not None else self.llm.thinking_enabled
        if use_thinking and self.llm.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        elif self.llm.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        response = self.llm.client.chat.completions.create(**kwargs)
        elapsed = _time.perf_counter() - t0

        if not response.choices:
            logger.error("[Chat._multi_turn] API returned empty choices — elapsed %.2fs", elapsed)
            return ""

        message = response.choices[0].message
        content = message.content or ""

        # Capture reasoning content (CoT) if available
        reasoning = getattr(message, "reasoning_content", None)
        self.llm.last_reasoning_content = reasoning
        if reasoning:
            logger.info("[Chat._multi_turn] Reasoning (CoT): %d chars", len(reasoning))

        # DeepSeek thinking models sometimes put everything in reasoning_content
        # and return empty content. Fall back to reasoning in that case.
        if not content and reasoning:
            logger.warning("[Chat._multi_turn] Content empty but reasoning has %d chars — using reasoning as response", len(reasoning))
            content = reasoning

        logger.info("[Chat._multi_turn] Response: %d chars in %.2fs", len(content), elapsed)
        return content

    def _maybe_update_self_prompt(
        self,
        message: str,
        response: str,
        history: list[dict] | None,
        character: dict,
        full_context: str,
    ) -> None:
        """Post-chat self-reflection: decide if the AI should rewrite its own self_prompt.

        This runs after every chat response. It's a lightweight check (~200 tokens)
        followed by a heavier writer call (~1000 tokens) only when triggered.
        """
        try:
            # Build conversation snippet for reflection
            conv_snippet = ""
            if history:
                for h in history[-4:]:
                    role = h.get("role", "user")
                    conv_snippet += f"[{role.upper()}]: {h.get('content', '')[:300]}\n"
            conv_snippet += f"[USER]: {message[:500]}\n"
            conv_snippet += f"[ΑΙΟΛΟΣ]: {response[:500]}\n"

            # Step 1: Lightweight reflection — should we update?
            reflection_user = (
                f"CONVERSATION:\n{conv_snippet}\n\n"
                f"CURRENT SELF_PROMPT (what the AI previously wrote about itself):\n"
                f"{character.get('self_prompt', '(empty — never written)')[:500]}\n\n"
                f"Should the AI update its self_prompt based on this conversation?"
            )

            reflection = self.llm.call_json(
                self.SELF_REFLECTION_PROMPT,
                reflection_user,
                max_tokens=150,
                temperature=0.2,
                thinking=False,
            )

            decision = reflection.get("decision", "skip")
            reason = reflection.get("reason", "")
            logger.info("[Chat.SelfReflection] Decision: %s — %s", decision, reason)

            if decision != "update":
                return

            # Step 2: Write the new self_prompt
            writer_user = (
                f"YOUR CURRENT SELF_PROMPT:\n"
                f"{character.get('self_prompt', '(empty — this is your first time writing about yourself)')}\n\n"
                f"YOUR CHARACTER STATE SUMMARY:\n"
                f"- Name: {character.get('name', 'Αίολος')}\n"
                f"- Creator: {character.get('creator', 'Πάνος')}\n"
                f"- Version: {character.get('version', 0)}\n"
                f"- Epistemic stance (first 300 chars): {character.get('current_epistemic_stance', '')[:300]}\n"
                f"- Active tensions: {len(character.get('active_tensions', []))}\n"
                f"- Concepts owned: {len(character.get('named_concepts_owned', []))}\n\n"
                f"THE CONVERSATION THAT TRIGGERED THIS UPDATE:\n{conv_snippet}\n\n"
                f"RELATED MEMORIES:\n{full_context[:2000]}\n\n"
                f"Now write your new self_prompt. Remember: this defines how you present yourself "
                f"in all future conversations."
            )

            new_self_prompt = self.llm.call(
                self.SELF_PROMPT_WRITER_PROMPT,
                writer_user,
                max_tokens=2000,
                temperature=0.7,
                thinking=False,
            )

            if not new_self_prompt or len(new_self_prompt.strip()) < 50:
                logger.warning("[Chat.SelfPrompt] Generated self_prompt too short, skipping")
                return

            new_self_prompt = new_self_prompt.strip()
            old_self_prompt = character.get("self_prompt", "")

            # Step 3: Save to character_state.json
            import json as _json
            character["self_prompt"] = new_self_prompt
            with open(CHARACTER_STATE_PATH, "w", encoding="utf-8") as f:
                _json.dump(character, f, ensure_ascii=False, indent=2)

            logger.info("[Chat.SelfPrompt] SELF-PROMPT UPDATED (%d chars) trigger=%s", len(new_self_prompt), reason)
            logger.info("[Chat.SelfPrompt] Preview: %s", new_self_prompt[:200])

            # Step 4: Log to core_change_log.jsonl (append-only witness)
            try:
                change_logger = CoreChangeLogger()
                if hasattr(self, '_mongo'):
                    change_logger._mongo = self._mongo
                change_logger.log(
                    run_number=character.get("version", 0),
                    change_type="SELF_PROMPT_UPDATE",
                    target="character_state.json/self_prompt",
                    description=f"AI rewrote its own self_prompt during chat. Trigger: {reason}",
                    reasoning=reason,
                    evidence_runs=[message[:200]],
                    distillate_at_time=new_self_prompt[:300],
                    concept_that_triggered=None,
                    expected_effect="Future chat responses will reflect the updated self-description.",
                    risk_acknowledged="Self-prompt may drift from user intent if reflection triggers too often.",
                    applied=True,
                )
            except Exception as log_err:
                logger.warning("[Chat.SelfPrompt] Failed to log change: %s", log_err)

        except Exception as e:
            # Self-reflection is non-critical — never crash the chat flow
            logger.warning("[Chat.SelfReflection] Failed: %s", e)

    def _apply_curiosity_changes(self, changes: dict, character: dict) -> None:
        """Apply character state changes suggested by curiosity reflection.

        Updates open_questions, active_tensions, and how_i_have_changed,
        then persists to character_state.json.
        """
        import json as _json
        modified = False

        # Remove answered questions
        answered = changes.get("questions_answered", [])
        if answered and character.get("open_questions"):
            original = character["open_questions"][:]
            character["open_questions"] = [
                q for q in character["open_questions"]
                if not any(a.lower() in q.lower() or q.lower() in a.lower() for a in answered)
            ]
            if len(character["open_questions"]) != len(original):
                modified = True

        # Add new questions
        new_q = changes.get("new_questions", [])
        if new_q:
            existing = character.get("open_questions", [])
            for q in new_q:
                if q and q not in existing:
                    existing.append(q)
                    modified = True
            character["open_questions"] = existing[-10:]  # Keep last 10

        # Resolve a tension
        resolved = changes.get("resolved_tension")
        if resolved and character.get("active_tensions"):
            for t in character["active_tensions"]:
                if not t.get("resolved") and resolved.lower() in t.get("description", "").lower():
                    t["resolved"] = True
                    modified = True
                    break

        # Add new tension
        new_tension = changes.get("new_tension")
        if new_tension:
            character.setdefault("active_tensions", []).append({
                "description": new_tension,
                "resolved": False,
                "opened_at_run": character.get("version", 0),
            })
            modified = True

        # Record character change
        char_change = changes.get("character_change")
        if char_change and isinstance(char_change, dict) and char_change.get("before"):
            character.setdefault("how_i_have_changed", []).append(char_change)
            modified = True

        if modified:
            # Increment version on curiosity-driven changes
            character["version"] = character.get("version", 0) + 1
            try:
                with open(CHARACTER_STATE_PATH, "w", encoding="utf-8") as f:
                    _json.dump(character, f, ensure_ascii=False, indent=2)
                logger.info("[Curiosity] Character state updated from exploration reflection")
                # Log change
                try:
                    change_logger = CoreChangeLogger()
                    if hasattr(self, '_mongo'):
                        change_logger._mongo = self._mongo
                    change_logger.log(
                        run_number=character.get("version", 0),
                        change_type="CURIOSITY_REFLECTION",
                        target="character_state.json",
                        description=f"Autonomous curiosity exploration changed character state",
                        reasoning=str(changes)[:300],
                        evidence_runs=[],
                        distillate_at_time="",
                        concept_that_triggered=None,
                        expected_effect="Character state reflects new knowledge from self-directed exploration",
                        risk_acknowledged="Character drift from autonomous updates",
                        applied=True,
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.warning("[Curiosity] Failed to save character changes: %s", e)

    def inject_knowledge(self, source: str, content: str) -> int:
        """Inject external knowledge that will be used in the next pipeline run.

        Args:
            source: Source identifier (e.g., "academic_paper", "expert_briefing").
            content: The knowledge text.

        Returns:
            Total number of injected knowledge entries.
        """
        self._external_knowledge.append({"source": source, "content": content})
        logger.info("[Knowledge] Injected: [%s] %s", source, content[:80])
        return len(self._external_knowledge)

    def clear_knowledge(self) -> int:
        """Clear all injected external knowledge. Returns count cleared."""
        cleared = len(self._external_knowledge)
        self._external_knowledge.clear()
        return cleared

    def list_knowledge(self) -> list[dict]:
        """List all currently injected external knowledge."""
        return list(self._external_knowledge)

    # ── Summarizers for inter-phase communication ──

    @staticmethod
    def _summarize_ontology(o) -> str:
        return (
            f"Ontological Nature: {o.ontological_nature}\n"
            f"Teleological Purpose: {o.teleological_purpose}\n"
            f"Causal Analysis: {o.causal_analysis}\n"
            f"Epistemological Check: {o.epistemological_check}\n"
            f"Reframed Problem: {o.reframed_problem}"
        )

    @staticmethod
    def _summarize_cross_domain(cd) -> str:
        lines = [f"Reframed: {cd.reframed_problem}", f"Layer: {cd.layer.value}", ""]
        for d in cd.domains_analyzed:
            lines.append(
                f"[{d.analogy_strength.value}] {d.domain} "
                f"(dist={d.domain_distance}, spec={d.mechanistic_specificity}): "
                f"{d.core_mechanism} → {d.transfer_hypothesis}"
            )
        lines.append(f"\nStrongest: {cd.strongest_analogy.domain}")
        lines.append(f"Structural formula: {cd.structural_formula}")
        if cd.layer_3_hypothesis:
            lines.append(f"Layer-3 Hypothesis: {cd.layer_3_hypothesis}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_views(v) -> str:
        lines = []
        for vi in v.views_applied:
            lines.append(f"[{vi.view_id}] {vi.view_name}: {vi.insight}")
            lines.append(f"  → Reveals: {vi.reveals_hidden}")
        lines.append(f"\nConvergent: {'; '.join(v.convergent_patterns)}")
        lines.append(f"Divergent: {'; '.join(v.divergent_insights)}")
        lines.append(f"Dominant: {v.dominant_pattern}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_scenario_pipeline(genesis, simulations, tribunal) -> str:
        """Summarize the entire scenario pipeline for XHEART."""
        lines = []

        # Scenarios
        lines.append(f"SCENARIOS GENERATED: {len(genesis.scenarios)}")
        lines.append(f"Generation logic: {genesis.generation_logic}\n")

        sim_by_id = {s.scenario_id: s for s in simulations.simulations}
        verdict_by_id = {v.scenario_id: v for v in tribunal.verdicts}

        for scenario in genesis.scenarios:
            sim = sim_by_id.get(scenario.id)
            verdict = verdict_by_id.get(scenario.id)

            rank = verdict.feasibility_rank if verdict else "?"
            score = f"{verdict.final_score:.2f}" if verdict else "?"
            rob = f"{sim.robustness_score:.2f}" if sim else "?"

            lines.append(f"[#{rank}] {scenario.name} (score={score}, robustness={rob})")
            lines.append(f"  Narrative: {scenario.narrative[:200]}")
            lines.append(f"  Outcome: {scenario.predicted_outcome[:150]}")
            lines.append(f"  Timeline: {scenario.timeline}")
            if sim:
                lines.append(f"  Simulation insight: {sim.simulation_insight[:200]}")
                fatal = [bp for bp in sim.breakpoints if bp.severity == "FATAL"]
                if fatal:
                    lines.append(f"  FATAL breakpoints: {'; '.join(bp.reason[:80] for bp in fatal)}")
            lines.append("")

        # Tribunal
        lines.append(f"DOMINANT SCENARIO: {tribunal.dominant_scenario.scenario_name} "
                     f"(score={tribunal.dominant_scenario.final_score:.2f})")
        lines.append(f"ALTERNATIVES: {len(tribunal.alternative_scenarios)}")
        lines.append(f"CONVERGENCE: {'; '.join(tribunal.convergence_points)}")
        lines.append(f"DIVERGENCE: {'; '.join(tribunal.divergence_points)}")
        lines.append(f"TRIBUNAL SYNTHESIS: {tribunal.tribunal_synthesis}")

        return "\n".join(lines)
