"""
XDART-Φ × XHEART — FastAPI Server

REST API endpoints:
  POST /xdart/run          → Full framework execution
  POST /xdart/stream       → SSE streaming (phase-by-phase)
  POST /xdart/chat         → Chat mode (router decides: respond or pipeline)
  GET  /xdart/memory       → List episodic memories
  GET  /xdart/prophecies   → List all stored prophecies
  GET  /xdart/health       → Health check
  GET  /xdart/system-audit → Latest 2-hour system integrity audit
  GET  /xdart/entity-graph/vis  → Interactive entity relationship map (HTML)
  GET  /xdart/entity-graph/data → Entity graph JSON for external renderers
  GET  /                    → Web UI
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from xdart.config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    PERCEPTION_ENABLED, PERCEPTION_DB_PATH, FRED_API_KEY,
    CHARACTER_STATE_PATH, IMMEDIATE_MEMORY_PATH,
    LLM_BASE_URL, CORS_ORIGINS,
)
try:
    from xdart.config import (
        ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
        ELEVENLABS_MODEL_TTS, ELEVENLABS_MODEL_TTS_WS, ELEVENLABS_MODEL_STT,
    )
except ImportError:
    ELEVENLABS_API_KEY = ""
    ELEVENLABS_VOICE_ID = ""
    ELEVENLABS_MODEL_TTS = "eleven_v3"
    ELEVENLABS_MODEL_TTS_WS = "eleven_multilingual_v2"
    ELEVENLABS_MODEL_STT = "scribe_v2"
try:
    from xdart.config import PROACTIVE_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    PROACTIVE_ENABLED = False
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""
try:
    from xdart.config import UCDP_API_TOKEN
except ImportError:
    UCDP_API_TOKEN = ""
try:
    from xdart.config import FINNHUB_API_KEY
except ImportError:
    FINNHUB_API_KEY = ""
from xdart.core import XDARTFramework
from xdart.core_change_logger import CoreChangeLogger
from xdart.health_tracker import health_tracker
from xdart.models import ClientProfile, FrameworkOutput

logger = logging.getLogger(__name__)

# ── Request / Response models ──

class ClientProfileInput(BaseModel):
    """Client profile for the analysis — who is the decision-maker?"""
    role: str = Field(description="e.g. 'Prime Minister advisor', 'shipping company owner with 12 tankers'")
    decisions_i_make: list[str] = Field(default_factory=list)
    resources_i_control: list[str] = Field(default_factory=list)
    time_horizon: str = Field(default="")
    risk_tolerance: str = Field(default="")
    constraints: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)


class RunRequest(BaseModel):
    problem: str = Field(description="The problem or question to analyze")
    client_profile: ClientProfileInput | None = Field(
        default=None, description="Who the analysis is for (optional)"
    )


class RunResponse(BaseModel):
    # User-visible output
    problem: str
    reframed_problem: str
    final_output: str
    falsifiability: str
    layer: str
    domains_used: list[str]
    views_used: list[str]
    convergent_patterns: list[str]
    memory_count: int

    # Phase details (optional, for transparency)
    phase0_reframe: str
    phase1_strongest_analogy: str
    phase2_dominant_pattern: str

    # XHEART is NOT exposed — internal only
    # But we expose whether synthesis survived
    xheart_has_synthesis: bool


class MemoryEntry(BaseModel):
    id: str
    problem: str
    reframed_problem: str
    distillate: str
    domains: list[str]
    layer_score: float


class HealthResponse(BaseModel):
    status: str
    model: str
    memories: int
    concepts: int
    pipeline_running: bool = False
    startup_complete: bool = False


# ── App ──

_framework: XDARTFramework | None = None
_collector: object | None = None  # DataCollector — stored for intelligence endpoint
_collector_task: asyncio.Task | None = None
_consolidation_task: asyncio.Task | None = None
_proactive_engine = None  # ProactiveEngine — stored for notification endpoints
_vision_integration = None  # VisionIntegration — stored for vision endpoints
_mongo_store = None  # MongoStore — structured persistence layer
_last_audit_result: dict = {}  # Latest system audit results — populated by audit loop
_shutdown_event: asyncio.Event | None = None  # Global shutdown signal for background tasks
_briefing_engine = None  # ScheduledBriefingEngine — Palantir autonomous daily briefs
_ontology_engine = None  # OntologyEngine — Palantir Βήμα 1: typed semantic entities & relationships
_action_graph = None    # IntelligenceActionGraph — Palantir Βήμα 2: analysis→decision→action→outcome
_darkwhisper_engine = None  # DarkWhisperEngine — Palantir Dark Wing: clearnet OSINT synthesis
_telegram_intel = None       # TelegramIntelTool — Αίολος' autonomous Telegram channel ops
_startup_complete: bool = False  # True after all lifespan init completes — UI polls this


async def _send_startup_notification() -> None:
    """Fire-and-forget Telegram notification when all systems are ready.

    Sent once per server start. Helps the user know exactly when to open
    the UI instead of guessing / repeatedly refreshing.
    """
    try:
        import httpx as _httpx
        from xdart.config import TELEGRAM_BOT_TOKEN as _TBT, TELEGRAM_CHAT_ID as _TCI
        components = health_tracker.get_summary()
        healthy = sum(1 for v in components.get("components", {}).values()
                      if v.get("status") == "ok")
        total = len(components.get("components", {}))
        text = (
            f"✅ Αίολος is online and ready\n"
            f"🧠 {healthy}/{total} subsystems green\n"
            f"📡 Open http://localhost:8000 to connect"
        )
        url = f"https://api.telegram.org/bot{_TBT}/sendMessage"
        async with _httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={"chat_id": _TCI, "text": text, "parse_mode": "Markdown"})
        logger.info("[Startup] Telegram ready notification sent")
    except Exception as exc:
        logger.debug("[Startup] Telegram notification failed (non-critical): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _framework, _collector, _collector_task, _consolidation_task, _proactive_engine, _vision_integration, _mongo_store, _shutdown_event, _briefing_engine, _ontology_engine, _action_graph, _darkwhisper_engine, _startup_complete

    # ── Ensure proper logging in uvicorn reload child process ──
    import logging as _logging, sys as _sys
    if not _logging.root.handlers or all(
        getattr(h, '_name', '') == 'uvicorn' or 'uvicorn' in type(h).__module__
        for h in _logging.root.handlers
    ):
        _handler = _logging.StreamHandler(_sys.stderr)
        _handler.setFormatter(_logging.Formatter(
            fmt="%(asctime)s \u2502 %(name)-25s \u2502 %(levelname)-5s \u2502 %(message)s",
            datefmt="%H:%M:%S",
        ))
        _logging.root.addHandler(_handler)
        _logging.root.setLevel(_logging.INFO)
        _logging.getLogger("httpx").setLevel(_logging.WARNING)
        _logging.getLogger("openai").setLevel(_logging.WARNING)
        _logging.getLogger("urllib3").setLevel(_logging.WARNING)
        logger.info("[Lifespan] Logging re-initialized for reload worker")

    _shutdown_event = asyncio.Event()

    # ── Windows ProactorEventLoop WinError 10054 suppression ──────────────────
    # On Windows, when a browser closes an SSE or streaming connection, asyncio
    # fires _call_connection_lost() on an already-gone socket and raises
    # ConnectionResetError (WinError 10054). This is a spurious Python 3.12
    # Windows bug — the connection IS properly closed (you'll see "SSE subscriber
    # removed" right after). Install a custom exception handler that silently
    # drops this specific error so it doesn't flood the logs.
    def _ignore_win_connection_reset(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        handle = context.get("handle")
        handle_repr = repr(handle) if handle else ""
        if (
            isinstance(exc, ConnectionResetError)
            and "_call_connection_lost" in handle_repr
        ):
            return  # safe to ignore — socket is already gone
        loop.default_exception_handler(context)

    asyncio.get_running_loop().set_exception_handler(_ignore_win_connection_reset)
    logger.info("[Lifespan] Windows WinError-10054 asyncio exception handler installed")

    # ── Expand default thread pool to prevent executor starvation ──
    # Background tasks (LLM calls ~30-60s each, NER, sub-agents, curiosity,
    # reflection, sandbox) compete with HTTP handlers for threads.
    # Default is min(32, cpu+4) ≈ 8-12 threads — easily exhausted when
    # 10+ concurrent LLM calls are in flight.
    _expanded_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=40, thread_name_prefix="xdart",
    )
    asyncio.get_running_loop().set_default_executor(_expanded_executor)
    logger.info("[Lifespan] Default thread pool expanded to 40 workers")

    # Pre-warm fastembed model in background so first embed call doesn't freeze
    try:
        from xdart.config import LOCAL_EMBEDDING_ENABLED as _LEE
        from xdart.llm import prewarm_local_embed as _prewarm
        if _LEE:
            asyncio.get_running_loop().run_in_executor(_expanded_executor, _prewarm)
            logger.info("[Lifespan] fastembed prewarm started in background thread")
    except Exception as _e:
        logger.warning("[Lifespan] fastembed prewarm setup failed: %s", _e)

    _framework = XDARTFramework()

    # ── MongoDB Structured Persistence ──
    _mongo_store = None
    try:
        from xdart.knowledge.mongo import MongoStore
        from xdart.config import MONGO_URI, MONGO_DB_NAME
        _mongo_store = MongoStore(uri=MONGO_URI, db_name=MONGO_DB_NAME)
        if _mongo_store.available:
            _framework._mongo = _mongo_store
            # Wire MongoDB into all subsystems of the framework
            if hasattr(_framework, 'curiosity_engine') and _framework.curiosity_engine:
                _framework.curiosity_engine._mongo = _mongo_store
            if hasattr(_framework, 'introspection') and _framework.introspection:
                _framework.introspection._mongo = _mongo_store
            if hasattr(_framework, 'self_evolution') and _framework.self_evolution:
                _framework.self_evolution._mongo = _mongo_store
            if hasattr(_framework, 'logic_sandbox') and _framework.logic_sandbox:
                _framework.logic_sandbox._mongo = _mongo_store
            # Wire LLM into MongoStore for creative imagination cycles
            _mongo_store._llm = _framework.llm
            logger.info("MongoDB connected — db=%s", MONGO_DB_NAME)
            health_tracker.record_startup("MongoDB", True, f"connected to {MONGO_DB_NAME}")
        else:
            logger.warning("MongoDB unavailable — running without database")
            health_tracker.record_startup("MongoDB", False, "unavailable")
    except Exception as e:
        logger.warning("MongoDB init failed (continuing without): %s", e)
        health_tracker.record_startup("MongoDB", False, str(e))

    # ── Initialize Proactive Communication Engine ──
    _proactive_task = None
    if PROACTIVE_ENABLED and _framework:
        try:
            from xdart.proactive import ProactiveEngine, ProactiveDigestLoop
            from xdart.config import PROACTIVE_LOG_PATH
            _proactive_engine = ProactiveEngine(
                llm=_framework.llm,
                telegram_bot_token=TELEGRAM_BOT_TOKEN,
                telegram_chat_id=TELEGRAM_CHAT_ID,
                web_agent=_framework.web_agent,  # auto-research capability
                log_path=Path(PROACTIVE_LOG_PATH),
            )
            # Wire proactive engine into framework for pipeline awareness
            _framework._proactive_engine = _proactive_engine
            # Set main event loop reference for thread-safe SSE delivery
            _proactive_engine._main_loop = asyncio.get_running_loop()
            # Wire proactive engine into WakeupProtocol so Αίολος sees pending
            # notification batch during chat (even before 10-item flush threshold)
            if hasattr(_framework, "wakeup") and _framework.wakeup:
                _framework.wakeup.proactive_engine = _proactive_engine
                logger.info("Proactive engine wired into WakeupProtocol (pending batch visible in chat)")
            # Wire prophetic memory for autonomous prophecy generation
            if hasattr(_framework, 'prophetic_memory') and _framework.prophetic_memory:
                _proactive_engine.prophetic_memory = _framework.prophetic_memory
            # Start daily digest loop
            digest_loop = ProactiveDigestLoop(
                engine=_proactive_engine,
                llm=_framework.llm,
            )
            _proactive_task = asyncio.create_task(digest_loop.run_forever())

            # Start periodic batch flush loop (every 30 min — flushes buffer even if < 10)
            async def _batch_flush_loop():
                """Flush pending notification batch every 30 min regardless of batch size."""
                while not _shutdown_event.is_set():
                    try:
                        await asyncio.sleep(1800)  # 30 minutes
                        if _proactive_engine is None:
                            continue
                        with _proactive_engine._notif_batch_lock:
                            pending = len(_proactive_engine._notif_batch)
                        if pending > 0:
                            logger.info(
                                "[Proactive] Periodic batch flush triggered (%d pending notifications)",
                                pending,
                            )
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(
                                None, _proactive_engine._flush_notification_batch
                            )
                    except asyncio.CancelledError:
                        break
                    except Exception as exc:
                        logger.warning("[Proactive] Batch flush loop error: %s", exc)

            asyncio.create_task(_batch_flush_loop())
            logger.info("Proactive engine started (telegram=%s, batch_flush_interval=30min)",
                        "yes" if TELEGRAM_BOT_TOKEN else "no")
            health_tracker.record_startup("ProactiveEngine", True)
        except Exception as e:
            logger.warning("Proactive engine failed to start: %s", e)
            health_tracker.record_startup("ProactiveEngine", False, str(e))

    # ── Domain-to-signal-type mapping for pattern diversity ──
    _DOMAIN_SIGNAL_MAP = {
        "ECONOMIC": "economic_shift",
        "ECONOMY": "economic_shift",
        "FINANCIAL": "financial_anomaly",
        "SECURITY": "security_event",
        "MILITARY": "security_event",
        "SOCIAL": "social_disruption",
        "TECHNOLOGY": "tech_disruption",
        "CYBER": "tech_disruption",
        "GEOPOLITICS": "perception_event",
        "ENERGY": "economic_shift",
        "HUMANITARIAN": "social_disruption",
    }

    # ── Shared alert handler for all perception sources (text, financial, multimodal) ──
    def _proactive_alert_handler(events: list[dict]):
        """Triggered when any collector detects high-salience events.
        Feeds each event into the PatternAccumulator as a signal.
        Patterns fire autonomously when convergence ≥ 0.50.

        Uses domain-balanced selection to prevent geopolitical dominance:
        instead of taking the first 25 events (which may all be geopolitical),
        we take up to 8 per domain, ensuring economic/market/tech/social
        events get through even when geopolitical headlines dominate.
        """
        if not _framework:
            return
        try:
            logger.info("[ProactiveAlert] %d high-salience events detected", len(events))

            if _proactive_engine:
                # Domain-balanced selection: max 8 per domain, total max 40
                MAX_PER_DOMAIN = 8
                MAX_TOTAL = 40
                by_domain: dict[str, list[dict]] = {}
                for ev in events:
                    domain = (ev.get("domain") or "MULTI").upper()
                    by_domain.setdefault(domain, []).append(ev)

                selected: list[dict] = []
                for domain, domain_events in by_domain.items():
                    selected.extend(domain_events[:MAX_PER_DOMAIN])

                # Sort by salience within the balanced set
                selected.sort(key=lambda e: e.get("salience", 0), reverse=True)
                selected = selected[:MAX_TOTAL]

                domain_counts = {}
                for ev in selected:
                    d = (ev.get("domain") or "MULTI").upper()
                    domain_counts[d] = domain_counts.get(d, 0) + 1
                logger.info("[ProactiveAlert] Domain-balanced: %s", domain_counts)

                for ev in selected:
                    raw_region = ev.get("region", "GLOBAL")
                    if isinstance(raw_region, list):
                        raw_region = raw_region[0] if raw_region else "GLOBAL"
                    # Use explicit signal_type if set, otherwise derive from domain
                    signal_type = ev.get("signal_type", "")
                    if not signal_type or signal_type == "perception_alert":
                        domain = ev.get("domain", "").upper()
                        signal_type = _DOMAIN_SIGNAL_MAP.get(domain, "perception_alert")
                    _proactive_engine.feed_signal(
                        source_type=signal_type,
                        headline=ev.get("headline", ""),
                        region=raw_region,
                        raw_data={
                            "source": ev.get("source", ""),
                            "domain": ev.get("domain", ""),
                            "salience": ev.get("salience", 0),
                        },
                    )
            else:
                logger.info("[ProactiveAlert] Engine not active — logged %d events",
                            len(events))
        except Exception as exc:
            logger.warning("[ProactiveAlert] Handler failed: %s", exc)
            health_tracker.record_error("ProactiveAlert", f"Handler failed: {exc}", exc)

    # Start background perception collector if enabled
    # Pre-initialize so Python doesn't treat them as unbound locals when DataCollector
    # references them below (they are fully assigned later in this startup sequence).
    _multimodal_collector = None
    _cross_system_loop = None
    if PERCEPTION_ENABLED:
        try:
            from xdart.perception import DataCollector, PerceptionDB, PerceptionFilter
            perception_db = PerceptionDB(db_path=PERCEPTION_DB_PATH)
            perception_filter = PerceptionFilter()

            # ── Entity Knowledge Graph (NER + relationship intelligence) ──
            entity_graph = None
            try:
                from xdart.knowledge.entity_graph import EntityGraph
                entity_graph_path = Path(PERCEPTION_DB_PATH).parent / "entity_graph.json"
                entity_graph = EntityGraph(persist_path=entity_graph_path)
                logger.info("Entity Knowledge Graph initialized (%d nodes, %d edges)",
                            entity_graph.node_count, entity_graph.edge_count)
                health_tracker.record_startup("EntityGraph", True, f"{entity_graph.node_count} nodes")
                # Wire MongoDB for dual-write
                if _mongo_store and _mongo_store.available:
                    entity_graph._mongo = _mongo_store
                    # Import existing JSON graph into MongoDB on first run
                    if entity_graph_path.exists() and _mongo_store.entity_stats().get("total_entities", 0) == 0:
                        try:
                            import json as _json
                            _graph_data = _json.loads(entity_graph_path.read_text(encoding="utf-8"))
                            _imported = _mongo_store.import_entity_graph_from_json(_graph_data)
                            logger.info("Entity graph imported to MongoDB: %d entities", _imported)
                        except Exception as _ie:
                            logger.warning("Entity graph MongoDB import failed: %s", _ie)
            except Exception as e:
                logger.warning("Entity graph init failed (continuing without): %s", e)
                health_tracker.record_startup("EntityGraph", False, str(e))

            # ── Financial Market Collector (VIX, S&P500, Oil, Gold, BTC, etc.) ──
            market_collector = None
            try:
                from xdart.perception.financial_feeds import MarketDataCollector
                market_collector = MarketDataCollector()
                logger.info("Financial market collector initialized (%d tickers)",
                            len(market_collector._history) or 8)
                health_tracker.record_startup("FinancialFeeds", True)
            except Exception as e:
                logger.warning("Financial feeds init failed (continuing without): %s", e)
                health_tracker.record_startup("FinancialFeeds", False, str(e))

            # Wire entity graph + market collector into ProactiveEngine
            if _proactive_engine:
                _proactive_engine.entity_graph = entity_graph
                _proactive_engine.market_collector = market_collector
                if _mongo_store and _mongo_store.available:
                    _proactive_engine._mongo = _mongo_store
                    # Wire mongo into Affect Layer for affective trace persistence
                    try:
                        _proactive_engine._affect_layer.affective_memory._mongo = _mongo_store
                        logger.info("Affect Layer wired to MongoDB (affect_traces collection)")
                        health_tracker.record_startup(
                            "AffectHeuristicLayer",
                            True,
                            "active — dedup(30min/0.85) + scorer(5-dim) + balance + affective_memory(MongoDB)",
                        )
                    except Exception as _al_exc:
                        logger.debug("Affect Layer mongo wire failed (non-critical): %s", _al_exc)
                        health_tracker.record_startup(
                            "AffectHeuristicLayer",
                            True,
                            "active — dedup + scorer + balance (affective_memory in-memory only, MongoDB wire failed)",
                        )

            # Wire into framework for chat mode access
            if _framework:
                _framework._entity_graph = entity_graph
                _framework._market_collector = market_collector

            # ── Typed Semantic Ontology (Palantir Βήμα 1) ──
            try:
                from xdart.intelligence.ontology import OntologyEngine
                from xdart.knowledge.entity_graph import _KNOWN_ENTITIES
                _ontology_engine = OntologyEngine(
                    entity_graph=entity_graph,
                    mongo=_mongo_store if _mongo_store and _mongo_store.available else None,
                    persist_path=Path(PERCEPTION_DB_PATH).parent,
                    known_entity_names=set(_KNOWN_ENTITIES.keys()),
                )
                _ontology_engine.start()
                logger.info(
                    "Typed Semantic Ontology initialized (%d entities, %d relationships)",
                    len(_ontology_engine._entities), len(_ontology_engine._relationships),
                )
                health_tracker.record_startup("OntologyEngine", True,
                                              f"{len(_ontology_engine._entities)} entities")
                # Wire into framework for chat context injection
                if _framework:
                    _framework._ontology_engine = _ontology_engine
            except Exception as _oe:
                logger.warning("Ontology engine init failed (continuing without): %s", _oe)
                health_tracker.record_startup("OntologyEngine", False, str(_oe))

            collector = DataCollector(
                db=perception_db,
                filter_layer=perception_filter,
                fred_api_key=FRED_API_KEY,
                ucdp_api_token=UCDP_API_TOKEN,
                finnhub_api_key=FINNHUB_API_KEY,
                on_alert=_proactive_alert_handler,
                entity_graph=entity_graph,
                market_collector=market_collector,
                multimodal_collector=_multimodal_collector,
                cross_system_runner=_cross_system_loop,
            )
            _collector = collector  # store reference for intelligence endpoint
            _collector_task = asyncio.create_task(collector.run_forever())
            # Wire spike detector into framework for context injection
            if _framework:
                _framework._spike_detector = collector.spike_detector
            # Wire PerceptionDB into ProactiveEngine for auto-research storage
            if _proactive_engine:
                _proactive_engine.perception_db = perception_db
            logger.info("Perception collector started as background task")
            health_tracker.record_startup("PerceptionCollector", True)
        except Exception as e:
            logger.warning("Perception collector failed to start: %s", e)
            health_tracker.record_startup("PerceptionCollector", False, str(e))

    # NOTE: Memory consolidation loop is started AFTER the vision system block
    # so that _vision_integration is available when the loop is created.
    # See "Start background memory consolidation loop" block below the vision init.

    # Start background Logic Sandbox maintenance loop (every 30 min)
    _sandbox_maintenance_task = None
    try:
        if _framework and _framework.logic_sandbox:
            async def _sandbox_maintenance_loop():
                """Periodically test+deploy pending sandbox proposals."""
                await asyncio.sleep(180)  # 3 min initial delay — let system boot
                while True:
                    try:
                        sandbox = _framework.logic_sandbox
                        # 1. Deploy any proposals that passed testing but were never approved
                        deployed = await asyncio.get_event_loop().run_in_executor(
                            None, sandbox.deploy_pending_proposals,
                        )
                        if deployed:
                            logger.info(
                                "[SandboxMaint] Deployed %d stale proposals: %s",
                                len(deployed),
                                ", ".join(d.get("function_id", "?") for d in deployed),
                            )

                        # 2. Test any proposals still in "pending" status
                        pending = [
                            (pid, p) for pid, p in sandbox._proposals.items()
                            if p.status == "pending"
                        ]
                        for proposal_id, proposal in pending:
                            try:
                                test_result = await asyncio.get_event_loop().run_in_executor(
                                    None, sandbox.test_proposal, proposal_id,
                                )
                                if test_result.get("all_passed"):
                                    approve_result = await asyncio.get_event_loop().run_in_executor(
                                        None,
                                        lambda pid=proposal_id: sandbox.approve_proposal(
                                            pid, approved_by="auto_maintenance",
                                        ),
                                    )
                                    if approve_result.get("status") == "approved":
                                        apply_result = await asyncio.get_event_loop().run_in_executor(
                                            None, sandbox.apply_proposal, proposal_id,
                                        )
                                        logger.info(
                                            "[SandboxMaint] ✓ AUTO-DEPLOYED %s for %s (maintenance cycle)",
                                            proposal_id[:12], proposal.function_id,
                                        )
                                else:
                                    # Failed sandbox tests — reject to unblock
                                    await asyncio.get_event_loop().run_in_executor(
                                        None,
                                        lambda pid=proposal_id: sandbox.reject_proposal(
                                            pid, reason="Auto-rejected: sandbox tests failed in maintenance",
                                        ),
                                    )
                                    logger.info(
                                        "[SandboxMaint] ✗ Rejected %s for %s (tests failed)",
                                        proposal_id[:12], proposal.function_id,
                                    )
                            except Exception as exc:
                                logger.warning(
                                    "[SandboxMaint] Error processing proposal %s: %s",
                                    proposal_id[:12], exc,
                                )
                    except Exception as exc:
                        logger.warning("[SandboxMaint] Maintenance cycle failed: %s", exc)
                        health_tracker.record_error("LogicSandbox", f"Maintenance cycle failed: {exc}", exc)

                    await asyncio.sleep(30 * 60)  # Every 30 minutes

            _sandbox_maintenance_task = asyncio.create_task(_sandbox_maintenance_loop())
            logger.info("Logic Sandbox maintenance loop started (30min interval)")
            health_tracker.record_startup("LogicSandbox", True)
    except Exception as e:
        logger.warning("Logic Sandbox maintenance loop failed to start: %s", e)
        health_tracker.record_startup("LogicSandbox", False, str(e))

    # Start background prophecy resolution loop (every 6 hours)
    _resolver_task = None
    try:
        async def _prophecy_resolution_loop():
            """Check prophecy deadlines — runs once on startup then every 6 hours."""
            # Initial delay: let the system fully boot (2 min)
            await asyncio.sleep(120)
            while True:
                if _framework and _framework.prophecy_resolver:
                    try:
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, _framework.prophecy_resolver.resolve_all,
                        )
                        logger.info(
                            "[ProphecyResolver] Background run: %d resolved (confirmed=%d, disconfirmed=%d)",
                            result.get("resolved_this_run", 0),
                            result.get("confirmed", 0),
                            result.get("disconfirmed", 0),
                        )
                        # Feed prophecy resolution into pattern accumulator
                        resolved_count = result.get("resolved_this_run", 0)
                        if resolved_count > 0 and _proactive_engine:
                            confirmed = result.get("confirmed", 0)
                            disconfirmed = result.get("disconfirmed", 0)
                            await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: _proactive_engine.feed_signal(
                                    source_type="prophecy_resolved",
                                    headline=f"Prophecy grounding: {resolved_count} resolved "
                                             f"({confirmed} confirmed, {disconfirmed} disconfirmed)",
                                    region="GLOBAL",
                                    raw_data={
                                        "resolved_count": resolved_count,
                                        "confirmed": confirmed,
                                        "disconfirmed": disconfirmed,
                                        "details": result.get("details", [])[:5],
                                    },
                                ),
                            )
                    except Exception as exc:
                        logger.warning("[ProphecyResolver] Background run failed: %s", exc)
                        health_tracker.record_error("ProphecyResolver", f"Background run failed: {exc}", exc)
                await asyncio.sleep(6 * 3600)  # Then every 6 hours

        _resolver_task = asyncio.create_task(_prophecy_resolution_loop())
        logger.info("Prophecy resolution loop started (6h interval)")
        health_tracker.record_startup("ProphecyResolver", True)
    except Exception as e:
        logger.warning("Prophecy resolution loop failed to start: %s", e)
        health_tracker.record_startup("ProphecyResolver", False, str(e))

    # Start background curiosity loop (autonomous exploration every 15 min)
    _curiosity_task = None
    if _framework and _framework.curiosity_engine:
        try:
            from xdart.phases.curiosity import CuriosityLoop

            # Get perception DB if available
            _perception_db = None
            if PERCEPTION_ENABLED:
                try:
                    from xdart.perception import PerceptionDB
                    _perception_db = PerceptionDB(db_path=PERCEPTION_DB_PATH)
                except Exception:
                    pass

            # Get web search function if available (sync wrapper for async web_search)
            _main_loop = asyncio.get_running_loop()
            _framework._async_loop = _main_loop  # Store for core.py threads

            _web_fn = None
            if _framework.web_agent:
                _wa = _framework.web_agent

                def _web_fn(query, max_results=5):
                    """Sync wrapper: schedules async web_search on the main loop."""
                    coro = _wa.web_search(query, max_results=max_results)
                    future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
                    result = future.result(timeout=60)
                    return result.get("results", [])

            # ── Curiosity notification wrapper ──
            # Curiosity findings must bypass PatternAccumulator (which requires
            # convergence ≥ 0.50 from multiple signals — a single curiosity
            # finding never crosses that gate). Route directly to evaluate_and_notify.
            _curiosity_notify_fn = None
            if _proactive_engine:
                def _curiosity_notify_fn(source_type="curiosity_finding", headline="",
                                         region="GLOBAL", raw_data=None):
                    """Direct notification for curiosity findings — bypasses PatternAccumulator."""
                    _proactive_engine.evaluate_and_notify(
                        event_type=source_type,
                        event_data={
                            "headlines": [headline],
                            "region": region,
                            **(raw_data or {}),
                        },
                        context=f"Autonomous curiosity finding: {headline}",
                    )

            curiosity_loop = CuriosityLoop(
                engine=_framework.curiosity_engine,
                perception_db=_perception_db,
                web_search_fn=_web_fn,
                character_path=CHARACTER_STATE_PATH,
                apply_changes_fn=_framework._apply_curiosity_changes,
                proactive_notify_fn=_curiosity_notify_fn,
                conversation_request_fn=(
                    _proactive_engine.request_conversation if _proactive_engine else None
                ),
                interval_minutes=30,
            )
            _curiosity_task = asyncio.create_task(curiosity_loop.run_forever())
            logger.info("Curiosity loop started (30min interval, web=%s, perception=%s)",
                        "yes" if _web_fn else "no",
                        "yes" if _perception_db else "no")
            health_tracker.record_startup("CuriosityLoop", True)
        except Exception as e:
            logger.warning("Curiosity loop failed to start: %s", e)
            health_tracker.record_startup("CuriosityLoop", False, str(e))

    # ── Shared memory store function for background subsystems ──
    # Routes to SemanticMemory.store_truth() → embeds in Qdrant
    def _background_memory_store(layer: str = "semantic", content: str = "",
                                 tags: list[str] | None = None, **_kwargs):
        """Store findings from background loops into Qdrant semantic memory."""
        if not _framework or not content:
            return
        try:
            if layer == "semantic" and hasattr(_framework, 'semantic_memory'):
                source = ",".join(tags[:3]) if tags else "background"
                _framework.semantic_memory.store_truth(
                    knowledge=content,
                    confidence=0.75,
                    source=source,
                )
                logger.info("[BackgroundMemory] Stored %d chars to semantic (tags=%s)",
                            len(content), tags)
        except Exception as exc:
            logger.warning("[BackgroundMemory] Store failed: %s", exc)
            health_tracker.record_error("BackgroundMemory", f"Store failed: {exc}", exc)

    # ── Create multimodal collector (wired INTO main perception cycle, not standalone) ──
    _multimodal_collector = None
    try:
        from xdart.config import MULTIMODAL_ENABLED, OPENSKY_USER, OPENSKY_PASS, FIRMS_MAP_KEY, MARINETRAFFIC_API_KEY
    except ImportError:
        MULTIMODAL_ENABLED = False
        OPENSKY_USER = OPENSKY_PASS = FIRMS_MAP_KEY = MARINETRAFFIC_API_KEY = ""

    if MULTIMODAL_ENABLED and PERCEPTION_ENABLED:
        try:
            from xdart.perception.multimodal import MultimodalCollector
            _multimodal_collector = MultimodalCollector(
                on_alert=_proactive_alert_handler,
                opensky_user=OPENSKY_USER,
                opensky_pass=OPENSKY_PASS,
                firms_map_key=FIRMS_MAP_KEY,
                marinetraffic_api_key=MARINETRAFFIC_API_KEY,
                entity_graph=getattr(_framework, '_entity_graph', None) if _framework else None,
                memory_store_fn=_background_memory_store,
            )
            if _framework:
                _framework._multimodal_collector = _multimodal_collector
            # Wire into already-running DataCollector (started before this block)
            if _collector:
                _collector.multimodal_collector = _multimodal_collector
            # Wire into ProactiveEngine so digest loop can access live sensor data
            if _proactive_engine:
                _proactive_engine._multimodal_collector = _multimodal_collector
            logger.info("Multimodal OSINT created (airspace=%s, satellite=%s, maritime=yes) — runs every perception cycle",
                        "auth" if OPENSKY_USER else "anon",
                        "yes" if FIRMS_MAP_KEY else "no")
            health_tracker.record_startup("MultimodalOSINT", True)
        except Exception as e:
            logger.warning("Multimodal perception failed to init: %s", e)
            health_tracker.record_startup("MultimodalOSINT", False, str(e))

    # ══════════════════════════════════════════════════════════════════
    #  PALANTIR P0: Real-Time Intelligence Feeds + Sanctions + Calendar
    # ══════════════════════════════════════════════════════════════════

    # ── Real-Time Feeds (Finnhub forex + Cyber Threats + Airspace Warnings) ──
    _realtime_feeds = None
    try:
        from xdart.config import OTX_API_KEY, GREYNOISE_API_KEY
    except ImportError:
        OTX_API_KEY = GREYNOISE_API_KEY = ""

    try:
        from xdart.perception.realtime_feeds import RealtimeFeedManager
        _realtime_feeds = RealtimeFeedManager(
            finnhub_api_key=FINNHUB_API_KEY,
            otx_api_key=OTX_API_KEY,
            greynoise_api_key=GREYNOISE_API_KEY,
        )
        if _proactive_engine:
            _proactive_engine._realtime_feeds = _realtime_feeds
        # Wire into already-running DataCollector
        if _collector:
            _collector.realtime_feeds = _realtime_feeds
        # Wire realtime digest into multimodal collector's external sections
        if _multimodal_collector and _realtime_feeds:
            _multimodal_collector._external_digest_sections.append(
                _realtime_feeds.get_realtime_digest
            )
        logger.info("Real-Time Feeds initialized (finnhub=%s, otx=%s, greynoise=%s)",
                    "yes" if FINNHUB_API_KEY else "no",
                    "yes" if OTX_API_KEY else "no",
                    "yes" if GREYNOISE_API_KEY else "no")
        health_tracker.record_startup("RealtimeFeeds", True)
    except Exception as e:
        logger.warning("Real-Time Feeds failed to init: %s", e)
        health_tracker.record_startup("RealtimeFeeds", False, str(e))

    # ── Sanctions Cross-Reference Engine (OFAC + EU + UN) ──
    _sanctions_registry = None
    try:
        from xdart.config import SANCTIONS_ENABLED
    except ImportError:
        SANCTIONS_ENABLED = True

    if SANCTIONS_ENABLED:
        try:
            from xdart.knowledge.sanctions import SanctionsRegistry
            _sanctions_registry = SanctionsRegistry()
            if _framework:
                _framework._sanctions_registry = _sanctions_registry
            if _proactive_engine:
                _proactive_engine._sanctions_registry = _sanctions_registry
            # Wire sanctions digest into multimodal collector's external sections
            if _multimodal_collector and _sanctions_registry:
                _multimodal_collector._external_digest_sections.append(
                    _sanctions_registry.get_sanctions_digest
                )

            # Start async refresh task (downloads lists on first run)
            async def _sanctions_refresh_loop():
                """Refresh sanctions lists every 24h."""
                await asyncio.sleep(30)  # 30s initial delay
                while True:
                    try:
                        await _sanctions_registry.refresh()
                        # Cross-reference against EntityGraph entities
                        if _framework and hasattr(_framework, '_entity_graph') and _framework._entity_graph:
                            try:
                                all_entities = list(_framework._entity_graph._graph.nodes)[:5000]
                                new_matches = _sanctions_registry.cross_reference_entities(all_entities)
                                if new_matches:
                                    logger.info("[Sanctions] %d new entity matches found", len(new_matches))
                                    # Feed matches as signals
                                    if _proactive_engine:
                                        for signal in _sanctions_registry.get_match_signals()[:10]:
                                            _proactive_engine.feed_signal(
                                                source_type="sanctions_match",
                                                headline=signal["headline"],
                                                region=signal.get("region", "GLOBAL"),
                                                raw_data=signal.get("data"),
                                            )
                            except Exception as e:
                                logger.debug("[Sanctions] Entity cross-ref failed: %s", e)
                    except Exception as e:
                        logger.warning("[Sanctions] Refresh failed: %s", e)
                    await asyncio.sleep(86400)  # 24h

            _sanctions_task = asyncio.create_task(_sanctions_refresh_loop())
            logger.info("Sanctions Registry initialized (OFAC + EU + UN auto-download)")
            health_tracker.record_startup("SanctionsRegistry", True)
        except Exception as e:
            logger.warning("Sanctions Registry failed to init: %s", e)
            health_tracker.record_startup("SanctionsRegistry", False, str(e))

    # ── Geopolitical Event Calendar ──
    _event_calendar = None
    try:
        from xdart.config import EVENT_CALENDAR_ENABLED
    except ImportError:
        EVENT_CALENDAR_ENABLED = True

    if EVENT_CALENDAR_ENABLED:
        try:
            from xdart.knowledge.event_calendar import GeopoliticalCalendar
            _event_calendar = GeopoliticalCalendar()
            if _framework:
                _framework._event_calendar = _event_calendar
            if _proactive_engine:
                _proactive_engine._event_calendar = _event_calendar
            # Wire calendar digest into multimodal collector's external sections
            if _multimodal_collector and _event_calendar:
                _multimodal_collector._external_digest_sections.append(
                    _event_calendar.get_calendar_digest
                )

            # Start calendar proximity check loop
            async def _calendar_check_loop():
                """Check for approaching events every hour."""
                await asyncio.sleep(60)  # 1 min initial delay
                while True:
                    try:
                        # Generate proximity signals
                        signals = _event_calendar.get_proximity_signals()
                        if signals and _proactive_engine:
                            for sig in signals:
                                _proactive_engine.feed_signal(
                                    source_type="calendar_proximity",
                                    headline=sig["headline"],
                                    region=sig.get("region", "GLOBAL"),
                                    raw_data=sig.get("data"),
                                )
                                logger.info("[Calendar] Proximity alert: %s", sig["headline"])
                    except Exception as e:
                        logger.warning("[Calendar] Check failed: %s", e)
                    await asyncio.sleep(3600)  # 1 hour

            _calendar_task = asyncio.create_task(_calendar_check_loop())
            upcoming = _event_calendar.get_upcoming_events(14)
            logger.info("Event Calendar initialized (%d curated, %d upcoming in 14d)",
                        len(_event_calendar._curated_events), len(upcoming))
            health_tracker.record_startup("EventCalendar", True)
        except Exception as e:
            logger.warning("Event Calendar failed to init: %s", e)
            health_tracker.record_startup("EventCalendar", False, str(e))

    # ── Temporal Reasoning Engine (P3 — recurring pattern learning) ──
    _temporal_engine = None
    try:
        from xdart.phases.temporal_reasoning import TemporalReasoningEngine
        _temporal_engine = TemporalReasoningEngine(
            llm=_framework.llm if _framework else None,
            calendar=_event_calendar,
        )
        # Wire perception DB (get from proactive engine if available)
        _pdb = getattr(_proactive_engine, "perception_db", None) if _proactive_engine else None
        if _pdb:
            _temporal_engine.perception_db = _pdb
        # Wire entity graph (stored on framework)
        if _framework and getattr(_framework, "_entity_graph", None):
            _temporal_engine.entity_graph = _framework._entity_graph
        # Wire into framework
        if _framework:
            _framework._temporal_engine = _temporal_engine
        # Wire into proactive engine
        if _proactive_engine:
            _proactive_engine._temporal_engine = _temporal_engine

        # Background loop: periodic temporal checks (every 2 hours)
        async def _temporal_check_loop():
            """Record event-window observations and check precursors."""
            await asyncio.sleep(300)  # 5 min initial delay
            while True:
                try:
                    loop = asyncio.get_running_loop()
                    results = await loop.run_in_executor(
                        None, _temporal_engine.periodic_check,
                    )
                    obs = results.get("observations_recorded", 0)
                    alerts = results.get("precursor_alerts", [])
                    seqs = results.get("sequences_active", 0)
                    if obs or alerts:
                        logger.info(
                            "[Temporal] Periodic check: %d obs recorded, "
                            "%d precursor alerts, %d active sequences",
                            obs, len(alerts), seqs,
                        )
                    # Feed precursor alerts to proactive engine
                    if alerts and _proactive_engine:
                        for alert in alerts:
                            _proactive_engine.feed_signal(
                                source_type="temporal_precursor",
                                headline=(
                                    f"TEMPORAL PATTERN: {alert['event_name']} in "
                                    f"{alert['days_until']}d — {alert.get('pattern_description', 'pattern match')}"
                                ),
                                region="GLOBAL",
                                raw_data=alert,
                            )
                except Exception as e:
                    logger.warning("[Temporal] Periodic check failed: %s", e)
                await asyncio.sleep(7200)  # 2 hours

        _temporal_task = asyncio.create_task(_temporal_check_loop())

        stats = _temporal_engine.stats()
        logger.info(
            "Temporal Reasoning Engine initialized (%d patterns, %d mature, %d observations)",
            stats["total_patterns"], stats["mature_patterns"], stats["total_observations"],
        )
        health_tracker.record_startup("TemporalReasoning", True)
    except Exception as e:
        logger.warning("Temporal Reasoning Engine failed to init: %s", e)
        health_tracker.record_startup("TemporalReasoning", False, str(e))

    # ── Create cross-system learning (wired INTO hourly perception cycle, not standalone) ──
    _cross_system_loop = None
    try:
        from xdart.config import CROSS_SYSTEM_LEARNING_ENABLED, CORE_API_KEY, S2_API_KEY
    except ImportError:
        CROSS_SYSTEM_LEARNING_ENABLED = False
        CORE_API_KEY = ""
        S2_API_KEY = ""

    if CROSS_SYSTEM_LEARNING_ENABLED and _framework:
        try:
            from xdart.knowledge.cross_system_learning import CrossSystemLearner, CrossSystemLearningLoop
            _cross_system_learner = CrossSystemLearner(
                llm=_framework.llm,
                core_api_key=CORE_API_KEY,
                s2_api_key=S2_API_KEY,
                proactive_notify_fn=(
                    _proactive_engine.feed_signal if _proactive_engine else None
                ),
                conversation_request_fn=(
                    _proactive_engine.request_conversation if _proactive_engine else None
                ),
                memory_store_fn=_background_memory_store,
                cache_path=str(Path(PERCEPTION_DB_PATH).parent / "cross_system_cache.json"),
            )
            _cross_system_loop = CrossSystemLearningLoop(
                learner=_cross_system_learner,
                curiosity_engine=_framework.curiosity_engine if hasattr(_framework, 'curiosity_engine') else None,
                proactive_engine=_proactive_engine,
                interval_hours=1,
            )
            if _framework:
                _framework._cross_system_learner = _cross_system_learner
            # Wire into already-running DataCollector (started before this block)
            if _collector:
                _collector.cross_system_runner = _cross_system_loop
            logger.info("Cross-system learning created (core=%s, openalex=free) — runs every hourly cycle",
                        "key" if CORE_API_KEY else "unauth")
            health_tracker.record_startup("CrossSystemLearning", True)
        except Exception as e:
            logger.warning("Cross-system learning failed to init: %s", e)
            health_tracker.record_startup("CrossSystemLearning", False, str(e))

    # ── Vision System (Αίολος' Eyes) — face detection + recognition ──
    try:
        from xdart.config import VISION_ENABLED, VISION_PRESENCE_COOLDOWN
    except ImportError:
        VISION_ENABLED = False
        VISION_PRESENCE_COOLDOWN = 300

    if VISION_ENABLED:
        try:
            from xdart.vision.integration import VisionIntegration
            _vision_integration = VisionIntegration(
                proactive_engine=_proactive_engine,
                entity_graph=getattr(_framework, '_entity_graph', None),
                presence_cooldown=VISION_PRESENCE_COOLDOWN,
                llm=getattr(_framework, 'llm', None),
                curiosity_engine=getattr(_framework, 'curiosity_engine', None),
                episodic_memory=getattr(_framework, 'memory', None),
                semantic_memory=getattr(_framework, 'semantic_memory', None),
                wisdom_tracker=getattr(_framework, 'wisdom_tracker', None),
            )
            if _framework:
                _framework._vision_integration = _vision_integration
            if _mongo_store and _mongo_store.available:
                _vision_integration._mongo = _mongo_store
            logger.info("Vision integration initialized (cooldown=%ds, llm=%s, curiosity=%s, "
                        "episodic=%s, semantic=%s, wisdom=%s)",
                        VISION_PRESENCE_COOLDOWN,
                        "yes" if getattr(_framework, 'llm', None) else "no",
                        "yes" if getattr(_framework, 'curiosity_engine', None) else "no",
                        "yes" if getattr(_framework, 'memory', None) else "no",
                        "yes" if getattr(_framework, 'semantic_memory', None) else "no",
                        "yes" if getattr(_framework, 'wisdom_tracker', None) else "no")
            health_tracker.record_startup("VisionIntegration", True)
        except Exception as e:
            logger.warning("Vision integration failed to initialize: %s", e)
            health_tracker.record_startup("VisionIntegration", False, str(e))

    # Start background memory consolidation loop (sleep process)
    # Placed AFTER vision init so _vision_integration is available
    try:
        from xdart.phases.consolidation import MemoryConsolidationLoop
        consolidation = MemoryConsolidationLoop(
            llm=_framework.llm,
            episodic_memory=_framework.memory,
            semantic_memory=_framework.semantic_memory,
            procedural_memory=_framework.procedural_memory,
            prophetic_memory=_framework.prophetic_memory,
            interval_minutes=30,
            vision_integration=_vision_integration,
        )
        # Wire MongoDB for imagination cycles
        if _mongo_store and _mongo_store.available:
            consolidation._mongo = _mongo_store
        _consolidation_task = asyncio.create_task(consolidation.run_forever())
        logger.info("Memory consolidation loop started (30min interval, vision=%s, imagination=%s)",
                     "yes" if _vision_integration else "no",
                     "yes" if _mongo_store and _mongo_store.available else "no")
        health_tracker.record_startup("MemoryConsolidation", True)
    except Exception as e:
        logger.warning("Memory consolidation loop failed to start: %s", e)
        health_tracker.record_startup("MemoryConsolidation", False, str(e))

    # Start background System Integrity Audit loop (every 2 hours)
    _audit_task = None
    _reflection_task = None
    try:
        async def _system_audit_loop():
            """Periodic system health & capability audit — checks all subsystems."""
            await asyncio.sleep(300)  # 5 min initial delay
            while True:
                try:
                    audit_start = time.time()
                    issues: list = []
                    stats: dict = {}

                    # 1. Perception DB freshness
                    if _collector and hasattr(_collector, 'db') and _collector.db:
                        try:
                            recent = await asyncio.get_event_loop().run_in_executor(
                                None, lambda: _collector.db.get_recent_events(hours_back=1, max_events=50),
                            )
                            stats["perception_recent_60min"] = len(recent)
                            if len(recent) == 0:
                                issues.append({
                                    "subsystem": "perception",
                                    "severity": "warning",
                                    "message": "No headlines ingested in last 60 minutes",
                                })
                        except Exception as e:
                            issues.append({
                                "subsystem": "perception",
                                "severity": "error",
                                "message": f"DB check failed: {e}",
                            })
                    else:
                        stats["perception_recent_60min"] = "N/A"

                    # 2. Entity graph health
                    if _framework and getattr(_framework, "_entity_graph", None):
                        eg = _framework._entity_graph
                        eg_stats = eg.stats()
                        stats["entity_graph"] = eg_stats
                        if eg_stats["nodes"] == 0:
                            issues.append({
                                "subsystem": "entity_graph",
                                "severity": "warning",
                                "message": "Entity graph is empty",
                            })
                    else:
                        stats["entity_graph"] = "not initialized"

                    # 3. Curiosity engine stats
                    if _framework and _framework.curiosity_engine:
                        ce_stats = _framework.curiosity_engine.get_stats()
                        stats["curiosity"] = ce_stats
                        if ce_stats.get("active_count", 0) == 0 and ce_stats.get("total_explored", 0) == 0:
                            issues.append({
                                "subsystem": "curiosity",
                                "severity": "info",
                                "message": "Curiosity engine has zero activity",
                            })
                    else:
                        stats["curiosity"] = "not initialized"

                    # 4. Proactive engine stats
                    if _proactive_engine:
                        try:
                            pe_stats = await asyncio.get_event_loop().run_in_executor(
                                None, lambda: {
                                    "pending_alerts": len(getattr(_proactive_engine, '_alert_queue', [])),
                                    "patterns_tracked": len(getattr(_proactive_engine, '_patterns', {})),
                                    "enabled": bool(getattr(_proactive_engine, 'enabled', False)),
                                },
                            )
                            stats["proactive_engine"] = pe_stats
                        except Exception as e:
                            stats["proactive_engine"] = f"check failed: {e}"
                    else:
                        stats["proactive_engine"] = "not initialized"

                    # 5. Memory health
                    if _framework and _framework.memory:
                        try:
                            mem_count = _framework.memory.entry_count
                            stats["episodic_memories"] = mem_count
                        except Exception:
                            stats["episodic_memories"] = "check failed"
                    else:
                        stats["episodic_memories"] = "not initialized"

                    # 6. Character state integrity
                    try:
                        with open(CHARACTER_STATE_PATH, "r", encoding="utf-8") as f:
                            cs = json.load(f)
                        worldview_count = len(cs.get("worldview", {}).get("beliefs", []))
                        identity_keys = list(cs.get("identity", {}).keys())
                        stats["character_state"] = {
                            "worldview_beliefs": worldview_count,
                            "identity_keys": len(identity_keys),
                            "has_identity": bool(identity_keys),
                        }
                    except FileNotFoundError:
                        stats["character_state"] = "not initialized"
                    except Exception:
                        stats["character_state"] = "check failed"

                    audit_elapsed = round(time.time() - audit_start, 2)
                    critical_issues = [i for i in issues if i["severity"] in ("error", "critical")]

                    # Store latest audit result for the API
                    _last_audit_result.update({
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                        "elapsed_seconds": audit_elapsed,
                        "stats": stats,
                        "issues": issues,
                        "issues_count": len(issues),
                        "critical_count": len(critical_issues),
                        "status": "critical" if critical_issues else ("warning" if issues else "healthy"),
                    })

                    if critical_issues:
                        logger.warning(
                            "[SystemAudit] %d CRITICAL issues found: %s",
                            len(critical_issues),
                            "; ".join(i["message"] for i in critical_issues),
                        )
                        # Notify proactive engine only on critical failures
                        if _proactive_engine:
                            try:
                                _proactive_engine.ingest_alert(
                                    source_type="system_audit",
                                    headline=f"System Audit: {len(critical_issues)} critical issues detected",
                                    region="INTERNAL",
                                    raw_data={"issues": critical_issues, "stats": stats},
                                )
                            except Exception:
                                pass
                    else:
                        logger.info(
                            "[SystemAudit] All clear — %d stats checked, %d minor issues, %.1fs",
                            len(stats), len(issues), audit_elapsed,
                        )
                except Exception as exc:
                    logger.warning("[SystemAudit] Audit cycle failed: %s", exc)
                    health_tracker.record_error("SystemAudit", f"Audit cycle failed: {exc}", exc)

                await asyncio.sleep(2 * 3600)  # Every 2 hours

        _audit_task = asyncio.create_task(_system_audit_loop())
        logger.info("System integrity audit loop started (2h interval)")
        health_tracker.record_startup("SystemAudit", True)
    except Exception as e:
        logger.warning("System audit loop failed to start: %s", e)
        health_tracker.record_startup("SystemAudit", False, str(e))

    # Start autonomous reflection loop (meta-cognition every 30 min)
    try:
        from xdart.phases.reflection_loop import AutonomousReflectionLoop
        _principle_registry = None
        try:
            _principle_registry = getattr(_framework, 'principle_registry', None)
        except Exception:
            pass
        reflection_loop = AutonomousReflectionLoop(
            llm=_framework.llm,
            character_path=str(CHARACTER_STATE_PATH),
            curiosity_engine=getattr(_framework, 'curiosity_engine', None),
            proactive_engine=_proactive_engine,
            principle_registry=_principle_registry,
            semantic_memory=getattr(_framework, 'semantic_memory', None),
            mongo=_mongo_store if _mongo_store and _mongo_store.available else None,
            interval_minutes=30,
        )
        # Give the reflection loop access to core engine for goal actions (agents, shell)
        reflection_loop.core_engine = _framework
        _reflection_task = asyncio.create_task(reflection_loop.run_forever())
        logger.info("Autonomous reflection loop started (30min interval)")
        health_tracker.record_startup("ReflectionLoop", True)
    except Exception as e:
        logger.warning("Reflection loop failed to start: %s", e)
        health_tracker.record_startup("ReflectionLoop", False, str(e))

    # ══════════════════════════════════════════════════════════════
    #  PALANTIR: Intelligence Action Graph (Βήμα 2)
    #  analysis → decision → action → outcome feedback loop
    # ══════════════════════════════════════════════════════════════
    _action_graph = None
    try:
        if _framework:
            from xdart.intelligence.action_graph import IntelligenceActionGraph
            _action_graph = IntelligenceActionGraph(
                llm=_framework.llm,
                proactive_engine=_proactive_engine,
                mongo=_mongo_store if _mongo_store and _mongo_store.available else None,
                persist_path=Path("."),
            )
            _action_graph.start()
            logger.info(
                "Intelligence Action Graph initialized (%d analyses, %d pending actions)",
                len(_action_graph._analyses),
                len(_action_graph.get_pending_actions()),
            )
            health_tracker.record_startup("ActionGraph", True)
            # Wire into framework for chat context + briefing context
            _framework._action_graph = _action_graph
            # Wire into briefing engine if it exists
            # (briefing engine init below will also set this)
    except Exception as _age:
        logger.warning("Intelligence Action Graph init failed (continuing without): %s", _age)
        health_tracker.record_startup("ActionGraph", False, str(_age))

    # ══════════════════════════════════════════════════════════════
    #  PALANTIR: Scheduled Autonomous Briefing Engine
    #  Αίολος reports daily at 06:00 Athens. No human trigger needed.
    # ══════════════════════════════════════════════════════════════
    _briefing_engine = None
    try:
        from xdart.config import BRIEFING_ENABLED, BRIEFING_SCHEDULE_TIMES, BRIEFING_TIMEZONE
        if BRIEFING_ENABLED and _proactive_engine and _framework:
            from xdart.intelligence.scheduled_briefing import ScheduledBriefingEngine
            _briefing_engine = ScheduledBriefingEngine(
                llm=_framework.llm,
                proactive_engine=_proactive_engine,
                schedule_times=BRIEFING_SCHEDULE_TIMES,
                tz_name=BRIEFING_TIMEZONE,
                telegram_bot_token=TELEGRAM_BOT_TOKEN,
                telegram_chat_id=TELEGRAM_CHAT_ID,
                mongo=_mongo_store if _mongo_store and _mongo_store.available else None,
            )
            _briefing_engine.start()
            logger.info(
                "Scheduled Briefing Engine started (schedule=%s tz=%s telegram=%s)",
                BRIEFING_SCHEDULE_TIMES, BRIEFING_TIMEZONE,
                "yes" if TELEGRAM_BOT_TOKEN else "no",
            )
            health_tracker.record_startup("ScheduledBriefing", True,
                                          f"schedule={BRIEFING_SCHEDULE_TIMES}")
        elif not BRIEFING_ENABLED:
            logger.info("Scheduled Briefing Engine disabled (BRIEFING_ENABLED=false)")
    except Exception as e:
        logger.warning("Scheduled Briefing Engine failed to start: %s", e)
        health_tracker.record_startup("ScheduledBriefing", False, str(e))

    # ══════════════════════════════════════════════════════════════
    #  PALANTIR DARK WING: Dark Whisper Intelligence Engine
    #  Clearnet OSINT → dirty pool → LLM triage → Creative Nexus → synthesis
    # ══════════════════════════════════════════════════════════════
    _darkwhisper_engine = None
    try:
        from xdart.config import DARKWEB_ENABLED
        if DARKWEB_ENABLED and _framework and _proactive_engine:
            from xdart.perception.darkweb import DirtyPool, DarkWebCollector
            from xdart.intelligence.dark_triage import DarkSignalTriage
            from xdart.intelligence.darkwhisper import DarkWhisperEngine

            _mongo_db = _mongo_store._db if _mongo_store and _mongo_store.available else None
            _dirty_pool = DirtyPool(mongo_db=_mongo_db)
            _dark_collector = DarkWebCollector(dirty_pool=_dirty_pool)
            _dark_triage = DarkSignalTriage(
                dirty_pool=_dirty_pool,
                llm=_framework.llm,
            )
            _darkwhisper_engine = DarkWhisperEngine(
                llm=_framework.llm,
                proactive_engine=_proactive_engine,
                mongo_store=_mongo_store if _mongo_store and _mongo_store.available else None,
                mongo_db=_mongo_db,
                dirty_pool=_dirty_pool,
                triage=_dark_triage,
                collector=_dark_collector,
            )
            # Start the collector (asyncio task) and synthesis engine (thread)
            _dark_collector.start()
            _darkwhisper_engine.start()
            # Wire into framework for context injection in chat
            if _framework:
                _framework._darkwhisper_engine = _darkwhisper_engine
                # Wire into WakeupProtocol so every API call injects live Dark Wing
                # status into the identity context (bridges the stateless LLM memory gap)
                if hasattr(_framework, "wakeup") and _framework.wakeup:
                    _framework.wakeup.darkwhisper_engine = _darkwhisper_engine
                    logger.info("Dark Wing wired into WakeupProtocol (live status per call)")
            # Wire into ProactiveEngine so pattern fires trigger dark signal resonance
            if _proactive_engine:
                _proactive_engine._darkwhisper_engine = _darkwhisper_engine
                logger.info("Dark Wing wired into ProactiveEngine (pattern resonance active)")
            logger.info(
                "Dark Whisper Intelligence Engine started "
                "(channels=%d, ahmia=%s, paste=%s)",
                len(__import__("xdart.config", fromlist=["DARKWEB_TELEGRAM_CHANNELS"]).DARKWEB_TELEGRAM_CHANNELS),
                __import__("xdart.config", fromlist=["DARKWEB_AHMIA_ENABLED"]).DARKWEB_AHMIA_ENABLED,
                __import__("xdart.config", fromlist=["DARKWEB_PASTE_ENABLED"]).DARKWEB_PASTE_ENABLED,
            )
            health_tracker.record_startup("DarkWhisperEngine", True, "clearnet OSINT active")
        elif not DARKWEB_ENABLED:
            logger.info("Dark Whisper Intelligence disabled (DARKWEB_ENABLED=false)")
            health_tracker.record_startup("DarkWhisperEngine", False, "disabled by config")
    except Exception as _dwe:
        logger.warning("Dark Whisper Engine failed to start (continuing without): %s", _dwe)
        health_tracker.record_startup("DarkWhisperEngine", False, str(_dwe))

    # ══════════════════════════════════════════════════════════════
    #  TELEGRAM INTELLIGENCE TOOL — Αίολος' autonomous channel ops
    #  Search • Validate • Monitor — feeds into DirtyPool pipeline
    # ══════════════════════════════════════════════════════════════
    global _telegram_intel
    try:
        from xdart.tools.telegram_intel_tool import TelegramIntelTool
        from xdart.config import (
            TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_NAME, BRAVE_SEARCH_API_KEY,
        )
        _telegram_intel = TelegramIntelTool(
            brave_api_key=BRAVE_SEARCH_API_KEY,
            api_id=TELEGRAM_API_ID,
            api_hash=TELEGRAM_API_HASH,
            session_name=TELEGRAM_SESSION_NAME,
            dark_collector=_dark_collector if "_dark_collector" in dir() else None,
            dirty_pool=_dirty_pool if "_dirty_pool" in dir() else None,
        )
        # Wire into framework for context injection in chat
        if _framework:
            _framework.telegram_intel = _telegram_intel
            # Wire into WakeupProtocol so every API call injects live Telegram Intel
            # status into the identity context (bridges the stateless LLM memory gap)
            if hasattr(_framework, "wakeup") and _framework.wakeup:
                _framework.wakeup.telegram_intel = _telegram_intel
                logger.info("Telegram Intel Tool wired into WakeupProtocol (live status per call)")
        health_tracker.record_startup(
            "TelegramIntelTool",
            True,
            f"tier1=active, tier2={'available' if TELEGRAM_API_ID else 'inactive'}",
        )
        logger.info(
            "Telegram Intel Tool initialized (tier1=active, tier2=%s, brave=%s)",
            "available" if TELEGRAM_API_ID else "inactive (no API_ID)",
            "YES" if BRAVE_SEARCH_API_KEY else "NO (fallback to DDG)",
        )
    except Exception as _ti_exc:
        logger.warning("Telegram Intel Tool failed to init (continuing without): %s", _ti_exc)
        health_tracker.record_startup("TelegramIntelTool", False, str(_ti_exc))

    # ── Startup complete ──────────────────────────────────────────────────────
    _startup_complete = True
    logger.info("XDART-Φ ✅ API fully initialized and ready (all systems green)")

    # Send Telegram notification so user knows the server is ready to use.
    # Runs as a fire-and-forget background task — doesn't block anything.
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        asyncio.create_task(_send_startup_notification())

    yield

    # ── Shutdown: signal all background tasks to stop gracefully ──
    logger.info("XDART-Φ API shutting down — signalling background tasks...")
    _shutdown_event.set()  # Signal all loops to stop at next check

    # Stop briefing engine (daemon thread — stop() is graceful)
    if _briefing_engine:
        try:
            _briefing_engine.stop()
        except Exception:
            pass

    # Stop Palantir Βήμα 1 + Βήμα 2 engines
    if _ontology_engine:
        try:
            _ontology_engine.stop()
        except Exception:
            pass
    if _action_graph:
        try:
            _action_graph.stop()
        except Exception:
            pass

    # Stop Dark Whisper Engine (Dark Wing)
    if _darkwhisper_engine:
        try:
            _darkwhisper_engine.stop()
            if hasattr(_darkwhisper_engine, "collector"):
                _darkwhisper_engine.collector.stop()
        except Exception:
            pass

    # Record temporal state for offline gap detection
    if _framework and hasattr(_framework, 'temporal_clock'):
        _framework.temporal_clock.record_shutdown()

    # Collect all active tasks
    _bg_tasks = [t for t in [
        _collector_task, _consolidation_task, _resolver_task,
        _curiosity_task, _proactive_task, _audit_task, _reflection_task,
    ] if t and not t.done()]

    # Give tasks a moment to notice shutdown_event and exit gracefully
    if _bg_tasks:
        logger.info("XDART-Φ Waiting for %d background tasks to finish...", len(_bg_tasks))
        # Wait up to 2 seconds for graceful exit
        done, pending = await asyncio.wait(_bg_tasks, timeout=2.0)
        # Force-cancel anything still running
        for task in pending:
            task.cancel()
        if pending:
            # Wait for cancellations to propagate
            await asyncio.wait(pending, timeout=1.0)
            logger.info("XDART-Φ Force-cancelled %d remaining tasks", len(pending))

    # Shutdown LLM thread pools AFTER all tasks are done
    if _framework and hasattr(_framework, 'llm') and _framework.llm:
        for pool_name in ('_timeout_pool', '_fallback_pool'):
            pool = getattr(_framework.llm, pool_name, None)
            if pool:
                pool.shutdown(wait=False, cancel_futures=True)
        logger.info("XDART-Φ LLM thread pools shut down")

    # Shutdown expanded executor
    _expanded_executor.shutdown(wait=False, cancel_futures=True)
    logger.info("XDART-Φ Thread pool shut down")

    logger.info("XDART-Φ API stopped")


app = FastAPI(
    title="XDART-Φ × XHEART",
    description="Epistemological Architecture for AI Reasoning",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/xdart/health", response_model=HealthResponse)
async def health():
    """Lightweight health check — never blocked by thread pool."""
    return HealthResponse(
        status="ok" if _startup_complete else "starting",
        model=OPENAI_MODEL,
        memories=_framework.memory.entry_count if _framework else 0,
        concepts=_framework.memory.concept_count if _framework else 0,
        pipeline_running=_framework.pipeline_running if _framework else False,
        startup_complete=_startup_complete,
    )


@app.get("/xdart/system/errors")
async def system_errors():
    """Full subsystem health report — errors, statuses, uptime.

    Αίολος and the dashboard use this to see what's broken and what's healthy.
    """
    return health_tracker.get_summary()


# ══════════════════════════════════════════════════════════════
#  HOT-RELOAD — surgical module reload without full restart
# ══════════════════════════════════════════════════════════════

# Modules that can be safely reloaded at runtime.
# After reload, methods on the _framework instance are patched so
# new code takes effect immediately — no restart, no lost state.
_HOT_RELOAD_MODULES = [
    "xdart.config",
    "xdart.llm",
    "xdart.models",
    "xdart.core",
    "xdart.proactive",
    "xdart.adversarial",
    "xdart.tools.agent_spawner",
    "xdart.tools.shell_executor",
    "xdart.knowledge.mongo",
    "xdart.knowledge.entity_graph",
    "xdart.knowledge.patterns",
    "xdart.knowledge.views_catalog",
    "xdart.phases.reflection_loop",
    "xdart.phases.wakeup",
    "xdart.phases.memory",
    "xdart.phases.memory_architecture",
    "xdart.perception.context_retriever",
    "xdart.perception.collector",
    "xdart.perception.filter",
    "xdart.perception.keyword_spikes",
    "xdart.evolution.core",
    "xdart.evolution.sandbox",
    "xdart.evolution.self_knowledge",
]


@app.post("/xdart/hot-reload")
async def hot_reload(modules: list[str] | None = None):
    """Reload Python modules without restarting the server.

    If no modules specified, reloads all key modules.
    After reload, patches the running framework instance so new
    code (prompts, logic, tools) takes effect immediately.

    Background tasks (CuriosityLoop, ReflectionLoop, etc.) keep running.
    MongoDB/Qdrant connections stay alive.
    """
    import importlib
    import sys
    import time as _time

    target_modules = modules or _HOT_RELOAD_MODULES
    results = {"reloaded": [], "failed": [], "patched": [], "duration_ms": 0}
    t0 = _time.perf_counter()

    # Phase 1: Reload requested modules
    for mod_name in target_modules:
        if mod_name not in sys.modules:
            results["failed"].append({"module": mod_name, "error": "not loaded"})
            continue
        try:
            importlib.reload(sys.modules[mod_name])
            results["reloaded"].append(mod_name)
        except Exception as e:
            results["failed"].append({"module": mod_name, "error": str(e)})
            logger.warning("[HotReload] Failed to reload %s: %s", mod_name, e)

    # Phase 2: Patch the running framework instance with new class methods
    if _framework and "xdart.core" in results["reloaded"]:
        try:
            from xdart.core import XDARTFramework as NewClass
            # Patch all methods from the new class onto the existing instance
            for attr_name in dir(NewClass):
                if attr_name.startswith("__"):
                    continue
                new_attr = getattr(NewClass, attr_name)
                if callable(new_attr) and not isinstance(new_attr, property):
                    try:
                        import types
                        if isinstance(new_attr, staticmethod):
                            setattr(_framework, attr_name, new_attr)
                        else:
                            bound = types.MethodType(new_attr, _framework)
                            setattr(_framework, attr_name, bound)
                    except Exception:
                        pass
            results["patched"].append("XDARTFramework (methods)")
            logger.info("[HotReload] Patched XDARTFramework methods on live instance")
        except Exception as e:
            results["failed"].append({"module": "framework_patch", "error": str(e)})

    # Patch AgentSpawner if reloaded
    if _framework and _framework.agent_spawner and "xdart.tools.agent_spawner" in results["reloaded"]:
        try:
            from xdart.tools.agent_spawner import AgentSpawner as NewSpawner
            import types
            for attr_name in dir(NewSpawner):
                if attr_name.startswith("__"):
                    continue
                new_attr = getattr(NewSpawner, attr_name)
                if callable(new_attr) and not isinstance(new_attr, property):
                    try:
                        bound = types.MethodType(new_attr, _framework.agent_spawner)
                        setattr(_framework.agent_spawner, attr_name, bound)
                    except Exception:
                        pass
            results["patched"].append("AgentSpawner (methods)")
        except Exception as e:
            results["failed"].append({"module": "spawner_patch", "error": str(e)})

    # Patch MongoStore if reloaded — focus on _action_* handlers + public methods
    if _mongo_store and "xdart.knowledge.mongo" in results["reloaded"]:
        try:
            from xdart.knowledge.mongo import MongoStore as NewMongo
            import types
            for attr_name in dir(NewMongo):
                if attr_name.startswith("__"):
                    continue
                # Patch action handlers and public methods
                if not (attr_name.startswith("_action_") or not attr_name.startswith("_")):
                    continue
                new_attr = getattr(NewMongo, attr_name)
                if callable(new_attr) and not isinstance(new_attr, property):
                    try:
                        bound = types.MethodType(new_attr, _mongo_store)
                        setattr(_mongo_store, attr_name, bound)
                    except Exception:
                        pass
            results["patched"].append("MongoStore (action handlers)")
        except Exception as e:
            results["failed"].append({"module": "mongo_patch", "error": str(e)})

    results["duration_ms"] = round((_time.perf_counter() - t0) * 1000)
    logger.info("[HotReload] Complete: %d reloaded, %d patched, %d failed (%.0fms)",
                len(results["reloaded"]), len(results["patched"]),
                len(results["failed"]), results["duration_ms"])
    return results


PRESET_CLIENT_PROFILES = {
    "pm_advisor_greece": {
        "role": "Σύμβουλος Πρωθυπουργού Ελλάδας",
        "decisions_i_make": [
            "Εισηγήσεις σε ΚΥΣΕΑ",
            "Τηλεφωνικές επικοινωνίες σε επίπεδο αρχηγών κρατών",
            "Κατεύθυνση κυβερνητικού αφηγήματος",
            "Ενεργοποίηση ή αποκλιμάκωση κρίσεων",
        ],
        "resources_i_control": [
            "ΥΠΕΞ", "ΓΕΕΘΑ", "ΕΥΠ",
            "Κυβερνητικός Εκπρόσωπος",
            "Άμεση γραμμή σε Μακρόν, Μέρκελ, NATO SG",
        ],
        "time_horizon": "24-72 ώρες (κρίση), 6 μήνες (στρατηγική)",
        "risk_tolerance": "Δεν αντέχει κλιμάκωση — εκλογικό κόστος, ευρωπαϊκή απομόνωση",
        "constraints": [
            "Συνταγματικοί περιορισμοί",
            "NATO υποχρεώσεις",
            "EU consensus mandate",
            "Μη πρόκληση αμερικανικής δυσαρέσκειας",
        ],
        "stakeholders": [
            "Πρωθυπουργός (τελικός αποδέκτης)",
            "Αρχηγός ΓΕΕΘΑ", "Υπουργός Εξωτερικών",
            "Ευρωπαϊκό Συμβούλιο",
        ],
    },
    "shipping_ceo": {
        "role": "CEO ναυτιλιακής εταιρείας, 12 tankers",
        "decisions_i_make": [
            "Δρομολόγηση/ανακατεύθυνση πλοίων",
            "Ασφαλιστική κάλυψη war-risk",
            "Spot vs time charter αποφάσεις",
            "Bunker hedging",
        ],
        "resources_i_control": [
            "12 tankers (Suezmax + Aframax)",
            "Ασφαλιστικοί brokers",
            "Commercial team Λονδίνο + Σιγκαπούρη",
            "Πρόσβαση σε VLCC pool",
        ],
        "time_horizon": "48 ωρών (repositioning), 12 μηνών (charter strategy)",
        "risk_tolerance": "Υψηλή ανοχή spot-market volatility, χαμηλή ανοχή σε piracy/sanctions exposure",
        "constraints": [
            "Δεν μπορεί να αρνηθεί OFAC-sanctioned cargo",
            "Insurance P&I coverage limits",
            "Crew safety obligations (ISM Code)",
        ],
        "stakeholders": [
            "Board of Directors", "P&I Club", "Charterers",
        ],
    },
    "hedge_fund_pm": {
        "role": "Portfolio Manager, macro hedge fund ($2B AUM)",
        "decisions_i_make": [
            "Country risk positioning (sovereign CDS, FX)",
            "Commodity directional bets (oil, gas, shipping)",
            "Equity sector allocation (energy, defense, tourism)",
            "Options structures for tail risk hedging",
        ],
        "resources_i_control": [
            "$2B gross exposure budget",
            "Prime broker relationships (Goldman, JPM)",
            "Real-time Bloomberg/Reuters terminals",
            "Analyst team (3 sector specialists)",
        ],
        "time_horizon": "Days (tactical), 3-6 months (strategic)",
        "risk_tolerance": "High vol tolerance, 15% max drawdown mandate",
        "constraints": [
            "UCITS/AIFMD compliance",
            "Client redemption windows (quarterly)",
            "Liquidity constraints on EM positions",
        ],
        "stakeholders": [
            "Fund investors (LPs)", "Risk committee", "Compliance officer",
        ],
    },
    "ngo_director": {
        "role": "Director, humanitarian NGO operating in crisis zone",
        "decisions_i_make": [
            "Staff evacuation or shelter-in-place",
            "Resource pre-positioning",
            "Coordination with UNHCR/ICRC",
            "Public statements and donor communication",
        ],
        "resources_i_control": [
            "Field teams (120 staff across 4 locations)",
            "Emergency fund ($5M)",
            "Logistics fleet (trucks, boats)",
            "Satellite comms",
        ],
        "time_horizon": "Hours (evacuation), weeks (operation pivot)",
        "risk_tolerance": "Zero tolerance for staff casualties, moderate for operational disruption",
        "constraints": [
            "Donor reporting requirements",
            "Humanitarian principles (neutrality, impartiality)",
            "Host government permissions",
        ],
        "stakeholders": [
            "Board of Trustees", "OCHA coordination", "Donors (ECHO, USAID)",
        ],
    },
}


@app.get("/xdart/client-profiles")
async def list_client_profiles():
    """Return available preset client profiles as a flat list with full data."""
    return [
        {"id": name, **data}
        for name, data in PRESET_CLIENT_PROFILES.items()
    ]


@app.get("/xdart/client-profiles/{profile_id}")
async def get_client_profile(profile_id: str):
    """Return a specific preset client profile."""
    if profile_id not in PRESET_CLIENT_PROFILES:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return PRESET_CLIENT_PROFILES[profile_id]


@app.post("/xdart/run", response_model=RunResponse)
async def run_framework(req: RunRequest):
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    if not req.problem.strip():
        raise HTTPException(status_code=400, detail="Problem cannot be empty")

    # Build ClientProfile if provided
    profile = None
    if req.client_profile:
        profile = ClientProfile(**req.client_profile.model_dump())

    result: FrameworkOutput = _framework.run(
        problem=req.problem,
        client_profile=profile,
    )

    return RunResponse(
        problem=result.problem,
        reframed_problem=result.phase0_ontology.reframed_problem,
        final_output=result.final_output,
        falsifiability=result.falsifiability,
        layer=result.layer.value,
        domains_used=[d.domain for d in result.phase1_xdart.domains_analyzed],
        views_used=[v.view_name for v in result.phase2_views.views_applied],
        convergent_patterns=result.phase2_views.convergent_patterns,
        memory_count=_framework.memory.entry_count,
        phase0_reframe=result.phase0_ontology.reframed_problem,
        phase1_strongest_analogy=(
            f"{result.phase1_xdart.strongest_analogy.domain}: "
            f"{result.phase1_xdart.strongest_analogy.transfer_hypothesis}"
        ),
        phase2_dominant_pattern=result.phase2_views.dominant_pattern,
        xheart_has_synthesis=result.phase3_xheart.synthesis is not None,
    )


@app.get("/xdart/memory", response_model=list[MemoryEntry])
async def list_memories():
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    def _get():
        memories = _framework.memory.retrieve("*", top_k=100)
        return [
            MemoryEntry(
                id=m.entry.id,
                problem=m.entry.problem,
                reframed_problem=m.entry.reframed_problem,
                distillate=m.entry.xheart_distillate,
                domains=m.entry.domain_tags,
                layer_score=m.entry.layer_score,
            )
            for m in memories
        ]

    return await asyncio.get_event_loop().run_in_executor(None, _get)


# ── Chat Mode Request/Response ──

class ChatMessage(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(description="User's chat message")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="Conversation history (last N turns)"
    )
    proactive: bool = Field(
        default=False,
        description="True when message originates from proactive engine (bypasses router)"
    )


class ChatResponse(BaseModel):
    action: str = Field(description="'respond' (direct answer) or 'pipeline' (triggers full analysis)")
    response: str | None = Field(default=None, description="Direct response text (when action='respond')")
    reasoning: str = Field(default="", description="Why this action was chosen")
    problem: str | None = Field(default=None, description="Problem text to run (when action='pipeline')")


@app.post("/xdart/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Chat mode — the system decides whether to respond directly or trigger the full pipeline.

    The system loads all its knowledge (character, memories, world context, concepts)
    and responds conversationally for simple questions. For deep strategic questions,
    it returns action='pipeline' to signal the UI to start a full SSE stream.
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    history_dicts = [{"role": m.role, "content": m.content} for m in req.history]

    # Inject recent proactive notifications as context for the chat
    proactive_context = ""
    if _proactive_engine:
        proactive_context = _proactive_engine.get_recent_context_for_chat(max_items=10)

    def _run():
        return _framework.chat(
            message=req.message,
            history=history_dicts,
            proactive_context=proactive_context,
            proactive=req.proactive,
        )

    try:
        result = await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as exc:
        logger.warning("[API] /xdart/chat failed: %s", exc)
        return ChatResponse(
            action="respond",
            response=f"Apologies — an internal error occurred: {str(exc)[:200]}",
            reasoning="error_fallback",
        )

    return ChatResponse(
        action=result.get("action", "respond"),
        response=result.get("response"),
        reasoning=result.get("reasoning", ""),
        problem=result.get("problem"),
    )


@app.post("/xdart/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming chat — returns Server-Sent Events as the LLM generates text.

    Events:
      event: routing    — {action, reasoning} — router decision
      event: chunk      — {text} — incremental text delta
      event: done       — {full_text, action, reasoning} — final cleaned response
      event: pipeline   — {problem, reasoning} — redirect to full pipeline
      event: error      — {message} — error occurred
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    history_dicts = [{"role": m.role, "content": m.content} for m in req.history]
    proactive_context = ""
    if _proactive_engine:
        proactive_context = _proactive_engine.get_recent_context_for_chat(max_items=10)

    # Log user message to MongoDB
    if _mongo_store and _mongo_store.available:
        try:
            _mongo_store.log_message("user", req.message)
        except Exception:
            pass

    async def event_generator():
        import json as _json
        full_response = []

        def _stream():
            return list(_framework.chat_stream(
                message=req.message,
                history=history_dicts,
                proactive_context=proactive_context,
                proactive=req.proactive,
            ))

        # Run the synchronous generator in a thread pool
        # We collect events from the generator and yield them as SSE
        loop = asyncio.get_event_loop()

        # Use a queue to bridge sync generator → async SSE
        import queue
        q: queue.Queue = queue.Queue()
        sentinel = object()

        def _produce():
            try:
                for ev in _framework.chat_stream(
                    message=req.message,
                    history=history_dicts,
                    proactive_context=proactive_context,
                    proactive=req.proactive,
                ):
                    q.put(ev)
            except Exception as exc:
                q.put({"event": "error", "data": {"message": str(exc)}})
            finally:
                q.put(sentinel)

        import threading
        threading.Thread(target=_produce, daemon=True, name="chat-stream-producer").start()

        while True:
            # Non-blocking poll with small sleep to yield to event loop
            try:
                item = await loop.run_in_executor(None, q.get, True, 0.05)
            except queue.Empty:
                continue
            if item is sentinel:
                break
            event_name = item.get("event", "chunk")
            event_data = item.get("data", {})
            # Log AI response to MongoDB on completion
            if event_name == "done" and _mongo_store and _mongo_store.available:
                try:
                    ai_text = event_data.get("full_text", "") if isinstance(event_data, dict) else ""
                    if ai_text:
                        _mongo_store.log_message("assistant", ai_text, {"action": event_data.get("action")})
                except Exception:
                    pass
            yield {"event": event_name, "data": _json.dumps(event_data, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@app.get("/xdart/self-prompt")
async def get_self_prompt():
    """View the AI's current self-written prompt."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    # Read character state directly — no need for full wakeup (avoids double wakeup on page load)
    character = _framework.wakeup._load_character()
    return {
        "name": character.get("name", ""),
        "self_prompt": character.get("self_prompt", ""),
        "version": character.get("version", 0),
        "has_self_prompt": bool(character.get("self_prompt", "")),
    }


