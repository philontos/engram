# cognitive-service

**English** · [中文](README.md)

Personal cognitive memory system. Turns raw input into a personality profile + knowledge graph and supports multi-turn personalized query consumption.

## Architecture

Two independent pipelines:

**Write pipeline (capture → process)**

```
POST /capture
  └─ embed(raw) → entries + vector_store

POST /entries/{id}/process
  ├─ slice_pipeline           dimension slicing → profile_dimensions (OCEAN / Schwartz / facts / situation)
  └─ backbone_pipeline
       Stage 1  Activation     activation weight (0–1) per knowledge domain
       Stage 2  Rough recall   embed(raw) → vector top-30 over existing nodes
       Stage 3  Node Extract   per-domain LLM (parallel) extracts candidate nodes (internal + external)
       Stage 4  Resolution     intra-domain dedup (≥0.92 merged); record cross-domain similar pairs
       Stage 5  Fine recall    per-node 3-hop / 1-hop subgraph expansion
       Stage 6  Edge Extract   per-domain LLM writes edges; algorithmic weight fusion
       Stage 7  Cross-domain   write similar edges across the pairs recorded in Stage 4
```

**Read pipeline (query)**

```
POST /query
  ├─ Load conversation history from DB (server-side; caller only passes session_id)
  ├─ Stage 1  Intent Check    intent classification (proceed / clarify / off_topic)
  ├─ Stage 2  Baseline (Q1)   generic answer (full mode)
  ├─ Stage 3  Persona (Q2)    personality lens with profile injection (full mode)
  ├─ Stage 4  Graph Explore   agent loop, multi-round tool calls over the graph
  │             graph_search     semantic search for entry nodes
  │             expand_node      expand subgraph along relation edges
  │             get_opposites    surface opposing / contradictory nodes
  ├─ Stage 5  Theme Analysis  deep-dive on high-strength nodes against linked raw entries
  └─ Stage 6  Synthesis       stream the final graph insight based on all of the above
```

Response format: NDJSON streaming, one JSON event per line (`stage` / `delta` / `tool_call` / `done`).

## Core mechanics

### Node strength decay

When an entry hits a node, its strength updates as:

```
time_decay  = exp(-λ × days_since_last_hit)
freq_bonus  = 1 + log(1 + hit_count)
hist_weight = time_decay × freq_bonus
alpha       = new_conf / (hist_weight × old_strength + new_conf)
new_strength = (1 - alpha) × old_strength + alpha × new_conf
```

- **Time decay**: nodes untouched for a long time lose historical weight; new evidence gains influence.
- **Frequency bonus**: frequently-touched nodes carry more historical weight and resist single-shot overwrites.
- **Origin upgrade**: an `external` node hit by `internal` evidence is upgraded to `internal`; never demoted back.

Edge weights are also multiplied by an independent time-decay factor at recall time (`max(floor, exp(-λ × days))`) — long-unreinforced edges fade in influence.

### Recall mechanics

At query time, four strategies pull nodes from the graph:

| Strategy | Implementation | Purpose |
|----------|----------------|---------|
| `positive_retrieval` | Global cosine similarity search | Find entry nodes semantically closest to the question |
| `expand_subgraph` | Multi-hop walk along supports / opposes / derives / similar edges | Explore knowledge structure around a node |
| `opposite_retrieval` | One-hop walk along `opposes` edges | Surface cognitive tension / contradictions |
| `find_blindspots` | High-strength nodes with zero opposing edges | Reveal cognitive blind spots |

The agent loop runs at most `MAX_EXPLORE_ROUNDS` rounds; the LLM decides when to stop.

### Context injection (multi-turn)

A `session_id` corresponds to one query session. The server auto-loads prior turns from `query_logs.turns_json` and injects them into every stage's prompt:

```
## Prior conversation turns (build on these — do not repeat conclusions)
**Turn 1** User asked: ... Answer summary: ...
```

Callers only pass `session_id`; history is closed-loop on the server. New session: omit `session_id` and the server generates one.

