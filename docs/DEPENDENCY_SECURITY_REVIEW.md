# Dependency, license and secret review — 2026-10-22

**Partial, reproducible review; not a comprehensive security audit or legal clearance. Publication remains NO-GO.** Baseline: `712c0538571d01129c0f8b1fb5488b35c9df6058`. Audit scope is source dependencies freshly resolved on Linux/Python 3.12.14 and the two committed npm lockfiles, not deployed image operating-system packages or external services.

## Security findings

| Scope | Observed result | Required action |
| --- | --- | --- |
| Python, 95 resolved distributions | 5 affected packages: pypdf 5.4.0, python-multipart 0.0.20, Starlette 0.46.2, Requests 2.32.3, python-dotenv 1.1.0 | Patch, test and re-audit; overlapping advisory IDs must not be counted as distinct exploits |
| Python with proposed #31 pins | Requests 2.34.2 and python-dotenv 1.2.4 no longer reported; 3 affected packages remain | #31 is a narrow mitigation, not a clean audit |
| Python with proposed #32 pins | pypdf 6.21.2 and python-multipart 0.0.32 have no matched advisories; 3 other affected packages remain | Full audit exits 1; #32 does not include #31 |
| Fresh environment combining #31 + #32 requirements | 96 resolved distributions; only Starlette 0.46.2 remains reported (14 advisory records) | Full audit exits 1; local combination, not merged-candidate CI |
| Python with proposed #34 pins | FastAPI 0.141.1 / Starlette 1.3.1 have no matched advisories; 4 other affected packages remain | 108 advisory records / 63 distinct package-advisory ID pairs; audit exits 1; does not include #31/#32 |
| Fresh environment combining #31 + #32 + #34 requirements | 97 resolved distributions; pip check passes; pip-audit exits 0 with no matched advisories | Local dependency combination only; full candidate CI and distribution/image review still required |
| Web `npm audit --omit=dev` | 0 findings | Limited to production dependency scope and this audit date |
| Web full `npm audit` | 10 findings: 9 high, 1 moderate | Review build/dev chains (including Tailwind/PostCSS, glob/micromatch and Next ESLint chain); production audit does not cover these |
| Web with proposed #35 lockfile | 9 affected nodes: 7 high, 2 moderate; distinct direct advisory IDs 11 → 2 | Full audit still exits 1; production audit remains 0 |
| Taro full `npm audit` | 83 findings: 8 critical, 51 high, 23 moderate, 1 low | Separate compatible upgrade work and bundle reachability review |
| Taro with proposed #36 lockfile | 79 affected nodes: 4 critical, 51 high, 23 moderate, 1 low; distinct direct advisory IDs 162 → 118 | Four compatible transitive patches; full audit still exits 1 |
| Docker base images / OS packages, #38 | Four pinned linux/amd64 bases scanned on 2026-10-23; all report HIGH findings, PGVector also CRITICAL | Gate fails; final built application images and runtime reachability remain unreviewed |

Taro's eight critical affected package nodes include `@tarojs/components`, `@tarojs/taro`, `decompress`, `proxy-addr`, `shell-quote`, `swiper`, `vm2` and `websocket-driver`. These are package/advisory propagation counts, not eight independently confirmed runtime vulnerabilities. Investigate bundled components such as Swiper separately from build tooling. Some automatic npm suggestions would downgrade Taro to 3.x; do not run `npm audit fix --force` as a release strategy.

pypdf handles user-supplied PDFs; multipart/Starlette sit on request parsing and serving boundaries. Their pending advisories deserve P0 review before public deployment. #34 upgrades FastAPI and Starlette together, within the declared compatibility range, and tests compatibility with the existing SSE dependency. The pypdf major upgrade is proposed in #32 with original generated PDF fixtures and real ASGI multipart parsing checks. New advisory feed entries and exploitability still require individual maintainer assessment.

