"""
XDART-Φ × XHEART — LLM Client

Multi-provider wrapper (OpenAI, DeepSeek, any OpenAI-compatible API).
Supports structured JSON output, embedding generation, reasoning/CoT capture,
and consistent error handling.

Provider switching via env vars:
  LLM_BASE_URL=""                  → OpenAI (default)
  LLM_BASE_URL="https://api.deepseek.com" → DeepSeek
  OPENAI_MODEL="deepseek-chat"     → DeepSeek V3.2 (fast)
  OPENAI_MODEL="deepseek-reasoner" → DeepSeek V3.2 (thinking/CoT)
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Any, Generator

from openai import OpenAI

from xdart.config import (
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_MODEL,
    OPENAI_MAX_TOKENS,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    LLM_BASE_URL,
    LLM_THINKING_ENABLED,
    LLM_MAX_CONTEXT_TOKENS,
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    LLM_FALLBACK_API_KEY,
    LLM_FALLBACK_BASE_URL,
    LLM_FALLBACK_MODEL,
    LOCAL_EMBEDDING_ENABLED,
    LOCAL_EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


# ── Embedding circuit breaker ─────────────────────────────────────────────────
# When OpenAI returns insufficient_quota (billing issue, not a transient 429),
# we stop hammering the endpoint for EMBED_QUOTA_COOLDOWN_MINUTES.
# This eliminates the repeated "Episodic store failed: 429" spam.
_embed_circuit: dict = {
    "open": False,           # True = circuit open, all embed calls fail fast
    "open_until": None,      # datetime when circuit closes again
    "last_error": "",        # last error message for logging context
}
_embed_circuit_lock = Lock()
_EMBED_QUOTA_COOLDOWN_MINUTES = 30  # re-try after 30 min
_EMBED_RATE_COOLDOWN_MINUTES = 2    # transient rate-limit: shorter cooldown


def _check_embed_circuit() -> str | None:
    """Return error string if circuit is open, else None (circuit closed = OK to call)."""
    with _embed_circuit_lock:
        if not _embed_circuit["open"]:
            return None
        if datetime.now(timezone.utc) >= _embed_circuit["open_until"]:
            # Cooldown expired — close circuit and retry
            _embed_circuit["open"] = False
            _embed_circuit["open_until"] = None
            logger.info("[LLM.embed] Circuit breaker reset — retrying OpenAI embeddings")
            return None
        remaining = (_embed_circuit["open_until"] - datetime.now(timezone.utc)).seconds // 60
        return f"Embedding circuit open ({remaining}min remaining): {_embed_circuit['last_error'][:120]}"


def _trip_embed_circuit(error_msg: str, *, quota: bool = False) -> None:
    """Open the embedding circuit breaker after a quota/rate-limit error."""
    cooldown = _EMBED_QUOTA_COOLDOWN_MINUTES if quota else _EMBED_RATE_COOLDOWN_MINUTES
    with _embed_circuit_lock:
        _embed_circuit["open"] = True
        _embed_circuit["open_until"] = datetime.now(timezone.utc) + timedelta(minutes=cooldown)
        _embed_circuit["last_error"] = error_msg
    level = "ERROR" if quota else "WARNING"
    logger.log(
        logging.ERROR if quota else logging.WARNING,
        "[LLM.embed] ⚡ Circuit breaker OPEN for %d min [%s]: %s",
        cooldown, "quota_exceeded" if quota else "rate_limit", error_msg[:200],
    )


# ── Local fastembed (offline fallback) ───────────────────────────────────────
_local_embed_model = None
_local_embed_lock = Lock()


def _get_local_embed_model():
    """Lazy-load the fastembed model (downloads on first use, cached to disk thereafter)."""
    global _local_embed_model
    if _local_embed_model is not None:
        return _local_embed_model
    with _local_embed_lock:
        if _local_embed_model is not None:
            return _local_embed_model
        try:
            from fastembed import TextEmbedding
            from pathlib import Path as _Path
            _cache = str(_Path(__file__).resolve().parent.parent / ".fastembed_cache")
            logger.info("[LLM.embed] Loading local fastembed model: %s (cache=%s)", LOCAL_EMBEDDING_MODEL, _cache)
            _local_embed_model = TextEmbedding(model_name=LOCAL_EMBEDDING_MODEL, cache_dir=_cache)
            logger.info("[LLM.embed] Local fastembed model ready")
        except Exception as exc:
            logger.error("[LLM.embed] Failed to load local fastembed model: %s", exc)
            raise
    return _local_embed_model


def _local_embed(text: str) -> list[float]:
    """Generate embedding using local fastembed model."""
    model = _get_local_embed_model()
    # fastembed returns a generator of numpy arrays
    results = list(model.embed([text]))
    return results[0].tolist()


def _local_embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate batch embeddings using local fastembed model."""
    model = _get_local_embed_model()
    results = list(model.embed(texts))
    return [r.tolist() for r in results]


