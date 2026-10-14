"""Tests for the model-free proposal source and the switches around it.

The rules source is what runs when PROPOSAL_SOURCE=rules: the sender comes from
his own Paperless list, the document type from his own approvals, the title date
from the date Paperless parsed while consuming. Nothing here may guess.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from app import health
from app.config import settings
from app.db import Database
from app.db import STATUS_MANUALLY_APPROVED
from app.models import ClassificationResult
from app.proposal_source import OllamaProposalSource
from app.proposal_source import ProposalRequest
from app.proposal_source import ProposalSource
from app.proposal_source import RulesProposalSource
from app.proposal_source import build_proposal_source
from app.validator import validate_classification


def _request(content: str = "Finanzamt Erkelenz\nGrundsteuerbescheid 2026", created="2026-01-23"):
    return ProposalRequest(
        document_id=7,
        content=content,
        ocr_excerpt=content,
        document={"content": content, "title": "scan0007", "created": created},
    )


def _rules_source(sender="Finanzamt Erkelenz", kernel=("Steuer", 4, 1)):
    paperless = SimpleNamespace(
        correspondent_from_text=lambda text: sender,
        resolve_correspondent_name=lambda name: name,
    )
    db = SimpleNamespace(type_kernel=lambda correspondent: kernel)
    return RulesProposalSource(paperless, db)


def test_rules_source_proposes_sender_type_and_date_from_his_own_records():
    result = _rules_source().classify(_request())

    assert result.correspondent == "Finanzamt Erkelenz"
    assert result.document_type == "Steuer"
    assert result.document_date == "2026-01-23"
    assert result.confidence == settings.rules_confidence_matching
    assert "4 Belege" in result.reason


def test_title_of_a_rules_proposal_keeps_the_paperless_date_as_last_component():
    from app.classifier import build_document_title

    result = _rules_source().classify(_request())
    result.title = build_document_title(result)

    assert result.title == "Steuer_Finanzamt_Erkelenz_2026-01-23"


def test_an_unknown_sender_stays_a_placeholder_and_goes_to_review():
    result = _rules_source(sender=None, kernel=(None, 0, 0)).classify(_request())

    assert result.correspondent == "Unbekannt"
    assert result.document_type == "Sonstiges"
    assert result.confidence == 0.5

    validation = validate_classification(result, document_head="Grundsteuer 2026")
    assert not validation.valid
    assert "placeholder_correspondent" in validation.reasons
    assert "low_confidence" in validation.reasons


def test_an_ambiguous_sender_type_is_reported_as_open_not_average():
    result = _rules_source(kernel=(None, 3, 2)).classify(_request())

    assert result.document_type == "Sonstiges"
    assert result.confidence == settings.rules_confidence_partial
    assert "2 Typen" in result.reason


def test_date_component_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "proposal_date_source", "none")

    result = _rules_source().classify(_request())

    assert result.document_date is None


def test_model_only_skips_the_evidence_fields_nobody_can_fill(monkeypatch):
    monkeypatch.setattr(settings, "proposal_source", "rules")
    monkeypatch.setattr(settings, "type_evidence_required", "model_only")

    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="KAVA Automobile GmbH",
        title="Rechnung_KAVA_Automobile_GmbH_Wechsel_2026-05-04",
        confidence=0.95,
    )
    validation = validate_classification(result, document_head="KAVA Automobile GmbH")

    assert validation.valid

    monkeypatch.setattr(settings, "type_evidence_required", "always")
    reasons = validate_classification(result, document_head="KAVA Automobile GmbH").reasons
    assert "missing_amount_for_invoice" in reasons


def test_model_only_still_checks_evidence_while_the_model_runs(monkeypatch):
    monkeypatch.setattr(settings, "proposal_source", "ollama")
    monkeypatch.setattr(settings, "type_evidence_required", "model_only")

    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="KAVA Automobile GmbH",
        title="Rechnung_KAVA_Automobile_GmbH_Wechsel_2026-05-04",
        confidence=0.95,
    )
    reasons = validate_classification(result, document_head="KAVA Automobile GmbH").reasons

    assert "missing_amount_for_invoice" in reasons


def test_type_kernel_only_returns_a_type_he_gave_once(tmp_path):
    db = Database(str(tmp_path))

    def approve(paperless_id: int, correspondent: str, document_type: str) -> None:
        db.insert_review_decision(
            document_db_id=paperless_id,
            paperless_id=paperless_id,
            action="saved",
            original_ai_title=None,
            original_ai_correspondent=None,
            original_ai_document_type=None,
            original_ai_tags=None,
            final_title=None,
            final_correspondent=correspondent,
            final_document_type=document_type,
            final_tags=None,
        )

    assert db.type_kernel("AXA Versicherung AG") == (None, 0, 0)

    approve(1, "AXA Versicherung AG", "Versicherung")
    approve(2, "axa versicherung ag", "Versicherung")
    assert db.type_kernel("AXA Versicherung AG") == ("Versicherung", 2, 1)

    approve(3, "AXA Versicherung AG", "Rechnung")
    assert db.type_kernel("AXA Versicherung AG") == (None, 3, 2)

    assert db.type_kernel("") == (None, 0, 0)
    db.close()


def test_approved_document_rows_alone_do_not_create_a_rule(tmp_path):
    """Only his decisions count, the same line tag_kernel draws."""

    db = Database(str(tmp_path))
    db.insert_document(
        paperless_id=11,
        file_hash="hash",
        ocr_hash=None,
        title="Rechnung_ERGO_Jahr",
        correspondent="ERGO",
        document_type="Rechnung",
        tags=[],
        confidence=0.95,
        reason=None,
        original_title=None,
        ocr_excerpt=None,
        paperless_url=None,
        export_path="",
        status=STATUS_MANUALLY_APPROVED,
        error_message=None,
    )

    assert db.type_kernel("ERGO") == (None, 0, 0)
    db.close()


def test_factory_honours_the_switch_and_rejects_an_unknown_source(monkeypatch):
    paperless = SimpleNamespace()
    db = SimpleNamespace()

    monkeypatch.setattr(settings, "proposal_source", "rules")
    assert isinstance(build_proposal_source(paperless, db), RulesProposalSource)

    monkeypatch.setattr(settings, "proposal_source", "papierlos")
    with pytest.raises(ValueError, match="PROPOSAL_SOURCE"):
        build_proposal_source(paperless, db)


def test_readiness_ignores_the_model_when_the_model_is_out(monkeypatch, tmp_path):
    """Without this the worker stays unhealthy forever after Ollama is removed."""

    monkeypatch.setattr(settings, "proposal_source", "rules")
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(health.requests, "get", _only_paperless_answers)

    payload = health.check_health()

    assert payload["ollama"] == {"status": "not_configured", "model": None}
    assert payload["status"] == "ok"


def test_readiness_still_needs_the_model_in_model_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "proposal_source", "ollama")
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(health.requests, "get", _only_paperless_answers)

    payload = health.check_health()

    assert payload["status"] == "degraded"
    assert payload["ollama"]["status"] == "error"


class _Ok:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"models": [{"name": settings.ollama_model}]}


def _only_paperless_answers(url, *args, **kwargs):
    if "/api/tags" in url:
        raise requests.exceptions.ConnectionError("ollama container gone")
    return _Ok()


def test_ollama_source_hands_over_the_raw_content():
    seen = {}

    class Client:
        def classify(self, content):
            seen["content"] = content
            return ClassificationResult(document_type="Brief")

    source: ProposalSource = OllamaProposalSource(client=Client())
    result = source.classify(_request(content="ganter OCR-Text"))

    assert seen["content"] == "ganter OCR-Text"
    assert result.document_type == "Brief"
