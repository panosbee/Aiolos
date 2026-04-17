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
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
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


# ── App ──

_framework: XDARTFramework | None = None
_collector: object | None = None  # DataCollector — stored for intelligence endpoint
_collector_task: asyncio.Task | None = None
_consolidation_task: asyncio.Task | None = None
_proactive_engine = None  # ProactiveEngine — stored for notification endpoints
_vision_integration = None  # VisionIntegration — stored for vision endpoints
_mongo_store = None  # MongoStore — structured persistence layer
_last_audit_result: dict = {}  # Latest system audit results — populated by audit loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _framework, _collector, _collector_task, _consolidation_task, _proactive_engine, _vision_integration, _mongo_store
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
        else:
            logger.warning("MongoDB unavailable — running without database")
    except Exception as e:
        logger.warning("MongoDB init failed (continuing without): %s", e)

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
            # Wire prophetic memory for autonomous prophecy generation
            if hasattr(_framework, 'prophetic_memory') and _framework.prophetic_memory:
                _proactive_engine.prophetic_memory = _framework.prophetic_memory
            # Start daily digest loop
            digest_loop = ProactiveDigestLoop(
                engine=_proactive_engine,
                llm=_framework.llm,
            )
            _proactive_task = asyncio.create_task(digest_loop.run_forever())
            logger.info("Proactive engine started (telegram=%s)",
                        "yes" if TELEGRAM_BOT_TOKEN else "no")
        except Exception as e:
            logger.warning("Proactive engine failed to start: %s", e)

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

    # Start background perception collector if enabled
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

            # ── Financial Market Collector (VIX, S&P500, Oil, Gold, BTC, etc.) ──
            market_collector = None
            try:
                from xdart.perception.financial_feeds import MarketDataCollector
                market_collector = MarketDataCollector()
                logger.info("Financial market collector initialized (%d tickers)",
                            len(market_collector._history) or 8)
            except Exception as e:
                logger.warning("Financial feeds init failed (continuing without): %s", e)

            # Wire entity graph + market collector into ProactiveEngine
            if _proactive_engine:
                _proactive_engine.entity_graph = entity_graph
                _proactive_engine.market_collector = market_collector
                if _mongo_store and _mongo_store.available:
                    _proactive_engine._mongo = _mongo_store

            # Wire into framework for chat mode access
            if _framework:
                _framework._entity_graph = entity_graph
                _framework._market_collector = market_collector

            collector = DataCollector(
                db=perception_db,
                filter_layer=perception_filter,
                fred_api_key=FRED_API_KEY,
                ucdp_api_token=UCDP_API_TOKEN,
                finnhub_api_key=FINNHUB_API_KEY,
                on_alert=_proactive_alert_handler,
                entity_graph=entity_graph,
                market_collector=market_collector,
            )
            _collector = collector  # store reference for intelligence endpoint
            _collector_task = asyncio.create_task(collector.run_forever())
            # Wire PerceptionDB into ProactiveEngine for auto-research storage
            if _proactive_engine:
                _proactive_engine.perception_db = perception_db
            logger.info("Perception collector started as background task")
        except Exception as e:
            logger.warning("Perception collector failed to start: %s", e)

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

                    await asyncio.sleep(30 * 60)  # Every 30 minutes

            _sandbox_maintenance_task = asyncio.create_task(_sandbox_maintenance_loop())
            logger.info("Logic Sandbox maintenance loop started (30min interval)")
    except Exception as e:
        logger.warning("Logic Sandbox maintenance loop failed to start: %s", e)

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
                await asyncio.sleep(6 * 3600)  # Then every 6 hours

        _resolver_task = asyncio.create_task(_prophecy_resolution_loop())
        logger.info("Prophecy resolution loop started (6h interval)")
    except Exception as e:
        logger.warning("Prophecy resolution loop failed to start: %s", e)

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
        except Exception as e:
            logger.warning("Curiosity loop failed to start: %s", e)

    # Start background multimodal perception (airspace, maritime, satellite)
    _multimodal_task = None
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
            )
            # Store reference for stats endpoint
            if _framework:
                _framework._multimodal_collector = _multimodal_collector
            _multimodal_task = asyncio.create_task(_multimodal_collector.run_forever())
            logger.info("Multimodal perception started (airspace=%s, satellite=%s, maritime=yes)",
                        "auth" if OPENSKY_USER else "anon",
                        "yes" if FIRMS_MAP_KEY else "no")
        except Exception as e:
            logger.warning("Multimodal perception failed to start: %s", e)

    # Start background cross-system learning (daily paper acquisition)
    _cross_system_task = None
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
                cache_path=str(Path(PERCEPTION_DB_PATH).parent / "cross_system_cache.json"),
            )
            _cross_system_loop = CrossSystemLearningLoop(
                learner=_cross_system_learner,
                curiosity_engine=_framework.curiosity_engine if hasattr(_framework, 'curiosity_engine') else None,
                proactive_engine=_proactive_engine,
                interval_hours=24,
            )
            if _framework:
                _framework._cross_system_learner = _cross_system_learner
            _cross_system_task = asyncio.create_task(_cross_system_loop.run_forever())
            logger.info("Cross-system learning started (core=%s, openalex=free, daily cycle)",
                        "key" if CORE_API_KEY else "unauth")
        except Exception as e:
            logger.warning("Cross-system learning failed to start: %s", e)

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
        except Exception as e:
            logger.warning("Vision integration failed to initialize: %s", e)

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
    except Exception as e:
        logger.warning("Memory consolidation loop failed to start: %s", e)

    # Start background System Integrity Audit loop (every 2 hours)
    _audit_task = None
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

                await asyncio.sleep(2 * 3600)  # Every 2 hours

        _audit_task = asyncio.create_task(_system_audit_loop())
        logger.info("System integrity audit loop started (2h interval)")
    except Exception as e:
        logger.warning("System audit loop failed to start: %s", e)

    logger.info("XDART-Φ API started")
    yield

    if _collector_task:
        _collector_task.cancel()
    if _consolidation_task:
        _consolidation_task.cancel()
    if _resolver_task:
        _resolver_task.cancel()
    if _curiosity_task:
        _curiosity_task.cancel()
    if _proactive_task:
        _proactive_task.cancel()
    if _multimodal_task:
        _multimodal_task.cancel()
    if _cross_system_task:
        _cross_system_task.cancel()
    if _audit_task:
        _audit_task.cancel()
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
    def _get():
        return HealthResponse(
            status="ok",
            model=OPENAI_MODEL,
            memories=_framework.memory.entry_count if _framework else 0,
            concepts=_framework.memory.concept_count if _framework else 0,
            pipeline_running=_framework.pipeline_running if _framework else False,
        )
    return await asyncio.get_event_loop().run_in_executor(None, _get)


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

    result = await asyncio.get_event_loop().run_in_executor(None, _run)

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
    _proactive_engine._notifications.append(test_notif)
    _proactive_engine._deliver_immediate(test_notif)
    _proactive_engine._log_notification(test_notif)

    return {"status": "sent", "notification": test_notif.to_dict()}


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
    return HTMLResponse(content=ui_path.read_text(encoding="utf-8"))


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the ΑΙΟΛΟΣ JARVIS Command Center dashboard."""
    dash_path = Path(__file__).parent.parent / "dashboard.html"
    if not dash_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return HTMLResponse(content=dash_path.read_text(encoding="utf-8"))


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

    The browser connects DIRECTLY to ElevenLabs WebSocket for TTS
    (lowest latency) and uses the REST API for STT. The API key is
    stored server-side and served only to the authenticated client.
    """
    if not ELEVENLABS_API_KEY:
        return {"enabled": False, "reason": "ELEVENLABS_API_KEY not set"}

    return {
        "enabled": True,
        "api_key": ELEVENLABS_API_KEY,
        "voice_id": ELEVENLABS_VOICE_ID,
        "model_tts": ELEVENLABS_MODEL_TTS,
        "model_tts_ws": ELEVENLABS_MODEL_TTS_WS,
        "model_stt": ELEVENLABS_MODEL_STT,
        "tts_settings": {
            "stability": 0.70,
            "similarity_boost": 0.75,
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
        # NOTE: language_code NOT set — eleven_v3 natively handles
        # code-switching (mixed Greek + English) via auto-detection.
        # Forcing a single language_code breaks the other language's pronunciation.
        "voice_settings": {
            "stability": 0.70,          # 0.70 = reduce hallucinations/gibberish
            "similarity_boost": 0.75,
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
