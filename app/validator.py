"""Validation layer for LLM classification results.

The classifier should only apply Paperless metadata automatically when the LLM
result is sufficiently specific and trustworthy. Weak, generic or incomplete
results are routed to the review UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings
from app.models import ClassificationResult


ALLOWED_DOCUMENT_TYPES = {
    "Rechnung",
    "Vertrag",
    "Versicherung",
    "Steuer",
    "Bank",
    "Gehalt",
    "Gesundheit",
    "Energie",
    "Brief",
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
    "null",
    "none",
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
    "gehalt",
    "gesundheit",
    "energie",
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

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AMOUNT_RE = re.compile(r"\d+[,.]?\d*\s?(EUR|€|Euro)?", re.IGNORECASE)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: list[str]

    @property
    def reason_text(self) -> str:
        return ", ".join(self.reasons)


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_title(value: str | None) -> str:
    return _normalize(value).replace("_", " ")


def _is_placeholder(value: str | None) -> bool:
    normalized = _normalize(value)
    return normalized in INVALID_PLACEHOLDER_VALUES


def _is_generic_title(value: str | None) -> bool:
    normalized = _normalize_title(value)
    return normalized in GENERIC_TITLES


def _valid_iso_date(value: str | None) -> bool:
    if value is None:
        return True

    return bool(DATE_RE.match(value.strip()))


def _valid_amount(value: str | None) -> bool:
    if value is None:
        return True

    return bool(AMOUNT_RE.search(value.strip()))


def _has_any_identifier(result: ClassificationResult) -> bool:
    return any(
        [
            result.invoice_number,
            result.customer_number,
            result.contract_number,
            result.document_date,
            result.amount,
            result.service_period,
        ]
    )


def validate_classification(result: ClassificationResult) -> ValidationResult:
    """Validate whether a classification result is safe for automatic processing.

    Documents are sent to review when:
    - confidence is below CONFIDENCE_THRESHOLD
    - required values are placeholders
    - generated title is too short or generic
    - document_type is outside the taxonomy
    - technical workflow tags would be written to Paperless
    - type-specific evidence is missing
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

    if result.document_date and not _valid_iso_date(result.document_date):
        reasons.append("invalid_document_date")

    if result.due_date and not _valid_iso_date(result.due_date):
        reasons.append("invalid_due_date")

    if result.amount and not _valid_amount(result.amount):
        reasons.append("invalid_amount")

    technical_tags = [
        tag
        for tag in result.tags
        if _normalize(tag).replace(" ", "_") in TECHNICAL_WORKFLOW_TAGS
    ]

    if technical_tags:
        reasons.append("technical_workflow_tag")

    # Type-specific checks. These do not try to be perfect; they only prevent
    # obviously weak automatic metadata writes.
    if result.document_type == "Rechnung":
        if not result.amount:
            reasons.append("missing_amount_for_invoice")
        if not result.document_date:
            reasons.append("missing_date_for_invoice")
        if not result.invoice_number and result.confidence < 0.9:
            reasons.append("missing_invoice_number")

    if result.document_type in {"Vertrag", "Versicherung"}:
        if not result.subject:
            reasons.append("missing_subject")
        if not result.contract_number and not result.customer_number and result.confidence < 0.9:
            reasons.append("missing_contract_or_customer_number")

    if result.document_type in {"Bank", "Gehalt"}:
        if not result.document_date and not result.service_period:
            reasons.append("missing_date_or_period")

    if result.document_type == "Sonstiges" and not _has_any_identifier(result):
        reasons.append("weak_sonstiges_classification")

    return ValidationResult(
        valid=len(reasons) == 0,
        reasons=reasons,
    )
