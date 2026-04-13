"""
模型提供方配置工具
==================
职责：
  1. 统一读取 DigitalOcean Model Access Key / OpenAI 兼容环境变量
  2. 提供可切换的聊天模型列表（排除 Claude）
  3. 提供 LangChain ChatOpenAI / Embeddings 的标准化初始化入口
"""

from __future__ import annotations

import os
import time
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from loguru import logger
from pydo import Client

DEFAULT_DO_BASE_URL = "https://inference.do-ai.run/v1"
DEFAULT_CHAT_MODEL = "openai-gpt-oss-20b"
MODEL_CACHE_TTL_SECONDS = 300
DEFAULT_LLM_TIMEOUT_SECONDS = 45.0
DEFAULT_LLM_MAX_RETRIES = 1

BLOCKED_MODEL_PREFIXES = ("anthropic-",)
NON_CHAT_MODEL_KEYWORDS = (
    "embedding",
    "mini-lm",
    "mpnet",
    "gte-",
)

MODEL_METADATA_RULES = [
    ("openai-gpt-", "OpenAI", "GPT"),
    ("openai-o", "OpenAI", "Reasoning"),
    ("google-gemini", "Google", "Gemini"),
    ("gemini", "Google", "Gemini"),
    ("alibaba-qwen", "Alibaba", "Qwen"),
    ("qwen", "Alibaba", "Qwen"),
    ("deepseek", "DeepSeek", "DeepSeek"),
    ("glm", "Zhipu", "GLM"),
    ("kimi", "Moonshot", "Kimi"),
    ("llama", "Meta", "Llama"),
    ("minimax", "MiniMax", "MiniMax"),
    ("nvidia", "NVIDIA", "Nemotron"),
    ("arcee", "Arcee", "Arcee"),
]

PREFERRED_MODEL_ORDER = [
    "openai-gpt-oss-20b",
    "openai-gpt-oss-120b",
    "openai-gpt-4o",
    "openai-gpt-4o-mini",
    "openai-gpt-5-mini",
    "openai-gpt-5",
    "openai-gpt-5.4-mini",
    "openai-gpt-5.4",
    "google-gemini-2.5-pro",
    "google-gemini-2.5-flash",
    "alibaba-qwen3-32b",
    "glm-5",
    "kimi-k2.5",
    "llama3.3-70b-instruct",
    "deepseek-r1-distill-llama-70b",
]

FALLBACK_CHAT_MODELS = [
    "openai-gpt-oss-20b",
    "openai-gpt-oss-120b",
    "openai-gpt-4o",
    "openai-gpt-4o-mini",
    "openai-gpt-5-mini",
    "openai-gpt-5",
    "alibaba-qwen3-32b",
    "glm-5",
    "kimi-k2.5",
    "llama3.3-70b-instruct",
    "deepseek-r1-distill-llama-70b",
]

_MODEL_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "models": [],
}


