from __future__ import annotations

import os
from typing import Any

from pypdf import PdfReader


def extract_text_from_pdf(file_path: str) -> list[dict[str, Any]]:
    reader = PdfReader(file_path)
    source_name = os.path.basename(file_path)
    pages: list[dict[str, Any]] = []
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if text and text.strip():
            pages.append(
                {
                    "text": text.strip(),
                    "metadata": {
                        "page": page_num + 1,
                        "source": source_name,
                        "total_pages": len(reader.pages),
                    },
                }
            )
    return pages
