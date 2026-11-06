"""Deadline extraction, its two gates, and the custom field it is written to.

The archive this was measured on contains no deadline that survives the gates, so
every positive case here is a wording the patterns are built for rather than one
his documents currently carry. The negative cases are the measured ones: the life
insurance running to 2055, the nine expired payment dates, and the contract that
names two different dates at once.
"""

from __future__ import annotations

import unicodedata
from datetime import date
from datetime import timedelta

import pytest

from app.deadline import DEADLINE_FIELD_NAME
from app.deadline import DEADLINE_FIELD_TYPE
from app.deadline import DEADLINE_MAX_YEARS_AHEAD
from app.deadline import extract_deadline
from app.models import ClassificationResult
from app.paperless_client import PaperlessClient
from app.validator import validate_classification

TODAY = date(2026, 11, 3)


@pytest.mark.parametrize(
    ("text", "expected", "label"),
    [
        ("Der Betrag ist zahlbar bis zum 15.11.2026.", "2026-11-15", "zahlbar bis"),
        ("zahlbar bis zur 15.11.2026", "2026-11-15", "zahlbar bis"),
        ("Der Beitrag ist fällig am 01.12.2026.", "2026-12-01", "fällig am"),
        ("Der Beitrag ist faellig zum 01.12.2026.", "2026-12-01", "fällig am"),
        ("Zahlungsziel: 30.11.26", "2026-11-30", "Zahlungsziel"),
        ("Zahlung bis 30.11.2026", "2026-11-30", "Zahlung bis"),
        ("Einspruchsfrist 03.12.2026", "2026-12-03", "Rechtsmittelfrist"),
        ("Widerspruchsfrist: bis 03.12.2026", "2026-12-03", "Rechtsmittelfrist"),
        ("Kündigungsfrist 31.01.2027", "2027-01-31", "Rechtsmittelfrist"),
    ],
)
def test_payment_wordings_are_recognised(text, expected, label) -> None:
    deadline = extract_deadline(text, today=TODAY)

    assert deadline is not None
    assert deadline.date == expected
    assert deadline.label == label
    # The wording it was read from, so he can check the field against the letter.
    assert deadline.evidence


def test_the_evidence_is_the_wording_itself() -> None:
    deadline = extract_deadline("Bitte überweisen Sie, zahlbar bis zum 15.11.2026.", today=TODAY)

    assert deadline is not None
    assert deadline.evidence == "zahlbar bis zum 15.11.2026"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Vertragsablauf: 01.12.2027", "2027-12-01"),
        ("Der Vertrag endet am 01.12.2027.", "2027-12-01"),
        ("Der Vertrag läuft aus am 01.12.2027.", "2027-12-01"),
        ("Dieses Zertifikat ist gültig bis 31.12.2026.", "2026-12-31"),
        ("Änderungsbeginn: 01.12.2026", "2026-12-01"),
    ],
)
def test_contract_wordings_are_recognised_when_no_payment_date_exists(text, expected) -> None:
    deadline = extract_deadline(text, today=TODAY)

    assert deadline is not None
    assert deadline.date == expected


def test_a_payment_deadline_outranks_a_contract_date_in_the_same_document() -> None:
    deadline = extract_deadline(
        "Bitte überweisen Sie, zahlbar bis zum 15.11.2026. Vertragsablauf: 01.12.2027.",
        today=TODAY,
    )

    assert deadline is not None
    assert deadline.date == "2026-11-15"


def test_two_dates_of_the_same_class_are_refused_instead_of_picked() -> None:
    # Measured live on 2026-11-04 over the 7589 characters of paperless 110: both
    # wordings below are found and both pass the gates, and the field stays empty.
    assert extract_deadline(
        "Vertragsablauf: 01.12.2027 Änderungsbeginn: 01.12.2026",
        today=TODAY,
    ) is None

    # Drop one wording and the refusal must go away: what decided was the second
    # date, not a pattern that failed to match.
    deadline = extract_deadline(
        "Vertragsablauf: 01.12.2027",
        today=TODAY,
    )

    assert deadline is not None
    assert deadline.date == "2027-12-01"
    assert deadline.label == "Vertragsablauf"


def test_two_payment_deadlines_are_refused_too() -> None:
    assert extract_deadline(
        "zahlbar bis 15.11.2026, ersatzweise fällig am 20.12.2026",
        today=TODAY,
    ) is None


