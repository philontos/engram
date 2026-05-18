# Engram API

[English](README.en.md) · **中文**

个人认知记忆系统。将原始输入转化为人格画像 + 知识图谱，并支持多轮个性化查询消费。

## 整体架构

两条独立链路：

**写入链路（capture → process）**

```
POST /capture
  └─ embed(raw) → entries + vector_store

POST /entries/{id}/process
  ├─ slice_pipeline         维度切片 → profile_dimensions（OCEAN / Schwartz / facts / situation）
  └─ backbone_pipeline
       Stage 1  Activation     各知识域激活权重（0–1）
       Stage 2  全域粗召回      embed(raw) → 向量搜索 top-30 存量节点
       Stage 3  Node Extract   各域 LLM 并发提取候选节点（内源 + 外源）
       Stage 4  Resolution     同域去重（≥0.92 合并），跨域记相似对
       Stage 5  精召回          per-node 3-hop/1-hop 子图展开
       Stage 6  Edge Extract   各域 LLM 写边，算法融合权重
       Stage 7  跨域相似边      写入 Stage 4 记录的跨域对
```

**消费链路（query）**

```
POST /query
  ├─ 从 DB 加载会话历史（server-side，调用方只需传 session_id）
  ├─ Stage 1  Intent Check    意图分类（proceed / clarify / off_topic）
  ├─ Stage 2  Baseline (Q1)   通用解答（full 模式）
  ├─ Stage 3  Persona (Q2)    人格穿刺，画像注入（full 模式）
  ├─ Stage 4  Graph Explore   Agent loop，多轮工具调用探索图谱
  │             graph_search     语义搜索入口节点
  │             expand_node      沿关系边展开子图
  │             get_opposites    获取对立/矛盾节点
  ├─ Stage 5  Theme Analysis  高权重节点关联原始 entries 深析
  └─ Stage 6  Synthesis       基于探索结果流式输出图谱洞察
```

响应格式：NDJSON 流式，每行一个 JSON 事件（`stage` / `delta` / `tool_call` / `done`）。

## 核心机制

### 节点 Strength 衰减（DWAS）

每次 entry 命中某节点时，strength 按 **DWAS（Decay-Weighted Activation Sum）** 更新：

```
写入：strength_new = strength_old × exp(-λ × Δt_since_last_hit) + new_conf
读取：effective    = stored × exp(-λ × days_since_last_hit)
```

实现见 `app/lib/backbone_pipeline.py:_update_node_strength` 与 `effective_strength`，参数在 `app/config/graph_rules.py:NODE_STRENGTH`。

#### 物理意义

- **strength**：节点的"近期反复出现强度"（动态关注度），不是稳态隐变量；范围 [0, ~5+]，无上界（可选 `cap` 截断）。
- **写入时衰减再累加**：先按距上次命中的天数衰减 stored 值，再加上本次 confidence。高频高置信节点累加上去，长期不命中节点自然下沉。
- **读取时再衰减一次**：召回排序看的是 effective 值，让"已经很久没被激活"的节点不会顽固压在前列。
- **origin 升级**：external 节点被 internal 证据命中后升级为 internal，不可降级。

边权重在召回时乘以独立的时间衰减因子（`max(floor, exp(-λ × days))`），长时间未强化的关系边影响力减弱。

#### 关键性质

| 性质 | 说明 |
|---|---|
| 自然无界（典型 0-5+）| 高频高置信节点可达 5-10，区分"老热点"和"近期升起" |
| 失活自动衰减 | 不命中即下沉，无需 GC |
| 单参数 λ | 沿用 0.01 / 半衰期 69 天 |
| 完全可 replay | 从 `backbone_activations` 表能精确重建任意时刻的 strength |

#### 阈值与排序权重（NODE_STRENGTH config）

`anchor_min` / `blindspot_min` 决定 agent 锚点 / 盲区扫描的下限；rank weights 决定召回排序时 strength / new_conf / rough_sim 的相对重要性。**默认值是基于 DWAS 数学的粗略估计，强烈建议在你真实数据上校准**：

1. 在 Pipeline tab 点 **"Replay node_strength"** → 看直方图
2. 取 p70-p80 作 `anchor_min`、p50-p60 作 `blindspot_min`
3. 改 `NODE_STRENGTH` config，重启服务

如果发现 strength 在召回排序中过度压制其他信号（高 strength 节点永远拍前），调小 `rank_strength_weight`（如 0.2）。

#### 为什么不是贝叶斯（vs profile_merge）

