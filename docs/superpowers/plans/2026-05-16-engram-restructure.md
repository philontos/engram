# Engram Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic `cognitive-service` (which currently bundles Python API + React frontend) into separated `api/` and `web/` directories at the repo root, with a `deploy/` folder housing Docker + Caddy configs. Enable fast local dev (no Docker required) while keeping single-command VPS deployment.

**Architecture:** Top-level monorepo with `web/` (SPA), `api/` (FastAPI), `shared/` (Python), and `deploy/` (Docker + Caddy). Local dev runs API and Web as separate processes (uvicorn + vite). VPS deployment uses 3 containers (api, web, caddy) orchestrated by docker-compose. Caddy reverse-proxies known API path prefixes to api container, everything else to web container.

**Tech Stack:** Python 3.12 / FastAPI / uvicorn, React 19 / Vite 8 / pnpm, Docker / docker-compose, Caddy 2, nginx (in web container).

**Out of scope:** MCP (`cognitive-mcp/`) and OpenClaw (`cognitive-openclaw/`) are NOT touched in this plan — they continue to talk to the API via the existing HTTP URL.

---

## Pre-Flight

**Worktree:** Execute in a fresh worktree via `superpowers:using-git-worktrees`. Suggested branch name: `restructure/api-web-split`.

**Backup confirmation:** Confirm `data/` directory (gitignored) is preserved on disk before starting — it contains the user's actual entries / graph state. Do not delete or move this directory.

**Smoke test environments:** This plan requires both `python 3.12`, `pnpm`, and a working `docker compose` (Docker Desktop or equivalent) on the developer machine.

---

## Target File Structure

```
engram/
├── web/                          # was cognitive-service/frontend
│   ├── src/                      # unchanged content
│   ├── public/                   # unchanged content
│   ├── index.html
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── tsconfig.json
│   ├── tsconfig.app.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts            # CHANGED: outDir + proxy list
│   ├── eslint.config.js
│   ├── README.md
│   ├── AGENTS.md                 # moved from cognitive-service/frontend/AGENTS.md
│   ├── Dockerfile                # NEW: 2-stage build → nginx
│   └── nginx.conf                # NEW: SPA routing
├── api/                          # was cognitive-service (frontend removed)
│   ├── app/                      # unchanged content
│   │   └── main.py               # CHANGED: remove static mount, add CORS
│   ├── migrations/               # unchanged content
│   ├── scripts/                  # unchanged content
│   ├── tests/                    # unchanged content
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── reset.sh
│   ├── README.md
│   ├── README.en.md
│   └── Dockerfile                # CHANGED: drop frontend build stage
├── shared/                       # unchanged
├── cognitive-mcp/                # UNCHANGED (out of scope)
├── cognitive-openclaw/           # UNCHANGED (out of scope)
├── deploy/
│   ├── docker-compose.yml        # NEW: api + web + caddy
│   ├── Caddyfile.tailscale       # NEW: HTTP reverse proxy
│   └── Caddyfile.https.example   # NEW: documented template for open-source users
├── docs/                         # unchanged
├── data/                         # unchanged (gitignored)
├── AGENTS.md                     # CHANGED: update path references
├── LICENSE
├── LICENSING.md
├── README.md                     # CHANGED: update quick-start instructions
├── README.zh.md                  # CHANGED: same
├── docker-compose.yml            # DELETED (moved to deploy/)
└── .gitignore                    # CHANGED: update stale paths
```

---

## API Path Inventory (used by Caddyfile)

All current top-level API path prefixes — needed for Caddy reverse-proxy rules:

| Prefix | Router |
|---|---|
| `/capture` | capture.py |
| `/import` | import_entries.py |
| `/entries` | revert_entry.py + process_entry.py |
| `/query` | query.py + agent.py |
| `/ui/api` | ui_api.py |
| `/health` | main.py (no router) |

Everything else → web container.

---

## Task 1: Move web/ to top level

**Files:**
- Move: `cognitive-service/frontend/` → `web/`

- [ ] **Step 1: Verify source directory exists**

Run: `ls cognitive-service/frontend/package.json`
Expected: file path printed (no error)

