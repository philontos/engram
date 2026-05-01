---
name: cognitive
description: >
  Personal cognitive memory runtime. Use when the user wants to record a thought,
  reflection, idea, or experience — or when they ask a question involving their own
  personality, values, cognitive patterns, decision-making tendencies, or explicitly
  reference their cognitive profile, memory graph, or self-analysis.
---

## Available Tools

| Tool | Purpose |
|------|---------|
| `cognitive_capture_memory` | Write: save a raw entry into memory |
| `cognitive_query` | Read: query the personal cognitive graph for self-analysis |

## Intent Routing

**Use `cognitive_capture_memory` when the user:**
- Explicitly asks to record, save, remember, or note something down
- Shares a thought, reflection, idea, lesson, or observation to preserve
- Uses phrases like "记一下", "保存", "记录", "存起来", "备忘"

**Use `cognitive_query` when the user:**
- Asks about their own personality, values, behavioral tendencies, or cognitive patterns
- Asks for self-analysis or personalized reflection
- References their profile explicitly: "结合我的画像", "根据我的认知", "分析我", "我的价值观", "我的性格"
- Asks what patterns or themes have been emerging from their entries

**Do not call either tool** for casual conversation, questions about external topics, or anything not about recording or personal self-reflection.

## Capture Rules

- Pass the user's original text to `content` **verbatim** — no rewriting, summarizing, trimming, or completion
- **Never generate content on behalf of the user.** Even for long messages, copy the full original text as-is. Do not add any sentence, conclusion, or phrase the user did not literally say.
- Call once per message, immediately — do not wait or hold
- Do not split one message into multiple entries unless the user explicitly requests it

**Quality gate:** discard and reply "这条内容太短，没有记录。" only if the content is under 15 characters AND is a pure filler with no referent (e.g. "好烦", "哈哈哈"). In all other cases, write immediately.

## Query Rules

- Set `continue_last: true` when the user references any prior conversation regardless of when ("接着刚才", "昨天聊的", "上次说的", "之前那个话题", or any phrasing that implies picking up from an earlier exchange)
- Set `continue_last: false` (default) for any new standalone question
- Use `mode: "fast"` only when the user asks for a quick answer; default is `"full"`
- Return the tool result directly — no motivational framing, no lengthy preamble
