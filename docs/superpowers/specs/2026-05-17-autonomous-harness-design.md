# 自主 Harness 设计

**日期**：2026-05-17
**作者**：王宇昊 + Claude
**状态**：Phase 1 设计（主链路）已就绪；Phase 2（防御层）推迟

## 1. 背景与目标

在 engram 与 phronos 两个 personal repo 上，搭建一套以 Claude Code 原生能力（slash command、skill、subagent、hook）为底座的"自主 harness"，把"讨论清楚一个 feature → 出 PR"压成一条**可预期**、**少人工干预**的流水线。

**首个用户场景**：嫁接到 engram，跑 Feature 交付类任务。一个 cycle 的产物 = 一个可合并的 PR。

**不解决**（明确不在范围）：
- bug fix / refactor / 文档 / i18n 任务的最佳路径（先做 Feature 一类）
- 多 cycle 并行编排（先单 cycle 跑顺）
- 远程（cron）调度（先本地）

## 2. 核心心智模型

整套 harness 的本质可以压成一句话：

> **6 个 slash command 按一份 `state.json` 协议互相接力。**

其它一切（worktree、Stop hook、PushNotification、AGENTS.md 注入、subagent）都是辅助设施，不构成主链路。

```
1 个 cycle  ⟺  1 个 git worktree  ⟺  1 条 harness/<cycle_id> 分支  ⟺  最终 1 个 PR
```

## 3. 五个关键设计决策（带原因）

| # | 决策 | 选项 | 选 | 原因 |
|---|---|---|---|---|
| 1 | 场地 | 沙盒 / engram / phronos / 全局 meta | **嫁接到 engram + phronos** | 验真比验快重要；AGENTS.md 硬规则已经把"什么不能干"写死，自主性边界清晰 |
| 2 | 人介入闸门 | spec only / spec+plan / 每 PR / 实时干预 | **spec gate + plan gate；之后全自动** | 一道闸门信任不够，三道破坏自主性；两道在"安全"与"自主"之间是甜点 |
| 3 | 首批任务类型 | Feature / Bug / Doc&Test / Refactor | **Feature 交付** | 最能覆盖全链路；如果 Feature 跑通，其它任务类型派生 |
| 4 | 触发模型 | slash / backlog / cron / 混合 | **混合（slash + backlog）** | `/harness <req>` 即开即跑，`/harness next` 从 backlog 取顶端项；不引入远程 |
| 5 | 失败行为 | 硬中断 / 降级 PR / 跳过 | **硬中断 + 保留现场 + 通知** | 跟"可预期"目标最匹配；降级 PR 容易制造"假完成" |

## 4. 架构总览

```
人触发 ─┬─ /harness <req>          ┐
       └─ /harness next  ←─ backlog ┘
                 │
                 ▼
spec ─→ [spec-review gate] ─→ plan ─→ [plan-review gate] ─→ impl ─→ review ─→ ship ─→ done
 │           │                  │              │              │        │        │
 ▼           ▼                  ▼              ▼              ▼        ▼        ▼
brain-      Ask                writing-       Ask           executing-  req-   finishing-
storming   User                 plans         User           plans +    code-   a-dev-
skill                           skill                        TDD +      review  branch
                                                             verif.     skill   skill
```

**三个组件，干净解耦**：

```
┌──────────────────┐   读     ┌──────────────────┐   读     ┌──────────────────┐
│  slash command   │ ───────→ │   state.json     │ ←─────── │   Stop hook      │
│  （phase 主体）    │  ←──     │  （现场记录）       │   ──→     │  （可选兜底）       │
└──────────────────┘   写     └──────────────────┘   决策    └──────────────────┘
        │
        │ 调用
        ▼
   superpowers skill
   （干活的大脑）
```

- **command** 只懂"做完一件事 + 写 state"，不知道下一步是谁。
- **skill** 只懂"怎么干这一类活"，不知道 harness 存在。
- **state.json** 是唯一接力契约。
- **Stop hook** 在 Phase 1 不实现；Phase 2 作为冗余防御层（防 PushNotification 漏发）。

