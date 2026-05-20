# Backlog — engram

This file is the handoff point between `/compass` (writes) and `/forge` (reads + executes).

**三段、三态：**

- `/compass:materialize` **追加** bullets 到 `## Queued`。
- `/forge next` **整块移动**最顶 bullet 从 `## Queued` 到 `## Dispatched`，加 `*(dispatched <ISO>)*` 注记。
- `/forge:ship` 在 cycle done 时**整块移动** bullet 从 `## Dispatched` 到 `## Completed`，加 `*(completed <ISO> @ <short-sha>)*` 注记。

**Dispatched ≠ Completed**。Dispatched 表示某 cycle 取走但还没 ship（可能还在跑、blocked、或被放弃）。要重做就**手动**把它从 Dispatched 挪回 Queued。

每条 bullet 描述一个 feature，1-3 句话，具体到 forge spec 阶段能上手。Bullet 整体块格式见 PROTOCOL.md §"Backlog handoff format"。

## Queued

- Router 重构：entry_signals 表 + router prompt + 下游消费改造
  goal: 把 intent gate 二态准入替换为 router 多 lens × effort 强度提取。Lens 枚举：cognitive / outcome / retrospective / method_in_use / intent_express / relationship_event。
  scope: in: 新 entry_signals 表 + 单次 LLM 调用输出 signal 数组 + 下游 pipeline (dimension / backbone) 改成消费 signal 而非 raw entry; out: 不在本次实现 forebode_extract / case_extract（这俩在各自后续 plan 里）。
  relevant_code: api/app/lib/intent_gate.py, api/app/lib/db.py, api/app/lib/slice_pipeline.py, api/app/lib/backbone_pipeline.py
  origin: compass-cycle 2026-05-18-first-principles-rethink / ADR-009

- Open_loops 表 + 状态机 + extract/close pipeline + decay job
  goal: 引入"伏笔 / 承诺"独立根（中文沿用"伏笔"叙事学比喻；英文表名弃 forebode 改用 open_loop，避免 "ominous" 负面含义）。状态机：active / revisited / fulfilled / abandoned / decayed。
  scope: in: 新 open_loops 表 + open_loop_extract（消费 intent_express signal）+ open_loop_close（每条新 entry 对 active 做相关性匹配）+ decay 定时 job; out: 关系互动账（走 derived view）不本次。
  relevant_code: api/app/lib/db.py, api/app/lib/ (new open_loop module)
  origin: compass-cycle 2026-05-18-first-principles-rethink / ADR-010 (rename adopted in forge cycle 2026-05-20-contacts-name-resolution-disambiguation)

- Method_cases 表 + extract/outcome_backfill pipeline
  goal: 引入方法论 case 库。case = "在情境 S 调用了方法 M，结果 O"；outcome 回灌驱动。
  scope: in: 新 method_cases 表 + case_extract（消费 method_in_use signal）+ case_outcome_backfill（消费 outcome / retrospective signal）+ 跟 backbone method/pattern 节点的弱关联; out: method outcome 用于决策辅助消费场景的具体咨询逻辑不本次。
  relevant_code: api/app/lib/db.py, api/app/lib/ (new method_cases module)
  origin: compass-cycle 2026-05-18-first-principles-rethink / ADR-010

- Backbone_activations 扩展为四态（hit / brush / avoid / absent）
  goal: 给 backbone_activations 表加 activation_kind 字段；活动状态从单态扩为四态语义，支撑反射类"看见你看不见的"和投射类"递入口"。
  scope: in: schema 微改（migration）+ pipeline 在写 activation 时标 kind; out: 基于四态的高阶咨询逻辑（如"擦边但没进入"的 surface）不本次。
  relevant_code: api/app/lib/db.py, api/migrations/, api/app/lib/backbone_pipeline.py
  origin: compass-cycle 2026-05-18-first-principles-rethink / ADR-010

- External backbone 节点主动维护机制
  goal: 让 backbone (origin=external) 节点不再只是边推时被动拉进来，而是有主动维护工序，使投射类输出（下一维度入口）的差集计算（B − A）能给出真正的远距离推荐。具体选 a (标杆种子) / b (用户喂入) / c (LLM 远邻扩展) 哪种或组合在 forge spec 阶段定。
  scope: in: 至少实现一种主动维护路径; out: 完整的 a + b + c 不本次。
  relevant_code: api/app/lib/backbone_pipeline.py, api/app/config/backbones/
  origin: compass-cycle 2026-05-18-first-principles-rethink / ADR-010

- 采集渠道形态不限定（强化已有共识）
  goal: 明确 channel（user entry / MCP / OpenClaw / 未来通道）只是手段，按"能否稳定产生高信噪比 signal"评估，不锁定具体形态。
  scope: in: STATUS「变化项」中"输入 channel 列表"条目保留并强化（已在 ADR-011 处理）; out: 不引入具体新 channel。
  relevant_code: api/app/, cognitive-mcp/, cognitive-openclaw/
  origin: compass-cycle 2026-05-18-first-principles-rethink

- 关系互动账以 derived view 实现（不开新底表）
  goal: 关系维护能力的数据基础通过 join 现有表（contacts × entry_signals(relationship_event) × forebodes(by contact)）实现，不引入冗余的 mentions 表。
  scope: in: 后续 implementation plan 中关系咨询走 derived view; out: 不新建 contact_mentions 表。
  relevant_code: api/app/lib/
  origin: compass-cycle 2026-05-18-first-principles-rethink

- Profile dimensions 保持现状，不扩"方法论维度"（反向决定）
  goal: 显式声明 dimension 层是 trait-shaped，不承担方法论职责；方法论由独立的 method_cases 根承担。防止后续有人想"加个方法论 dimension"。
  scope: in: dimension 选择保持; out: 不在 dimension 内加方法论。
  relevant_code: api/app/config/dimensions/, api/app/lib/profile_merge.py
  origin: compass-cycle 2026-05-18-first-principles-rethink

- 三个张力作为长期文档记录
  goal: cognitive-only intake vs outcome 数据需求 / dimension trait-shaped vs case-based / 思考过 vs 做过 —— 三个张力已在 discovery.md § 3.X 标记，前两个由 ADR-009 / ADR-010 解决，第三个 v1.0 不解决（行为通道是 post-1.0）。
  scope: in: 保留在 .compass-cycles/2026-05-18-first-principles-rethink/discovery.md 作为长期参照; out: 不单独 ADR 化。
  relevant_code: —
  origin: compass-cycle 2026-05-18-first-principles-rethink

## Dispatched

<!-- /forge next 取走的条目移动到这里，附带 *(dispatched <ISO>)* 注记 -->

## Completed

<!-- /forge:ship 完成后从 Dispatched 移过来，附带 *(completed <ISO> @ <short-sha>)* 注记 -->

- contacts 表 + name resolution / disambiguation 工序（Day-1）  *(completed 2026-05-20T11:12:48Z @ 97f9287)*
  goal: 引入熟人 / 关系网独立根。包括 contacts 表、name resolution / disambiguation 工序、relationship_kind 用户可覆盖机制。是 forebodes 的 anchor 依赖。
  scope: in: 新 contacts 表 + 初始 LLM 工序 + 用户确认 / 合并 UI; out: 关系互动账走 derived view 实现，不本次。
  relevant_code: api/app/lib/db.py, api/app/lib/ (new contacts module), web/ (确认/合并 UI)
  origin: compass-cycle 2026-05-18-first-principles-rethink / ADR-010
