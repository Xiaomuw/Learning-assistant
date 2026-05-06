"""
使用 DigitalOcean 官方 pydo SDK 验证模型访问配置。

运行方式：
  cd backend
  python scripts/check_do_model_access.py
"""

from __future__ import annotations

import os
import sys
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


def main() -> None:
    ensure_model_env_aliases()

    client = Client(token=_get_token())
    model = resolve_active_chat_model("openai-gpt-4o")
    prompt = os.getenv("DO_SMOKE_PROMPT", "请用一句中文介绍章鱼的一个有趣事实。")

    models = client.inference.list_models()
    model_ids = [item.get("id", "") for item in models.get("data", [])]
    print(f"models_count={len(model_ids)}")
    if model_ids:
        print(f"sample_models={', '.join(model_ids[:5])}")

    print(f"stream_model={model}")
    health = build_model_health_snapshot(chat_model=model)
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
    print("stream_output=", end="", flush=True)

    stream = client.inference.create_chat_completion(
        body={
            "messages": [{"role": "user", "content": prompt}],
            "model": model,
            "max_tokens": 128,
            "stream": True,
        }
    )

    with stream:
        for chunk in stream:
            delta = (chunk.get("choices") or [{}])[0].get("delta", {})
            token = delta.get("content", "")
            if token:
                print(token, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
