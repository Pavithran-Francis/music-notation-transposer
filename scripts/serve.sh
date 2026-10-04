#!/usr/bin/env bash
# Production-style single process: builds the frontend and serves it from FastAPI on :8000.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd frontend && npm run build)
cd backend && exec .venv/bin/uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --workers 1
