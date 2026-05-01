import os
from volcenginesdkarkruntime import AsyncArk

client = AsyncArk(api_key=os.environ.get("ARK_API_KEY"))

EMBED_MODEL = os.getenv("DOUBAO_EMBED_MODEL", "ep-20260330172714-b6ll6")


async def embed(text: str) -> list[float]:
    resp = await client.multimodal_embeddings.create(
        model=EMBED_MODEL,
        input=[{"type": "text", "text": text}],
    )
    return resp.data.embedding
