"""
Subjects API — 学科 / 笔记本管理
=================================
保留 /subjects 兼容接口，同时提供 /notebooks 产品语义别名。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger

from app.application.errors import ApplicationError
from app.application.notebooks.service import (
    create_notebook,
    delete_notebook,
    generate_notebook_knowledge_base,
    get_knowledge_status,
    get_notebook,
    list_notebooks,
    update_notebook,
)
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user
from app.interfaces.http_errors import to_http_exception
from app.shared.schemas.subject import (
    SubjectCreate,
    SubjectInfo,
    SubjectUpdate,
)

router = APIRouter()


# ============================================================
# GET /subjects — 列出所有学科 / 笔记本
# ============================================================

@router.get("/notebooks", response_model=list[SubjectInfo])
@router.get("/subjects", response_model=list[SubjectInfo])
async def list_subjects(_: AuthenticatedUser = Depends(require_current_user)):
    """列出所有学科 / 笔记本（含文档数）"""
    return list_notebooks()


# ============================================================
# POST /subjects — 创建新学科 / 笔记本
# ============================================================

@router.post("/notebooks", response_model=SubjectInfo, status_code=201)
@router.post("/subjects", response_model=SubjectInfo, status_code=201)
async def create_subject(
    body: SubjectCreate,
    _: AuthenticatedUser = Depends(require_current_user),
):
    """创建新学科 / 笔记本"""
    try:
        new_subject = create_notebook(
            name=body.name,
            icon=body.icon,
            description=body.description,
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc

    logger.info(f"✅ 创建学科: {body.name} (id={new_subject.id})")
    return new_subject


@router.put("/notebooks/{subject_id}", response_model=SubjectInfo)
@router.put("/subjects/{subject_id}", response_model=SubjectInfo)
async def update_subject(
    subject_id: str,
    body: SubjectUpdate,
    _: AuthenticatedUser = Depends(require_current_user),
):
    """更新学科 / 笔记本基础信息"""
    try:
        updated_subject = update_notebook(
            subject_id=subject_id,
            name=body.name,
            icon=body.icon,
            description=body.description,
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc

    logger.info(f"📝 更新学科: {body.name} (id={subject_id})")
    return updated_subject


# ============================================================
# GET /subjects/{id} — 获取学科 / 笔记本详情
# ============================================================

@router.get("/notebooks/{subject_id}", response_model=SubjectInfo)
@router.get("/subjects/{subject_id}", response_model=SubjectInfo)
async def get_subject(
    subject_id: str,
    _: AuthenticatedUser = Depends(require_current_user),
):
    """获取学科 / 笔记本详情"""
    try:
        return get_notebook(subject_id)
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc


@router.get("/notebooks/{subject_id}/knowledge/status")
@router.get("/subjects/{subject_id}/knowledge/status")
async def get_subject_knowledge_status(
    subject_id: str,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    """获取 notebook 知识库/向量库状态。"""
    try:
        return get_knowledge_status(subject_id, user_id=current_user.id).model_dump()
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc


# ============================================================
# DELETE /subjects/{id} — 删除学科 / 笔记本及其知识库
# ============================================================

@router.delete("/notebooks/{subject_id}")
@router.delete("/subjects/{subject_id}")
async def delete_subject(
    subject_id: str,
    _: AuthenticatedUser = Depends(require_current_user),
):
    """删除学科 / 笔记本及其关联的知识库"""
    try:
        return delete_notebook(subject_id).model_dump()
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc


# ============================================================
# POST /subjects/{id}/generate — LLM 自动生成知识框架
# ============================================================

@router.post("/notebooks/{subject_id}/generate")
@router.post("/subjects/{subject_id}/generate")
async def generate_knowledge_base(
    subject_id: str,
    _: AuthenticatedUser = Depends(require_current_user),
):
    """
    用 LLM 自动为指定学科 / 笔记本生成核心知识点概要，并入库。
    适配用于没有上传文档但想快速开始学习的场景。
    """
    try:
        return generate_notebook_knowledge_base(subject_id).model_dump()
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
