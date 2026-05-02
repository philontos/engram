"""Web search via Tavily API.

Tavily is designed for LLM agents — returns clean snippets, no scraping required.
Sign up at https://tavily.com — free tier 1000 searches/month.

If TAVILY_API_KEY is not set, web_search returns a "not configured" message
that the agent can route around. No hard failure.
"""

import os
import httpx

TAVILY_ENDPOINT = "https://api.tavily.com/search"


def is_web_search_configured() -> bool:
    return bool(os.getenv("TAVILY_API_KEY", "").strip())


async def web_search(query: str, max_results: int = 5) -> dict:
    """Run a web search. Returns {results, summary} or {error}.

    results: list of {title, url, snippet}
    summary: short string the LLM can quote in its synthesis
    """
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {
            "error": "web_search 未配置（缺少 TAVILY_API_KEY）",
            "results": [],
            "summary": "（web_search 未配置，跳过此次调用）",
        }

    max_results = max(1, min(max_results, 10))
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",      # "basic" or "advanced"
        "max_results": max_results,
        "include_answer": True,        # Tavily generates a quick LLM-friendly summary
        "include_raw_content": False,  # would inflate context
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(TAVILY_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return {"error": "web_search 超时", "results": [], "summary": "（搜索超时）"}
    except httpx.HTTPStatusError as e:
        return {"error": f"web_search HTTP {e.response.status_code}", "results": [], "summary": "（搜索失败）"}
    except Exception as e:
        return {"error": f"web_search 异常: {e}", "results": [], "summary": "（搜索异常）"}

    results = []
    for r in data.get("results", []):
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content") or "")[:600],
        })

    answer = (data.get("answer") or "").strip()
    return {
        "results": results,
        "summary": answer or f"找到 {len(results)} 条结果",
    }


def format_results(results: list[dict], summary: str) -> str:
    """Format web results as text for the agent's tool message."""
    if not results:
        return summary or "（无结果）"
    lines = []
    if summary:
        lines.append(f"**速览：** {summary}\n")
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] **{r['title']}**")
        lines.append(f"    {r['url']}")
        if r['snippet']:
            lines.append(f"    {r['snippet']}")
        lines.append("")
    return "\n".join(lines)