## 5. 目录布局

**Harness 代码**（全局，engram 与 phronos 共用）：

```
~/.claude/
├── commands/
│   ├── harness.md              # /harness <req> | /harness next  （bootstrap）
│   └── harness/
│       ├── spec.md             # /harness:spec
│       ├── plan.md             # /harness:plan
│       ├── impl.md             # /harness:impl
│       ├── review.md           # /harness:review
│       ├── ship.md             # /harness:ship
│       └── approve.md          # /harness:approve
└── （hooks/、settings.json 改动留到 Phase 2）
```

**Cycle 工作区**（每个 cycle 一份，住在所操作 repo 的内部 .gitignore 目录里）：

```
<repo>/.harness-worktrees/<cycle_id>/    # git worktree，分支 harness/<cycle_id>
├── .harness/
│   ├── state.json
│   ├── spec.md                 # spec phase 产物
│   ├── plan.md                 # plan phase 产物
│   ├── transcript/<phase>.log  # 各 phase 的会话节录，blocked 时给人接手用
│   └── blocker.md              # 仅 blocked 时存在
└── ...（repo 原有代码，处于 harness/<cycle_id> 分支签出状态）
```

**Backlog**（每个 repo 一份，常驻主仓）：

```
<repo>/docs/harness/backlog.md   # markdown bullet list；顶端先进先出
```

**Bootstrap 必须做的 .gitignore 注入**（每个 repo 首次跑 harness 时）：

```gitignore
# autonomous harness — cycle worktrees
.harness-worktrees/
```

## 6. State.json 协议

```jsonc
{
  "cycle_id": "2026-05-17-add-creativity-dimension",  // 创建时定，等于分支名后缀
  "repo": "engram",                                    // engram | phronos
  "request": "为 engram 加一个 creativity dimension…", // 原始描述
  "phase": "plan",                                     // spec | plan | impl | review | ship | done
  "status": "needs-review",                            // ok | needs-review | blocked | done
  "next": "impl",                                      // status=ok 时下一 phase；status=done 时为 null
  "gate": {                                            // 仅 status=needs-review 时存在
    "kind": "plan-review",                             // spec-review | plan-review
    "artifact": ".harness/plan.md",
    "approve_cmd": "/harness:approve"
  },
  "blocker": null,                                     // 仅 status=blocked 时填
                                                       // { phase, reason, last_action, transcript }
  "history": [                                         // append-only；hook/command 不读它做决策
    { "phase": "spec", "status": "ok", "at": "2026-05-17T10:01:33Z" },
    { "phase": "plan", "status": "needs-review", "at": "2026-05-17T10:14:02Z" }
  ]
}
```

**不变量**：

1. `status` 只有 4 种取值；任何消费方分支只看 status。
2. `next` 必须是 `{spec, plan, impl, review, ship}` 之一（或 null）。命令通过 `~/.claude/commands/harness/${next}.md` 反查模板文件。
3. `gate.approve_cmd` 必须是字面 `/harness:approve`——人不需要记任何命令。
4. `history` 仅供观测；消费方做决策时**不读 history**，保证幂等。

## 7. 六个 command 的职责

每个 command 模板（markdown）的内部分四段：
1. 设定上下文（读 AGENTS.md、读 state.json、读上游产物）
2. 调对应 superpowers skill 干活
3. 写 state.json
4. **Self-chain 尾段**（所有 command 共享同一段固定话术）

### 7.1 Self-chain 尾段（所有 command 共享）

```markdown
最后一步——自驱接力：
1. 读回 .harness/state.json 的 status 和 next 字段
2. 如果 status == "ok" 且 next 非空：
   读取 ~/.claude/commands/harness/${next}.md 的全部内容，
   作为新的指令立即执行（等于在同一轮里跑下一个 phase）
3. 如果 status 是 needs-review 或 blocked 或 done：
   调 PushNotification 工具，message 为：
     needs-review → "{cycle_id}: {gate.kind} 待审, 运行 {gate.approve_cmd}"
     blocked      → "{cycle_id}: blocked at {blocker.phase}: {blocker.reason}"
     done         → "{cycle_id}: 完成 ✓"
   然后让本轮自然结束，不再继续。
```

