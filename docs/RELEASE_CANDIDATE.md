# Proposed v0.1.0-rc.1 — release candidate runbook

**Decision: NO-GO for publication (2026-10-23).** This is preparation, not a tagged or published release. No existing Git tags or GitHub Releases were found. `v0.1.0-rc.1` is a proposal for maintainer approval; individual frontend package versions are not evidence of a repository release.

Use the [verification ledger](RELEASE_VERIFICATION.md), [dependency review](DEPENDENCY_SECURITY_REVIEW.md), [history review](GIT_HISTORY_EXPOSURE_REVIEW.md), and [draft notes](../CHANGELOG.md) together. Evidence on separate PR heads does not validate their future merged combination. Re-run all gates on the exact final commit before tagging.

## Scope and limitations

The code provides LangGraph orchestration with QA, question-generation and mastery graphs, a FastAPI API, PostgreSQL/PGVector persistence, a Next.js web client, and a Taro client. Deterministic rule paths and synthetic tests are useful without API keys. General tutoring, model-generated exercises and real document embedding require configured providers; their quality, cost and availability have not been accepted in this review.

This is an experimental developer project. It has no verified external adoption or production-readiness claim. Current-tree removal of unverified question data does not erase Git history. Uploaded documents must be owned or licensed for the intended use. The two independently authored example questions are in `examples/practice_questions.json`.

## Environment

| Component | Tested / required baseline |
| --- | --- |
| Native backend / hosted CI | Python 3.13; clean local dependency installation also tested on 3.12.14 |
| Development Docker backend | `python:3.12-slim`; production recipe uses `python:3.13-slim` |
| Node / npm | Node 22 in CI and Docker; local checks used Node 24.19.0 / npm 11.9.0 |
| Web | Next.js 16.4.2 / React 19.3.0, committed npm lockfile |
| Mini program | Taro 4.2.0, committed npm lockfile; real WeChat validation needs owner AppID |
| Database | PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`) |
| Containers | Docker Engine with Compose v2; free loopback ports 5434, 8003, 3003 |

Python requirements contain version ranges and do not provide a complete transitive, hash-locked environment. Main Docker tags are mutable; Draft #38 and combined #42 pin base-image digests, while apt/Python transitives remain unresolved ranges. Successful fresh installs are evidence for the recorded date, not bit-for-bit future reproducibility. Resolve and test a lock/digest policy before distributing release images.

## Fresh, isolated Docker installation without paid APIs

Use a new directory and a host without another Learning-assistant Compose stack. The development file specifies fixed `la-*` container names and ports, so a different Compose project name alone does not remove collisions. Do not run these cleanup commands against a working or production installation.

```bash
git clone https://github.com/Xiaomuw/Learning-assistant.git learning-assistant-rc-check
cd learning-assistant-rc-check
git rev-parse HEAD
# Validation-only candidate SHAs and limits: docs/RELEASE_CLOSURE_STATUS.md.
# Check out the explicitly reviewed SHA; there is no rc tag or release approval.
python3 - <<'ENV'
import secrets
from pathlib import Path
assert not Path('.env').exists() and not Path('backend/.env').exists(), 'Use a fresh clone'
Path('.env').write_text(
    'POSTGRES_DB=learning_assistant_compose_ci\nPOSTGRES_USER=la_compose_ci\n'
    f'POSTGRES_PASSWORD={secrets.token_urlsafe(40)}\n')
Path('backend/.env').write_text(
    f'JWT_SECRET_KEY={secrets.token_hex(32)}\n'
    'CORS_ALLOW_ORIGINS=http://127.0.0.1:3003\n'
    'RUN_ALEMBIC_UPGRADE=true\nRUN_BOOTSTRAP_APP_DATA=true\n'
    'RUN_BUILTIN_NOTEBOOK_SEED=false\nENABLE_GRAPH_FACTS=false\n'
    'ENABLE_GRAPH_DUAL_WRITE=false\nENABLE_PRACTICE_FINALIZER_WORKER=false\n'
    'MCP_ENABLED=false\nLANGSMITH_TRACING=false\nLANGCHAIN_TRACING_V2=false\n'
    'GRAPH_EVAL_LANGSMITH=false\n')
for name in ('.env', 'backend/.env'):
    Path(name).chmod(0o600)