- [ ] **Step 2: Move via git**

Run: `git mv cognitive-service/frontend web`

- [ ] **Step 3: Verify move**

Run: `ls web/package.json && ls -d cognitive-service/frontend 2>/dev/null || echo "source removed (good)"`
Expected: `web/package.json` exists; `cognitive-service/frontend` no longer exists.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: move cognitive-service/frontend to web/"
```

---

## Task 2: Rename cognitive-service to api

**Files:**
- Move: `cognitive-service/` → `api/`

- [ ] **Step 1: Move via git**

Run: `git mv cognitive-service api`

- [ ] **Step 2: Verify**

Run: `ls api/app/main.py api/requirements.txt api/Dockerfile`
Expected: all three exist; no error.

- [ ] **Step 3: Remove old static build artifacts**

The `static/` directory existed as the output target of the frontend build. With the frontend gone, this is dead.

Run: `git rm -rf api/static 2>/dev/null; rm -rf api/static; ls api/static 2>/dev/null || echo "removed"`
Expected: prints `removed`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename cognitive-service to api; drop static dir"
```

---

## Task 3: Update web/vite.config.ts (proxy + outDir)

**Files:**
- Modify: `web/vite.config.ts`

- [ ] **Step 1: Replace file content**

Write `web/vite.config.ts` with this exact content:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Local dev proxies API paths to the FastAPI server on :18080.
// All paths here MUST stay in sync with the prefixes registered in api/app/main.py.
const API_PROXIES = ['/capture', '/import', '/entries', '/query', '/ui/api', '/health']

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PROXIES.map((p) => [p, { target: 'http://localhost:18080', changeOrigin: true }])
    ),
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
```

- [ ] **Step 2: Verify TypeScript still parses**

Run: `cd web && pnpm exec tsc --noEmit -p tsconfig.node.json`
Expected: exit code 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add web/vite.config.ts
git commit -m "refactor(web): outDir → dist, centralize API proxy list"
```

---

## Task 4: Update api/app/main.py (drop static mount, add CORS)

**Files:**
- Modify: `api/app/main.py`

- [ ] **Step 1: Replace file content**

Write `api/app/main.py` with this exact content:

```python
from dotenv import load_dotenv
load_dotenv()

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.lib.db import init_db
from app.lib.config_loader import detect_orphan_domains
from app.routes import agent, capture, import_entries, process_entry, query, revert_entry, ui_api

app = FastAPI(title="Cognitive Service")
logger = logging.getLogger("cognitive")


# Local dev only: enable CORS for the Vite dev server on :5173.
# In production, Caddy keeps web + api same-origin, so CORS is unnecessary.
if os.getenv("ENGRAM_DEV") == "1":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def startup():
    init_db()
    orphans = detect_orphan_domains()
    if orphans:
        logger.warning(
            "Orphan backbone domains in DB (no matching config dir): %s. "
            "Existing nodes are kept and still consumed by query pipelines, "
            "but new entries will not write to these domains.",
            ", ".join(orphans),
        )

    # Crash recovery: any entry left in 'processing' from a previous run had
    # its pipeline interrupted (process killed, OOM, container restart). Roll
    # them back to 'captured' so process_pending picks them up again.
    from app.lib.db import get_conn
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE entries SET processing_status='captured' WHERE processing_status='processing'"
        )
        if cur.rowcount:
            logger.warning("Reset %d stuck 'processing' entries to 'captured' on startup", cur.rowcount)


app.include_router(capture.router)
app.include_router(import_entries.router)
app.include_router(process_entry.router)
app.include_router(revert_entry.router)
app.include_router(query.router)
app.include_router(agent.router)
app.include_router(ui_api.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

Notes on the change:
1. **Removed** `from fastapi.staticfiles import StaticFiles` import.
2. **Removed** the final `app.mount("/", StaticFiles(...))` line.
3. **Added** CORS middleware behind `ENGRAM_DEV=1` flag.
4. Everything else unchanged.

- [ ] **Step 2: Verify import works**

Run: `cd api && python -c "from app.main import app; print('ok:', app.title)"`
Expected: `ok: Cognitive Service`

- [ ] **Step 3: Commit**

```bash
git add api/app/main.py
git commit -m "refactor(api): drop static mount, add dev-only CORS"
```

---

## Task 5: Simplify api/Dockerfile (drop frontend build stage)

**Files:**
- Modify: `api/Dockerfile`

- [ ] **Step 1: Replace file content**

Write `api/Dockerfile` with this exact content:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./
COPY shared ./shared

RUN mkdir -p data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Notes:
1. **Removed** entire Stage 1 (frontend build). No more Node in this image.
2. **Removed** `COPY --from=frontend /static ./static`.
3. Build context is still the repo root (so it can access `shared/`).

- [ ] **Step 2: Verify Dockerfile syntax**

Run: `docker buildx build --no-cache -f api/Dockerfile -t engram-api:test . --target= --load 2>&1 | tail -5` from the repo root.

If `docker buildx` is not available, fall back to: `docker build -f api/Dockerfile -t engram-api:test .`

Expected: build completes successfully, last line shows `Successfully tagged engram-api:test` or equivalent.

- [ ] **Step 3: Commit**

```bash
git add api/Dockerfile
git commit -m "refactor(api): simplify Dockerfile, drop frontend build stage"
```

---

## Task 6: Create web/Dockerfile and web/nginx.conf

**Files:**
- Create: `web/Dockerfile`
- Create: `web/nginx.conf`

- [ ] **Step 1: Create web/Dockerfile**

Write `web/Dockerfile` with this exact content:

```dockerfile
# Stage 1: build the SPA
FROM node:20-slim AS builder