### 7.2 各 command 简表

| Command | 调的 skill | 主要产出 | status 取值 | next 取值 |
|---|---|---|---|---|
| `/harness <req>` 或 `/harness next` | using-git-worktrees | worktree + 初始 state.json | ok | spec |
| `/harness:spec` | brainstorming | spec.md | needs-review | plan |
| `/harness:approve` | （无） | 翻 status | ok | （沿用上一 phase 写好的 next） |
| `/harness:plan` | writing-plans | plan.md | needs-review | impl |
| `/harness:impl` | executing-plans + test-driven-development + verification-before-completion；可派 dispatching-parallel-agents | 代码变更 + 测试 + commit | ok / blocked | review |
| `/harness:review` | requesting-code-review（reviewer 是独立 subagent，仅看 diff + spec.md + AGENTS.md） | review 报告 | ok / blocked | ship |
| `/harness:ship` | finishing-a-development-branch | push + `gh pr create` | done | null |

**bootstrap 命令 `/harness`** 的两种形态：

- `/harness <自由文本需求>`：直接以该需求建 cycle
- `/harness next`：从 `<当前所在 repo>/docs/harness/backlog.md` 顶端取一条 bullet 作为 request；取走后从顶端移动到底部"已派单"区

`cycle_id` 规则：`YYYY-MM-DD-<kebab-slug>`；slug 来自 request 的前几个关键词（assistant 自定，保证唯一）。

### 7.3 关键细节：AGENTS.md 注入

`spec` 和 `review` 两个 phase 必须把当前 repo 的 `AGENTS.md`（及 sub-AGENTS.md，如 `web/AGENTS.md`、`cognitive-service/frontend/AGENTS.md`）**全文**读入上下文。
- `spec` phase：在 brainstorming 之前注入，使产物从一开始就受硬规则约束。
- `review` phase：reviewer subagent 以 AGENTS.md 为审查 checklist 之一。

不需要额外做规则解析或自动化静态检查（那是 Phase 2）。

## 8. 失败路径（最小版）

任一 command 在 phase 内部判定"无法继续"时统一动作：

1. 写 `state.json`：`{ status:"blocked", blocker:{ phase, reason, last_action, transcript:".harness/transcript/<phase>.log" } }`
2. 写 `.harness/blocker.md`（人类可读：现象 + 已尝试方案 + 建议人介入的位置）
3. 调 `PushNotification`：`"<cycle_id>: blocked at <phase>: <reason>"`
4. **不** self-chain；让本轮自然结束。
5. **不** 清理 worktree。

人接手两条路径：

- `cd <repo>/.harness-worktrees/<cycle_id>/`，看 `blocker.md` + `transcript/`，必要时手改文件，最后 `/harness:resume`（语义：把 status 翻成 ok，重跑被 blocked 的 phase）。`resume` 留作 Phase 2 实现；Phase 1 人手动改 state.json 即可。
- 放弃：`git worktree remove <path>` + `git branch -D harness/<cycle_id>`。

**Phase 1 不做**：
- 自动重试预算（N 次）
- Stop hook 兜底通知
- 自动诊断 blocker 类型
- blocked cycle 自动回 backlog

## 9. 不做（Phase 2 及以后）

明确推迟，避免污染 Phase 1：

| 项 | 推迟原因 |
|---|---|
| Stop hook（os notification 兜底） | 主链路通了再加；99% 情况主链路够 |
| `/harness:resume` 命令 | Phase 1 人手改 state.json 简单可行 |
| 多 cycle 并行编排 | 单 cycle 跑顺再扩 |
| Backlog 状态机（queued→speccing→…） | Phase 1 backlog 仅为 FIFO bullet 列表 |
| 跨 cycle learning（memory 积累） | 等若干 cycle 真实数据后再设计 |
| 远程 cron agent | 本地够用 |
| 自动 AGENTS.md 静态检查 | reviewer subagent 已经做语义检查 |

