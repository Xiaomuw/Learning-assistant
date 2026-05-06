from __future__ import annotations

import os

from langchain_text_splitters import RecursiveCharacterTextSplitter


def get_default_chunk_size() -> int:
    return int(os.getenv("CHUNK_SIZE", "1000"))


def get_default_chunk_overlap() -> int:
    return int(os.getenv("CHUNK_OVERLAP", "200"))


def build_text_splitter(
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or get_default_chunk_size(),
        chunk_overlap=chunk_overlap or get_default_chunk_overlap(),
        length_function=len,
    )


def split_text(
    text: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    content = str(text or "").strip()
    if not content:
        return []
    return build_text_splitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    ).split_text(content)

