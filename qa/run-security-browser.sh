#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p qa/output
PYTHONPATH="$ROOT/backend:$ROOT/backend/qa" "${QA_PYTHON:-$ROOT/backend/.qa-venv/bin/python}" qa/serve-security-api.py >qa/output/security-api-browser.log 2>&1 &
API_PID=$!
npm --prefix dashboard run dev -- --host 127.0.0.1 --port 5176 --strictPort >qa/output/security-dashboard-vite.log 2>&1 &
DASH_PID=$!
trap 'kill "$API_PID" "$DASH_PID" 2>/dev/null || true' EXIT
node --input-type=module -e 'for (const port of [8000,5176]) { let ready=false;for(let i=0;i<100;i++){try{const r=await fetch(`http://127.0.0.1:${port}${port===8000?"/api/health":""}`);if(r.ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}if(!ready)process.exit(1)}'
node qa/browser-security.mjs
