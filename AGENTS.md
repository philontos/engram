# Repo rules for AI coding agents

This file is read by Claude Code, Cursor, Codex, Copilot, and other agents that follow the [agents.md](https://agents.md) convention. Human contributors should follow the same rules.

## Project layout

- `api/` and `web/` — Python (FastAPI) backend + React (Vite) frontend.
- `cognitive-mcp/` — MCP server for Claude Code / Cursor.
- `cognitive-openclaw/` — OpenClaw plugin.
- `shared/` — shared LLM client.

## Product context

- **`docs/product/STATUS.md` is the single source of truth** for what Engram is, who it serves, and what's explicitly out of scope. Read it on session start before making any product / architecture / scope suggestion.
- **`docs/product/decisions/*.md`** (if/when present) is a write-only journal of past major decisions. **Do not read by default** — past decisions don't constrain new ones. Only consult when the user explicitly asks to review history (e.g., "what did we decide about X before?").
- **When product understanding evolves:** OVERWRITE `STATUS.md` (not append). It's working memory, not a changelog.
- **When a major decision happens:** APPEND a new `decisions/<id>-<slug>.md` (write-only — never edit existing archives). Then update STATUS.md to reflect the new judgment.

## Hard rules (apply everywhere)

1. **Engram only stores cognitive content** — thoughts, reflections, ideas, decisions, observations, emotional self-analysis. The intent gate (`app/lib/intent_gate.py`) rejects pure event logs / reminders / factual notes. Do NOT add features that turn Engram into a notes / journal / todo app. If a feature pushes the system toward "log everything", say no.
2. **Canonical enums are English.** `domain`, `node_type`, `relation_type` in code, prompts, configs, and DB are always English (`psychology`, `concept`, `opposes`, …). Chinese display is a presentation concern handled by i18n on the frontend. Never write Chinese enum literals into Python source, prompts, configs, or DB schemas.
3. **Backend prompts default to English.** Built-in `app/config/backbones/*` and `app/config/dimensions/*` prompt templates are written in English. LLMs are instructed to "match the user's language" — do not pin output language in prompts (no "in Chinese" / "X Chinese characters" / "X English words" wording). User-extended backbones / dimensions can be any language; defaults stay English.
4. **Restart-required config is OK.** Backbone / dimension loaders run at module import; adding or toggling a backbone via `scripts/manage_config.py` requires a service restart. Don't paper over this with hot-reload heuristics.
5. **Migration files are forward-only and idempotent.** New SQL migrations live in `api/migrations/`. Never re-edit a committed migration; add a new one.

## Sub-rules per area

- Frontend i18n: read [`web/AGENTS.md`](web/AGENTS.md). Any user-visible string must come from `useI18n().t(...)`.
- Backbone / dimension extension: use `python -m scripts.manage_config <kind> {list,add,disable,enable,remove}` rather than hand-editing directories. Doc: `api/README.md`.

## Style

- Follow existing structure rather than introducing new patterns. If you find yourself copying boilerplate from a different file, that's usually fine; if you find yourself inventing a new pattern, ask first.
- No emojis in code or commits unless the user explicitly asks.
- Code comments: only when the *why* is non-obvious. Don't narrate *what*.
