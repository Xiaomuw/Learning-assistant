from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.infrastructure.llm.config import (
    DEFAULT_CHAT_MODEL,
    ensure_model_env_aliases,
    get_chat_model_connection,
    get_embedding_check_ctx_length,
    get_locked_chat_model,
    get_llm_max_retries,
    get_llm_timeout_seconds,
    get_model_access_key,
    get_openai_compatible_base_url,
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
            openai_api_key=connection.api_key,
            openai_api_base=connection.base_url,
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
    embedding_model = model_id or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        embeddings = OpenAIEmbeddings(
            model=embedding_model,
            openai_api_key=get_model_access_key(),
            openai_api_base=get_openai_compatible_base_url(),
            check_embedding_ctx_length=get_embedding_check_ctx_length(),
        )
        vector = embeddings.embed_query("health check")
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
        openai_api_key=connection.api_key,
        openai_api_base=connection.base_url,
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


def get_embeddings(
    *,
    default_model: str,
) -> OpenAIEmbeddings:
    """创建统一配置的 Embedding 实例。"""
    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", default_model),
        openai_api_key=get_model_access_key(),
        openai_api_base=get_openai_compatible_base_url(),
        check_embedding_ctx_length=get_embedding_check_ctx_length(),
    )
