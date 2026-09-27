#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "=== Promo Python syntax"
python3 -m py_compile backend/api/routers/landing_pages.py deploy/promo-controller/controller.py

echo "=== Promo landing contracts"
python3 backend/qa/qa_promo_landing.py

echo "=== Promo Cloudflare contracts"
python3 backend/qa/qa_promo_cloudflare.py

echo "=== Promo Google integrations"
python3 backend/qa/qa_promo_google.py

echo "=== Promo shell syntax"
bash -n deploy/deploy-promo.sh

echo "=== Promo-only regression PASS"
