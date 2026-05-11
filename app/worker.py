"""
Main worker loop.

Continuously polls Paperless for new documents
and processes unhandled entries.
"""

import logging
import time
import requests

from app.classifier import DocumentClassifier
from app.config import settings


logger = logging.getLogger(__name__)


class Worker:
    """
    Background worker process.
    """

    def __init__(self) -> None:
        self.classifier = DocumentClassifier()



        self.processed_documents = set()

    def is_paperless_available(self):
        try:
            response = requests.get(
                "http://paperless:8000",
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def wait_for_paperless(self):
        while not self.is_paperless_available():
            logger.info(
                "Paperless ist nicht verfügbar. Warte..."
            )

            time.sleep(5)

    def run(self) -> None:
        """
        Start infinite processing loop.
        """

        logger.info("Worker started")

        # Wait for dependencies
        self.wait_for_paperless()

        while True:
            try:
                documents = self.classifier.paperless.get_documents()

                logger.info(
                    f"Found {len(documents)} documents."
                )

                for document in documents:
                    document_id = document["id"]

                    if document_id in self.processed_documents:
                        continue

                    logger.info(
                        f"Processing document {document_id}."
                    )

                    try:
                        self.classifier.process_document(
                            document_id
                        )

                        self.processed_documents.add(
                            document_id
                        )

                        logger.info(
                            f"Document {document_id} processed."
                        )

                    except Exception:
                        logger.exception(
                            f"Failed processing document {document_id}."
                        )

            except Exception:
                logger.exception(
                    "Worker loop failed"
                )

                # Prevent hot-looping
                time.sleep(10)

            time.sleep(settings.poll_interval)
