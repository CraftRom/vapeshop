# Storefront browser verification

Install application dependencies with `npm ci` in `miniapp` and `dashboard`, and QA dependencies with `npm ci` in `qa`. Install the Playwright browser with `npx playwright install chromium` from `qa`.

Run `bash qa/run-browser.sh` from the project root. The runner starts both Vite servers, intercepts API traffic with neutral fixtures and closes the servers when done. Screenshots and results are written to `qa/output`.

A local Chromium binary can be supplied through `PLAYWRIGHT_EXECUTABLE_PATH`. It is optional on systems with the standard Playwright browser installed.

Node regression suites live in each application's `tests` directory. Run a suite from its application directory so its source-path assertions resolve correctly. Backend regression dependencies are in `backend/requirements-qa.txt`.
