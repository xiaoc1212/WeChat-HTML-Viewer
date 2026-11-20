#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[Error] Python 3.9+ not found. Please install Python 3 first."
  exit 1
fi

exec "$PY" viewer_server.py "$@"