# ── MongoDB Stats & Notes API ──

@app.get("/xdart/mongo/stats")
async def mongo_stats():
    """MongoDB statistics — collection sizes, total documents."""
    if not _mongo_store or not _mongo_store.available:
        return {"available": False, "message": "MongoDB not connected"}
    try:
        stats = _mongo_store.stats()
        return {"available": True, **stats}
    except Exception as e:
        return {"available": False, "error": str(e)}


@app.get("/xdart/mongo/conversations")
async def mongo_conversations(limit: int = 50):
    """Recent conversation history from MongoDB."""
    if not _mongo_store or not _mongo_store.available:
        return {"available": False, "messages": []}
    messages = _mongo_store.get_conversation_history(limit=limit)
    return {"available": True, "count": len(messages), "messages": messages}


@app.post("/xdart/mongo/notes")
async def mongo_save_note(data: dict):
    """Save or update a note (Αίολος' structured knowledge)."""
    if not _mongo_store or not _mongo_store.available:
        raise HTTPException(status_code=503, detail="MongoDB not available")
    title = data.get("title", "")
    content = data.get("content", "")
    tags = data.get("tags", [])
    category = data.get("category", "general")
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content required")
    result = _mongo_store.save_note(title=title, content=content, tags=tags, category=category)
    return {"ok": True, "note_id": str(result)}


