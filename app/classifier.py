"""Document processing pipeline.

Paperless is the single source of truth for documents and document metadata.
This classifier no longer exports PDF files. Workflow state such as review
requirements is stored only in SQLite for the review UI.
"""

from __future__ import annotations

import json
import logging
import re

import requests

from app.config import settings
from app.db import Database
from app.db import STATUS_AUTO_APPROVED
from app.db import STATUS_DRY_RUN
from app.db import STATUS_FAILED_API
from app.db import STATUS_FAILED_LLM
from app.db import STATUS_FAILED_OCR
from app.db import STATUS_NEEDS_REVIEW
from app.db import STATUS_SKIPPED_DUPLICATE
from app.hash_store import sha256
from app.models import ClassificationResult
from app.ollama_client import OllamaClient
from app.paperless_client import PaperlessClient
from app.validator import validate_classification

logger = logging.getLogger(__name__)


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


def build_ocr_excerpt(content: str, max_length: int = 3000) -> str:
    cleaned = " ".join(content.split())
    return cleaned[:max_length]


def build_paperless_document_url(document_id: int) -> str:
    base_url = getattr(settings, "paperless_public_url", settings.paperless_url).rstrip("/")
    return f"{base_url}/documents/{document_id}/details"


def get_result_confidence(result: ClassificationResult) -> float | None:
    value = getattr(result, "confidence", None)

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_result_reason(result: ClassificationResult) -> str | None:
    value = getattr(result, "reason", None)

    if value is None:
        return None

    return str(value).strip() or None


def sanitize_title_part(value: str | None) -> str:
    """Prepare one title component for Paperless.

    Requirements:
    - no spaces
    - underscores as separators
    - keep common German characters
    - remove characters that are problematic in filenames and Paperless titles
    """

    if value is None:
        return ""

    value = str(value).strip()
    value = value.replace("€", "EUR")
    value = value.replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9_\-().,äöüÄÖÜß]", "", value)
    value = re.sub(r"_+", "_", value)

    return value.strip("_")


def build_document_title(result: ClassificationResult) -> str:
    """Build a deterministic Paperless title from structured fields.

    The LLM may provide a title, but the final Paperless title is generated
    here to keep names consistent and to avoid generic values such as
    "Rechnung".
    """

    parts: list[str] = []

    if result.document_type:
        parts.append(result.document_type)

    if result.correspondent:
        parts.append(result.correspondent)

    if result.subject:
        parts.append(result.subject)

    if result.document_date:
        parts.append(result.document_date)

    # Add the most useful identifier, but avoid overly long titles.
    if result.invoice_number:
        parts.append(result.invoice_number)
    elif result.contract_number:
        parts.append(result.contract_number)
    elif result.customer_number:
        parts.append(result.customer_number)

    if result.amount:
        parts.append(result.amount)

    cleaned_parts = []
    seen = set()

    for part in parts:
        cleaned = sanitize_title_part(part)
        key = cleaned.lower()

        if cleaned and key not in seen:
            cleaned_parts.append(cleaned)
            seen.add(key)

    title = "_".join(cleaned_parts)
    title = re.sub(r"_+", "_", title).strip("_")

    if not title:
        title = sanitize_title_part(result.title) or "Unbenanntes_Dokument"

    return title[:120]


def clean_paperless_tags(tags: list[str] | None) -> list[str]:
    """Remove workflow tags before writing tags to Paperless."""

    cleaned_tags: list[str] = []
    seen: set[str] = set()

    for tag in tags or []:
        clean_tag = str(tag).strip()

        if not clean_tag:
            continue

        normalized = clean_tag.lower().replace(" ", "_")

        if normalized in TECHNICAL_WORKFLOW_TAGS:
            continue

        if normalized in seen:
            continue

        cleaned_tags.append(clean_tag)
        seen.add(normalized)

    return cleaned_tags


