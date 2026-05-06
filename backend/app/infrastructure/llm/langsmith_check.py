"""LangSmith diagnostics command.

Run from the backend directory:
    .venv313/bin/python -m app.infrastructure.llm.langsmith_check
"""

from __future__ import annotations

import json

from dotenv import load_dotenv

from app.infrastructure.llm.langsmith import (
    get_langsmith_client,
    get_langsmith_settings,
    initialize_langsmith,
    qa_tracing_context,
    reset_langsmith_client_cache,
    sanitize_for_langsmith,
    trace_run,
)


def run_check() -> dict[str, object]:
    load_dotenv()
    reset_langsmith_client_cache()
    initialized = initialize_langsmith()
    settings = get_langsmith_settings()
    client = get_langsmith_client()

    trace_attempted = False
    trace_error = ""
    if client is not None and settings.enabled:
        trace_attempted = True
        try:
            with qa_tracing_context(
                metadata={"diagnostic": True, "component": "langsmith_check"},
                tags=["diagnostic", "langsmith"],
            ):
                with trace_run(
                    name="diagnostics.langsmith",
                    run_type="chain",
                    inputs={"question": "LangSmith connectivity check"},
                    metadata={"diagnostic": True},
                    tags=["diagnostic", "langsmith"],
                ) as run:
                    run.end(outputs={"status": "ok"})
        except Exception as exc:  # pragma: no cover - external service dependent
            trace_error = type(exc).__name__

    return {
        "sdk_available": settings.sdk_available,
        "tracing_enabled": settings.enabled,
        "configured": settings.configured,
        "has_api_key": settings.has_api_key,
        "project": settings.project,
        "endpoint": settings.endpoint or "cloud-default",
        "client_ok": client is not None,
        "initialize_ok": initialized,
        "test_trace_attempted": trace_attempted,
        "test_trace_error_type": trace_error,
        "sanitizer_preview": sanitize_for_langsmith(
            {
                "api_key": "this-should-not-appear",
                "database_url": "postgresql://user:password@example/db",
                "notebook_context": "HTTP " * 200,
            }
        ),
    }


def main() -> None:
    print(json.dumps(run_check(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
