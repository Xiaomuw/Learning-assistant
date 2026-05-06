.PHONY: test-graphs eval-graphs eval-graphs-remote

test-graphs:
	LANGSMITH_TRACING=false GRAPH_EVAL_LANGSMITH=false backend/.venv313/bin/python -m unittest \
		backend.tests.test_agent_graph_contracts \
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
	cd backend && LANGSMITH_TRACING=$${LANGSMITH_TRACING:-$${GRAPH_EVAL_LANGSMITH:-false}} GRAPH_EVAL_LANGSMITH=$${GRAPH_EVAL_LANGSMITH:-false} ./.venv313/bin/python -m app.orchestration.graphs.eval_runner

eval-graphs-remote:
	cd backend && GRAPH_EVAL_LANGSMITH=true LANGSMITH_TRACING=$${LANGSMITH_TRACING:-true} ./.venv313/bin/python -m app.orchestration.graphs.langsmith_eval --all
