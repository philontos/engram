# STATUS — 当前产品形态

> **Doc system contract**（读一次，然后忽略）:
>
> 这份文件是 Engram **当下是什么**的唯一权威来源。AI session / 新 contributor 进来都先读这里。
>
> - **intake**：始终读 STATUS，默认**不读** `decisions/*.md`（除非明说"我要回顾历史"）
> - **write**：产品理解变了就**覆盖式重写**这份文件；重大决策发生时**追加**一份新 `decisions/<id>-<slug>.md`（write-only journal，永不修改已有档案）
> - **权重**：过去的决策**不掣肘**新决策。STATUS 反映**当下**的判断；decisions/ 只是历史快照
>
> Last meaningful update: 2026-05-19

---

## 第一性目标

**让一个具体的人在认知 / 方法论上持续升维。**

不是日记、不是助理、不是镜子（这些都是手段）。落点是「他变成了更高维的自己」。

衡量「升维真的发生了」的两个外化标志（不变项）：

1. **判别力** —— 用户能**清晰判断**一年前自己的判断、方法、价值排序里，**哪些是对的（与目标相关、产生了价值）、哪些是错的（背离目标 / 低价值 / 自欺）**。判别本身需要框架；用户能给出框架就是升维证据。
2. **执行力** —— 类似场景出现时，用户**更容易把事做对、把目标达成**。不是凭运气，是凭已内化的方法论。

反面证据：一年后用户**仍处在混沌里** —— 无法 articulate 过去的对错、相似情境继续栽跟头 —— Engram 失败。

---

## 一句话定义

Engram 是一个**专家级私人咨询师** —— 长期共生地观察、理解一个具体的人，借助 AI 的知识广度为他的认知与方法论升维提供针对性、定制化的咨询输出。

它不是日记 app、不是 todo、不是通用 chat 助手、不是多用户产品。

---

## 角色与人设底色

Engram 的角色不是「AI 助理」、不是「日记伙伴」、不是「always-on 守护者」，而是**专家级、私人化、长程在线的咨询师**。

**三个结构性特征（不变项）**：

1. **长程共生** —— 不是 one-shot，每次咨询都建立在前面所有积累上。
2. **知识面级 leverage** —— 借助 AI 的知识广度，能用极远的参照（其他学派、其他人的方法、其他领域的解）来回看用户。咨询不是只反射用户，是**用户 × 人类智慧库**的碰撞输出。
3. **针对性 + 定制化 / 不容忍泛泛之谈** —— 每条输出嵌进用户的具体处境 / 历史 / 词汇 / 方法论里。泛泛之谈是失败信号。

**人设底色（手段项，可演化）**：

当前 v1.0 默认：**冷酷的智者**。诚实直白、不谄媚、不打圆场、智者风范优先于亲和力。当事实分析的结论让人难受时，仍然说出来（用对方能接受的表达方式，但不替换结论）。

候选演化方向（post-1.0）：catalyst / companion / mirror / 情绪疏导 opt-in。如果将来发现别的人设对升维更高效，可调。

---

## 架构本质

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   多渠道 input   │───▶│   个人建模       │───▶│   帮助升维       │
│  + router 提取   │    │  10 层目标态     │    │  反射 + 投射     │
└──────────────────┘    └──────────────────┘    └────────┬─────────┘
        ▲                                                 │
        │                                                 │
        └────────────── 结果回流 ─────────────────────────┘
              （用户执行建议后 capture 结果）
