from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from app.orchestration.graphs.eval_runner import (
    build_eval_case_example,
    get_graph_eval_cases,
    run_graph_eval_case,
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FORBIDDEN_PAYLOAD_KEYS = {
    "question",
    "answer",
    "notebook_context",
    "raw_output",
    "tool_args",
    "document",
    "content",
    "prompt",
}


def is_langsmith_dataset_sync_enabled() -> bool:
    return str(os.getenv("GRAPH_EVAL_LANGSMITH", "")).strip().lower() in _TRUE_VALUES


def load_langsmith_eval_env() -> None:
    """Load backend .env only for the explicit LangSmith eval CLI path."""

    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)


def get_eval_dataset_name() -> str:
    return os.getenv("GRAPH_EVAL_DATASET", "learning-assistant-graph-smoke")


def build_eval_dataset_preview() -> dict[str, Any]:
    cases = [build_eval_case_example(case) for case in get_graph_eval_cases()]
    return {
        "dataset_name": get_eval_dataset_name(),
        "status": "preview",
        "total": len(cases),
        "cases": [
            {
                "case_name": item["inputs"]["case_name"],
                "graph_type": item["inputs"]["graph_type"],
                "expected_metrics": item["outputs"].get("expected_metrics", {}),
            }
            for item in cases
        ],
    }


def sync_eval_dataset(client: Any | None = None) -> dict[str, Any]:
    preview = build_eval_dataset_preview()
    if not is_langsmith_dataset_sync_enabled():
        return {
            **preview,
            "synced": False,
            "reason": "GRAPH_EVAL_LANGSMITH disabled",
        }

    try:
        if client is None:
            from langsmith import Client

            client = Client()
        dataset_name = preview["dataset_name"]
        dataset = _read_or_create_dataset(client, dataset_name)
        existing_case_names = _existing_case_names(client, dataset)
        created_count = 0
        skipped_count = 0
        for case in get_graph_eval_cases():
            example = build_eval_case_example(case)
            case_name = str(example["inputs"]["case_name"])
            if case_name in existing_case_names:
                skipped_count += 1
                continue
            client.create_example(
                inputs=example["inputs"],
                outputs=example["outputs"],
                metadata=example["metadata"],
                dataset_id=dataset.id,
            )
            created_count += 1
        return {
            **preview,
            "synced": True,
            "example_count": len(preview["cases"]),
            "created_count": created_count,
            "skipped_count": skipped_count,
        }
    except Exception as exc:  # pragma: no cover - external service boundary
        return {
            **preview,
            "synced": False,
            "reason": exc.__class__.__name__,
        }


def run_remote_eval(client: Any | None = None, evaluate_fn: Callable[..., Any] | None = None) -> dict[str, Any]:
    preview = build_eval_dataset_preview()
    if not is_langsmith_dataset_sync_enabled():
        return {
            **preview,
            "ran": False,
            "reason": "GRAPH_EVAL_LANGSMITH disabled",
        }

    sync_result = sync_eval_dataset(client=client)
    if not sync_result.get("synced"):
        return {
            **preview,
            "ran": False,
            "reason": str(sync_result.get("reason") or "dataset_sync_failed"),
        }

    try:
        if client is None:
            from langsmith import Client

            client = Client()
        if evaluate_fn is None:
            from langsmith.evaluation import evaluate as evaluate_fn  # type: ignore[assignment]

        dataset_name = preview["dataset_name"]

        def target(inputs: dict[str, Any]) -> dict[str, Any]:
            case_name = str(inputs.get("case_name") or "")
            return _sanitize_eval_output(run_graph_eval_case(case_name))

        result = evaluate_fn(
            target,
            data=dataset_name,
            evaluators=[
                qa_groundedness,
                tool_policy_precision,
                qgen_quality,
                mastery_stability,
            ],
            client=client,
            experiment_prefix="learning-assistant-graph",
            metadata={
                "component": "graph_eval",
                "dataset_name": dataset_name,
                "contains_raw_user_text": False,
                "raw_response_included": False,
            },
            blocking=True,
            upload_results=True,
        )
        return {
            **preview,
            "ran": True,
            "dataset_name": dataset_name,
            "evaluator_count": 4,
            "result_type": type(result).__name__,
        }
    except Exception as exc:  # pragma: no cover - external service boundary
        return {
            **preview,
            "ran": False,
            "reason": exc.__class__.__name__,
        }


