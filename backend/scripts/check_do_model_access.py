"""
使用 DigitalOcean 官方 pydo SDK 验证模型访问配置。

运行方式：
  cd backend
  python scripts/check_do_model_access.py
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydo import Client

from tools.model_provider import ensure_model_env_aliases, get_active_chat_model


def _get_token() -> str:
    token = os.getenv("MODEL_ACCESS_KEY") or os.getenv("OPENAI_API_KEY")
    if not token:
        raise RuntimeError("未找到 MODEL_ACCESS_KEY / OPENAI_API_KEY，请先配置 backend/.env")
    return token


def main() -> None:
    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
    ensure_model_env_aliases()

    client = Client(token=_get_token())
    model = get_active_chat_model("openai-gpt-4o")
    prompt = os.getenv("DO_SMOKE_PROMPT", "请用一句中文介绍章鱼的一个有趣事实。")

    models = client.inference.list_models()
    model_ids = [item.get("id", "") for item in models.get("data", [])]
    print(f"models_count={len(model_ids)}")
    if model_ids:
        print(f"sample_models={', '.join(model_ids[:5])}")

    print(f"stream_model={model}")
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
