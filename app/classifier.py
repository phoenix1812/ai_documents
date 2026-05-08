"""
Core document processing pipeline.

This module:
- loads documents from Paperless
- extracts OCR text
- sends content to Ollama for classification
- updates Paperless metadata
- exports PDF files
- prevents duplicate exports via hashing
"""

import logging

from app.config import settings
from app.exporter import Exporter
from app.hash_store import HashStore, sha256
from app.ollama_client import OllamaClient
from app.paperless_client import PaperlessClient


logger = logging.getLogger(__name__)


DOCUMENT_TYPE_MAPPING = {
    "Rechnung": 1,
    "Vertrag": 2,
    "Versicherung": 3,
    "Steuer": 4,
    "Bank": 5,
    "Sonstiges": 6,
}


class DocumentClassifier:
    """
    End-to-end document processing pipeline.
    """

    def __init__(self) -> None:
        self.paperless = PaperlessClient()
        self.ollama = OllamaClient()
        self.exporter = Exporter()

        # Persistent duplicate detection store
        self.hash_store = HashStore(
            settings.export_path
        )

    def process_document(self, document_id: int) -> None:
        """
        Fully safe processing pipeline:
        - download first
        - hash check BEFORE LLM
        - classify only if needed
        - never overwrite files
        """

        # ----------------------------
        # Load metadata (optional)
        # ----------------------------
        document = self.paperless.get_document(document_id)

        # ----------------------------
        # Download file FIRST
        # ----------------------------
        file_bytes = self.paperless.download_document(
            document_id=document_id,
        )

        # ----------------------------
        # Duplicate detection EARLY
        # ----------------------------
        file_hash = sha256(file_bytes)

        if self.hash_store.exists(file_hash):
            logger.info(
                "Duplicate skipped BEFORE LLM: %s",
                document_id,
            )
            return

        # ----------------------------
        # OCR content (only now)
        # ----------------------------
        content = document.get("content", "")

        if not content:
            logger.warning(
                "Document %s has no OCR content",
                document_id,
            )
            return

        # ----------------------------
        # LLM classification (ONLY IF NEW)
        # ----------------------------
        result = self.ollama.classify(content)

        logger.info(
            "Classification result: %s",
            result,
        )

        # ----------------------------
        # Build filename
        # ----------------------------
        base_filename = self.exporter.build_filename(
            title=result.title,
            tags=result.tags,
        )

        # 🔥 IMPORTANT: prevent overwrite collisions
        unique_filename = (
            f"{file_hash[:10]}_{base_filename}"
        )

        # ----------------------------
        # Export path
        # ----------------------------
        target_file = self.exporter.export_path(
            document_type=result.document_type,
            correspondent=result.correspondent,
            filename=unique_filename,
        )

        # ----------------------------
        # Write file (NEVER overwrite same hash exists)
        # ----------------------------
        with open(target_file, "wb") as f:
            f.write(file_bytes)

        # ----------------------------
        # Store hash AFTER success
        # ----------------------------
        self.hash_store.add(
            file_hash,
            str(target_file),
        )

        logger.info(
            "Exported: %s",
            target_file,
        )

        # ----------------------------
        # Update Paperless metadata
        # ----------------------------
        payload = {
            "title": result.title,
            "document_type": DOCUMENT_TYPE_MAPPING.get(
                result.document_type,
                6,
            ),
        }

        self.paperless.update_document(
            document_id,
            payload,
        )