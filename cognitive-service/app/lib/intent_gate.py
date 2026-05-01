"""入口意图识别：决定一条输入走哪条轨道。

track:
  entry  — 内容完整，用户在处理某件事（有观点/情绪展开/反思/决策），走完整分析链路
  memo   — 内容完整，用户只是在记录某件事（事实/备忘/提醒/简短情绪标记），存 memos 表
  buffer — 内容明显未说完，暂存等待续写
"""

from shared.llm import chat_json, is_structured_llm_configured

_SYSTEM = """\
You are an intent classifier for a personal cognitive capture system.
Classify the user's input into exactly one track. Output strict JSON only:
{"track": "entry" | "memo" | "buffer", "reason": "<one short sentence>"}

## Track definitions

entry — The user is PROCESSING something: expressing an opinion, working through an emotion,
  reflecting on a pattern, weighing a decision, or narrating an experience with self-observation.
  The content is self-contained and complete.
  Examples:
  - "我总是恐飞，真的好苦恼，不知道如何解决" → entry (persistent pattern + emotional weight + seeking resolution)
  - "今天开会我意识到自己总是回避冲突" → entry (self-observation)
  - "要不要换工作，我在想..." → entry (decision weighing)

memo — The user is RECORDING something: stating a fact, logging an event, leaving a reminder,
  or making a brief note. The content is complete but has no cognitive signal worth analyzing.
  Examples:
  - "今天吃了火锅" → memo (pure event log)
  - "下周提醒我去体检" → memo (reminder)
  - "跑步5km，28分钟" → memo (data log)
  - "今天有点累" → memo (brief emotion tag, no elaboration)
  - "明天10点开会" → memo (calendar note)

buffer — The input is clearly incomplete: the sentence is unfinished, it's an obvious
  continuation of something unsaid, or it's just a topic opener with no content yet,
  OR the user explicitly signals they haven't finished.
  Examples:
  - "今天开会讨论了产品方向，" → buffer (sentence trails off)
  - "关于最近的状态，" → buffer (topic opener, no content)
  - "还有一点，" → buffer (explicit continuation marker)
  - "今天发生了很多事，心情很复杂。我还没说完" → buffer (explicit unfinished signal at end)
  - "接上一条。然后我意识到..." → buffer (explicit continuation of prior segment)
  - "接上面一条，我当时..." → buffer (explicit continuation of prior segment)
  - "我女儿刚5岁，有时候难以反抗这个权威。接着说" → buffer (continuation signal at end)

## Key distinction: entry vs memo
Ask: is the user PROCESSING or just RECORDING?
- "今天和朋友吵架了" → memo (event statement only)
- "今天和朋友吵架了，我意识到我很难接受被否定" → entry (self-observation added)
- "今天很累" → memo
- "今天很累，但还是把方案写完了，感觉自己放不下对结果的执念" → entry

## OVERRIDE: explicit recording intent
If the text starts with an explicit recording qualifier — '单纯记录', '只是记录', '随手记', '备忘一下', '记一下', '记录一下' — classify as **memo** regardless of how deep or reflective the content appears.
The user has explicitly stated they do NOT want cognitive processing; honor that signal.
Examples:
- "单纯记录一下：感觉这个认知系统的泛化性不够。在单一领域还行，但跨领域泛化不太行。" → memo (explicit recording qualifier overrides content depth)
- "随手记一下，优化点：认知系统接口应该返回明确信息" → memo (explicit recording qualifier)\
"""


async def classify(content: str) -> dict:
    """返回 {"track": "entry"|"memo"|"buffer", "reason": str}。
    LLM 不可用时降级为 entry（保守策略，不丢数据）。
    """
    if not is_structured_llm_configured():
        return {"track": "entry", "reason": "llm not configured, fallback to entry"}

    try:
        result = await chat_json(
            system_prompt=_SYSTEM,
            user_prompt=content,
            stage="intent_gate",
        )
        track = result.get("track", "entry")
        if track not in ("entry", "memo", "buffer"):
            track = "entry"
        return {"track": track, "reason": result.get("reason", "")}
    except Exception:
        return {"track": "entry", "reason": "classification failed, fallback to entry"}
