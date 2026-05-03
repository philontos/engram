"""Embedding client — OpenAI-compatible /embeddings, plus an Ark multimodal adapter.

Configure with:

    EMBED_BASE_URL   default: LLM_BASE_URL
    EMBED_API_KEY    default: LLM_API_KEY
    EMBED_MODEL      e.g. text-embedding-3-small / doubao-embedding-text-240715 / ep-xxx
    EMBED_API_STYLE  "openai" (default) | "ark_multimodal"
                     Switch to ark_multimodal when the bound model is a Doubao /
                     Seed multimodal embedding (vision); they only accept the
                     /embeddings/multimodal endpoint with array-typed input.
"""

import os

import httpx


_DEFAULT_TIMEOUT = float(os.getenv("EMBED_TIMEOUT_SECONDS", "30"))


def _resolve_config() -> tuple[str, str, str, str]:
    base_url = (
        os.getenv("EMBED_BASE_URL") or os.getenv("LLM_BASE_URL") or ""
    ).strip().rstrip("/")
    api_key = (
        os.getenv("EMBED_API_KEY") or os.getenv("LLM_API_KEY") or ""
    ).strip()
    model = (os.getenv("EMBED_MODEL") or "").strip()
    style = (os.getenv("EMBED_API_STYLE") or "openai").strip().lower()
    return base_url, api_key, model, style


def _extract_openai(data: dict) -> list[float]:
    return data["data"][0]["embedding"]


def _extract_ark_multimodal(data: dict) -> list[float]:
    # Ark multimodal returns { "data": { "embedding": [...] } } — singular, not a list.
    inner = data["data"]
    if isinstance(inner, list):
        return inner[0]["embedding"]
    return inner["embedding"]


async def embed(text: str) -> list[float]:
    base_url, api_key, model, style = _resolve_config()
    if not (base_url and api_key and model):
        raise RuntimeError(
            "Embedding model not configured. Set EMBED_MODEL "
            "(and EMBED_API_KEY / EMBED_BASE_URL if different from LLM_*)."
        )

    if style == "ark_multimodal":
        url = f"{base_url}/embeddings/multimodal"
        payload = {"model": model, "input": [{"type": "text", "text": text}]}
        extract = _extract_ark_multimodal
    elif style == "openai":
        url = f"{base_url}/embeddings"
        payload = {"model": model, "input": text}
        extract = _extract_openai
    else:
        raise RuntimeError(f"Unknown EMBED_API_STYLE: {style!r}")

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Embedding request failed: status={resp.status_code} body={resp.text[:400]}"
        )
    data = resp.json()
    try:
        return extract(data)
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Embedding response shape unexpected.") from exc
