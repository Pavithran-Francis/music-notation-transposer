#!/usr/bin/env bash
# Run backend (http://127.0.0.1:8000, API docs at /docs) and frontend (http://127.0.0.1:5173).
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
(cd backend && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5173) &
wait
