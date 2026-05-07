from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.errors import ServiceUnavailableError, ValidationError
from app.application.ingest.service import ingest_pdf_bytes, ingest_urls


class IngestServiceTest(unittest.TestCase):
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
                "app.application.ingest.service.ingest_notebook_documents",
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
                "app.application.ingest.service.ingest_notebook_documents",
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
                "app.application.ingest.service.ingest_notebook_documents",
                return_value=3,
            ) as mocked_ingest,
        ):
            result = ingest_urls(
                subject_id="test-notebook",
                urls=["https://example.com"],
                user_id="user-1",
            )

        self.assertEqual(result.total_chunks, 3)
        mocked_ingest.assert_called_once()
        self.assertEqual(mocked_ingest.call_args.kwargs["user_id"], "user-1")


if __name__ == "__main__":
    unittest.main()
