"""
使用 DigitalOcean 官方 pydo SDK 验证模型访问配置。

运行方式：
  cd backend
  python scripts/check_do_model_access.py
"""

from __future__ import annotations

import os
import sys
import socket
from pathlib import Path

from dotenv import load_dotenv
from pydo import Client

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

from app.infrastructure.llm.provider import build_model_health_snapshot, ensure_model_env_aliases
from app.services.runtime_models import resolve_active_chat_model

def _get_token() -> str:
    token = os.getenv("MODEL_ACCESS_KEY") or os.getenv("OPENAI_API_KEY")
    if not token:
        raise RuntimeError("未找到 MODEL_ACCESS_KEY / OPENAI_API_KEY，请先配置 backend/.env")
    return token


def _check_dns(host: str) -> bool:
    try:
        ip = socket.gethostbyname(host)
        print(f"dns_check={host} resolved={ip}")
        return True
    except Exception as exc:
        print(f"dns_check_failed host={host}: {type(exc).__name__} {exc}")
        return False


def _format_error(exc: Exception) -> str:
    code = getattr(exc, "status_code", None)
    msg = getattr(exc, "message", str(exc))
    if code is not None:
        return f"HTTP {code} {type(exc).__name__}: {msg}"
    return f"{type(exc).__name__}: {msg}"


def _print_health_status(health: dict[str, object]) -> None:
    print(
        "health="
        f"chat_ok={health['chat_model_ok']} "
        f"embedding_ok={health['embedding_model_ok']} "
        f"tool_calling={health['supports_tool_calling']} "
        f"structured={health['supports_structured_output']}"
    )
    if health.get("chat_model_error"):
        print(f"chat_error={health['chat_model_error']}")
    if health.get("embedding_model_error"):
        print(f"embedding_error={health['embedding_model_error']}")
    if health.get("embedding_base_url") and health.get("embedding_base_url") != health.get("base_url"):
        print(f"embedding_base_url={health['embedding_base_url']}")


def main() -> None:
    ensure_model_env_aliases()
    if not _check_dns("inference.do-ai.run"):
        print(
            "external_network_blocked="
            "inference.do-ai.run DNS 不可达；模型列表与聊天 smoke 后续步骤不具备可信性，已跳过。"
        )
        print("diagnosis=external_dns_unavailable")
        sys.exit(1)

    try:
        client = Client(token=_get_token())
    except Exception as exc:
        print(f"client_init_failed: {_format_error(exc)}")
        sys.exit(1)
    model = resolve_active_chat_model("openai-gpt-4o")
    prompt = os.getenv("DO_SMOKE_PROMPT", "请用一句中文介绍章鱼的一个有趣事实。")

    try:
        models = client.inference.list_models()
    except Exception as exc:
        print(f"list_models_failed: {_format_error(exc)}")
        models = {"data": []}
    model_ids = [item.get("id", "") for item in models.get("data", [])]
    print(f"models_count={len(model_ids)}")
    if model_ids:
        print(f"sample_models={', '.join(model_ids[:5])}")

    print(f"stream_model={model}")
    health = build_model_health_snapshot(chat_model=model)
    _print_health_status(health)
    print("stream_output=", end="", flush=True)
    try:
        stream = client.inference.create_chat_completion(
            body={
                "messages": [{"role": "user", "content": prompt}],
                "model": model,
                "max_tokens": 128,
                "stream": True,
            }
        )
    except Exception as exc:
        print(f"\nchat_stream_failed: {_format_error(exc)}")
        sys.exit(1)

    try:
        with stream:
            for chunk in stream:
                delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    print(token, end="", flush=True)
        print()
    except Exception as exc:
        print(f"\nchat_stream_iter_failed: {_format_error(exc)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