### Node origin semantics

| origin | Meaning | Weight at query time |
|--------|---------|----------------------|
| `internal` | Node generated from the user's own experience / thinking | High — represents the user's actual cognition |
| `external` | Referenced external concept / framework / figure | Low — represents the cognitive boundary |

Internal↔external edges define the cognitive boundary zone — the highest-value exploration target. A high-strength internal node with no opposing edge is a potential blind spot.

---

## Extension: Dimension (profile dimensions)

```
app/config/dimensions/
  _template/    ← copy this directory, rename it, edit three files
  ocean/
  schwartz/
  facts/
  situation/
```

| File | Purpose |
|------|---------|
| `config.py` | metadata: key / name / enabled / merge / summary_format etc. |
| `extract.spt` | LLM extraction prompt |
| `rubric.md` | scoring rubric for sub-dimensions |

`config.py` key fields:

```python
"enabled":        True,      # False = soft-disable; skip this dimension (data is preserved)
"merge":          True,      # False = stored only in slice_features, never merged into profile_dimensions
"summary_format": "scores",  # scores | key_value | skip | free
"sort_by_score":  True,
```

Maintain via the CLI (recommended — see [Config CLI](#config-management-cli)); or manually `cp -r _template/ my_dim/`.

---

## Extension: Backbone Domain (knowledge graph domain)

```
app/config/backbones/
  _template/    ← copy this directory, rename it, edit two files
  psychology/
  philosophy/
  history/
  business/
  science/
  technology/
```

| File | Purpose |
|------|---------|
| `config.py` | key / name / color / enabled / description / focus_hints |
| `node_extract.spt` | internal node extraction prompt |

Maintain via the CLI (recommended); or manually `cp -r _template/ my_domain/`.

After adding / removing a backbone, **restart the service** for changes to take effect. After removal, existing DB nodes remain as orphan domains — a startup warning surfaces them, query pipelines still consume them, but new entries never write to them again.

---

## Config management CLI

`scripts/manage_config.py` is a single script that manages backbone / dimension directories. Commands are symmetric across the two object kinds.

```bash
# List all backbones / dimensions (with key / name / status)
python3 -m scripts.manage_config backbone  list
python3 -m scripts.manage_config dimension list

# Create new (copies from _template, auto-rewrites the key + name fields)
python3 -m scripts.manage_config backbone  add economics --name "Economics"
python3 -m scripts.manage_config dimension add curiosity --name "Curiosity"

# Soft toggle (flips the enabled field in config.py; no file or DB changes)
python3 -m scripts.manage_config backbone  disable history
python3 -m scripts.manage_config backbone  enable  history

# Hard delete (two-step confirmation; entire directory removed; DB nodes kept as orphans)
python3 -m scripts.manage_config backbone  remove history
python3 -m scripts.manage_config dimension remove curiosity --force   # skip confirmation
```

Constraints:
- `key` must match `[a-z][a-z0-9_]*`; written as the DB enum value.
- After `add`, you still need to edit the prompt files (`node_extract.spt` / `extract.spt` / `rubric.md`) to replace `[DOMAIN NAME]` etc. placeholders with real content.
- All operations are filesystem-only; **restart the cognitive-service for changes to take effect** (the loader does a one-shot module-level load at startup).

---

## Persistence

| Path | Content |
|------|---------|
| `data/cognitive.db` | SQLite — all structured data (entries, graph, profile, query history) |
| `data/vectors/` | Node embeddings (used by positive_retrieval) |

In Docker, `data/` is bind-mounted from the host's `./data/cognitive/`, so container rebuilds don't lose data.

**Critical assets**: everything under `data/cognitive/`. Graph nodes, profile, and query history accumulate; they cannot be fully reconstructed from raw entries and must be backed up as a whole. See `backup.sh` at the repo root.

---

## Tables

| Table | Purpose |
|-------|---------|
| `entries` | Raw input, plus embedding vector_id, mood, memory_type |
| `slices` | per-entry slice records (immutable) |
| `slice_features` | per-dimension extraction output |
| `profile_dimensions` | accumulated profile (weighted merge for `merge=True` dimensions) |
| `backbone_nodes` | graph nodes (domain / label / strength / hit_count / origin) |
| `backbone_edges` | relations between nodes (supports / opposes / derives / similar / related, with weight) |
| `backbone_activations` | node activation history |
| `query_logs` | query history (session_id / turns_json / q1–q4 full text) |
| `pipeline_traces` | per-stage execution traces |
| `profile_snapshots` | profile snapshots (historical archive) |

---

## Environment variables

Universal OpenAI-compatible interface — three variables and you're done:

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
EMBED_MODEL=text-embedding-3-small   # falls back to LLM_BASE_URL / LLM_API_KEY
DB_PATH=./data/cognitive.db
VECTOR_INDEX_PATH=./data/vectors
```

Or pick a preset (no base_url to remember):

```bash
LLM_PROVIDER=openai|anthropic|gemini|grok|openrouter|deepseek|moonshot|qwen|glm|minimax|ark|ollama
LLM_API_KEY=...
# LLM_MODEL=...    # optional, override preset's default model
```

See the full provider matrix in the root [README.md](../README.md#configuration).

---

## Running

```bash
# Local dev (run directly; data lands in cognitive-service/data/)
cd cognitive-service
PYTHONPATH=.. uvicorn app.main:app --reload --port 18080

# Docker (recommended; data lands in repo-root data/cognitive/)
docker compose up cognitive
```

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/capture` | Write a raw memory; auto-embed |
| POST | `/entries/{id}/process` | Trigger slice + backbone pipeline |
| POST | `/import/entries` | Batch import historical entries (preserves timestamps) |
| POST | `/query` | Consume query, NDJSON streaming response |
| GET  | `/query/latest-session` | Latest session_id, useful for resuming |
| GET  | `/ui/api/stats` | Per-table counts |
| GET  | `/ui/api/entries` | Entries list (limit/offset) |
| GET  | `/ui/api/entry/{id}` | Single entry detail |
| DELETE | `/ui/api/entry/{id}` | Delete an entry and its derived data |
| GET  | `/ui/api/graph?domain=` | Knowledge graph (Cytoscape format) |
| GET  | `/ui/api/profile` | Persistent user profile |
| GET  | `/ui/api/backbones` | Backbone catalog (drives frontend filters) |
| GET  | `/ui/api/dimensions` | Dimension catalog |
| GET  | `/ui/api/query-logs` | Query history list |
| GET  | `/ui/api/query-logs/{id}` | Query history detail |
| GET  | `/ui/api/export` | Export all entries (JSON) |
| POST | `/ui/api/admin/reset` | Clear data (scope=derived\|all, requires confirm=yes) |
| POST | `/ui/api/admin/process-pending` | Process all pending entries |
| GET  | `/health` | Health check |

`/query` request body:

```json
{
  "question": "...",
  "mode": "full | fast",
  "session_id": "uuid (optional; omit for a new session)"
}
```

---

## Maintenance scripts

```bash
# Data overview
python3 scripts/inspect_memory.py overview

# Recent entries
python3 scripts/inspect_memory.py entries --limit 20

# Persistent profile
python3 scripts/inspect_memory.py profile

# Backbone nodes
python3 scripts/inspect_memory.py nodes --domain psychology --limit 20

# Per-domain graph (ASCII adjacency)
python3 scripts/inspect_memory.py graph --domain business

# Export raw entries (backup)
python3 scripts/export_raw_entries.py --output data/backup_$(date +%F).json

# Clear derived data, keep raw entries
python3 scripts/reset_data.py --scope derived --yes

# Clear everything (including entries)
python3 scripts/reset_data.py --scope all --yes

# Delete a specific entry and its slice data
python3 scripts/delete_entry.py --entry-id 12 --yes
```
