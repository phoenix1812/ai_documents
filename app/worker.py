import logging
import time

from app.classifier import DocumentClassifier
from app.config import settings

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self) -> None:
        self.classifier = DocumentClassifier()
        self.processed_documents = set()

    def run(self) -> None:
        logger.info("Worker started")

        while True:
            try:
                documents = (
                    self.classifier.paperless.get_documents()
                )

                for document in documents:
                    document_id = document["id"]

                    if document_id in self.processed_documents:
                        continue

                    logger.info(
                        "Processing document %s",
                        document_id,
                    )

                    self.classifier.process_document(
                        document_id
                    )

                    self.processed_documents.add(
                        document_id
                    )

            except Exception:
                logger.exception(
                    "Worker loop failed"
                )

            time.sleep(settings.poll_interval)