WORKDIR /build

RUN npm install -g pnpm

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# Stage 2: serve via nginx
FROM nginx:1.27-alpine

COPY --from=builder /build/dist /usr/share/nginx/html
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
```

Notes:
- Build context is repo root, so paths are `web/...`
- `pnpm build` outputs to `/build/dist` (per the updated vite.config.ts)

- [ ] **Step 2: Create web/nginx.conf**

Write `web/nginx.conf` with this exact content:

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback — any path not matching a file returns index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Aggressive caching for built assets (Vite hashes filenames)
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

- [ ] **Step 3: Verify the build works**

Run: `docker build -f web/Dockerfile -t engram-web:test .` from the repo root.
Expected: build completes successfully, no errors.

- [ ] **Step 4: Run the container and verify it serves index.html**

Run: `docker run --rm -d --name engram-web-test -p 18081:80 engram-web:test && sleep 2 && curl -fs http://localhost:18081/ | head -5 ; docker stop engram-web-test`

Expected: `<!doctype html>` line (or similar HTML) appears in output, then container stops cleanly.

- [ ] **Step 5: Commit**

```bash
git add web/Dockerfile web/nginx.conf
git commit -m "feat(web): add Dockerfile and nginx config for production serving"
```

---

## Task 7: Create deploy/ directory with docker-compose.yml and Caddyfile

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/Caddyfile.tailscale`
- Create: `deploy/Caddyfile.https.example`
- Delete: `docker-compose.yml` (root)

- [ ] **Step 1: Create deploy directory**

Run: `mkdir -p deploy`

- [ ] **Step 2: Write deploy/docker-compose.yml**

Write `deploy/docker-compose.yml` with this exact content:

```yaml
services:
  api:
    build:
      context: ..
      dockerfile: api/Dockerfile
    expose:
      - "8080"
    volumes:
      # Host: <repo>/data/cognitive/   →   Container: /app/data
      # Path preserved from the previous docker-compose.yml so existing user data
      # (at <repo>/data/cognitive/cognitive.db) is read without migration.
      # DB_PATH default is ./data/cognitive.db (relative to WORKDIR /app), so the
      # DB lands at /app/data/cognitive.db inside container = <repo>/data/cognitive/cognitive.db on host.
      - ../data/cognitive:/app/data
    env_file:
      - ../api/.env
    restart: unless-stopped

  web:
    build:
      context: ..
      dockerfile: web/Dockerfile
    expose:
      - "80"
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
    volumes:
      - ./Caddyfile.tailscale:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    restart: unless-stopped
    depends_on:
      - api
      - web