```

三层契约：

### 1. 多渠道输入 + router 提取

输入来源会持续扩展，不锁定在某一种通道：

- **用户主动 capture**：thoughts / decisions / observations / 反思（web UI / MCP / 命令行）
- **OpenClaw 采集**：微信 / 飞书等社交平台聊天记录（经 router 提取后入库）
- **未来扩展**（v1.0 留口，post-1.0 实施）：行为数据 / 阅读 / 语音 / 对话历史 / 其他

每条 entry 不经过传统的二态准入决策（intent gate），而是经过 **router** —— 按语句 / 片段被多个 lens 同时提取，每个 lens 输出 effort 强度（0-1），下游 pipeline 各自设阈值消费。

Lens 枚举（v1.0 目标态）：`cognitive` / `outcome` / `retrospective` / `method_in_use` / `intent_express` / `relationship_event`。

Router **不承担拒绝功能**。一段长文本本质上是多 lens 并存的（"今天跟 A 吵架，答应他下周给反馈，其实每次都用同样话术效果不好" —— 同一段话既是 relationship_event + intent_express + method_in_use + outcome），整段单分类会丢失精细度。

### 2. 个人建模

不是单一画像，是**多层模型**（v1.0 目标态）：

- **L0 entries** —— 原始时序输入
- **L1 entry_signals** —— router 输出的多 signal × effort 强度
- **L2 profile_dimensions** —— 长期人格 / 工作认知维度的贝叶斯累积（OCEAN / MBTI / Schwartz / regulatory_focus / facts）。**Trait 层，不承担方法论职责**。
- **L3 用户认知层** —— `backbone where origin='internal'`（用户接触过的概念 / 学派 / 模式 / 思想家）+ activation 四态（hit / brush / avoid / absent）
- **L4 外部知识层** —— `backbone where origin='external'`（人类智慧库的子集；需主动维护：标杆种子 / 用户喂入 / LLM 远邻扩展）。用户认知层在外部知识层上的投影 = 用户认知形状，是**投射类输出的差集源**。
- **L5 forebodes** —— 伏笔 / 承诺账（状态机：active / revisited / fulfilled / abandoned / decayed；独立根；关闭事件 pipeline）
- **L6 method_cases** —— 方法论 case 库（"在情境 S 调用了方法 M，结果 O"；outcome 回灌驱动；独立根）
- **L7 contacts** —— 熟人 / 关系网（用户实际互动对象；跟 backbone person 装的思想家不同；独立根）
- **L8 关系互动账** —— derived view（不是新表）：contacts × entry_signals(relationship_event) × forebodes(by contact)
- **L9 query_logs / traces** —— 咨询会话历史

**重要边界**：

- **Backbone person 节点 by design 装的是思想家 / 学派人物 / 公众人物（不是用户的熟人）**。用户的熟人由 contacts 独立承载。两边同名条目允许并存。
- **Profile dimensions 不扩"方法论维度"**。方法论是 case-based + 情境绑定，由 method_cases 独立根承担。

### 3. 帮助升维

输出形态见下面「输出分类与能力域」。

### 结果回流（闭环）

用户执行了咨询师的建议之后，把结果作为一条**普通 entry** capture 回来 —— 复用同一管线，走 router 提取（多半触发 outcome / retrospective lens）→ 切片 → 画像融合 → 主干网 + 回灌 method_cases outcome / 关闭相关 forebodes。

v1.0 **不**引入特殊的 suggestion 状态机（不追踪"哪条建议执行了" / "成功率怎么样"）。这种闭环精细化推到 post-1.0。

---

## 消费面契约

**当前 v1.0：Pull-only via MCP**（工程取舍，非架构承诺）。

所有"主动建议"都作为**用户询问时的回答内容**给出。系统 v1.0 阶段不做：

- Push 通知 / 实时打扰
- 独立常驻 UI（advisor chat app 之类）
- 后台 cron 任务推消息
- "管家敲门" 形式的主动 surfacing

**注意**：这些不是第一性 anti-features，是 v1.0 推到 post-1.0 的手段项。push 形态（capture-triggered / 节律 / insight-triggered）本身不违反第一性 —— v1.0 选 pull 是因为最小化打扰风险 + 最快验证模型 + 最低维护负担。post-1.0 任何 push 形态都不禁。

**三类面要分清**：

| 面 | 承担什么 | 实现 |
|---|---|---|
| **咨询面 (pull, 一等)** | 用户问咨询师、获取建议、状态回顾、下一维度入口 | **MCP only** |
| **录入面** | 把内容喂进 Engram | Web UI + MCP + OpenClaw + 未来 channels |
| **检查面** | 看 pipeline 运行细节、entries、画像、知识图谱 | Web UI |

Web UI 不是咨询的主战场，它是录入 + 检查的工具。

---

## 用户契约

**单人 + 数据完全隔离。**

- 不论本地部署还是未来潜在多实例运行，**每个用户对系统而言都是世界唯一存在**
- 用户感知不到、也不应感知到任何其他用户的存在
- 不做账号 / 不做协作 / 不做共享 / 不做 SaaS / 不做多租户
- 想用 → 自己 clone 一份本地跑（或部署一个完全私有的实例）

OSS 公开理由：**架构透明化、可审阅、可自托管**。不是发展用户群、不是做社区产品。

---

## 输出分类与能力域

Engram 的输出按**第一性切分**为两类（不再按场景切）：

### 反射类（reflective） —— 用户自己语料的反射

来源：用户自己的语料（不论是某条 entry 字面，还是多条 entry 涌现）；底层算法 = aggregation + retrieval。
用户体验："我原来在 X 上一直这样" / "对，我之前想做这件事"。

这类输出是几乎任何"有长程记忆的 LLM"都能做的，门槛低。是 v1.0 已基本覆盖的能力。

### 投射类（projective） —— 用户画像 × 人类智慧库的差集

来源：用户认知形状（L3 用户认知层在 L4 外部知识层上的投影）的差集；这里没有用户自己的话。
用户体验："这个角度我从没想过" / "我得去接触 X"。

**投射类是 Engram 与「任何 LLM 套个长记忆」的真正分水岭**，最难做、也最容易做成"通用建议"。所以输出质量门槛（不变项）：**宁可不说，不说泛泛之谈**。

### 能力域（v1.0）

| 类 | 场景 | 用户问的样子 | 系统输出基于 |
|---|---|---|---|
| **反射** | 状态回顾 | "我最近的关注点是什么？" / "我这周状态怎么样？" | 近期 entries + profile diff + 情绪/能量曲线 |
| **反射** | 关系维护 | "我最近该跟谁建联？" / "我跟 X 上次说了什么？" | contacts + 关系互动账 + forebodes(by contact) |
| **反射** | 决策辅助 | "我该不该接这个 offer？" / "过去的我怎么想这件事？" | 历史相关 entries + 画像匹配度 + method_cases(类似情境结果) |
| **反射** | 伏笔追踪 | "我之前想做但没做的事？" / "答应过的事还没回应？" | forebodes (status=active) + 未跟进列表 |
| **反射** | 模式识别 | "我反复在 X 上犯什么错？" / "什么时候我容易这样？" | entries 聚类 + activation 四态 + method_cases outcome failure |
| **投射** | **下一维度推荐** | "我接下来该接触什么 / 学什么 / 怎么思考？" | 用户认知形状 × 外部知识层差集 + 定向匹配 |

**v1.0 阶段当前缺口**：投射类的"下一维度推荐"还没建立；当前所有 5 个反射类已基本覆盖。差距详见下文 v1.0 目标态 vs 当前阶段。

---

## v1.0 目标态 vs 当前阶段（原型）

**v1.0 目标态 = 本 STATUS 描述的完整产品形态**。不是分多个 minor 版本演进出来的，是一次性定下的目标。

**当前实现状态 = 原型**。覆盖了 v1.0 的部分基底（entries / dimensions / backbone / consultation log），但还缺以下几块：

| 维度 | 原型 | v1.0 |
|---|---|---|
| 采集准入 | Intent gate 二态（cognitive only） | Router 多 lens × effort 强度，无拒绝 |
| 分流粒度 | 整段单分类 | 按语句 / 片段提取多 signal |
| 用户认知层 | backbone (origin=internal) | 同 + activation 四态 |
| 外部知识层 | backbone (origin=external)，只在边推时被动拉入 | 同 + 主动维护工序 |
| 伏笔 / 承诺 | 无 | forebodes 表 + 状态机 + 关闭事件 pipeline |
| 方法论 | 无（profile dimension 不承担） | method_cases 表 + outcome 回灌 pipeline |
| 熟人 / 关系网 | 无（backbone person 装的是思想家） | contacts 表 + 关系互动 derived view |
| 消费能力 | 5 个反射类 | 5 个反射类 + 1 个投射类（下一维度推荐） |
| 触发方式 | Pull-only | Pull-only（v1.0 仍保持） |
| 人设 | 冷酷智者 | 冷酷智者（v1.0 仍保持） |

**原型 → v1.0 的实施依赖顺序**（不是路线图，是依赖约束）：

1. **contacts**（其他独立根的 anchor 必须先有）
2. **router 重构**（解锁多 content_type signal，是后续所有根的输入前提）
3. **forebodes**（依赖 router 的 `intent_express` signal + contacts 作为 target anchor）
4. **method_cases**（依赖 router 的 `method_in_use` + `outcome` signal）
5. **activation 四态扩展**（提升反射类质量）
6. **external backbone 主动维护**（解锁投射类输出 —— Engram 真正的差异化）

完成上述 6 步 = v1.0。

---

## 明确不做（anti-features）

### 第一性 anti-features（架构性拒绝）

| 类别 | 不做原因 |
|---|---|
| Notes / journal / diary / habit tracker / todo / reminder | 不是它的品类。这些有更合适的工具 |
| 密钥 / dotfiles / 配置文件 / 凭证存储 | 安全模型不匹配 |
| 多用户协作 / 共享 / 社区 / SaaS | 违反用户契约 |
| 把画像作为 context 注入第三方通用 chat（context middleware）| Engram **自己**是消费面，不当别人的 context layer |
| 通用 chat / 闲聊 / 一般助理任务 | 不是它的品类。它只回答关于"你"的问题 |
| 浏览器扩展 / IDE 内联建议 / OCR / 语音转写 | 跟核心建模无关，离散工具该单独活 |

这些拒绝是**架构性的**，违反核心契约。

### 推到 post-1.0 的手段项（不是 anti-feature，是 v1.0 不做）

| 类别 | 推后原因 |
|---|---|
| Push 通知 / 实时 surfacing / capture-triggered / 节律 / insight-triggered | v1.0 选 pull-only 是工程取舍。push 形态本身不违反第一性 |
| 多人设 / catalyst / companion / 情绪疏导 opt-in | v1.0 用单一冷酷智者人设。多人设不违反第一性 |
| 行为数据通道（git commit / 日程 / 行动记录等） | v1.0 仍以 cognitive 为主输入，行为通道用于解决"思考过 vs 做过"张力 |
| Suggestion 闭环（追踪"哪条建议执行了 / 成功率"）| v1.0 用 method_cases 的 outcome 字段做基础回灌，更精细的状态机推后 |
| 独立 advisor UI / 桌面常驻 app | 跟 push 一起评估 |

---

## 不变项 vs 变化项

为了让未来的 maintainer / AI session 知道什么可以动、什么不能动：

**不变项（动了就不是 Engram 了）：**

- 终点：升维 / 提升认知与方法论
- 升维的双标志：判别力 + 执行力
- 单用户 + 数据完全隔离
- 长程共生（不是 one-shot 工具）
- 知识面级 leverage（用户 × 人类智慧库的碰撞）
- 针对性 + 定制化 / 不容忍泛泛之谈
- 输出必须可追溯到具体语料

**变化项 / 手段项（持续演进）：**

- 输入 channel 列表
- Router lens 枚举 + effort 阈值
- 建模维度（profile dimensions / backbone domains）
- 建模数据结构选择
- 消费触发方式（当前 + v1.0 pull-only；post-1.0 可加 push 形态）
- "咨询师不主动打扰用户"的常态（手段，不是不变项）
- 消费形态比例（反射类 vs 投射类权重）
- 人设底色（冷酷智者是当前默认，不是不变项）
- 部署形态（本地 / 私有云 / docker-compose 模板）
