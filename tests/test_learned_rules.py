"""Regression tests for the rules learned from the operator's own corrections.

Every rule here traces back to a repeated manual fix in review_decisions:
document_type Steuer for tax offices, and canonical spellings for correspondents
that Paperless would otherwise create a second time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import settings
from app.db import Database
from app.db import STATUS_AUTO_APPROVED
from app.db import STATUS_MANUALLY_APPROVED
from app.db import STATUS_NEEDS_REVIEW
from app.models import ClassificationResult
from app.paperless_client import resolve_existing_name
from app.paperless_client import to_display_case
from app.review_ui import DEFAULT_CORRECTION_REASON
from app.review_ui import approve
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


def test_accepting_an_unchanged_proposal_needs_no_reason(tmp_path, monkeypatch) -> None:
    """A rule can send a correct document to review; accepting it is not a
    correction, so it must stay possible without writing a reason."""

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    _db_with_decision(tmp_path)

    approve(
        item_id=1,
        title="Rechnung_Amazon_Bueromaterial_2026-05-12",
        correspondent="Amazon",
        document_type="Rechnung",
        tags="Steuer",
        apply_to_paperless=False,
    )

    row = Database(str(tmp_path)).conn.execute(
        "SELECT status FROM documents WHERE paperless_id = 42"
    ).fetchone()

    assert row["status"] == STATUS_MANUALLY_APPROVED


def test_accepting_a_changed_proposal_is_refused(tmp_path, monkeypatch) -> None:
    """Without this the accept button would be a way to skip the reason that the
    learned rules are built from."""

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    _db_with_decision(tmp_path)

    with pytest.raises(HTTPException) as excinfo:
        approve(
            item_id=1,
            title="Rechnung_Amazon_Bueromaterial_2026-05-12",
            correspondent="Amazon",
            document_type="Rechnung",
            tags="Steuer, Buero",
            apply_to_paperless=False,
        )

    assert excinfo.value.status_code == 400
    assert "Speichern" in excinfo.value.detail


def test_the_form_does_not_demand_a_reason_before_the_server_decides() -> None:
    """The browser used to block an unchanged accept with required on the field,
    which is stricter than the rule in save_document."""

    template = (
        Path(__file__).resolve().parent.parent / "app" / "templates" / "review_detail.html"
    ).read_text(encoding="utf-8")

    assert 'name="correction_reason" required' not in template
    assert "/approve" in template


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
        unknown_tag_names=lambda names: [],
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


def test_a_shouted_sender_becomes_initial_capitals() -> None:
    assert to_display_case("MANN GEBÄUDETECHNIK") == "Mann Gebäudetechnik"


def test_a_name_with_lowercase_letters_keeps_its_own_styling() -> None:
    assert to_display_case("ALTE LEIPZIGER Versicherung Aktiengesellschaft") == (
        "ALTE LEIPZIGER Versicherung Aktiengesellschaft"
    )


def test_abbreviations_survive_the_rewrite() -> None:
    assert to_display_case("BKK EUREGIO") == "BKK Euregio"
    assert to_display_case("VOLKSWOHL BUND LEBENSVERSICHERUNG A.G.") == (
        "Volkswohl Bund Lebensversicherung A.G."
    )


def test_an_empty_or_valueless_name_passes_through() -> None:
    assert to_display_case("") == ""
    assert to_display_case(None) == ""
    assert to_display_case("1234 5678") == "1234 5678"


def test_the_display_case_is_idempotent() -> None:
    once = to_display_case("MANN GEBÄUDETECHNIK GMBH")
    assert to_display_case(once) == once


def test_the_classifier_stores_the_shouted_sender_in_nice_case(
    tmp_path, monkeypatch
) -> None:
    """The rewrite has to happen before the title is built and before the row is
    stored, otherwise the queue and the filename keep the shouted spelling."""

    from types import SimpleNamespace

    from app.classifier import DocumentClassifier

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "confidence_threshold", 0.90)

    applied: dict = {}
    classifier = DocumentClassifier.__new__(DocumentClassifier)
    classifier.db = Database(str(tmp_path))
    classifier.paperless = SimpleNamespace(
        download_document=lambda document_id: b"pdf-bytes",
        get_document=lambda document_id: {
            "content": "Stadt Hückelhoven\nGrundsteuerbescheid 2025\nBetrag 312,40 EUR",
            "title": "scan0002",
        },
        update_document_metadata_by_names=lambda **kwargs: (
            applied.update(kwargs) or {"title": kwargs["title"]}
        ),
        unknown_tag_names=lambda names: [],
    )
    classifier.ollama = SimpleNamespace(
        classify=lambda content: ClassificationResult(
            document_type="Steuer",
            correspondent="STADT HÜCKELHOVEN",
            title="unbenannt",
            subject="Grundsteuerbescheid 2025",
            document_date="2025-01-24",
            confidence=0.95,
            reason="Grundsteuerbescheid der Stadt Hückelhoven",
        ),
    )

    assert classifier.process_document(document_id=77) == STATUS_AUTO_APPROVED
    assert applied["correspondent"] == "Stadt Hückelhoven"

    row = classifier.db.conn.execute(
        "SELECT correspondent, title FROM documents WHERE paperless_id = 77"
    ).fetchone()
    assert row["correspondent"] == "Stadt Hückelhoven"
    assert row["title"].startswith("Steuer_Stadt_Hückelhoven_")


def _approved(db, *, paperless_id, correspondent, document_type, tags) -> None:
    db.insert_review_decision(
        document_db_id=paperless_id,
        paperless_id=paperless_id,
        action="saved",
        original_ai_title="titel",
        original_ai_correspondent=correspondent,
        original_ai_document_type=document_type,
        original_ai_tags=["Plunder"],
        final_title="titel",
        final_correspondent=correspondent,
        final_document_type=document_type,
        final_tags=tags,
        reason="Testentscheidung",
    )


def _classifier(tmp_path, monkeypatch, *, tags, unknown_tags=(), confidence=0.98):
    """Worker with the model, Paperless and the queue replaced by fakes."""

    from types import SimpleNamespace

    from app.classifier import DocumentClassifier

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "confidence_threshold", 0.90)

    applied: dict = {}
    classifier = DocumentClassifier.__new__(DocumentClassifier)
    classifier.db = Database(str(tmp_path))
    classifier.paperless = SimpleNamespace(
        download_document=lambda document_id: b"pdf-bytes",
        get_document=lambda document_id: {
            "content": "Stadt Hückelhoven\nGrundsteuerbescheid\nBetrag 312,40 EUR",
            "title": "scan",
        },
        update_document_metadata_by_names=lambda **kwargs: (
            applied.update(kwargs) or {"title": kwargs["title"]}
        ),
        unknown_tag_names=lambda names: list(unknown_tags),
    )
    classifier.ollama = SimpleNamespace(
        classify=lambda content: ClassificationResult(
            document_type="Steuer",
            correspondent="Stadt Hückelhoven",
            title="unbenannt",
            subject="Grundsteuerbescheid",
            document_date="2026-01-23",
            confidence=confidence,
            reason="Grundsteuerbescheid der Stadt",
            tags=tags,
        ),
    )
    return classifier, applied


def _stored(classifier, paperless_id):
    return classifier.db.conn.execute(
        "SELECT status, tags, reason, error_message FROM documents WHERE paperless_id = ?",
        (paperless_id,),
    ).fetchone()


def test_the_kernel_is_the_one_set_he_approved(tmp_path) -> None:
    db = Database(str(tmp_path))
    _approved(
        db,
        paperless_id=52,
        correspondent="Stadt Hückelhoven",
        document_type="Steuer",
        tags=["Grundsteuer", "Nebenkosten", "Grundstück"],
    )

    assert db.tag_kernel("STADT HÜCKELHOVEN", "steuer") == (
        ["Grundsteuer", "Grundstück", "Nebenkosten"],
        1,
    )


def test_a_key_with_two_approved_sets_is_no_rule(tmp_path) -> None:
    db = Database(str(tmp_path))
    _approved(db, paperless_id=37, correspondent="Finanzamt Erkelenz",
              document_type="Steuer", tags=["Einkommensteuer", "Vorauszahlung"])
    _approved(db, paperless_id=38, correspondent="Finanzamt Erkelenz",
              document_type="Steuer", tags=["Einkommensteuer", "Festsetzung"])

    assert db.tag_kernel("Finanzamt Erkelenz", "Steuer") is None


def test_only_the_last_decision_per_document_counts(tmp_path) -> None:
    db = Database(str(tmp_path))
    _approved(db, paperless_id=52, correspondent="Stadt Hückelhoven",
              document_type="Steuer", tags=["Grundsteuer", "Gebühren"])
    _approved(db, paperless_id=52, correspondent="Stadt Hückelhoven",
              document_type="Steuer", tags=["Grundsteuer", "Nebenkosten"])

    assert db.tag_kernel("Stadt Hückelhoven", "Steuer") == (["Grundsteuer", "Nebenkosten"], 1)


def test_the_kernel_counts_every_document_behind_it(tmp_path) -> None:
    """Two documents carrying the same set make it a rule, one is a hint."""

    db = Database(str(tmp_path))
    _approved(db, paperless_id=52, correspondent="Stadt Hückelhoven",
              document_type="Steuer", tags=["Grundsteuer", "Nebenkosten"])
    _approved(db, paperless_id=53, correspondent="STADT HÜCKELHOVEN",
              document_type="steuer", tags=["Nebenkosten", "Grundsteuer"])

    assert db.tag_kernel("Stadt Hückelhoven", "Steuer") == (["Grundsteuer", "Nebenkosten"], 2)


def test_an_unknown_key_has_no_kernel(tmp_path) -> None:
    assert Database(str(tmp_path)).tag_kernel("ERGO", "Versicherung") is None


def test_a_second_groundsteuer_bescheid_gets_the_same_tags(tmp_path, monkeypatch) -> None:
    """pid 52 gegen pid 54: gleiches Jahr-Muster, andere OCR, gleiche Tags."""

    classifier, applied = _classifier(tmp_path, monkeypatch, tags=["Grundsteuer", "Gebühren", "Zähler"])
    _approved(classifier.db, paperless_id=52, correspondent="Stadt Hückelhoven",
              document_type="Steuer", tags=["Grundsteuer", "Nebenkosten", "Grundstück"])

    assert classifier.process_document(document_id=54) == STATUS_NEEDS_REVIEW

    row = _stored(classifier, 54)
    assert json.loads(row["tags"]) == ["Grundsteuer", "Grundstück", "Nebenkosten"]
    assert "freigegeben hast" in row["error_message"]
    assert applied == {}


def test_a_kernel_he_confirmed_twice_applies_without_asking(tmp_path, monkeypatch) -> None:
    """The deviation itself is not a question any more: the tags written to
    Paperless are his own, so only a single-support kernel still asks."""

    classifier, applied = _classifier(tmp_path, monkeypatch, tags=["Grundsteuer", "Zähler"])
    for paperless_id in (52, 53):
        _approved(classifier.db, paperless_id=paperless_id,
                  correspondent="Stadt Hückelhoven", document_type="Steuer",
                  tags=["Grundsteuer", "Nebenkosten", "Grundstück"])

    assert classifier.process_document(document_id=57) == STATUS_AUTO_APPROVED

    assert applied["tags"] == ["Grundsteuer", "Grundstück", "Nebenkosten"]
    row = _stored(classifier, 57)
    assert json.loads(row["tags"]) == ["Grundsteuer", "Grundstück", "Nebenkosten"]
    assert "Regel: Kern-Tags uebernommen" in row["reason"]
    assert row["error_message"] != "Tag rule needs the operator"


def test_a_tag_paperless_does_not_know_is_not_created_silently(tmp_path, monkeypatch) -> None:
    classifier, applied = _classifier(
        tmp_path, monkeypatch, tags=["Grundsteuer", "Zähler"], unknown_tags=["Zähler"]
    )

    assert classifier.process_document(document_id=55) == STATUS_NEEDS_REVIEW
    assert "Zähler" in _stored(classifier, 55)["error_message"]
    assert applied == {}


def test_a_known_tag_set_without_kernel_still_auto_approves(tmp_path, monkeypatch) -> None:
    classifier, applied = _classifier(tmp_path, monkeypatch, tags=["Grundsteuer", "Steuer"])

    assert classifier.process_document(document_id=56) == STATUS_AUTO_APPROVED
    assert applied["tags"] == ["Grundsteuer", "Steuer"]