ENV
docker compose -p la-ci -f docker-compose.yml config --quiet
docker compose -p la-ci -f docker-compose.yml build --parallel
docker compose -p la-ci -f docker-compose.yml up -d --no-build
```

Allow startup migrations/bootstrap to finish. Open <http://127.0.0.1:3003/login>. Health is at <http://127.0.0.1:8003/health>. PostgreSQL is on `127.0.0.1:5434` from the host, but `postgres:5432` inside Compose. The frontend server proxies to `http://backend:8000/api`; browser requests use `/api`.

On the test branch in [PR #30](https://github.com/Xiaomuw/Learning-assistant/pull/30), `python3 scripts/check_compose_stack.py` waits for liveness/login, checks loopback port bindings, and expects anonymous `/api/auth/me` to return 401. It does not equate `/health` with database readiness. Run migrations and bootstrap explicitly to verify the database:

```bash
docker compose -p la-ci -f docker-compose.yml exec -T backend alembic upgrade head
docker compose -p la-ci -f docker-compose.yml exec -T backend python scripts/bootstrap_app_data.py --confirm BOOTSTRAP_APP_DATA
docker compose -p la-ci -f docker-compose.yml exec -T backend alembic current
docker compose -p la-ci -f docker-compose.yml exec -T backend alembic heads
```

This keyless stack checks installation and service boundaries. It does not enable public registration: normal registration requires SMTP. The automated real-auth script below supplies an isolated local SMTP sink. Do not insert a real mail password or paid model key merely to run CI.

Stop without discarding data using `docker compose -p la-ci -f docker-compose.yml down`. To validate **disposable** empty-volume recovery, use `down --volumes --remove-orphans`, then `up -d --no-build`, and repeat the checks/migration/bootstrap. This destroys the test database. PR #30 automates both boots. Finally stop and remove the disposable volumes and generated `.env` files from this dedicated clone.

## Native setup and synthetic data

Create a new virtual environment, not an old development environment:

```bash
cd backend
python3.13 -m venv .venv313
. .venv313/bin/activate
python -m pip install --no-cache-dir -r requirements.txt
python -m pip check
```

Set `DATABASE_URL` to an isolated PostgreSQL/pgvector database with privileges to create the extension and test schemas. Set a new random `JWT_SECRET_KEY` and explicit localhost CORS. Use `backend/.env.example` as a reference; placeholder keys are not credentials. Do not copy the example model endpoint/key into a keyless test environment. See [CONTRIBUTING](../CONTRIBUTING.md) for the CI environment flags.

```bash
alembic upgrade head
python scripts/bootstrap_app_data.py --confirm BOOTSTRAP_APP_DATA
python scripts/import_questions.py ../examples/practice_questions.json --dry-run
# Optional, only in this disposable DB; this command inserts the two examples:
python scripts/import_questions.py ../examples/practice_questions.json
```

The importer validates canonical taxonomy and uses the database even in dry-run mode. It does not make historical questions lawful, and importing examples is not embedding/retrieval acceptance. Never restore the removed 530-question JSONs.

From the repository root, install each JS project independently:

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
INTERNAL_API_BASE=http://127.0.0.1:8000/api npm run build
npm run smoke:proxy
cd ../frontend-weapp
npm ci
npm run typecheck
npm run lint
npm run build:weapp
npm run test:chat-stream
```

`smoke:proxy` uses a fake backend; its SSE frames do not prove a real model or FastAPI stream. The mini-program build uses tourist development configuration, not a signed/distributed WeChat application.

## Repeatable acceptance commands

From `backend`, set `TEST_DATABASE_URL` and `DATABASE_URL` to the same **disposable** database, `POSTGRES_TEST_STRICT=true`, `ENABLE_GRAPH_FACTS=true`, `ENABLE_GRAPH_DUAL_WRITE=false`, and the other flags in `.github/workflows/backend-full-suite.yml`. Then run:

```bash
python -m compileall -q app tests
alembic upgrade head
python scripts/bootstrap_app_data.py --confirm BOOTSTRAP_APP_DATA
python scripts/run_isolated_unittests.py
```

The runner uses a fresh process per test module to isolate module-level mocks/environment changes. Do not replace it with a single-process discovery run or count skipped PostgreSQL tests as acceptance. Temporary schemas are created and dropped only in the supplied test database.

The real HTTP test requires an already built frontend and installed backend dependencies. From the root:

```bash
python scripts/smoke_real_auth.py --allow-disposable-db
```

Read the script's guards first: it uses the exact loopback database `learning_assistant_web_e2e_test`, refuses existing application `.env` files, starts real local FastAPI/Next processes and a local SMTP sink, and owns cleanup. Reproduce its database/service configuration from `.github/workflows/backend-auth-regression.yml`. Run it in a separate fresh clone, not the Docker clone above. PR #30 extends its 18 auth assertions with six real SSE/protocol assertions for deterministic arithmetic; no LLM is involved.

Run architecture/data checks from the root:

```bash
python -m unittest discover -s backend/tests -p test_architecture_boundaries.py -v
python -m unittest discover -s scripts/tests -p 'test_*.py' -v
python scripts/audit_question_bank_provenance.py
python scripts/audit_question_bank_provenance.py --release-gate
```

The last command is expected to fail while the historical provenance ledger remains `REVIEW_REQUIRED`; retain that failure as a release blocker. Consult the workflow filenames if commands change.

## Migration, backup and rollback

`alembic upgrade head` changes schema and some historical revisions also change data. Bootstrap writes canonical metadata. A code rollback or `alembic downgrade` is not a data restore. PR #30 prevents future question JSON corruption but cannot reconstruct option text/review lists already summarized in existing rows; inspect affected records and re-import/regenerate only from authorized sources with owner approval. Before any future non-disposable upgrade, the operator must take an access-controlled PostgreSQL backup, preserve the matching uploaded documents and configuration separately, and test restoration into an isolated database. Do not put dumps, keys or user uploads in Git/CI artifacts.

Record the starting Alembic revision and candidate SHA. Inspect every revision between them, including destructive operations. Prove a restore on the target PostgreSQL/pgvector version, validate row counts, auth, retrieval and schema heads, and rehearse reverting the application against the restored database. No production upgrade, downgrade, backup or recovery exercise was performed here. Dropping Compose volumes irreversibly removes that local database unless a usable backup exists. Changing embedding dimensions/providers can require a separate re-index and compatibility plan.

## Release Go / No-Go table

| Gate | Decision / evidence |
| --- | --- |
| Governance, code license, current-tree data boundary | GO for foundation only; merged #3/#6, CI and current-tree inventory |
| Fresh dependency installs and client builds | Combined #42 PASS for recorded environment; image digests pinned; complete Python/apt locks remain open |
| Database migration, bootstrap, auth and service smoke | Combined candidate PASS; exact SHAs, workflow URLs and limitations in [closure report](RELEASE_CLOSURE_STATUS.md); maintainer review remains |
| Real question persistence and learning-cycle regression | PR #30 fixes reproduced question JSON corruption; strict PostgreSQL exact-head suite PASS, review pending |
| Python / JS / image vulnerabilities | NO-GO: Python fixes proposed in #31/#32/#34 have a clean combined local audit but remain unmerged; Web/Taro and scanned OS/image findings remain open |
| Third-party licenses and embedded assets | NO-GO: inventory prepared; redistribution obligations/asset provenance not fully closed |
| Historical question-bank rights/exposure | NO-GO: rights unresolved; ordinary branch heads clear, old blobs still reachable |
| Secret scan / historical test-account reuse | Partial review; owner must confirm candidate fixture credentials were never reused |
| Live model / real embedding RAG | Not run; owner-provided sandbox credentials and explicit spend approval needed |
| Chromium UI / synthetic restore | Scoped PASS in #40/#42; intercepted browser APIs and disposable dump/restore do not validate live services or existing data |
| Other browsers, physical devices, real WeChat/SMTP, production-mode HTTPS staging | Not run; sandbox resources/configuration and manual acceptance needed |
| Published tag/release/image/deployment | Not authorized in this task; none created |

A public-source repository, green CI, or an Apache-2.0 file alone does not satisfy these gates.

## Current browser and distribution evidence

See [closure status](RELEASE_CLOSURE_STATUS.md) for the actual browser recordings,
combined SHA and final-image findings. Reproduce `frontend/scripts/test-safe-next.mjs`
and the pinned Playwright workflow on #40/#42. The candidate production workflow
builds Dockerfiles, verifies packaged project licenses byte-for-byte, migrates a
fresh database, exercises loopback APIs and restores a synthetic backup. It uses
APP_ENV=development: the real production guard requires owner service settings.
No paid provider, real account, live database or public deployment is used.
