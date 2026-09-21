"""Duplicate marking: Paperless gets a tag plus a note, the queue stores why."""

from __future__ import annotations

import pytest
import requests

import app.paperless_client as paperless_module
from app.classifier import DocumentClassifier
from app.config import settings
from app.db import Database
from app.db import STATUS_SKIPPED_DUPLICATE
from app.paperless_client import DUPLICATE_TAG_NAME
from app.paperless_client import PaperlessClient
from app.paperless_client import format_duplicate_note


def test_note_names_the_original_and_the_reason() -> None:
    note = format_duplicate_note(38, "Versicherung_Allianz", "ocr_hash")

    assert note.startswith("Duplikat von #38 (Versicherung_Allianz)")
    assert "identischer OCR-Text" in note


def test_note_without_a_known_original_title() -> None:
    assert "Duplikat von #38: identische PDF-Datei" in format_duplicate_note(
        38, None, "file_hash"
    )


def test_unknown_reason_is_not_translated() -> None:
    assert "asn_mismatch" in format_duplicate_note(5, "", "asn_mismatch")


class FakeResponse:
    def __init__(self, payload: object = None) -> None:
        self.payload = payload if payload is not None else {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


@pytest.fixture
def paperless_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, object]]:
    calls: list[tuple[str, str, object]] = []

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        calls.append(("GET", url, kwargs.get("params")))

        if url.endswith("/api/documents/43/"):
            return FakeResponse({"id": 43, "tags": [7]})

        return FakeResponse(
            {"results": [{"id": 11, "name": DUPLICATE_TAG_NAME}], "next": None}
        )

    def fake_patch(url: str, **kwargs: object) -> FakeResponse:
        calls.append(("PATCH", url, kwargs.get("json")))
        return FakeResponse()

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        calls.append(("POST", url, kwargs.get("json")))
        return FakeResponse({"id": 1})

    monkeypatch.setattr(paperless_module.requests, "get", fake_get)
    monkeypatch.setattr(paperless_module.requests, "patch", fake_patch)
    monkeypatch.setattr(paperless_module.requests, "post", fake_post)
    return calls


def test_mark_as_duplicate_keeps_existing_tags(paperless_calls) -> None:
    marking = PaperlessClient().mark_as_duplicate(
        document_id=43,
        original_id=38,
        original_title="Versicherung_Allianz",
        duplicate_reason="ocr_hash",
    )

    assert marking["tag_added"] is True
    patches = [call for call in paperless_calls if call[0] == "PATCH"]
    assert patches == [("PATCH", patches[0][1], {"tags": [7, 11]})]
    notes = [call for call in paperless_calls if call[0] == "POST"]
    assert "#38" in notes[0][2]["note"]
    assert notes[0][2]["is_note"] is True


def _classifier(tmp_path, monkeypatch) -> DocumentClassifier:
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    classifier = DocumentClassifier.__new__(DocumentClassifier)
    classifier.db = Database(str(tmp_path))
    classifier.paperless = PaperlessClient()
    return classifier


def test_duplicate_row_records_the_marking(tmp_path, monkeypatch, paperless_calls) -> None:
    monkeypatch.setattr(settings, "dry_run", False)
    classifier = _classifier(tmp_path, monkeypatch)

    status = classifier._store_duplicate(
        document_id=43,
        file_hash="pdf-hash",
        ocr_hash="ocr-hash",
        duplicate_reason="ocr_hash",
        duplicate_row={"paperless_id": 38, "title": "Versicherung_Allianz"},
    )

    row = dict(
        classifier.db.conn.execute(
            "SELECT status, duplicate_of_paperless_id, error_message FROM documents"
            " WHERE paperless_id = 43"
        ).fetchone()
    )

    assert status == STATUS_SKIPPED_DUPLICATE
    assert row["duplicate_of_paperless_id"] == 38
    assert "marked in Paperless" in row["error_message"]


def test_dry_run_never_marks_in_paperless(
    tmp_path, monkeypatch, paperless_calls
) -> None:
    monkeypatch.setattr(settings, "dry_run", True)
    classifier = _classifier(tmp_path, monkeypatch)

    classifier._store_duplicate(
        document_id=43,
        file_hash="pdf-hash",
        ocr_hash="ocr-hash",
        duplicate_reason="ocr_hash",
        duplicate_row={"paperless_id": 38, "title": "Versicherung_Allianz"},
    )

    row = dict(
        classifier.db.conn.execute(
            "SELECT status, duplicate_of_paperless_id, error_message FROM documents"
            " WHERE paperless_id = 43"
        ).fetchone()
    )

    assert paperless_calls == []
    assert row["error_message"].endswith("not marked (dry run)")


def test_a_failing_marking_stays_a_skipped_duplicate(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "dry_run", False)
    classifier = _classifier(tmp_path, monkeypatch)

    def boom(**kwargs: object) -> None:
        raise requests.RequestException("connection reset")

    monkeypatch.setattr(classifier.paperless, "mark_as_duplicate", boom)

    status = classifier._store_duplicate(
        document_id=43,
        file_hash="pdf-hash",
        ocr_hash="ocr-hash",
        duplicate_reason="ocr_hash",
        duplicate_row={"paperless_id": 38, "title": "Versicherung_Allianz"},
    )

    row = dict(
        classifier.db.conn.execute(
            "SELECT status, duplicate_of_paperless_id, error_message FROM documents"
            " WHERE paperless_id = 43"
        ).fetchone()
    )

    assert status == STATUS_SKIPPED_DUPLICATE
    assert "marking failed: connection reset" in row["error_message"]
