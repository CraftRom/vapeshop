#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p qa/output
npm --prefix dashboard run dev -- --host 127.0.0.1 --port 5173 --strictPort >qa/output/dashboard-vite.log 2>&1 &
DASH_PID=$!
npm --prefix miniapp run dev -- --host 127.0.0.1 --port 5174 --strictPort >qa/output/miniapp-vite.log 2>&1 &
MINI_PID=$!
trap 'kill "$DASH_PID" "$MINI_PID" 2>/dev/null || true' EXIT
node --input-type=module -e 'for (const port of [5173,5174]) { let ok=false; for(let i=0;i<50;i++){try{const r=await fetch(`http://127.0.0.1:${port}`);if(r.ok){ok=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}if(!ok)process.exit(1)}'
if [[ "${QA_BROWSER_SUITE:-all}" == "catalog" ]]; then
  node qa/browser-catalog.mjs
else
  node qa/browser-ui.mjs
  node qa/browser-storefront.mjs
  node qa/browser-catalog.mjs
fi