def qa_groundedness(*, inputs: dict[str, Any] | None = None, outputs: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    case_name = str((inputs or {}).get("case_name") or "")
    if not case_name.startswith("qa_"):
        return _score("qa_groundedness", 1, "not_applicable")
    output = outputs or {}
    if output.get("status") != "passed":
        return _score("qa_groundedness", 0, "case_failed")
    if case_name == "qa_notebook_only_insufficient":
        return _score("qa_groundedness", 1, "notebook_only_no_fabrication")
    if bool(output.get("response_empty")):
        return _score("qa_groundedness", 0, "empty_response")
    return _score("qa_groundedness", 1, "grounded_contract_passed")


def tool_policy_precision(*, inputs: dict[str, Any] | None = None, outputs: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    case_name = str((inputs or {}).get("case_name") or "")
    if not case_name.startswith("qa_"):
        return _score("tool_policy_precision", 1, "not_applicable")
    output = outputs or {}
    if case_name == "qa_concept_filtered_retrieval":
        if int(output.get("tool_request_count") or 0) == 1:
            return _score("tool_policy_precision", 1, "concept_filtered_retrieval_passed")
        return _score("tool_policy_precision", 0, "missing_concept_filtered_request")
    if int(output.get("tool_request_count") or 0) > 0:
        return _score("tool_policy_precision", 0, "unexpected_tool_request")
    return _score("tool_policy_precision", 1, "tool_policy_passed")


def qgen_quality(*, inputs: dict[str, Any] | None = None, outputs: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    case_name = str((inputs or {}).get("case_name") or "")
    if not case_name.startswith("qgen_"):
        return _score("qgen_quality", 1, "not_applicable")
    output = outputs or {}
    if output.get("status") != "passed":
        return _score("qgen_quality", 0, "case_failed")
    if int(output.get("error_count") or 0) > 0:
        return _score("qgen_quality", 0, "graph_errors")
    return _score("qgen_quality", 1, "quality_contract_passed")


def mastery_stability(*, inputs: dict[str, Any] | None = None, outputs: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    case_name = str((inputs or {}).get("case_name") or "")
    if not case_name.startswith("mastery_"):
        return _score("mastery_stability", 1, "not_applicable")
    output = outputs or {}
    if output.get("status") != "passed":
        return _score("mastery_stability", 0, "case_failed")
    return _score("mastery_stability", 1, "bounded_update_contract_passed")


def _score(key: str, score: int, comment: str) -> dict[str, Any]:
    return {"key": key, "score": score, "comment": comment}


def _sanitize_eval_output(output: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "name",
        "case_name",
        "graph_type",
        "status",
        "failures",
        "latency_ms",
        "evidence_count",
        "tool_request_count",
        "tool_result_count",
        "learning_event_count",
        "error_count",
    }
    payload = {key: output.get(key) for key in sorted(allowed) if key in output}
    if "final_answer_empty" in output:
        payload["response_empty"] = bool(output.get("final_answer_empty"))
    return payload


def _read_or_create_dataset(client: Any, dataset_name: str) -> Any:
    try:
        return client.read_dataset(dataset_name=dataset_name)
    except Exception:
        return client.create_dataset(
            dataset_name=dataset_name,
            description="Learning Assistant graph smoke evals",
        )


def _existing_case_names(client: Any, dataset: Any) -> set[str]:
    case_names: set[str] = set()
    try:
        examples = client.list_examples(dataset_id=dataset.id)
    except Exception:
        return case_names
    for example in examples:
        inputs = getattr(example, "inputs", None)
        if isinstance(inputs, dict):
            case_name = str(inputs.get("case_name") or "")
            if case_name:
                case_names.add(case_name)
    return case_names


def assert_no_sensitive_eval_payload(payload: dict[str, Any]) -> None:
    leaked = sorted(_find_forbidden_keys(payload))
    if leaked:
        raise AssertionError(f"langsmith eval payload contains forbidden keys: {', '.join(leaked)}")


def _find_forbidden_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found: set[str] = set()
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in _FORBIDDEN_PAYLOAD_KEYS:
                found.add(key_text)
            found.update(_find_forbidden_keys(child))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found.update(_find_forbidden_keys(child))
        return found
    return set()


def main(argv: list[str] | None = None) -> int:
    load_langsmith_eval_env()
    parser = argparse.ArgumentParser(description="Sync or run graph evals with LangSmith.")
    parser.add_argument("--sync", action="store_true", help="create/update the LangSmith dataset")
    parser.add_argument("--run", action="store_true", help="run LangSmith remote evaluators")
    parser.add_argument("--all", action="store_true", help="sync dataset, then run evaluators")
    args = parser.parse_args(argv)

    if args.all:
        sync_result = sync_eval_dataset()
        run_result = run_remote_eval()
        payload = {"sync": sync_result, "run": run_result}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if run_result.get("ran") or not is_langsmith_dataset_sync_enabled() else 1
    if args.run:
        result = run_remote_eval()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ran") or not is_langsmith_dataset_sync_enabled() else 1
    result = sync_eval_dataset()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("synced") or not is_langsmith_dataset_sync_enabled() else 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
