from app.classifier import build_document_title
from app.classifier import rebuild_title_from_stored_fields
from app.models import ClassificationResult


def test_model_creation():
    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="Amazon",
        title="Amazon Rechnung",
        tags=["Steuer"],
        confidence=0.9,
    )

    assert result.document_type == "Rechnung"


def test_document_title_keeps_amount_out_of_the_file_name():
    result = ClassificationResult(
        document_type="Rechnung",
        correspondent="Amazon",
        subject="Bueromaterial",
        document_date="2026-05-12",
        amount="84,99 EUR",
    )

    assert build_document_title(result) == "Rechnung_Amazon_Bueromaterial_2026-05-12"


def test_rebuild_uses_stored_fields_after_a_manual_correction():
    title = rebuild_title_from_stored_fields(
        correspondent="BKK EUREGIO",
        document_type="Versicherung",
        subject="Elternzeit Elterngeld",
        document_date="2026-07-23",
        fallback_title="Versicherung_Neu_Vertrag",
    )

    assert title == "Versicherung_BKK_EUREGIO_Elternzeit_Elterngeld_2026-07-23"


def test_rebuild_without_stored_subject_falls_back_to_the_current_title():
    title = rebuild_title_from_stored_fields(
        correspondent="",
        document_type="",
        subject=None,
        document_date=None,
        fallback_title="Rechnung Amazon Buero",
    )

    assert title == "Rechnung_Amazon_Buero"


def test_rebuild_from_legacy_rows_uses_type_and_correspondent():
    title = rebuild_title_from_stored_fields(
        correspondent="ERGO",
        document_type="Versicherung",
        subject="",
        document_date="",
        fallback_title="Versicherung_ERGO_Jaehrliche_Renteninformation",
    )

    assert title == "Versicherung_ERGO"