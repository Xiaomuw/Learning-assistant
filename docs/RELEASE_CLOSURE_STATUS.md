# Release closure status — 2026-10-23

**NO-GO. P0/P1/P2 are not all closed.** Main remains
`712c0538571d01129c0f8b1fb5488b35c9df6058`. Draft changes have not been merged.
This report distinguishes completed engineering evidence from rights, external
services and genuine adoption that cannot be established by editing a checklist.

## What was completed in this follow-up

| Proposal | Concrete change | Evidence |
| --- | --- | --- |
| [#40](https://github.com/Xiaomuw/Learning-assistant/pull/40), `f2db8ab` | Remove five file-scoped Hooks exceptions, initialize user-scoped state at mount, guard asynchronous responses, normalize local redirects and preserve manual trace collapse | Eight hosted workflows pass; strict Web lint has zero warnings; 18 redirect/panel cases and six real Chromium scenario groups |
| [#41](https://github.com/Xiaomuw/Learning-assistant/pull/41), `e9f81f3` | Inventory 33 baseline tracked assets; exclude historical reports from `git archive`; carry canonical project license/scope into all component build contexts and Taro output | Seven hosted workflows pass; 14 local script tests; real Taro build compares LICENSE.txt and scope bytes |
| [#42](https://github.com/Xiaomuw/Learning-assistant/pull/42) | Compose #29–#41 and #43 in one review-only branch; build and scan production images, inventory licenses/SBOM, validate isolated migration/proxy and synthetic dump/restore | See exact candidate results below; this PR is validation only, not a shortcut around individual reviews |
| [#43](https://github.com/Xiaomuw/Learning-assistant/pull/43), `f5e694c` | Remove unnecessary global npm/Corepack/Yarn and pip installer bundles from production runtime filesystems; start Next directly via Node | Actual container absence/import assertions, default-command HTTP smoke and combined image scans; no application dependency removed |
| [#29](https://github.com/Xiaomuw/Learning-assistant/pull/29) | Update the existing release documentation, standards assessment and factual program draft; provide a first-run feedback form | Documentation changes; no claimed external user feedback |

## Combined acceptance and its limits

The first complete combination, head `5292b0e9104f8412d6790a317924b27a914ae5bb`
(GitHub test merge `eba1ac335899b70d91141f77aaf2086277dfe0fe`), passed all eight
application workflows. The backend runner completed **74 modules / 679 tests**
without unittest skips. Its two vulnerability workflows failed on real findings.
This snapshot precedes #43's runtime reduction. Its exact input SHAs are retained
in #42's `docs/audits/candidate-inputs.json` and Git history.

The final tested head is **`13805cb8f5102acdaf4fae03a8c9ab4d75f65843`**, combining
the recorded #29–#41 inputs plus #43 `f5e694c`. GitHub tested merge SHA
`81b902e2b93245d72930b357b74746d67fabcd61`; both commits were verified to have
tree `1da506ab0de1bd7313b255c63c56908e93fac708`. Main did not change.
The later evidence-only update to #29 is not part of that functional snapshot.

| Actual command / workflow scope | Final result | Hosted run |
| --- | --- | --- |
| Fresh backend install, migrations/bootstrap, `python scripts/run_isolated_unittests.py`; production image import/installer-absence assertions | PASS: 74 modules / 679 tests, zero unittest skips | [39924777429](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777429) |
| `python scripts/smoke_real_auth.py --allow-disposable-db` plus PostgreSQL auth regressions | PASS: 24 real HTTP auth/SSE assertions; local SMTP and deterministic arithmetic, no LLM | [39924777413](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777413) |
| Clean clone, Docker Compose build/boot/migrate/health, `down --volumes`, boot again | PASS: two disposable boots | [39924777625](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777625) |
| Web `npm ci`, lint, CSS tests, build; Taro `npm ci`, lint/typecheck/build/stream tests, license/NOTICE byte comparisons; architecture/scripts | PASS | [39924777430](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777430) |
| Next build/typecheck/proxy smoke, `npm audit --omit=dev --audit-level=high`, production Docker default command and package-manager absence | PASS; production npm audit is not the full development audit | [39924777433](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777433) |
| Strict lint (`--max-warnings=0`), 18 helper cases, build/typecheck, actual Chromium harness | PASS: six scenario groups, two viewport sizes | [39924777397](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777397) |
| Public-data boundary and synthetic data on PostgreSQL | PASS; historical-rights release gate remains blocked | [39924777414](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777414) |
| Compose loopback/configuration isolation regressions | PASS | [39924777394](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777394) |
| `python scripts/scan_container_bases.py` | FAIL: real HIGH/CRITICAL findings remain | [39924777402](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777402) |
| Production Docker builds, `python3 scripts/check_production_stack.py`, `python3 scripts/scan_built_images.py --trivy ... --output-dir ...` | Packaging/runtime/license/backup checks PASS; vulnerability gate FAIL | [39924777395](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777395) |

The rebuilt frontend final filesystem has **0 HIGH / 0 CRITICAL** matches (previously
11/0); backend has **48 HIGH / 0 CRITICAL** (previously 52/0). All 48 remaining backend
package/advisory matches lack a FixedVersion in this scan. This is not a claim
that all severities, architectures, base/build images or OCI lower layers are clean.
The base PGVector image still reports 113 HIGH / 16 CRITICAL matches.
[Distribution reports, licenses and SBOM](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777395/artifacts/12489430896)
and a [sanitized durable snapshot](audits/candidate-verification-2026-10-23.json)
preserve image IDs, advisories, file hashes and exact scopes. No finding was suppressed.
The downloaded artifact ZIP's SHA-256 matches GitHub's digest.

Failures retained as evidence: the initial browser fixture omitted an auth cookie,
then incorrectly targeted an unused component instead of the chat's actual native
`details` element. Fixtures/selectors were corrected without weakening behavior
assertions. Taro initially copied extensionless `LICENSE` as a directory; an explicit
`LICENSE.txt` output and byte check fixed it. An earlier independent #41 backend run
hit the existing grace-response race; #30's independently reviewed repair is present
in the combined candidate. None of these failures was hidden by deleting a test.


The production Dockerfiles/Compose were built and exercised against disposable
PostgreSQL with **APP_ENV=development**. Startup with APP_ENV=production initially
failed because required production configuration, including real WeChat settings,
was unavailable. No fake provider credentials were supplied and that guard was
not weakened. Loopback health/login/proxy, migration and pg_dump/restore evidence
is a packaging/compatibility check, not production-mode, TLS or real-WeChat acceptance.

The browser harness runs the actual production-built Next UI at 1280×900 and
390×844 with explicitly intercepted **synthetic API responses**. It covers safe
login redirects, stream trace open/collapse and nonpersistence, cached practice
resume/answer persistence, profile retrieval and dashboard error/retry. It uses
Chromium, not Safari/Firefox or a physical phone. Its synthetic auth cookie only
satisfies middleware presence checks; real backend auth is verified separately.
Neither the browser recording nor the deterministic HTTP SSE test calls a model.

[Recorded screenshots, six WebM clips and results](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39923429262/artifacts/12487754107)
come from that actual browser run, not generated UI. They contain synthetic users
and questions. The mobile chat screenshot was visually inspected. Artifacts expire
on 2026-11-06; download them before expiry or reproduce the pinned browser workflow.
They are a scoped UI demonstration, not an accepted live AI-product demonstration.
The [final-candidate recording](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39924777397/artifacts/12488892519)
also passes the same six scenario groups.

Local checks: `python -m unittest discover -s scripts/tests -v` (24 candidate
script tests), architecture boundaries (9 tests), `actionlint`, Python compilation
and `git diff --check` pass. The isolated #40 client passed strict lint, 18 helper
cases, TypeScript and a local webpack production build using existing dependencies.
Local Playwright execution was blocked by unavailable Chromium and a malformed
browser download; hosted clean installation/browser execution supplies the evidence.
No local Docker run is claimed.

## Unclosed items and the evidence needed

| Priority / item | Current disposition | Required next evidence or action |
| --- | --- | --- |
| P0 JavaScript | #35/#36 reduce compatible findings, but full Web/Taro audits still fail | Review each remaining advisory and dependency path. Taro 4.3.0 registry metadata still pins Swiper 11.1.15; braces registry versions end at 3.0.3 with no advertised fix for the recorded advisory. A major upgrade alone is not clearance; evaluate a tested upstream patch/fork or component replacement |
| P0 container vulnerabilities | Exact bases and final images have been scanned; findings remain visible | Resolve/rebuild affected OS/runtime components or document a component-specific, evidence-backed disposition. Do not accept scanner silence from exclusions as remediation |
| P0 original-code rights | No owner authorship/copy-source attestation received | Owner supplies original authorship and contributor/employer authority, plus source/license evidence for copied snippets; Git author metadata is not proof of rights |
| P0 historical 530-question corpus | Current trees remain clear; history remains exposed and rights unverified | Owner supplies source permissions or separately approves a remediation plan. Do not republish questions, fabricate provenance or rewrite history in this task |
| P0 other materials / privacy | #39 replaces 16 navigation PNGs; #41 inventories baseline paths/hashes and excludes 17 historical screenshots/reports from source archives | Review remaining media and screenshot rights/personal data; new icons and export-ignore do not erase Git objects, clones, caches or previous archives |
| P0 distribution licenses | Canonical project licenses and icon notices are packaged; built-image license inventory and CycloneDX SBOM now exist | Review actual shipped components and preserve their exact texts/notices; satisfy applicable LGPL/GPL source/relinking and other obligations. Metadata detection is neither a violation finding nor a redistribution approval. OCI lower layers must be considered too |
| P1 Hooks | Implemented/tested in #40; issue #8 is still open and main unchanged | Maintainer review/merge, then verify final main; do not close the issue solely because a Draft is green |
| P1 external/browser/device/deployment | Chromium and isolated production-image packaging verified; other environments unverified | Authorized disposable HTTPS staging, actual WeChat/SMTP configuration, physical iOS/Android devices and Safari/Firefox; separately approved model/embedding/search budget if used |
| P2 demo and external feedback | Real synthetic-API UI recordings exist; genuine external adoption not established | Record an accepted real-service demo only after its prerequisites; collect voluntary actual first-run reports with the new issue template. No outreach, testimonials or simulated users were manufactured |

The owner should provide only factual source/rights references in discussion.
Configure service secrets privately in an approved sandbox; never post raw keys,
cookies, private email, learner documents or Organization IDs in GitHub/chat.
There is no request here to merge, publish, deploy, revoke keys or rewrite history.

## Open-source assessment

The Apache-2.0 license choice and public contribution foundation are appropriate
for material the licensor is authorized to distribute. The current evidence does
**not** establish complete lawful redistribution or this project's release gates.
The Open Source Definition does not impose a star count, zero vulnerabilities or
a public production deployment; these are separate from our release policy.
See [standards assessment](OPEN_SOURCE_STANDARDS_ASSESSMENT.md) and the
[dependency evidence](DEPENDENCY_SECURITY_REVIEW.md). Broad external adoption
remains unproven; program admission is an independent decision by OpenAI.
