# Learning Assistant

[简体中文](README.md) | **English**

Learning Assistant is an experimental, multi-client AI study assistant built with **FastAPI, LangGraph, LangChain, PostgreSQL/PGVector, Next.js and Taro**. It combines notebook-based retrieval-augmented question answering, multiple-choice practice, learning events, and knowledge-mastery tracking.

> **Project status:** Open-source readiness work is in progress. This is not a claim of production readiness, independent security review, or established public adoption. The pinned **Next.js 14.2.29** is within public security-advisory affected ranges: do not expose this build publicly before upgrading and validating compatibility ([issue #4](https://github.com/Xiaomuw/Learning-assistant/issues/4)). Check [current project status](docs/project-current-status.md) before deploying.

## Features and architecture

| Area | Implementation described in this repository |
| --- | --- |
| Knowledge | Notebook-based PDF/URL ingestion and PGVector retrieval |
| Orchestration | LearningOrchestratorGraph with dedicated QAGraph, QuestionGenerationGraph and MasteryEvaluationGraph |
| Practice | Multiple-choice questions, attempts and mastery snapshots |
| Web client | Next.js H5, including streamed responses |
| WeChat mini-program | Taro + React, with streaming and sync/polling fallback |
| Infrastructure | Docker Compose, PostgreSQL, configuration checks and test scripts |

The orchestrator decides which operation to perform; question answering, practice generation and mastery updates have distinct responsibilities. Consult [graph overview](docs/langgraph-overview.md) and [feature flows](docs/feature-flows.md) for details.

## Quick start (local development)

Prerequisites include Python 3.13, Node.js, PostgreSQL with PGVector, and provider credentials for any external model or service you enable. See the full [Chinese setup instructions](README.md) and [deployment guide](docs/DEPLOY.md) for details.

```bash
# From repository root:
cp backend/.env.example backend/.env
# Configure local credentials and database URLs in backend/.env.
docker compose up -d --build
```

Development host ports (from `docker-compose.yml`) are **5434 for Postgres, 8003 for FastAPI, and 3003 for Next.js**. The production Compose file is different. The developer-only default database password and published host ports are unsafe on an untrusted network; restrict access and never reuse these defaults for production.

For a native backend environment:

```bash
cd backend
python3.13 -m venv .venv313
source .venv313/bin/activate
pip install -r requirements.txt
python scripts/check_environment.py
python scripts/run_migrations_with_diagnostics.py
python scripts/bootstrap_app_data.py --confirm BOOTSTRAP_APP_DATA
python -m app.main
```

Do not commit real `.env` files, user content, credentials or personal data. The mini-program uses a generic `touristappid` by default; set `TARO_APP_ID` or `WECHAT_MINI_APP_ID` locally for your own WeChat application and keep `project.private.config.json` ignored.

## Validation

The repository includes backend, graph and frontend tests. To run the existing local test targets after installing dependencies:

```bash
make test-backend
make test-graphs
make eval-graphs
make check-frontend
make check-weapp
```

These commands have different environment requirements; see the [main README](README.md). GitHub Actions also checks architecture boundaries and builds the web/mini-program clients; these checks still do not exercise the complete backend. It does **not** replace authenticated smoke tests, live Postgres integration tests or deployment verification.

## Open source and contributing

- [Apache-2.0 license text](LICENSE) and [precise license scope](LICENSE-SCOPE.md)
- [Contributing](CONTRIBUTING.md) and [maintenance process](MAINTAINERS.md)
- [Security reporting](SECURITY.md)
- [Third-party dependency notice](THIRD_PARTY.md)
- [Open-source readiness checklist](docs/OPEN_SOURCE_READINESS.md), [data/release audit](docs/DATA_AND_RELEASE_AUDIT.md) and [web-collected question-bank remediation plan](docs/QUESTION_BANK_REMEDIATION.md)
- [Synthetic practice-question example](examples/README.md) (not a replacement for the full bank)

**Important:** The owner confirms AI used web search to collect existing online question banks before reorganizing 530 questions. The datasets are *not* covered by this project's Apache-2.0 grant; source licenses and redistribution permissions remain unverified. All 530 records have an ID-only [review ledger](data/provenance/408-source-review.csv); see the [remediation plan](docs/QUESTION_BANK_REMEDIATION.md). Do not redistribute or publish a release with these questions until the rights issue is resolved.

Project owner: [@Xiaomuw](https://github.com/Xiaomuw). Contributions and genuine user feedback are welcome.