def test_the_same_date_worded_twice_is_not_ambiguous() -> None:
    deadline = extract_deadline(
        "zahlbar bis 15.11.2026. Wir erinnern Sie: zahlbar bis zum 15.11.2026.",
        today=TODAY,
    )

    assert deadline is not None
    assert deadline.date == "2026-11-15"


def test_an_expired_deadline_is_not_written() -> None:
    assert extract_deadline("Der Beitrag war fällig am 01.05.2026.", today=TODAY) is None


def test_a_deadline_beyond_the_horizon_is_not_written() -> None:
    # The measured artefact: a life insurance whose text names the year 2055.
    assert extract_deadline("Beitrag zahlbar bis 01.08.2055.", today=TODAY) is None


def test_the_horizon_reaches_exactly_the_configured_years_ahead() -> None:
    limit = TODAY.replace(year=TODAY.year + DEADLINE_MAX_YEARS_AHEAD)

    inside = extract_deadline(f"zahlbar bis {limit:%d.%m.%Y}", today=TODAY)
    outside = extract_deadline(f"zahlbar bis {limit.replace(day=limit.day + 1):%d.%m.%Y}", today=TODAY)

    assert inside is not None
    assert inside.date == limit.isoformat()
    assert outside is None


def test_an_impossible_calendar_date_is_ocr_damage_not_metadata() -> None:
    assert extract_deadline("Rechnung zahlbar bis 31.02.2027.", today=TODAY) is None


def test_a_bare_date_without_a_deadline_wording_is_not_read() -> None:
    assert extract_deadline("Rechnung 12.345,67 EUR, Kundennummer 99.12.2027", today=TODAY) is None


def test_a_delivery_period_is_not_a_deadline() -> None:
    assert extract_deadline("Lieferzeit bis zu 3 Wochen ab dem 05.11.2026.", today=TODAY) is None


def test_decomposed_umlauts_match_the_same_way_as_composed_ones() -> None:
    text = "Der Beitrag ist fällig am 01.12.2026."
    composed = extract_deadline(text, today=TODAY)
    decomposed = extract_deadline(unicodedata.normalize("NFD", text), today=TODAY)

    assert composed is not None
    assert composed == decomposed


def test_a_document_without_text_yields_nothing() -> None:
    assert extract_deadline("", today=TODAY) is None
    assert extract_deadline(None, today=TODAY) is None


def test_the_validator_accepts_a_deadline_at_the_horizon() -> None:
    far = date.today().replace(year=date.today().year + DEADLINE_MAX_YEARS_AHEAD)
    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="Mann Gebäudetechnik GmbH",
        title="Rechnung_Mann_Gebäudetechnik_GmbH_2026-11-03",
        due_date=far.isoformat(),
        confidence=0.95,
    )

    assert "invalid_due_date" not in validate_classification(result).reasons


def test_the_validator_still_rejects_a_deadline_beyond_the_horizon() -> None:
    too_far = date.today().replace(year=date.today().year + DEADLINE_MAX_YEARS_AHEAD + 1)
    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="Mann Gebäudetechnik GmbH",
        title="Rechnung_Mann_Gebäudetechnik_GmbH_2026-11-03",
        due_date=too_far.isoformat(),
        confidence=0.95,
    )

    assert "invalid_due_date" in validate_classification(result).reasons


def test_the_document_date_keeps_its_narrower_bound() -> None:
    too_far = date.today().replace(year=date.today().year + DEADLINE_MAX_YEARS_AHEAD)
    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="Mann Gebäudetechnik GmbH",
        title="Rechnung_Mann_Gebäudetechnik_GmbH_2026-11-03",
        document_date=too_far.isoformat(),
        confidence=0.95,
    )

    assert "invalid_document_date" in validate_classification(result).reasons


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

        if url.endswith("/api/custom_fields/"):
            return FakeResponse(
                {"results": [{"id": 5, "name": DEADLINE_FIELD_NAME}], "next": None}
            )
        if url.endswith("/api/documents/110/"):
            return FakeResponse(
                {
                    "id": 110,
                    "custom_fields": [
                        {"field": 9, "value": "Rechnung"},
                        {"field": 5, "value": "2026-11-15"},
                    ],
                }
            )
        raise AssertionError(url)

    def fake_patch(url: str, **kwargs: object) -> FakeResponse:
        calls.append(("PATCH", url, kwargs.get("json")))
        return FakeResponse()

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        calls.append(("POST", url, kwargs.get("json")))
        return FakeResponse({"id": 5})

    import app.paperless_client as paperless_module

    monkeypatch.setattr(paperless_module.requests, "get", fake_get)
    monkeypatch.setattr(paperless_module.requests, "patch", fake_patch)
    monkeypatch.setattr(paperless_module.requests, "post", fake_post)
    return calls


