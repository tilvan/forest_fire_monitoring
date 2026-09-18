#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$ROOT/backend/.env" ]]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  echo "Created backend/.env — add FIRMS_MAP_KEY from https://firms.modaps.eosdis.nasa.gov/api/area/"
fi

cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  PYTHON_BIN="$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)"
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt

cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi

echo "Backend:  cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000"
echo "Frontend: cd frontend && npm run dev"
echo "Open http://127.0.0.1:5173 — сначала вставьте FIRMS_MAP_KEY в backend/.env"
