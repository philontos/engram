import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator, Optional

import httpx


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


LLM_PROVIDER = os.getenv("STRUCTURED_LLM_PROVIDER", "ark").strip().lower()
LLM_TIMEOUT_SECONDS = float(os.getenv("STRUCTURED_LLM_TIMEOUT_SECONDS", "60"))


class StructuredLLMError(RuntimeError):
    pass


def _provider_defaults(provider: str) -> tuple[str | None, str | None]:
    if provider == "ark":
        return (
            os.getenv("ARK_API_KEY"),
            os.getenv("ARK_TEXT_MODEL"),
        )
    if provider == "moonshot":
        return (
            os.getenv("MOONSHOT_API_KEY"),
            os.getenv("MOONSHOT_TEXT_MODEL") or "kimi-k2.5",
        )
    if provider == "deepseek":
        return (
            os.getenv("DEEPSEEK_API_KEY"),
            os.getenv("DEEPSEEK_TEXT_MODEL") or "deepseek-chat",
        )
    if provider == "minimax":
        return (
            os.getenv("MINIMAX_TEXT_API_KEY") or os.getenv("MINIMAX_API_KEY"),
            os.getenv("MINIMAX_TEXT_MODEL") or "MiniMax-M2.5",
        )
    return (None, None)


def _provider_base_url(provider: str) -> str | None:
    if provider == "ark":
        return "https://ark.cn-beijing.volces.com/api/v3"
    if provider == "moonshot":
        return "https://api.moonshot.cn/v1"
    if provider == "deepseek":
        return "https://api.deepseek.com"
    if provider == "minimax":
        return "https://api.minimax.io/v1"
    return None


def resolve_structured_llm_config() -> dict[str, str]:
    provider = LLM_PROVIDER
    api_key, default_model = _provider_defaults(provider)
    api_key = api_key or ""
    model = (default_model or "").strip()
    base_url = _provider_base_url(provider) or ""
    return {
        "provider": provider,
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


async def chat_json(
    *, system_prompt: str, user_prompt: str,
    stage: str = "", context: dict | None = None,
) -> dict[str, Any]:
    config = resolve_structured_llm_config()
    if not is_structured_llm_configured():
        raise StructuredLLMError(
            "Structured extraction LLM is not configured. Set STRUCTURED_LLM_PROVIDER plus the matching provider API key/model."
        )

    payload = {
        "model": config["model"],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    prompt_chars = len(system_prompt or "") + len(user_prompt or "")
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
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
                f"Structured extraction LLM failed: status={resp.status_code} body={resp.text[:400]}"
            )

        data = resp.json()
        usage = data.get("usage") or {}
        record = {
            "stage": stage or "unknown", "model": config["model"],
            "prompt_chars": prompt_chars,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "duration_ms": duration_ms, "context": context or {},
            "status": "ok",
        }
        _record_llm_call(record)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise StructuredLLMError("Structured extraction LLM returned an unexpected response shape.") from exc

        return _extract_json_object(content)
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
        "temperature": 0.3,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
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
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    start = time.monotonic()

    content_buf = ""
    tc_acc: dict[int, dict] = {}
    finish_reason = "stop"
    usage: dict = {}

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
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

    payload = {
        "model": config["model"],
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    prompt_chars = len(system_prompt or "") + len(user_prompt or "")
    completion_chars = 0
    usage: dict = {}
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        async with client.stream(
            "POST",
            f"{config['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
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