@app.get("/xdart/mongo/notes")
async def mongo_search_notes(q: str = "", tags: str = ""):
    """Search notes by text query and/or tags."""
    if not _mongo_store or not _mongo_store.available:
        return {"available": False, "notes": []}
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    notes = _mongo_store.search_notes(text_query=q or None, tags=tag_list)
    return {"available": True, "count": len(notes), "notes": notes}


@app.get("/xdart/introspection")
async def get_introspection():
    """View recent introspection reports (αυτογνωσία)."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    def _get():
        recent = _framework.introspection.get_recent(10)
        avg_integrity = _framework.introspection.get_average_integrity(10)
        failure_patterns = _framework.introspection.get_failure_patterns()
        return {
            "recent_reports": recent,
            "avg_integrity": round(avg_integrity, 3),
            "failure_patterns": failure_patterns,
            "total_reports": len(_framework.introspection.get_recent(1000)),
        }

    return await asyncio.get_event_loop().run_in_executor(None, _get)


@app.get("/xdart/self-evolution")
async def get_self_evolution():
    """View self-evolution journal and proposals (αυτοεξέλιξη)."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    stats = _framework.self_evolution.get_journal_stats()
    proposals = _framework.self_evolution.get_active_proposals()
    return {
        "stats": stats,
        "active_proposals": proposals,
    }


