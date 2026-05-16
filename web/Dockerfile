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
