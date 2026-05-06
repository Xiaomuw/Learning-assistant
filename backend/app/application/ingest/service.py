from __future__ import annotations

import os
import tempfile
from typing import Any

from loguru import logger

from app.application.errors import NotFoundError, ProcessingError, ValidationError
from app.infrastructure.db.repositories.subjects import get_subject_record
from app.infrastructure.ingest.pdf import extract_text_from_pdf
from app.infrastructure.ingest.web import extract_text_from_url
from app.services.notebook_knowledge_base import ingest_notebook_documents
from app.shared.schemas.contracts import IngestResult
from app.shared.schemas.subject import normalize_subject_id


def _ensure_subject_exists(subject_id: str) -> None:
    if not get_subject_record(subject_id):
        raise NotFoundError(f"学科 '{subject_id}' 不存在")


def _build_pdf_ingest_payload(*, filename: str, subject_id: str, pages: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    texts = [page["text"] for page in pages]
    metadatas = [
        {
            **page["metadata"],
            "subject_id": subject_id,
            "doc_type": "pdf",
            "source": filename,
            "source_id": filename,
            "knowledge_point": "",
            "visibility": "personal",
        }
        for page in pages
    ]
    return texts, metadatas


def _build_url_ingest_payload(*, subject_id: str, urls: list[str]) -> tuple[list[str], list[dict[str, Any]], int]:
    texts: list[str] = []
    metadatas: list[dict[str, Any]] = []
    success_count = 0
    for raw_url in urls:
        url = raw_url.strip()
        if not url:
            continue
        text = extract_text_from_url(url)
        if text and len(text) > 50:
            texts.append(text)
            metadatas.append(
                {
                    "subject_id": subject_id,
                    "doc_type": "url",
                    "source": url,
                    "source_id": url,
                    "knowledge_point": "",
                    "visibility": "personal",
                }
            )
            success_count += 1
    return texts, metadatas, success_count


def ingest_pdf_bytes(*, filename: str, content: bytes, subject_id: str, user_id: str) -> IngestResult:
    if not filename or not filename.lower().endswith(".pdf"):
        raise ValidationError("仅支持 PDF 文件上传")
    if not content:
        raise ValidationError("上传文件为空")

    subject_id = normalize_subject_id(subject_id)
    _ensure_subject_exists(subject_id)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        pages = extract_text_from_pdf(tmp_path)
        if not pages:
            raise ValidationError("PDF 解析失败或内容为空")
        texts, metadatas = _build_pdf_ingest_payload(
            filename=filename,
            subject_id=subject_id,
            pages=pages,
        )
        total_chunks = ingest_notebook_documents(
            texts=texts,
            metadatas=metadatas,
            subject_id=subject_id,
            user_id=user_id,
        )
        return IngestResult(
            filename=filename,
            total_pages=len(pages),
            total_chunks=total_chunks,
            subject_id=subject_id,
            message=f"上传并入库成功（学科: {subject_id}）",
        )
    except (NotFoundError, ValidationError):
        raise
    except Exception as exc:
        logger.error(f"❌ 文件处理失败: {exc}")
        raise ProcessingError(f"文件处理失败: {str(exc)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def ingest_urls(*, subject_id: str, urls: list[str], user_id: str) -> IngestResult:
    try:
        subject_id = normalize_subject_id(subject_id)
        _ensure_subject_exists(subject_id)
        texts, metadatas, success_count = _build_url_ingest_payload(subject_id=subject_id, urls=urls)
        if not texts:
            raise ValidationError("所有 URL 解析失败或内容过少")
        total_chunks = ingest_notebook_documents(
            texts=texts,
            metadatas=metadatas,
            subject_id=subject_id,
            user_id=user_id,
        )
        return IngestResult(
            total_urls=len(urls),
            successful_urls=success_count,
            total_chunks=total_chunks,
            subject_id=subject_id,
            message=f"成功抓取 {success_count}/{len(urls)} 个网页",
        )
    except (NotFoundError, ValidationError):
        raise
    except Exception as exc:
        logger.error(f"❌ URL 入库失败: {exc}")
        raise ProcessingError(f"URL 入库失败: {str(exc)}") from exc