@app.get("/xdart/wisdom")
async def get_wisdom():
    """View wisdom calibration report (σοφία)."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    wisdom_index = _framework.wisdom_tracker.compute_wisdom_index()
    report = _framework.wisdom_tracker.get_calibration_report()
    return {
        "wisdom_index": wisdom_index,
        "calibration_report": report,
        "context_string": _framework.wisdom_tracker.to_context_string(),
    }


@app.get("/xdart/overlays")
async def get_overlays():
    """View prompt overlay system state (αυτο-τροποποίηση).

    Shows all active overlays written by Αίολος via self-evolution,
    plus system stats (total applied, rollbacks, history).
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    return {
        "active_overlays": _framework.overlay_manager.get_active_overlays(),
        "stats": _framework.overlay_manager.get_stats(),
        "context_string": _framework.overlay_manager.to_context_string(),
    }


@app.post("/xdart/resolve-prophecies")
async def resolve_prophecies():
    """On-demand prophecy resolution — check all predictions against reality.

    This is the grounding mechanism. It:
    1. Finds all prophecies with passed deadlines
    2. Retrieves current world data
    3. Evaluates each prediction (binary: confirmed/disconfirmed)
    4. Computes real Brier scores
    5. Updates wisdom calibration with actual outcomes
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    if not _framework.prophecy_resolver:
        raise HTTPException(status_code=503, detail="Prophecy resolver not available")

    result = await asyncio.get_event_loop().run_in_executor(
        None, _framework.prophecy_resolver.resolve_all,
    )
    return result


@app.get("/xdart/accuracy")
async def get_accuracy():
    """View real prediction accuracy stats from resolved prophecies."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    accuracy = _framework.prophetic_memory.compute_accuracy_stats()
    last_resolution = None
    if _framework.prophecy_resolver:
        last_resolution = _framework.prophecy_resolver.last_run_result
    return {
        "accuracy": accuracy,
        "last_resolution_run": last_resolution,
    }


class AdversarialRequest(BaseModel):
    category: str | None = None  # optional — run only this category


@app.post("/xdart/adversarial-test")
async def run_adversarial_test(req: AdversarialRequest | None = None):
    """Run adversarial test cases through the pipeline.

    Each case feeds a known-tricky input (false premise, vague question,
    contradiction, etc.) and an LLM judge scores the output.

    Optional body: {"category": "false_premise"} to run only that category.
    Categories: false_premise, epistemic_humility, vague_input, contradiction,
                numeric_accuracy, calibration
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    if not _framework.adversarial:
        raise HTTPException(status_code=503, detail="Adversarial harness not available")

    category = req.category if req else None

    if category:
        report = await asyncio.get_event_loop().run_in_executor(
            None, _framework.adversarial.run_category, category,
        )
    else:
        report = await asyncio.get_event_loop().run_in_executor(
            None, _framework.adversarial.run_all,
        )
    return report.to_dict()


@app.post("/xdart/stream")
async def stream_framework(req: RunRequest):
    """SSE endpoint — streams each phase result as it completes."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    if not req.problem.strip():
        raise HTTPException(status_code=400, detail="Problem cannot be empty")

    logger.info("[API/SSE] Stream request: %s", req.problem[:100])

    import asyncio
    import queue
    import threading

    event_queue: queue.Queue = queue.Queue()

    def run_pipeline():
        """Run the framework in a thread, pushing phase events to the queue."""
        pipeline_t0 = time.time()
        try:
            def on_phase(name: str, result) -> None:
                phase_elapsed = time.time() - pipeline_t0
                phase_labels = {
                    "wakeup_complete": "Phase 0.0 — Identity Wakeup",
                    "phase0_ontology": "Phase 0 — Ontological Grounding",
                    "phase1_xdart": "Phase 1 — XDART-Φ Cross-Domain",
                    "phase2_views": "Phase 2 — Multiple Views",
                    "phase2_5_scenarios": "Phase 2.5 — Scenario Genesis",
                    "phase2_7_simulations": "Phase 2.7 — Scenario Simulation",
                    "phase2_9_tribunal": "Phase 2.9 — Scenario Tribunal",
                    "phase2_95_actions": "Phase 2.95 — Scenario-Action Mapping",
                    "phase3_xheart": "Phase 3 — XHEART Distillation",
                    "phase3_5_historical": "Phase 3.5 — Historical Resonance",
                    "phase3_7_strategic": "Phase 3.7 — Strategic Foresight",
                    "phase3_9_bets": "Phase 3.9 — Decision Triggers",
                    "phase4_memory": "Phase 4 — Episodic Memory",
                    "character_updated": "Phase 5b — Character Update",
                    "world_context": "Phase 0.35 — World Perception",
                    "prophetic_memory_stored": "Phase 4.5 — Prophetic Memory",
                    "introspection_complete": "Phase 5c — Introspection",
                    "wisdom_updated": "Phase 5c.2 — Wisdom Tracking",
                    "self_evolution_diagnosis": "Phase 5c.3 — Self-Evolution",
                    "prophetic_memories": "Phase 0.4 — Prophetic Recall",
                    "working_memory_state": "Phase 0.5 — Working Memory",
                    "evolution_tools_ran": "Phase 0.6 — Evolution Tools",
                    "prophetic_loop": "Phase 0.3 — Prophetic Loop",
                }

                payload = {
                    "phase": name,
                    "label": phase_labels.get(name, name),
                    "elapsed": round(phase_elapsed, 2),
                }

                if name == "wakeup_complete":
                    # result is dict with character info
                    payload["data"] = result
                    event_queue.put(("phase", json.dumps(payload, ensure_ascii=False)))
                    return
                elif name == "character_updated":
                    # result is dict with version, tensions, changes
                    payload["data"] = result
                    event_queue.put(("phase", json.dumps(payload, ensure_ascii=False)))
                    return
                elif name == "core_change_proposed":
                    # result is dict with change_id, change_type, target, description, reasoning
                    payload["data"] = result
                    event_queue.put(("phase", json.dumps(payload, ensure_ascii=False)))
                    return
                elif name == "world_context":
                    # result is dict with events count, indicators count, sample
                    payload["data"] = result
                    event_queue.put(("phase", json.dumps(payload, ensure_ascii=False)))
                    return
                elif name == "phase0_ontology":
                    payload["data"] = {
                        "ontological_nature": result.ontological_nature,
                        "teleological_purpose": result.teleological_purpose,
                        "causal_analysis": result.causal_analysis,
                        "epistemological_check": result.epistemological_check,
                        "reframed_problem": result.reframed_problem,
                    }
                elif name == "concepts_activated":
                    # result is list[dict] of active concepts
                    concept_payload = {
                        "phase": "concepts_activated",
                        "label": "Concept Registry — Active Concepts",
                        "elapsed": round(phase_elapsed, 2),
                        "data": {
                            "concepts": [
                                {
                                    "name": c["name"],
                                    "key_insight": c.get("key_insight", ""),
                                    "similarity": round(c.get("similarity", 0), 3),
                                }
                                for c in result
                            ]
                        },
                    }
                    event_queue.put(("phase", json.dumps(concept_payload, ensure_ascii=False)))
                    return  # already pushed
                elif name == "phase1_xdart":
                    payload["data"] = {
                        "domains": [
                            {
                                "domain": d.domain,
                                "strength": d.analogy_strength.value,
                                "distance": d.domain_distance,
                                "specificity": d.mechanistic_specificity,
                                "hypothesis": d.transfer_hypothesis,
                            }
                            for d in result.domains_analyzed
                        ],
                        "strongest": result.strongest_analogy.domain,
                        "layer": result.layer.value,
                        "structural_formula": result.structural_formula,
                        "layer_3_hypothesis": result.layer_3_hypothesis,
                    }
                elif name == "phase2_views":
                    payload["data"] = {
                        "views": [
                            {
                                "id": v.view_id,
                                "name": v.view_name,
                                "category": v.category,
                                "insight": v.insight,
                                "reveals": v.reveals_hidden,
                            }
                            for v in result.views_applied
                        ],
                        "convergent": result.convergent_patterns,
                        "divergent": result.divergent_insights,
                        "dominant": result.dominant_pattern,
                    }
                elif name == "phase2_5_scenarios":
                    # Scenario Genesis results (result is dict from callback)
                    payload["label"] = "Phase 2.5 — Scenario Genesis"
                    payload["data"] = result
                elif name == "phase2_7_simulations":
                    # Simulation results (result is dict from callback)
                    payload["label"] = "Phase 2.7 — Scenario Simulation"
                    payload["data"] = result
                elif name == "phase2_9_tribunal":
                    # Tribunal results (result is dict from callback)
                    payload["label"] = "Phase 2.9 — Scenario Tribunal"
                    payload["data"] = result
                elif name == "phase2_95_actions":
                    # Scenario-Action Mapping results
                    payload["label"] = "Phase 2.95 — Scenario-Action Mapping"
                    payload["data"] = result
                elif name == "phase3_xheart":
                    # INTERNAL — only expose synthesis status
                    payload["data"] = {
                        "has_synthesis": result.synthesis is not None,
                        "is_layer_3": result.is_layer_3,
                    }
                elif name == "phase3_5_historical":
                    # Historical Resonance results (result is dict)
                    payload["label"] = "Phase 3.5 — Historical Resonance"
                    payload["data"] = result
                elif name == "phase3_7_strategic":
                    # Strategic Foresight results (result is dict)
                    payload["label"] = "Phase 3.7 — Strategic Foresight"
                    payload["data"] = result
                elif name == "phase3_9_bets":
                    # Decision Triggers + Bets results (result is dict)
                    payload["label"] = "Phase 3.9 — Decision Triggers"
                    payload["data"] = result
                elif name == "phase3_95_executive_brief":
                    # Executive Intelligence Brief (result is dict)
                    payload["label"] = "Phase 3.95 — Executive Intelligence Brief"
                    payload["data"] = result
                elif name == "xheart_expansion":
                    # Self-generated layer info (result is list[dict])
                    for layer in result:
                        exp_payload = {
                            "phase": "xheart_expansion",
                            "label": f"⟳ Self-Generated Layer: {layer.get('layer_name', '?')}",
                            "elapsed": round(phase_elapsed, 2),
                            "data": {
                                "layer_name": layer.get("layer_name", ""),
                                "layer_type": layer.get("layer_type", ""),
                                "gap_description": layer.get("gap_description", ""),
                                "key_insight": layer.get("key_insight", ""),
                            },
                        }
                        event_queue.put(("phase", json.dumps(exp_payload, ensure_ascii=False)))
                    return  # already pushed, skip default push
                elif name == "phase4_memory":
                    payload["data"] = result
                elif name == "evolution_deployed":
                    # Evolution tool deployment notification
                    payload["label"] = "Evolution — Tool Deployed"
                    payload["data"] = result
                else:
                    # Generic handler for any other phase — ensure serializable
                    try:
                        payload["data"] = result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result)
                    except Exception:
                        payload["data"] = {"info": str(result)[:500]}

                try:
                    event_queue.put(("phase", json.dumps(payload, ensure_ascii=False)))
                except (TypeError, ValueError) as ser_err:
                    logger.warning("[API/SSE] Failed to serialize phase '%s': %s", name, ser_err)
                    payload["data"] = {"info": f"Phase {name} completed (data not serializable)"}
                    event_queue.put(("phase", json.dumps(payload, ensure_ascii=False)))

            # Build ClientProfile if provided in stream request
            stream_profile = None
            if req.client_profile:
                stream_profile = ClientProfile(**req.client_profile.model_dump())

            result = _framework.run(
                problem=req.problem,
                callback=on_phase,
                client_profile=stream_profile,
            )

            total_elapsed = time.time() - pipeline_t0
            final_payload = {
                "problem": result.problem,
                "reframed_problem": result.phase0_ontology.reframed_problem,
                "final_output": result.final_output,
                "falsifiability": result.falsifiability,
                "layer": result.layer.value,
                "domains_used": [d.domain for d in result.phase1_xdart.domains_analyzed],
                "views_used": [v.view_name for v in result.phase2_views.views_applied],
                "convergent_patterns": result.phase2_views.convergent_patterns,
                "xheart_has_synthesis": result.phase3_xheart.synthesis is not None,
                "expansion_triggered": result.expansion_triggered,
                "expansion_layer": (
                    result.self_generated_layers[0].get("layer_name", "")
                    if result.self_generated_layers else None
                ),
                # Phase 3.5 — Historical Resonance
                "historical_resonance": (
                    result.phase3_5_historical.model_dump()
                    if result.phase3_5_historical else None
                ),
                # Phase 3.7 — Strategic Foresight
                "strategic_foresight": (
                    result.phase3_7_strategic.model_dump()
                    if result.phase3_7_strategic else None
                ),
                # Phase 2.95 — Scenario-Action Mapping
                "scenario_actions": (
                    result.phase2_95_actions.model_dump()
                    if result.phase2_95_actions else None
                ),
                # Phase 3.9 — Decision Triggers + Bets
                "decision_triggers": result.phase3_9_bets,
                "memory_count": _framework.memory.entry_count,
                "concept_count": _framework.memory.concept_count,
                "total_elapsed": round(total_elapsed, 2),

                # ── FULL DOSSIER DATA (for Intelligence Dossier PDF) ──
                # Phase 0 — Ontology (full)
                "dossier_ontology": {
                    "original_problem": result.phase0_ontology.original_problem,
                    "ontological_nature": result.phase0_ontology.ontological_nature,
                    "teleological_purpose": result.phase0_ontology.teleological_purpose,
                    "causal_analysis": result.phase0_ontology.causal_analysis,
                    "epistemological_check": result.phase0_ontology.epistemological_check,
                    "reframed_problem": result.phase0_ontology.reframed_problem,
                },
                # Phase 1 — Cross-Domain (full)
                "dossier_cross_domain": {
                    "domains": [
                        {
                            "domain": d.domain,
                            "core_mechanism": d.core_mechanism,
                            "transfer_hypothesis": d.transfer_hypothesis,
                            "analogy_strength": d.analogy_strength.value if hasattr(d.analogy_strength, 'value') else str(d.analogy_strength),
                        }
                        for d in result.phase1_xdart.domains_analyzed
                    ],
                    "strongest_analogy": {
                        "domain": result.phase1_xdart.strongest_analogy.domain,
                        "core_mechanism": result.phase1_xdart.strongest_analogy.core_mechanism,
                        "transfer_hypothesis": result.phase1_xdart.strongest_analogy.transfer_hypothesis,
                    },
                    "structural_formula": result.phase1_xdart.structural_formula,
                    "layer_3_hypothesis": result.phase1_xdart.layer_3_hypothesis,
                    "layer": result.phase1_xdart.layer.value,
                },
                # Phase 2 — Views (full insights)
                "dossier_views": {
                    "views": [
                        {
                            "view_id": v.view_id,
                            "view_name": v.view_name,
                            "insight": v.insight,
                        }
                        for v in result.phase2_views.views_applied
                    ],
                    "convergent_patterns": result.phase2_views.convergent_patterns,
                    "divergent_insights": result.phase2_views.divergent_insights,
                    "dominant_pattern": result.phase2_views.dominant_pattern,
                },
                # Phase 2.5 — Scenarios (full)
                "dossier_scenarios": (
                    {
                        "scenarios": [
                            {
                                "id": s.id,
                                "name": s.name,
                                "narrative": s.narrative,
                                "confidence": s.confidence,
                                "timeline": s.timeline,
                                "predicted_outcome": s.predicted_outcome,
                                "falsifiability": s.falsifiability,
                            }
                            for s in result.phase2_5_scenarios.scenarios
                        ],
                        "generation_logic": result.phase2_5_scenarios.generation_logic,
                    }
                    if result.phase2_5_scenarios else None
                ),
                # Phase 2.7 — Simulations (full)
                "dossier_simulations": (
                    {
                        "simulations": [
                            {
                                "scenario_name": sim.scenario_name,
                                "forward_projection": sim.forward_projection,
                                "stress_test_results": sim.stress_test_results,
                                "breakpoints": [
                                    {
                                        "at_step": bp.at_step,
                                        "reason": bp.reason,
                                        "severity": bp.severity,
                                    }
                                    for bp in sim.breakpoints
                                ],
                                "robustness_score": sim.robustness_score,
                                "revised_confidence": sim.revised_confidence,
                                "simulation_insight": sim.simulation_insight,
                            }
                            for sim in result.phase2_7_simulations.simulations
                        ],
                        "simulation_summary": result.phase2_7_simulations.simulation_summary,
                    }
                    if result.phase2_7_simulations else None
                ),
                # Phase 2.9 — Tribunal (full)
                "dossier_tribunal": (
                    {
                        "verdicts": [
                            {
                                "scenario_name": v.scenario_name,
                                "final_score": v.final_score,
                                "evidence_strength": v.evidence_strength,
                                "internal_consistency": v.internal_consistency,
                                "feasibility_rank": v.feasibility_rank,
                                "reasoning": v.reasoning,
                            }
                            for v in result.phase2_9_tribunal.verdicts
                        ],
                        "dominant_scenario": result.phase2_9_tribunal.dominant_scenario.scenario_name,
                        "dominant_score": result.phase2_9_tribunal.dominant_scenario.final_score,
                        "convergence_points": result.phase2_9_tribunal.convergence_points,
                        "divergence_points": result.phase2_9_tribunal.divergence_points,
                        "tribunal_synthesis": result.phase2_9_tribunal.tribunal_synthesis,
                    }
                    if result.phase2_9_tribunal else None
                ),
                # Phase 3.95 — Executive Brief
                "executive_brief": (
                    result.executive_brief.model_dump()
                    if result.executive_brief else None
                ),
            }
            event_queue.put(("complete", json.dumps(final_payload, ensure_ascii=False)))

        except Exception as exc:
            logger.exception("[API/SSE] Pipeline error")
            event_queue.put(("error", json.dumps({"error": str(exc)})))

        event_queue.put(("done", None))

    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    async def event_generator():
        """Yield SSE events with periodic keepalive to prevent stream timeout."""
        POLL_INTERVAL = 30  # seconds — check queue every 30s
        MAX_IDLE = 3600     # seconds — hard cap: 1 hour with no events
        idle_elapsed = 0
        while True:
            try:
                event_type, data = await asyncio.get_event_loop().run_in_executor(
                    None, event_queue.get, True, POLL_INTERVAL
                )
                idle_elapsed = 0  # reset on any real event
            except Exception:
                # queue.Empty — no event within POLL_INTERVAL seconds
                idle_elapsed += POLL_INTERVAL
                if idle_elapsed >= MAX_IDLE:
                    logger.warning("[API/SSE] Stream idle timeout (%ds) — closing", MAX_IDLE)
                    break
                # Send SSE keepalive comment to prevent browser/proxy timeout
                yield {"event": "heartbeat", "data": json.dumps({"keepalive": True, "idle": idle_elapsed})}
                continue

            if event_type == "done":
                break

            yield {"event": event_type, "data": data}

    return EventSourceResponse(event_generator())


@app.get("/xdart/core_changes")
async def get_core_changes(limit: int = 20):
    """Read proposed core changes from the append-only log."""
    cl = CoreChangeLogger()
    all_entries = cl.read_all()
    return {
        "total": len(all_entries),
        "recent": all_entries[-limit:],
    }


