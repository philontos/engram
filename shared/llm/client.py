import asyncio
import json
import os
import random
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator, Optional

import httpx


# Transient errors worth retrying. ReadTimeout covers slow LLM responses
# (DeepSeek can take >60s); RemoteProtocolError covers chunked-stream drops;
# the rest cover flaky DNS / connection / pool issues.
_RETRY_EXCEPTIONS = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectError,
    httpx.PoolTimeout,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
)
_RETRY_STATUSES = {429, 502, 503, 504}


def _backoff_seconds(attempt: int) -> float:
    """Backoff schedule: ~2s, ~6s. Jittered. Total ~8s of wait across two
    retries — covers DeepSeek's typical 5-10s flake windows without making
    failure reporting feel hung."""
    return 2.0 * (3 ** attempt) + random.uniform(0, 0.5)


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    json_body: dict,
    max_attempts: int = 3,
) -> httpx.Response:
    """POST with up to `max_attempts` tries. Retries on transient httpx errors
    and on 429 / 5xx. Non-retryable 4xx and successful responses return
    immediately."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = await client.post(url, headers=headers, json=json_body)
            if resp.status_code in _RETRY_STATUSES and attempt < max_attempts - 1:
                await asyncio.sleep(_backoff_seconds(attempt))
                continue
            return resp
        except _RETRY_EXCEPTIONS as exc:
            last_exc = exc
            if attempt >= max_attempts - 1:
                raise
            await asyncio.sleep(_backoff_seconds(attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("retry loop exited without response")  # unreachable


# --------------------------------------------------------------------------
# LLM 调用观测：每次调用记录 stage/模型/prompt 体积/tokens/duration 等
# --------------------------------------------------------------------------

_llm_trace_sink: ContextVar[Optional[list]] = ContextVar("llm_trace_sink", default=None)


@contextmanager
def capture_llm_calls(sink: list):
    """在 with 块内，所有 chat_json / chat_text_stream 调用自动记录到 sink。

    用法:
        calls = []
        with capture_llm_calls(calls):
            await run_pipeline(...)
        # calls 里每条是 {stage, model, prompt_chars, prompt_tokens, completion_tokens,
        #                 total_tokens, duration_ms, context, status}
    """
    token = _llm_trace_sink.set(sink)
    try:
        yield sink
    finally:
        _llm_trace_sink.reset(token)


def _record_llm_call(record: dict) -> None:
    sink = _llm_trace_sink.get()
    if sink is not None:
        sink.append(record)


LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS") or "60")


class StructuredLLMError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Provider config — universal OpenAI-compatible interface.
#
# Engram talks to any LLM that exposes an OpenAI-style /chat/completions
# endpoint. To configure, set three variables:
#
#     LLM_BASE_URL   e.g. https://api.openai.com/v1
#     LLM_API_KEY    your provider key
#     LLM_MODEL      e.g. gpt-4.1, claude-sonnet-4-5, gemini-2.5-pro, ...
#
# Or pick a built-in preset via LLM_PROVIDER (no need to remember base_url):
#
#     openai | anthropic | gemini | grok | openrouter |
#     deepseek | moonshot | qwen | glm | minimax | ark | ollama
#
# Anthropic and Gemini are reached via their OpenAI-compatible endpoints —
# the client itself stays a single OpenAI-shape implementation, no per-vendor
# adapters.
# --------------------------------------------------------------------------

# (base_url, default_model_or_None)
_PRESETS: dict[str, tuple[str, str | None]] = {
    "openai":     ("https://api.openai.com/v1",                    "gpt-4.1-mini"),
    "anthropic":  ("https://api.anthropic.com/v1",                 "claude-sonnet-4-5"),
    "gemini":     ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "grok":       ("https://api.x.ai/v1",                          "grok-4"),
    "openrouter": ("https://openrouter.ai/api/v1",                 None),
    "deepseek":   ("https://api.deepseek.com",                     "deepseek-chat"),
    "moonshot":   ("https://api.moonshot.cn/v1",                   "kimi-k2.5"),
    "qwen":       ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "glm":        ("https://open.bigmodel.cn/api/paas/v4",         "glm-4.6"),
    "minimax":    ("https://api.minimax.io/v1",                    "MiniMax-M2.5"),
    "ark":        ("https://ark.cn-beijing.volces.com/api/v3",     None),
    "ollama":     ("http://localhost:11434/v1",                    "llama3.1"),
}

# Provider capability + verification table.
#   json_object — supports response_format={"type":"json_object"}.
#                 Providers not listed default to True (auto-fallback on 400).
#   tested      — has been verified end-to-end by the maintainer.
#                 False does NOT mean broken — it means "compatible by spec
#                 but not yet exercised in production". Surface this honestly
#                 in the README compatibility matrix.
_PROVIDER_CAPS: dict[str, dict[str, bool]] = {
    "openai":     {"json_object": True,  "tested": False},
    "anthropic":  {"json_object": False, "tested": False},
    "gemini":     {"json_object": True,  "tested": False},
    "grok":       {"json_object": True,  "tested": False},
    "openrouter": {"json_object": True,  "tested": False},
    "deepseek":   {"json_object": True,  "tested": True},
    "moonshot":   {"json_object": True,  "tested": False},
    "qwen":       {"json_object": True,  "tested": False},
    "glm":        {"json_object": True,  "tested": False},
    "minimax":    {"json_object": True,  "tested": False},
    "ark":        {"json_object": True,  "tested": True},
    "ollama":     {"json_object": True,  "tested": False},
}


def _provider_supports_json_object(provider: str) -> bool:
    """Best-effort capability check; unknown providers assumed to support it
    (we'll detect 400 and retry without)."""
    return _PROVIDER_CAPS.get(provider, {}).get("json_object", True)


# Model-level capability: which models reject the `temperature` parameter
# outright and return 400. Detection is substring-based on the lower-cased
# model id (after stripping any routing prefix like `cc/`).
#
# Why pre-filter instead of relying on the 400 + strip-and-retry fallback:
# some OpenAI-compatible proxies (e.g. 9router) treat the upstream 400 as a
# "this account can't serve this model" signal and lock the account out for
# 30s. The retry then hits a locked account and the whole pipeline collapses.
# Pre-filtering avoids triggering the lock at all.
#
# Sources (verified, not guessed):
#   Anthropic Opus 4.7 — "Starting with Claude Opus 4.7, setting temperature,
#     top_p, or top_k to any non-default value will return a 400 error."
#     https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
#     Note: Claude 4.0–4.6 (incl. sonnet-4-6, haiku-4-5) still ACCEPT temperature.
#   OpenAI o-series — Azure/OpenAI docs: reasoning models do not support
#     temperature/top_p; API returns "Unsupported parameter" 400.
#     https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/reasoning
#   DeepSeek-reasoner — silently ignores, no error. No need to filter.
#   Qwen3 thinking / QwQ — accepts temperature (Qwen3 recommends 0.6).
_NO_TEMPERATURE_MODELS: tuple[str, ...] = (
    # Anthropic — only Opus 4.7 (per official docs)
    "claude-opus-4-7",
    # OpenAI reasoning series: o1*, o3*, o4-mini
    "o1-",      # o1-mini, o1-preview, o1-pro
    "o3-",      # o3-mini, o3-pro
    "o4-mini",
)


def _supports_temperature(model: str) -> bool:
    """Return False for models known to reject `temperature`. Unknown models
    default to True; `_strip_unsupported_params_if_rejected` covers misses
    when the upstream proxy doesn't penalise the 400."""
    m = (model or "").lower()
    if "/" in m:
        m = m.rsplit("/", 1)[-1]
    if m in ("o1", "o3"):
        return False
    return not any(s in m for s in _NO_TEMPERATURE_MODELS)


_JSON_ONLY_HINT = (
    "\n\nIMPORTANT: Respond with a single valid JSON object only. "
    "No markdown fences, no prose, no explanation — JSON only."
)


def resolve_structured_llm_config() -> dict[str, str]:
    """Resolve LLM config from LLM_BASE_URL / LLM_API_KEY / LLM_MODEL,
    optionally seeded by an LLM_PROVIDER preset."""
    base_url = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("LLM_API_KEY") or "").strip()
    model = (os.getenv("LLM_MODEL") or "").strip()

    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider and provider in _PRESETS:
        preset_url, preset_model = _PRESETS[provider]
        if not base_url:
            base_url = preset_url
        if not model and preset_model:
            model = preset_model

    return {
        "provider": provider or "custom",
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def is_structured_llm_configured() -> bool:
    config = resolve_structured_llm_config()
    return bool(config["api_key"] and config["base_url"] and config["model"])


def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise StructuredLLMError("Structured extraction model returned empty content.")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise StructuredLLMError("Structured extraction model did not return valid JSON.")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise StructuredLLMError("Structured extraction model returned malformed JSON.") from exc


def _looks_like_json_format_rejection(status_code: int, body: str) -> bool:
    """Detect provider 400s where the cause is the response_format field.

    Anthropic's OpenAI-compat layer (and a few others) rejects or ignores
    response_format. We want to retry without it instead of failing.
    """
    if status_code != 400:
        return False
    needles = ("response_format", "json_object", "unsupported", "not supported")
    low = (body or "").lower()
    return any(n in low for n in needles)


def _looks_like_temperature_rejection(status_code: int, body: str) -> bool:
    """Detect provider 400s where the cause is the `temperature` parameter.

    Anthropic's newer extended-thinking models (e.g. claude-opus-4-7) deprecated
    temperature; passing it through an OpenAI-compat proxy yields a 400 like
    `temperature is deprecated for this model`. Retry without it.
    """
    if status_code != 400:
        return False
    low = (body or "").lower()
    if "temperature" not in low:
        return False
    # Prefix `deprecat` matches both `deprecated` and the truncated `deprecate`
    # form some proxies (e.g. 9router) emit when they wrap upstream errors.
    return any(n in low for n in ("deprecat", "unsupported", "not supported", "not allowed"))


def _strip_unsupported_params_if_rejected(payload: dict, status_code: int, body: str) -> bool:
    """Remove provider-rejected params from `payload` in-place.

    Returns True if the payload was modified — caller should retry once with
    the stripped payload. Currently handles `response_format` and `temperature`.
    """
    if status_code != 400:
        return False
    changed = False
    if "response_format" in payload and _looks_like_json_format_rejection(status_code, body):
        payload.pop("response_format", None)
        changed = True
    if "temperature" in payload and _looks_like_temperature_rejection(status_code, body):
        payload.pop("temperature", None)
        changed = True
    return changed


async def chat_json(
    *, system_prompt: str, user_prompt: str,
    stage: str = "", context: dict | None = None,
) -> dict[str, Any]:
    """Get a JSON object back from the LLM, robust across providers.

    Strategy (per provider capability):
      1. Providers known to support json_object → send response_format upfront.
      2. Providers known not to support it (Anthropic) → skip response_format,
         rely on prompt-only JSON discipline.
      3. Unknown providers → optimistic: try with response_format, auto-retry
         without on a 400 that smells like a response_format rejection.
      4. Always extract JSON via _extract_json_object so markdown fences /
         leading prose don't kill us.
    """
    config = resolve_structured_llm_config()
    if not is_structured_llm_configured():
        raise StructuredLLMError(
            "LLM is not configured. Set LLM_BASE_URL + LLM_API_KEY + LLM_MODEL "
            "(or LLM_PROVIDER=<preset> + LLM_API_KEY [+ LLM_MODEL])."
        )

    use_json_format = _provider_supports_json_object(config["provider"])

    # Anthropic rejects empty user-message content with 400 ("messages: at
    # least one message is required"); OpenAI/Qwen accept it. Normalize at
    # the library layer so callers that put everything in system_prompt
    # (e.g. pipeline slice stages) work across providers.
    user_content = (user_prompt or "").strip() or "Proceed."
    base_messages = [
        {"role": "system", "content": (system_prompt or "") + _JSON_ONLY_HINT},
        {"role": "user", "content": user_content},
    ]
    base_payload: dict[str, Any] = {
        "model": config["model"],
        "messages": base_messages,
        # Explicit false — some OpenAI-compatible proxies (e.g. 9router) default
        # to streaming when unset, which breaks the resp.json() path below.
        "stream": False,
    }
    if _supports_temperature(config["model"]):
        base_payload["temperature"] = 0.1
    if use_json_format:
        base_payload["response_format"] = {"type": "json_object"}

    prompt_chars = len(system_prompt or "") + len(user_prompt or "")
    start = time.monotonic()

    async def _post(payload: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            return await _post_with_retry(
                client,
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json_body=payload,
            )

    try:
        resp = await _post(base_payload)

        # Auto-fallback: strip provider-rejected params (response_format on
        # Anthropic OpenAI-compat, temperature on Claude extended-thinking
        # models) and retry once.
        if _strip_unsupported_params_if_rejected(base_payload, resp.status_code, resp.text):
            resp = await _post(base_payload)

        duration_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code >= 400:
            _record_llm_call({
                "stage": stage or "unknown", "model": config["model"],
                "prompt_chars": prompt_chars,
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                "duration_ms": duration_ms, "context": context or {},
                "status": "http_error", "error": f"status={resp.status_code}",
                # Full I/O capture for trace debug (PR #8): system_prompt only —
                # response is the error body, included separately.
                "system_prompt": system_prompt or "",
                "user_prompt":   user_prompt or "",
                "response":      resp.text[:4000],
            })
            raise StructuredLLMError(
                f"Structured extraction LLM failed: status={resp.status_code} body={resp.text[:400]}"
            )

        data = resp.json()
        usage = data.get("usage") or {}

        # Extract response content for both record AND return value
        try:
            response_content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            _record_llm_call({
                "stage": stage or "unknown", "model": config["model"],
                "prompt_chars": prompt_chars,
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
                "duration_ms": duration_ms, "context": context or {},
                "status": "shape_error", "error": str(exc)[:200],
                "system_prompt": system_prompt or "",
                "user_prompt":   user_prompt or "",
                "response":      str(data)[:4000],
            })
            raise StructuredLLMError("Structured extraction LLM returned an unexpected response shape.") from exc

        _record_llm_call({
            "stage": stage or "unknown", "model": config["model"],
            "prompt_chars": prompt_chars,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "duration_ms": duration_ms, "context": context or {},
            "status": "ok",
            # Full I/O capture for trace debug (PR #8): enables left-outline /
            # right-detail trace inspector to show what the LLM saw + returned.
            "system_prompt": system_prompt or "",
            "user_prompt":   user_prompt or "",
            "response":      response_content,
        })

        return _extract_json_object(response_content)
    except StructuredLLMError:
        raise
    except Exception as exc:
        _record_llm_call({
            "stage": stage or "unknown", "model": config["model"],
            "prompt_chars": prompt_chars,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "context": context or {},
            "status": "exception", "error": str(exc)[:200],
            "system_prompt": system_prompt or "",
            "user_prompt":   user_prompt or "",
            "response":      "",
        })
        raise


async def chat_with_tools(
    *,
    messages: list[dict],
    tools: list[dict],
    stage: str = "",
    context: dict | None = None,
) -> dict:
    """Single non-streaming round with tool calling. Returns {"finish_reason", "message"}.

    message may contain tool_calls (finish_reason="tool_calls") or plain content
    (finish_reason="stop"). Callers append the returned message to their messages
    list, then append role="tool" results before the next round.
    """
    config = resolve_structured_llm_config()
    if not is_structured_llm_configured():
        raise StructuredLLMError("LLM not configured.")

    payload = {
        "model": config["model"],
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        # Explicit false — see chat_json for rationale.
        "stream": False,
    }
    if _supports_temperature(config["model"]):
        payload["temperature"] = 0.3
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            url = f"{config['base_url']}/chat/completions"
            headers = {
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            }
            resp = await _post_with_retry(client, url, headers=headers, json_body=payload)
            # Auto-fallback: strip params the provider rejected (e.g. temperature
            # on Claude extended-thinking models) and retry once.
            if _strip_unsupported_params_if_rejected(payload, resp.status_code, resp.text):
                resp = await _post_with_retry(client, url, headers=headers, json_body=payload)
        duration_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code >= 400:
            _record_llm_call({
                "stage": stage or "unknown", "model": config["model"],
                "prompt_chars": prompt_chars,
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                "duration_ms": duration_ms, "context": context or {},
                "status": "http_error", "error": f"status={resp.status_code}",
            })
            raise StructuredLLMError(
                f"Tool-calling LLM failed: status={resp.status_code} body={resp.text[:400]}"
            )

        data = resp.json()
        usage = data.get("usage") or {}
        _record_llm_call({
            "stage": stage or "unknown", "model": config["model"],
            "prompt_chars": prompt_chars,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "duration_ms": duration_ms, "context": context or {},
            "status": "ok",
        })

        choice = data["choices"][0]
        return {
            "finish_reason": choice.get("finish_reason", "stop"),
            "message": choice["message"],
        }
    except StructuredLLMError:
        raise
    except Exception as exc:
        _record_llm_call({
            "stage": stage or "unknown", "model": config["model"],
            "prompt_chars": prompt_chars,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "context": context or {}, "status": "exception", "error": str(exc)[:200],
        })
        raise


async def chat_with_tools_stream(
    *,
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.3,
    stage: str = "",
    context: dict | None = None,
) -> AsyncIterator[dict]:
    """Streaming variant of chat_with_tools, OpenAI-compatible SSE.

    Yields events:
      {"type":"content_delta",     "delta": str}
      {"type":"tool_call_partial", "index": int, "id": str|None,
                                   "name": str|None, "arguments_delta": str}
      {"type":"done",              "finish_reason": str, "message": dict,
                                   "usage": dict, "duration_ms": int}

    The final "message" follows the OpenAI assistant-message shape and is ready
    to be appended back to the messages list before the next round.
    """
    config = resolve_structured_llm_config()
    if not is_structured_llm_configured():
        raise StructuredLLMError("LLM not configured.")

    payload = {
        "model": config["model"],
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    if _supports_temperature(config["model"]):
        payload["temperature"] = temperature
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    start = time.monotonic()

    content_buf = ""
    tc_acc: dict[int, dict] = {}
    finish_reason = "stop"
    usage: dict = {}

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            url = f"{config['base_url']}/chat/completions"
            headers = {
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            }
            # Two-attempt loop: if the provider rejects a param (e.g. temperature
            # on Claude 4.x), strip it and reopen the stream once.
            for attempt in (1, 2):
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        body_text = body.decode("utf-8", errors="replace")
                        if attempt == 1 and _strip_unsupported_params_if_rejected(
                            payload, resp.status_code, body_text
                        ):
                            continue
                        _record_llm_call({
                            "stage": stage or "unknown", "model": config["model"],
                            "prompt_chars": prompt_chars,
                            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                            "duration_ms": int((time.monotonic() - start) * 1000),
                            "context": context or {},
                            "status": "http_error",
                            "error": f"status={resp.status_code}",
                        })
                        raise StructuredLLMError(
                            f"Tool-call stream LLM failed: status={resp.status_code} body={body[:400]!r}"
                        )
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            obj = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(obj.get("usage"), dict):
                            usage = obj["usage"]
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        fr = choice.get("finish_reason")
                        if fr:
                            finish_reason = fr
                        delta = choice.get("delta") or {}
                        text_delta = delta.get("content")
                        if text_delta:
                            content_buf += text_delta
                            yield {"type": "content_delta", "delta": text_delta}
                        for tc_delta in delta.get("tool_calls") or []:
                            idx = tc_delta.get("index", 0)
                            slot = tc_acc.setdefault(idx, {
                                "id": None,
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                            if tc_delta.get("id"):
                                slot["id"] = tc_delta["id"]
                            fn = tc_delta.get("function") or {}
                            if fn.get("name"):
                                slot["function"]["name"] = fn["name"]
                            args_piece = fn.get("arguments")
                            if args_piece is not None:
                                slot["function"]["arguments"] += args_piece
                            yield {
                                "type": "tool_call_partial",
                                "index": idx,
                                "id": slot["id"],
                                "name": slot["function"]["name"] or None,
                                "arguments_delta": args_piece or "",
                            }
                    break  # success — exit attempt loop
    except StructuredLLMError:
        raise
    except Exception as exc:
        _record_llm_call({
            "stage": stage or "unknown", "model": config["model"],
            "prompt_chars": prompt_chars,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "context": context or {}, "status": "exception", "error": str(exc)[:200],
        })
        raise

    duration_ms = int((time.monotonic() - start) * 1000)
    tool_calls_final = [tc_acc[i] for i in sorted(tc_acc.keys())] if tc_acc else None
    message: dict = {"role": "assistant", "content": content_buf or None}
    if tool_calls_final:
        message["tool_calls"] = tool_calls_final

    _record_llm_call({
        "stage": stage or "unknown", "model": config["model"],
        "prompt_chars": prompt_chars,
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": int(usage.get("completion_tokens", 0))
            or _estimate_tokens(len(content_buf)),
        "total_tokens": int(usage.get("total_tokens", 0)),
        "duration_ms": duration_ms,
        "context": context or {},
        "status": "ok",
        "streamed": True,
    })

    yield {
        "type": "done",
        "finish_reason": finish_reason,
        "message": message,
        "usage": usage,
        "duration_ms": duration_ms,
    }


async def chat_text_stream(
    *, system_prompt: str, user_prompt: str, temperature: float = 0.7,
    stage: str = "", context: dict | None = None,
) -> AsyncIterator[str]:
    """流式文本补全，按 OpenAI-compatible SSE 协议解析 delta。yield 文本增量。"""
    config = resolve_structured_llm_config()
    if not is_structured_llm_configured():
        raise StructuredLLMError(
            "Structured extraction LLM is not configured."
        )

    # Anthropic rejects empty user-message content; normalize for cross-provider.
    user_content = (user_prompt or "").strip() or "Proceed."
    payload = {
        "model": config["model"],
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    if _supports_temperature(config["model"]):
        payload["temperature"] = temperature
    prompt_chars = len(system_prompt or "") + len(user_prompt or "")
    completion_chars = 0
    usage: dict = {}
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        url = f"{config['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        }
        # Two-attempt loop: strip provider-rejected params (e.g. temperature on
        # Claude 4.x) and reopen the stream once.
        for attempt in (1, 2):
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    body_text = body.decode("utf-8", errors="replace")
                    if attempt == 1 and _strip_unsupported_params_if_rejected(
                        payload, resp.status_code, body_text
                    ):
                        continue
                    _record_llm_call({
                        "stage": stage or "unknown", "model": config["model"],
                        "prompt_chars": prompt_chars,
                        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "context": context or {},
                        "status": "http_error",
                        "error": f"status={resp.status_code}",
                    })
                    raise StructuredLLMError(
                        f"Stream LLM failed: status={resp.status_code} body={body[:400]!r}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj.get("usage"), dict):
                        usage = obj["usage"]
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    try:
                        delta = choices[0]["delta"].get("content") or ""
                    except (KeyError, IndexError, TypeError):
                        continue
                    if delta:
                        completion_chars += len(delta)
                        yield delta
                break  # success — exit attempt loop

    duration_ms = int((time.monotonic() - start) * 1000)
    _record_llm_call({
        "stage": stage or "unknown", "model": config["model"],
        "prompt_chars": prompt_chars,
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": int(usage.get("completion_tokens", 0))
            or _estimate_tokens(completion_chars),
        "total_tokens": int(usage.get("total_tokens", 0)),
        "duration_ms": duration_ms,
        "context": context or {},
        "status": "ok",
        "streamed": True,
    })


def _estimate_tokens(chars: int) -> int:
    """中英文混合粗略估算：~2 字符/token。"""
    return chars // 2 if chars else 0