## 10. 首个验证 Cycle（Phase 1 的 Acceptance Test）

在 engram 上跑一个真实 cycle 作为 harness 主链路是否可用的验收：

**Feature**：为 engram 加一个新的 dimension —— `creativity`（创造力）。

**为何选它**：

- 覆盖 spec → plan → impl → review → ship 全链路
- 触发 engram 三条 AGENTS.md 硬规则（English enums / English default prompts / restart-required config OK）
- 涉及目录结构：`cognitive-service/app/config/dimensions/`、`scripts/manage_config`
- 范围被 dimension 体系约束，不会发散
- 失败损失低（一个 dimension 加错了，回退一个 PR 即可）

**Acceptance**：

1. `/harness creativity 维度` 启动；spec phase 产出符合 AGENTS.md 的 `spec.md`；spec gate 触发，PushNotification 推到手机
2. `/harness:approve` 后 plan phase 自动续上；plan gate 触发，再次推送
3. `/harness:approve` 后 impl phase 自动续上，跑测试通过
4. review subagent 通过（没有"必须改"项）
5. ship phase 自动 push + 开 PR；done 通知到手机
6. 整个过程除两次 `/harness:approve` 外，没有任何人工干预

## 11. 工作量估计（Phase 1）

| 项 | 估计 |
|---|---|
| 6 个 command 模板 | ~3 小时 |
| state.json 协议固化（schema 注释文档） | 0.5 小时 |
| backlog.md 模板 | 5 分钟 |
| bootstrap 的 .gitignore 注入 | 5 分钟 |
| 首个验证 cycle 实跑（含调试） | 0.5–数小时（取决于踩多少坑） |

**总计**：半天到一天可跑通主链路。

## 12. 风险与已知约束

- **Self-chain 上下文长度**：6 个 phase 串成一个长 Claude turn，可能逼近 context 上限。依赖 Claude Code 自动压缩；最坏情况下分多次会话执行，靠 state.json 的幂等性接住。
- **`stop_hook_active`**：选 self-chain 而非 hook-driven 接力，本质上就是为了绕开这个标志。Phase 2 加 Stop hook 时必须只用作"非续接的兜底通知"，不再尝试注入 prompt。
- **AGENTS.md 是 source of truth**：harness 不替代 AGENTS.md 的硬规则，它只是把规则注入到每个相关 phase。规则更新由 repo 维护者负责。
- **首个 cycle 失败处理**：如果首个验证 cycle 在 plan/impl 阶段反复 blocked，先排查"command 模板里 self-chain / state 写入"是否正确，再排查 "skill 是否被正确调用"，最后再排查"业务规则是否被违反"。

## 13. 落地顺序（供 writing-plans 拆任务时参考）

1. 落 state.json schema 文档 + backlog.md 模板（最容易先固化）
2. 写 6 个 command 模板（建议顺序：harness.md → spec.md → approve.md → plan.md → impl.md → review.md → ship.md）
3. 在 engram 注入 `.gitignore` + 建 `docs/harness/backlog.md`
4. 跑首个验证 cycle（creativity dimension），记录每一步实际行为
5. 据实跑结果回填 command 模板里的 prompt 细节
6. 同样的 6 个 command 试跑 phronos 的一个小 feature，确认全局共用方案成立

Phase 2 改动单独立 spec。

---

**对应 brainstorm 共识检查清单**：

- [x] 场地：engram + phronos
- [x] 闸门：spec + plan，之后全自动
- [x] 任务类型：Feature 交付
- [x] 触发：混合 slash + backlog
- [x] 失败：硬中断 + 现场 + 通知
- [x] 位置：全局 ~/.claude
- [x] 隔离：git worktree
- [x] 协议：state.json
- [x] 执行：6 个 command + self-chain + skill 复用
- [x] Phase 2：Stop hook + 重试 + backlog 状态机 + 跨 cycle learning
- [x] 首个验证：engram creativity dimension
