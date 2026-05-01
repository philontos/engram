# ── Stage 1: build frontend ───────────────────────────────────────────────────
FROM node:20-slim AS frontend

WORKDIR /build

RUN npm install -g pnpm

COPY cognitive-service/frontend/package.json cognitive-service/frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY cognitive-service/frontend/ .
# outDir in vite.config.ts is "../static" → resolves to /static inside this stage
RUN pnpm build

# ── Stage 2: Python backend ───────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY cognitive-service/requirements.txt ./requirements.txt
RUN apt-get update && apt-get install -y g++ && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY cognitive-service/ .
COPY shared ./shared

# Overwrite static/ with the freshly built frontend
COPY --from=frontend /static ./static

RUN mkdir -p data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
