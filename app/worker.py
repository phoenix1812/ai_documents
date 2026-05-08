"""
Main worker loop.

Continuously polls Paperless for new documents
and processes unhandled entries.
"""

import logging
import time

from app.classifier import DocumentClassifier
from app.config import settings


logger = logging.getLogger(__name__)


class Worker:
    """
    Background worker process.
    """

    def __init__(self) -> None:
        self.classifier = DocumentClassifier()

        # In-memory tracking
        # Will be replaced by SQLite in Phase 2
        self.processed_documents = set()

    def run(self) -> None:
        """
        Start infinite processing loop.
        """

        logger.info("Worker started")

        while True:
            try:
                # Load all documents
                documents = (
                    self.classifier
                    .paperless
                    .get_documents()
                )

                for document in documents:
                    document_id = document["id"]

                    # Skip already processed docs
                    if (
                        document_id
                        in self.processed_documents
                    ):
                        continue

                    logger.info(
                        "Processing document %s",
                        document_id,
                    )

                    # Execute classification pipeline
                    self.classifier.process_document(
                        document_id
                    )

                    # Mark as processed
                    self.processed_documents.add(
                        document_id
                    )

            except Exception:
                logger.exception(
                    "Worker loop failed"
                )

            # Poll interval
            time.sleep(
                settings.poll_interval
            )