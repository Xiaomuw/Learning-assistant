"""
Upload API — POST /upload
==========================
接收 PDF 文件，解析文本后分块写入 Chroma 向量库。
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, Form
from loguru import logger
from pypdf import PdfReader
from pydantic import BaseModel

from db.repositories import get_subject_by_id
from tools.retriever import ingest_documents
import requests
from bs4 import BeautifulSoup

router = APIRouter()


# ---------- 响应模型 ----------
class UploadResponse(BaseModel):
    """上传响应"""
    filename: str
    total_pages: int
    total_chunks: int
    subject_id: str
    message: str


# ---------- PDF 解析 ----------
def _extract_text_from_pdf(file_path: str) -> list[dict[str, Any]]:
    """
    从 PDF 文件提取文本。

    Returns:
        [{ "text": str, "metadata": { "page": int, "source": str } }, ...]
    """
    reader = PdfReader(file_path)
    source_name = os.path.basename(file_path)
    pages: list[dict[str, Any]] = []

    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if text and text.strip():
            pages.append({
                "text": text.strip(),
                "metadata": {
                    "page": page_num + 1,
                    "source": source_name,
                    "total_pages": len(reader.pages),
                },
            })

    logger.info(
        f"📄 PDF 解析完成: {source_name}, "
        f"共 {len(reader.pages)} 页, 有效 {len(pages)} 页"
    )
    return pages


# ---------- 路由 ----------
@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    subject_id: str = Form(default="general"),
):
    """
    POST /api/upload — 上传 PDF 文件并写入向量库
    """
    # ---- 文件校验 ----
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件上传")

    if not get_subject_by_id(subject_id):
        raise HTTPException(status_code=404, detail=f"学科 '{subject_id}' 不存在")

    logger.info(f"📄 收到文件上传: {file.filename}")

    tmp_path: str | None = None

    try:
        # ---- 保存临时文件 ----
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        logger.info(f"📄 临时文件已保存: {tmp_path}")

        # ---- 解析 PDF ----
        pages = _extract_text_from_pdf(tmp_path)
        if not pages:
            raise HTTPException(status_code=422, detail="PDF 解析失败或内容为空")

        # ---- 入库 ----
        texts = [p["text"] for p in pages]
        metadatas = [{**p["metadata"], "source": file.filename, "subject": subject_id} for p in pages]
        total_chunks = ingest_documents(
            texts=texts,
            metadatas=metadatas,
            subject_id=subject_id,
        )

        logger.info(
            f"✅ 文件 {file.filename} 入库完成: "
            f"{len(pages)} 页, {total_chunks} 个分块"
        )

        return UploadResponse(
            filename=file.filename,
            total_pages=len(pages),
            total_chunks=total_chunks,
            subject_id=subject_id,
            message=f"上传并入库成功（学科: {subject_id}）",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 文件处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"文件处理失败: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
            logger.debug(f"🗑️ 临时文件已清理: {tmp_path}")


# ---------- URL 抓取模型与路由 ----------
class UrlIngestRequest(BaseModel):
    subject_id: str
    urls: list[str]

class UrlIngestResponse(BaseModel):
    total_urls: int
    successful_urls: int
    total_chunks: int
    subject_id: str
    message: str

def _extract_text_from_url(url: str) -> str | None:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        # 移除非内容标签
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception as e:
        logger.warning(f"⚠️ URL 抓取失败 {url}: {e}")
        return None

@router.post("/upload/urls", response_model=UrlIngestResponse)
async def ingest_urls(request: UrlIngestRequest):
    """
    POST /api/upload/urls — 爬取网页文本并写入向量库
    """
    if not get_subject_by_id(request.subject_id):
        raise HTTPException(status_code=404, detail=f"学科 '{request.subject_id}' 不存在")

    logger.info(f"🌐 收到 URL 抓取任务: {len(request.urls)} 个链接, 学科: {request.subject_id}")
    
    texts = []
    metadatas = []
    success_count = 0

    for url in request.urls:
        url = url.strip()
        if not url:
            continue
            
        text = _extract_text_from_url(url)
        if text and len(text) > 50:
            texts.append(text)
            metadatas.append({
                "source": url,
                "subject": request.subject_id,
            })
            success_count += 1
            logger.info(f"✅ 成功抓取: {url} ({len(text)} 字符)")
            
    if not texts:
        raise HTTPException(status_code=422, detail="所有 URL 解析失败或内容过少")
        
    # 入库
    total_chunks = ingest_documents(
        texts=texts,
        metadatas=metadatas,
        subject_id=request.subject_id,
    )
    
    return UrlIngestResponse(
        total_urls=len(request.urls),
        successful_urls=success_count,
        total_chunks=total_chunks,
        subject_id=request.subject_id,
        message=f"成功抓取 {success_count}/{len(request.urls)} 个网页",
    )
