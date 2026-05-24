from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.errors import ServiceUnavailableError, ValidationError
from app.application.ingest.service import _build_url_ingest_payload, ingest_pdf_bytes, ingest_urls


class IngestServiceTest(unittest.TestCase):
    def test_url_payload_builder_ignores_short_pages_and_keeps_long_pages(self) -> None:
        long_text = (
            "HTTP 是应用层协议，默认端口是 80。"
            "这个临时页面包含足够多的正文，用来验证 URL 入库的内容长度门槛。"
        )
        with patch(
            "app.application.ingest.service.extract_text_from_url",
            side_effect=["太短", long_text],
        ):
            texts, metadatas, success_count = _build_url_ingest_payload(
                subject_id="computer-network",
                urls=["https://example.com/short", "https://example.com/http"],
            )

        self.assertEqual(texts, [long_text])
        self.assertEqual(success_count, 1)
        self.assertEqual(metadatas[0]["source"], "https://example.com/http")
        self.assertEqual(metadatas[0]["doc_type"], "url")

    def test_url_ingest_wraps_vector_store_failures_as_service_unavailable(self) -> None:
        with (
            patch(
                "app.application.ingest.service.get_subject_record",
                return_value=object(),
            ),
            patch(
                "app.application.ingest.service._build_url_ingest_payload",
                return_value=(["HTTP content"], [{"source": "https://example.com"}], 1),
            ),
            patch(
                "app.application.ingest.service.ingest_notebook_documents_with_summary",
                side_effect=RuntimeError("embedding failed"),
            ),
        ):
            with self.assertRaises(ServiceUnavailableError) as raised:
                ingest_urls(
                    subject_id="test-notebook",
                    urls=["https://example.com"],
                    user_id="user-1",
                )

        self.assertIn("URL 入库失败", raised.exception.detail)
        self.assertIn("embedding failed", raised.exception.detail)

    def test_pdf_ingest_wraps_model_failures_as_service_unavailable(self) -> None:
        with (
            patch(
                "app.application.ingest.service.get_subject_record",
                return_value=object(),
            ),
            patch(
                "app.application.ingest.service.extract_text_from_pdf",
                return_value=[
                    {
                        "text": "HTTP content",
                        "metadata": {"page": 1},
                    }
                ],
            ),
            patch(
                "app.application.ingest.service.ingest_notebook_documents_with_summary",
                side_effect=RuntimeError("model not found"),
            ),
        ):
            with self.assertRaises(ServiceUnavailableError) as raised:
                ingest_pdf_bytes(
                    filename="http.pdf",
                    content=b"%PDF-1.4",
                    subject_id="test-notebook",
                    user_id="user-1",
                )

        self.assertIn("文件处理失败", raised.exception.detail)
        self.assertIn("model not found", raised.exception.detail)

    def test_pdf_parse_failures_remain_validation_errors(self) -> None:
        with (
            patch(
                "app.application.ingest.service.get_subject_record",
                return_value=object(),
            ),
            patch(
                "app.application.ingest.service.extract_text_from_pdf",
                side_effect=RuntimeError("startxref not found"),
            ),
        ):
            with self.assertRaises(ValidationError) as raised:
                ingest_pdf_bytes(
                    filename="broken.pdf",
                    content=b"not-a-real-pdf",
                    subject_id="test-notebook",
                    user_id="user-1",
                )

        self.assertIn("PDF 解析失败或文件格式不正确", raised.exception.detail)

    def test_url_parse_failures_remain_validation_errors(self) -> None:
        with (
            patch(
                "app.application.ingest.service.get_subject_record",
                return_value=object(),
            ),
            patch(
                "app.application.ingest.service._build_url_ingest_payload",
                return_value=([], [], 0),
            ),
        ):
            with self.assertRaises(ValidationError) as raised:
                ingest_urls(
                    subject_id="test-notebook",
                    urls=["https://example.com"],
                    user_id="user-1",
                )

        self.assertIn("所有 URL 解析失败或内容过少", raised.exception.detail)

    def test_url_ingest_writes_personal_documents(self) -> None:
        with (
            patch(
                "app.application.ingest.service.get_subject_record",
                return_value=object(),
            ),
            patch(
                "app.application.ingest.service._build_url_ingest_payload",
                return_value=(
                    ["HTTP content"],
                    [{"subject_id": "test-notebook", "doc_type": "url", "source": "https://example.com"}],
                    1,
                ),
            ),
            patch(
                "app.application.ingest.service.ingest_notebook_documents_with_summary",
                return_value=SimpleNamespace(inserted_chunks=3, mapped_chunks=2, unmapped_chunks=1),
            ) as mocked_ingest,
        ):
            result = ingest_urls(
                subject_id="test-notebook",
                urls=["https://example.com"],
                user_id="user-1",
            )

        self.assertEqual(result.total_chunks, 3)
        self.assertEqual(result.mapped_chunks, 2)
        self.assertEqual(result.unmapped_chunks, 1)
        mocked_ingest.assert_called_once()
        self.assertEqual(mocked_ingest.call_args.kwargs["user_id"], "user-1")

    def test_url_ingest_preserves_zero_mapped_chunks_from_summary(self) -> None:
        with (
            patch(
                "app.application.ingest.service.get_subject_record",
                return_value=object(),
            ),
            patch(
                "app.application.ingest.service._build_url_ingest_payload",
                return_value=(
                    ["unmapped content"],
                    [{"subject_id": "test-notebook", "doc_type": "url", "source": "https://example.com"}],
                    1,
                ),
            ),
            patch(
                "app.application.ingest.service.ingest_notebook_documents_with_summary",
                return_value=SimpleNamespace(inserted_chunks=1, mapped_chunks=0, unmapped_chunks=1),
            ),
        ):
            result = ingest_urls(
                subject_id="test-notebook",
                urls=["https://example.com"],
                user_id="user-1",
            )

        self.assertEqual(result.total_chunks, 1)
        self.assertEqual(result.mapped_chunks, 0)
        self.assertEqual(result.unmapped_chunks, 1)


if __name__ == "__main__":
    unittest.main()
