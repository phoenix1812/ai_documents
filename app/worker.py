"""Event-driven document worker with Paperless dependency handling."""
from __future__ import annotations
import logging
import time
import requests
from app.classifier import DocumentClassifier
from app.config import settings

logger = logging.getLogger(__name__)

class Worker:
    def __init__(self) -> None:
        self.classifier = DocumentClassifier()

    def is_paperless_available(self) -> bool:
        try:
            response = requests.get(settings.paperless_healthcheck_url, timeout=10)
            return response.status_code < 500
        except requests.RequestException:
            return False

    def wait_for_paperless(self) -> None:
        while not self.is_paperless_available():
            logger.info("Paperless ist nicht verfügbar. Warte...")
            time.sleep(5)

    def process_once(self, document_id: int) -> str:
        self.wait_for_paperless()
        if self.classifier.db.exists_paperless_id(document_id):
            logger.info("Document %s already reached a final state. Skipping.", document_id)
            return "ALREADY_PROCESSED"
        logger.info("Processing document %s.", document_id)
        result = self.classifier.process_document(document_id=document_id)
        logger.info("Document %s finished with status %s.", document_id, result)
        return result
