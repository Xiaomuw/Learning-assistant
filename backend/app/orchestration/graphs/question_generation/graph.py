from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.orchestration.graphs.question_generation.adapter import (
    DeterministicQuestionCandidateGenerator,
    InMemoryLearningEventRepository,
    InMemoryQuestionItemRepository,
    QuestionCandidateGenerator,
    QuestionCandidateRepairer,
    LegacyPracticeQuestionCandidateGenerator,
)
from app.orchestration.graphs.question_generation.nodes import (
    build_blueprint_node,
    compose_response_node,
    difficulty_calibrator_node,
    make_dedupe_checker_node,
    make_generate_candidates_node,
    make_persist_question_items_node,
    make_repair_candidates_node,
    make_solver_verifier_node,
    prepare_source_refs_node,
    quality_reviewer_node,
    route_after_quality_reviewer,
    QuestionQualityVerifier,
)
from app.orchestration.graphs.question_generation.state import QuestionGenerationState
from app.persistence.interfaces import LearningEventRepository, QuestionItemRepository
from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled


def build_graph(
    *,
    candidate_generator: QuestionCandidateGenerator | None = None,
    candidate_repairer: QuestionCandidateRepairer | None = None,
    quality_verifier: QuestionQualityVerifier | None = None,
    question_item_repository: QuestionItemRepository | None = None,
    learning_event_repository: LearningEventRepository | None = None,
) -> StateGraph:
    generator = candidate_generator or DeterministicQuestionCandidateGenerator()
    repairer = candidate_repairer or (generator if hasattr(generator, "repair") else DeterministicQuestionCandidateGenerator())
    question_repo = question_item_repository or InMemoryQuestionItemRepository()
    event_repo = learning_event_repository or InMemoryLearningEventRepository()

    graph = StateGraph(QuestionGenerationState)
    graph.add_node("build_blueprint", build_blueprint_node)
    graph.add_node("prepare_source_refs", prepare_source_refs_node)
    graph.add_node("generate_candidates", make_generate_candidates_node(generator))
    graph.add_node("solver_verifier", make_solver_verifier_node(quality_verifier))
    graph.add_node("quality_reviewer", quality_reviewer_node)
    graph.add_node("repair_candidates", make_repair_candidates_node(repairer))
    graph.add_node("dedupe_checker", make_dedupe_checker_node(question_repo))
    graph.add_node("difficulty_calibrator", difficulty_calibrator_node)
    graph.add_node(
        "persist_question_items",
        make_persist_question_items_node(
            question_item_repository=question_repo,
            learning_event_repository=event_repo,
        ),
    )
    graph.add_node("compose_response", compose_response_node)

    graph.set_entry_point("build_blueprint")
    graph.add_edge("build_blueprint", "prepare_source_refs")
    graph.add_edge("prepare_source_refs", "generate_candidates")
    graph.add_edge("generate_candidates", "solver_verifier")
    graph.add_edge("solver_verifier", "quality_reviewer")
    graph.add_conditional_edges(
        "quality_reviewer",
        route_after_quality_reviewer,
        {"repair": "repair_candidates", "continue": "dedupe_checker"},
    )
    graph.add_edge("repair_candidates", "solver_verifier")
    graph.add_edge("dedupe_checker", "difficulty_calibrator")
    graph.add_edge("difficulty_calibrator", "persist_question_items")
    graph.add_edge("persist_question_items", "compose_response")
    graph.add_edge("compose_response", END)
    return graph


def build_production_graph(
    *,
    candidate_generator: QuestionCandidateGenerator | None = None,
    candidate_repairer: QuestionCandidateRepairer | None = None,
    quality_verifier: QuestionQualityVerifier | None = None,
) -> StateGraph:
    repairer = candidate_repairer or (
        candidate_generator
        if candidate_generator is not None and hasattr(candidate_generator, "repair")
        else LegacyPracticeQuestionCandidateGenerator()
    )
    if not is_graph_facts_enabled():
        return build_graph(candidate_generator=candidate_generator, candidate_repairer=repairer, quality_verifier=quality_verifier)
    repos = build_graph_fact_repositories()
    return build_graph(
        candidate_generator=candidate_generator,
        candidate_repairer=repairer,
        quality_verifier=quality_verifier,
        question_item_repository=repos.question_items,
        learning_event_repository=repos.learning_events,
    )