volumes:
  caddy_data:
  caddy_config:
```

**Note on data path:** The mount source path is now `../data/cognitive:/app/data` (instead of the old `./data/cognitive:/app/data`) because the docker-compose file moved from repo root to `deploy/`. The host-side directory `<repo>/data/cognitive/` is unchanged — **no data migration is needed**. Existing users keep their DB at `<repo>/data/cognitive/cognitive.db` exactly where it was.

- [ ] **Step 3: Write deploy/Caddyfile.tailscale**

Write `deploy/Caddyfile.tailscale` with this exact content:

```caddyfile
# Default deployment mode: HTTP only, intended for Tailscale-private or
# LAN-only access. For public HTTPS, see Caddyfile.https.example.
#
# Caddy is the only entrypoint on :80. It splits traffic:
#   - known API path prefixes → api:8080
#   - everything else (including SPA routes) → web:80
#
# Keep this list in sync with web/vite.config.ts (API_PROXIES).

:80 {
    @api {
        path /capture* /import* /entries/* /query* /ui/api/* /health
    }
    handle @api {
        reverse_proxy api:8080
    }

    handle {
        reverse_proxy web:80
    }

    log {
        output stdout
        format console
    }
}
```

- [ ] **Step 4: Write deploy/Caddyfile.https.example**

Write `deploy/Caddyfile.https.example` with this exact content:

```caddyfile
# Public HTTPS deployment template.
# To use:
#   1. Point your domain's A record at the VPS IP.
#   2. Copy this file: cp Caddyfile.https.example Caddyfile.tailscale
#      (overwrite the active Caddyfile; or change docker-compose to point at this file)
#   3. Replace "engram.example.com" with your real domain.
#   4. In docker-compose.yml, expose port 443 in addition to 80:
#         ports:
#           - "80:80"
#           - "443:443"
#   5. docker compose up -d --build
#
# Caddy will auto-provision a Let's Encrypt cert. No further config needed.
#
# WARNING: v1 has no built-in auth. Do NOT expose Engram to the public internet
# unless you put basic-auth or an SSO proxy in front. Engram stores private
# cognitive content.

engram.example.com {
    @api {
        path /capture* /import* /entries/* /query* /ui/api/* /health
    }
    handle @api {
        reverse_proxy api:8080
    }

    handle {
        reverse_proxy web:80
    }
}
```

- [ ] **Step 5: Delete root docker-compose.yml**

Run: `git rm docker-compose.yml`

- [ ] **Step 6: Verify Caddyfile syntax**

Run: `docker run --rm -v "$PWD/deploy/Caddyfile.tailscale:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile`

Expected: line `Valid configuration` (or similar success message).

- [ ] **Step 7: Commit**

```bash
git add deploy/
git commit -m "feat(deploy): add docker-compose.yml + Caddyfiles (Tailscale + HTTPS template)"
```

---

## Task 8: Update .gitignore for new paths

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Replace file content**

Write `.gitignore` with this exact content:

```gitignore
# Python
.venv/
__pycache__/
*.pyc
.pytest_cache/

# User data (DB, vector index, exports) — never commit
data/

# Environment
.env
*.env.local

# Node / Vite
node_modules/
dist/

# OS
.DS_Store

# Personal exports & seed data (contain raw reflections — never commit)
cognitive_entries*.json
seed-reflections*.json
```

Changes from previous version:
- Removed stale `cognitive-service/static/...` entries (the directory no longer exists).
- Consolidated comments.

- [ ] **Step 2: Verify nothing tracked should now be ignored**

Run: `git status --short`
Expected: no `data/` or `node_modules/` showing up; the worktree is clean of build artifacts.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: update .gitignore for new directory layout"
```

---

## Task 9: Update root README.md with new quick-start

**Files:**
- Modify: `README.md`
- Modify: `README.zh.md`

- [ ] **Step 1: Locate the Quick Start section in README.md**

Run: `grep -n "Quick start\|Quick Start\|快速开始" README.md README.zh.md`
Expected: prints line numbers for the headings.

- [ ] **Step 2: Replace the quick-start section in README.md**

Find the section under `## Quick start` (or the closest heading) in `README.md` and replace it with this content:

````markdown
## Quick start

### Local development (no Docker required)

```bash
# Terminal 1: API (FastAPI + hot reload)
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / EMBED_MODEL
ENGRAM_DEV=1 uvicorn app.main:app --reload --port 18080

# Terminal 2: Web (Vite dev server with HMR)
cd web
pnpm install
pnpm dev

# Open http://localhost:5173 in your browser.
```

### Local Docker smoke test (recommended before VPS deploy)

```bash
cd deploy
docker compose up --build
# Open http://localhost in your browser.
docker compose down  # when done
```

### VPS deployment (Tailscale-private, default)

Prerequisites: Tailscale installed and running on the VPS, your laptop in the same Tailnet, VPS firewall blocks public access on :80.

```bash
ssh <vps>
git clone <this-repo> ~/engram
cd ~/engram
cp api/.env.example api/.env  # fill in
cd deploy
docker compose up -d --build
# Access from any Tailscale device: http://<vps-tailscale-ip>
```

### VPS deployment (Public HTTPS)

See `deploy/Caddyfile.https.example` for the public-deployment template. WARNING: there is no built-in auth in v1; add a layer in front before exposing publicly.
````

- [ ] **Step 3: Do the same for README.zh.md (Chinese mirror)**

Apply the equivalent change in `README.zh.md`. Translate the section headings; keep code blocks identical.

- [ ] **Step 4: Commit**

```bash
git add README.md README.zh.md
git commit -m "docs: update quick-start for new api/web/deploy layout"
```

---

## Task 10: Update AGENTS.md path references

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Find stale references**

Run: `grep -n "cognitive-service" AGENTS.md`
Expected: prints line numbers where the old path is referenced.

- [ ] **Step 2: Replace stale paths**

In `AGENTS.md`, replace:
- `cognitive-service/` → `api/`
- `cognitive-service/frontend/` → `web/`
- `cognitive-service/app/lib/intent_gate.py` → `api/app/lib/intent_gate.py`
- `cognitive-service/frontend/AGENTS.md` → `web/AGENTS.md`
- `cognitive-service/README.md` → `api/README.md`

Use a deliberate find-and-replace; do not regex over the whole file without checking each match.

- [ ] **Step 3: Verify no stale references remain**

Run: `grep -n "cognitive-service" AGENTS.md`
Expected: no output (no matches), OR only intentional references (e.g., historical changelog entries — confirm each one).

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md
git commit -m "docs(AGENTS): update path references to new layout"
```

---

## Task 11: Local dev smoke test (no Docker)

**Verifies:** The new structure works for non-Docker local development before we trust the Docker variant.

- [ ] **Step 1: Set up API venv**

Run from repo root:
```bash
cd api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: install completes without errors. Confirm `python --version` reports 3.12.x.

- [ ] **Step 2: Ensure .env exists**

Run: `ls .env || cp .env.example .env`

If `.env.example` does not exist, create a minimal `api/.env` from the existing user `.env` if known, OR document that the user must supply LLM credentials before continuing.

- [ ] **Step 3: Start API**

Run (in `api/` dir, with venv active):
```bash
ENGRAM_DEV=1 uvicorn app.main:app --reload --port 18080
```

Wait until the server reports `Application startup complete.`

- [ ] **Step 4: Hit /health from another terminal**

Run: `curl -fs http://localhost:18080/health`
Expected: `{"status":"ok"}`

- [ ] **Step 5: Start web dev server**

In a new terminal, from repo root:
```bash
cd web
pnpm install
pnpm dev
```

Wait until Vite prints `Local: http://localhost:5173/`.

- [ ] **Step 6: Manually verify dashboard loads**

Open `http://localhost:5173` in a browser. The Engram dashboard should load without console errors. Network tab should show successful requests to `/ui/api/...` (proxied to 18080).

- [ ] **Step 7: Verify proxy works via CLI**

Run: `curl -fs http://localhost:5173/health`
Expected: `{"status":"ok"}` (proxied through Vite to FastAPI).

- [ ] **Step 8: Stop both dev servers**

Ctrl+C in both terminals.

- [ ] **Step 9: Run existing test suite**

Run from `api/` (with venv active):
```bash
pytest -x -q
```

Expected: all existing tests pass. If any fail due to path changes (e.g., test discovery issues), fix them as a sub-task and commit separately.

---

## Task 12: Docker smoke test (local)

**Verifies:** The Docker build + Caddy reverse-proxy works end-to-end locally, before pushing to VPS.

- [ ] **Step 1: Ensure data directory exists**

Run from repo root: `mkdir -p data/cognitive`

This matches the volume mount in `deploy/docker-compose.yml`. If you already have data at `<repo>/data/cognitive/cognitive.db` from previous use, leave it in place — the new docker-compose reads it from the same path.

- [ ] **Step 2: Verify .env is present**

Run: `ls api/.env`
Expected: file exists. If not, copy from `.env.example` and fill in credentials.

- [ ] **Step 3: Build and start all containers**

Run from repo root:
```bash
cd deploy
docker compose up --build
```

Wait until all three services log readiness:
- api: `Application startup complete.`
- web: nginx ready (no error logs)
- caddy: server running on :80

- [ ] **Step 4: Hit health endpoint via Caddy**

In another terminal: `curl -fs http://localhost/health`
Expected: `{"status":"ok"}`

- [ ] **Step 5: Hit dashboard via Caddy**

Run: `curl -fs http://localhost/ | head -5`
Expected: HTML starting with `<!doctype html>` (the SPA shell).

- [ ] **Step 6: Open in browser and verify**

Visit `http://localhost` in a browser. The dashboard should load identically to the dev mode in Task 11.

- [ ] **Step 7: Stop containers**

Back in the `deploy/` terminal: Ctrl+C, then `docker compose down`.

Verify the volumes are intact:
```bash
docker volume ls | grep deploy_caddy
```
Expected: `deploy_caddy_data` and `deploy_caddy_config` listed.

- [ ] **Step 8: Verify data persisted on host**

Run: `ls -lh ../data/cognitive/cognitive.db`
Expected: the DB file exists, modification time is recent (was touched by the api container).

---

## Task 13: Final cleanup and summary

- [ ] **Step 1: Look for any remaining stale references**

Run from repo root:
```bash
grep -rn "cognitive-service" --include="*.md" --include="*.py" --include="*.ts" --include="*.yml" --include="*.yaml" --include="*.toml" --include="Dockerfile*" .
```

Expected: only matches inside `cognitive-mcp/` and `cognitive-openclaw/` (which are out of scope per the brief). If matches appear elsewhere, fix them and commit.

- [ ] **Step 2: Confirm worktree is clean**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

- [ ] **Step 3: Show the diff summary**

Run: `git log --oneline main..HEAD`
Expected: a clean series of conventional commits from Tasks 1–12.

- [ ] **Step 4: Open the branch as a PR (or merge directly)**

Per `superpowers:finishing-a-development-branch`, choose the appropriate integration path. Default suggestion for solo-project: rebase + fast-forward merge into main.

---

## Rollback

If anything goes wrong:

```bash
# Bail entirely (from inside the worktree):
git checkout main
git worktree remove ../engram-restructure  # or whatever the worktree path is
```

The main branch is never touched, so this restructure is fully reversible.

---

## Definition of Done

All of the following are true:

- [ ] `web/`, `api/`, `deploy/` exist at repo root with the contents described in "Target File Structure".
- [ ] `cognitive-service/` no longer exists.
- [ ] `cognitive-mcp/` and `cognitive-openclaw/` are unchanged (per scope).
- [ ] Local dev (Task 11) works: `cd api && uvicorn ...` + `cd web && pnpm dev` → dashboard loads at `:5173`.
- [ ] Local Docker (Task 12) works: `cd deploy && docker compose up --build` → dashboard loads at `:80`.
- [ ] All existing pytest tests pass.
- [ ] No stale `cognitive-service` references in repo (except inside `cognitive-mcp/` and `cognitive-openclaw/` which are out of scope).
- [ ] `.gitignore` is up-to-date.
- [ ] `README.md` quick-start reflects the new layout.
- [ ] Worktree is clean; commit history is a tidy sequence of conventional commits.
