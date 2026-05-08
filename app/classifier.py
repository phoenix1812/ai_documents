import logging

from app.exporter import Exporter
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
    def __init__(self) -> None:
        self.paperless = PaperlessClient()

        self.ollama = OllamaClient()

        self.exporter = Exporter()

    def process_document(
        self,
        document_id: int,
    ) -> None:
        document = self.paperless.get_document(
            document_id
        )

        content = document.get("content", "")

        if not content:
            logger.warning(
                "Document %s has no OCR content",
                document_id,
            )
            return

        result = self.ollama.classify(content)

        logger.info(
            "Classification result: %s",
            result,
        )

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

        target_file = (
            self.exporter.export_path(
                document_type=result.document_type,
                correspondent=result.correspondent,
                filename=(
                    f"{result.title}.pdf"
                ),
            )
        )

        logger.info(
            "Exporting document to %s",
            target_file,
        )

        self.paperless.download_document(
            document_id=document_id,
            target_path=str(target_file),
        )

        logger.info(
            "Document %s exported successfully",
            document_id,
        )