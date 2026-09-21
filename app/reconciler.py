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

BASELINE_META_KEY = "reconcile_baseline_document_id"


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
        if not settings.reconcile_enabled:
            logger.info(
                "Periodic reconciliation disabled via RECONCILE_ENABLED=false. "
                "POST /reconcile still works on demand."
            )
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _baseline_document_id(self, documents: list[dict]) -> int:
        """Highest Paperless ID that reconciliation must not import automatically.

        With RECONCILE_INITIAL_IMPORT=false the existing stock is frozen on the
        first cycle, so a fresh AI database cannot rewrite the whole archive.
        """
        if settings.reconcile_initial_import:
            return 0

        stored = self.db.get_meta(BASELINE_META_KEY)
        if stored is not None:
            return int(stored)

        baseline = max((int(document["id"]) for document in documents), default=0)
        self.db.set_meta(BASELINE_META_KEY, str(baseline))
        logger.warning(
            "RECONCILE_INITIAL_IMPORT=false: freezing automatic import at Paperless ID %s. "
            "Run scripts/reconcile_missing.sh to process existing documents.",
            baseline,
        )
        return baseline

    def reconcile_once(self) -> dict[str, int]:
        documents = self.paperless.get_documents()
        baseline = self._baseline_document_id(documents)
        queued = 0
        already_known = 0
        skipped = 0
        preexisting = 0

        for document in documents:
            document_id = int(document["id"])

            if document_id <= baseline:
                preexisting += 1
                continue

            # Anything the current mode still considers unfinished is requeued:
            # failures for recovery, and DRY_RUN rows once live mode is on.
            if self.db.exists_paperless_id(document_id):
                already_known += 1
                continue

            result = self.processing_queue.enqueue(document_id)
            if result.queued:
                queued += 1
            else:
                skipped += 1

        logger.info(
            "Reconciliation finished: Paperless=%s, queued=%s, known=%s, "
            "skipped=%s, preexisting_ignored=%s.",
            len(documents),
            queued,
            already_known,
            skipped,
            preexisting,
        )
        return {
            "paperless_documents": len(documents),
            "queued": queued,
            "already_known": already_known,
            "skipped": skipped,
            "preexisting_ignored": preexisting,
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
