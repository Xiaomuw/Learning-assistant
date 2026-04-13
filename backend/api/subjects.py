"""
Subjects API — 学科管理
========================
CRUD 接口 + LLM 自动生成知识框架。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from db.repositories import (
    create_subject as create_subject_record,
    delete_subject as delete_subject_record,
    get_subject_by_id,
    list_subjects as list_subject_records,
    update_subject as update_subject_record,
)
from schemas.subject import (
    SubjectCreate,
    SubjectInfo,
    SubjectUpdate,
)
from tools.model_provider import get_chat_llm

router = APIRouter()


# ============================================================
# GET /subjects — 列出所有学科
# ============================================================

@router.get("/subjects", response_model=list[SubjectInfo])
async def list_subjects():
    """列出所有学科（含文档数）"""
    subjects = list_subject_records()

    # 动态更新文档数
    from tools.retriever import get_chroma_client
    try:
        client = get_chroma_client()
        for s in subjects:
            collection_name = f"learning_{s['id']}"
            try:
                col = client.get_collection(collection_name)
                s["doc_count"] = col.count()
            except Exception:
                s["doc_count"] = 0
    except Exception as e:
        logger.warning(f"⚠️ 获取文档数失败: {e}")

    return subjects


# ============================================================
# POST /subjects — 创建新学科
# ============================================================

@router.post("/subjects", response_model=SubjectInfo, status_code=201)
async def create_subject(body: SubjectCreate):
    """创建新学科"""
    try:
        new_subject = create_subject_record(
            name=body.name,
            icon=body.icon,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(f"✅ 创建学科: {body.name} (id={new_subject['id']})")
    return new_subject


@router.put("/subjects/{subject_id}", response_model=SubjectInfo)
async def update_subject(subject_id: str, body: SubjectUpdate):
    """更新学科 / 笔记本基础信息"""
    try:
        updated_subject = update_subject_record(
            subject_id=subject_id,
            name=body.name,
            icon=body.icon,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not updated_subject:
        raise HTTPException(status_code=404, detail=f"学科 '{subject_id}' 不存在")

    logger.info(f"📝 更新学科: {body.name} (id={subject_id})")
    return updated_subject


# ============================================================
# GET /subjects/{id} — 获取学科详情
# ============================================================

@router.get("/subjects/{subject_id}", response_model=SubjectInfo)
async def get_subject(subject_id: str):
    """获取学科详情"""
    subject = get_subject_by_id(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail=f"学科 '{subject_id}' 不存在")

    # 获取文档数
    from tools.retriever import get_chroma_client
    try:
        client = get_chroma_client()
        col = client.get_collection(f"learning_{subject_id}")
        subject["doc_count"] = col.count()
    except Exception:
        subject["doc_count"] = 0

    return subject


# ============================================================
# DELETE /subjects/{id} — 删除学科及其知识库
# ============================================================

@router.delete("/subjects/{subject_id}")
async def delete_subject(subject_id: str):
    """删除学科及其关联的知识库"""
    deleted = delete_subject_record(subject_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"学科 '{subject_id}' 不存在")

    # 删除 Chroma Collection
    from tools.retriever import get_chroma_client
    try:
        client = get_chroma_client()
        client.delete_collection(f"learning_{subject_id}")
        logger.info(f"🗑️ 已删除学科 '{subject_id}' 的知识库")
    except Exception as e:
        logger.warning(f"⚠️ 删除知识库失败（可能不存在）: {e}")

    return {"message": f"学科 '{subject_id}' 已删除"}


# ============================================================
# POST /subjects/{id}/generate — LLM 自动生成知识框架
# ============================================================

@router.post("/subjects/{subject_id}/generate")
async def generate_knowledge_base(subject_id: str):
    """
    用 LLM 自动为指定学科生成核心知识点概要，并入库。
    适配用于没有上传文档但想快速开始学习的场景。
    """
    subject = get_subject_by_id(subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail=f"学科 '{subject_id}' 不存在")

    subject_name = subject["name"]
    logger.info(f"🤖 开始为 '{subject_name}' 自动生成知识框架...")

    # ---- 用 LLM 生成知识点 ----
    llm = get_chat_llm(
        default_model="llama3.3-70b-instruct",
        temperature=0.3,
    )

    prompt = f"""你是一位{subject_name}领域的教授。请为这门课程生成一份完整的知识框架，用于构建学习知识库。

要求：
1. 列出 8-12 个核心章节/知识模块
2. 每个章节写 150-250 字的概要，涵盖该章节的核心概念、关键术语和重要原理
3. 每个章节独立成段，格式如下：

## 章节名称
概要内容...

请确保内容准确、全面，适合大学本科学习使用。"""

    try:
        response = llm.invoke(prompt)
        raw_text = response.content

        # 按章节分割
        sections = []
        current_title = ""
        current_content = []

        for line in raw_text.split("\n"):
            if line.startswith("## "):
                if current_title and current_content:
                    sections.append({
                        "title": current_title,
                        "content": "\n".join(current_content).strip(),
                    })
                current_title = line[3:].strip()
                current_content = []
            else:
                current_content.append(line)

        # 追加最后一个章节
        if current_title and current_content:
            sections.append({
                "title": current_title,
                "content": "\n".join(current_content).strip(),
            })

        if not sections:
            raise HTTPException(status_code=500, detail="LLM 生成内容解析失败")

        # ---- 入库到 Chroma ----
        from tools.retriever import ingest_documents

        texts = [f"{s['title']}\n\n{s['content']}" for s in sections]
        metadatas = [
            {
                "source": "auto_generated",
                "chapter": s["title"],
                "subject": subject_name,
            }
            for s in sections
        ]

        total_chunks = ingest_documents(
            texts=texts,
            metadatas=metadatas,
            subject_id=subject_id,
        )

        logger.info(
            f"✅ '{subject_name}' 知识框架生成完成: "
            f"{len(sections)} 章节, {total_chunks} 个分块"
        )

        return {
            "subject_id": subject_id,
            "subject_name": subject_name,
            "chapters": len(sections),
            "total_chunks": total_chunks,
            "chapter_titles": [s["title"] for s in sections],
            "message": f"已为 '{subject_name}' 生成 {len(sections)} 个章节的知识框架",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 知识框架生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")