@app.get("/xdart/curiosities")
async def get_curiosities():
    """Return active curiosities and recent explorations from the autonomous curiosity engine."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")
    if not _framework.curiosity_engine:
        return {"enabled": False, "active": [], "recent_explorations": [], "stats": {}}

    engine = _framework.curiosity_engine
    return {
        "enabled": True,
        "active": [c.to_dict() for c in engine.active_curiosities],
        "recent_explorations": [c.to_dict() for c in engine.recent_explorations],
        "stats": engine.get_stats(),
    }


@app.get("/xdart/curiosities/journal")
async def get_curiosity_journal(limit: int = 50):
    """Return recent entries from the curiosity journal (append-only log)."""
    import json as _json
    from xdart.config import CURIOSITY_JOURNAL_PATH
    journal_path = Path(CURIOSITY_JOURNAL_PATH)
    if not journal_path.exists():
        return {"total": 0, "entries": []}
    entries = []
    with open(journal_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
    return {
        "total": len(entries),
        "entries": entries[-limit:],
    }


# ── Entity Graph Visualization ──

@app.get("/xdart/system-audit")
async def get_system_audit():
    """Return the latest system integrity audit results."""
    if not _last_audit_result:
        return {"status": "pending", "message": "First audit has not run yet (runs 5min after startup, then every 2h)"}
    return _last_audit_result


# ── Live Events Map — geo-coded events for Leaflet visualization ──

# Country/region centroid fallback for events without explicit coordinates
_REGION_CENTROIDS: dict[str, list[float]] = {
    "US": [39.8, -98.6], "USA": [39.8, -98.6], "NORTH_AMERICA": [39.8, -98.6],
    "GB": [54.0, -2.0], "UK": [54.0, -2.0], "EUROPE": [50.0, 10.0],
    "FR": [46.6, 2.2], "DE": [51.2, 10.4], "IT": [42.5, 12.5],
    "RU": [55.8, 37.6], "RUSSIA": [55.8, 37.6],
    "CN": [35.0, 105.0], "CHINA": [35.0, 105.0], "EAST_ASIA": [35.0, 105.0],
    "JP": [36.2, 138.3], "KR": [36.5, 127.8], "KP": [40.0, 127.0],
    "IN": [20.6, 79.0], "INDIA": [20.6, 79.0], "SOUTH_ASIA": [20.6, 79.0],
    "PK": [30.4, 69.3], "BD": [23.7, 90.4],
    "BR": [-14.2, -51.9], "SOUTH_AMERICA": [-14.2, -51.9],
    "AU": [-25.3, 133.8], "OCEANIA": [-25.3, 133.8],
    "ZA": [-30.6, 22.9], "NG": [9.1, 8.7], "AFRICA": [1.0, 20.0],
    "EG": [26.8, 30.8], "MIDDLE_EAST": [29.0, 47.0], "MENA": [29.0, 47.0],
    "IL": [31.0, 35.0], "IR": [32.4, 53.7], "IQ": [33.2, 43.7],
    "SA": [24.0, 45.0], "TR": [39.9, 32.9], "UA": [48.4, 31.2],
    "SY": [35.0, 38.0], "LB": [33.9, 35.9], "YE": [15.6, 48.5],
    "AF": [33.9, 67.7], "MM": [19.8, 96.0], "TW": [23.7, 121.0],
    "PH": [12.9, 121.8], "VN": [16.0, 108.0], "TH": [15.9, 100.5],
    "ID": [-0.8, 113.9], "SE_ASIA": [10.0, 106.0], "SOUTHEAST_ASIA": [10.0, 106.0],
    "MX": [23.6, -102.5], "CO": [4.6, -74.3], "VE": [6.4, -66.6],
    "AR": [-38.4, -63.6], "CL": [-35.7, -71.5],
    "PL": [51.9, 19.1], "RO": [45.9, 25.0], "GR": [39.1, 21.8],
    "CENTRAL_ASIA": [41.0, 65.0], "GLOBAL": [20.0, 0.0], "MULTI": [20.0, 0.0],
}

# Headline keyword → [lat, lon] for geocoding news articles without explicit coords
import re as _re
_HEADLINE_GEO_PATTERNS: list[tuple[_re.Pattern, list[float]]] = [
    (_re.compile(r'\bIran\b', _re.I),                [32.4, 53.7]),
    (_re.compile(r'\bTehran\b', _re.I),              [35.7, 51.4]),
    (_re.compile(r'\bIraq\b|Baghdad\b', _re.I),      [33.2, 43.7]),
    (_re.compile(r'\bSyria\b|Damascus\b', _re.I),    [35.0, 38.0]),
    (_re.compile(r'\bLebanon\b|Beirut\b', _re.I),    [33.9, 35.9]),
    (_re.compile(r'\bIsrael\b|Gaza\b|IDF\b', _re.I), [31.5, 34.8]),
    (_re.compile(r'\bYemen\b|Houthi', _re.I),        [15.6, 48.5]),
    (_re.compile(r'\bSaudi\b|Riyadh\b', _re.I),      [24.0, 45.0]),
    (_re.compile(r'\bGulf\b|Persian Gulf|Strait of Hormuz', _re.I), [26.5, 52.0]),
    (_re.compile(r'\bOman\b', _re.I),                [21.5, 57.0]),
    (_re.compile(r'\bUkrain', _re.I),                [48.4, 31.2]),
    (_re.compile(r'\bKyiv\b|Kiev\b', _re.I),         [50.4, 30.5]),
    (_re.compile(r'\bRussi|Moscow\b|Kremlin\b', _re.I), [55.8, 37.6]),
    (_re.compile(r'\bChina\b|Beijing\b', _re.I),     [39.9, 116.4]),
    (_re.compile(r'\bTaiwan\b|Taipei\b', _re.I),     [23.7, 121.0]),
    (_re.compile(r'\bNorth Korea\b|Pyongyang\b|DPRK\b', _re.I), [40.0, 127.0]),
    (_re.compile(r'\bSouth Korea\b|Seoul\b', _re.I), [37.6, 127.0]),
    (_re.compile(r'\bJapan\b|Tokyo\b', _re.I),       [35.7, 139.7]),
    (_re.compile(r'\bIndia\b|Delhi\b|Mumbai\b', _re.I), [20.6, 79.0]),
    (_re.compile(r'\bPakistan\b|Islamabad\b', _re.I), [30.4, 69.3]),
    (_re.compile(r'\bAfghan', _re.I),                [33.9, 67.7]),
    (_re.compile(r'\bMyanmar\b|Burma\b', _re.I),     [19.8, 96.0]),
    (_re.compile(r'\bIndonesi', _re.I),              [-0.8, 113.9]),
    (_re.compile(r'\bPhilippin', _re.I),             [12.9, 121.8]),
    (_re.compile(r'\bSoutheast Asia\b|ASEAN\b', _re.I), [10.0, 106.0]),
    (_re.compile(r'\bEurop\b|EU\b|Brussels\b', _re.I), [50.8, 4.4]),
    (_re.compile(r'\bGerman|Berlin\b', _re.I),        [52.5, 13.4]),
    (_re.compile(r'\bFranc\b|Paris\b|Macron\b', _re.I), [48.9, 2.3]),
    (_re.compile(r'\bBritain\b|London\b', _re.I),     [51.5, -0.1]),
    (_re.compile(r'\bItaly\b|Rome\b', _re.I),         [41.9, 12.5]),
    (_re.compile(r'\bPoland\b|Warsaw\b', _re.I),      [52.2, 21.0]),
    (_re.compile(r'\bTurk|Ankara\b|Erdogan\b', _re.I), [39.9, 32.9]),
    (_re.compile(r'\bEgypt\b|Cairo\b', _re.I),        [30.0, 31.2]),
    (_re.compile(r'\bLibya\b|Tripoli\b', _re.I),      [32.9, 13.2]),
    (_re.compile(r'\bSudan\b|Khartoum\b', _re.I),     [15.6, 32.5]),
    (_re.compile(r'\bSomal', _re.I),                  [5.2, 46.2]),
    (_re.compile(r'\bNigeri', _re.I),                  [9.1, 8.7]),
    (_re.compile(r'\bSouth Africa\b', _re.I),          [-30.6, 22.9]),
    (_re.compile(r'\bEthiopi', _re.I),                 [9.0, 38.7]),
    (_re.compile(r'\bCongo\b|DRC\b', _re.I),           [-4.0, 21.8]),
    (_re.compile(r'\bMexico\b', _re.I),                [23.6, -102.5]),
    (_re.compile(r'\bBrazil\b', _re.I),                [-14.2, -51.9]),
    (_re.compile(r'\bVenezuel', _re.I),                [6.4, -66.6]),
    (_re.compile(r'\bColombi', _re.I),                 [4.6, -74.3]),
    (_re.compile(r'\bArgentin', _re.I),                [-38.4, -63.6]),
    (_re.compile(r'\bCanad', _re.I),                   [56.1, -106.3]),
    (_re.compile(r'\bAustrali', _re.I),                [-25.3, 133.8]),
    (_re.compile(r'\bU\.?S\.?\b|United States|Washington|Pentagon|White House|Trump|Biden', _re.I), [38.9, -77.0]),
    (_re.compile(r'\bMiddle East\b', _re.I),           [29.0, 47.0]),
    (_re.compile(r'\bAsia\b', _re.I),                  [30.0, 100.0]),
    (_re.compile(r'\bAfrica\b', _re.I),                [1.0, 20.0]),
    (_re.compile(r'\bSuez\b', _re.I),                  [30.0, 32.3]),
    (_re.compile(r'\bRed Sea\b', _re.I),               [20.0, 38.5]),
    (_re.compile(r'\bSouth China Sea\b', _re.I),       [12.0, 114.0]),
    (_re.compile(r'\bBlack Sea\b', _re.I),             [43.0, 34.0]),
    (_re.compile(r'\bArctic\b', _re.I),                [71.0, 0.0]),
    (_re.compile(r'\bHong Kong\b', _re.I),             [22.3, 114.2]),
    (_re.compile(r'\bSingapore\b', _re.I),             [1.3, 103.8]),
]


def _geocode_headline(headline: str) -> tuple[float, float] | None:
    """Try to extract geographic coordinates from headline text."""
    if not headline:
        return None
    for pattern, coords in _HEADLINE_GEO_PATTERNS:
        if pattern.search(headline):
            return (coords[0], coords[1])
    return None


def _extract_coords(event: dict) -> tuple[float, float] | None:
    """Extract [lat, lon] from an event's raw_payload or region.

    Tries multiple source formats:
    - raw_payload.coordinates = [lon, lat] (USGS, EONET, UCDP, GDACS, GDELT)
    - raw_payload.latitude / raw_payload.longitude (ACLED)
    - region_focus → centroid fallback
    """
    rp = event.get("raw_payload")
    if isinstance(rp, dict):
        # Direct coordinates array: [lon, lat, ...]
        coords = rp.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon, lat = float(coords[0]), float(coords[1])
                if -180 <= lon <= 180 and -90 <= lat <= 90 and (lon != 0 or lat != 0):
                    return (lat, lon)
            except (ValueError, TypeError):
                pass

        # ACLED-style: separate lat/lon fields
        lat_val = rp.get("latitude")
        lon_val = rp.get("longitude")
        if lat_val is not None and lon_val is not None:
            try:
                lat, lon = float(lat_val), float(lon_val)
                if -180 <= lon <= 180 and -90 <= lat <= 90 and (lon != 0 or lat != 0):
                    return (lat, lon)
            except (ValueError, TypeError):
                pass

    # Headline-based geocoding (more accurate than generic region)
    headline = event.get("headline", "")
    geo = _geocode_headline(headline)
    if geo:
        return geo

    # Fallback: region centroid
    regions = event.get("region_focus", [])
    if isinstance(regions, list):
        for r in regions:
            centroid = _REGION_CENTROIDS.get(str(r).upper())
            if centroid:
                return (centroid[0], centroid[1])

    source_region = event.get("source_region", "")
    centroid = _REGION_CENTROIDS.get(str(source_region).upper())
    if centroid:
        return (centroid[0], centroid[1])

    return None


@app.get("/xdart/events/geo")
async def get_geo_events(
    hours_back: int = 48,
    max_events: int = 500,
    min_salience: float = 0.3,
):
    """Return geo-coded events for the live map visualization.

    Extracts coordinates from raw_payload (GDELT, USGS, ACLED, EONET, UCDP, GDACS)
    or falls back to region centroids. Returns lightweight GeoJSON-like array.
    """
    from xdart.perception.db import PerceptionDB

    db = PerceptionDB(db_path=PERCEPTION_DB_PATH)
    events = db.get_recent_events(hours_back=hours_back, max_events=max_events)

    features = []
    for ev in events:
        salience = ev.get("salience_score", 0)
        if salience < min_salience:
            continue

        coords = _extract_coords(ev)
        if not coords:
            continue

        rp = ev.get("raw_payload", {}) or {}
        is_precise = bool(
            (isinstance(rp.get("coordinates"), (list, tuple)) and len(rp.get("coordinates", [])) >= 2)
            or (rp.get("latitude") is not None and rp.get("longitude") is not None)
        )

        features.append({
            "lat": round(coords[0], 4),
            "lon": round(coords[1], 4),
            "precise": is_precise,
            "headline": ev.get("headline", "")[:200],
            "domain": ev.get("domain", "MULTI"),
            "source": ev.get("source_name", ""),
            "salience": round(salience, 2),
            "collected_at": ev.get("collected_at", ""),
            "published_at": ev.get("published_at", ""),
        })

    return {
        "features": features,
        "total": len(features),
        "hours_back": hours_back,
    }


@app.get("/xdart/entity-graph/data")
async def get_entity_graph_data(
    entity_filter: str = "",
    entity_type: str = "",
    max_nodes: int = 150,
    min_mentions: int = 2,
):
    """Return entity graph data as JSON for external renderers."""
    if not _framework or not getattr(_framework, "_entity_graph", None):
        raise HTTPException(status_code=503, detail="Entity graph not available")
    return _framework._entity_graph.export_vis_data(
        entity_filter=entity_filter,
        entity_type=entity_type,
        max_nodes=max_nodes,
        min_mentions=min_mentions,
    )


@app.get("/xdart/entity-graph/vis", response_class=HTMLResponse)
async def entity_graph_visualization(
    entity_filter: str = "",
    entity_type: str = "",
    max_nodes: int = 150,
    min_mentions: int = 2,
):
    """Interactive entity relationship map — force-directed vis.js graph."""
    if not _framework or not getattr(_framework, "_entity_graph", None):
        raise HTTPException(status_code=503, detail="Entity graph not available")

    vis_data = _framework._entity_graph.export_vis_data(
        entity_filter=entity_filter,
        entity_type=entity_type,
        max_nodes=max_nodes,
        min_mentions=min_mentions,
    )

    nodes_json = json.dumps(vis_data["nodes"], ensure_ascii=False)
    edges_json = json.dumps(vis_data["edges"], ensure_ascii=False)
    meta = vis_data["meta"]
    legend_json = json.dumps(meta.get("type_legend", {}), ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>XDART-Φ Entity Graph — Αίολος</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0e17; color: #c0c8d8; font-family: 'Segoe UI', system-ui, sans-serif; }}
  #graph {{ width: 100vw; height: 100vh; }}
  #controls {{
    position: fixed; top: 12px; left: 12px; z-index: 10;
    background: rgba(10,14,23,0.92); border: 1px solid #1e2a40; border-radius: 8px;
    padding: 14px 18px; max-width: 340px; font-size: 13px;
  }}
  #controls h2 {{ color: #4A90D9; font-size: 15px; margin-bottom: 8px; }}
  #controls .stat {{ color: #7a8ba8; margin: 2px 0; }}
  #legend {{ margin-top: 10px; }}
  #legend .item {{ display: inline-flex; align-items: center; margin: 3px 8px 3px 0; }}
  #legend .dot {{ width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }}
  #search-box {{
    margin-top: 10px; width: 100%; padding: 6px 10px;
    background: #111827; border: 1px solid #2a3a55; border-radius: 4px;
    color: #c0c8d8; font-size: 13px; outline: none;
  }}
  #search-box:focus {{ border-color: #4A90D9; }}
  #tooltip {{
    position: fixed; display: none; z-index: 20;
    background: rgba(10,14,23,0.95); border: 1px solid #4A90D9; border-radius: 6px;
    padding: 10px 14px; max-width: 350px; font-size: 12px; pointer-events: none;
  }}
  #tooltip h3 {{ color: #4A90D9; font-size: 14px; margin-bottom: 4px; }}
  #tooltip .kv {{ color: #7a8ba8; }}
</style>
</head>
<body>
<div id="controls">
  <h2>XDART-Φ Entity Graph</h2>
  <div class="stat">Nodes: {meta['displayed_nodes']} / {meta['total_nodes']}</div>
  <div class="stat">Edges: {meta['displayed_edges']} / {meta['total_edges']}</div>
  <div class="stat">Headlines ingested: {meta['headlines_ingested']:,}</div>
  <div id="legend"></div>
  <input id="search-box" type="text" placeholder="Search entities..." />
</div>
<div id="tooltip"></div>
<div id="graph"></div>
<script>
const rawNodes = {nodes_json};
const rawEdges = {edges_json};
const legend  = {legend_json};

// Build legend
const legendEl = document.getElementById('legend');
Object.entries(legend).forEach(([type, color]) => {{
  legendEl.innerHTML += '<span class="item"><span class="dot" style="background:'+color+'"></span>'+type+'</span>';
}});

// vis.js DataSets
const nodes = new vis.DataSet(rawNodes.map(n => ({{
  id: n.id, label: n.label, color: {{ background: n.color, border: n.color, highlight: {{ background: '#fff', border: n.color }} }},
  size: n.size, font: {{ color: '#c0c8d8', size: Math.max(10, n.size * 0.7) }},
  title: n.type + ' | ' + n.mentions + ' mentions',
  _raw: n,
}})));

const edges = new vis.DataSet(rawEdges.map((e, i) => ({{
  id: i, from: e.source, to: e.target, width: e.width,
  color: {{ color: 'rgba(100,140,200,0.3)', highlight: '#4A90D9' }},
  _raw: e,
}})));

const container = document.getElementById('graph');
const network = new vis.Network(container, {{ nodes, edges }}, {{
  physics: {{
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {{
      gravitationalConstant: -350,
      centralGravity: 0.004,
      springLength: 280,
      springConstant: 0.035,
      damping: 0.42,
      avoidOverlap: 0.6,
    }},
    stabilization: {{ iterations: 350, updateInterval: 25 }},
    maxVelocity: 40,
    minVelocity: 0.75,
  }},
  interaction: {{ hover: true, tooltipDelay: 100, zoomView: true, dragView: true, navigationButtons: false, keyboard: true }},
  nodes: {{ shape: 'dot', borderWidth: 2 }},
  edges: {{ smooth: {{ type: 'continuous', roundness: 0.15 }}, arrows: {{ to: false }} }},
}});

// Tooltip on hover
const tooltip = document.getElementById('tooltip');
network.on('hoverNode', function(params) {{
  const nodeData = nodes.get(params.node)._raw;
  tooltip.innerHTML = '<h3>' + nodeData.label + '</h3>'
    + '<div class="kv">Type: ' + nodeData.type + '</div>'
    + '<div class="kv">Mentions: ' + nodeData.mentions + '</div>'
    + '<div class="kv">Activity: ' + nodeData.activity_score + '</div>'
    + (nodeData.last_seen_iso ? '<div class="kv">Last: ' + new Date(nodeData.last_seen_iso).toLocaleString() + '</div>' : '');
  tooltip.style.display = 'block';
  tooltip.style.left = params.event.center.x + 15 + 'px';
  tooltip.style.top = params.event.center.y + 15 + 'px';
}});
network.on('blurNode', () => {{ tooltip.style.display = 'none'; }});

// Click node → show connected edges' headlines
network.on('click', function(params) {{
  if (params.nodes.length === 1) {{
    const nid = params.nodes[0];
    const connected = network.getConnectedEdges(nid);
    let headlines = [];
    connected.forEach(eid => {{
      const ed = edges.get(eid)._raw;
      if (ed.recent_headlines) headlines = headlines.concat(ed.recent_headlines);
    }});
    if (headlines.length) {{
      tooltip.innerHTML = '<h3>' + nid + ' — Recent Headlines</h3>'
        + headlines.slice(0, 8).map(h => '<div class="kv">• ' + h + '</div>').join('');
      tooltip.style.display = 'block';
      tooltip.style.left = params.event.center.x + 15 + 'px';
      tooltip.style.top = params.event.center.y + 15 + 'px';
    }}
  }}
}});

// Search
document.getElementById('search-box').addEventListener('input', function(e) {{
  const q = e.target.value.toLowerCase();
  if (!q) {{
    nodes.forEach(n => nodes.update({{ id: n.id, hidden: false }}));
    return;
  }}
  nodes.forEach(n => {{
    const match = n.label.toLowerCase().includes(q);
    nodes.update({{ id: n.id, hidden: !match, opacity: match ? 1 : 0.1 }});
  }});
  // Focus on first match
  const match = rawNodes.find(n => n.label.toLowerCase().includes(q));
  if (match) network.focus(match.id, {{ scale: 1.2, animation: true }});
}});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/xdart/prophecies")
async def get_prophecies(limit: int = 50, status: str | None = None):
    """Return all stored prophecies with full scenario details.

    Query params:
        limit:  Max entries to return (default 50).
        status: Filter by tracking_status — active | tracking | confirmed | disconfirmed | expired.
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    def _get():
        all_entries = _framework.prophetic_memory.list_all(limit=limit)

        if status:
            entries = [e for e in all_entries if e.get("tracking_status") == status]
        else:
            entries = all_entries

        prophecies = []
        for e in entries:
            scenario = e.get("scenario", {})
            simulation = e.get("simulation", {})
            prophecies.append({
                "id": e.get("id", ""),
                "timestamp": e.get("timestamp", ""),
                "problem": e.get("problem", ""),
                "tracking_status": e.get("tracking_status", "active"),
                "was_dominant": e.get("was_dominant", False),
                "tribunal_rank": e.get("tribunal_rank", 99),
                "tribunal_score": e.get("tribunal_score", 0.0),
                "scenario": {
                    "name": scenario.get("name", ""),
                    "narrative": scenario.get("narrative", ""),
                    "predicted_outcome": scenario.get("predicted_outcome", ""),
                    "confidence": scenario.get("confidence", 0.0),
                    "timeframe": scenario.get("timeframe", ""),
                    "key_indicators": scenario.get("key_indicators", []),
                    "falsifiable_markers": scenario.get("falsifiable_markers", []),
                },
                "simulation": {
                    "robustness_score": simulation.get("robustness_score", 0.0),
                    "forward_projection": simulation.get("forward_projection", ""),
                    "breakpoints": simulation.get("breakpoints", []),
                },
                "reality_checks": e.get("reality_checks", []),
            })

        return {
            "total": _framework.prophetic_memory.entry_count,
            "returned": len(prophecies),
            "prophecies": prophecies,
        }

    return await asyncio.get_event_loop().run_in_executor(None, _get)


# ── Autonomous Prophecies — approve/reject ──

@app.get("/xdart/prophecies/autonomous")
async def get_autonomous_prophecies():
    """List all autonomous prophecies awaiting approval."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    def _get():
        return _framework.prophetic_memory.list_autonomous_pending()

    pending = await asyncio.get_event_loop().run_in_executor(None, _get)
    return {"pending": pending, "count": len(pending)}


@app.post("/xdart/prophecies/autonomous/{entry_id}/approve")
async def approve_autonomous_prophecy(entry_id: str):
    """Approve an autonomous prophecy — promotes it to active tracking."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    def _approve():
        return _framework.prophetic_memory.approve_autonomous_prophecy(entry_id)

    success = await asyncio.get_event_loop().run_in_executor(None, _approve)
    if not success:
        raise HTTPException(status_code=404, detail=f"Entry '{entry_id}' not found or not in autonomous_proposed status")
    return {"status": "active", "entry_id": entry_id}


@app.post("/xdart/prophecies/autonomous/{entry_id}/reject")
async def reject_autonomous_prophecy(entry_id: str, reason: str = ""):
    """Reject an autonomous prophecy."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    def _reject():
        return _framework.prophetic_memory.reject_autonomous_prophecy(entry_id, reason=reason)

    success = await asyncio.get_event_loop().run_in_executor(None, _reject)
    if not success:
        raise HTTPException(status_code=404, detail=f"Entry '{entry_id}' not found or not in autonomous_proposed status")
    return {"status": "rejected", "entry_id": entry_id, "reason": reason}


@app.get("/xdart/accuracy")
async def get_prediction_accuracy():
    """Return Brier-score based prediction accuracy stats.

    Brier score: 0.0 = perfect, 1.0 = worst.
    Rating: excellent (<0.1), good (<0.25), fair (<0.5), poor (>=0.5).
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    return await asyncio.get_event_loop().run_in_executor(
        None, _framework.prophetic_memory.compute_accuracy_stats
    )


class KnowledgeInjectRequest(BaseModel):
    source: str = Field(description="Source identifier — e.g., academic_paper, expert_briefing, classified")
    content: str = Field(description="The knowledge text to inject into the next pipeline run")


@app.post("/xdart/knowledge/inject")
async def inject_knowledge(req: KnowledgeInjectRequest):
    """Inject external knowledge into the next pipeline run.

    Use for: academic papers, domain expert inputs, classified briefings,
    or any contextual information the system should consider.
    Knowledge persists until cleared or the server restarts.
    """
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    total = _framework.inject_knowledge(source=req.source, content=req.content)
    return {"injected": True, "total_knowledge_entries": total}


@app.get("/xdart/knowledge/external")
async def list_external_knowledge():
    """List all currently injected external knowledge."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    entries = _framework.list_knowledge()
    return {"count": len(entries), "entries": entries}


@app.delete("/xdart/knowledge/external")
async def clear_external_knowledge():
    """Clear all injected external knowledge."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    cleared = _framework.clear_knowledge()
    return {"cleared": cleared}


