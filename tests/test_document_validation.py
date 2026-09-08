"""Tests for backend/documents/validation.py -- pure functions, no mocking needed."""
from backend.documents.validation import MAX_UPLOAD_SIZE_BYTES, document_type_for, validate_upload

import pytest


def test_accepts_valid_pdf():
    validate_upload("report.pdf", "application/pdf", 1024)


def test_accepts_valid_jpg():
    validate_upload("scan.jpg", "image/jpeg", 1024)


def test_accepts_valid_png():
    validate_upload("scan.png", "image/png", 1024)


def test_rejects_disallowed_extension():
    with pytest.raises(ValueError, match="Unsupported file type"):
        validate_upload("report.exe", "application/pdf", 1024)


def test_rejects_disallowed_content_type():
    with pytest.raises(ValueError, match="Unsupported content type"):
        validate_upload("report.pdf", "application/octet-stream", 1024)


def test_rejects_empty_file():
    with pytest.raises(ValueError, match="empty"):
        validate_upload("report.pdf", "application/pdf", 0)


def test_rejects_oversized_file():
    with pytest.raises(ValueError, match="too large"):
        validate_upload("report.pdf", "application/pdf", MAX_UPLOAD_SIZE_BYTES + 1)


def test_document_type_for_pdf():
    assert document_type_for("application/pdf") == "pdf"


def test_document_type_for_image():
    assert document_type_for("image/jpeg") == "image"
    assert document_type_for("image/png") == "image"