def test_writing_a_deadline_keeps_the_other_custom_fields(paperless_calls) -> None:
    outcome = PaperlessClient().set_custom_field(
        document_id=110,
        name=DEADLINE_FIELD_NAME,
        data_type=DEADLINE_FIELD_TYPE,
        value="2026-12-01",
    )

    patches = [payload for method, _, payload in paperless_calls if method == "PATCH"]
    assert outcome == {"field": DEADLINE_FIELD_NAME, "value": "2026-12-01", "written": True}
    # Paperless treats the list as the whole truth: anything missing is deleted.
    assert patches == [
        {
            "custom_fields": [
                {"field": 9, "value": "Rechnung"},
                {"field": 5, "value": "2026-12-01"},
            ]
        }
    ]


def test_an_unchanged_deadline_does_not_touch_paperless(paperless_calls) -> None:
    outcome = PaperlessClient().set_custom_field(
        document_id=110,
        name=DEADLINE_FIELD_NAME,
        data_type=DEADLINE_FIELD_TYPE,
        value="2026-11-15",
    )

    assert outcome["written"] is False
    assert not [call for call in paperless_calls if call[0] == "PATCH"]


def test_the_pipeline_stores_the_deadline_and_writes_it_to_paperless(
    tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from app.classifier import DocumentClassifier
    from app.config import settings
    from app.db import Database
    from app.db import STATUS_AUTO_APPROVED

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "confidence_threshold", 0.90)
    # Both are the values his worker runs with. A rules-only proposer cannot
    # read an amount, so the invoice evidence check is switched off with it.
    monkeypatch.setattr(settings, "proposal_source", "rules")
    monkeypatch.setattr(settings, "type_evidence_required", "model_only")

    # Relative to the run date: the pipeline reads today from the clock, so a
    # hard coded "future" deadline would silently expire and turn this test red.
    due = date.today() + timedelta(days=17)
    content = (
        "Mann Gebäudetechnik GmbH\nRechnung 2026-1103\n"
        f"Bitte überweisen Sie den Betrag, zahlbar bis zum {due:%d.%m.%Y}."
    )
    written: list[tuple] = []

    classifier = DocumentClassifier.__new__(DocumentClassifier)
    classifier.db = Database(str(tmp_path))
    classifier.paperless = SimpleNamespace(
        download_document=lambda document_id: b"pdf-bytes",
        get_document=lambda document_id: {"content": content, "title": "scan0110"},
        update_document_metadata_by_names=lambda **kwargs: {"title": kwargs["title"]},
        set_custom_field=lambda **kwargs: written.append(kwargs) or {"written": True},
        unknown_tag_names=lambda names: [],
        correspondent_from_text=lambda text: "Mann Gebäudetechnik GmbH",
        resolve_correspondent_name=lambda name: None,
    )
    classifier.source = SimpleNamespace(
        classify=lambda request: ClassificationResult(
            document_type="Rechnung",
            correspondent="Mann Gebäudetechnik GmbH",
            title="unbenannt",
            subject="Heizungswartung",
            document_date="2026-11-03",
            confidence=0.95,
            reason="Vorschlag aus dem Bestand",
        ),
    )

    assert classifier.process_document(document_id=110) == STATUS_AUTO_APPROVED

    assert written == [
        {
            "document_id": 110,
            "name": DEADLINE_FIELD_NAME,
            "data_type": DEADLINE_FIELD_TYPE,
            "value": due.isoformat(),
        }
    ]

    row = classifier.db.get_latest_for_paperless_id(110)
    assert row["due_date"] == due.isoformat()
    assert f'Frist {due} aus "zahlbar bis zum {due:%d.%m.%Y}"' in row["reason"]
    assert f"Frist {due} gesetzt" in row["error_message"]