@app.get("/xdart/world_context")
async def get_world_context():
    """Return current world perception status and recent events."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    if not _framework.world_context:
        return {
            "enabled": False,
            "message": "Perception layer is disabled",
        }

    status = _framework.world_context.status()
    return {
        "enabled": True,
        **status,
    }


@app.get("/xdart/knowledge")
async def get_knowledge():
    """Return comprehensive view of everything the framework currently knows."""
    if not _framework:
        raise HTTPException(status_code=503, detail="Framework not initialized")

    # 1. World perception
    perception = {"enabled": False}
    if _framework.world_context:
        try:
            from xdart.perception.db import PerceptionDB
            db = PerceptionDB(db_path=PERCEPTION_DB_PATH)
            events_raw = db.get_recent_events(hours_back=72, max_events=30)
            events = [
                {
                    "headline": e.get("headline", ""),
                    "source": e.get("source_name", ""),
                    "domain": e.get("domain", ""),
                    "content_type": e.get("content_type", ""),
                    "salience": e.get("salience_score", 0),
                    "collected_at": e.get("collected_at", ""),
                }
                for e in events_raw
            ]
            econ_raw = db.get_recent_economic(max_indicators=20)
            indicators = [
                {
                    "indicator": e.get("indicator", ""),
                    "value": e.get("value"),
                    "unit": e.get("unit", ""),
                    "period": e.get("period", ""),
                    "change_pct": e.get("change_pct"),
                    "source": e.get("source", ""),
                }
                for e in econ_raw
            ]
            perception = {
                "enabled": True,
                "total_events": db.event_count(),
                "total_economic": db.economic_count(),
                "events": events,
                "indicators": indicators,
            }
        except Exception as exc:
            logger.warning("[Knowledge] Perception query failed: %s", exc)
            perception = {"enabled": True, "error": str(exc)}

    # 2. Episodic memories
    memories = _framework.memory.list_all_memories(limit=50)

    # 3. Concept registry
    concepts = _framework.memory.list_all_concepts(limit=100)

    # 4. Character state
    character = {}
    try:
        with open(CHARACTER_STATE_PATH, "r", encoding="utf-8") as f:
            character = json.load(f)
    except Exception:
        pass

    # 5. Immediate memory
    immediate = {}
    try:
        with open(IMMEDIATE_MEMORY_PATH, "r", encoding="utf-8") as f:
            immediate = json.load(f)
    except Exception:
        pass

    return {
        "perception": perception,
        "memories": {
            "count": _framework.memory.entry_count,
            "entries": memories,
        },
        "concepts": {
            "count": _framework.memory.concept_count,
            "entries": concepts,
        },
        "character": {
            "version": character.get("version", 0),
            "epistemic_stance": character.get("current_epistemic_stance", "")[:500],
            "tensions_count": len(character.get("active_tensions", [])),
            "tensions": character.get("active_tensions", [])[:5],
            "concepts_owned": character.get("named_concepts_owned", []),
            "changes_count": len(character.get("how_i_have_changed", [])),
        },
        "immediate_memory": {
            "recent_runs": immediate.get("recent_runs", []),
        },
    }


@app.get("/xdart/intelligence")
async def get_intelligence():
    """Live intelligence dashboard data — CII scores, trending keywords, spikes,
    infrastructure status, and correlation alerts."""
    from xdart.perception.country_risk import (
        CURATED_COUNTRIES, estimate_cii_from_events, compute_strategic_cii_score,
    )
    from xdart.perception.infrastructure import get_infrastructure_graph
    from xdart.perception.keyword_spikes import KeywordSpikeDetector

    result = {
        "cii_scores": {},
        "strategic_risk_score": 0.0,
        "trending_keywords": [],
        "recent_spikes": [],
        "infrastructure": {"nodes": 0, "edges": 0},
        "perception_sources": 0,
        "total_events_24h": 0,
    }

    # Trending keywords and spikes from collector's spike detector
    if _collector and hasattr(_collector, "spike_detector"):
        detector = _collector.spike_detector
        result["trending_keywords"] = detector.get_trending_terms(15)
        raw_spikes = detector.get_recent_spikes(max_age_seconds=3600)
        result["recent_spikes"] = [
            {
                "term": s.term,
                "count": s.current_count,
                "sources": s.unique_sources,
                "surge_ratio": s.surge_ratio,
                "detected_at": s.detected_at,
            }
            for s in raw_spikes[:10]
        ]

    # CII scores from recent perception events
    try:
        from xdart.perception.db import PerceptionDB
        db = PerceptionDB(db_path=PERCEPTION_DB_PATH)
        events_raw = db.get_recent_events(hours_back=24, max_events=200)
        result["total_events_24h"] = len(events_raw)

        # Group events by detected country codes
        from xdart.perception.country_risk import detect_countries_in_text
        country_events: dict[str, list[dict]] = {}
        for ev in events_raw:
            text = f"{ev.get('headline', '')} {ev.get('summary', '')}"
            detections = detect_countries_in_text(text)
            for code, _ in detections[:2]:
                country_events.setdefault(code, []).append(ev)

        # Compute CII for countries with events
        cii_scores = {}
        for code, c_events in country_events.items():
            if len(c_events) >= 2:  # need at least 2 events for meaningful score
                cii = estimate_cii_from_events(code, c_events)
                profile = CURATED_COUNTRIES.get(code)
                cii_scores[code] = {
                    "score": cii,
                    "name": profile.name if profile else code,
                    "event_count": len(c_events),
                    "tier": "curated" if code in CURATED_COUNTRIES else "auto",
                }

        # Sort by score descending
        result["cii_scores"] = dict(
            sorted(cii_scores.items(), key=lambda x: x[1]["score"], reverse=True)
        )
        result["strategic_risk_score"] = compute_strategic_cii_score(
            {k: v["score"] for k, v in cii_scores.items()}
        )
    except Exception as exc:
        logger.warning("[Intelligence] CII computation failed: %s", exc)

    # Infrastructure graph stats
    try:
        graph = get_infrastructure_graph()
        result["infrastructure"] = {
            "nodes": graph.node_count,
            "edges": graph.edge_count,
        }
    except Exception:
        pass

    # Perception source count
    if _collector and hasattr(_collector, "status"):
        try:
            coll_status = _collector.status()
            result["perception_sources"] = coll_status.get("rss_sources", 0)
        except Exception:
            pass

    return result


@app.get("/xdart/briefing")
async def get_daily_briefing():
    """Daily Intelligence Briefing — executive summary of the perception layer.

    Returns a structured briefing with:
    - Top CII movers (biggest changes)
    - Key economic indicators (FX, commodities, macro)
    - Trending keywords and active spikes
    - Correlation alerts (cross-stream patterns)
    - Infrastructure risk status
    """
    from xdart.perception.country_risk import (
        CURATED_COUNTRIES, estimate_cii_from_events, compute_strategic_cii_score,
        detect_countries_in_text,
    )
    from xdart.perception.db import PerceptionDB

    briefing = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategic_risk_score": 0.0,
        "top_cii_countries": [],
        "economic_snapshot": {
            "forex": [],
            "commodities": [],
            "macro": [],
        },
        "trending_terms": [],
        "active_spikes": [],
        "correlation_alerts": [],
        "event_summary": {
            "total_24h": 0,
            "by_domain": {},
            "by_source": {},
        },
        "narrative": "",
    }

    try:
        db = PerceptionDB(db_path=PERCEPTION_DB_PATH)

        # ── Events & CII ──
        events_raw = db.get_recent_events(hours_back=24, max_events=500)
        briefing["event_summary"]["total_24h"] = len(events_raw)

        # Count by domain and source
        domain_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for ev in events_raw:
            d = ev.get("domain", "UNKNOWN")
            domain_counts[d] = domain_counts.get(d, 0) + 1
            s = ev.get("source_name", "unknown")
            source_counts[s] = source_counts.get(s, 0) + 1
        briefing["event_summary"]["by_domain"] = dict(sorted(domain_counts.items(), key=lambda x: x[1], reverse=True))
        briefing["event_summary"]["by_source"] = dict(sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:15])

        # CII computation
        country_events: dict[str, list[dict]] = {}
        for ev in events_raw:
            text = f"{ev.get('headline', '')} {ev.get('summary', '')}"
            detections = detect_countries_in_text(text)
            for code, _ in detections[:2]:
                country_events.setdefault(code, []).append(ev)

        cii_scores: dict[str, float] = {}
        for code, c_events in country_events.items():
            if len(c_events) >= 2:
                cii = estimate_cii_from_events(code, c_events)
                cii_scores[code] = cii

        # Top 10 by CII score
        sorted_cii = sorted(cii_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        for code, score in sorted_cii:
            profile = CURATED_COUNTRIES.get(code)
            briefing["top_cii_countries"].append({
                "code": code,
                "name": profile.name if profile else code,
                "cii": round(score, 1),
                "event_count": len(country_events.get(code, [])),
            })

        briefing["strategic_risk_score"] = round(
            compute_strategic_cii_score(cii_scores), 1
        )

        # ── Economic Snapshot ──
        econ_data = db.get_recent_economic(max_indicators=100)
        for ind in econ_data:
            source = ind.get("source", "")
            indicator = ind.get("indicator", "")
            value = ind.get("value")
            unit = ind.get("unit", "")
            period = ind.get("period", "")

            entry = {
                "indicator": indicator,
                "value": value,
                "unit": unit,
                "period": period,
                "source": source,
            }

            if source == "ExchangeRate":
                briefing["economic_snapshot"]["forex"].append(entry)
            elif source == "Commodities":
                briefing["economic_snapshot"]["commodities"].append(entry)
            else:
                briefing["economic_snapshot"]["macro"].append(entry)

        # Deduplicate (keep latest per indicator)
        for category in ["forex", "commodities", "macro"]:
            seen: dict[str, dict] = {}
            for entry in briefing["economic_snapshot"][category]:
                key = entry["indicator"]
                if key not in seen:
                    seen[key] = entry
            briefing["economic_snapshot"][category] = list(seen.values())

        # ── Trending Keywords & Spikes ──
        if _collector and hasattr(_collector, "spike_detector"):
            detector = _collector.spike_detector
            briefing["trending_terms"] = detector.get_trending_terms(20)
            raw_spikes = detector.get_recent_spikes(max_age_seconds=86400)
            briefing["active_spikes"] = [
                {
                    "term": s.term,
                    "count": s.current_count,
                    "sources": s.unique_sources,
                    "surge_ratio": s.surge_ratio,
                    "detected_at": s.detected_at,
                }
                for s in raw_spikes[:15]
            ]

        # ── Correlation Alerts ──
        if _collector and hasattr(_collector, "correlation_engine"):
            engine = _collector.correlation_engine
            alerts = engine.get_recent_alerts(max_age=86400)
            briefing["correlation_alerts"] = [
                {
                    "alert_id": a.alert_id,
                    "severity": a.severity.value,
                    "country": a.country_code,
                    "summary": a.summary,
                    "signal_types": a.signal_types,
                    "merged_count": a.merged_count,
                }
                for a in alerts[:10]
            ]

        # ── Generate narrative summary ──
        lines = []
        lines.append(f"XDART-Φ DAILY INTELLIGENCE BRIEFING")
        lines.append(f"Generated: {briefing['generated_at'][:16]}Z")
        lines.append(f"Strategic Risk Score: {briefing['strategic_risk_score']}/100")
        lines.append(f"Events tracked (24h): {briefing['event_summary']['total_24h']}")
        lines.append("")

        if briefing["top_cii_countries"]:
            lines.append("TOP RISK COUNTRIES:")
            for c in briefing["top_cii_countries"][:5]:
                lines.append(f"  {c['name']} ({c['code']}): CII {c['cii']} — {c['event_count']} events")
            lines.append("")

        if briefing["economic_snapshot"]["commodities"]:
            lines.append("COMMODITIES:")
            for c in briefing["economic_snapshot"]["commodities"]:
                lines.append(f"  {c['indicator']}: {c['value']} {c['unit']}")
            lines.append("")

        if briefing["economic_snapshot"]["forex"]:
            lines.append("FOREX (vs USD):")
            for f in briefing["economic_snapshot"]["forex"][:5]:
                lines.append(f"  {f['indicator']}: {f['value']}")
            lines.append("")

        if briefing["trending_terms"]:
            top_terms = [t["term"] if isinstance(t, dict) else str(t) for t in briefing["trending_terms"][:10]]
            lines.append(f"TRENDING: {', '.join(top_terms)}")
            lines.append("")

        if briefing["active_spikes"]:
            lines.append("ACTIVE SPIKES:")
            for s in briefing["active_spikes"][:5]:
                lines.append(f"  '{s['term']}' — {s['count']}× from {s['sources']} sources (×{s['surge_ratio']:.1f} surge)")
            lines.append("")

        if briefing["correlation_alerts"]:
            lines.append("CORRELATION ALERTS:")
            for a in briefing["correlation_alerts"][:5]:
                lines.append(f"  [{a['severity'].upper()}] {a['summary']}")
            lines.append("")

        briefing["narrative"] = "\n".join(lines)

    except Exception as exc:
        logger.warning("[Briefing] Generation failed: %s", exc)
        briefing["narrative"] = f"Briefing generation failed: {exc}"

    return briefing


# ══════════════════════════════════════════════════════════════
#  PALANTIR: Scheduled Autonomous Briefing Endpoints
# ══════════════════════════════════════════════════════════════

@app.post("/xdart/briefing/now")
async def trigger_briefing_now():
    """Trigger an immediate Intelligence Brief generation.

    Αίολος assembles all live intelligence (patterns, hypotheses, macro synthesis,
    active prophecies, world events), synthesises via LLM, and delivers via
    Telegram + SSE. The full brief is returned in the response.

    This is the on-demand counterpart to the scheduled 06:00 daily brief.
    """
    if not _briefing_engine:
        return {
            "status": "error",
            "message": "Briefing engine not running — check BRIEFING_ENABLED in .env",
        }
    try:
        loop = asyncio.get_running_loop()
        brief = await loop.run_in_executor(None, _briefing_engine.force_generate)
        if not brief:
            return {"status": "error", "message": "Briefing generation returned no data — check logs"}
        return {
            "status": "ok",
            "brief": brief,
        }
    except Exception as exc:
        logger.error("[Briefing API] /now failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@app.get("/xdart/briefing/last")
async def get_last_intelligence_brief():
    """Return the most recently generated Intelligence Brief.

    If no brief has been generated yet, returns a status object.
    """
    if not _briefing_engine:
        return {
            "status": "unavailable",
            "message": "Briefing engine not running — check BRIEFING_ENABLED in .env",
        }
    last = _briefing_engine.get_last_brief()
    if not last:
        return {
            "status": "no_brief",
            "message": "No brief generated yet. Use POST /xdart/briefing/now to generate one.",
            "stats": _briefing_engine.stats(),
        }
    return {
        "status": "ok",
        "brief": last,
        "stats": _briefing_engine.stats(),
    }


@app.get("/xdart/briefing/history")
async def get_briefing_history(n: int = 10):
    """Return the last N Intelligence Briefs (newest first).

    Args:
        n: Number of briefs to return (max 30). Default 10.
    """
    if not _briefing_engine:
        return {
            "status": "unavailable",
            "message": "Briefing engine not running",
        }
    n = max(1, min(n, 30))
    return {
        "status": "ok",
        "count": n,
        "briefs": _briefing_engine.get_history(n),
        "stats": _briefing_engine.stats(),
    }


@app.get("/xdart/briefing/schedule")
async def get_briefing_schedule():
    """Return the briefing schedule and engine status.

    Shows: configured schedule, last brief time, next scheduled time,
    delivery statistics, and Telegram status.
    """
    if not _briefing_engine:
        return {
            "status": "unavailable",
            "enabled": False,
            "message": "Briefing engine not running — BRIEFING_ENABLED=false or startup failed",
        }
    stats = _briefing_engine.stats()
    return {
        "status": "ok",
        "enabled": True,
        **stats,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PALANTIR ΒΗΜΑ 1 — Typed Semantic Ontology Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/xdart/ontology/stats")
async def get_ontology_stats():
    """Ontology engine statistics — entity types, confidence buckets, relationship types."""
    if not _ontology_engine:
        return {"status": "unavailable", "message": "OntologyEngine not running"}
    return {"status": "ok", **_ontology_engine.stats()}


@app.get("/xdart/ontology/entities")
async def get_ontology_entities(
    min_confidence: float = 0.40,
    entity_type: str | None = None,
    limit: int = 50,
):
    """Return high-confidence typed entities.

    Args:
        min_confidence: minimum confidence threshold (0.0–1.0)
        entity_type: filter by type — person / organization / country / location / movement / bloc / event / concept
        limit: max results (capped at 200)
    """
    if not _ontology_engine:
        return {"status": "unavailable", "message": "OntologyEngine not running"}
    limit = min(200, max(1, limit))
    entities = _ontology_engine.get_high_confidence_entities(
        min_confidence=min_confidence,
        entity_type=entity_type,
        limit=limit,
    )
    return {"status": "ok", "count": len(entities), "entities": entities}


@app.get("/xdart/ontology/entity/{name:path}")
async def get_ontology_entity_profile(name: str):
    """Full entity profile: typed entity metadata + active relationships.

    Args:
        name: entity canonical name (e.g., 'Vladimir Putin', 'United States')
    """
    if not _ontology_engine:
        return {"status": "unavailable", "message": "OntologyEngine not running"}
    profile = _ontology_engine.get_entity_profile(name)
    if not profile:
        return {"status": "not_found", "message": f"Entity '{name}' not found in ontology"}
    return {"status": "ok", "profile": profile}


@app.get("/xdart/ontology/relationships")
async def get_ontology_relationships(
    relation_type: str | None = None,
    min_confidence: float = 0.35,
    limit: int = 50,
):
    """Return active typed relationships filtered by type and confidence.

    Args:
        relation_type: attacks / allied_with / funds / controls / opposes / sanctions / commands / negotiates_with / trades_with / monitors / depends_on / leads / supports / co_occurrence
        min_confidence: minimum relationship confidence (0.0–1.0)
        limit: max results (capped at 200)
    """
    if not _ontology_engine:
        return {"status": "unavailable", "message": "OntologyEngine not running"}
    limit = min(200, max(1, limit))
    rels = _ontology_engine.get_active_relationships(
        relation_type=relation_type,
        min_confidence=min_confidence,
        limit=limit,
    )
    return {"status": "ok", "count": len(rels), "relationships": rels}


@app.get("/xdart/ontology/paths")
async def get_ontology_paths(entity_a: str, entity_b: str, max_depth: int = 3):
    """Find relationship paths between two entities.

    Args:
        entity_a: source entity canonical name
        entity_b: target entity canonical name
        max_depth: max path length (1–5)
    """
    if not _ontology_engine:
        return {"status": "unavailable", "message": "OntologyEngine not running"}
    max_depth = min(5, max(1, max_depth))
    paths = _ontology_engine.find_relationship_paths(entity_a, entity_b, max_depth)
    return {"status": "ok", "paths": paths, "path_count": len(paths)}


# ══════════════════════════════════════════════════════════════════════════════
#  PALANTIR ΒΗΜΑ 2 — Intelligence Action Graph Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/xdart/actions/pending")
async def get_pending_intelligence_actions(limit: int = 10):
    """Return pending intelligence actions sorted by priority.

    Pending actions are recommendations generated by the Intelligence Action Graph
    that haven't been executed yet.
    """
    if not _action_graph:
        return {"status": "unavailable", "message": "Action Graph not running"}
    limit = min(50, max(1, limit))
    actions = _action_graph.get_pending_actions(limit=limit)
    return {"status": "ok", "count": len(actions), "actions": actions}


@app.get("/xdart/actions/history")
async def get_intelligence_action_history(n: int = 20):
    """Return the N most recent intelligence analysis cycles.

    Each entry includes: trigger, situation summary, decisions, and actions.
    """
    if not _action_graph:
        return {"status": "unavailable", "message": "Action Graph not running"}
    n = min(50, max(1, n))
    analyses = _action_graph.get_recent_analyses(n=n)
    return {"status": "ok", "count": len(analyses), "analyses": analyses}


@app.get("/xdart/actions/stats")
async def get_intelligence_action_stats():
    """Action graph cycle statistics: prediction accuracy, completion rate, total analyses."""
    if not _action_graph:
        return {"status": "unavailable", "message": "Action Graph not running"}
    return {"status": "ok", **_action_graph.get_cycle_stats()}


@app.post("/xdart/actions/{action_id}/execute")
async def mark_intelligence_action_executed(action_id: str, result: str = ""):
    """Mark an intelligence action as executed.

    Args:
        action_id: UUID of the action to mark as executed
        result: optional description of what was done
    """
    if not _action_graph:
        return {"status": "unavailable", "message": "Action Graph not running"}
    success = _action_graph.mark_action_executed(action_id, result=result)
    if not success:
        return {"status": "not_found", "message": f"Action {action_id} not found or already completed"}
    return {"status": "ok", "message": f"Action {action_id} marked as executed"}


@app.post("/xdart/actions/{action_id}/outcome")
async def record_intelligence_action_outcome(
    action_id: str,
    outcome_type: str,
    evidence: str = "",
    impact_score: float = 0.5,
):
    """Record the outcome for an intelligence action.

    Args:
        action_id: UUID of the action
        outcome_type: confirmed / partial / denied / unknown
        evidence: what signal confirmed or denied the prediction
        impact_score: actual impact of the event (0.0–1.0)
    """
    if not _action_graph:
        return {"status": "unavailable", "message": "Action Graph not running"}
    outcome = _action_graph.record_outcome(
        action_id=action_id,
        outcome_type=outcome_type,
        evidence=evidence,
        impact_score=min(1.0, max(0.0, impact_score)),
    )
    if not outcome:
        return {"status": "not_found", "message": f"Action {action_id} not found"}
    return {"status": "ok", "outcome": outcome.to_dict()}


@app.post("/xdart/actions/analyze")
async def trigger_manual_analysis(
    trigger_summary: str,
    situation_summary: str,
    key_entities: str = "",
    domains: str = "",
    confidence: float = 0.5,
):
    """Manually trigger an intelligence analysis cycle.

    Creates an analysis record, generates decisions via LLM, and produces
    actionable recommendations.

    Args:
        trigger_summary: one-line summary of what triggered the analysis
        situation_summary: detailed situation assessment
        key_entities: comma-separated entity names
        domains: comma-separated domain names (GEOPOLITICAL, ECONOMIC, etc.)
        confidence: trigger confidence (0.0–1.0)
    """
    if not _action_graph:
        return {"status": "unavailable", "message": "Action Graph not running"}
    entities = [e.strip() for e in key_entities.split(",") if e.strip()]
    domain_list = [d.strip() for d in domains.split(",") if d.strip()]
    loop = asyncio.get_event_loop()
    from xdart.intelligence.action_graph import AnalysisTrigger
    analysis = await loop.run_in_executor(
        None,
        lambda: _action_graph.record_analysis(
            trigger_type=AnalysisTrigger.MANUAL,
            trigger_id="manual",
            trigger_summary=trigger_summary,
            situation_summary=situation_summary,
            key_entities=entities,
            domains=domain_list,
            confidence=confidence,
        ),
    )
    pending = _action_graph.get_pending_actions(limit=10)
    return {
        "status": "ok",
        "analysis_id": analysis.id,
        "decisions_generated": len(analysis.decision_ids),
        "pending_actions": [a for a in pending if a["analysis_id"] == analysis.id],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PALANTIR DARK WING: Dark Whisper Intelligence Endpoints
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/xdart/dark/stats")
async def dark_stats():
    """Dark Whisper Engine stats — collector, triage, synthesis, dirty pool."""
    if not _darkwhisper_engine:
        return {"status": "disabled", "message": "Dark Whisper Engine not running (DARKWEB_ENABLED=false)"}
    return {
        "status": "ok",
        "engine": _darkwhisper_engine.stats(),
    }


@app.get("/xdart/dark/signals")
async def dark_signals(limit: int = 20):
    """Recent raw signals from the dirty pool (untriaged + triaged)."""
    if not _darkwhisper_engine:
        return {"status": "disabled", "signals": []}
    try:
        pool_stats = _darkwhisper_engine.pool.stats()
        untriaged = _darkwhisper_engine.pool.get_untriaged(limit=limit)
        # Clean _id from docs
        for d in untriaged:
            d.pop("_id", None)
            if "mongo_id" in d:
                d["mongo_id"] = str(d["mongo_id"])
        return {
            "status": "ok",
            "pool_stats": pool_stats,
            "untriaged_sample": untriaged,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/xdart/dark/whispers")
async def dark_whispers(limit: int = 10):
    """Recent Dark Whisper syntheses."""
    if not _darkwhisper_engine:
        return {"status": "disabled", "syntheses": []}
    try:
        syntheses = _darkwhisper_engine.get_recent_syntheses(limit=limit)
        dormant = _darkwhisper_engine.get_dormant_signals(limit=10)
        return {
            "status": "ok",
            "recent_syntheses": syntheses,
            "dormant_count": len(dormant),
            "dormant_sample": dormant[:5],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/xdart/dark/collect")
async def dark_collect_now():
    """Trigger an immediate collection cycle (bypass interval timer)."""
    if not _darkwhisper_engine:
        return {"status": "disabled", "message": "Dark Whisper Engine not running"}
    try:
        inserted = await _darkwhisper_engine.collector.collect_now()
        return {"status": "ok", "signals_inserted": inserted}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/xdart/dark/triage")
async def dark_triage_now():
    """Trigger an immediate triage batch on untriaged signals."""
    if not _darkwhisper_engine:
        return {"status": "disabled", "message": "Dark Whisper Engine not running"}
    try:
        loop = asyncio.get_event_loop()
        triaged = await loop.run_in_executor(
            None,
            _darkwhisper_engine.triage.run_triage_batch,
        )
        return {
            "status": "ok",
            "triaged_count": len(triaged),
            "yes": sum(1 for s in triaged if s.is_yes),
            "maybe": sum(1 for s in triaged if s.is_maybe),
            "triage_stats": _darkwhisper_engine.triage.stats(),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── Telegram Intelligence Endpoints ──────────────────────────────────────────


class TelegramSearchRequest(BaseModel):
    query: str = Field(description="Natural language topic to search for Telegram channels")
    limit: int = Field(default=10, ge=1, le=25, description="Max channels to return")


class TelegramAddRequest(BaseModel):
    channel: str = Field(description="Telegram channel handle (without @)")
    reason: str = Field(default="", description="Why this channel is being added")


class TelegramReadRequest(BaseModel):
    channel: str = Field(description="Channel handle to read messages from")
    limit: int = Field(default=20, ge=1, le=100, description="Max messages to return")


class TelegramTelethonSearchRequest(BaseModel):
    query: str = Field(description="Search query for Telegram native search (requires Tier 2)")
    limit: int = Field(default=10, ge=1, le=20)


@app.post("/xdart/telegram/intel/search")
async def telegram_intel_search(req: TelegramSearchRequest):
    """Search for Telegram channels matching a topic.

    Tier 1 (always active): Web search → t.me/s/ validation.
    Channels with active web preview can be added to live monitoring.
    """
    if not _telegram_intel:
        return {"status": "disabled", "message": "TelegramIntelTool not initialized"}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _telegram_intel.search_channels(req.query, limit=req.limit),
        )
        return {"status": "ok", **result}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/xdart/telegram/intel/add")
async def telegram_intel_add(req: TelegramAddRequest):
    """Add a Telegram channel to live monitoring.

    Validates channel first — must have t.me/s/ web preview active.
    Added channels are immediately picked up by DarkWebCollector.
    """
    if not _telegram_intel:
        return {"status": "disabled", "message": "TelegramIntelTool not initialized"}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _telegram_intel.add_channel(req.channel, reason=req.reason),
        )
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.delete("/xdart/telegram/intel/remove/{channel}")
async def telegram_intel_remove(channel: str):
    """Remove a channel from live monitoring."""
    if not _telegram_intel:
        return {"status": "disabled", "message": "TelegramIntelTool not initialized"}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _telegram_intel.remove_channel(channel),
        )
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/xdart/telegram/intel/monitored")
async def telegram_intel_list():
    """List all dynamically monitored Telegram channels."""
    if not _telegram_intel:
        return {"status": "disabled", "message": "TelegramIntelTool not initialized"}
    return _telegram_intel.list_monitored()


@app.post("/xdart/telegram/intel/read")
async def telegram_intel_read(req: TelegramReadRequest):
    """Read recent messages from a channel's public web preview (Tier 1)."""
    if not _telegram_intel:
        return {"status": "disabled", "message": "TelegramIntelTool not initialized"}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _telegram_intel.read_channel_preview(req.channel, limit=req.limit),
        )
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/xdart/telegram/intel/telethon/search")
async def telegram_intel_telethon_search(req: TelegramTelethonSearchRequest):
    """Search channels via Telegram MTProto API (Tier 2 — requires Telethon setup).

    Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in .env,
    and an active session from _setup_telegram_session.py.
    """
    if not _telegram_intel:
        return {"status": "disabled", "message": "TelegramIntelTool not initialized"}
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _telegram_intel.telethon_search_channels(req.query, limit=req.limit),
        )
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/xdart/telegram/intel/stats")
async def telegram_intel_stats():
    """Stats and status of the Telegram Intelligence Tool."""
    if not _telegram_intel:
        return {"status": "disabled", "message": "TelegramIntelTool not initialized"}
    return _telegram_intel.get_stats()


# ── Web Agent Endpoints ──

_web_agent = None


def _get_web_agent():
    """Lazy-init the web agent singleton."""
    global _web_agent
    if _web_agent is None:
        from xdart.config import WEB_AGENT_ENABLED, LIGHTPANDA_CDP_URL, WEB_AGENT_RESPECT_ROBOTS
        if not WEB_AGENT_ENABLED:
            return None
        from xdart.tools.web_agent import WebAgent
        _web_agent = WebAgent(
            lightpanda_cdp_url=LIGHTPANDA_CDP_URL,
            respect_robots=WEB_AGENT_RESPECT_ROBOTS,
        )
        logger.info("[WebAgent] Initialized (CDP=%s)", LIGHTPANDA_CDP_URL or "disabled")
    return _web_agent


class WebSearchRequest(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, ge=1, le=10)
    region: str = Field(default="wt-wt", description="Region: wt-wt, gr-el, us-en, etc.")


class WebBrowseRequest(BaseModel):
    url: str = Field(description="URL to navigate to")
    use_js: bool = Field(default=False, description="Force JS rendering via CDP/Playwright")


class WebScrapeRequest(BaseModel):
    url: str = Field(description="URL to scrape")
    selectors: dict[str, str] | None = Field(default=None, description="CSS selectors: {name: selector}")
    extract_tables: bool = Field(default=False)
    use_js: bool = Field(default=False)


class WebSearchReadRequest(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=3, ge=1, le=5)
    max_content_per_page: int = Field(default=5000, ge=500, le=20000)


@app.post("/xdart/web/search")
async def web_search(req: WebSearchRequest):
    """Search the web. Returns titles, URLs, and snippets."""
    agent = _get_web_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Web agent is disabled")
    return await agent.web_search(query=req.query, max_results=req.max_results, region=req.region)


@app.post("/xdart/web/browse")
async def web_browse(req: WebBrowseRequest):
    """Navigate to a URL, extract text content, headings, and links."""
    agent = _get_web_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Web agent is disabled")
    return await agent.web_browse(url=req.url, use_js=req.use_js)


@app.post("/xdart/web/scrape")
async def web_scrape(req: WebScrapeRequest):
    """Scrape specific data from a URL using CSS selectors."""
    agent = _get_web_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Web agent is disabled")
    return await agent.web_scrape(
        url=req.url, selectors=req.selectors,
        extract_tables=req.extract_tables, use_js=req.use_js,
    )


@app.post("/xdart/web/extract")
async def web_extract(req: WebBrowseRequest):
    """Smart article extraction: author, date, content, metadata."""
    agent = _get_web_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Web agent is disabled")
    return await agent.web_extract(url=req.url, use_js=req.use_js)


@app.post("/xdart/web/search-and-read")
async def web_search_and_read(req: WebSearchReadRequest):
    """Search the web and read the top results. Primary research tool."""
    agent = _get_web_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Web agent is disabled")
    return await agent.search_and_read(
        query=req.query, max_results=req.max_results,
        max_content_per_page=req.max_content_per_page,
    )


