#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

for name in backend frontend; do
  pidfile=".run/${name}.pid"
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    kill "$pid" >/dev/null 2>&1 || true
    rm -f "$pidfile"
    echo "Stopped $name (pid=$pid)"
  else
    echo "$name is not running"
  fi
done
