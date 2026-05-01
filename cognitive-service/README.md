# cognitive-service

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

### 节点 Strength 衰减

每次 entry 命中某节点时，strength 按以下公式更新：

```
time_decay  = exp(-λ × days_since_last_hit)
freq_bonus  = 1 + log(1 + hit_count)
hist_weight = time_decay × freq_bonus
alpha       = new_conf / (hist_weight × old_strength + new_conf)
new_strength = (1 - alpha) × old_strength + alpha × new_conf
```

- **时间衰减**：长时间未触达的节点历史权重下降，新证据影响力增大
- **频次加成**：频繁触达的节点历史权重更大，不易被单次新证据覆盖
- **origin 升级**：external 节点被 internal 证据命中后升级为 internal，不可降级

边权重在召回时乘以独立的时间衰减因子（`max(floor, exp(-λ × days))`），长时间未强化的关系边影响力减弱。

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

新增：

```bash
cp -r app/config/dimensions/_template app/config/dimensions/my_dim
```

| 文件 | 说明 |
|------|------|
| `config.py` | key / name / merge / summary_format 等元信息 |
| `extract.spt` | LLM 提取 prompt |
| `rubric.md` | 各子维度评分标准 |

`config.py` 关键字段：

```python
"merge":          True,      # False = 只存 slice_features，不进 profile_dimensions
"summary_format": "scores",  # scores | key_value | skip | free
"sort_by_score":  True,
```

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

新增：

```bash
cp -r app/config/backbones/_template app/config/backbones/my_domain
```

| 文件 | 说明 |
|------|------|
| `config.py` | key / description / focus_hints |
| `node_extract.spt` | 内源节点提取 prompt |

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

```bash
STRUCTURED_LLM_PROVIDER=ark|moonshot|deepseek|minimax
ARK_API_KEY=...
DOUBAO_EMBED_MODEL=...        # 豆包 Embedding endpoint
ARK_TEXT_MODEL=...
MOONSHOT_API_KEY=...
DEEPSEEK_API_KEY=...
MINIMAX_TEXT_API_KEY=...
DB_PATH=./data/cognitive.db
VECTOR_INDEX_PATH=./data/vectors
```

---

## 启动

```bash
# 本地开发（直接跑，数据在 cognitive-service/data/）
cd cognitive-service
PYTHONPATH=.. uvicorn app.main:app --reload --port 18080

# Docker（推荐，数据在根目录 data/cognitive/）
docker compose up cognitive
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
