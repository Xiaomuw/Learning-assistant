"""Real multipart/PDF parsing with original in-memory documents; storage is fake."""
from __future__ import annotations

import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.application.ingest import service
from app.interfaces.api.upload import router
from app.interfaces.auth.dependencies import require_current_user


def synthetic_pdf(*, blank: bool = False) -> bytes:
    """Generate our own text and a blank page without third-party document assets."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if not blank:
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 250 Td (Synthetic HTTP lesson: a request has a method.) Tj ET")
        page[NameObject("/Contents")] = stream
        writer.add_blank_page(width=300, height=300)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class UploadParserTest(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id="synthetic-user")
        self.app = app
        self.client = self.enterContext(TestClient(app))
        self.enterContext(patch.object(service, "get_subject_record", return_value=object()))
        self.storage = self.enterContext(patch.object(
            service, "ingest_notebook_documents_with_summary",
            return_value=SimpleNamespace(inserted_chunks=1, mapped_chunks=0, unmapped_chunks=1),
        ))
        self.parser = self.enterContext(patch.object(
            service, "extract_text_from_pdf", wraps=service.extract_text_from_pdf,
        ))

    def upload(self, content: bytes, filename: str = "原创-lesson.pdf"):
        return self.client.post(
            "/api/upload", data={"subject_id": "computer-network"},
            files={"file": (filename, content, "application/pdf")},
        )

    def assert_temporary_files_removed(self) -> None:
        for call in self.parser.call_args_list:
            self.assertFalse(Path(call.args[0]).exists(), "PDF temporary file must be removed")

    def test_real_pdf_multipart_preserves_text_page_source_and_owner(self) -> None:
        response = self.upload(synthetic_pdf())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["filename"], "原创-lesson.pdf")
        # Existing API counts extracted nonempty pages; metadata retains physical pages.
        self.assertEqual(response.json()["total_pages"], 1)
        self.assertEqual(response.json()["mapped_chunks"], 0)
        self.storage.assert_called_once()
        payload = self.storage.call_args.kwargs
        self.assertEqual(payload["texts"], ["Synthetic HTTP lesson: a request has a method."])
        self.assertEqual(payload["user_id"], "synthetic-user")
        self.assertEqual(payload["subject_id"], "computer-network")
        metadata = payload["metadatas"][0]
        self.assertEqual(metadata["source_file"], "原创-lesson.pdf")
        self.assertEqual(metadata["total_pages"], 2)
        self.assertEqual((metadata["page_start"], metadata["page_end"]), (1, 1))
        self.assertEqual(metadata["visibility"], "personal")
        self.assert_temporary_files_removed()

    def test_corrupt_pdf_is_client_error_and_cleans_temporary_file(self) -> None:
        response = self.upload(b"not a PDF")
        self.assertEqual(response.status_code, 400, response.text)
        self.parser.assert_called_once()
        self.storage.assert_not_called()
        self.assert_temporary_files_removed()

    def test_blank_pdf_is_client_error_without_storage_write(self) -> None:
        response = self.upload(synthetic_pdf(blank=True))
        self.assertEqual(response.status_code, 400, response.text)
        self.storage.assert_not_called()
        self.assert_temporary_files_removed()

    def test_empty_and_wrong_extension_are_rejected_before_parsing(self) -> None:
        for filename, data in [("empty.pdf", b""), ("lesson.txt", b"synthetic text")]:
            with self.subTest(filename=filename):
                response = self.upload(data, filename)
                self.assertEqual(response.status_code, 400, response.text)
        self.parser.assert_not_called()
        self.storage.assert_not_called()

    def test_missing_file_is_validation_error(self) -> None:
        response = self.client.post("/api/upload", data={"subject_id": "computer-network"})
        self.assertEqual(response.status_code, 422, response.text)
        self.storage.assert_not_called()

    def test_multipart_without_boundary_is_rejected(self) -> None:
        response = self.client.post(
            "/api/upload", content=b"invalid form", headers={"Content-Type": "multipart/form-data"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.storage.assert_not_called()

    def test_unauthenticated_upload_never_reaches_ingestion(self) -> None:
        self.app.dependency_overrides.clear()
        response = self.upload(synthetic_pdf())
        self.assertEqual(response.status_code, 401, response.text)
        self.parser.assert_not_called()
        self.storage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
