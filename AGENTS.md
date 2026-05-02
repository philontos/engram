# Repo rules for AI coding agents

This file is read by Claude Code, Cursor, Codex, Copilot, and other agents that follow the [agents.md](https://agents.md) convention. Human contributors should follow the same rules.

## Project layout

- `cognitive-service/` — Python (FastAPI) backend + React (Vite) frontend.
- `cognitive-mcp/` — MCP server for Claude Code / Cursor.
- `cognitive-openclaw/` — OpenClaw plugin.
- `shared/` — shared LLM client.

## Hard rules (apply everywhere)

1. **Canonical enums are English.** `domain`, `node_type`, `relation_type` in code, prompts, configs, and DB are always English (`psychology`, `concept`, `opposes`, …). Chinese display is a presentation concern handled by i18n on the frontend. Never write Chinese enum literals into Python source, prompts, configs, or DB schemas.
2. **Backend prompts default to English.** Built-in `app/config/backbones/*` and `app/config/dimensions/*` prompt templates are written in English. LLMs are instructed to "match the user's language" — do not pin output language in prompts (no "in Chinese" / "X Chinese characters" / "X English words" wording). User-extended backbones / dimensions can be any language; defaults stay English.
3. **Restart-required config is OK.** Backbone / dimension loaders run at module import; adding or toggling a backbone via `scripts/manage_config.py` requires a service restart. Don't paper over this with hot-reload heuristics.
4. **Migration files are forward-only and idempotent.** New SQL migrations live in `cognitive-service/migrations/`. Never re-edit a committed migration; add a new one.

## Sub-rules per area

- Frontend i18n: read [`cognitive-service/frontend/AGENTS.md`](cognitive-service/frontend/AGENTS.md). Any user-visible string must come from `useI18n().t(...)`.
- Backbone / dimension extension: use `python -m scripts.manage_config <kind> {list,add,disable,enable,remove}` rather than hand-editing directories. Doc: `cognitive-service/README.md`.

## Style

- Follow existing structure rather than introducing new patterns. If you find yourself copying boilerplate from a different file, that's usually fine; if you find yourself inventing a new pattern, ask first.
- No emojis in code or commits unless the user explicitly asks.
- Code comments: only when the *why* is non-obvious. Don't narrate *what*.
