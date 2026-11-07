#!/usr/bin/env bash
# BIM 5D Estimator - run:  bash start-mac-linux.sh   (needs Python 3.10+)
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "Python was not found. Install Python 3.10+ from https://www.python.org/downloads/"
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First start: installing, this takes a few minutes..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
echo "Starting BIM 5D Estimator on http://localhost:8000  (Ctrl+C to stop)"
( sleep 2; (command -v open >/dev/null && open http://localhost:8000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || true ) &
.venv/bin/python -m uvicorn server:app --port 8000
