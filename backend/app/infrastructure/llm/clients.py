from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.infrastructure.llm.config import (
    DEFAULT_CHAT_MODEL,
    ensure_model_env_aliases,
    get_chat_model_connection,
    get_embedding_check_ctx_length,
    get_embedding_model_connection,
    get_embedding_provider,
    get_fallback_embedding_model_connection,
    get_google_api_key,
    get_google_embedding_model,
    get_locked_chat_model,
    get_llm_max_retries,
    get_llm_timeout_seconds,
    is_model_switching_enabled,
)
from app.infrastructure.llm.profile import get_model_profile


def get_active_chat_model(default_model: str | None = None) -> str:
    """返回基础设施层默认生效的聊天模型，仅依赖环境变量。"""
    ensure_model_env_aliases()
    if not is_model_switching_enabled():
        return get_locked_chat_model()
    return os.getenv("OPENAI_MODEL") or default_model or DEFAULT_CHAT_MODEL


def validate_chat_model_access(model_id: str) -> tuple[bool, str | None]:
    """发送一次轻量请求验证模型是否真的可用。"""
    try:
        connection = get_chat_model_connection(model_id)
        if not connection.api_key:
            return False, f"{connection.provider} 模型密钥未配置"
        llm = ChatOpenAI(
            model=connection.model_id,
            temperature=0,
            api_key=connection.api_key,
            base_url=connection.base_url,
            timeout=get_llm_timeout_seconds(),
            max_retries=get_llm_max_retries(),
        )
        response = llm.invoke("Reply with OK only.")
        content = response.content if isinstance(response.content, str) else str(response.content)
        if not content.strip():
            return False, "模型返回为空，暂时不建议作为聊天模型使用"
        return True, None
    except Exception as exc:
        return False, str(exc)


def validate_embedding_model_access(model_id: str | None = None) -> tuple[bool, str | None]:
    """发送一次轻量 embedding 请求，区分聊天模型和向量模型故障。"""
    try:
        connection = get_embedding_model_connection(model_id)
        if not connection.api_key:
            return False, f"{connection.provider} Embedding 模型密钥未配置"
        emb = _build_embedding_instance(connection)
        vector = emb.embed_query("health check")
        if not vector:
            return False, "Embedding 模型返回为空"
        return True, None
    except Exception as exc:
        return False, str(exc)


def get_chat_llm(
    *,
    default_model: str,
    temperature: float,
    model_override: str | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> Any:
    """创建统一配置的 ChatOpenAI 实例。"""
    model_id = model_override or get_active_chat_model(default_model)
    connection = get_chat_model_connection(model_id)
    model_profile = get_model_profile(model_id)
    llm = ChatOpenAI(
        model=connection.model_id,
        temperature=temperature,
        api_key=connection.api_key,
        base_url=connection.base_url,
        timeout=timeout_seconds if timeout_seconds is not None else get_llm_timeout_seconds(),
        max_retries=max_retries if max_retries is not None else get_llm_max_retries(),
    )
    return llm.with_config(
        {
            "tags": [
                "llm",
                f"provider:{model_profile.provider.lower()}",
                f"family:{model_profile.family.lower()}",
            ],
            "metadata": {
                "selected_model": model_profile.model_id,
                "model_provider": model_profile.provider,
                "model_family": model_profile.family,
            },
        }
    )


def _build_google_embeddings() -> Any:
    """创建支持多 Key 轮换的 Google Gemini Embedding 实例。

    特性：
    1. 支持多 API Key：当某个 Key 触发速率限制（429）时自动切到下一个
    2. 修复 embed_documents batch bug：强制逐条调用
    """
    import threading
    import time

    from langchain_core.embeddings import Embeddings as LCEmbeddings
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from loguru import logger

    from app.infrastructure.llm.config import get_google_api_keys

    api_keys = get_google_api_keys()
    if not api_keys:
        raise RuntimeError("未配置 GOOGLE_API_KEYS，无法创建 Embedding 实例")

    model = get_google_embedding_model()
    # 为每个 Key 预建实例
    instances = [
        GoogleGenerativeAIEmbeddings(model=model, google_api_key=key)
        for key in api_keys
    ]
    lock = threading.Lock()
    state = {"index": 0}

    def _embed_with_rotation(text: str) -> list[float]:
        """逐条嵌入，遇到 429 自动轮换 Key。"""
        attempts = len(instances)
        last_exc: Exception | None = None
        for _ in range(attempts):
            with lock:
                idx = state["index"]
            instance = instances[idx]
            try:
                return instance.embed_query(text)
            except Exception as exc:
                exc_str = str(exc)
                is_rate_limit = "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str
                if is_rate_limit and len(instances) > 1:
                    with lock:
                        next_idx = (state["index"] + 1) % len(instances)
                        state["index"] = next_idx
                    logger.warning(
                        f"⚠️ Google Key #{idx + 1} 超速率，切换到 Key #{next_idx + 1}"
                    )
                    last_exc = exc
                    time.sleep(0.5)
                    continue
                raise
        raise last_exc or RuntimeError("所有 Google API Key 均已超速率")

    class _MultiKeyGoogleEmbeddings(LCEmbeddings):
        """多 Key 轮换 + 逐条嵌入的 Google Embedding 包装器。"""

        def embed_query(self, text: str) -> list[float]:
            return _embed_with_rotation(text)

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [_embed_with_rotation(t) for t in texts]

    logger.info(f"✅ Google Embedding 就绪: {model}, {len(api_keys)} 个 Key 可用")
    return _MultiKeyGoogleEmbeddings()


def _build_openai_embeddings(connection: Any) -> OpenAIEmbeddings:
    """从 EmbeddingModelConnection 创建 OpenAIEmbeddings 实例。"""
    # DashScope 每次 batch 最多 10 条；留安全余量设为 6
    batch_size = 6 if getattr(connection, "provider", "") == "DashScope" else 1000
    return OpenAIEmbeddings(
        model=connection.model_id,
        api_key=connection.api_key,
        base_url=connection.base_url,
        check_embedding_ctx_length=get_embedding_check_ctx_length(),
        chunk_size=batch_size,
    )


def _build_embedding_instance(connection: Any) -> Any:
    """根据 provider 创建对应的 Embedding 实例。"""
    if getattr(connection, "provider", "") == "Google":
        return _build_google_embeddings()
    return _build_openai_embeddings(connection)


def get_embeddings(
    *,
    default_model: str,
) -> Any:
    """创建统一配置的 Embedding 实例。

    Google provider 直接返回实例；
    OpenAI-compatible provider 只做客户端构造，可用性探测留给 validate_embedding_model_access。
    """
    from loguru import logger

    connection = get_embedding_model_connection()

    if connection.provider == "Google":
        instance = _build_google_embeddings()
        logger.debug(f"✅ Embedding 就绪: {connection.model_id} (Google)")
        return instance

    # OpenAI-compatible: 保持构造纯粹，不在高频索引/检索路径发起健康探测。
    try:
        instance = _build_openai_embeddings(connection)
        logger.debug(f"✅ Embedding 客户端已构造: {connection.model_id} ({connection.provider})")
        return instance
    except Exception as primary_exc:
        fallback_connection = get_fallback_embedding_model_connection()
        if not fallback_connection:
            logger.error(f"❌ Embedding 主模型 {connection.model_id} 失败且无兜底模型: {primary_exc}")
            raise
        logger.warning(
            f"⚠️ Embedding 主模型 {connection.model_id} 失败 ({primary_exc})，"
            f"降级到兜底模型 {fallback_connection.model_id}"
        )
        return _build_openai_embeddings(fallback_connection)