@app.get("/xdart/web/status")
async def web_agent_status():
    """Check web agent status and capabilities."""
    from xdart.config import WEB_AGENT_ENABLED, LIGHTPANDA_CDP_URL
    agent = _get_web_agent()
    cdp_ok = False
    if agent:
        cdp_ok = await agent._check_cdp()
    return {
        "enabled": WEB_AGENT_ENABLED,
        "lightpanda_cdp_url": LIGHTPANDA_CDP_URL or None,
        "cdp_available": cdp_ok,
        "js_rendering": cdp_ok or bool(agent),
        "capabilities": [
            "web_search", "web_browse", "web_scrape",
            "web_extract", "search_and_read",
        ] if agent else [],
    }


@app.get("/xdart/dashboard/data")
async def dashboard_data():
    """Aggregated endpoint for the JARVIS Command Center dashboard.

    Returns all dashboard-relevant data in a single response to minimize
    round trips. Auto-refreshed by the dashboard every 30 seconds.

    All synchronous DB/Qdrant/file reads are offloaded to a thread pool
    so the async event loop stays responsive even when the pipeline
    thread holds a Qdrant lock.
    """
    import asyncio

    def _collect_dashboard_data() -> dict:
        """Synchronous helper — runs in a thread via run_in_executor."""
        result = {
            "health": None,
            "prophecies": None,
            "accuracy": None,
            "world_context": None,
            "core_changes": None,
            "wisdom": None,
            "introspection": None,
            "evolution": None,
            "character": None,
        }

        if not _framework:
            return result

        # Health
        try:
            result["health"] = {
                "status": "ok",
                "model": OPENAI_MODEL,
                "memories": _framework.memory.entry_count,
                "concepts": _framework.memory.concept_count,
            }
        except Exception as exc:
            logger.debug("[Dashboard] Health query failed: %s", exc)

        # Prophecies
        try:
            all_entries = _framework.prophetic_memory.list_all(limit=50)
            result["prophecies"] = {
                "total": _framework.prophetic_memory.entry_count,
                "prophecies": [
                    {
                        "id": e.get("id", ""),
                        "timestamp": e.get("timestamp", ""),
                        "problem": e.get("problem", ""),
                        "tracking_status": e.get("tracking_status", "active"),
                        "was_dominant": e.get("was_dominant", False),
                        "tribunal_rank": e.get("tribunal_rank", 99),
                        "tribunal_score": e.get("tribunal_score", 0.0),
                        "scenario": {
                            "name": e.get("scenario", {}).get("name", ""),
                            "narrative": e.get("scenario", {}).get("narrative", ""),
                            "predicted_outcome": e.get("scenario", {}).get("predicted_outcome", ""),
                            "confidence": e.get("scenario", {}).get("confidence", 0.0),
                            "timeframe": e.get("scenario", {}).get("timeframe", ""),
                            "key_indicators": e.get("scenario", {}).get("key_indicators", []),
                        },
                        "simulation": {
                            "robustness_score": e.get("simulation", {}).get("robustness_score", 0.0),
                        },
                        "reality_checks": e.get("reality_checks", []),
                    }
                    for e in all_entries
                ],
            }
        except Exception as exc:
            logger.debug("[Dashboard] Prophecies query failed: %s", exc)

        # Accuracy
        try:
            result["accuracy"] = {
                "accuracy": _framework.prophetic_memory.compute_accuracy_stats(),
            }
        except Exception as exc:
            logger.debug("[Dashboard] Accuracy query failed: %s", exc)

        # World context (events from perception)
        try:
            if _framework.world_context:
                from xdart.perception.db import PerceptionDB
                db = PerceptionDB(db_path=PERCEPTION_DB_PATH)
                events_raw = db.get_recent_events(hours_back=72, max_events=50)
                result["world_context"] = {
                    "enabled": True,
                    "events": [
                        {
                            "headline": e.get("headline", ""),
                            "source": e.get("source_name", ""),
                            "domain": e.get("domain", ""),
                            "salience": e.get("salience_score", 0),
                            "collected_at": e.get("collected_at", ""),
                        }
                        for e in events_raw
                    ],
                }
            else:
                result["world_context"] = {"enabled": False, "events": []}
        except Exception as exc:
            logger.debug("[Dashboard] World context query failed: %s", exc)
            result["world_context"] = {"enabled": False, "events": []}

        # Core changes
        try:
            cl = CoreChangeLogger()
            all_changes = cl.read_all()
            result["core_changes"] = {
                "total": len(all_changes),
                "recent": all_changes[-15:],
            }
        except Exception as exc:
            logger.debug("[Dashboard] Core changes query failed: %s", exc)

        # Wisdom
        try:
            result["wisdom"] = {
                "wisdom_index": _framework.wisdom_tracker.compute_wisdom_index(),
                "calibration_report": _framework.wisdom_tracker.get_calibration_report(),
            }
        except Exception as exc:
            logger.debug("[Dashboard] Wisdom query failed: %s", exc)

        # Introspection
        try:
            result["introspection"] = {
                "avg_integrity": round(_framework.introspection.get_average_integrity(10), 3),
                "failure_patterns": _framework.introspection.get_failure_patterns(),
                "total_reports": len(_framework.introspection.get_recent(1000)),
            }
        except Exception as exc:
            logger.debug("[Dashboard] Introspection query failed: %s", exc)

        # Self-evolution
        try:
            result["evolution"] = {
                "stats": _framework.self_evolution.get_journal_stats(),
                "active_proposals": _framework.self_evolution.get_active_proposals(),
            }
        except Exception as exc:
            logger.debug("[Dashboard] Evolution query failed: %s", exc)

        # Character state
        try:
            with open(CHARACTER_STATE_PATH, "r", encoding="utf-8") as f:
                char = json.load(f)
            result["character"] = {
                "name": char.get("name", "Αίολος"),
                "version": char.get("version", 0),
                "tensions_count": len(char.get("active_tensions", [])),
                "concepts_count": len(char.get("named_concepts_owned", [])),
            }
        except Exception as exc:
            logger.debug("[Dashboard] Character query failed: %s", exc)

        return result

    # Run in thread pool — won't block the event loop while pipeline holds Qdrant lock
    return await asyncio.get_event_loop().run_in_executor(None, _collect_dashboard_data)


@app.post("/xdart/llm-proxy/v1/chat/completions")
async def llm_proxy(request: Request):
    """Proxy OpenAI-compatible chat completions for page-agent.

    This keeps the API key server-side. The page-agent client sends
    requests to this endpoint instead of directly to OpenAI.
    Security: forces a lightweight model and caps max_tokens.
    """
    import httpx

    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="No API key configured")

    body = await request.json()

    # Security: force lightweight model for page-agent (DOM control only)
    body["model"] = "gpt-4o-mini"
    # Security: cap token usage to prevent abuse
    body["max_tokens"] = min(body.get("max_tokens", 2048), 2048)

    base_url = LLM_BASE_URL or "https://api.openai.com/v1"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
        )

    return resp.json()


# ══════════════════════════════════════════════════════════════════════════════
#  PROACTIVE NOTIFICATIONS — Αίολος initiates contact
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/xdart/notifications")
async def list_notifications(limit: int = 50):
    """List recent proactive notifications (newest first)."""
    if not _proactive_engine:
        return {"notifications": [], "unread_count": 0, "stats": {}}
    return {
        "notifications": _proactive_engine.get_recent(limit),
        "unread_count": _proactive_engine.get_unread_count(),
        "stats": _proactive_engine.get_stats(),
    }


@app.post("/xdart/notifications/read")
async def mark_notifications_read(request: Request):
    """Mark notification(s) as read. Empty id = mark all."""
    if not _proactive_engine:
        raise HTTPException(status_code=503, detail="Proactive engine not active")
    body = await request.json()
    notification_id = body.get("notification_id", "")
    if notification_id:
        ok = _proactive_engine.mark_read(notification_id)
        return {"marked": 1 if ok else 0}
    else:
        count = _proactive_engine.mark_all_read()
        return {"marked": count}


@app.get("/xdart/notifications/stats")
async def notification_stats():
    """Proactive engine statistics."""
    if not _proactive_engine:
        return {"active": False}
    return {"active": True, **_proactive_engine.get_stats()}


@app.get("/xdart/notifications/pending")
async def get_pending_notifications():
    """Return the current notification batch buffer (0-9 items not yet flushed to Telegram).

    Αίολος and the dashboard can always see what's queued mid-batch.
    """
    if not _proactive_engine:
        return {"active": False, "pending": [], "count": 0, "flush_at": 10}
    pending = _proactive_engine.get_pending_batch()
    return {
        "active": True,
        "pending": pending,
        "count": len(pending),
        "flush_at": _proactive_engine._notif_batch_size,
        "total_flushed": _proactive_engine._notif_batch_total_flushed,
    }


@app.post("/xdart/notifications/flush")
async def flush_notification_batch():
    """Manually flush the current notification batch to Telegram immediately.

    Use this when Πάνος says 'send me what you have' without waiting for 10 items.
    Returns the number of notifications flushed.
    """
    if not _proactive_engine:
        raise HTTPException(status_code=503, detail="Proactive engine not active")
    count = await asyncio.get_running_loop().run_in_executor(
        None, _proactive_engine.flush_batch_now
    )
    return {"flushed": count, "status": "ok" if count > 0 else "empty"}


# ══════════════════════════════════════════════════════════════
#  Pattern Accumulator Monitoring Endpoints
# ══════════════════════════════════════════════════════════════

@app.get("/xdart/patterns")
async def get_active_patterns():
    """All active patterns currently tracked by the accumulator."""
    if not _proactive_engine:
        return {"active": False, "patterns": []}
    patterns = _proactive_engine.accumulator.get_active_patterns()
    return {
        "active": True,
        "count": len(patterns),
        "patterns": patterns,
    }


@app.get("/xdart/patterns/hot")
async def get_hot_patterns(min_convergence: float = 0.30):
    """Patterns approaching the firing threshold (convergence ≥ min_convergence)."""
    if not _proactive_engine:
        return {"active": False, "patterns": []}
    # Clamp the parameter to valid range
    min_convergence = max(0.0, min(1.0, min_convergence))
    patterns = _proactive_engine.accumulator.get_hot_patterns(min_convergence)
    return {
        "active": True,
        "threshold": min_convergence,
        "count": len(patterns),
        "patterns": patterns,
    }


@app.get("/xdart/patterns/stats")
async def pattern_accumulator_stats():
    """Detailed statistics from the PatternAccumulator."""
    if not _proactive_engine:
        return {"active": False}
    return {
        "active": True,
        **_proactive_engine.accumulator.get_stats(),
    }


@app.get("/xdart/notifications/stream")
async def notification_sse_stream(request: Request):
    """SSE stream for real-time proactive notifications.

    The client connects once and receives notifications as they arrive.
    Heartbeat every 30s keeps the connection alive.
    """
    if not _proactive_engine:
        raise HTTPException(status_code=503, detail="Proactive engine not active")

    queue = _proactive_engine.subscribe_sse()

    async def event_generator():
        try:
            # Send initial state
            yield {
                "event": "connected",
                "data": json.dumps({
                    "unread_count": _proactive_engine.get_unread_count(),
                    "stats": _proactive_engine.get_stats(),
                }),
            }

            while True:
                if await request.is_disconnected():
                    break

                try:
                    # Wait for notification with 30s timeout (for heartbeat)
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {
                        "event": "notification",
                        "data": json.dumps(data, ensure_ascii=False),
                    }
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({
                            "unread_count": _proactive_engine.get_unread_count(),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }),
                    }
        except (asyncio.CancelledError, GeneratorExit):
            # Graceful shutdown during reload — suppress noisy tracebacks
            pass
        finally:
            _proactive_engine.unsubscribe_sse(queue)

    return EventSourceResponse(event_generator())


@app.post("/xdart/notifications/test")
async def test_notification():
    """Send a test notification to verify the proactive pipeline works."""
    if not _proactive_engine:
        raise HTTPException(status_code=503, detail="Proactive engine not active")

    from xdart.proactive import Notification, IMPORTANT
    test_notif = Notification(
        headline="Test: Proactive Engine Online",
        summary="Αυτό είναι ένα δοκιμαστικό μήνυμα. Η proactive μηχανή λειτουργεί κανονικά. "
                "Ο Αίολος μπορεί πλέον να επικοινωνήσει μαζί σου αυτόνομα.",
        urgency=IMPORTANT,
        source="test",
        reason="Manual test trigger",
    )
    _proactive_engine.register_notification(test_notif, dedup=False)
    _proactive_engine._deliver_immediate(test_notif)

    return {"status": "sent", "notification": test_notif.to_dict()}


# ══════════════════════════════════════════════════════════════
#  HYPOTHESIS ENGINE — persistent "if X then Y" tracking
# ══════════════════════════════════════════════════════════════

@app.get("/xdart/hypotheses")
async def list_hypotheses(status: str | None = None):
    """List all hypotheses, optionally filtered by status.

    Query params:
      status: active | trigger_detected | confirmed | disconfirmed | expired
    """
    if not _proactive_engine:
        return {"active": False}
    return {
        "active": True,
        "hypotheses": _proactive_engine.hypothesis_engine.get_all_hypotheses(status),
        "stats": _proactive_engine.hypothesis_engine.stats(),
    }


@app.get("/xdart/hypotheses/stats")
async def hypothesis_stats():
    """Hypothesis engine statistics and accuracy metrics."""
    if not _proactive_engine:
        return {"active": False}
    return {
        "active": True,
        **_proactive_engine.hypothesis_engine.stats(),
    }


@app.post("/xdart/hypotheses/create")
async def create_hypothesis(payload: dict):
    """Manually create a hypothesis for tracking.

    Body JSON:
      hypothesis_text: "IF X THEN Y within Z"
      trigger_condition: "The observable trigger"
      expected_outcome: "The expected consequence"
      trigger_keywords: ["kw1", "kw2"]
      outcome_keywords: ["kw1", "kw2"]
      trigger_entities: ["Entity1"] (optional)
      outcome_entities: ["Entity1"] (optional)
      timeframe_days: 30 (optional, default 30)
      confidence: 0.5 (optional, default 0.5)
      domains: ["SECURITY", "ECONOMIC"] (optional)
    """
    if not _proactive_engine:
        raise HTTPException(status_code=503, detail="Proactive engine not active")

    required = ["hypothesis_text", "trigger_condition", "expected_outcome",
                 "trigger_keywords", "outcome_keywords"]
    for field in required:
        if field not in payload:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

    hyp = _proactive_engine.hypothesis_engine.create_hypothesis(
        hypothesis_text=payload["hypothesis_text"],
        trigger_condition=payload["trigger_condition"],
        expected_outcome=payload["expected_outcome"],
        trigger_keywords=set(payload["trigger_keywords"]),
        outcome_keywords=set(payload["outcome_keywords"]),
        trigger_entities=set(payload.get("trigger_entities", [])),
        outcome_entities=set(payload.get("outcome_entities", [])),
        timeframe_days=payload.get("timeframe_days", 30),
        confidence=payload.get("confidence", 0.5),
        source="user",
        domains=payload.get("domains", []),
    )

    if hyp is None:
        raise HTTPException(status_code=409, detail="Hypothesis rejected (max active or duplicate)")

    return {
        "status": "created",
        "hypothesis": _proactive_engine.hypothesis_engine._hyp_to_dict(hyp),
    }


@app.get("/xdart/hypotheses/digest")
async def hypothesis_digest():
    """Get the formatted hypothesis intelligence digest."""
    if not _proactive_engine:
        return {"active": False, "digest": ""}
    return {
        "active": True,
        "digest": _proactive_engine.hypothesis_engine.get_digest(),
    }


# ══════════════════════════════════════════════════════════════
#  TEMPORAL REASONING — Recurring patterns, precursors, sequences
# ══════════════════════════════════════════════════════════════

@app.get("/xdart/temporal/stats")
async def temporal_stats():
    """Temporal Reasoning Engine statistics."""
    if not _temporal_engine:
        return {"active": False}
    return {
        "active": True,
        **_temporal_engine.stats(),
    }


@app.get("/xdart/temporal/patterns")
async def temporal_patterns():
    """List all learned temporal patterns."""
    if not _temporal_engine:
        return {"active": False, "patterns": []}
    return {
        "active": True,
        "patterns": _temporal_engine.get_all_patterns(),
    }


@app.get("/xdart/temporal/digest")
async def temporal_digest():
    """Get the current temporal intelligence digest."""
    if not _temporal_engine:
        return {"active": False, "digest": ""}
    return {
        "active": True,
        "digest": _temporal_engine.get_temporal_digest(),
    }


@app.get("/xdart/temporal/precursors")
async def temporal_precursors():
    """Check for active precursor matches right now."""
    if not _temporal_engine:
        return {"active": False, "alerts": []}
    loop = asyncio.get_running_loop()
    alerts = await loop.run_in_executor(None, _temporal_engine.check_precursors)
    return {
        "active": True,
        "alerts": alerts,
    }


# ══════════════════════════════════════════════════════════════
#  MULTIMODAL PERCEPTION — Airspace, Maritime, Satellite
# ══════════════════════════════════════════════════════════════

@app.get("/xdart/multimodal/stats")
async def multimodal_stats():
    """Get multimodal perception statistics."""
    if not _framework or not hasattr(_framework, '_multimodal_collector') or not _framework._multimodal_collector:
        return {"status": "disabled", "message": "Multimodal perception not active"}
    return await asyncio.get_event_loop().run_in_executor(
        None, _framework._multimodal_collector.get_stats,
    )


@app.get("/xdart/multimodal/zones")
async def multimodal_zones():
    """Get list of monitored strategic zones."""
    from xdart.perception.multimodal import STRATEGIC_ZONES
    return {
        "zones": {
            k: {"name": v["name"], "lat": v["lat"], "lon": v["lon"],
                 "radius_km": v["radius_km"], "significance": v["significance"]}
            for k, v in STRATEGIC_ZONES.items()
        },
        "total": len(STRATEGIC_ZONES),
    }


@app.get("/xdart/live-osint")
async def live_osint_digest():
    """Get the live OSINT intelligence digest — Palantir-class sensor feed.

    Returns a structured text digest of ALL current sensor readings:
    airspace (ADS-B), maritime (AIS), satellite (FIRMS thermal).
    This is the same data injected into Αίολος's LLM context.
    """
    if not _framework or not hasattr(_framework, '_multimodal_collector') or not _framework._multimodal_collector:
        return {"status": "disabled", "digest": "", "message": "Multimodal perception not active"}

    collector = _framework._multimodal_collector
    digest = await asyncio.get_event_loop().run_in_executor(
        None, collector.get_live_digest,
    )
    stats = await asyncio.get_event_loop().run_in_executor(
        None, collector.get_stats,
    )
    return {
        "status": "active",
        "digest": digest,
        "cycles": stats.get("cycles", 0),
        "airspace_zones": len(collector.airspace.zone_status),
        "maritime_chokepoints": len(collector.maritime.chokepoint_status),
        "satellite_zones": len(collector.satellite.zone_thermal_status),
    }


@app.get("/xdart/palantir/status")
async def palantir_status():
    """Full Palantir P0 intelligence platform status — all new-gen components."""
    status = {
        "platform": "XDART-Φ Palantir Intelligence Platform",
        "components": {},
    }

    # Real-Time Feeds
    if _realtime_feeds:
        status["components"]["realtime_feeds"] = {
            "active": True,
            **_realtime_feeds.stats(),
        }
    else:
        status["components"]["realtime_feeds"] = {"active": False}

    # Sanctions Registry
    if _sanctions_registry:
        status["components"]["sanctions_registry"] = {
            "active": True,
            **_sanctions_registry.stats(),
        }
    else:
        status["components"]["sanctions_registry"] = {"active": False}

    # Event Calendar
    if _event_calendar:
        status["components"]["event_calendar"] = {
            "active": True,
            **_event_calendar.stats(),
        }
    else:
        status["components"]["event_calendar"] = {"active": False}

    # Temporal Reasoning
    if _temporal_engine:
        status["components"]["temporal_reasoning"] = {
            "active": True,
            **_temporal_engine.stats(),
        }
    else:
        status["components"]["temporal_reasoning"] = {"active": False}

    # Compound Alerts
    if _proactive_engine:
        status["components"]["compound_alerts"] = {
            "active": True,
            **_proactive_engine.compound_alerts.stats(),
        }
    else:
        status["components"]["compound_alerts"] = {"active": False}

    # Multimodal OSINT
    if _multimodal_collector:
        status["components"]["multimodal_osint"] = {
            "active": True,
            "cycles": _multimodal_collector._cycle_count,
            "airspace_zones": len(_multimodal_collector.airspace.zone_status),
            "chokepoints": len(_multimodal_collector.maritime.chokepoint_status),
            "satellite_zones": len(_multimodal_collector.satellite.zone_thermal_status),
            "external_digest_sections": len(_multimodal_collector._external_digest_sections),
        }
    else:
        status["components"]["multimodal_osint"] = {"active": False}

    return status


@app.get("/xdart/sanctions")
async def sanctions_status():
    """Get sanctions cross-reference status and flagged entities."""
    if not _sanctions_registry:
        return {"status": "disabled", "message": "Sanctions registry not active"}

    return {
        "status": "active",
        **_sanctions_registry.stats(),
        "flagged_entities": {
            name: matches
            for name, matches in list(_sanctions_registry._entity_matches.items())[:50]
        },
    }


@app.get("/xdart/calendar")
async def calendar_status():
    """Get geopolitical event calendar with upcoming events."""
    if not _event_calendar:
        return {"status": "disabled", "message": "Event calendar not active"}

    upcoming_14d = _event_calendar.get_upcoming_events(14)
    return {
        "status": "active",
        **_event_calendar.stats(),
        "upcoming_events": [
            {
                "date": ev["date"],
                "name": ev["name"],
                "category": ev.get("category", ""),
                "region": ev.get("region", "GLOBAL"),
                "impact": ev.get("impact", 0),
                "days_until": ev["days_until"],
                "hours_until": round(ev["hours_until"], 1),
            }
            for ev in upcoming_14d[:25]
        ],
        "active_watch_keywords": sorted(_event_calendar.get_active_watch_keywords()),
        "digest": _event_calendar.get_calendar_digest(),
    }


@app.get("/xdart/compound-alerts")
async def compound_alerts_status():
    """Get compound alert chain status and recent compound fires."""
    if not _proactive_engine:
        return {"status": "disabled", "message": "Proactive engine not active"}

    engine = _proactive_engine.compound_alerts
    return {
        "status": "active",
        **engine.stats(),
        "recent_compounds": engine._compound_fires[-10:],
        "digest": engine.get_compound_digest(),
    }


# ══════════════════════════════════════════════════════════════
#  CROSS-SYSTEM LEARNING — Research Paper Acquisition
# ══════════════════════════════════════════════════════════════

@app.get("/xdart/cross-system/stats")
async def cross_system_stats():
    """Get cross-system learning statistics."""
    if not _framework or not hasattr(_framework, '_cross_system_learner') or not _framework._cross_system_learner:
        return {"status": "disabled", "message": "Cross-system learning not active"}
    return await asyncio.get_event_loop().run_in_executor(
        None, _framework._cross_system_learner.get_stats,
    )


@app.post("/xdart/cross-system/run")
async def cross_system_run_now():
    """Trigger an immediate cross-system learning cycle (on-demand)."""
    if not _framework or not hasattr(_framework, '_cross_system_learner') or not _framework._cross_system_learner:
        raise HTTPException(status_code=503, detail="Cross-system learning not active")

    learner = _framework._cross_system_learner

    # Gather context
    curiosity_topics = []
    if hasattr(_framework, 'curiosity_engine') and _framework.curiosity_engine:
        try:
            active = _framework.curiosity_engine.get_active_curiosities()
            curiosity_topics = [
                c.get("question", "") if isinstance(c, dict) else getattr(c, "question", "")
                for c in active[:10]
            ]
        except Exception:
            pass

    result = await learner.run_daily_cycle(
        curiosity_topics=curiosity_topics,
    )
    return result


# ══════════════════════════════════════════════════════════════
#  VISION SYSTEM — Αίολος' Eyes (Face Detection + Recognition)
# ══════════════════════════════════════════════════════════════

@app.post("/xdart/vision/event")
async def vision_event(event: dict):
    """Receive visual perception events from the Vision Service.

    Called by the FaceNet microservice when humans are detected/depart.
    Triggers proactive conversations and updates visual memory.
    """
    if not _vision_integration:
        raise HTTPException(status_code=503, detail="Vision system not active")

    result = await asyncio.get_event_loop().run_in_executor(
        None, _vision_integration.handle_event, event,
    )
    return result


@app.get("/xdart/vision/status")
async def vision_status():
    """Get vision system status and sighting stats."""
    if not _vision_integration:
        return {"status": "disabled", "message": "Vision system not active"}
    return _vision_integration.stats


@app.get("/xdart/vision/sightings")
async def vision_sightings():
    """Get recent visual sighting log."""
    if not _vision_integration:
        return {"status": "disabled", "sightings": []}
    return {
        "sightings": _vision_integration.sighting_log,
        "humans_present": _vision_integration.humans_present,
        "current_faces": _vision_integration.current_faces,
    }


@app.post("/xdart/vision/scene")
async def vision_scene(scene: dict):
    """Receive browser-side COCO-SSD scene detection results.

    Called by the TF.js COCO-SSD model running in the browser every 3 seconds.
    Contains detected objects (80 COCO classes) with counts and confidence scores.
    """
    if not _vision_integration:
        raise HTTPException(status_code=503, detail="Vision system not active")
    obj_names = list((scene.get("objects") or {}).keys())
    total = scene.get("total_detections", 0)
    n = _vision_integration._stats.get("scene_updates", 0) + 1
    if n <= 3 or n % 30 == 0:
        logger.info("[Vision/scene] #%d received — %d objects: %s", n, total, obj_names)
    _vision_integration.update_scene(scene)
    return {"status": "ok"}


@app.post("/xdart/vision/register-face")
async def vision_register_face(body: dict):
    """Register a face UUID → human name association.

    Once registered, Αίολος will recognize this face by name in all future
    detections. The mapping persists across restarts.

    Body: {"face_id": "uuid-string", "name": "Panos"}
    """
    if not _vision_integration:
        raise HTTPException(status_code=503, detail="Vision system not active")
    face_id = body.get("face_id", "").strip()
    name = body.get("name", "").strip()
    if not face_id or not name:
        raise HTTPException(status_code=400, detail="Both 'face_id' and 'name' are required")
    result = _vision_integration.register_face_name(face_id, name)
    return result


@app.delete("/xdart/vision/register-face/{face_id}")
async def vision_unregister_face(face_id: str):
    """Remove a face UUID → name association."""
    if not _vision_integration:
        raise HTTPException(status_code=503, detail="Vision system not active")
    return _vision_integration.unregister_face_name(face_id)


