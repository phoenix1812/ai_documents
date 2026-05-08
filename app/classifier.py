"""
Core document classification pipeline.

Coordinates:
- OCR content loading
- Ollama classification
- Paperless metadata updates
- PDF export
"""

import logging

from app.exporter import Exporter
from app.ollama_client import OllamaClient
from app.paperless_client import PaperlessClient


logger = logging.getLogger(__name__)


# Maps LLM labels to Paperless document type IDs
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
    Main document processing pipeline.
    """

    def __init__(self) -> None:
        self.paperless = PaperlessClient()

        self.ollama = OllamaClient()

        self.exporter = Exporter()

    def process_document(
        self,
        document_id: int,
    ) -> None:
        """
        Process a single Paperless document.
        """

        # Load document metadata
        document = self.paperless.get_document(
            document_id
        )

        # OCR text content
        content = document.get(
            "content",
            "",
        )

        if not content:
            logger.warning(
                "Document %s has no OCR content",
                document_id,
            )
            return

        # Run LLM classification
        result = self.ollama.classify(content)

        logger.info(
            "Classification result: %s",
            result,
        )

        # Update Paperless metadata
        payload = {
            "title": result.title,
            "document_type": (
                DOCUMENT_TYPE_MAPPING.get(
                    result.document_type,
                    6,
                )
            ),
        }

        self.paperless.update_document(
            document_id,
            payload,
        )

        # Build export path
        target_filename = self.exporter.build_filename(
            title=result.title,
            tags=result.tags,
        )

        target_file = self.exporter.export_path(
            document_type=result.document_type,
            correspondent=result.correspondent,
            filename=target_filename,
        )

        logger.info(
            "Exporting document to %s",
            target_file,
        )

        # Download PDF from Paperless
        self.paperless.download_document(
            document_id=document_id,
            target_path=str(target_file),
        )

        logger.info(
            "Document %s exported successfully",
            document_id,
        )