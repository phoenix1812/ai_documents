"""
Document processing pipeline.
"""

import json
import logging

import requests

from app.config import settings
from app.db import Database
from app.db import STATUS_AUTO_APPROVED
from app.db import STATUS_DRY_RUN
from app.db import STATUS_FAILED_API
from app.db import STATUS_FAILED_EXPORT
from app.db import STATUS_FAILED_LLM
from app.db import STATUS_FAILED_OCR
from app.db import STATUS_NEEDS_REVIEW
from app.db import STATUS_SKIPPED_DUPLICATE
from app.exporter import Exporter
from app.hash_store import sha256
from app.ollama_client import OllamaClient
from app.paperless_client import PaperlessClient
from app.validator import validate_classification


logger = logging.getLogger(__name__)


def build_ocr_excerpt(content: str, max_length: int = 3000) -> str:
    cleaned = " ".join(content.split())
    return cleaned[:max_length]


def build_paperless_document_url(document_id: int) -> str:
    base_url = getattr(settings, "paperless_public_url", settings.paperless_url).rstrip("/")
    return f"{base_url}/documents/{document_id}/details"


def get_result_confidence(result) -> float | None:
    value = getattr(result, "confidence", None)
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_result_reason(result) -> str | None:
    value = getattr(result, "reason", None)
    if value is None:
        return None

    return str(value).strip() or None


class DocumentClassifier:
    def __init__(self) -> None:
        self.paperless = PaperlessClient()
        self.ollama = OllamaClient()
        self.exporter = Exporter()
        self.db = Database(settings.db_path)

    def _write_bytes(self, target_file, file_bytes: bytes) -> None:
        with open(target_file, "wb") as f:
            f.write(file_bytes)

    def _send_to_review(
        self,
        document_id: int,
        file_hash: str,
        file_bytes: bytes,
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
        filename = self.exporter.build_review_filename(
            document_id=document_id,
            file_hash=file_hash,
            reasons=reasons,
        )
        target_file = self.exporter.review_export_path(filename)
        target_file = self.exporter.unique_path(target_file)

        try:
            self._write_bytes(target_file, file_bytes)
        except OSError as exc:
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
                export_path=str(target_file),
                status=STATUS_FAILED_EXPORT,
                error_message=str(exc),
            )
            return STATUS_FAILED_EXPORT

        reason_text = ", ".join(reasons)

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
            export_path=str(target_file),
            status=STATUS_NEEDS_REVIEW,
            error_message=reason_text,
        )

        try:
            self.paperless.update_document(
                document_id=document_id,
                payload={"title": f"[Review] {title or 'Unklassifiziertes Dokument'}"},
            )
        except requests.RequestException:
            logger.exception(
                "Paperless review metadata update failed for document %s.",
                document_id,
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

            confidence = get_result_confidence(result)
            reason = get_result_reason(result)
            validation = validate_classification(result)

            if not validation.valid:
                return self._send_to_review(
                    document_id=document_id,
                    file_hash=file_hash,
                    file_bytes=file_bytes,
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

            filename = self.exporter.build_filename(
                title=result.title,
                tags=result.tags,
            )
            target_file = self.exporter.export_path(
                document_type=result.document_type,
                correspondent=result.correspondent,
                filename=filename,
            )
            target_file = self.exporter.unique_path(target_file)

            try:
                self._write_bytes(target_file, file_bytes)
            except OSError as exc:
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
                    export_path=str(target_file),
                    status=STATUS_FAILED_EXPORT,
                    error_message=str(exc),
                )
                return STATUS_FAILED_EXPORT

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
                    export_path=str(target_file),
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
                export_path=str(target_file),
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
