from __future__ import annotations

from loguru import logger

from app.application.errors import ForbiddenError, NotFoundError
from app.infrastructure.db.repositories.subjects import (
    get_subject_record,
    list_subject_records,
)
from app.services.notebook_knowledge_base import (
    count_notebook_documents,
    get_notebook_knowledge_status,
)
from app.shared.schemas.contracts import (
    DeleteResult,
    NotebookKnowledgeGenerationResult,
    NotebookKnowledgeStatus,
    NotebookListItem,
    SubjectRecord,
)
from app.shared.schemas.subject import CANONICAL_SUBJECT_IDS, DEFAULT_SUBJECTS, normalize_subject_id


_CANONICAL_SUBJECT_METADATA = {str(item["id"]): item for item in DEFAULT_SUBJECTS}


def _load_notebook_or_404(subject_id: str) -> SubjectRecord:
    normalized_subject_id = normalize_subject_id(subject_id)
    subject = get_subject_record(normalized_subject_id)
    if not subject:
        raise NotFoundError(f"知识库 '{normalized_subject_id}' 不存在")
    return subject


def _count_notebook_documents(subject_id: str) -> int:
    try:
        return count_notebook_documents(subject_id)
    except Exception as exc:
        logger.warning(f"⚠️ 获取文档数失败: {exc}")
        return 0


def list_notebooks() -> list[NotebookListItem]:
    records = {item.id: item for item in list_subject_records()}
    notebooks: list[NotebookListItem] = []
    for subject_id in CANONICAL_SUBJECT_IDS:
        if subject_id not in records:
            continue
        payload = records[subject_id].model_dump()
        payload.update(_CANONICAL_SUBJECT_METADATA.get(subject_id, {}))
        notebooks.append(NotebookListItem.model_validate(payload))
    for item in notebooks:
        item.doc_count = _count_notebook_documents(item.id)
    return notebooks


def get_notebook(subject_id: str) -> NotebookListItem:
    subject = _load_notebook_or_404(subject_id)
    raw_payload = subject.model_dump()
    raw_payload.update(_CANONICAL_SUBJECT_METADATA.get(subject.id, {}))
    payload = NotebookListItem.model_validate(raw_payload)
    payload.doc_count = _count_notebook_documents(payload.id)
    return payload


def get_knowledge_status(subject_id: str, user_id: str | None = None) -> NotebookKnowledgeStatus:
    subject = _load_notebook_or_404(subject_id)
    return get_notebook_knowledge_status(subject.id, user_id=user_id)


def create_notebook(name: str, icon: str = "📚", description: str = "") -> SubjectRecord:
    raise ForbiddenError("默认知识库由系统维护，暂不支持用户新建 notebook")


def update_notebook(subject_id: str, name: str, icon: str = "📚", description: str = "") -> SubjectRecord:
    raise ForbiddenError("默认知识库由系统维护，暂不支持用户编辑 notebook 信息")


def delete_notebook(subject_id: str) -> DeleteResult:
    raise ForbiddenError("默认知识库由系统维护，暂不支持用户删除 notebook")


def generate_notebook_knowledge_base(subject_id: str) -> NotebookKnowledgeGenerationResult:
    raise ForbiddenError("默认知识库由系统维护，暂不支持用户手动生成知识框架")