def test_a_deadline_outside_the_gates_leaves_the_custom_field_alone(
    tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from app.classifier import DocumentClassifier
    from app.config import settings
    from app.db import Database
    from app.db import STATUS_AUTO_APPROVED

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "confidence_threshold", 0.90)
    # Both are the values his worker runs with. A rules-only proposer cannot
    # read an amount, so the invoice evidence check is switched off with it.
    monkeypatch.setattr(settings, "proposal_source", "rules")
    monkeypatch.setattr(settings, "type_evidence_required", "model_only")

    content = (
        "Mann Gebäudetechnik GmbH\nRechnung 2020-0113\n"
        "Der Betrag war zahlbar bis zum 20.01.2020."
    )
    written: list[tuple] = []

    classifier = DocumentClassifier.__new__(DocumentClassifier)
    classifier.db = Database(str(tmp_path))
    classifier.paperless = SimpleNamespace(
        download_document=lambda document_id: b"pdf-bytes",
        get_document=lambda document_id: {"content": content, "title": "scan0113"},
        update_document_metadata_by_names=lambda **kwargs: {"title": kwargs["title"]},
        set_custom_field=lambda **kwargs: written.append(kwargs) or {"written": True},
        unknown_tag_names=lambda names: [],
        correspondent_from_text=lambda text: "Mann Gebäudetechnik GmbH",
        resolve_correspondent_name=lambda name: None,
    )
    classifier.source = SimpleNamespace(
        classify=lambda request: ClassificationResult(
            document_type="Rechnung",
            correspondent="Mann Gebäudetechnik GmbH",
            title="unbenannt",
            subject="Heizungswartung",
            document_date="2020-01-13",
            confidence=0.95,
            reason="Vorschlag aus dem Bestand",
        ),
    )

    assert classifier.process_document(document_id=113) == STATUS_AUTO_APPROVED
    assert written == []

    row = classifier.db.get_latest_for_paperless_id(113)
    assert row["due_date"] is None
    assert "Frist" not in (row["reason"] or "")


def test_a_failing_custom_field_write_does_not_fail_the_document(
    tmp_path, monkeypatch
) -> None:
    """Title, correspondent, type and tags are already in Paperless at that
    point; the deadline must not turn an approved document into a failure."""

    import requests

    from types import SimpleNamespace

    from app.classifier import DocumentClassifier
    from app.config import settings
    from app.db import Database
    from app.db import STATUS_AUTO_APPROVED

    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "confidence_threshold", 0.90)
    # Both are the values his worker runs with. A rules-only proposer cannot
    # read an amount, so the invoice evidence check is switched off with it.
    monkeypatch.setattr(settings, "proposal_source", "rules")
    monkeypatch.setattr(settings, "type_evidence_required", "model_only")

    def boom(**kwargs):
        raise requests.RequestException("Paperless nicht erreichbar")

    open_deadline = date.today() + timedelta(days=17)

    classifier = DocumentClassifier.__new__(DocumentClassifier)
    classifier.db = Database(str(tmp_path))
    classifier.paperless = SimpleNamespace(
        download_document=lambda document_id: b"pdf-bytes",
        get_document=lambda document_id: {
            "content": (
                "Mann Gebäudetechnik GmbH\nRechnung\nzahlbar bis "
                + f"{open_deadline:%d.%m.%Y}"
            ),
            "title": "scan0114",
        },
        update_document_metadata_by_names=lambda **kwargs: {"title": kwargs["title"]},
        set_custom_field=boom,
        unknown_tag_names=lambda names: [],
        correspondent_from_text=lambda text: "Mann Gebäudetechnik GmbH",
        resolve_correspondent_name=lambda name: None,
    )
    classifier.source = SimpleNamespace(
        classify=lambda request: ClassificationResult(
            document_type="Rechnung",
            correspondent="Mann Gebäudetechnik GmbH",
            title="unbenannt",
            subject="Heizungswartung",
            document_date="2026-11-03",
            confidence=0.95,
            reason="Vorschlag aus dem Bestand",
        ),
    )

    assert classifier.process_document(document_id=114) == STATUS_AUTO_APPROVED

    row = classifier.db.get_latest_for_paperless_id(114)
    assert row["due_date"] == open_deadline.isoformat()
    assert f"Frist {open_deadline} nicht geschrieben" in row["error_message"]