profile_merge 估计的是**稳态隐变量**（用户某维度的"真实值"），需要收敛。strength 反映的是**动态关注度**（recurring patterns），收敛反而是 bug —— 用户兴趣转移时该跟得上。两者数学范畴不同。

### Profile Merge（人格画像融合）

每条 entry 抽取出 (score, confidence) 后，通过**贝叶斯共轭递推**融合进 `profile_dimensions`。每个子维度独立维护后验 (μ, τ)，公式如下：

```
τ_obs = c²                      # 观测精度（c = LLM 置信度）
τ_new = γ × τ_old + τ_obs       # 遗忘因子衰减后累加
α     = τ_obs / τ_new           # 新观测的混合权重
μ_new = μ_old + α × (x − μ_old) # 后验均值递推
```

实现见 `app/lib/profile_merge.py`，参数在 `app/config/graph_rules.py:PROFILE_MERGE`。

#### 物理意义

- **τ（累积精度）**：替代了"样本数"的角色，但带置信度加权 —— 一条 c=0.9 的强信号贡献的 τ_obs (0.81) 比一条 c=0.3 的弱信号 (0.09) 大 9 倍。
- **γ（遗忘因子，0.98）**：等价于"假设画像每年漂移 ~5 分"的卡尔曼先验。τ 不会无限累加，稳态 τ_∞ = E[c²] / (1−γ) ≈ 12-15，使**画像追踪能力不会随使用时间衰减**。
- **τ_prior（虚拟先验，1.0）**：相当于"系统先天认为 score=midpoint 一条"，避免首条 entry 把分数拉到极端。
- **μ_0（先验均值）**：取自维度配置的 `score_range` 中点（0-100 维度即 50，0-1 维度即 0.5），无信息先验。

#### 关键性质

| 性质 | 数学表达 | 工程含义 |
|---|---|---|
| 稳态精度有界 | τ_∞ = E[c²] / (1−γ) | 不管用多久，新信号始终有 ~1% 权重，系统永远"愿意学" |
| 收敛性 | μ_n → E[x_t] (n→∞) | θ 不变时画像收敛到稳定值，不再震荡 |
| 漂移响应 | 半衰期 ≈ ln 2 / ln(1/γ) ≈ 34 entry | 真实人格慢漂移时，约 100 条 entry 内追上 |
| Scale 不变 | α 是无量纲精度比 | 同一公式适配任何 score_range 的新维度，零配置接入 |
| Sub-dim 独立 | 每个子维度独立 (μ, τ) | OCEAN 五维互不干扰；新增子维度从先验起步，已有不动 |

#### γ 的取舍

| γ | 半衰期 | 稳态等效样本 | 适用场景 |
|---|---|---|---|
| 1.00 | ∞ | ∞ | 假设画像绝对不变（数学上最强收敛，但越用越死） |
| **0.98** | **34** | **50** | **默认。允许慢漂移，与"画像每年变 ~5 分"对齐** |
| 0.95 | 14 | 20 | 响应快、稳态更抖；适合"频繁变化的状态量" |

#### 无信号语义（null vs low-confidence）

`extract.spt` 约定 LLM 对**无信号**的子维度返回 `null`，而不是用 `score=50, confidence=0.05` 这种"低置信占位"。融合层按优先级处理：

1. **`null`（首选）**：LLM 显式 abstain → 保留旧画像，不更新
2. **`min_conf` 兜底**：confidence < 0.15 的占位 → 同样保留旧画像（防 LLM 不守约定）

`slice_pipeline._normalize_extraction` 会把异常 schema（缺字段 / 错类型 / `{"abstain": true}` 之类）统一兜底为 `null`，避免污染贝叶斯递推。

#### Anchoring bias 的边界

LLM 抽取在弱信号时仍可能向 score=50 锚定（即使 prompt 要求返回 null）。`τ_obs = c²` 的二阶精度加权会**自然压制弱信号 hedged 观测的影响**，但无法完全消除偏差。`slice_pipeline._extraction_health` 把每条 entry 的 `null_count / low_conf_count / midpoint_hedge_count` 写入 trace，供观测和后续 prompt 调优。

#### 为什么不是简单移动平均

- 简单 EWMA：忽略观测置信度，弱信号和强信号一视同仁
- 旧公式（`1 + log(1+n)` freq_bonus）：增长太慢，500 条 entry 后单条仍能动 ~10%，**数学上不可能收敛**
- 贝叶斯共轭：精度加权 + γ 遗忘，是稳态隐变量估计的标准答案（等价于状态不变下的卡尔曼滤波）

### 召回机制

查询时通过四种方式从图谱召回节点：

