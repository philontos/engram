# Backlog — engram

This file is the handoff point between `/compass` (writes) and `/forge` (reads).

- `/compass` materialize phase **appends** bullets to `## Queued`.
- `/forge next` **pops** the topmost bullet from `## Queued` and moves it to `## Dispatched` with a timestamp.

Each bullet describes a feature in 1–3 sentences, concrete enough for the forge spec phase to chew on. Place context, constraints, and "why" inline.

## Queued

- 为 engram 加一个 creativity 维度（PHRONOS-style work-cognition 那种思路也行，但范围限定在 engram psychology preset 内）。dimension 包含 backbone prompt + 默认 weight + 测试数据。验证 forge 主链路使用。

## Dispatched

<!-- 取走的条目移动到这里，附带时间戳 -->
