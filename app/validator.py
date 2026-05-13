"""
Validation layer for LLM classification results.

The classifier should only apply Paperless metadata automatically when the LLM
result is sufficiently specific and trustworthy. Placeholder values such as
"Unbekannt", "Unbenannt" or "Sonstiges" are routed to the review UI.
"""

from dataclasses import dataclass

from app.config import settings
from app.models import ClassificationResult

ALLOWED_DOCUMENT_TYPES = {
    "Rechnung",
    "Vertrag",
    "Versicherung",
    "Steuer",
    "Bank",
    "Sonstiges",
}

INVALID_PLACEHOLDER_VALUES = {
    "",
    "unbekannt",
    "unbekannte",
    "unbekannter",
    "unbenannt",
    "unbenanntes dokument",
    "unbenanntes_dokument",
    "sonstiges",
    "sonstige",
    "dokument",
    "scan",
    "pdf",
    "unknown",
    "untitled",
    "other",
}

GENERIC_TITLES = {
    "rechnung",
    "brief",
    "vertrag",
    "dokument",
    "versicherung",
    "kontoauszug",
    "bank",
    "steuer",
    "sonstiges",
}

TECHNICAL_WORKFLOW_TAGS = {
    "review",
    "ai-review",
    "ai_review",
    "needs-review",
    "needs_review",
    "needs-ai-review",
    "needs_ai_review",
    "duplicate",
    "manual",
    "manuell",
}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: list[str]

    @property
    def reason_text(self) -> str:
        return ", ".join(self.reasons)


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _is_placeholder(value: str | None) -> bool:
    normalized = _normalize(value)
    return normalized in INVALID_PLACEHOLDER_VALUES


def _is_generic_title(value: str | None) -> bool:
    normalized = _normalize(value).replace("_", " ")
    return normalized in GENERIC_TITLES


def validate_classification(result: ClassificationResult) -> ValidationResult:
    """
    Validate whether a classification result is safe for automatic processing.

    Documents are sent to review when:
    - confidence is below CONFIDENCE_THRESHOLD
    - title/correspondent/document_type contain placeholder values
    - title is too short or generic
    - document_type is outside the expected taxonomy
    - technical workflow tags would be written to Paperless
    """

    reasons: list[str] = []

    if result.confidence < settings.confidence_threshold:
        reasons.append("low_confidence")

    if result.document_type not in ALLOWED_DOCUMENT_TYPES:
        reasons.append("unknown_document_type")

    if _is_placeholder(result.document_type):
        reasons.append("placeholder_document_type")

    if _is_placeholder(result.correspondent):
        reasons.append("placeholder_correspondent")

    if _is_placeholder(result.title):
        reasons.append("placeholder_title")

    if _is_generic_title(result.title):
        reasons.append("generic_title")

    if len((result.title or "").strip()) < settings.min_title_length:
        reasons.append("title_too_short")

    technical_tags = [
        tag
        for tag in result.tags
        if _normalize(tag).replace(" ", "_") in TECHNICAL_WORKFLOW_TAGS
    ]
    if technical_tags:
        reasons.append("technical_workflow_tag")

    return ValidationResult(
        valid=len(reasons) == 0,
        reasons=reasons,
    )
