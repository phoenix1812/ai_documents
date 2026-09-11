"""Periodic reconciliation between Paperless and the AI processing database."""

from __future__ import annotations

import logging
import threading
import time

from app.config import settings
from app.db import Database
from app.paperless_client import PaperlessClient
from app.document_queue import DocumentProcessingQueue

logger = logging.getLogger(__name__)


class Reconciler:
    def __init__(self, processing_queue: DocumentProcessingQueue) -> None:
        self.processing_queue = processing_queue
        self.paperless = PaperlessClient()
        self.db = Database(settings.db_path)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="paperless-reconciler",
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def reconcile_once(self) -> dict[str, int]:
        documents = self.paperless.get_documents()
        queued = 0
        already_known = 0
        skipped = 0

        for document in documents:
            document_id = int(document["id"])

            # FINAL_STATUSES includes approved, review, dry-run and ignored
            # states. Failed documents are intentionally eligible for recovery.
            if self.db.exists_paperless_id(document_id):
                already_known += 1
                continue

            result = self.processing_queue.enqueue(document_id)
            if result.queued:
                queued += 1
            else:
                skipped += 1

        logger.info(
            "Reconciliation finished: Paperless=%s, queued=%s, known=%s, skipped=%s.",
            len(documents),
            queued,
            already_known,
            skipped,
        )
        return {
            "paperless_documents": len(documents),
            "queued": queued,
            "already_known": already_known,
            "skipped": skipped,
        }

    def _run(self) -> None:
        # Give Paperless a little time during container startup.
        time.sleep(max(0, settings.reconciliation_start_delay_seconds))

        while not self._stop.is_set():
            try:
                self.reconcile_once()
            except Exception:
                logger.exception("Paperless reconciliation failed.")

            self._stop.wait(max(30, settings.reconciliation_interval_seconds))
