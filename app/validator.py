"""
Validation layer for LLM classification results.

The classifier should only export documents automatically when the
LLM result is sufficiently specific and trustworthy. Placeholder values
such as "Unbekannt", "Unbenannt" or "Sonstiges" are routed to review.
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
    "sonstiges",
    "sonstige",
    "dokument",
    "scan",
    "pdf",
    "unknown",
    "untitled",
    "other",
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


def validate_classification(
    result: ClassificationResult,
) -> ValidationResult:
    """
    Validate whether a classification result is safe for automatic export.

    Documents are sent to review when:
    - confidence is below CONFIDENCE_THRESHOLD
    - title/correspondent/document_type contain placeholder values
    - title is too short to be useful
    - document_type is outside the expected taxonomy
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

    if len((result.title or "").strip()) < settings.min_title_length:
        reasons.append("title_too_short")

    return ValidationResult(
        valid=len(reasons) == 0,
        reasons=reasons,
    )