def _get_llm_timeout_seconds() -> float:
    raw = os.getenv("LLM_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_LLM_TIMEOUT_SECONDS

    try:
        return max(5.0, float(raw))
    except ValueError:
        return DEFAULT_LLM_TIMEOUT_SECONDS


def _get_llm_max_retries() -> int:
    raw = os.getenv("LLM_MAX_RETRIES")
    if not raw:
        return DEFAULT_LLM_MAX_RETRIES

    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_LLM_MAX_RETRIES


def ensure_model_env_aliases() -> None:
    """在运行时对齐 MODEL_ACCESS_KEY / OPENAI_API_KEY，兼容不同接入方式。"""
    model_access_key = os.getenv("MODEL_ACCESS_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if model_access_key and not openai_api_key:
        os.environ["OPENAI_API_KEY"] = model_access_key
    elif openai_api_key and not model_access_key:
        os.environ["MODEL_ACCESS_KEY"] = openai_api_key


def get_model_access_key() -> str | None:
    """优先读取 DigitalOcean 官方密钥变量，兼容旧的 OpenAI 风格变量。"""
    ensure_model_env_aliases()
    return os.getenv("MODEL_ACCESS_KEY") or os.getenv("OPENAI_API_KEY")


def get_openai_compatible_base_url() -> str:
    """返回 OpenAI 兼容接口地址，默认使用 DigitalOcean inference endpoint。"""
    return os.getenv("OPENAI_BASE_URL", DEFAULT_DO_BASE_URL)


def get_pydo_client() -> Client:
    """返回 DigitalOcean 官方 pydo 客户端。"""
    token = get_model_access_key()
    if not token:
        raise RuntimeError("未找到 MODEL_ACCESS_KEY / OPENAI_API_KEY")
    return Client(token=token)


def _is_selectable_chat_model(model_id: str) -> bool:
    normalized = model_id.lower()

    if any(normalized.startswith(prefix) for prefix in BLOCKED_MODEL_PREFIXES):
        return False

    if any(keyword in normalized for keyword in NON_CHAT_MODEL_KEYWORDS):
        return False

    return True


def _titleize_token(token: str) -> str:
    if token.isupper():
        return token
    if token.isdigit():
        return token
    return token.capitalize()


def _prettify_model_label(model_id: str, family: str) -> str:
    if family == "GPT":
        return (
            model_id.replace("openai-", "")
            .replace("gpt-", "GPT-")
            .replace("oss", "OSS")
        )
    if family == "Gemini":
        return model_id.replace("google-", "").replace("gemini-", "Gemini-")
    if family == "Qwen":
        return model_id.replace("alibaba-", "").replace("qwen", "Qwen")
    if family == "GLM":
        return model_id.upper()
    if family == "Kimi":
        return model_id.replace("kimi-", "Kimi-")
    if family == "Llama":
        return model_id.replace("llama", "Llama ")
    if family == "DeepSeek":
        return model_id.replace("deepseek-", "DeepSeek-")

    return " ".join(_titleize_token(token) for token in model_id.split("-"))


def _build_model_option(model_id: str) -> dict[str, str] | None:
    if not _is_selectable_chat_model(model_id):
        return None

    normalized = model_id.lower()
    provider = "Other"
    family = "Other"

    for prefix, rule_provider, rule_family in MODEL_METADATA_RULES:
        if normalized.startswith(prefix):
            provider = rule_provider
            family = rule_family
            break

    return {
        "id": model_id,
        "label": _prettify_model_label(model_id, family),
        "provider": provider,
        "family": family,
    }


def _sort_model_options(models: list[dict[str, str]]) -> list[dict[str, str]]:
    order = {model_id: index for index, model_id in enumerate(PREFERRED_MODEL_ORDER)}
    return sorted(
        models,
        key=lambda item: (
            order.get(item["id"], len(PREFERRED_MODEL_ORDER) + 1),
            item["provider"],
            item["label"],
        ),
    )


def list_selectable_chat_models(force_refresh: bool = False) -> list[dict[str, str]]:
    """
    返回当前账号可切换的聊天模型列表。

    仅暴露 GPT / Gemini / Qwen / Llama / GLM / Kimi / DeepSeek 等非 Claude 模型。
    """
    now = time.time()
    if (
        not force_refresh
        and _MODEL_CACHE["models"]
        and now < float(_MODEL_CACHE["expires_at"])
    ):
        return list(_MODEL_CACHE["models"])

    model_options: list[dict[str, str]] = []

    try:
        remote_models = get_pydo_client().inference.list_models().get("data", [])
        for item in remote_models:
            model_id = item.get("id", "")
            option = _build_model_option(model_id)
            if option:
                model_options.append(option)
    except Exception as exc:
        logger.warning(f"⚠️ 拉取远程模型列表失败，回退到本地候选列表: {exc}")

    if not model_options:
        model_options = [
            option
            for model_id in FALLBACK_CHAT_MODELS
            if (option := _build_model_option(model_id))
        ]

    deduplicated: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for option in model_options:
        if option["id"] in seen_ids:
            continue
        seen_ids.add(option["id"])
        deduplicated.append(option)

    deduplicated = _sort_model_options(deduplicated)
    _MODEL_CACHE["models"] = list(deduplicated)
    _MODEL_CACHE["expires_at"] = now + MODEL_CACHE_TTL_SECONDS
    return deduplicated


def get_active_chat_model(default_model: str | None = None) -> str:
    """返回当前生效的聊天模型，优先读取数据库设置。"""
    ensure_model_env_aliases()

    configured = None
    try:
        from db.repositories import get_app_setting

        configured = get_app_setting("chat_model")
    except Exception as exc:
        logger.warning(f"⚠️ 读取数据库模型设置失败，回退到环境变量: {exc}")

    return (
        configured
        or os.getenv("OPENAI_MODEL")
        or default_model
        or DEFAULT_CHAT_MODEL
    )


def is_supported_chat_model(model_id: str) -> bool:
    """判断模型是否在当前可选列表内。"""
    return model_id in {item["id"] for item in list_selectable_chat_models()}


def validate_chat_model_access(model_id: str) -> tuple[bool, str | None]:
    """
    发送一次轻量请求验证模型是否真的可用。

    这样可以拦截“列表里能看到，但当前订阅等级实际不可调用”的模型。
    """
    try:
        llm = ChatOpenAI(
            model=model_id,
            temperature=0,
            openai_api_key=get_model_access_key(),
            openai_api_base=get_openai_compatible_base_url(),
            timeout=_get_llm_timeout_seconds(),
            max_retries=_get_llm_max_retries(),
        )
        response = llm.invoke("Reply with OK only.")
        content = response.content if isinstance(response.content, str) else str(response.content)
        if not content.strip():
            return False, "模型返回为空，暂时不建议作为聊天模型使用"
        return True, None
    except Exception as exc:
        return False, str(exc)


def get_chat_llm(
    *,
    default_model: str,
    temperature: float,
) -> ChatOpenAI:
    """创建统一配置的 ChatOpenAI 实例。"""
    return ChatOpenAI(
        model=get_active_chat_model(default_model),
        temperature=temperature,
        openai_api_key=get_model_access_key(),
        openai_api_base=get_openai_compatible_base_url(),
        timeout=_get_llm_timeout_seconds(),
        max_retries=_get_llm_max_retries(),
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
    )
