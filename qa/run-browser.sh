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
node --input-type=module -e 'for (const port of [5173,5174]) { let ok=false; for(let i=0;i<200;i++){try{const r=await fetch(`http://127.0.0.1:${port}`);if(r.ok){ok=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}if(!ok){console.error(`QA server not ready on port ${port}`);process.exit(1)}}'
if [[ "${QA_BROWSER_SUITE:-all}" == "promo-codes" ]]; then
  node qa/browser-promo-codes.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "support-history" ]]; then
  node qa/browser-support-history.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "financial-periods" ]]; then
  node qa/browser-financial-periods.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "quantity-sync" ]]; then
  node qa/browser-cart-quantity-sync.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "cart-guard" ]]; then
  node qa/browser-cart-checkout-guard.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "cart-recovery" ]]; then
  node qa/browser-cart-recovery.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "miniapp-support" ]]; then
  node qa/browser-miniapp-support.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "chat-drafts" ]]; then
  node qa/browser-chat-drafts.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "dashboard-chat" ]]; then
  node qa/browser-dashboard-chat.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "ux" ]]; then
  node qa/browser-ux-stage6.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "chat" ]]; then
  node qa/browser-after-sales-chat.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "broadcasts" ]]; then
  node qa/browser-broadcasts.mjs
  node qa/browser-broadcast-compose.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "working-data" ]]; then
  node qa/browser-working-data.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "analytics" ]]; then
  node qa/browser-analytics.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "checkout" ]]; then
  node qa/browser-checkout.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "catalog" ]]; then
  node qa/browser-catalog.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "navigation" ]]; then
  node qa/browser-storefront-navigation.mjs
elif [[ "${QA_BROWSER_SUITE:-all}" == "storefront" ]]; then
  node qa/browser-storefront.mjs
else
  node qa/browser-promo-codes.mjs
  node qa/browser-support-history.mjs
  node qa/browser-financial-periods.mjs
  node qa/browser-cart-quantity-sync.mjs
  node qa/browser-cart-checkout-guard.mjs
  node qa/browser-cart-recovery.mjs
  node qa/browser-miniapp-support.mjs
  node qa/browser-chat-drafts.mjs
  node qa/browser-dashboard-chat.mjs
  node qa/browser-ux-stage6.mjs
  node qa/browser-after-sales-chat.mjs
  node qa/browser-broadcasts.mjs
  node qa/browser-broadcast-compose.mjs
  node qa/browser-working-data.mjs
  node qa/browser-ui.mjs
  node qa/browser-checkout.mjs
  node qa/browser-storefront.mjs
  node qa/browser-catalog.mjs
  node qa/browser-storefront-navigation.mjs
  node qa/browser-analytics.mjs
fi
