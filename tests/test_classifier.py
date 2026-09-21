from app.classifier import build_document_title
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