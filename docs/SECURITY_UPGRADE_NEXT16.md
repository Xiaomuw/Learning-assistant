# Next.js 16 migration and real authentication verification — merged PR #7

**Current status (2026-10-22): merged into main; no production deployment or version release has been performed.** The tests below are evidence of the verified scope, not a full production security certification.

## Candidate versions and scope

The web client on the original default branch pins Next.js `14.2.29`. This proposal uses **Next.js 16.4.2**, **React / React DOM 19.3.0**, Node 22 and updated ESLint/TypeScript tooling. Version changes and passing CI do not establish the absence of all vulnerabilities.

Upstream references for independent review:
- https://nextjs.org/support-policy
- https://github.com/vercel/next.js/security/advisories
- https://github.com/vercel/next.js/releases/tag/v16.4.2
- https://nextjs.org/docs/app/guides/upgrading/version-16

## Stacked review order

This security PR is now stacked on the **data-free OSS candidate**, not the old default branch:

1. [PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6) merged: removes the five question-bank JSON files from the current main tree.
2. [PR #3](https://github.com/Xiaomuw/Learning-assistant/pull/3) merged: adds Apache-2.0 scope, governance, documentation and the historical provenance ledger.
3. [PR #7](https://github.com/Xiaomuw/Learning-assistant/pull/7) merged: adds the Next.js migration, real authentication regression and HTTP integration.

After separate owner approval, merge in dependency order, retarget dependent PRs to `main` as appropriate, and recheck their final diff and CI. Nothing here authorizes an automatic merge, old-branch deletion or history rewrite.

## Migration changes

- Replace `next lint` with ESLint 9 flat configuration.
- Move `middleware.ts` to `proxy.ts` and export `proxy`.
- Await Next.js asynchronous `cookies()` calls.
- Use Node 22 Docker base images and copy `public/` assets into the production image.
- Update React 19 TypeScript declarations.
- Use a committed npm lockfile generated from registry metadata rather than fabricated integrity fields. The temporary branch-only lockfile generation workflow has been removed.
- Preserve limited file-scoped `react-hooks/set-state-in-effect` exceptions for five existing components. Refactoring and the remaining lint warnings are tracked in [Issue #8](https://github.com/Xiaomuw/Learning-assistant/issues/8), not declared resolved here.

## Verified evidence on commit `684fa0b` — 2026-10-21

All four workflows completed successfully on the same integrated candidate:

| Workflow | Evidence and scope |
| --- | --- |
| [Quality checks](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39632733852) | Python/architecture/provenance checks and web/mini-program lint/build checks |
| [Next 16 migration verification](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39632733862) | Reproducible npm install, TypeScript, production build, mock-backend HTTP/SSE smoke, production dependency audit, Docker build and login-route health |
| [Public question-data boundary](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39632733838) | Removed-corpus boundary and synthetic-question import/rebuild tests using disposable PostgreSQL |
| [Real backend authentication regression](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39632733869) | 22 existing authentication regressions plus 18 new real HTTP assertions described below |

Earlier migration run [39618628848](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39618628848) reported zero production npm advisory findings and successful Docker `/login` HTTP 200. This is a point-in-time package advisory check, **not** a full application or backend security audit.

### Existing authentication regression: 22 tests

The authentication job runs `tests.test_auth_api` (12), `tests.test_auth_refresh_replay` (4), and `tests.test_auth_verification` (6), separately. The API tests use an isolated real PostgreSQL database and FastAPI TestClient; some external email/WeChat calls and unit-test dependencies are intentionally mocked. The 22 tests are not all live-network end-to-end tests.

### New HTTP integration: 18 assertions

`scripts/smoke_real_auth.py` starts the actual complete FastAPI application under Uvicorn and a built Next.js production server. All authentication requests go through Next.js to FastAPI and a disposable PostgreSQL/PGVector database. The normal migration chain and bootstrap run successfully before startup; the test does not bypass application readiness.

Checks passed for anonymous page redirects and API rejection; verification-code delivery; registration persistence; forwarding both HttpOnly authentication cookies; current-user lookup; protected page access; refresh-token rotation; logout and cookie deletion; post-logout rejection; wrong-password rejection; valid login; password change; old-password rejection; new-password login; and rejection of a forged frontend cookie by the actual backend API.

The only external-service replacement in this HTTP test is a **loopback SMTP sink**. The application's real SMTP client sends a real MIME message to that local server, but no email leaves the CI runner. Authentication routes, token generation, cookie processing and persistence are not mocked in this test.

## Safety constraints

- The smoke requires `--allow-disposable-db`, a loopback database host and the exact database name `learning_assistant_web_e2e_test`.
- It refuses a checkout with actual root/backend `.env` files and requires a built frontend.
- It uses fresh synthetic identities and randomly generated test secrets, and shuts down local services afterward.
- It does not use production databases, external mail accounts, LLM credentials, private datasets or a live deployment.
- A forged cookie may pass the frontend's presence-only navigation gate; it **does not** authorize the backend API, as verified by the HTTP test.

## Still not verified / release limitations

- Real LLM-backed chat, RAG retrieval quality and actual backend SSE response delivery. The existing SSE smoke still uses a mock backend.
- Browser-click flows, responsive layouts, `next/image`, external SMTP delivery, public TLS, production proxy/CORS settings and full staging acceptance.
- The full backend suite, all dependency licenses/advisories, source ownership, historical Git content and other active branches holding old question JSON.
- A clean install/build currently allows Next.js to normalize TypeScript configuration; persist that normalization in a focused follow-up to avoid build-time configuration drift.
- Genuine third-party adoption and an approved public release. CI success is not OpenAI program acceptance or proof of ecosystem impact.

Remaining items are real-model RAG/chat/SSE, browser/mobile acceptance, external email delivery, public TLS/CORS/proxy, staging, full dependency/ownership review, and historical/other-branch question data. These are not represented as completed by the merged PR. Related: [Issue #4](https://github.com/Xiaomuw/Learning-assistant/issues/4), [Issue #5](https://github.com/Xiaomuw/Learning-assistant/issues/5).
