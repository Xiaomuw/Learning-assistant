# Browser regression and recording scope

The `Browser UI regression (synthetic API)` workflow builds the actual Next.js
application and runs Chromium at 390×844 and 1280×900. Screenshots, WebM recordings
and results.json are retained as workflow artifacts for 14 days. These recordings
show the real UI with original synthetic questions and intercepted API responses;
they are not live-model demonstrations, actual user adoption or physical-device
acceptance. No external model, SMTP, WeChat or production service is contacted.

The suite checks same-origin login redirects, hydration/runtime errors, streaming
process expansion/collapse, exclusion of ephemeral traces from cache, user-scoped
practice restoration, appended-question progress and profile/dashboard loading.
It complements the existing real FastAPI/PostgreSQL/Next proxy workflows.

To reproduce, install project dependencies with `npm ci` in frontend, build with
`npm run build`, and start `npm run start -- --hostname 127.0.0.1 --port 3100`.
In a second terminal, install the optional test tool separately:

```bash
npm install --prefix /tmp/la-ui-tools --no-save playwright@1.62.1
/tmp/la-ui-tools/node_modules/.bin/playwright install chromium
node scripts/test-safe-next.mjs
NODE_PATH=/tmp/la-ui-tools/node_modules UI_TEST_OUTPUT=/tmp/la-ui-evidence node scripts/browser-regression.mjs
```

Run these commands inside frontend. The browser harness refuses non-loopback
targets. Existing production dependencies/lockfiles are unchanged. Device tests
still require an owner-controlled WeChat app, iOS/Android devices and a disposable
deployment with approved provider budget. Review the recordings before sharing;
label them **synthetic API UI regression**, never as a provider-quality benchmark.
