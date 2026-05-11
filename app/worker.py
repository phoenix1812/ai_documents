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

    def is_paperless_available(self) -> bool:
        try:
            response = requests.get(
                settings.paperless_healthcheck_url,
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def wait_for_paperless(self) -> None:
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
                    "Found %s documents.",
                    len(documents),
                )

                for document in documents:
                    document_id = document["id"]

                    if self.classifier.db.exists_paperless_id(document_id):
                        logger.debug(
                            "Document %s already processed. Skipping.",
                            document_id,
                        )
                        continue

                    logger.info(
                        "Processing document %s.",
                        document_id,
                    )

                    try:
                        status = self.classifier.process_document(
                            document_id
                        )

                        logger.info(
                            "Document %s finished with status %s.",
                            document_id,
                            status,
                        )

                    except Exception:
                        logger.exception(
                            "Failed processing document %s.",
                            document_id,
                        )

            except Exception:
                logger.exception(
                    "Worker loop failed"
                )

                # Prevent hot-looping
                time.sleep(10)

            time.sleep(settings.poll_interval)
