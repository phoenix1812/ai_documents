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