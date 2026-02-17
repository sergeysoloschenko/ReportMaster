#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Set ANTHROPIC_API_KEY before real runs."
fi

if [[ -x ".venv/bin/python" ]]; then
  VENV_BIN=".venv/bin"
elif [[ -x "venv/bin/python" ]]; then
  VENV_BIN="venv/bin"
else
  python3 -m venv .venv
  VENV_BIN=".venv/bin"
fi

if [[ ! -x "$VENV_BIN/uvicorn" ]]; then
  "$VENV_BIN/pip" install -r requirements.txt
fi

if [[ ! -d "webapp/frontend/node_modules" ]]; then
  (cd webapp/frontend && npm install)
fi

mkdir -p .run

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8000 is already in use. Stop existing process first (make dev-down) or free the port."
  exit 1
fi

if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 5173 is already in use. Stop existing process first (make dev-down) or free the port."
  exit 1
fi

echo "Starting backend on http://localhost:8000 ..."
"$VENV_BIN/uvicorn" src.webapp.backend.app:app --host 0.0.0.0 --port 8000 > .run/backend.log 2>&1 &
BACK_PID=$!
echo "$BACK_PID" > .run/backend.pid

echo "Starting frontend on http://localhost:5173 ..."
(cd webapp/frontend && npm run dev -- --host 0.0.0.0 --port 5173 > ../../.run/frontend.log 2>&1) &
FRONT_PID=$!
echo "$FRONT_PID" > .run/frontend.pid

cleanup() {
  if [[ -f .run/backend.pid ]]; then
    kill "$(cat .run/backend.pid)" >/dev/null 2>&1 || true
    rm -f .run/backend.pid
  fi
  if [[ -f .run/frontend.pid ]]; then
    kill "$(cat .run/frontend.pid)" >/dev/null 2>&1 || true
    rm -f .run/frontend.pid
  fi
}

trap cleanup EXIT INT TERM

echo "Backend log:  $ROOT_DIR/.run/backend.log"
echo "Frontend log: $ROOT_DIR/.run/frontend.log"
echo "Press Ctrl+C to stop both services."

wait
