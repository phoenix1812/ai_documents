"""Periodic Paperless-to-AI queue reconciliation.

The first reconciliation establishes a baseline and intentionally does not import
existing Paperless documents unless RECONCILE_INITIAL_IMPORT=true.
"""
from __future__ import annotations
from datetime import datetime, timezone
import logging
import threading
from app.config import settings
from app.paperless_client import PaperlessClient
from app.queue_store import QueueStore

logger = logging.getLogger(__name__)
BASELINE_KEY = "reconcile_baseline_at"

class Reconciler:
    def __init__(self, queue_store: QueueStore) -> None:
        self.queue_store = queue_store
        self.paperless = PaperlessClient()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="paperless-reconciler")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def reconcile(self, include_existing: bool = False) -> dict:
        baseline = self.queue_store.get_meta(BASELINE_KEY)
        if baseline is None and not include_existing and not settings.reconcile_initial_import:
            now = self._now()
            self.queue_store.set_meta(BASELINE_KEY, now)
            logger.info("Reconciliation baseline initialized at %s; existing documents are not imported.", now)
            return {"queued": 0, "baseline_initialized": True, "initial_import": False}

        params = None if (include_existing or settings.reconcile_initial_import) else {"created__gte": baseline}
        documents = self.paperless._get_paginated("/api/documents/", params=params)
        known_ids = set()
        # Only IDs already represented by a completed/terminal processing record are considered known.
        rows = self.queue_store.db.conn.execute("SELECT paperless_id FROM documents WHERE paperless_id IS NOT NULL").fetchall()
        known_ids = {int(row[0]) for row in rows}
        queued = []
        for document in documents:
            document_id = int(document["id"])
            if document_id not in known_ids:
                self.queue_store.enqueue(document_id)
                queued.append(document_id)

        now = self._now()
        self.queue_store.set_meta(BASELINE_KEY, now)
        logger.info("Reconciliation finished: %s document(s) queued.", len(queued))
        return {"queued": len(queued), "document_ids": queued, "baseline": now}

    def start(self) -> None:
        if not settings.reconcile_enabled:
            logger.info("Reconciliation disabled by configuration.")
            return
        self._thread.start()

    def _loop(self) -> None:
        # Give Paperless time to become available before the first scheduled run.
        while not self._stop.wait(settings.reconcile_interval_seconds):
            try:
                self.reconcile()
            except Exception:
                logger.exception("Periodic reconciliation failed; will retry later.")

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
