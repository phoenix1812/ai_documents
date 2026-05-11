"""
Document processing pipeline:
- Paperless ingestion
- OCR text classification via Ollama
- Duplicate detection via SQLite
- Export with structured filenames
- Basic Paperless metadata update
"""

import json
import logging

import requests

from app.config import settings
from app.db import Database
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


logger = logging.getLogger(__name__)


class DocumentClassifier:
    def __init__(self) -> None:
        self.paperless = PaperlessClient()
        self.ollama = OllamaClient()
        self.exporter = Exporter()

        # SQLite inside container volume
        self.db = Database(settings.db_path)

    def process_document(self, document_id: int) -> str:
        """
        Process one Paperless document.

        Deduplication is based on file hash.
        Processing state is persisted in SQLite.
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

            # 5. Confidence gate
            if result.confidence < settings.confidence_threshold:
                logger.warning(
                    "Low confidence for document %s: %s",
                    document_id,
                    result.confidence,
                )
                self.db.insert_document(
                    paperless_id=document_id,
                    file_hash=file_hash,
                    title=result.title,
                    correspondent=result.correspondent,
                    document_type=result.document_type,
                    export_path="",
                    status=STATUS_NEEDS_REVIEW,
                    error_message=(
                        f"Low confidence: {result.confidence}; "
                        f"threshold: {settings.confidence_threshold}"
                    ),
                )

                # Minimal Paperless visibility for manual review.
                self.paperless.update_document(
                    document_id=document_id,
                    payload={
                        "title": f"[Review] {result.title}",
                    },
                )
                return STATUS_NEEDS_REVIEW

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
                with open(target_file, "wb") as f:
                    f.write(file_bytes)
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

            # 8. Store in DB
            self.db.insert_document(
                paperless_id=document_id,
                file_hash=file_hash,
                title=result.title,
                correspondent=result.correspondent,
                document_type=result.document_type,
                export_path=str(target_file),
            )

            # 9. Minimal Paperless metadata update.
            # More advanced metadata updates require mapping names to Paperless IDs.
            self.paperless.update_document(
                document_id=document_id,
                payload={
                    "title": result.title,
                },
            )

            logger.info(
                "Exported: %s",
                target_file,
            )

            return "DONE"

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
