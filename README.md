# Engram

**English** · [中文](README.zh.md)

> Your thoughts, mapped. Engram turns the way you *think* into a structure your AI can finally see.

Engram captures the cognitive content of your day — thoughts, reflections, ideas, decisions, observations — and builds a structured personality profile + knowledge graph from them. Over time, your AI tools stop replying to your messages and start replying to *you*.

**Engram is not a notes app.** Don't use it to log what you ate for lunch. Use it when you catch yourself thinking, doubting, deciding, realizing. Pure factual logs are politely declined at the gate.

---

## Why Engram is different

Most AI memory systems are retrieval layers: store text, search text. Engram builds a model of *you*.

| Feature | Engram | mem0 / Letta / Zep |
|---------|--------|-------------------|
| Personality profiling (OCEAN + Schwartz values) | ✅ | ❌ |
| Knowledge graph with time-decay | ✅ | ❌ |
| Per-entry situational context analysis | ✅ | ❌ |
| Precision LIFO revert (rollback graph state) | ✅ | ❌ |
| Extensible dimension system | ✅ | ❌ |
| MCP compatible (Claude Code, Cursor, etc.) | ✅ | partial |

---

## How it works

```
A thought you typed / spoke / messaged
         ↓
   [ capture ]          Intent gate accepts thoughts; rejects pure event logs
         ↓
   [ slice pipeline ]   Extract OCEAN, Schwartz values, situational context
         ↓
   [ backbone graph ]   Build knowledge nodes + edges, apply time-decay
         ↓
   [ profile merge ]    Accumulate personality dimensions over time
         ↓
   [ query ]            Answer questions using your full cognitive graph
```

Every entry contributes signals. Your profile evolves. The graph grows denser. Over months, Engram builds a model of your values, beliefs, patterns, and blind spots — and makes that available to any AI tool you use.

---

## Quick start

```bash
git clone https://github.com/your-username/engram.git
cd engram

# Configure your LLM API key
cp cognitive-service/.env.example cognitive-service/.env
# Edit cognitive-service/.env: set ARK_API_KEY, ARK_TEXT_MODEL, ARK_EMBEDDING_MODEL

# Build the dashboard UI
pnpm --prefix cognitive-service/frontend install
pnpm --prefix cognitive-service/frontend run build

# Start the service
docker compose up -d --build
```

The cognitive service starts at `http://localhost:18080`.  
The dashboard UI is at `http://localhost:18080/`.

---

## Connect to your AI tool

The MCP server is a thin stdio bridge. Your AI client spawns it as a subprocess on demand; it forwards tool calls over HTTP to the cognitive-service running on `localhost:18080`. Build it once, then point each client at the same `dist/index.js`.

### Build the MCP server

```bash
cd cognitive-mcp
pnpm install
pnpm build
# produces cognitive-mcp/dist/index.js
```

> Re-run `pnpm build` whenever you change MCP source. Restart the client (or reconnect the server) so it picks up the new binary.

### Claude Code

Use the CLI (recommended — avoids hand-editing JSON):

```bash
claude mcp add engram --scope user \
  --env ENGRAM_SERVICE_URL=http://127.0.0.1:18080 \
  -- node /absolute/path/to/engram/cognitive-mcp/dist/index.js
```

Or edit `~/.claude.json` directly and add under the top-level `mcpServers` key:

```json
{
  "mcpServers": {
    "engram": {
      "command": "node",
      "args": ["/absolute/path/to/engram/cognitive-mcp/dist/index.js"],
      "env": { "ENGRAM_SERVICE_URL": "http://127.0.0.1:18080" }
    }
  }
}
```

Verify: run `/mcp` inside Claude Code — `engram` should show **connected**.

### Cursor

Edit `~/.cursor/mcp.json` (project-scoped: `.cursor/mcp.json` in repo root):

```json
{
  "mcpServers": {
    "engram": {
      "command": "node",
      "args": ["/absolute/path/to/engram/cognitive-mcp/dist/index.js"],
      "env": { "ENGRAM_SERVICE_URL": "http://127.0.0.1:18080" }
    }
  }
}
```

Verify: Cursor → Settings → MCP — `engram` row should show a green dot.

### Codex CLI

Edit `~/.codex/config.toml` (TOML, not JSON):

```toml
[mcp_servers.engram]
command = "node"
args = ["/absolute/path/to/engram/cognitive-mcp/dist/index.js"]

[mcp_servers.engram.env]
ENGRAM_SERVICE_URL = "http://127.0.0.1:18080"
```

Verify: `codex mcp list` should show `engram`.

### Tools exposed

Two tools become available in any of the clients above:
- **`cognitive_capture_thought`** — capture a thought, reflection, idea, or observation (event/fact logs are rejected at the intent gate)
- **`cognitive_query`** — ask a question using your full cognitive profile

### OpenClaw

```bash
cd cognitive-openclaw
# link as an OpenClaw plugin per your openclaw config
```

---

## Project structure

```
engram/
  cognitive-service/     # Core backend — FastAPI, SQLite, HNSWLIB
    app/
      config/
        dimensions/      # Profile dimensions: OCEAN, Schwartz, facts
        entry_analyzers/ # Per-entry analyzers: situational context
        backbones/       # Knowledge graph domains
      lib/               # Pipelines: slice, backbone, profile merge, query
      routes/            # HTTP API
    frontend/            # Dashboard UI (React + Vite)
  cognitive-mcp/         # MCP server — Claude Code, Cursor, etc.
  cognitive-openclaw/    # OpenClaw plugin
  shared/                # Shared LLM client
```

---

## Key concepts

**Dimensions** — Profile dimensions that accumulate over time. OCEAN (Big Five personality) and Schwartz values are built-in. Add your own by dropping a directory into `config/dimensions/`.

**Entry analyzers** — Per-entry annotations that don't affect the profile. Situational context (temporal frame, pressure level, etc.) is built-in. These help the pipeline adjust how it processes each entry.

**Backbone graph** — A knowledge graph of concepts, beliefs, and relationships extracted from your entries. Nodes decay over time if not reinforced; edges strengthen with repeated co-occurrence.

**LIFO revert** — Every processed entry records a rollback snapshot. You can revert entries in order, restoring the graph and profile to any prior state — useful for cleaning up bad captures or ASR errors.

---

## Configuration

### LLM

Engram uses an OpenAI-compatible API for all LLM calls. Configure in `cognitive-service/.env`:

```env
ARK_API_KEY=your_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_TEXT_MODEL=your_model_id
ARK_EMBEDDING_MODEL=your_embedding_model_id
```

Any OpenAI-compatible endpoint works (OpenAI, DeepSeek, local Ollama, etc.).

### Adding a dimension

Create `cognitive-service/app/config/dimensions/my_dim/`:

```
my_dim/
  config.py      # DIMENSION = { "key": "my_dim", ... }
  extract.spt    # Extraction prompt template
  rubric.md      # Scoring rubric (optional)
```

The dimension is auto-discovered on next startup. No code changes required.

---

## License

MIT
