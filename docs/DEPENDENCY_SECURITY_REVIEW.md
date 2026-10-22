# Dependency, license and secret review — 2026-10-22

**Partial, reproducible review; not a comprehensive security audit or legal clearance. Publication remains NO-GO.** Baseline: `712c0538571d01129c0f8b1fb5488b35c9df6058`. Audit scope is source dependencies freshly resolved on Linux/Python 3.12.14 and the two committed npm lockfiles, not deployed image operating-system packages or external services.

## Security findings

| Scope | Observed result | Required action |
| --- | --- | --- |
| Python, 95 resolved distributions | 5 affected packages: pypdf 5.4.0, python-multipart 0.0.20, Starlette 0.46.2, Requests 2.32.3, python-dotenv 1.1.0 | Patch, test and re-audit; overlapping advisory IDs must not be counted as distinct exploits |
| Python with proposed #31 pins | Requests 2.34.2 and python-dotenv 1.2.4 no longer reported; 3 affected packages remain | #31 is a narrow mitigation, not a clean audit |
| Web `npm audit --omit=dev` | 0 findings | Limited to production dependency scope and this audit date |
| Web full `npm audit` | 10 findings: 9 high, 1 moderate | Review build/dev chains (including Tailwind/PostCSS, glob/micromatch and Next ESLint chain); production audit does not cover these |
| Taro full `npm audit` | 83 findings: 8 critical, 51 high, 23 moderate, 1 low | Separate compatible upgrade work and bundle reachability review |
| Docker images / OS packages | Not scanned | Resolve image digests, scan actual built images and evaluate deployed reachability |

Taro's eight critical affected package nodes include `@tarojs/components`, `@tarojs/taro`, `decompress`, `proxy-addr`, `shell-quote`, `swiper`, `vm2` and `websocket-driver`. These are package/advisory propagation counts, not eight independently confirmed runtime vulnerabilities. Investigate bundled components such as Swiper separately from build tooling. Some automatic npm suggestions would downgrade Taro to 3.x; do not run `npm audit fix --force` as a release strategy.

pypdf handles user-supplied PDFs; multipart/Starlette sit on request parsing and serving boundaries. Their pending advisories deserve P0 review before public deployment. Do not override Starlette beyond FastAPI 0.115.12's declared range: upgrade FastAPI/Starlette/SSE coherently with upload, authentication, error and streaming regressions. A pypdf major upgrade needs parser fixtures and compatibility checks. New advisory feed entries and exploitability still require individual maintainer assessment.

[PR #31](https://github.com/Xiaomuw/Learning-assistant/pull/31) patches only Requests and python-dotenv. Local tests exercise real loopback HTTP extraction and dotenv override/interpolation; related ingest/configuration tests passed (37). Requests upstream notices: [netrc leakage](https://github.com/psf/requests/security/advisories/GHSA-9hjg-9r4m-mvj7), [temporary-file handling](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2). See also the [dotenv changelog](https://github.com/theskumar/python-dotenv/blob/main/CHANGELOG.md). No paid API was used.

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

GitHub Actions use version tags (`checkout@v4`, `setup-python@v5`, `setup-node@v4`), not immutable commit pins. Existing Dependabot major-version PRs need compatibility review, including runtime deprecation notices. Docker uses mutable `python:*‑slim`, `node:22-alpine` and `pgvector/pgvector:pg16` tags. Neither tag review nor dependency-only audit substitutes for image scanning.

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
