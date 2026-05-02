# Engram

[English](README.md) · **中文**

> 把你的"思考"映射出来。Engram 让 AI 终于能看见你的*思维结构*，而不是只看见你的字。

Engram 只收一种东西：你日常的思考内容——想法、反思、洞察、决策、自我观察。它把这些累积成一份结构化的人格画像 + 知识图谱。一段时间后，你的 AI 工具不再是在"回复你的消息"，而是在"回应你这个人"。

**Engram 不是笔记 app。** 别用它记"今天午饭吃了什么"。用它捕捉那些你正在思考、犹豫、决定、意识到的瞬间。纯事件流水会在意图门被礼貌挡回。

---

## Engram 与众不同

大多数 AI 记忆系统是检索层：存文本、搜文本。Engram 是建模层——它在建模"你"。

| 能力 | Engram | mem0 / Letta / Zep |
|------|--------|--------------------|
| 人格画像（OCEAN + Schwartz 价值观） | ✅ | ❌ |
| 带时间衰减的知识图谱 | ✅ | ❌ |
| 单条 entry 的情境上下文分析 | ✅ | ❌ |
| 精确的 LIFO 撤销（图状态回滚） | ✅ | ❌ |
| 可扩展的维度系统 | ✅ | ❌ |
| 兼容 MCP（Claude Code、Cursor 等） | ✅ | 部分 |

---

## 工作原理

```
你写下/说出/发送的一段思考
         ↓
   [ 捕获 ]              意图门：接受思考，拒绝纯事件流水
         ↓
   [ 切片管线 ]          抽取 OCEAN、Schwartz 价值观、情境上下文
         ↓
   [ 主干图 ]            构建知识节点 + 边，应用时间衰减
         ↓
   [ 画像融合 ]          沿时间累积人格维度
         ↓
   [ 查询 ]              基于完整认知图谱回答问题
```

每条 entry 都贡献信号。画像在演化，图谱在变密。数月后，Engram 拥有一份关于你的价值观、信念、模式与盲区的完整模型——并把它开放给你使用的任意 AI 工具。

---

## 快速开始

```bash
git clone https://github.com/your-username/engram.git
cd engram

# 配置 LLM API 密钥
cp cognitive-service/.env.example cognitive-service/.env
# 编辑 cognitive-service/.env：填写 ARK_API_KEY、ARK_TEXT_MODEL、ARK_EMBEDDING_MODEL

# 构建 Dashboard 前端
pnpm --prefix cognitive-service/frontend install
pnpm --prefix cognitive-service/frontend run build

# 启动服务
docker compose up -d --build
```

服务启动在 `http://localhost:18080`。  
Dashboard UI 在 `http://localhost:18080/`。

---

## 接入到你的 AI 工具

MCP server 是一层薄薄的 stdio 桥接：AI 客户端按需把它 fork 为子进程，子进程再通过 HTTP 把工具调用转给跑在 `localhost:18080` 的 cognitive-service。构建一次，所有客户端都指向同一个 `dist/index.js`。

### 构建 MCP server

```bash
cd cognitive-mcp
pnpm install
pnpm build
# 产物：cognitive-mcp/dist/index.js
```

> 改了 MCP 源码后必须重新 `pnpm build`，并让客户端重连（或重启）以加载新产物。

### Claude Code

推荐用 CLI（避免手动改 JSON 写错路径）：

```bash
claude mcp add engram --scope user \
  --env ENGRAM_SERVICE_URL=http://127.0.0.1:18080 \
  -- node /绝对路径/engram/cognitive-mcp/dist/index.js
```

或者直接编辑 `~/.claude.json`，在顶层 `mcpServers` 下加：

```json
{
  "mcpServers": {
    "engram": {
      "command": "node",
      "args": ["/绝对路径/engram/cognitive-mcp/dist/index.js"],
      "env": { "ENGRAM_SERVICE_URL": "http://127.0.0.1:18080" }
    }
  }
}
```

验证：在 Claude Code 里输入 `/mcp`，`engram` 应显示 **connected**。

### Cursor

编辑 `~/.cursor/mcp.json`（项目级则放仓库根目录的 `.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "engram": {
      "command": "node",
      "args": ["/绝对路径/engram/cognitive-mcp/dist/index.js"],
      "env": { "ENGRAM_SERVICE_URL": "http://127.0.0.1:18080" }
    }
  }
}
```

验证：Cursor → Settings → MCP，`engram` 一行应该有绿点。

### Codex CLI

编辑 `~/.codex/config.toml`（注意是 TOML，不是 JSON）：

```toml
[mcp_servers.engram]
command = "node"
args = ["/绝对路径/engram/cognitive-mcp/dist/index.js"]

[mcp_servers.engram.env]
ENGRAM_SERVICE_URL = "http://127.0.0.1:18080"
```

验证：`codex mcp list` 应能看到 `engram`。

### 暴露的工具

以上任意一个客户端连通后，都会拿到这两个工具：
- **`cognitive_capture_thought`** — 捕获一段想法、反思、灵感或观察（事件/事实日志会在 intent gate 被拒）
- **`cognitive_query`** — 基于你的完整认知画像发起查询

### OpenClaw

```bash
cd cognitive-openclaw
# 按 OpenClaw 的配置方式作为插件加载
```

---

## 项目结构

```
engram/
  cognitive-service/     # 核心后端 — FastAPI、SQLite、HNSWLIB
    app/
      config/
        dimensions/      # 画像维度：OCEAN、Schwartz、facts
        entry_analyzers/ # 单条 entry 分析器：情境上下文
        backbones/       # 知识图谱域
      lib/               # 管线：slice / backbone / profile merge / query
      routes/            # HTTP API
    frontend/            # Dashboard UI（React + Vite）
  cognitive-mcp/         # MCP 服务器 — Claude Code、Cursor 等
  cognitive-openclaw/    # OpenClaw 插件
  shared/                # 共享 LLM 客户端
```

---

## 核心概念

**Dimension（画像维度）** — 沿时间累积的画像维度。OCEAN（大五人格）与 Schwartz 价值观是内置维度。在 `config/dimensions/` 下放一个目录就能加新维度。

**Entry analyzer（条目分析器）** — 仅对单条 entry 进行标注，不影响画像。情境上下文（时间视角、压力等级等）是内置分析器。它们帮管线对每条 entry 调整处理方式。

**Backbone graph（主干图）** — 从 entry 中抽取出的概念、信念、关系所构成的知识图谱。节点未被强化时会随时间衰减；边在多次共现中加强。

**LIFO Revert（按序撤销）** — 每条已处理 entry 都记录回滚快照。可按写入顺序撤销，将图谱与画像还原到任意历史状态——非常适合清理低质捕获或语音识别错误。

---

## 配置

### LLM

Engram 用 OpenAI 兼容 API 调用所有 LLM。在 `cognitive-service/.env` 配置：

```env
ARK_API_KEY=your_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_TEXT_MODEL=your_model_id
ARK_EMBEDDING_MODEL=your_embedding_model_id
```

任何 OpenAI 兼容端点都可（OpenAI、DeepSeek、本地 Ollama 等）。

### 添加维度

在 `cognitive-service/app/config/dimensions/my_dim/` 创建：

```
my_dim/
  config.py      # DIMENSION = { "key": "my_dim", ... }
  extract.spt    # 抽取 prompt 模板
  rubric.md      # 评分标准（可选）
```

下次启动时会被自动发现，无需改代码。

---

## 协议

MIT