@app.get("/xdart/vision/face-registry")
async def vision_face_registry():
    """Get all registered face UUID → name mappings."""
    if not _vision_integration:
        return {"status": "disabled", "registry": {}}
    return {
        "registry": _vision_integration.face_registry,
        "total": len(_vision_integration.face_registry),
    }


@app.get("/xdart/vision/objects")
async def vision_objects():
    """Get object tracking data — accumulated history of detected objects."""
    if not _vision_integration:
        return {"status": "disabled", "tracking": {}, "log": []}
    return {
        "current_scene": _vision_integration.stats.get("scene_objects", {}),
        "tracking": _vision_integration.object_tracking,
        "recent_log": _vision_integration.object_log[-20:],
        "scene_timestamp": _vision_integration.stats.get("scene_timestamp", ""),
    }


@app.get("/xdart/vision/debug")
async def vision_debug():
    """Full vision debug view — smoothed scene, raw state, stats, context string."""
    if not _vision_integration:
        return {"status": "disabled"}
    vi = _vision_integration
    return {
        "status": "ok",
        "current_scene": vi._current_scene,
        "smoothed_scene": {k: {kk: vv for kk, vv in v.items() if kk != "first_seen_ts" and kk != "last_seen_ts"}
                           for k, v in vi._smoothed_scene.items()},
        "scene_timestamp": vi._scene_timestamp,
        "scene_updates": vi._stats.get("scene_updates", 0),
        "object_events": vi._stats.get("object_events", 0),
        "humans_present": vi._humans_present,
        "current_faces_count": len(vi._current_faces),
        "object_tracking_keys": list(vi._object_tracking.keys()),
        "context_string": vi.to_context_string(),
    }


@app.get("/xdart/vision/journal")
async def vision_journal(last_n: int = 50):
    """Get Αίολος' visual memory journal — persistent record of everything seen."""
    if not _vision_integration:
        return {"status": "disabled", "entries": []}
    entries = _vision_integration.get_journal(last_n=min(last_n, 500))
    return {
        "status": "ok",
        "count": len(entries),
        "entries": entries,
    }


@app.post("/xdart/vision/reflect")
async def vision_reflect():
    """Trigger an immediate visual reflection — Αίολος thinks about what it has seen."""
    if not _vision_integration:
        raise HTTPException(status_code=503, detail="Vision integration not active")
    # Force reflection by resetting the timer
    _vision_integration._last_reflection_time = 0
    result = await asyncio.get_event_loop().run_in_executor(
        None, _vision_integration.run_visual_reflection
    )
    if result is None:
        return {"status": "skipped", "reason": "Insufficient visual data for reflection"}
    return {"status": "ok", "reflection": result}


@app.get("/xdart/vision/cognition")
async def vision_cognition():
    """Get Αίολος' visual cognition state — patterns, predictions, experience."""
    if not _vision_integration:
        return {"status": "disabled"}
    return {
        "status": "ok",
        "patterns": _vision_integration._visual_patterns[-20:],
        "active_predictions": [p for p in _vision_integration._visual_predictions if not p.get("resolved")],
        "resolved_predictions": [p for p in _vision_integration._visual_predictions if p.get("resolved")],
        "visual_distillate": _vision_integration.get_visual_distillate_for_character(),
        "reflection_interval_hours": _vision_integration._reflection_interval / 3600,
        "last_reflection_ago_sec": int(time.time() - _vision_integration._last_reflection_time)
            if _vision_integration._last_reflection_time > 0 else None,
    }


class ConversationRequestBody(BaseModel):
    topic: str = Field(..., description="Topic for conversation")
    reason: str = Field(default="", description="Why this conversation is needed")


@app.post("/xdart/conversation/request")
async def request_conversation(body: ConversationRequestBody):
    """Manually trigger a conversation request from Αίολος."""
    if not _proactive_engine:
        raise HTTPException(status_code=503, detail="Proactive engine not active")

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _proactive_engine.request_conversation(
            topic=body.topic,
            reason=body.reason or f"Manual request: {body.topic}",
        ),
    )
    if result:
        return {"status": "sent", "notification": result.to_dict()}
    return {"status": "cooldown", "message": "Conversation request on cooldown"}


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the XDART-Φ × XHEART web UI."""
    ui_path = Path(__file__).parent.parent / "ui.html"
    if not ui_path.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    # run_in_executor avoids blocking the asyncio event loop on file I/O
    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(None, lambda: ui_path.read_text(encoding="utf-8"))
    return HTMLResponse(content=content)


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the ΑΙΟΛΟΣ JARVIS Command Center dashboard."""
    dash_path = Path(__file__).parent.parent / "dashboard.html"
    if not dash_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(None, lambda: dash_path.read_text(encoding="utf-8"))
    return HTMLResponse(content=content)


from fastapi.responses import FileResponse


# ══════════════════════════════════════════════════════════════
#  COGNITIVE STRATEGIES — View / Manage thinking patterns
# ══════════════════════════════════════════════════════════════


@app.get("/xdart/strategies")
async def get_cognitive_strategies():
    """List all cognitive strategies (active and inactive)."""
    try:
        if not _framework:
            raise HTTPException(status_code=503, detail="Framework not initialized")
        registry = _framework.strategy_registry
        strategies = registry.get_all(active_only=False)
        return {
            "strategies": [s.to_dict() for s in strategies],
            "stats": registry.stats(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[API] Failed to load strategies: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/strategies/{strategy_id}/deactivate")
async def deactivate_strategy(strategy_id: str):
    """Deactivate a cognitive strategy."""
    try:
        if not _framework:
            raise HTTPException(status_code=503, detail="Framework not initialized")
        registry = _framework.strategy_registry
        success = registry.deactivate(strategy_id, reason="manual deactivation via API")
        if not success:
            raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")
        return {"status": "deactivated", "strategy_id": strategy_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
#  LOGIC SANDBOX — Self-modification of algorithmic functions
# ══════════════════════════════════════════════════════════════


@app.get("/xdart/logic-sandbox")
async def get_logic_sandbox():
    """Get the logic sandbox registry — modifiable functions + proposals."""
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")
        return {
            "functions": _framework.logic_sandbox.get_registry(),
            "proposals": _framework.logic_sandbox.get_proposals(),
            "stats": _framework.logic_sandbox.get_stats(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[API] Logic sandbox get failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/xdart/logic-sandbox/proposals")
async def get_logic_proposals():
    """Get all logic modification proposals."""
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")
        return {"proposals": _framework.logic_sandbox.get_proposals()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LogicApproveRequest(BaseModel):
    principle_id: str = Field(default="", description="Optional principle ID")


@app.post("/xdart/logic-sandbox/proposals/{proposal_id}/approve")
async def approve_logic_proposal(proposal_id: str):
    """Approve a logic modification proposal — applies the change."""
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")
        result = _framework.logic_sandbox.approve_proposal(proposal_id)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/logic-sandbox/proposals/{proposal_id}/reject")
async def reject_logic_proposal(proposal_id: str, reason: str = ""):
    """Reject a logic modification proposal."""
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")
        result = _framework.logic_sandbox.reject_proposal(proposal_id, reason=reason)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/logic-sandbox/functions/{function_name}/rollback")
async def rollback_logic_function(function_name: str, to_factory: bool = False):
    """Rollback a function to its previous version or factory original."""
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")
        result = _framework.logic_sandbox.rollback(function_name, to_original=to_factory)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/logic-sandbox/deploy-all")
async def deploy_all_pending_proposals():
    """Auto-approve and apply ALL sandbox-tested proposals that are awaiting approval."""
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")
        results = _framework.logic_sandbox.deploy_pending_proposals()
        return {"deployed": len([r for r in results if r.get("action") == "deployed"]), "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/logic-sandbox/register")
async def register_sandbox_function(body: dict):
    """Register a new function for self-modification in the Logic Sandbox.

    Required body fields: function_id, description, module_path, function_name,
                          signature, code, constraints, test_inputs, expected_behavior
    """
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")

        required = ["function_id", "description", "module_path", "function_name",
                     "signature", "code", "constraints", "test_inputs", "expected_behavior"]
        missing = [f for f in required if f not in body]
        if missing:
            raise HTTPException(status_code=422, detail=f"Missing fields: {missing}")

        result = _framework.logic_sandbox.register_function(
            function_id=body["function_id"],
            description=body["description"],
            module_path=body["module_path"],
            function_name=body["function_name"],
            signature=body["signature"],
            code=body["code"],
            constraints=body["constraints"],
            test_inputs=body["test_inputs"],
            expected_behavior=body["expected_behavior"],
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/xdart/logic-sandbox/functions/{function_id}")
async def unregister_sandbox_function(function_id: str):
    """Remove a function from the Logic Sandbox registry."""
    try:
        if not _framework or not _framework.logic_sandbox:
            raise HTTPException(status_code=503, detail="Logic Sandbox is disabled")
        result = _framework.logic_sandbox.unregister_function(function_id)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
#  DYNAMIC PRINCIPLE REGISTRY — Learned operating principles
# ══════════════════════════════════════════════════════════════


@app.get("/xdart/principles")
async def get_principles(include_retired: bool = False):
    """List all dynamic principles (active, proposed, optionally retired)."""
    try:
        if not _framework or not _framework.principle_registry:
            raise HTTPException(status_code=503, detail="Principle Registry is disabled")
        return {
            "principles": _framework.principle_registry.get_all(include_retired=include_retired),
            "stats": _framework.principle_registry.get_stats(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[API] Principles get failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/xdart/principles/pending")
async def get_pending_principles():
    """Get principles awaiting human approval."""
    try:
        if not _framework or not _framework.principle_registry:
            raise HTTPException(status_code=503, detail="Principle Registry is disabled")
        return {"pending": _framework.principle_registry.get_pending_approvals()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/principles/{principle_id}/approve")
async def approve_principle(principle_id: str):
    """Approve a proposed principle — makes it active in the pipeline."""
    try:
        if not _framework or not _framework.principle_registry:
            raise HTTPException(status_code=503, detail="Principle Registry is disabled")
        result = _framework.principle_registry.approve(principle_id)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/principles/{principle_id}/reject")
async def reject_principle(principle_id: str, reason: str = ""):
    """Reject a proposed principle."""
    try:
        if not _framework or not _framework.principle_registry:
            raise HTTPException(status_code=503, detail="Principle Registry is disabled")
        result = _framework.principle_registry.reject(principle_id, reason=reason)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Principle Philosophy ──

@app.get("/xdart/principles/philosophy")
async def get_principle_philosophy():
    """Get current principle discovery philosophy mode and settings."""
    try:
        if not _framework or not _framework.principle_registry:
            raise HTTPException(status_code=503, detail="Principle Registry is disabled")
        return _framework.principle_registry.get_philosophy()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/xdart/principles/philosophy/{mode}")
async def set_principle_philosophy(mode: str):
    """Switch principle discovery philosophy.

    Modes:
      - balanced: Default — error prevention AND pattern discovery
      - conservative: Ultra-conservative — 3+ events needed, higher retire threshold
      - exploratory: Aggressive discovery — even 1 event suffices, auto-approve with probation
    """
    try:
        if not _framework or not _framework.principle_registry:
            raise HTTPException(status_code=503, detail="Principle Registry is disabled")
        result = _framework.principle_registry.set_philosophy(mode)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
#  BAYESIAN-FUZZY TEMPLATES — Custom domain template management
# ══════════════════════════════════════════════════════════════


@app.get("/xdart/bayesian-fuzzy/templates")
async def list_bf_templates():
    """List all Bayesian-Fuzzy domain templates (built-in + custom)."""
    try:
        from xdart.phases.bayesian_fuzzy import list_all_templates
        return {"templates": list_all_templates()}
    except Exception as e:
        logger.error("[API] BF templates list failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/xdart/bayesian-fuzzy/templates/{name}")
async def get_bf_template(name: str):
    """Get full detail for a specific Bayesian-Fuzzy template."""
    try:
        from xdart.phases.bayesian_fuzzy import get_template_detail
        detail = get_template_detail(name)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
        return {"name": name, "template": detail}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[API] BF template get failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class BFTemplateRequest(BaseModel):
    name: str = Field(description="Template name (lowercase, underscores, no spaces)")
    template: dict = Field(description="Template definition with variables, latent_nodes, causal_edges, priors, keywords")


@app.post("/xdart/bayesian-fuzzy/templates")
async def create_bf_template(req: BFTemplateRequest):
    """Create or update a custom Bayesian-Fuzzy domain template."""
    try:
        from xdart.phases.bayesian_fuzzy import save_custom_template
        result = save_custom_template(req.name, req.template)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[API] BF template save failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/xdart/bayesian-fuzzy/templates/{name}")
async def delete_bf_template(name: str):
    """Delete a custom Bayesian-Fuzzy template (built-in templates cannot be deleted)."""
    try:
        from xdart.phases.bayesian_fuzzy import delete_custom_template
        result = delete_custom_template(name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[API] BF template delete failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
#  VOICE — ElevenLabs TTS + STT
# ══════════════════════════════════════════════════════════════


@app.get("/xdart/voice/config")
async def voice_config():
    """Return ElevenLabs configuration for browser-side voice engine.

    TTS is currently DISABLED due to quality/stability issues.
    Re-enable by setting VOICE_ENABLED=true in environment.
    """
    # Voice disabled — WebSocket proxy had recurring disconnection issues
    # and audio quality was unacceptable. Can be re-enabled when fixed.
    voice_enabled = os.environ.get("VOICE_ENABLED", "false").lower() == "true"

    if not voice_enabled or not ELEVENLABS_API_KEY:
        return {"enabled": False, "reason": "Voice temporarily disabled"}

    return {
        "enabled": True,
        "api_key": ELEVENLABS_API_KEY,           # kept for backward compat (direct WS fallback)
        "voice_id": ELEVENLABS_VOICE_ID,
        "model_tts": ELEVENLABS_MODEL_TTS,
        "model_tts_ws": ELEVENLABS_MODEL_TTS_WS,
        "model_stt": ELEVENLABS_MODEL_STT,
        "tts_proxy_ws": True,                    # signal browser to use server proxy WS
        "tts_settings": {
            "stability": 0.55,
            "similarity_boost": 0.85,
            "speed": 1.0,
        },
    }


class TTSRequest(BaseModel):
    text: str = Field(description="Text to convert to speech")
    voice_id: str = Field(default="", description="Override default voice ID")


@app.post("/xdart/voice/tts")
async def text_to_speech(req: TTSRequest):
    """Convert text to speech using ElevenLabs TTS streaming.

    Fallback server-side proxy — used when browser WebSocket is unavailable.
    """
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY not configured")

    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    # eleven_v3 has 5 000 char limit
    if len(text) > 5000:
        text = text[:5000]

    voice_id = req.voice_id or ELEVENLABS_VOICE_ID
    if not voice_id:
        raise HTTPException(status_code=400, detail="No voice ID configured")

    import httpx

    # Use the STREAMING endpoint for low-latency chunked audio
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_TTS,
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.85,
            "speed": 1.0,
        },
    }

    logger.info("[Voice/TTS] Streaming request: %d chars, model=%s", len(text), ELEVENLABS_MODEL_TTS)

    async def _stream_audio():
        """Yield audio chunks from ElevenLabs as they arrive."""
        total_bytes = 0
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                    params={"output_format": "mp3_22050_32"},
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning("[Voice/TTS] ElevenLabs error %d: %s", resp.status_code, body[:200])
                        return
                    async for chunk in resp.aiter_bytes(chunk_size=4096):
                        total_bytes += len(chunk)
                        yield chunk
        except httpx.TimeoutException:
            logger.warning("[Voice/TTS] ElevenLabs streaming timeout")
        except Exception as exc:
            logger.error("[Voice/TTS] Streaming error: %s", exc)
        finally:
            logger.info("[Voice/TTS] Streamed %d bytes for %d chars", total_bytes, len(text))

    return StreamingResponse(
        _stream_audio(),
        media_type="audio/mpeg",
    )


@app.websocket("/xdart/voice/tts-stream")
async def tts_stream_proxy(ws: WebSocket):
    """WebSocket proxy for TTS streaming via ElevenLabs REST + eleven_v3.

    Browser sends the same protocol as ElevenLabs WebSocket:
      BOS: {text:" ", voice_settings:{...}, xi_api_key:"...", generation_config:{...}}
      Text chunks: {text: "hello world "}
      EOS: {text: ""}

    Server buffers text, detects sentence boundaries, calls ElevenLabs REST
    streaming endpoint with eleven_v3 (which doesn't support direct WebSocket),
    and forwards PCM audio chunks back as base64 — same format the browser
    already decodes.

    This gives us v3 quality + progressive streaming + sync with chat text.
    """
    import base64
    import httpx
    import re as _re_mod

    await ws.accept()

    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        logger.warning("[Voice/TTS-Proxy] Not configured — key=%s, voice=%s",
                       bool(ELEVENLABS_API_KEY), bool(ELEVENLABS_VOICE_ID))
        await ws.send_json({"error": "ElevenLabs not configured"})
        await ws.close(code=1008)
        return

    voice_settings: dict = {}
    text_buffer = ""
    total_audio_bytes = 0
    sentences_streamed = 0
    chunks_received = 0
    # Sentence boundary: split after .!?;·;\n followed by whitespace
    _SENTENCE_RE = _re_mod.compile(r'(?<=[.!?;·;\n])\s+')
    # Also flush if buffer exceeds this many chars without a sentence boundary
    _FLUSH_THRESHOLD = 200

    async def _stream_sentence(sentence: str) -> int:
        """Call ElevenLabs REST streaming for one sentence, forward PCM chunks.
        Returns total audio bytes sent for this sentence."""
        nonlocal total_audio_bytes, sentences_streamed
        sent_bytes = 0
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        }
        vs = voice_settings or {
            "stability": 0.55,
            "similarity_boost": 0.85,
            "speed": 1.0,
        }
        payload = {
            "text": sentence,
            "model_id": ELEVENLABS_MODEL_TTS,
            "voice_settings": vs,
        }
        logger.info("[Voice/TTS-Proxy] → ElevenLabs: %d chars, model=%s",
                     len(sentence), ELEVENLABS_MODEL_TTS)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload,
                    params={"output_format": "pcm_24000"},
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning("[Voice/TTS-Proxy] ElevenLabs HTTP %d: %s",
                                       resp.status_code, body[:300])
                        return 0
                    async for chunk in resp.aiter_bytes(chunk_size=4096):
                        sent_bytes += len(chunk)
                        b64 = base64.b64encode(chunk).decode("ascii")
                        await ws.send_json({"audio": b64})
        except Exception as exc:
            logger.warning("[Voice/TTS-Proxy] Sentence stream error: %s", exc)
            return sent_bytes

        total_audio_bytes += sent_bytes
        sentences_streamed += 1
        logger.info("[Voice/TTS-Proxy] ← ElevenLabs: %d bytes PCM for %d chars (sentence #%d)",
                     sent_bytes, len(sentence), sentences_streamed)
        return sent_bytes

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            # BOS message — extract voice settings
            if "xi_api_key" in msg or "voice_settings" in msg:
                vs = msg.get("voice_settings", {})
                if vs:
                    voice_settings = vs
                logger.info("[Voice/TTS-Proxy] BOS received, model=%s, voice_settings=%s",
                            ELEVENLABS_MODEL_TTS, voice_settings)
                continue

            text = msg.get("text", "")

            # EOS — flush remaining buffer and send isFinal
            if text == "":
                remaining = text_buffer.strip()
                if remaining:
                    logger.info("[Voice/TTS-Proxy] EOS flush: %d chars remaining in buffer",
                                len(remaining))
                    await _stream_sentence(remaining)
                    text_buffer = ""
                else:
                    logger.info("[Voice/TTS-Proxy] EOS: buffer empty (all text already streamed)")
                await ws.send_json({"isFinal": True})
                logger.info("[Voice/TTS-Proxy] EOS — isFinal sent "
                            "(chunks_received=%d, sentences=%d, audio=%d bytes)",
                            chunks_received, sentences_streamed, total_audio_bytes)
                break

            # Accumulate text
            chunks_received += 1
            text_buffer += text

            # Check for sentence boundaries — stream complete sentences immediately
            parts = _SENTENCE_RE.split(text_buffer)
            if len(parts) > 1:
                # All but last are complete sentences
                for sentence in parts[:-1]:
                    s = sentence.strip()
                    if s:
                        await _stream_sentence(s)
                text_buffer = parts[-1]
            elif len(text_buffer) >= _FLUSH_THRESHOLD:
                # Buffer is getting large without a sentence boundary — flush it
                # Find the last natural break point (comma, dash, colon)
                flush_text = text_buffer.strip()
                if flush_text:
                    logger.info("[Voice/TTS-Proxy] Buffer threshold flush: %d chars",
                                len(flush_text))
                    await _stream_sentence(flush_text)
                text_buffer = ""

    except WebSocketDisconnect:
        logger.info("[Voice/TTS-Proxy] Client disconnected "
                    "(chunks=%d, sentences=%d, audio=%d bytes)",
                    chunks_received, sentences_streamed, total_audio_bytes)
    except Exception as exc:
        logger.warning("[Voice/TTS-Proxy] Error: %s", exc)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


@app.post("/xdart/voice/stt")
async def speech_to_text(file: UploadFile = File(...)):
    """Transcribe audio to text using ElevenLabs Scribe v2."""
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY not configured")

    audio_bytes = await file.read()
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio file too small")
    if len(audio_bytes) > 25 * 1024 * 1024:  # 25MB limit
        raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")

    import httpx

    url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
    }

    # Determine content type from filename
    content_type = file.content_type or "audio/webm"
    filename = file.filename or "recording.webm"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                data={"model_id": ELEVENLABS_MODEL_STT},
                files={"file": (filename, audio_bytes, content_type)},
            )
            if resp.status_code != 200:
                logger.warning("[Voice/STT] ElevenLabs error %d: %s", resp.status_code, resp.text[:200])
                raise HTTPException(status_code=resp.status_code, detail=f"ElevenLabs STT error: {resp.text[:200]}")

            result = resp.json()
            transcript = result.get("text", "")
            language = result.get("language_code", "unknown")

            logger.info("[Voice/STT] Transcribed %d bytes → '%s' (lang=%s)", len(audio_bytes), transcript[:80], language)

            return {
                "text": transcript,
                "language": language,
                "language_probability": result.get("language_probability", 0),
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="ElevenLabs STT timeout")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[Voice/STT] Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════
#  SHELL EXECUTOR — Local command execution
# ══════════════════════════════════════════════════════════════


@app.get("/xdart/shell/status")
async def shell_status():
    """Get Shell Executor status, stats, and recent audit log."""
    if not _framework or not _framework.shell_executor:
        return {"status": "disabled", "message": "Shell Executor not active"}
    se = _framework.shell_executor
    return {
        "status": "enabled",
        "stats": se.get_stats(),
        "audit_log": se.get_audit_log(limit=20),
    }


class ShellExecuteRequest(BaseModel):
    command: str = Field(description="Command to execute")
    shell_type: str = Field(default="powershell", description="Shell type: powershell or cmd")
    timeout: int = Field(default=30, description="Timeout in seconds", ge=1, le=300)


@app.post("/xdart/shell/execute")
async def shell_execute(req: ShellExecuteRequest):
    """Execute a shell command directly via API."""
    if not _framework or not _framework.shell_executor:
        raise HTTPException(status_code=503, detail="Shell Executor is disabled")
    result = _framework.shell_executor.execute(
        req.command, timeout=req.timeout, shell_type=req.shell_type
    )
    return result


class ShellPythonRequest(BaseModel):
    code: str = Field(description="Python code to execute")
    timeout: int = Field(default=30, description="Timeout in seconds", ge=1, le=300)


@app.post("/xdart/shell/python")
async def shell_python(req: ShellPythonRequest):
    """Execute Python code directly via API."""
    if not _framework or not _framework.shell_executor:
        raise HTTPException(status_code=503, detail="Shell Executor is disabled")
    result = _framework.shell_executor.execute_python(req.code, timeout=req.timeout)
    return result



# ══════════════════════════════════════════════════════════════
#  AGENT SPAWNER — Sub-agent delegation
# ══════════════════════════════════════════════════════════════


@app.get("/xdart/agents/status")
async def agent_spawner_status():
    """Get Agent Spawner status, stats, and recent audit log."""
    if not _framework or not _framework.agent_spawner:
        return {"status": "disabled", "message": "Agent Spawner not active"}
    sp = _framework.agent_spawner
    return {
        "status": "enabled",
        "stats": sp.get_stats(),
        "audit_log": sp.get_audit_log(limit=20),
    }


class AgentSpawnRequest(BaseModel):
    role: str = Field(default="researcher", description="Agent role: researcher, analyst, critic, summarizer, translator, coder, fact_checker, scenario_builder, custom")
    task: str = Field(description="The task for the sub-agent")
    context: str = Field(default="", description="Additional context")
    custom_prompt: str = Field(default="", description="Custom system prompt (for role=custom)")
    max_tokens: int = Field(default=8000, description="Max tokens for response", ge=100, le=16000)
    temperature: float = Field(default=0.5, description="LLM temperature", ge=0.0, le=1.5)


@app.post("/xdart/agents/spawn")
async def agent_spawn(req: AgentSpawnRequest):
    """Spawn a single sub-agent and return its result."""
    if not _framework or not _framework.agent_spawner:
        raise HTTPException(status_code=503, detail="Agent Spawner is disabled")
    result = _framework.agent_spawner.spawn(
        role=req.role, task=req.task, context=req.context,
        custom_prompt=req.custom_prompt, max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    return {
        "agent_id": result.agent_id,
        "role": result.role,
        "success": result.success,
        "output": result.output,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }


class AgentSpawnParallelRequest(BaseModel):
    agents: list[dict] = Field(description="List of agent specs: [{role, task, context?, custom_prompt?, max_tokens?, temperature?}]")
    timeout: int = Field(default=120, description="Overall timeout in seconds", ge=10, le=600)


@app.post("/xdart/agents/spawn-parallel")
async def agent_spawn_parallel(req: AgentSpawnParallelRequest):
    """Spawn multiple sub-agents in parallel and return all results."""
    if not _framework or not _framework.agent_spawner:
        raise HTTPException(status_code=503, detail="Agent Spawner is disabled")
    if not req.agents:
        raise HTTPException(status_code=400, detail="No agents specified")
    results = _framework.agent_spawner.spawn_parallel(req.agents, timeout=req.timeout)
    return {
        "count": len(results),
        "successful": sum(1 for r in results if r.success),
        "results": [
            {
                "agent_id": r.agent_id,
                "role": r.role,
                "success": r.success,
                "output": r.output,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in results
        ],
    }


@app.get("/static/{filename}")
async def serve_static(filename: str):
    """Serve static assets (page-agent.js etc.)."""
    import re as _re
    if not _re.match(r'^[\w.-]+$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    static_dir = Path(__file__).parent.parent / "static"
    file_path = static_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media = "application/javascript" if filename.endswith(".js") else "application/octet-stream"
    return FileResponse(file_path, media_type=media)
