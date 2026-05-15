.PHONY: test-backend test-backend-postgres test-graphs eval-graphs eval-graphs-remote smoke-backend check-backend-env check-frontend check-weapp check-whitespace check-project

test-backend:
	LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false GRAPH_EVAL_LANGSMITH=false backend/.venv313/bin/python -m unittest discover -s backend/tests -t .

test-backend-postgres:
	@test -n "$$TEST_DATABASE_URL" || (echo "TEST_DATABASE_URL is required for make test-backend-postgres" >&2; exit 2)
	@case "$$TEST_DATABASE_URL" in *__tests_only__*) echo "TEST_DATABASE_URL must not contain __tests_only__ placeholder" >&2; exit 2;; *) true;; esac
	@case "$$TEST_DATABASE_URL" in postgres://*|postgresql://*|postgresql+psycopg://*) true;; *) echo "TEST_DATABASE_URL must be a PostgreSQL DSN" >&2; exit 2;; esac
	POSTGRES_TEST_STRICT=true LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false GRAPH_EVAL_LANGSMITH=false backend/.venv313/bin/python -m unittest discover -s backend/tests -t .

test-graphs:
	LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false GRAPH_EVAL_LANGSMITH=false backend/.venv313/bin/python -m unittest \
		backend.tests.test_agent_graph_contracts \
		backend.tests.test_route_decider \
		backend.tests.test_orchestrator_intent_rules \
		backend.tests.test_child_invokers \
		backend.tests.test_tooling_contracts \
		backend.tests.test_learning_orchestrator_graph \
		backend.tests.test_quiz_request_resolver \
		backend.tests.test_cross_graph_contracts \
		backend.tests.test_graph_persistence_repositories \
		backend.tests.test_graph_facts_backfill \
		backend.tests.test_graph_migrations \
		backend.tests.test_qa_graph_adapter \
		backend.tests.test_qa_graph_runtime_adapter \
		backend.tests.test_question_generation_graph_adapter \
		backend.tests.test_mastery_graph_adapter \
		backend.tests.test_graph_eval_runner \
		backend.tests.test_practice_source_normalization \
		backend.tests.test_practice_graph_facts

eval-graphs:
	cd backend && LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false GRAPH_EVAL_LANGSMITH=false ./.venv313/bin/python -m app.orchestration.graphs.eval_runner

eval-graphs-remote:
	cd backend && GRAPH_EVAL_LANGSMITH=true LANGSMITH_TRACING=$${LANGSMITH_TRACING:-true} LANGCHAIN_TRACING_V2=$${LANGCHAIN_TRACING_V2:-true} ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --all

smoke-backend:
	cd backend && ./.venv313/bin/python scripts/smoke_backend.py

check-backend-env:
	cd backend && ./.venv313/bin/python scripts/check_environment.py

check-frontend:
	cd frontend && npm run lint
	cd frontend && npm run build

check-weapp:
	cd frontend-weapp && npm run typecheck
	cd frontend-weapp && npm run lint
	cd frontend-weapp && ./node_modules/.bin/taro build --type weapp --no-check

check-whitespace:
	git diff --check

check-project: check-backend-env test-backend test-graphs eval-graphs check-frontend check-weapp check-whitespace