| 方式 | 实现 | 用途 |
|------|------|------|
| `positive_retrieval` | 全库 cosine 相似度搜索 | 找到与问题语义最近的入口节点 |
| `expand_subgraph` | 沿 support/oppose/derive/similar 边多跳展开 | 探索节点周边知识结构 |
| `opposite_retrieval` | 沿 "对立" 边跳 1 跳 | 主动寻找认知张力和矛盾面 |
| `find_blindspots` | 找高 strength 但无对立边的节点 | 暴露认知盲区 |

Agent loop 最多 `MAX_EXPLORE_ROUNDS` 轮，LLM 自主决定何时停止探索。

### 上下文注入（多轮对话）

session_id 对应一个查询会话，服务端自动从 `query_logs.turns_json` 加载历史轮次，注入到所有 stage 的 prompt：

```
## 前几轮对话记录（请在此基础上深化，不要重复已有结论）
**第1轮** 用户问：... 回答要点：...
```

调用方只需传 `session_id`，history 由服务端闭环管理。新会话不传 session_id，服务端自动生成。

### 节点 Origin 语义

| origin | 含义 | 查询时权重 |
|--------|------|-----------|
| `internal` | 用户自身经验/思考中产生的节点 | 高，代表用户真实认知 |
| `external` | 引用的外部概念/框架/人物 | 低，代表知识边界 |

internal↔external 的边是认知边界区，探索价值最高。高 strength internal 节点无对立边 = 潜在认知盲区。

---

## 扩展：Dimension（人格画像维度）

```
app/config/dimensions/
  _template/    ← 复制此目录，改名，编辑三个文件
  ocean/
  schwartz/
  facts/
  situation/
```

| 文件 | 说明 |
|------|------|
| `config.py` | key / name / enabled / merge / summary_format 等元信息 |
| `extract.spt` | LLM 提取 prompt |
| `rubric.md` | 各子维度评分标准 |

`config.py` 关键字段：

```python
"enabled":        True,      # False = 软关闭，跳过该维度（不删数据）
"merge":          True,      # False = 只存 slice_features，不进 profile_dimensions
"summary_format": "scores",  # scores | key_value | skip | free
"sort_by_score":  True,
```

