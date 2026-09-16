# Production image for the Elastic AI Copilot Gateway.
#
# Stages:
#   1. frontend         — build the React (v2) UI with Node, output /build/dist
#   2. compiler         — Cython-compile the license-critical backend modules
#                         into native .so extensions (obfuscation)
#   3. backend-plain    — plaintext backend passthrough (debug builds only)
#   4. backend-selected — alias that resolves to (2) or (3) via BACKEND_STAGE
#   5. base             — assemble the FastAPI gateway, bundle the built UI
#
# By default the image ships the license-enforcement modules as compiled
# .so binaries so the gate cannot be patched out without native-binary
# reverse engineering. See poc/backend/_cython_build.py and docs/SECURITY.md.
#
# Used by the root-level docker-compose.yml for full-stack deployments.
# Build from the project root:  docker build -t rst-elastic-ai-copilot-gateway .
#
# Debug (un-obfuscated) build:
#   docker build --build-arg BACKEND_STAGE=backend-plain -t rst-elastic-ai-copilot-gateway:debug .

# Global ARG — selects which backend the final image bundles. Declared in the
# global scope so it can be expanded by a `FROM` line (the documented
# workaround for `--from` not supporting variable expansion).
ARG BACKEND_STAGE=compiler

# ─── Stage 1: build the React (v2) frontend → /build/dist ───────────────────
FROM node:22-slim AS frontend

WORKDIR /build

# Install deps first (cached unless package.json / lockfile change).
# `npm install` (not `npm ci`) — the lockfile is generated on Windows and omits
# Linux-only optional deps (@emnapi/runtime etc.); npm install resolves them.
COPY poc/frontend/package.json poc/frontend/package-lock.json ./
RUN npm install --no-audit --no-fund

# Build the SPA. `npm run build` = tsc -b && vite build.
COPY poc/frontend/ ./
RUN npm run build

# ─── Stage 2: Cython-compile the license-critical modules → native .so ──────
# main.py + the six license modules ship as compiled extensions so the
# license-enforcement path cannot be patched (e.g. deleting the
# `app.add_middleware(LicenseGateMiddleware)` line) without disassembling a
# native binary. The poc/ source tree itself stays plaintext for dev / eval.
#
# IMPORTANT: this stage MUST use the same Python minor version as the `base`
# stage below (3.13) — a Cython .so is ABI-bound to one (platform, python)
# pair. python:3.13-slim already ships the CPython development headers.
FROM python:3.13-slim AS compiler

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY poc/requirements-build.txt ./
RUN pip install -r requirements-build.txt

COPY poc/backend ./backend
# Compiles the target modules to <module>.cpython-313-*.so and deletes the
# corresponding .py source + Cython .c intermediates. Fails the build loudly
# if any target does not produce a .so.
RUN python backend/_cython_build.py

# ─── Stage 3: plaintext backend passthrough (debug builds only) ─────────────
# Selected with  --build-arg BACKEND_STAGE=backend-plain  to ship a readable,
# un-obfuscated backend when troubleshooting. NOT for production delivery.
FROM scratch AS backend-plain
COPY poc/backend /build/backend

# ─── Stage 4: resolve which backend the final image bundles ─────────────────
# `FROM` supports ARG expansion; `COPY --from` does not — so this alias stage
# lets the `base` stage COPY from a fixed name regardless of BACKEND_STAGE.
FROM ${BACKEND_STAGE} AS backend-selected

# ─── Stage 5: Python FastAPI gateway ────────────────────────────────────────
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for cryptography (RSA-PSS verifier needs cffi / openssl).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential libffi-dev libssl-dev curl \
 && rm -rf /var/lib/apt/lists/*

# 装的是锁文件，不是 requirements.txt —— 同一个 tag 在不同日期 build 必须得到
# 同一棵依赖树（理由见 poc/requirements.lock.txt 开头）。
COPY poc/requirements.txt poc/requirements.lock.txt /app/
RUN pip install -r /app/requirements.lock.txt

# Backend — obfuscated (compiler) by default, or plaintext (backend-plain)
# when built with --build-arg BACKEND_STAGE=backend-plain.
COPY --from=backend-selected /build/backend /app/backend
COPY poc/keys    /app/keys
# /app/eval exists but ships EMPTY. Nothing reads the eval fixtures at runtime
# (cases.yaml / detection_rule.yaml / rag_seed.yaml / run*.py are a dev
# harness), and shipping them published internal test expectations to anyone
# who could `docker cp` — which rather undercuts compiling the backend to hide
# it. The directory itself stays because main.py writes
# eval/failed_cases.yaml here and deploy/restore.sh restores into it.
RUN mkdir -p /app/eval

# v2 frontend — built in stage 1. main.py serves it from /app/frontend/dist.
COPY --from=frontend /build/dist /app/frontend/dist

# All writable runtime state lands in /app/state so a single mounted volume
# persists it across container restarts (see docker-compose.yml).
#
# The gateway runs as uid 10001, not root: a bug on the FastAPI side should not
# hand out root inside the container, and the secrets under /app/state
# (.rst_secret_key, license.key, sessions.json) should not be root-owned.
# /app/state and /app/eval are chowned here so a FRESH named volume inherits
# that ownership; docker-entrypoint.sh fixes an EXISTING (root-owned) volume on
# upgrade and then drops privileges.
RUN groupadd -r -g 10001 rst \
 && useradd -r -u 10001 -g 10001 -d /app -s /bin/sh rst \
 && mkdir -p /app/state \
 && chown -R 10001:10001 /app/state /app/eval

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

ENV ES_URL=http://elasticsearch:9200 \
    KIBANA_URL=http://kibana:5601 \
    PYTHONPATH=/app \
    RST_SETTINGS_FILE=/app/state/settings.yml \
    RST_LLM_CONFIG=/app/state/llm_providers.yml \
    RST_DASHBOARDS_FILE=/app/state/dashboards.yml \
    RST_QUOTA_FILE=/app/state/quota.json \
    RST_LICENSE_FILE=/app/state/license.key \
    RST_SERVER_GUID_FILE=/app/state/server_guid \
    RST_SESSION_STORE=/app/state/sessions.json \
    RST_CONTENT_DIR=/app/state/content

EXPOSE 8000

# Liveness probe — /healthz is always 200 while the process is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fs http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
