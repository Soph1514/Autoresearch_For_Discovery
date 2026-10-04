#!/usr/bin/env bash
# Run from any directory; never silently attach to a different checkout's server.
set -euo pipefail
cd "$(dirname "$0")/.."
export MODAL_PROFILE="${MODAL_PROFILE:-arin06}"
export RESEARCH_MODEL="${RESEARCH_MODEL:-claude-sonnet-4-6}"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
if lsof -tiTCP:8000 -sTCP:LISTEN >/dev/null || lsof -tiTCP:5173 -sTCP:LISTEN >/dev/null; then
  echo 'Port 8000 or 5173 is already in use. Stop that lab before starting this checkout.' >&2
  exit 1
fi
mkdir -p runs
.venv/bin/python -m uvicorn the_pigeon_holes.ui.api:app --host 127.0.0.1 --port 8000 >>runs/backend.log 2>&1 &
backend_pid=$!
(cd frontend && npm run dev -- --strictPort) >>runs/frontend.log 2>&1 &
frontend_pid=$!
trap 'kill "$backend_pid" "$frontend_pid" 2>/dev/null || true' EXIT INT TERM
printf 'Research lab: http://127.0.0.1:5173\nBackend and frontend logs: runs/\n'
wait
