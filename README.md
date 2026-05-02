# Engram

**English** · [中文](README.zh.md)

> A personal cognitive graph that models who you are, not just what you said.

Engram is a self-building memory system for AI assistants. As you capture thoughts, reflections, and observations over time, Engram constructs a structured personality profile and knowledge graph — so your AI tools can give genuinely personalized responses, not just recall what you typed last week.

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
Your notes / voice / chat
         ↓
   [ capture ]          Intent gate → entry / memo / buffer
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

### Claude Code / Cursor

```bash
cd cognitive-mcp
pnpm install
pnpm build
```

Add to `~/.claude/settings.json` (Claude Code) or `~/.cursor/mcp.json` (Cursor):

```json
{
  "mcpServers": {
    "engram": {
      "command": "node",
      "args": ["/path/to/engram/cognitive-mcp/dist/index.js"],
      "env": {
        "ENGRAM_SERVICE_URL": "http://127.0.0.1:18080"
      }
    }
  }
}
```

Two tools become available in your AI assistant:
- **`cognitive_capture_memory`** — capture a thought, reflection, or observation
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
