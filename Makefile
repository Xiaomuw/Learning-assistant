.PHONY: test-backend test-graphs eval-graphs eval-graphs-remote

test-backend:
	LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false GRAPH_EVAL_LANGSMITH=false backend/.venv313/bin/python -m unittest discover -s backend/tests

test-graphs:
	LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false GRAPH_EVAL_LANGSMITH=false backend/.venv313/bin/python -m unittest \
		backend.tests.test_agent_graph_contracts \
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
