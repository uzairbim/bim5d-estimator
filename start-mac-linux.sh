#!/usr/bin/env bash
# BIM 5D Estimator - run:  bash start-mac-linux.sh   (needs Python 3.10 - 3.14)
cd "$(dirname "$0")"
PY=""
for c in python3.13 python3.12 python3.14 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 - 3.14 was not found. Install it from https://www.python.org/downloads/"
  exit 1
fi
if [ ! -f .venv/installed.ok ]; then
  echo "First start: installing the parts it needs (2-5 minutes, needs internet)..."
  { [ -x .venv/bin/python ] || "$PY" -m venv .venv; } &&
  .venv/bin/python -m pip install --disable-pip-version-check --upgrade pip &&
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt &&
  touch .venv/installed.ok || {
    echo "Installation did not finish. Check the internet connection and run this again."
    echo "If it keeps failing: rm -rf .venv and try again."
    exit 1
  }
fi
exec .venv/bin/python run.py