[PR #31](https://github.com/Xiaomuw/Learning-assistant/pull/31) patches only Requests and python-dotenv. Local tests exercise real loopback HTTP extraction and dotenv override/interpolation; related ingest/configuration tests passed (37). Requests upstream notices: [netrc leakage](https://github.com/psf/requests/security/advisories/GHSA-9hjg-9r4m-mvj7), [temporary-file handling](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2). See also the [dotenv changelog](https://github.com/theskumar/python-dotenv/blob/main/CHANGELOG.md). No paid API was used.

[PR #32](https://github.com/Xiaomuw/Learning-assistant/pull/32) updates pypdf 5.4.0 → 6.21.2 and python-multipart 0.0.20 → 0.0.32. Upstream [pypdf release notes](https://pypdf.readthedocs.io/en/6.21.2/meta/CHANGELOG.html) include security fixes in 6.21.2; the [multipart changelog](https://github.com/Kludex/python-multipart/blob/main/CHANGELOG.md) describes parser bounds/validation and scanning improvements. Seven new tests exercise the real PDF/multipart boundary without external document assets; storage is an explicit fake. All seven workflows passed at `bf29dc5e870514b4a0db7907b99e2287af5e5c8c`, including 70 backend modules.

A second **fresh** uncached environment combined only the four requirements edits in #31/#32. `pip check` and 44 focused tests passed; pip-audit still exited 1 for Starlette. Fully resolved [parser-only](audits/python-parsers-2026-10-22.json) and [combined](audits/python-combined-2026-10-22.json) snapshots retain package versions, advisory IDs and fixes. The latter resolved 96 distributions versus the earlier 95, illustrating that current ranges do not freeze transitives. Neither snapshot is an installation lock. Neither proposed patch has changed main.

[PR #34](https://github.com/Xiaomuw/Learning-assistant/pull/34) pins FastAPI 0.141.1 and Starlette 1.3.1. FastAPI's [release notes](https://fastapi.tiangolo.com/release-notes/) record Starlette 1.x support from 0.133.0; its broad minimum alone still allows vulnerable Starlette versions, hence the explicit security pin. These are bounded tested versions, not the latest upstream versions. Starlette 1.3.1 fixes URL-encoded form limits in [GHSA-82w8-qh3p-5jfq](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq). The new field-count/size regressions fail on the baseline (422 instead of early 400) and pass with the patched framework. Four other tests cover multipart limits/file bytes and real loopback HTTP SSE completion/disconnect. sse-starlette 2.2.1 remains unchanged after those compatibility checks; this is not external-model or deployed-proxy acceptance. Installed license texts identify FastAPI and its new transitive annotated-doc dependency as MIT, and Starlette/sse-starlette as BSD-3-Clause.

A third **fresh**, uncached environment combined the six pins from #31/#32/#34. `pip check`, 103 focused tests and `pip-audit` passed; the audit enumerated 97 distributions and reported no known vulnerabilities. The [framework-only](audits/python-framework-2026-10-22.json) and [six-pin combination](audits/python-framework-combined-2026-10-22.json) snapshots retain resolved versions and requirement checksums. Zero matches is scoped to this environment/feed, not a complete security clearance. Main still has the old dependencies. Web/Taro findings, unscanned image packages, transitive locking and release review remain open. Previous snapshots are retained as historical observations, not overwritten; their 14 Starlette records represent seven distinct advisory IDs, not 14 independent CVEs.

### Compatible JavaScript transitive patches

[PR #35](https://github.com/Xiaomuw/Learning-assistant/pull/35) updates brace-expansion 1.1.14 → 1.1.21, Browserslist 4.28.2 → 4.29.4, postcss-selector-parser 6.1.2 → 6.1.5, and four Browserslist data/helper packages. Versions remain within their existing ranges. Next/React/Tailwind/Autoprefixer direct versions are unchanged; no new dependency or override is added. The [brace-expansion advisory](https://github.com/juliangruber/brace-expansion/security/advisories/GHSA-q2hr-2g5m-vwhr) and [Browserslist changelog](https://github.com/browserslist/browserslist/blob/main/CHANGELOG.md) document the relevant fixes. Fresh installation, lint/typecheck, three actual CSS-pipeline regressions, production build and synthetic HTTP proxy smoke pass.

Two direct Web advisories remain: GHSA-vfj7-8cjw-p6xm in braces 3.0.3 (no compatible published patch found), and GHSA-rj75-hqrm-r3gf in postcss-selector-parser (the [fix is in 7.1.6+](https://github.com/postcss/postcss-selector-parser/blob/main/CHANGELOG.md), outside the current Tailwind/PostCSS Nested 6.x ranges). Updating to 6.1.5 removes the older recursion advisory, not the newer flat-selector issue. npm also propagates the remaining advisory to postcss-nested, so package-node counts fall only from 10 to 9 while distinct direct advisory IDs fall from 11 to 2. These are neither CVE counts nor exploitability findings. [Web snapshot](audits/web-transitives-2026-10-22.json) records both counts, remaining chains and lock checksums.

[PR #36](https://github.com/Xiaomuw/Learning-assistant/pull/36) updates proxy-addr 2.0.7 → 2.0.8, shell-quote 1.8.3 → 1.12.0, websocket-driver 0.7.4 → 0.7.5 and vm2 3.11.2 → 3.12.2 within existing ranges. Only these four locked versions change; npm additionally recalculates peer metadata. References: [proxy-addr history](https://github.com/jshttp/proxy-addr/blob/master/HISTORY.md), [shell-quote changelog](https://github.com/ljharb/shell-quote/blob/main/CHANGELOG.md), [WebSocket advisory](https://github.com/faye/websocket-driver-node/security/advisories/GHSA-xv26-6w52-cph6), [vm2 advisory](https://github.com/patriksimek/vm2/security/advisories/GHSA-5h3f-q97h-ccvc). Fresh install, typecheck, lint, existing stream-client tests and tourist mini-program build pass. The [Taro snapshot](audits/taro-transitives-2026-10-22.json) retains the still-failing full audit; Swiper, decompress and propagated Taro component/runtime findings remain critical.

`npm explain` identifies vm2 under the webpack runner's prerender implementation, proxy-addr under Express, shell-quote under launch-editor, and websocket-driver under faye-websocket/sockjs. Ordinary build success does not exercise every optional prerender/dev-server path or establish bundle reachability. No untrusted project was executed, no development server was exposed publicly, and no real WeChat AppID/device acceptance was performed. The existing stream test is now part of Taro quality CI.

Both lockfiles were produced by npm, and their published Git blob hashes were checked against the local generated files. No integrity values were invented. Changed-package license metadata/files were inspected: most are MIT, electron-to-chromium is ISC, caniuse-lite is CC-BY-4.0, and websocket-driver is Apache-2.0. The existing attribution/distribution review remains open. These patches do not replace review of the pending Dependabot direct upgrades, final-candidate CI, image scans or historical rights work.

### Next.js re-check

The installed lockfile version is 16.4.2, React 19.3.0 and Sharp 0.35.5. The official Vercel advisories examined on this date list fixes at 16.4.1 for [GHSA-2464-fhr4-w9xw](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw) and [GHSA-673q-mjm6-r5xr](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr), and 16.3.6 for [GHSA-vcvr-r3jv-pc5j](https://github.com/vercel/next.js/security/advisories/GHSA-vcvr-r3jv-pc5j). The first also calls for Sharp >=0.35.5. The current versions satisfy those specific patched-version boundaries; this is not an assurance against every present/future advisory. Refresh the upstream security list and audit on the exact release lockfile.

## License and source inventory

Tooling: pip-audit 2.10.1, pip-licenses 5.5.5, detect-secrets 1.5.0, npm 11.9.0. `npm sbom --package-lock-only --sbom-format=cyclonedx` enumerated 432 Web and 1,283 Taro components (including optional/platform dependencies). Python inventory enumerated 95 distributions. License metadata is an input to review, not a legal conclusion; installed package license texts were spot-checked where metadata was incomplete.

| Component / source | Observed metadata or text | Distribution review still needed |
| --- | --- | --- |
| psycopg, psycopg-binary, psycopg-pool | LGPL-3.0 | Preserve notices; assess bundled binaries and corresponding source/relinking obligations |
| Sharp / platform libvips packages | Apache-2.0 and LGPL-3.0-or-later components | Review actual production image contents and bundled library notices |
| certifi, orjson; Web axe-core; Taro lightningcss, mdn-data, webpack-chain | MPL-2.0 or license expressions containing it | Preserve notices/source obligations for any distributed or modified covered files |
| caniuse-lite | CC-BY-4.0 | Preserve required data attribution in distributed build materials |
| node-forge | BSD-3-Clause OR GPL-2.0 | Evaluate the chosen permitted license branch; do not label every alternative expression incompatible |
| string.fromcodepoint 0.2.1 | SBOM metadata incomplete; installed LICENSE-MIT.txt and legacy `licenses` field identify MIT / Mathias Bynens | Preserve actual license text; no guessed license |
| lucide-react 0.475.0 | ISC; LICENSE also identifies Feather portions under MIT and their copyright | Keep upstream notices for redistributed icons |
| 16 PNG files across Web/Taro icon directories | No reliable author/source/license evidence established in this review | Owner to establish origin/permission or replace independently; code license does not grant third-party rights |
| Historical UI screenshots and old mini-program assets | No full image/content provenance or personal-data review | Review before inclusion in a release/demo; do not treat screenshots as fresh acceptance evidence |

The web layout uses system font families; no remotely loaded font was identified in that layout. This does not replace a final built-asset inventory. A complete copied-code ownership review and distribution-specific NOTICE bundle remain outstanding. No old question data is covered by the project license.

Main still uses mutable Action version tags. Draft [#37](https://github.com/Xiaomuw/Learning-assistant/pull/37) pins all 24 calls to verified official commits and disables credential persistence on all 13 checkouts, with redacted runtime checks and synthetic regressions. See its [scoped CI review](https://github.com/Xiaomuw/Learning-assistant/blob/security/pin-ci-actions-2026-10/docs/CI_SECURITY.md); the proposal remains unmerged. Existing Dependabot major-version PRs need compatibility review, including runtime deprecation notices. Docker uses mutable `python:*‑slim`, `node:22-alpine` and `pgvector/pgvector:pg16` tags. Neither tag review nor dependency-only audit substitutes for image scanning.

## Reproduce the dependency inventory

Use fresh environments and preserve private raw reports outside public logs if they contain local paths or registry URLs. Do not ignore audit exit codes: a nonzero vulnerability result is part of the evidence.

```bash
python3 -m venv /tmp/la-audit-tools
/tmp/la-audit-tools/bin/pip install pip-audit==2.10.1 pip-licenses==5.5.5 detect-secrets==1.5.0
# After a fresh backend dependency installation:
backend/.venv313/bin/python -m pip freeze > /tmp/la-resolved.txt
/tmp/la-audit-tools/bin/pip-audit --disable-pip --no-deps -r /tmp/la-resolved.txt -f json -o /tmp/la-python-audit.json
/tmp/la-audit-tools/bin/pip-licenses --python=backend/.venv313/bin/python --format=json --with-urls --with-license-file --no-license-path > /tmp/la-licenses.json
cd frontend
npm ci
npm audit --json
npm audit --omit=dev --json
npm sbom --package-lock-only --sbom-format=cyclonedx
cd ../frontend-weapp
npm ci
npm audit --json
npm sbom --package-lock-only --sbom-format=cyclonedx
```

The [sanitized snapshot](audits/dependency-review-2026-10-22.json) records resolved versions, advisory identifiers/fixes, license metadata and lockfile checksums. It is evidence, not a validated installation lock or an approved third-party notice bundle. Raw secret values and historical question text are not included.

## Secret review scope and limits

Current tracked files were scanned with `detect-secrets scan --no-verify` (110 heuristic candidates). A read-only full-clone scan inspected 1,718 unique reachable blobs across 162 commits, including 91 binary blobs that were inventoried but not text-scanned. Its detector used the same library's line-processing filters without credential verification; file-level exclusions differed from the CLI, so the 9,770 historical heuristic matches are not comparable with the current-tree count. Most historical entropy matches are npm integrity hashes or TypeScript build metadata. These are not confirmed exposed keys.

Manual spot-checks found test/example database credentials, validation fixtures, code references and a test-report password assignment. No provider-specific live API key was confirmed. This is **not** a clean-bill assertion: the historical fixture/password candidates have not all been owner-validated for non-reuse, binary images were not OCR-scanned, and unreachable/PR-only refs, external clones and caches were not covered. See the [history scope](GIT_HISTORY_EXPOSURE_REVIEW.md).

Candidate locations requiring owner confirmation include `docs/test-reports/h5-user-e2e-2026-06-02.md:90` (test-account password assignment) and historical `docker-compose.yml` (database/JWT example values). Do not publish their values. Confirm whether any were used on an accessible service or reused elsewhere; if so, rotate/revoke through the relevant owner account, invalidate sessions where applicable, then assess historical removal separately. No credential was tried against an external service, rotated or revoked, and no history was rewritten.

## Container and current-asset follow-up — 2026-10-23

Draft [#38](https://github.com/Xiaomuw/Learning-assistant/pull/38) at
`9c9993a5b510a9d623410c4678148757e82558e4` pins 15 references to four
registry-verified multi-platform image digests. Trivy 0.76.1 with vulnerability DB
updated `2026-10-23T01:18:09.482141619Z` scanned linux/amd64 only.
Python 3.12, Python 3.13, Node 22 Alpine and PGVector/PostgreSQL 16 report
44/0, 48/0, 11/0 and 113/16 HIGH/CRITICAL package-advisory pairs.
These are not unique exploit counts. All scanners exit 10; the wrapper exits 1.
The [hosted security gate](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39917546818)
reproduces the findings and uploads reports. No unfixed findings are filtered.
Seven application/Compose compatibility workflows pass. Pinning does not patch
these findings, and final built images, arm64 runtime and distribution licenses
still need review. Evidence JSON and reproduction commands are in that PR.

Draft [#39](https://github.com/Xiaomuw/Learning-assistant/pull/39) at
`6e521f5033e4deededbd4c7afc175b0b5f28727b` replaces the 16 current
navigation PNGs with traceable Lucide 0.475.0 derivatives, unmodified SVG sources
and complete ISC/Feather MIT notices. Source Git blob hashes match upstream.
This addresses only those current assets after review/merge; historical PNGs,
other media, original code and final distributed bundle obligations are not
cleared. See the [standards assessment](OPEN_SOURCE_STANDARDS_ASSESSMENT.md).