通过 CLI 维护（推荐，见下方 [配置管理 CLI](#配置管理-cli)）；也可手动 `cp -r _template/ my_dim/`。

---

## 扩展：Backbone Domain（知识图谱域）

```
app/config/backbones/
  _template/    ← 复制此目录，改名，编辑两个文件
  psychology/
  philosophy/
  history/
  business/
  science/
  technology/
```

| 文件 | 说明 |
|------|------|
| `config.py` | key / name / color / enabled / description / focus_hints |
| `node_extract.spt` | 内源节点提取 prompt |

通过 CLI 维护（推荐）；也可手动 `cp -r _template/ my_domain/`。

加 / 删 backbone 后**重启服务**生效；删除后旧 DB 节点保留为 orphan domain，启动日志会有 warning，仍可被 query 链路消费但新 entry 不再写入。

---

## 配置管理 CLI

`scripts/manage_config.py` 是 backbone / dimension 目录的统一管理脚本。两类对象命令完全对称。

```bash
# 列出所有 backbones / dimensions（含 key / name / 状态）
python3 -m scripts.manage_config backbone  list
python3 -m scripts.manage_config dimension list

# 新增（基于 _template 复制目录，自动改写 key / name 字段）
python3 -m scripts.manage_config backbone  add economics --name "Economics"
python3 -m scripts.manage_config dimension add curiosity --name "Curiosity"

# 软关 / 软开（修改 config.py 的 enabled 字段，不动文件不动 DB）
python3 -m scripts.manage_config backbone  disable history
python3 -m scripts.manage_config backbone  enable  history

# 硬删（二次确认；目录与 prompt 文件全删；DB 中旧节点保留为 orphan）
python3 -m scripts.manage_config backbone  remove history
python3 -m scripts.manage_config dimension remove curiosity --force   # 跳过确认
```

约束：
- `key` 必须 `[a-z][a-z0-9_]*`，会作为 DB enum 写入。
- `add` 后仍需手工编辑 prompt 文件（`node_extract.spt` / `extract.spt` / `rubric.md`），把 `[DOMAIN NAME]` 等占位替换成实际域内容。
- 所有操作仅改文件系统，**改完需要重启 Engram API 才会生效**（loader 启动时一次性装载）。

---

## 数据持久化

| 位置 | 内容 |
|------|------|
| `data/cognitive.db` | SQLite，所有结构化数据（entries、图谱、画像、查询历史） |
| `data/vectors/` | 节点 embedding（用于 positive_retrieval） |

Docker 部署时 `data/` 对应宿主机 `./data/cognitive/`（bind mount，容器重建不丢数据）。

**核心资产**：`data/cognitive/` 全部内容。图谱节点、画像、查询历史均为累积结果，无法从原始 entries 完整重建，必须整体保护。备份方式见根目录 `backup.sh`。

---

## 数据库表

| 表 | 说明 |
|----|------|
| `entries` | 原始输入，含 embedding vector_id、mood、memory_type |
| `slices` | per-entry 切片记录（不可变） |
| `slice_features` | 各 dimension 提取结果 |
| `profile_dimensions` | 持久化融合画像（merge=True 的维度加权累积） |
| `backbone_nodes` | 知识图谱节点（domain/label/strength/hit_count/origin） |
| `backbone_edges` | 节点间关系（support/oppose/derive/similar，含 weight） |
| `backbone_activations` | 节点激活历史 |
| `query_logs` | 查询历史（session_id / turns_json / q1–q4 全文） |
| `pipeline_traces` | 管线各阶段执行记录 |
| `profile_snapshots` | 画像快照（历史存档） |

---

## 环境变量

通用 OpenAI 兼容接入，三个变量搞定：

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
EMBED_MODEL=text-embedding-3-small   # 默认沿用 LLM_BASE_URL / LLM_API_KEY
DB_PATH=./data/cognitive.db
VECTOR_INDEX_PATH=./data/vectors
```

或用预设（无需记 base_url）：

```bash
LLM_PROVIDER=anthropic|openai|gemini|grok|openrouter|deepseek|moonshot|qwen|glm|minimax|ark|ollama
LLM_API_KEY=...
# LLM_MODEL=...    # 可选，覆盖预设默认模型
```

完整选项见根目录 [README.zh.md](../README.zh.md#配置) 的 Configuration 章节。

---

## 启动

```bash
# 本地开发（直接跑，数据在 ../data/cognitive/）
cd api
PYTHONPATH=.. uvicorn app.main:app --reload --port 18080

# Docker（推荐，数据在根目录 data/cognitive/）
cd deploy && docker compose up api
```

---

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/capture` | 写入原始记忆，自动 embed |
| POST | `/entries/{id}/process` | 触发 slice + backbone 管线 |
| POST | `/import/entries` | 批量导入历史 entries（保留原始时间戳） |
| POST | `/query` | 消费查询，NDJSON 流式响应 |
| GET  | `/query/latest-session` | 返回最近 session_id，供续接上次对话 |
| GET  | `/ui/api/stats` | 各表数量统计 |
| GET  | `/ui/api/entries` | entries 列表（limit/offset） |
| GET  | `/ui/api/entry/{id}` | 单条 entry 详情 |
| DELETE | `/ui/api/entry/{id}` | 删除 entry 及衍生数据 |
| GET  | `/ui/api/graph?domain=` | 知识图谱（Cytoscape 格式） |
| GET  | `/ui/api/profile` | 持久化用户画像 |
| GET  | `/ui/api/query-logs` | 查询历史列表 |
| GET  | `/ui/api/query-logs/{id}` | 查询历史详情 |
| GET  | `/ui/api/export` | 导出全量 entries（JSON） |
| POST | `/ui/api/admin/reset` | 清空数据（scope=derived\|all，需 confirm=yes） |
| POST | `/ui/api/admin/process-pending` | 处理所有待 process 的 entries |
| GET  | `/health` | 健康检查 |

`/query` 请求体：

```json
{
  "question": "...",
  "mode": "full | fast",
  "session_id": "uuid（可选，不传则开新会话）"
}
```

---

## 运维脚本

```bash
# 数据概览
python3 scripts/inspect_memory.py overview

# 查看最近 entries
python3 scripts/inspect_memory.py entries --limit 20

# 查看持久化画像
python3 scripts/inspect_memory.py profile

# 查看 backbone 节点
python3 scripts/inspect_memory.py nodes --domain psychology --limit 20

# 查看某域图谱（ASCII 邻接表）
python3 scripts/inspect_memory.py graph --domain business

# 导出 raw entries（备份）
python3 scripts/export_raw_entries.py --output data/backup_$(date +%F).json

# 清空衍生数据，保留原始 entries
python3 scripts/reset_data.py --scope derived --yes

# 清空全部数据（含 entries）
python3 scripts/reset_data.py --scope all --yes

# 删除指定 entry 及其 slice 数据
python3 scripts/delete_entry.py --entry-id 12 --yes
```
