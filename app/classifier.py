"""
Document processing pipeline:
- Paperless ingestion
- OCR text classification via Ollama
- Duplicate detection via SQLite
- Export with structured filenames
"""

import logging

from app.config import settings
from app.exporter import Exporter
from app.db import Database
from app.ollama_client import OllamaClient
from app.paperless_client import PaperlessClient
from app.hash_store import sha256


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

        Deduplication is based on file hash, not paperless_id.
        """

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
                return "SKIPPED_DUPLICATE"

            # 3. Get OCR content
            document = self.paperless.get_document(document_id)
            content = document.get("content", "")

            if not content:
                logger.warning(
                    "No OCR content: %s",
                    document_id,
                )
                raise ValueError("No OCR content")

            # 4. LLM classification
            result = self.ollama.classify(content)

            # 5. Build filename
            filename = self.exporter.build_filename(
                title=result.title,
                tags=result.tags,
            )

            target_file = self.exporter.export_path(
                document_type=result.document_type,
                correspondent=result.correspondent,
                filename=filename,
            )

            # 6. Write file
            with open(target_file, "wb") as f:
                f.write(file_bytes)

            # 7. Store in DB
            self.db.insert_document(
                paperless_id=document_id,
                file_hash=file_hash,
                title=result.title,
                correspondent=result.correspondent,
                document_type=result.document_type,
                export_path=str(target_file),
            )

            logger.info(
                "Exported: %s",
                target_file,
            )

            return "DONE"

        except Exception as exc:
            self.db.mark_failed(
                paperless_id=document_id,
                error_message=str(exc),
            )
            raise