#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && .venv/bin/python -m pytest -q -p no:warnings "$@")
(cd frontend && npx tsc -b && npm run lint --silent)
