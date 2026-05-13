"""
Document processing pipeline:

- Paperless ingestion
- OCR text classification via Ollama
- validation of LLM output
- duplicate detection via SQLite
- final export or review export
- optional Paperless metadata update
"""

import json
import logging

import requests

from app.config import settings
from app.db import Database
from app.db import STATUS_DONE
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


class DocumentClassifier:
    """Coordinates download, classification, export and Paperless updates."""

    def __init__(self) -> None:
        self.paperless = PaperlessClient()
        self.ollama = OllamaClient()
        self.exporter = Exporter()
        # SQLite inside container volume
        self.db = Database(settings.db_path)

    def _write_bytes(
        self,
        target_file,
        file_bytes: bytes,
    ) -> None:
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
        reasons: list[str],
    ) -> str:
        """Export document to _REVIEW and persist NEEDS_REVIEW state."""
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
            export_path=str(target_file),
            status=STATUS_NEEDS_REVIEW,
            error_message=reason_text,
        )

        if settings.dry_run:
            logger.info(
                "Dry run enabled. Skipped Paperless review metadata update "
                "for document %s.",
                document_id,
            )
            return STATUS_NEEDS_REVIEW

        try:
            self.paperless.update_document(
                document_id=document_id,
                payload={
                    "title": f"[Review] {title or 'Unklassifiziertes Dokument'}",
                },
            )
        except requests.RequestException:
            logger.exception(
                "Paperless review metadata update failed for document %s.",
                document_id,
            )

        logger.warning(
            "Document %s moved to review: %s -> %s",
            document_id,
            reason_text,
            target_file,
        )
        return STATUS_NEEDS_REVIEW

    def process_document(self, document_id: int) -> str:
        """Process one Paperless document.

        Deduplication is based on file hash. Processing state is persisted in
        SQLite. Documents with unsafe classification results are sent to
        _REVIEW. In dry-run mode, valid classifications are exported and stored,
        but Paperless metadata is not changed.
        """
        file_hash = ""

        try:
            # 1. Download PDF
            file_bytes = self.paperless.download_document(
                document_id=document_id,
            )
            file_hash = sha256(file_bytes)

            # 2. Duplicate check by file hash
            if self.db.exists_hash(file_hash):
                logger.info(
                    "Duplicate skipped by hash: %s",
                    document_id,
                )
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=f"{file_hash}-{document_id}-duplicate",
                    title="",
                    correspondent="",
                    document_type="",
                    export_path="",
                    status=STATUS_SKIPPED_DUPLICATE,
                    error_message=f"Duplicate hash: {file_hash}",
                )
                return STATUS_SKIPPED_DUPLICATE

            # 3. Get OCR content
            document = self.paperless.get_document(document_id)
            content = document.get("content", "")
            if not content:
                logger.warning(
                    "No OCR content: %s",
                    document_id,
                )
                # No OCR can not be classified safely. Keep this as OCR failure,
                # not review, because manual review can not fix missing OCR
                # metadata.
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title="",
                    correspondent="",
                    document_type="",
                    export_path="",
                    status=STATUS_FAILED_OCR,
                    error_message="No OCR content",
                )
                return STATUS_FAILED_OCR

            # 4. LLM classification
            try:
                result = self.ollama.classify(content)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title="",
                    correspondent="",
                    document_type="",
                    export_path="",
                    status=STATUS_FAILED_LLM,
                    error_message=str(exc),
                )
                return STATUS_FAILED_LLM

            # 5. Validate classification before final export
            validation = validate_classification(result)
            if not validation.valid:
                return self._send_to_review(
                    document_id=document_id,
                    file_hash=file_hash,
                    file_bytes=file_bytes,
                    title=result.title,
                    correspondent=result.correspondent,
                    document_type=result.document_type,
                    reasons=validation.reasons,
                )

            # 6. Build safe filename and final export path
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

            # 7. Write file
            try:
                self._write_bytes(target_file, file_bytes)
            except OSError as exc:
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title=result.title,
                    correspondent=result.correspondent,
                    document_type=result.document_type,
                    export_path=str(target_file),
                    status=STATUS_FAILED_EXPORT,
                    error_message=str(exc),
                )
                return STATUS_FAILED_EXPORT

            # 8. Dry-run mode: export and store result, but do not update
            # Paperless metadata.
            if settings.dry_run:
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title=result.title,
                    correspondent=result.correspondent,
                    document_type=result.document_type,
                    export_path=str(target_file),
                    status=STATUS_DRY_RUN,
                    error_message="Dry run: Paperless metadata was not updated.",
                )
                logger.info(
                    "[DRY RUN] Would update document %s with: "
                    "title=%s, type=%s, correspondent=%s",
                    document_id,
                    result.title,
                    result.document_type,
                    result.correspondent,
                )
                return STATUS_DRY_RUN

            # 9. Minimal Paperless metadata update.
            # More advanced metadata updates require mapping names to Paperless IDs.
            self.paperless.update_document(
                document_id=document_id,
                payload={
                    "title": result.title,
                },
            )

            # 10. Store in DB only after Paperless update succeeded.
            self.db.insert_document(
                paperless_id=document_id,
                file_hash=file_hash,
                title=result.title,
                correspondent=result.correspondent,
                document_type=result.document_type,
                export_path=str(target_file),
                status=STATUS_DONE,
            )

            logger.info(
                "Exported: %s",
                target_file,
            )
            return STATUS_DONE

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
