"""Regression tests for the LLM output hardening.

These cover the failure modes seen with a 4B model on real documents: an empty
JSON answer, sentence-sized tags, and impossible dates.
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

# The repository keeps the Ollama model store in ./ollama, which shadows the
# installed package when tests run outside the container.
if not hasattr(sys.modules.get("ollama", None), "Client"):
    _ollama_stub = types.ModuleType("ollama")
    _ollama_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["ollama"] = _ollama_stub

import app.ollama_client as ollama_module
from app.classifier import clip_words
from app.models import ClassificationResult
from app.prompts import DOCUMENT_TYPES
from app.validator import validate_classification


def _fake_client(monkeypatch: pytest.MonkeyPatch, payload: object) -> dict:
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def chat(self, **kwargs: object) -> dict:
            captured.update(kwargs)
            return {"message": {"content": json.dumps(payload)}}

    monkeypatch.setattr(ollama_module, "ollama", SimpleNamespace(Client=FakeClient))
    return captured


def test_empty_llm_answer_raises_instead_of_becoming_sonstiges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_client(monkeypatch, {})

    with pytest.raises(ValueError, match="empty classification"):
        ollama_module.OllamaClient().classify("Rechnung über 10,00 EUR")


def test_null_only_llm_answer_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"document_type": None, "correspondent": None, "confidence": None}
    _fake_client(monkeypatch, payload)

    with pytest.raises(ValueError, match="empty classification"):
        ollama_module.OllamaClient().classify("OCR text")


def test_classify_sends_a_json_schema_not_plain_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _fake_client(monkeypatch, {"document_type": "Rechnung", "reason": "x"})

    ollama_module.OllamaClient().classify("OCR text")

    assert isinstance(captured["format"], dict)
    assert captured["format"]["required"]
    assert (
        captured["format"]["properties"]["document_type"]["enum"]
        == list(DOCUMENT_TYPES)
    )


def test_tags_are_bounded_and_sentences_are_dropped() -> None:
    tags = ollama_module._as_tags(
        ["Heizung"]
        + ["Wir behalten uns eine Nachkalkulation in Höhe der am Liefertag gültigen vor"]
        + [f"Tag {index}" for index in range(30)]
    )

    assert len(tags) <= ollama_module.MAX_TAGS
    assert all(len(tag.split()) <= ollama_module.MAX_TAG_WORDS for tag in tags)
    assert "Heizung" in tags


def test_clip_words_cuts_on_the_clause_boundary() -> None:
    clipped = clip_words("Austausch der defekten Platine, an der Heizungsanlage", 5, 45)

    assert clipped == "Austausch der defekten Platine"


def test_clip_words_never_splits_a_word() -> None:
    clipped = clip_words("Kostenvoranschlag fuer den completosten Austauschaufwand", 5, 25)

    assert clipped == "Kostenvoranschlag fuer"


def test_implausible_document_date_sends_invoice_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.validator.settings.confidence_threshold", 0.5)
    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="Mann Gebäudetechnik GmbH",
        title="Rechnung_Mann_Gebaeudetechnik_Platine_1899-05-19_870,58_EUR",
        subject="Platine",
        document_date="1899-05-19",
        amount="870,58 EUR",
        confidence=0.9,
    )

    assert "invalid_document_date" in validate_classification(result).reasons


def test_correspondent_from_a_footer_is_not_applied_automatically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.validator.settings.confidence_threshold", 0.5)
    head = "Allgemeine Geschäftsbedingungen (AGB) der Stromio GmbH für Energie"
    result = ClassificationResult(
        document_type="Vertrag",
        correspondent="Bundesnetzagentur für Elektrizität, Gas, Telekommunikation",
        title="Vertrag_Bundesnetzagentur_AGB_Strom_2020-02-07",
        subject="AGB Stromliefervertrag",
        confidence=0.9,
    )

    reasons = validate_classification(result, document_head=head).reasons
    assert "correspondent_not_in_document_head" in reasons

    # The same check must not fire for a sender that is in the letterhead.
    result.correspondent = "Stromio GmbH"
    assert "correspondent_not_in_document_head" not in validate_classification(
        result,
        document_head=head,
    ).reasons
