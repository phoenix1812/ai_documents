"""Crash-safe single-worker persistent queue."""
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass
from app.config import settings
from app.queue_store import QueueStore
from app.worker import Worker

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class QueueStatus:
    document_id: int
    accepted: bool
    queued: bool
    status: str
    queue_size: int

class DocumentProcessingQueue:
    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        self.store = QueueStore()
        recovered = self.store.recover()
        if recovered:
            logger.warning("Recovered %s stale processing jobs after restart.", recovered)
        self._lock = threading.Lock()
        self._current_document_id: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="document-processing-queue")
        self._thread.start()

    def enqueue(self, document_id: int) -> QueueStatus:
        if document_id <= 0:
            raise ValueError("document_id must be greater than 0")
        inserted = self.store.enqueue(document_id)
        snapshot = self.store.snapshot()
        return QueueStatus(
            document_id=document_id,
            accepted=True,
            queued=inserted,
            status="QUEUED" if inserted else "ALREADY_QUEUED_OR_FINISHED",
            queue_size=snapshot["queue_size"],
        )

    def snapshot(self) -> dict:
        snapshot = self.store.snapshot()
        with self._lock:
            snapshot["current_document_id"] = self._current_document_id
        return snapshot

    def _run(self) -> None:
        while not self._stop.is_set():
            job = None
            try:
                job = self.store.claim()
                if job is None:
                    time.sleep(settings.queue_poll_seconds)
                    continue
                document_id = int(job["document_id"])
                with self._lock:
                    self._current_document_id = document_id
                logger.info("Processing queued document %s (attempt %s/%s).", document_id, job["attempts"], job["max_attempts"])
                try:
                    result = self.worker.process_once(document_id=document_id)
                    self.store.finish(int(job["id"]), result)
                    logger.info("Document %s finished: %s.", document_id, result)
                except Exception as exc:
                    retry = self.store.fail(int(job["id"]), str(exc), int(job["attempts"]))
                    if retry:
                        logger.warning("Document %s failed; scheduled retry: %s", document_id, exc)
                    else:
                        logger.error("Document %s moved to DEAD after maximum retries: %s", document_id, exc)
            except Exception:
                logger.exception("Persistent queue loop failed.")
                time.sleep(2)
            finally:
                with self._lock:
                    self._current_document_id = None

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.store.close()
