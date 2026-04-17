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
)

logger = logging.getLogger(__name__)


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

        # Timeout: 60s prevents hanging on DeepSeek stalls
        # Uses httpx.Timeout with explicit per-phase limits
        import httpx
        client_kwargs["timeout"] = httpx.Timeout(60.0, connect=10.0)

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

        # Shared thread pool for hard-timeout API calls (max 4 concurrent)
        self._timeout_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm-timeout")

    # Hard wall-clock timeout for API calls.
    # httpx read-timeout resets on every byte so DeepSeek keepalives bypass it.
    # This wrapper gives an absolute ceiling regardless of network activity.
    _API_CALL_TIMEOUT = 90  # seconds — hard wall-clock limit

    def _api_call_with_timeout(self, kwargs: dict[str, Any], label: str = "LLM"):
        """Run client.chat.completions.create with a hard wall-clock timeout."""
        future = self._timeout_pool.submit(self.client.chat.completions.create, **kwargs)
        try:
            return future.result(timeout=self._API_CALL_TIMEOUT)
        except FuturesTimeout:
            future.cancel()
            logger.error("[%s] Hard timeout (%ds) — DeepSeek did not respond in time", label, self._API_CALL_TIMEOUT)
            raise TimeoutError(f"{label}: API call exceeded {self._API_CALL_TIMEOUT}s wall-clock limit")

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

        # Reasoning models don't support temperature/top_p
        if not self.is_reasoning:
            kwargs["temperature"] = effective_temp

        # DeepSeek thinking mode — allow per-call override
        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        elif self.is_deepseek:
            # Explicitly disable thinking to save completion tokens
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        t0 = time.perf_counter()
        response = self._api_call_with_timeout(kwargs, label="LLM.call")
        elapsed = time.perf_counter() - t0

        if not response.choices:
            logger.error("[LLM.call] API returned empty choices — elapsed %.2fs", elapsed)
            return ""

        message = response.choices[0].message
        content = message.content or ""

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
        logger.info("[LLM.call] Response received — %d chars, %.2fs elapsed", len(content), elapsed)
        if usage:
            logger.info("[LLM.call] Tokens — prompt=%d, completion=%d, total=%d",
                         usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)
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

        if not self.is_reasoning:
            kwargs["temperature"] = effective_temp

        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        elif self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        t0 = time.perf_counter()
        stream = self.client.chat.completions.create(**kwargs)

        total_content = 0
        for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    total_content += len(delta.content)
                    yield delta.content

        elapsed = time.perf_counter() - t0
        logger.info("[LLM.call_stream] Stream complete — %d chars, %.2fs elapsed", total_content, elapsed)

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
        if not self.is_reasoning:
            kwargs["temperature"] = temperature

        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        elif self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        logger.info("[LLM.call_stream_multi] Sending streaming request — model=%s, %d messages",
                     self.model, len(clean_messages))

        t0 = time.perf_counter()
        stream = self.client.chat.completions.create(**kwargs)

        total_content = 0
        for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    total_content += len(delta.content)
                    yield delta.content

        elapsed = time.perf_counter() - t0
        logger.info("[LLM.call_stream_multi] Stream complete — %d chars, %.2fs elapsed", total_content, elapsed)

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

        # Reasoning models: no temperature, but JSON mode is supported
        if not self.is_reasoning:
            kwargs["temperature"] = temperature if temperature is not None else OPENAI_TEMPERATURE

        # response_format supported by OpenAI and DeepSeek
        kwargs["response_format"] = {"type": "json_object"}

        # DeepSeek thinking mode — allow per-call override
        use_thinking = thinking if thinking is not None else self.thinking_enabled
        if use_thinking and self.is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        elif self.is_deepseek:
            # Explicitly disable thinking to save completion tokens
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        t0 = time.perf_counter()
        _max_retries = 2
        response = None
        for _attempt in range(_max_retries):
            try:
                response = self._api_call_with_timeout(kwargs, label="LLM.call_json")
                if response.choices:
                    break
                logger.warning("[LLM.call_json] Empty choices on attempt %d/%d — retrying", _attempt + 1, _max_retries)
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

        Uses separate embedding client (OpenAI) when main provider
        doesn't support embeddings (e.g., DeepSeek).
        """
        truncated_len = min(len(text), 8191)
        logger.info("[LLM.embed] Generating embedding — text_len=%d (truncated=%d), model=%s",
                     len(text), truncated_len, OPENAI_EMBEDDING_MODEL)
        t0 = time.perf_counter()
        response = self._embed_client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=text[:8191],  # respect token limit
        )
        elapsed = time.perf_counter() - t0
        embedding = response.data[0].embedding
        logger.info("[LLM.embed] Embedding generated — dim=%d, %.2fs elapsed", len(embedding), elapsed)
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in a single API call.

        Uses separate embedding client when main provider lacks embeddings.
        OpenAI supports up to 2048 inputs per batch request."""
        if not texts:
            return []
        truncated = [t[:8191] for t in texts]
        logger.info("[LLM.embed_batch] Generating %d embeddings, model=%s",
                     len(truncated), OPENAI_EMBEDDING_MODEL)
        t0 = time.perf_counter()
        # Process in chunks of 2048 (OpenAI batch limit)
        all_embeddings = []
        for i in range(0, len(truncated), 2048):
            chunk = truncated[i:i + 2048]
            response = self._embed_client.embeddings.create(
                model=OPENAI_EMBEDDING_MODEL,
                input=chunk,
            )
            # Sort by index to preserve order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            all_embeddings.extend([d.embedding for d in sorted_data])
        elapsed = time.perf_counter() - t0
        logger.info("[LLM.embed_batch] %d embeddings generated — %.2fs elapsed",
                     len(all_embeddings), elapsed)
        return all_embeddings
