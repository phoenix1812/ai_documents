"""Regression tests for the rules learned from the operator's own corrections.

Every rule here traces back to a repeated manual fix in review_decisions:
document_type Steuer for tax offices, and canonical spellings for correspondents
that Paperless would otherwise create a second time.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import settings
from app.db import Database
from app.db import STATUS_AUTO_APPROVED
from app.models import ClassificationResult
from app.paperless_client import resolve_existing_name
from app.review_ui import DEFAULT_CORRECTION_REASON
from app.review_ui import save_document
from app.validator import apply_tax_authority_type_rule


def _result(**overrides) -> ClassificationResult:
    base = dict(
        document_type="Rechnung",
        correspondent="Finanzamt Erkelenz",
        title="Rechnung_Finanzamt_Erkelenz_Bescheid_2026-05-01",
        confidence=0.95,
    )
    base.update(overrides)
    return ClassificationResult(**base)


def test_tax_office_forces_the_type_to_steuer() -> None:
    result = _result()

    assert apply_tax_authority_type_rule(result) is True
    assert result.document_type == "Steuer"


def test_an_already_correct_type_is_left_alone() -> None:
    result = _result(document_type="Steuer")

    assert apply_tax_authority_type_rule(result) is False
    assert result.document_type == "Steuer"


def test_the_rule_does_not_touch_other_senders() -> None:
    result = _result(correspondent="Mann Gebäudetechnik GmbH")

    assert apply_tax_authority_type_rule(result) is False
    assert result.document_type == "Rechnung"


CORRESPONDENTS = [
    {"id": 10, "name": "Finanzamt Erkelenz", "document_count": 9},
    {"id": 12, "name": "Finanzamt", "document_count": 0},
    {"id": 17, "name": "Mann Gebäudetechnik GmbH", "document_count": 8},
    {"id": 40, "name": "AXA Versicherung AG", "document_count": 1},
]


def test_a_vague_sender_name_resolves_to_the_established_spelling() -> None:
    # The model writing "Finanzamt" must not attach documents to the empty
    # duplicate correspondent that the old code created for it.
    match = resolve_existing_name("Finanzamt", CORRESPONDENTS)

    assert match is not None
    assert match["name"] == "Finanzamt Erkelenz"


def test_capitalisation_differences_land_on_the_same_correspondent() -> None:
    match = resolve_existing_name("MANN GEBÄUDETECHNIK", CORRESPONDENTS)

    assert match is not None
    assert match["name"] == "Mann Gebäudetechnik GmbH"


def test_a_more_specific_sender_is_not_merged_into_a_shorter_one() -> None:
    # "Mann Gebäudetechnik Service GmbH" really could be a different company,
    # so containment only ever resolves vague -> specific.
    assert resolve_existing_name("Gebäudetechnik Service GmbH", CORRESPONDENTS) is None


def test_short_sender_names_are_not_matched_by_containment() -> None:
    assert resolve_existing_name("ERV", CORRESPONDENTS) is None
    assert resolve_existing_name("AXA", CORRESPONDENTS) is None


def test_an_unknown_sender_creates_no_match() -> None:
    assert resolve_existing_name("WestVerkehr GmbH", CORRESPONDENTS) is None


def test_equal_document_counts_refuse_to_guess() -> None:
    tied = [
        {"id": 1, "name": "Muster Stadtwerke GmbH", "document_count": 3},
        {"id": 2, "name": "Muster Stadtwerke Nord", "document_count": 3},
    ]

    assert resolve_existing_name("Muster Stadtwerke", tied) is None


def _db_with_decision(tmp_path, paperless_id: int = 42) -> Database:
    db = Database(str(tmp_path))
    db.insert_document(
        paperless_id=paperless_id,
        file_hash=f"hash-{paperless_id}",
        title="Rechnung_Amazon_Bueromaterial_2026-05-12",
        correspondent="Amazon",
        document_type="Rechnung",
        tags=["Steuer"],
        export_path="",
        status=STATUS_AUTO_APPROVED,
    )
    return db


def test_correction_patterns_group_repeated_type_fixes(tmp_path) -> None:
    db = _db_with_decision(tmp_path)

    for paperless_id, final_type in ((42, "Steuer"), (43, "Steuer"), (44, "Bank")):
        db.insert_review_decision(
            document_db_id=1,
            paperless_id=paperless_id,
            action="saved",
            original_ai_title="t",
            original_ai_correspondent="Finanzamt",
            original_ai_document_type="Rechnung",
            original_ai_tags=[],
            final_title="t",
            final_correspondent="Finanzamt Erkelenz",
            final_document_type=final_type,
            final_tags=[],
        )

    patterns = db.correction_patterns()

    assert patterns["document_types"][0]["from_value"] == "Rechnung"
    assert patterns["document_types"][0]["to_value"] == "Steuer"
    assert patterns["document_types"][0]["occurrences"] == 2
    assert patterns["correspondents"][0]["to_value"] == "Finanzamt Erkelenz"


def test_correction_patterns_ignore_unchanged_decisions(tmp_path) -> None:
    db = _db_with_decision(tmp_path)
    db.insert_review_decision(
        document_db_id=1,
        paperless_id=42,
        action="saved",
        original_ai_title="t",
        original_ai_correspondent="Amazon",
        original_ai_document_type="Rechnung",
        original_ai_tags=[],
        final_title="t",
        final_correspondent="Amazon",
        final_document_type="Rechnung",
        final_tags=[],
    )

    assert db.correction_patterns() == {"document_types": [], "correspondents": []}


def test_a_content_correction_demands_a_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    _db_with_decision(tmp_path)

    with pytest.raises(HTTPException) as excinfo:
        save_document(
            item_id=1,
            title="Rechnung_Amazon_Bueromaterial_2026-05-12",
            correspondent="Finanzamt Erkelenz",
            document_type="Rechnung",
            tags="Steuer",
            apply_to_paperless=False,
            # What the form submits when he leaves the field empty; the old
            # pre-filled placeholder has to be rejected the same way.
            correction_reason="",
        )

    assert excinfo.value.status_code == 400
    assert "Grund" in excinfo.value.detail

    with pytest.raises(HTTPException) as excinfo:
        save_document(
            item_id=1,
            title="Rechnung_Amazon_Bueromaterial_2026-05-12",
            correspondent="Finanzamt Erkelenz",
            document_type="Rechnung",
            tags="Steuer",
            apply_to_paperless=False,
            correction_reason=DEFAULT_CORRECTION_REASON,
        )

    assert excinfo.value.status_code == 400


def test_a_correction_with_a_reason_is_stored(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    _db_with_decision(tmp_path)

    save_document(
        item_id=1,
        title="Steuer_Finanzamt_Erkelenz_Bescheid_2026-05-12",
        correspondent="Finanzamt Erkelenz",
        document_type="Steuer",
        tags="Steuer",
        apply_to_paperless=False,
        correction_reason="Absender verwechselt",
    )

    row = Database(str(tmp_path)).conn.execute(
        "SELECT final_correspondent, final_document_type, reason FROM review_decisions"
    ).fetchone()

    assert row["final_correspondent"] == "Finanzamt Erkelenz"
    assert row["final_document_type"] == "Steuer"
    assert row["reason"] == "Absender verwechselt"


def test_a_pure_title_edit_still_needs_no_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    _db_with_decision(tmp_path)

    save_document(
        item_id=1,
        title="Anderer_Titel",
        correspondent="Amazon",
        document_type="Rechnung",
        tags="Steuer",
        apply_to_paperless=False,
        correction_reason="",
    )

    assert Database(str(tmp_path)).conn.execute(
        "SELECT title FROM documents WHERE paperless_id = 42"
    ).fetchone()["title"] == "Anderer_Titel"


def test_the_rule_rewrites_the_title_before_paperless_sees_it(tmp_path, monkeypatch) -> None:
    """Ordering matters: document_type is a title component, so the rule has to
    run before build_document_title or Paperless keeps an invoice title."""

    from types import SimpleNamespace

    from app.classifier import DocumentClassifier
    from app.db import STATUS_AUTO_APPROVED

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "confidence_threshold", 0.90)

    applied: dict = {}
    classifier = DocumentClassifier.__new__(DocumentClassifier)
    classifier.db = Database(str(tmp_path))
    classifier.paperless = SimpleNamespace(
        download_document=lambda document_id: b"pdf-bytes",
        get_document=lambda document_id: {
            "content": "Finanzamt Erkelenz\nEinkommensteuerbescheid 2025\nBetrag 1.234,56 EUR",
            "title": "scan0001",
        },
        update_document_metadata_by_names=lambda **kwargs: (
            applied.update(kwargs) or {"title": kwargs["title"]}
        ),
    )
    classifier.ollama = SimpleNamespace(
        classify=lambda content: ClassificationResult(
            document_type="Rechnung",
            correspondent="Finanzamt Erkelenz",
            title="unbenannt",
            subject="Einkommensteuerbescheid 2025",
            document_date="2025-11-03",
            confidence=0.95,
            reason="Dokument ist ein Steuerbescheid des Finanzamtes",
        ),
    )

    assert classifier.process_document(document_id=60) == STATUS_AUTO_APPROVED
    assert applied["document_type"] == "Steuer"
    assert applied["title"].startswith("Steuer_Finanzamt_Erkelenz_")