def prewarm_local_embed() -> bool:
    """Pre-load the fastembed model at startup so the first embed call doesn't block.

    Call from api.py lifespan in a background thread before HTTP requests arrive.
    Returns True on success, False on failure.
    """
    if not LOCAL_EMBEDDING_ENABLED:
        return False
    try:
        _get_local_embed_model()
        logger.info("[LLM.embed] Prewarm complete — model ready")
        return True
    except Exception as exc:
        logger.error("[LLM.embed] Prewarm failed: %s", exc)
        return False


def _is_reasoning_model(model: str) -> bool:
    """Check if the model is a reasoning/thinking model (DeepSeek-reasoner, o1, etc)."""
    reasoning_indicators = ("reasoner", "o1-", "o3-")
    return any(ind in model.lower() for ind in reasoning_indicators)


def _estimate_tokens(text_or_chars: str | int) -> int:
    """Fast token count estimate: ~3.5 chars per token for English mixed content."""
    n = text_or_chars if isinstance(text_or_chars, int) else len(text_or_chars)
    return n // 3


class LLMClient:
    """Multi-provider LLM client for XDART-Φ framework.

    Supports OpenAI, DeepSeek, and any OpenAI-compatible API.
    Automatically handles reasoning model differences (no temperature,
    reasoning_content capture).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        resolved_key = api_key or OPENAI_API_KEY
        if not resolved_key:
            raise ValueError(
                "API key not set. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )

        # Build client kwargs
        client_kwargs: dict[str, Any] = {"api_key": resolved_key}
        resolved_base_url = base_url or LLM_BASE_URL
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url

        # Timeout: keep connect at 10s (fast-fail if server unreachable) but set
        # read to None so httpx never cuts off long DeepSeek thinking chains.
        # The hard wall-clock ceiling is enforced by _api_call_with_timeout's
        # thread-pool future.result(timeout=_API_CALL_TIMEOUT).
        import httpx
        client_kwargs["timeout"] = httpx.Timeout(None, connect=10.0)

        self.client = OpenAI(**client_kwargs)
        self.model = model or OPENAI_MODEL
        self.is_reasoning = _is_reasoning_model(self.model)
        self._base_url = resolved_base_url or "https://api.openai.com/v1"

        # Separate embedding client (DeepSeek has no embeddings → keep OpenAI)
        embedding_key = EMBEDDING_API_KEY or resolved_key
        embedding_kwargs: dict[str, Any] = {"api_key": embedding_key}
        if EMBEDDING_BASE_URL:
            embedding_kwargs["base_url"] = EMBEDDING_BASE_URL
        # Only create separate embedding client if base URLs differ
        if EMBEDDING_BASE_URL and EMBEDDING_BASE_URL != resolved_base_url:
            self._embed_client = OpenAI(**embedding_kwargs)
        elif resolved_base_url and "deepseek" in resolved_base_url.lower():
            # DeepSeek has no embeddings — use OpenAI for embeddings
            self._embed_client = OpenAI(api_key=EMBEDDING_API_KEY or OPENAI_API_KEY)
        else:
            self._embed_client = self.client

        # Last reasoning content (CoT) from reasoning models
        self.last_reasoning_content: str | None = None

        # Detect if provider supports thinking parameter (DeepSeek V3.2)
        self.is_deepseek = "deepseek" in self._base_url.lower()
        self.thinking_enabled = LLM_THINKING_ENABLED and self.is_deepseek

        provider = "DeepSeek" if self.is_deepseek else "OpenAI"
        thinking_str = "thinking" if self.thinking_enabled else "no-thinking"
        mode = "reasoning" if self.is_reasoning else "standard"
        logger.info("LLMClient initialized — provider=%s, model=%s, mode=%s, thinking=%s, base_url=%s",
                     provider, self.model, mode, thinking_str, self._base_url)

        # Shared thread pool for hard-timeout API calls
        # Primary pool: enough workers so concurrent background calls don't starve
        self._timeout_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm-primary")
        # Separate fallback pool: NEVER blocked by stuck primary threads
        self._fallback_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm-fallback")

        # ── Fallback LLM client (OpenAI) ──
        self._fallback_client = None
        self._fallback_model = LLM_FALLBACK_MODEL
        fallback_key = LLM_FALLBACK_API_KEY
        if fallback_key and self.is_deepseek:
            import httpx as _httpx
            fb_kwargs: dict[str, Any] = {"api_key": fallback_key, "timeout": _httpx.Timeout(None, connect=10.0)}
            if LLM_FALLBACK_BASE_URL:
                fb_kwargs["base_url"] = LLM_FALLBACK_BASE_URL
            self._fallback_client = OpenAI(**fb_kwargs)
            logger.info("Fallback LLM configured — model=%s", self._fallback_model)

    # Hard wall-clock timeout for API calls.
    # httpx read-timeout resets on every byte so DeepSeek keepalives bypass it.
    # This wrapper gives an absolute ceiling regardless of network activity.
    # 400s primary: DeepSeek thinking mode can produce long CoT chains (100-200s+).
    # Previous 220s was cutting off heavy reasoning runs.
    _API_CALL_TIMEOUT = 400  # seconds — hard wall-clock limit for primary
    _FALLBACK_TIMEOUT = 120  # seconds — fallback ceiling (GPT is faster but large prompts need time)

    def _api_call_with_timeout(self, kwargs: dict[str, Any], label: str = "LLM"):
        """Run client.chat.completions.create with a hard wall-clock timeout.
        If primary fails and a fallback client exists, retry on OpenAI.
        Uses separate thread pools so primary timeouts cannot block fallback."""
        # ── Try primary (DeepSeek) ──
        try:
            future = self._timeout_pool.submit(self.client.chat.completions.create, **kwargs)
        except RuntimeError:
            # Pool shut down (reload/shutdown in progress)
            raise RuntimeError(f"{label}: executor shutdown — reload in progress")
        try:
            result = future.result(timeout=self._API_CALL_TIMEOUT)
            if result.choices:
                return result
            logger.warning("[%s] Primary returned empty choices — trying fallback", label)
        except FuturesTimeout:
            future.cancel()
            logger.error("[%s] Primary hard timeout (%ds)", label, self._API_CALL_TIMEOUT)
        except RuntimeError:
            raise  # Re-raise shutdown errors immediately
        except Exception as exc:
            logger.error("[%s] Primary API error: %s", label, exc)

        # ── Fallback to OpenAI (separate pool, shorter timeout) ──
        if not self._fallback_client:
            raise TimeoutError(f"{label}: Primary failed and no fallback configured")

        logger.info("[%s] Falling back to OpenAI (%s)", label, self._fallback_model)
        fb_kwargs = dict(kwargs)
        fb_kwargs["model"] = self._fallback_model
        # Remove DeepSeek-specific params that OpenAI rejects
        fb_kwargs.pop("extra_body", None)
        # OpenAI uses temperature normally
        if "temperature" not in fb_kwargs:
            fb_kwargs["temperature"] = 0.7

        try:
            fb_future = self._fallback_pool.submit(self._fallback_client.chat.completions.create, **fb_kwargs)
        except RuntimeError:
            raise RuntimeError(f"{label}: fallback executor shutdown — reload in progress")
        try:
            return fb_future.result(timeout=self._FALLBACK_TIMEOUT)
        except FuturesTimeout:
            fb_future.cancel()
            logger.error("[%s] Fallback also timed out (%ds)", label, self._FALLBACK_TIMEOUT)
            raise TimeoutError(f"{label}: Both primary and fallback failed")
        except Exception as exc:
            logger.error("[%s] Fallback API error: %s", label, exc)
            raise

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
    ) -> str:
        """Single LLM call → raw text response.

        For reasoning models (deepseek-reasoner, o1):
        - temperature/top_p are ignored (model controls these)
        - reasoning_content (CoT) is captured in self.last_reasoning_content

        Args:
            thinking: Override thinking mode per-call. None=use global setting,
                      False=disable thinking for this call (saves completion tokens).
        """
        effective_temp = temperature if temperature is not None else OPENAI_TEMPERATURE
        effective_max = max_tokens or OPENAI_MAX_TOKENS

        # Budget guard — prevent 400 errors from oversized prompts
        total_chars = len(system_prompt) + len(user_prompt)
        est_prompt_tokens = _estimate_tokens(total_chars)
        max_allowed_prompt = LLM_MAX_CONTEXT_TOKENS - effective_max - 500  # 500 token safety margin
        if est_prompt_tokens > max_allowed_prompt:
            budget_chars = max_allowed_prompt * 3  # reverse estimate: tokens → chars
            system_chars = len(system_prompt)
            user_budget = max(budget_chars - system_chars, 10000)
            if len(user_prompt) > user_budget:
                logger.warning(
                    "[LLM.call] PROMPT BUDGET EXCEEDED: ~%d tokens (limit %d). Truncating user prompt %d → %d chars",
                    est_prompt_tokens, max_allowed_prompt, len(user_prompt), user_budget,
                )
                user_prompt = user_prompt[:user_budget] + "\n\n[... context truncated to fit model context window ...]"

        logger.info("[LLM.call] Sending request — model=%s, system_len=%d, user_len=%d, temp=%.2f, max_tokens=%d",
                     self.model, len(system_prompt), len(user_prompt),
                     effective_temp, effective_max)

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": effective_max,
        }

        # DeepSeek thinking mode — allow per-call override
        # reasoning_effort="high" is the new V4-Pro parameter for effort control
        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
        elif self.is_deepseek:
            # Explicitly disable thinking to save completion tokens
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        # Reasoning models don't support temperature/top_p.
        # DeepSeek thinking mode also suppresses temperature (no effect per docs).
        if not self.is_reasoning and not (use_thinking and self.is_deepseek):
            kwargs["temperature"] = effective_temp

        t0 = time.perf_counter()
        response = self._api_call_with_timeout(kwargs, label="LLM.call")
        elapsed = time.perf_counter() - t0

        if not response.choices:
            logger.error("[LLM.call] API returned empty choices — elapsed %.2fs", elapsed)
            return ""

        message = response.choices[0].message
        content = message.content or ""
        finish_reason = response.choices[0].finish_reason

        # Capture reasoning content (CoT) if available
        reasoning = getattr(message, "reasoning_content", None)
        self.last_reasoning_content = reasoning
        if reasoning:
            logger.info("[LLM.call] Reasoning (CoT): %d chars captured", len(reasoning))

        # DeepSeek thinking models sometimes put everything in reasoning_content
        # and return empty content. Fall back to reasoning in that case.
        if not content and reasoning:
            logger.warning("[LLM.call] Content empty but reasoning has %d chars — using reasoning as response", len(reasoning))
            content = reasoning

        usage = response.usage
        logger.info("[LLM.call] Response received — %d chars, %.2fs elapsed, finish=%s",
                    len(content), elapsed, finish_reason or "unknown")
        if finish_reason == "length":
            logger.warning("[LLM.call] ⚠️ Response was CUT OFF (finish_reason=length, max_tokens=%d)", effective_max)
        if usage:
            logger.info("[LLM.call] Tokens — prompt=%d, completion=%d, total=%d",
                         usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)
            cache_hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
            cache_miss = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
            if cache_hit or cache_miss:
                logger.info("[LLM.call] KV cache — hit=%d tokens, miss=%d tokens (%.0f%% hit rate)",
                             cache_hit, cache_miss,
                             100 * cache_hit / (cache_hit + cache_miss) if (cache_hit + cache_miss) else 0)
        return content

    def call_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
    ) -> Generator[str, None, None]:
        """Streaming LLM call — yields text chunks as they arrive.

        Same parameters as call() but returns a generator of text deltas.
        This allows the caller to process/send chunks before the full
        response is complete (e.g. for SSE streaming to browser).
        """
        effective_temp = temperature if temperature is not None else OPENAI_TEMPERATURE
        effective_max = max_tokens or OPENAI_MAX_TOKENS

        # Budget guard
        total_chars = len(system_prompt) + len(user_prompt)
        est_prompt_tokens = _estimate_tokens(total_chars)
        max_allowed_prompt = LLM_MAX_CONTEXT_TOKENS - effective_max - 500
        if est_prompt_tokens > max_allowed_prompt:
            budget_chars = max_allowed_prompt * 3
            system_chars = len(system_prompt)
            user_budget = max(budget_chars - system_chars, 10000)
            if len(user_prompt) > user_budget:
                logger.warning(
                    "[LLM.call_stream] PROMPT BUDGET EXCEEDED: ~%d tokens (limit %d). Truncating user prompt %d → %d chars",
                    est_prompt_tokens, max_allowed_prompt, len(user_prompt), user_budget,
                )
                user_prompt = user_prompt[:user_budget] + "\n\n[... context truncated to fit model context window ...]"

        logger.info("[LLM.call_stream] Sending streaming request — model=%s, system_len=%d, user_len=%d",
                     self.model, len(system_prompt), len(user_prompt))

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": effective_max,
            "stream": True,
        }

        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
        elif self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        if not self.is_reasoning and not (use_thinking and self.is_deepseek):
            kwargs["temperature"] = effective_temp

        t0 = time.perf_counter()
        try:
            stream = self.client.chat.completions.create(**kwargs)
            total_content = 0
            got_first = False
            last_finish_reason = None
            for chunk in stream:
                if chunk.choices:
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        last_finish_reason = choice.finish_reason
                    delta = choice.delta
                    if delta and delta.content:
                        got_first = True
                        total_content += len(delta.content)
                        yield delta.content
            elapsed = time.perf_counter() - t0
            if got_first:
                logger.info("[LLM.call_stream] Stream complete — %d chars, %.2fs elapsed, finish=%s",
                            total_content, elapsed, last_finish_reason or "unknown")
                if last_finish_reason == "length":
                    logger.warning("[LLM.call_stream] ⚠️ Response was CUT OFF (finish_reason=length, max_tokens=%d)", effective_max)
                return
            logger.warning("[LLM.call_stream] Primary returned 0 content chars (%.1fs)", elapsed)
        except Exception as exc:
            logger.warning("[LLM.call_stream] Primary stream error: %s", exc)

        # ── Fallback to OpenAI ──
        if self._fallback_client:
            logger.info("[LLM.call_stream] Falling back to OpenAI (%s)", self._fallback_model)
            fb_kwargs = dict(kwargs)
            fb_kwargs["model"] = self._fallback_model
            fb_kwargs.pop("extra_body", None)
            if "temperature" not in fb_kwargs:
                fb_kwargs["temperature"] = effective_temp
            try:
                fb_stream = self._fallback_client.chat.completions.create(**fb_kwargs)
                total_fb = 0
                for chunk in fb_stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            total_fb += len(delta.content)
                            yield delta.content
                elapsed = time.perf_counter() - t0
                logger.info("[LLM.call_stream] Fallback stream complete — %d chars, %.2fs total", total_fb, elapsed)
            except Exception as fb_exc:
                logger.error("[LLM.call_stream] Fallback also failed: %s", fb_exc)

    def call_stream_multi(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 8000,
        thinking: bool | None = None,
    ) -> Generator[str, None, None]:
        """Streaming multi-turn LLM call — yields text chunks as they arrive."""
        clean_messages = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": clean_messages,
            "max_completion_tokens": max_tokens,
            "stream": True,
        }

        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
        elif self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        if not self.is_reasoning and not (use_thinking and self.is_deepseek):
            kwargs["temperature"] = temperature

        logger.info("[LLM.call_stream_multi] Sending streaming request — model=%s, %d messages, max_tokens=%d",
                     self.model, len(clean_messages), max_tokens)

        t0 = time.perf_counter()
        try:
            stream = self.client.chat.completions.create(**kwargs)
            total_content = 0
            got_first = False
            last_finish_reason = None
            for chunk in stream:
                if chunk.choices:
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        last_finish_reason = choice.finish_reason
                    delta = choice.delta
                    if delta and delta.content:
                        got_first = True
                        total_content += len(delta.content)
                        yield delta.content
            elapsed = time.perf_counter() - t0
            if got_first:
                logger.info("[LLM.call_stream_multi] Stream complete — %d chars, %.2fs elapsed, finish=%s",
                            total_content, elapsed, last_finish_reason or "unknown")
                if last_finish_reason == "length":
                    logger.warning("[LLM.call_stream_multi] ⚠️ Response was CUT OFF (finish_reason=length, max_tokens=%d)", max_tokens)
                return
            logger.warning("[LLM.call_stream_multi] Primary returned 0 content chars (%.1fs)", elapsed)
        except Exception as exc:
            logger.warning("[LLM.call_stream_multi] Primary stream error: %s", exc)

        # ── Fallback to OpenAI ──
        if self._fallback_client:
            logger.info("[LLM.call_stream_multi] Falling back to OpenAI (%s)", self._fallback_model)
            fb_kwargs = dict(kwargs)
            fb_kwargs["model"] = self._fallback_model
            fb_kwargs.pop("extra_body", None)
            if "temperature" not in fb_kwargs:
                fb_kwargs["temperature"] = temperature
            try:
                fb_stream = self._fallback_client.chat.completions.create(**fb_kwargs)
                total_fb = 0
                for chunk in fb_stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            total_fb += len(delta.content)
                            yield delta.content
                elapsed = time.perf_counter() - t0
                logger.info("[LLM.call_stream_multi] Fallback stream complete — %d chars, %.2fs total", total_fb, elapsed)
            except Exception as fb_exc:
                logger.error("[LLM.call_stream_multi] Fallback also failed: %s", fb_exc)

    def call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
    ) -> dict[str, Any]:
        """LLM call expecting JSON response. Returns parsed dict.

        For reasoning models: JSON output is supported but temperature is ignored.
        For models that don't support response_format, falls back to prompt-based JSON.

        Args:
            thinking: Override thinking mode per-call. None=use global setting,
                      False=disable thinking for this call (saves completion tokens).
        """
        logger.info("[LLM.call_json] Sending JSON request — model=%s, system_len=%d, user_len=%d",
                     self.model, len(system_prompt), len(user_prompt))

        effective_max = max_tokens or OPENAI_MAX_TOKENS

        # Budget guard — prevent 400 errors from oversized prompts
        total_chars = len(system_prompt) + len(user_prompt)
        est_prompt_tokens = _estimate_tokens(total_chars)
        max_allowed_prompt = LLM_MAX_CONTEXT_TOKENS - effective_max - 500
        if est_prompt_tokens > max_allowed_prompt:
            budget_chars = max_allowed_prompt * 3
            system_chars = len(system_prompt)
            user_budget = max(budget_chars - system_chars, 10000)
            if len(user_prompt) > user_budget:
                logger.warning(
                    "[LLM.call_json] PROMPT BUDGET EXCEEDED: ~%d tokens (limit %d). Truncating user prompt %d → %d chars",
                    est_prompt_tokens, max_allowed_prompt, len(user_prompt), user_budget,
                )
                user_prompt = user_prompt[:user_budget] + "\n\n[... context truncated to fit model context window ...]"

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": effective_max,
        }

        # response_format supported by OpenAI and DeepSeek
        kwargs["response_format"] = {"type": "json_object"}

        # DeepSeek thinking mode — allow per-call override
        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
        elif self.is_deepseek:
            # Explicitly disable thinking to save completion tokens
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        # Reasoning models and DeepSeek thinking mode don't support temperature
        if not self.is_reasoning and not (use_thinking and self.is_deepseek):
            kwargs["temperature"] = temperature if temperature is not None else OPENAI_TEMPERATURE

        t0 = time.perf_counter()
        _max_retries = 2
        response = None
        for _attempt in range(_max_retries):
            try:
                response = self._api_call_with_timeout(kwargs, label="LLM.call_json")
                if response.choices:
                    break
                logger.warning("[LLM.call_json] Empty choices on attempt %d/%d — retrying", _attempt + 1, _max_retries)
            except RuntimeError as rt_exc:
                # Executor shutdown — don't retry, propagate immediately
                logger.warning("[LLM.call_json] Executor shutdown: %s", rt_exc)
                raise
            except Exception as api_exc:
                logger.warning("[LLM.call_json] API error on attempt %d/%d: %s", _attempt + 1, _max_retries, api_exc)
                if _attempt == _max_retries - 1:
                    raise
        elapsed = time.perf_counter() - t0

        if not response or not response.choices:
            logger.error("[LLM.call_json] API returned empty choices after %d attempts — elapsed %.2fs", _max_retries, elapsed)
            return {}

        message = response.choices[0].message
        raw = message.content or "{}"

        # Capture reasoning content (CoT) if available
        reasoning = getattr(message, "reasoning_content", None)
        self.last_reasoning_content = reasoning
        if reasoning:
            logger.info("[LLM.call_json] Reasoning (CoT): %d chars", len(reasoning))

        usage = response.usage
        logger.info("[LLM.call_json] Response received — %d chars, %.2fs elapsed", len(raw), elapsed)
        if usage:
            logger.info("[LLM.call_json] Tokens — prompt=%d, completion=%d, total=%d",
                         usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)
            cache_hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
            cache_miss = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
            if cache_hit or cache_miss:
                logger.info("[LLM.call_json] KV cache — hit=%d tokens, miss=%d tokens (%.0f%% hit rate)",
                             cache_hit, cache_miss,
                             100 * cache_hit / (cache_hit + cache_miss) if (cache_hit + cache_miss) else 0)
        raw = raw.strip()

        # Strip markdown code fences if the model wraps them
        if raw.startswith("```"):
            logger.debug("[LLM.call_json] Stripping leading markdown code fence")
            raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            logger.debug("[LLM.call_json] Stripping trailing markdown code fence")
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            # First attempt: strip control characters that LLMs sometimes embed
            # (e.g. \x00-\x1f except \n \r \t which are valid in JSON strings when escaped)
            if "control character" in str(e).lower():
                import re as _re_ctrl
                sanitized = _re_ctrl.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
                try:
                    parsed = json.loads(sanitized)
                    logger.info("[LLM.call_json] JSON parse succeeded after stripping control chars")
                    return parsed
                except json.JSONDecodeError:
                    pass  # Fall through to standard repair

            logger.warning("[LLM.call_json] JSON parse failed: %s — attempting repair", e)
            repaired = raw

            import re as _re

            # If error is mid-response (not near the end), try truncating at the error position
            # and closing the structure from there
            error_pos = e.pos if hasattr(e, 'pos') else None
            if error_pos and error_pos < len(raw) - 50:
                # Find the last valid comma or closing bracket before error position
                candidate = raw[:error_pos]
                # Walk back to the last clean boundary (end of a value)
                for cutoff in [candidate.rfind('},'), candidate.rfind('],'),
                               candidate.rfind('",'), candidate.rfind('"')]:
                    if cutoff > 0:
                        repaired = raw[:cutoff + 1]
                        break
                logger.info("[LLM.call_json] Truncated at pos %d (error was at %d)", len(repaired), error_pos)

            # Strip trailing incomplete key (e.g. '\n  "systematic_iss' without closing quote/colon)
            repaired = _re.sub(r',\s*"[^"]*$', '', repaired)
            # Strip trailing incomplete value after a colon
            repaired = _re.sub(r':\s*$', ': null', repaired)

            # Strip trailing comma
            repaired = repaired.rstrip()
            if repaired.endswith(','):
                repaired = repaired[:-1]

            # Close any trailing open string
            if repaired.count('"') % 2 != 0:
                repaired += '"'

            # Close open brackets/braces
            open_brackets = repaired.count('[') - repaired.count(']')
            open_braces = repaired.count('{') - repaired.count('}')
            repaired += ']' * max(0, open_brackets)
            repaired += '}' * max(0, open_braces)

            try:
                parsed = json.loads(repaired)
                logger.info("[LLM.call_json] JSON repair succeeded")
            except json.JSONDecodeError:
                logger.error("[LLM.call_json] JSON repair also failed — returning empty dict")
                parsed = {}
        logger.info("[LLM.call_json] Parsed JSON — %d keys: %s", len(parsed), list(parsed.keys()))
        return parsed

    def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Priority:
        1. LOCAL_EMBEDDING_ENABLED=true → always use fastembed (offline)
        2. OpenAI circuit closed → use OpenAI
        3. OpenAI circuit open (quota/rate) → fallback to fastembed if available
        """
        # ── Local-first mode ──
        if LOCAL_EMBEDDING_ENABLED:
            return _local_embed(text)

        # ── Circuit breaker check ──
        circuit_err = _check_embed_circuit()
        if circuit_err:
            # Try local fallback before failing
            try:
                logger.debug("[LLM.embed] Circuit open — falling back to local fastembed")
                return _local_embed(text)
            except Exception:
                raise RuntimeError(circuit_err)

        truncated_len = min(len(text), 8191)
        logger.info("[LLM.embed] Generating embedding — text_len=%d (truncated=%d), model=%s",
                     len(text), truncated_len, OPENAI_EMBEDDING_MODEL)
        t0 = time.perf_counter()
        try:
            response = self._embed_client.embeddings.create(
                model=OPENAI_EMBEDDING_MODEL,
                input=text[:8191],
            )
        except Exception as exc:
            exc_str = str(exc)
            if "insufficient_quota" in exc_str or "exceeded your current quota" in exc_str:
                _trip_embed_circuit(exc_str, quota=True)
                # Immediate local fallback after tripping
                try:
                    logger.info("[LLM.embed] Quota exceeded — switching to local fastembed fallback")
                    return _local_embed(text)
                except Exception:
                    pass
            elif "429" in exc_str or "rate_limit" in exc_str.lower():
                _trip_embed_circuit(exc_str, quota=False)
                try:
                    logger.debug("[LLM.embed] Rate limit — falling back to local fastembed")
                    return _local_embed(text)
                except Exception:
                    pass
            raise
        elapsed = time.perf_counter() - t0
        embedding = response.data[0].embedding
        logger.info("[LLM.embed] Embedding generated — dim=%d, %.2fs elapsed", len(embedding), elapsed)
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Priority same as embed(): local-first when enabled, OpenAI otherwise,
        auto-fallback to local on quota/rate errors.
        """
        if not texts:
            return []

        # ── Local-first mode ──
        if LOCAL_EMBEDDING_ENABLED:
            return _local_embed_batch(texts)

        # ── Circuit breaker check ──
        circuit_err = _check_embed_circuit()
        if circuit_err:
            try:
                logger.debug("[LLM.embed_batch] Circuit open — falling back to local fastembed")
                return _local_embed_batch(texts)
            except Exception:
                raise RuntimeError(circuit_err)

        truncated = [t[:8191] for t in texts]
        logger.info("[LLM.embed_batch] Generating %d embeddings, model=%s",
                     len(truncated), OPENAI_EMBEDDING_MODEL)
        t0 = time.perf_counter()
        all_embeddings = []
        try:
            for i in range(0, len(truncated), 2048):
                chunk = truncated[i:i + 2048]
                response = self._embed_client.embeddings.create(
                    model=OPENAI_EMBEDDING_MODEL,
                    input=chunk,
                )
                sorted_data = sorted(response.data, key=lambda x: x.index)
                all_embeddings.extend([d.embedding for d in sorted_data])
        except Exception as exc:
            exc_str = str(exc)
            if "insufficient_quota" in exc_str or "exceeded your current quota" in exc_str:
                _trip_embed_circuit(exc_str, quota=True)
                try:
                    logger.info("[LLM.embed_batch] Quota exceeded — switching to local fastembed fallback")
                    return _local_embed_batch(texts)
                except Exception:
                    pass
            elif "429" in exc_str or "rate_limit" in exc_str.lower():
                _trip_embed_circuit(exc_str, quota=False)
                try:
                    logger.debug("[LLM.embed_batch] Rate limit — falling back to local fastembed")
                    return _local_embed_batch(texts)
                except Exception:
                    pass
            raise
        elapsed = time.perf_counter() - t0
        logger.info("[LLM.embed_batch] %d embeddings generated — %.2fs elapsed",
                     len(all_embeddings), elapsed)
        return all_embeddings