class DocumentClassifier:
    def __init__(self) -> None:
        self.paperless = PaperlessClient()
        self.ollama = OllamaClient()
        self.db = Database(settings.db_path)

    def _store_review(
        self,
        document_id: int,
        file_hash: str,
        title: str,
        correspondent: str,
        document_type: str,
        tags: list[str],
        reasons: list[str],
        confidence: float | None,
        reason: str | None,
        original_title: str | None,
        ocr_excerpt: str | None,
        paperless_url: str | None,
    ) -> str:
        """Store review state in SQLite only.

        No review tag and no [Review] prefix is written to Paperless.
        """

        self.db.insert_document(
            paperless_id=document_id,
            file_hash=file_hash,
            title=title,
            correspondent=correspondent,
            document_type=document_type,
            tags=tags,
            confidence=confidence,
            reason=reason,
            original_title=original_title,
            ocr_excerpt=ocr_excerpt,
            paperless_url=paperless_url,
            export_path="",
            status=STATUS_NEEDS_REVIEW,
            error_message=", ".join(reasons),
        )

        return STATUS_NEEDS_REVIEW

    def process_document(self, document_id: int) -> str:
        file_hash = ""

        try:
            file_bytes = self.paperless.download_document(document_id=document_id)
            file_hash = sha256(file_bytes)

            if self.db.exists_hash(file_hash):
                logger.info("Duplicate skipped by hash: %s", document_id)

                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=f"{file_hash}-{document_id}-duplicate",
                    title="",
                    correspondent="",
                    document_type="",
                    tags=[],
                    confidence=None,
                    reason="duplicate",
                    original_title=None,
                    ocr_excerpt=None,
                    paperless_url=build_paperless_document_url(document_id),
                    export_path="",
                    status=STATUS_SKIPPED_DUPLICATE,
                    error_message=f"Duplicate hash: {file_hash}",
                )

                return STATUS_SKIPPED_DUPLICATE

            document = self.paperless.get_document(document_id)
            content = document.get("content", "")
            original_title = document.get("title") or ""
            paperless_url = build_paperless_document_url(document_id)
            ocr_excerpt = build_ocr_excerpt(content)

            if not content:
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title="",
                    correspondent="",
                    document_type="",
                    tags=[],
                    confidence=None,
                    reason=None,
                    original_title=original_title,
                    ocr_excerpt="",
                    paperless_url=paperless_url,
                    export_path="",
                    status=STATUS_FAILED_OCR,
                    error_message="No OCR content",
                )

                return STATUS_FAILED_OCR

            try:
                result = self.ollama.classify(content)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title="",
                    correspondent="",
                    document_type="",
                    tags=[],
                    confidence=None,
                    reason=None,
                    original_title=original_title,
                    ocr_excerpt=ocr_excerpt,
                    paperless_url=paperless_url,
                    export_path="",
                    status=STATUS_FAILED_LLM,
                    error_message=str(exc),
                )

                return STATUS_FAILED_LLM

            result.tags = clean_paperless_tags(result.tags)
            result.title = build_document_title(result)

            confidence = get_result_confidence(result)
            reason = get_result_reason(result)

            validation = validate_classification(result)

            if not validation.valid:
                return self._store_review(
                    document_id=document_id,
                    file_hash=file_hash,
                    title=result.title,
                    correspondent=result.correspondent,
                    document_type=result.document_type,
                    tags=result.tags,
                    reasons=validation.reasons,
                    confidence=confidence,
                    reason=reason,
                    original_title=original_title,
                    ocr_excerpt=ocr_excerpt,
                    paperless_url=paperless_url,
                )

            if settings.dry_run:
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title=result.title,
                    correspondent=result.correspondent,
                    document_type=result.document_type,
                    tags=result.tags,
                    confidence=confidence,
                    reason=reason,
                    original_title=original_title,
                    ocr_excerpt=ocr_excerpt,
                    paperless_url=paperless_url,
                    export_path="",
                    status=STATUS_DRY_RUN,
                    error_message="Dry run: Paperless metadata was not updated.",
                )

                return STATUS_DRY_RUN

            applied_payload = self.paperless.update_document_metadata_by_names(
                document_id=document_id,
                title=result.title,
                correspondent=result.correspondent,
                document_type=result.document_type,
                tags=result.tags,
            )

            self.db.insert_document(
                paperless_id=document_id,
                file_hash=file_hash,
                title=result.title,
                correspondent=result.correspondent,
                document_type=result.document_type,
                tags=result.tags,
                confidence=confidence,
                reason=reason,
                original_title=original_title,
                ocr_excerpt=ocr_excerpt,
                paperless_url=paperless_url,
                export_path="",
                status=STATUS_AUTO_APPROVED,
                error_message=f"Auto-approved and applied to Paperless: {applied_payload}",
            )

            return STATUS_AUTO_APPROVED

        except requests.RequestException as exc:
            self.db.mark_failed(
                paperless_id=document_id,
                error_message=str(exc),
                status=STATUS_FAILED_API,
            )
            raise

        except Exception as exc:
            self.db.mark_failed(
                paperless_id=document_id,
                error_message=str(exc),
            )
            raise
