"""
XDART-Φ × XHEART — Configuration

All settings loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Explicit path — immune to CWD issues (Greek directory names on Windows
# can break find_dotenv() which relies on os.getcwd() traversal)
_dotenv_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_dotenv_path, override=False)

# ── Paths ──
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))

# ── OpenAI ──
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4")
OPENAI_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "65536"))
OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

# ── LLM Context Window ──
# Maximum context length for the model. DeepSeek chat: 131072. GPT-5.4: 128000+.
# Used for prompt budget enforcement — prevents 400 errors from oversized prompts.
LLM_MAX_CONTEXT_TOKENS: int = int(os.getenv("LLM_MAX_CONTEXT_TOKENS", "131072"))

# ── LLM Provider (multi-provider support) ──
# Set LLM_BASE_URL to switch providers. Leave empty for OpenAI default.
# DeepSeek: https://api.deepseek.com
# OpenAI:   https://api.openai.com/v1 (default, leave empty)
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
# DeepSeek models: "deepseek-chat" (V3.2 fast), "deepseek-reasoner" (V3.2 with CoT thinking)
# When using deepseek-reasoner, reasoning_content is captured and logged.
LLM_REASONING_ENABLED: bool = os.getenv("LLM_REASONING_ENABLED", "false").lower() in ("true", "1", "yes")
# Enable thinking/CoT for DeepSeek models (works with both deepseek-chat and deepseek-reasoner)
# Adds {"thinking": {"type": "enabled"}} to API calls
LLM_THINKING_ENABLED: bool = os.getenv("LLM_THINKING_ENABLED", "true").lower() in ("true", "1", "yes")
# ── Embedding provider — DeepSeek doesn't have embeddings, keep OpenAI for this
EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "")

# ── Local (offline) embeddings via fastembed ──
# Set LOCAL_EMBEDDING_ENABLED=true to use fastembed instead of OpenAI.
# Requires `pip install fastembed` (already installed).
# Default model: BAAI/bge-small-en-v1.5 → 384 dims.
# ⚠ Changing dims requires QDRANT_VECTOR_SIZE to match + Qdrant collections will be recreated.
LOCAL_EMBEDDING_ENABLED: bool = os.getenv("LOCAL_EMBEDDING_ENABLED", "false").lower() in ("true", "1", "yes")
LOCAL_EMBEDDING_MODEL: str = os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
LOCAL_EMBEDDING_DIM: int = int(os.getenv("LOCAL_EMBEDDING_DIM", "384"))
# ── LLM Fallback Provider ──
# If primary LLM (e.g. DeepSeek) fails/times out, fall back to this provider.
# Explicitly set in .env to disable fallback (empty string = no fallback client created)
LLM_FALLBACK_API_KEY: str = os.getenv("LLM_FALLBACK_API_KEY", "")
LLM_FALLBACK_BASE_URL: str = os.getenv("LLM_FALLBACK_BASE_URL", "")  # empty = OpenAI default
LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "gpt-4o-mini")

# ── MongoDB (Structured Persistence) ──
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "aiolos")

# ── Qdrant (Episodic Memory — local embedded mode, zero Docker) ──
QDRANT_STORAGE_PATH: str = os.getenv("QDRANT_STORAGE_PATH", str(DATA_DIR / "qdrant_storage"))
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "xheart_states")
# Auto-match vector size to local embedding dim when LOCAL_EMBEDDING_ENABLED=true
_default_vector_size = str(LOCAL_EMBEDDING_DIM) if LOCAL_EMBEDDING_ENABLED else "1536"
QDRANT_VECTOR_SIZE: int = int(os.getenv("QDRANT_VECTOR_SIZE", _default_vector_size))

# ── Framework Parameters ──
XDART_MIN_DOMAINS: int = int(os.getenv("XDART_MIN_DOMAINS", "10"))
XDART_MAX_VIEWS: int = int(os.getenv("XDART_MAX_VIEWS", "18"))
XHEART_MEMORY_TOP_K: int = int(os.getenv("XHEART_MEMORY_TOP_K", "3"))
LAYER3_THRESHOLD: int = int(os.getenv("LAYER3_THRESHOLD", "4"))

# ── Identity / Character / Immediate Memory ──
CHARACTER_STATE_PATH: str = os.getenv("CHARACTER_STATE_PATH", str(DATA_DIR / "character_state.json"))
IMMEDIATE_MEMORY_PATH: str = os.getenv("IMMEDIATE_MEMORY_PATH", str(DATA_DIR / "immediate_memory.json"))

# ── Perception Layer (Data Perception — real-world awareness) ──
PERCEPTION_ENABLED: bool = os.getenv("PERCEPTION_ENABLED", "true").lower() in ("true", "1", "yes")
PERCEPTION_DB_PATH: str = os.getenv("PERCEPTION_DB_PATH", str(DATA_DIR / "perception.db"))
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
UCDP_API_TOKEN: str = os.getenv("UCDP_API_TOKEN", "")
FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
PERCEPTION_HOURS_BACK: int = int(os.getenv("PERCEPTION_HOURS_BACK", "72"))
PERCEPTION_MAX_EVENTS: int = int(os.getenv("PERCEPTION_MAX_EVENTS", "10"))
PERCEPTION_MAX_ECONOMIC: int = int(os.getenv("PERCEPTION_MAX_ECONOMIC", "5"))

# ── Palantir P0: Real-Time Intelligence Feeds ──
# OTX AlienVault (free, register at https://otx.alienvault.com)
OTX_API_KEY: str = os.getenv("OTX_API_KEY", "***REMOVED***")
# GreyNoise Community (free, register at https://www.greynoise.io)
GREYNOISE_API_KEY: str = os.getenv("GREYNOISE_API_KEY", "***REMOVED***")
# Sanctions cross-reference auto-download (always enabled, no key needed)
SANCTIONS_ENABLED: bool = os.getenv("SANCTIONS_ENABLED", "true").lower() in ("true", "1", "yes")
# Event calendar (always enabled, curated + dynamic)
EVENT_CALENDAR_ENABLED: bool = os.getenv("EVENT_CALENDAR_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Evolution Core (autonomous self-improvement) ──
EVOLUTION_ENABLED: bool = os.getenv("EVOLUTION_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Curiosity Engine (autonomous self-orientation) ──
CURIOSITY_ENABLED: bool = os.getenv("CURIOSITY_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Logic Sandbox (self-modification of algorithmic functions) ──
LOGIC_SANDBOX_ENABLED: bool = os.getenv("LOGIC_SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Dynamic Principle Registry (learned operating principles from experience) ──
PRINCIPLE_REGISTRY_ENABLED: bool = os.getenv("PRINCIPLE_REGISTRY_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Quantum Scenario Engine (Phase 2.91) ──
QUANTUM_ENABLED: bool = os.getenv("QUANTUM_ENABLED", "true").lower() in ("true", "1", "yes")
QUANTUM_COHERENCE_INITIAL: float = float(os.getenv("QUANTUM_COHERENCE_INITIAL", "0.95"))
QUANTUM_DECOHERENCE_RATE: float = float(os.getenv("QUANTUM_DECOHERENCE_RATE", "0.01"))
QUANTUM_INTERFERENCE_THRESHOLD: float = float(os.getenv("QUANTUM_INTERFERENCE_THRESHOLD", "0.03"))

# ── Bayesian-Fuzzy Reasoning Engine (Phase 2.92) ──
BAYESIAN_FUZZY_ENABLED: bool = os.getenv("BAYESIAN_FUZZY_ENABLED", "true").lower() in ("true", "1", "yes")
BAYESIAN_FUZZY_PRIOR_WEIGHT: float = float(os.getenv("BAYESIAN_FUZZY_PRIOR_WEIGHT", "1.5"))

# ── Web Agent (browser + search capabilities) ──
WEB_AGENT_ENABLED: bool = os.getenv("WEB_AGENT_ENABLED", "true").lower() in ("true", "1", "yes")
# Lightpanda CDP URL — Docker: docker run -d --name lightpanda -p 9222:9222 lightpanda/browser:nightly
# Leave empty to use Playwright built-in Chromium, or httpx-only mode
LIGHTPANDA_CDP_URL: str = os.getenv("LIGHTPANDA_CDP_URL", "")  # e.g. "ws://127.0.0.1:9222"
# Set to False to allow scraping of sites that disallow robots
WEB_AGENT_RESPECT_ROBOTS: bool = os.getenv("WEB_AGENT_RESPECT_ROBOTS", "true").lower() in ("true", "1", "yes")

# ── Search Engine Configuration ──
# Search engine priority order. Comma-separated list.
# Available: searxng, brave, duckduckgo
# SearXNG is recommended primary — self-hosted, no rate limits, aggregates multiple engines.
# Brave Search free tier: 2000 queries/month, very reliable.
# DuckDuckGo: no key needed but aggressive rate-limiting.
SEARCH_ENGINE_ORDER: str = os.getenv("SEARCH_ENGINE_ORDER", "brave,duckduckgo,searxng")

# SearXNG — self-hosted meta-search engine (recommended)
# Docker: docker run -d -p 8888:8080 -e SEARXNG_SECRET=xdart searxng/searxng
SEARXNG_URL: str = os.getenv("SEARXNG_URL", "http://localhost:8888")

# Brave Search API — free tier: 2000 queries/month
# Get key at: https://brave.com/search/api/
BRAVE_SEARCH_API_KEY: str = os.getenv("BRAVE_SEARCH_API_KEY", "")

# ── Meta-Orchestrator (adaptive pipeline intelligence) ──
# When enabled, the system plans its own analysis path instead of running
# a fixed linear sequence. Includes reflection gates, custom phase injection,
# and parallel branching.
META_ORCHESTRATOR_ENABLED: bool = os.getenv("META_ORCHESTRATOR_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Shell Executor (Αίολος' hands on the local system) ──
# When enabled, Αίολος can execute PowerShell commands, run Python scripts,
# browse the filesystem, and manage processes on the local machine.
SHELL_EXECUTOR_ENABLED: bool = os.getenv("SHELL_EXECUTOR_ENABLED", "true").lower() in ("true", "1", "yes")
SHELL_EXECUTOR_TIMEOUT: int = int(os.getenv("SHELL_EXECUTOR_TIMEOUT", "30"))

# ── Agent Spawner (Αίολος' ability to delegate to sub-agents) ──
# When enabled, Αίολος can spawn specialized sub-agents (researcher, analyst, critic, etc.)
# that run as parallel LLM calls and return results to the main conversation.
AGENT_SPAWNER_ENABLED: bool = os.getenv("AGENT_SPAWNER_ENABLED", "true").lower() in ("true", "1", "yes")
AGENT_SPAWNER_MAX_CONCURRENT: int = int(os.getenv("AGENT_SPAWNER_MAX_CONCURRENT", "5"))
AGENT_SPAWNER_TIMEOUT: int = int(os.getenv("AGENT_SPAWNER_TIMEOUT", "60"))

# ── Proactive Communication Engine ──
# When enabled, Αίολος can initiate contact with the user autonomously.
# Evaluates findings from curiosity, perception, prophecy resolution for importance.
PROACTIVE_ENABLED: bool = os.getenv("PROACTIVE_ENABLED", "true").lower() in ("true", "1", "yes")
# Telegram Bot API — create a bot via @BotFather, paste token here.
# Chat ID: send /start to your bot, then GET https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Telegram MTProto Intelligence (TelegramIntelTool — user account, NOT bot) ──
# Required for Tier 2: join private channels, read history, native search
# Get api_id and api_hash from: https://my.telegram.org/apps (create an app)
# After setting these, run: python _setup_telegram_session.py (one-time phone verification)
TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION_NAME: str = os.getenv("TELEGRAM_SESSION_NAME", ".telegram_session")
# Tier 1 is always active (web search + t.me/s/ validation — no credentials needed)
TELEGRAM_INTEL_TIER2_ENABLED: bool = bool(TELEGRAM_API_ID and TELEGRAM_API_HASH)

# ── Multimodal Perception ──
# OpenSky Network (free, registration recommended for higher rate limits)
# API Client credentials — clientId as user, clientSecret as pass
OPENSKY_USER: str = os.getenv("OPENSKY_USER", "***REMOVED***")
OPENSKY_PASS: str = os.getenv("OPENSKY_PASS", "***REMOVED***")
# NASA FIRMS (free MAP_KEY from https://firms.modaps.eosdis.nasa.gov/api/area/)
FIRMS_MAP_KEY: str = os.getenv("FIRMS_MAP_KEY", "***REMOVED***")
# MarineTraffic (optional, free tier available)
MARINETRAFFIC_API_KEY: str = os.getenv("MARINETRAFFIC_API_KEY", "")
# Enable/disable multimodal perception
MULTIMODAL_ENABLED: bool = os.getenv("MULTIMODAL_ENABLED", "true").lower() in ("true", "1", "yes")

# ── Cross-system Learning ──
# CORE API key (free from https://core.ac.uk/services/api)
# Works without key (100 tokens/day unauth), better with key (1000+/day)
CORE_API_KEY: str = os.getenv("CORE_API_KEY", "")
# Semantic Scholar API key (free from https://www.semanticscholar.org/product/api)
# Without key: 1000 req/s shared among ALL unauthenticated users (frequent 429s)
# With key: dedicated 1 RPS (introductory), much more reliable
S2_API_KEY: str = os.getenv("S2_API_KEY", "")
# Enable/disable cross-system learning
CROSS_SYSTEM_LEARNING_ENABLED: bool = os.getenv("CROSS_SYSTEM_LEARNING_ENABLED", "true").lower() in ("true", "1", "yes")

# ── ElevenLabs Voice (TTS + STT) ──
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_MODEL_TTS: str = os.getenv("ELEVENLABS_MODEL_TTS", "eleven_v3")
ELEVENLABS_MODEL_TTS_WS: str = os.getenv("ELEVENLABS_MODEL_TTS_WS", "eleven_multilingual_v2")
ELEVENLABS_MODEL_STT: str = os.getenv("ELEVENLABS_MODEL_STT", "scribe_v2")

# ── Vision System (Αίολος' Eyes) ──
# Face detection + recognition via FaceNet microservice
VISION_ENABLED: bool = os.getenv("VISION_ENABLED", "true").lower() in ("true", "1", "yes")
VISION_SERVICE_URL: str = os.getenv("VISION_SERVICE_URL", "http://localhost:8100")
# Minimum interval between proactive conversation triggers from vision (seconds)
VISION_PRESENCE_COOLDOWN: int = int(os.getenv("VISION_PRESENCE_COOLDOWN", "300"))

# ── Logging ──
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── CORS (production: restrict to your domain) ──
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
]

# ── Data File Paths (all default to DATA_DIR for volume mount compatibility) ──
INTROSPECTION_LOG_PATH: str = str(DATA_DIR / "introspection_log.jsonl")
SELF_EVOLUTION_JOURNAL_PATH: str = str(DATA_DIR / "self_evolution_journal.jsonl")
CORE_CHANGE_LOG_PATH: str = str(DATA_DIR / "core_change_log.jsonl")
WISDOM_CALIBRATION_PATH: str = str(DATA_DIR / "wisdom_calibration.json")
SELF_AWARENESS_BRIEF_PATH: str = str(DATA_DIR / "self_awareness_brief.json")
PROMPT_OVERLAYS_PATH: str = str(DATA_DIR / "prompt_overlays.json")
CURIOSITY_JOURNAL_PATH: str = str(DATA_DIR / "curiosity_journal.jsonl")
CURIOSITY_STATE_PATH: str = str(DATA_DIR / "curiosity_state.json")
PROACTIVE_LOG_PATH: str = str(DATA_DIR / "proactive_log.jsonl")

# ── Palantir: Scheduled Autonomous Briefings ──
# When enabled, Αίολος generates a full Executive Intelligence Brief on a
# schedule and pushes it to Telegram + SSE without any human trigger.
# BRIEFING_SCHEDULE_TIMES: comma-separated "HH:MM" values in Athens time.
# E.g. "06:00" or "06:00,18:00" for morning and evening briefs.
BRIEFING_ENABLED: bool = os.getenv("BRIEFING_ENABLED", "true").lower() in ("true", "1", "yes")
BRIEFING_SCHEDULE_TIMES: list[str] = [
    t.strip() for t in os.getenv("BRIEFING_SCHEDULE_TIMES", "06:00").split(",") if t.strip()
]
BRIEFING_TIMEZONE: str = os.getenv("BRIEFING_TIMEZONE", "Europe/Athens")

# ── Dark Whisper Intelligence (Palantir Dark Wing — clearnet OSINT) ──
# Monitors dark-adjacent clearnet sources: Telegram threat actor channels,
# paste sites, ahmia.fi dark web index, and optional OSINT APIs.
# ALL signals are isolated in a dirty pool; LLM triage before any integration.
# DISABLED by default — enable explicitly when ready for dark signal intake.
DARKWEB_ENABLED: bool = os.getenv("DARKWEB_ENABLED", "false").lower() in ("true", "1", "yes")

# Collection interval in seconds (default: 30 minutes)
DARKWEB_COLLECTION_INTERVAL: int = int(os.getenv("DARKWEB_COLLECTION_INTERVAL", "1800"))

# Telegram public channels to monitor (comma-separated, without @)
# Telegram public broadcast channels that support t.me/s/{channel} web preview.
# IMPORTANT: channels without web preview enabled return a 302 redirect and yield
# 0 signals. Only list channels verified to have web preview enabled.
# Verified 2026-04-28: vxunderground, RedPacketSecurity, secharvester all return
# live messages. The old hacktivist channels (KillNet, NoName, AnonymousSudan etc.)
# have all disabled web preview — they are removed from the default list.
DARKWEB_TELEGRAM_CHANNELS: list[str] = [
    c.strip() for c in os.getenv(
        "DARKWEB_TELEGRAM_CHANNELS",
        "vxunderground,RedPacketSecurity,secharvester",
    ).split(",") if c.strip()
]

# Ahmia.fi — clearnet index of dark web content (search-engine style)
# NOTE: ahmia.fi clearnet search results are JS-rendered (AJAX) — the plain HTTP
# response is a shell page with no results. Disabled by default until a proper
# headless browser or their onion service is integrated.
DARKWEB_AHMIA_ENABLED: bool = os.getenv("DARKWEB_AHMIA_ENABLED", "false").lower() in ("true", "1", "yes")

# Paste sites polling (pastebin public archive)
DARKWEB_PASTE_ENABLED: bool = os.getenv("DARKWEB_PASTE_ENABLED", "true").lower() in ("true", "1", "yes")

# OSINT API keys (optional — leave empty to skip)
# DarkOwl: https://www.darkowl.com/  (paid, enterprise)
DARKWEB_DARKOWL_KEY: str = os.getenv("DARKWEB_DARKOWL_KEY", "")
# IntelligenceX: https://intelx.io/  (free tier available)
DARKWEB_INTELX_KEY: str = os.getenv("DARKWEB_INTELX_KEY", "")

# Minimum raw credibility (0-1) for a collected signal to enter dirty pool
DARKWEB_MIN_CREDIBILITY: float = float(os.getenv("DARKWEB_MIN_CREDIBILITY", "0.05"))

# LLM triage batch size (signals processed together in one LLM call)
DARKWEB_TRIAGE_BATCH_SIZE: int = int(os.getenv("DARKWEB_TRIAGE_BATCH_SIZE", "10"))

# MAYBE signal reactivation threshold — entity/topic overlap fraction required
# to reactivate a dormant dark whisper when new evidence arrives
DARKWEB_REACTIVATION_THRESHOLD: float = float(os.getenv("DARKWEB_REACTIVATION_THRESHOLD", "0.35"))

# Threat keywords for ahmia.fi and paste site search targeting
DARKWEB_THREAT_KEYWORDS: list[str] = [
    k.strip() for k in os.getenv(
        "DARKWEB_THREAT_KEYWORDS",
        "cyberattack,ransomware,data breach,critical infrastructure,"
        "NATO,Greece,Turkey,Israel,Iran,Russia,Ukraine,"
        "financial system,power grid,water treatment,ddos campaign,"
        "zero-day exploit,supply chain attack",
    ).split(",") if k.strip()
]

# Maximum age (hours) of dark signals to keep in dirty pool before auto-purge
DARKWEB_MAX_SIGNAL_AGE_HOURS: int = int(os.getenv("DARKWEB_MAX_SIGNAL_AGE_HOURS", "168"))  # 7 days

# ── RSS threat intelligence feeds ────────────────────────────────────────────
# Public RSS/Atom feeds from established cybersecurity sources.
# These are clearnet, no API key required, and provide high-credibility signals.
# Entries are filtered by DARKWEB_THREAT_KEYWORDS before entering the dirty pool.
DARKWEB_RSS_ENABLED: bool = os.getenv("DARKWEB_RSS_ENABLED", "true").lower() in ("true", "1", "yes")

_DEFAULT_RSS_FEEDS = (
    # CISA Known Exploited Vulnerabilities / Advisories
    "https://www.cisa.gov/cybersecurity-advisories/all-advisories.xml,"
    # BleepingComputer — covers ransomware, breaches, APT campaigns
    "https://www.bleepingcomputer.com/feed/,"
    # The Hacker News — threat intelligence, zero-days, nation-state activity
    "https://feeds.feedburner.com/TheHackersNews,"
    # SecurityWeek — enterprise security, OT/ICS, APT
    "https://www.securityweek.com/feed/,"
    # The Record by Recorded Future — geopolitical cyber coverage
    "https://therecord.media/feed,"
    # Krebs on Security — deep investigative cybercrime/breach coverage
    "https://krebsonsecurity.com/feed/"
)

DARKWEB_RSS_FEEDS: list[str] = [
    u.strip() for u in os.getenv("DARKWEB_RSS_FEEDS", _DEFAULT_RSS_FEEDS).split(",")
    if u.strip()
]
