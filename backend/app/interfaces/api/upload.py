"""
Upload API — POST /upload
==========================
接收 PDF 文件，解析文本后分块写入 PGVector。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, Form
from pydantic import BaseModel

from app.application.errors import ApplicationError
from app.application.ingest.service import ingest_pdf_bytes, ingest_urls as ingest_urls_service
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user
from app.interfaces.http_errors import to_http_exception
from app.shared.schemas.subject import DEFAULT_SUBJECT_ID

router = APIRouter()


# ---------- 响应模型 ----------
class UploadResponse(BaseModel):
    """上传响应"""
    filename: str
    total_pages: int
    total_chunks: int
    subject_id: str
    message: str


# ---------- 路由 ----------
@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    subject_id: str = Form(default=DEFAULT_SUBJECT_ID),
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """
    POST /api/upload — 上传 PDF 文件并写入 PGVector
    """
    try:
        result = ingest_pdf_bytes(
            filename=file.filename or "",
            content=await file.read(),
            subject_id=subject_id,
            user_id=current_user.id,
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    payload = result.model_dump()
    return UploadResponse(
        filename=payload["filename"],
        total_pages=payload["total_pages"],
        total_chunks=payload["total_chunks"],
        subject_id=payload["subject_id"],
        message=payload["message"],
    )


# ---------- URL 抓取模型与路由 ----------
class UrlIngestRequest(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    urls: list[str]

class UrlIngestResponse(BaseModel):
    total_urls: int
    successful_urls: int
    total_chunks: int
    subject_id: str
    message: str

@router.post("/upload/urls", response_model=UrlIngestResponse)
async def ingest_urls(
    request: UrlIngestRequest,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """
    POST /api/upload/urls — 爬取网页文本并写入向量库
    """
    try:
        result = ingest_urls_service(
            subject_id=request.subject_id,
            urls=request.urls,
            user_id=current_user.id,
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    payload = result.model_dump()
    return UrlIngestResponse(
        total_urls=payload["total_urls"],
        successful_urls=payload["successful_urls"],
        total_chunks=payload["total_chunks"],
        subject_id=payload["subject_id"],
        message=payload["message"],
    )
