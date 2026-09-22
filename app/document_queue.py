"""Single-worker persistent document processing queue."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from app.config import settings
from app.db import TRANSIENT_FAILURE_STATUSES
from app.queue_store import PersistentQueueStore
from app.worker import Worker

logger = logging.getLogger(__name__)

# Deterministic failures (no OCR text, unparsable model answer) are terminal:
# repeating them would occupy the single worker for up to
# QUEUE_MAX_ATTEMPTS x the Ollama retry count without any chance of success.
RETRY_STATUSES = set(TRANSIENT_FAILURE_STATUSES)


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
        self.store = PersistentQueueStore(settings.db_path, recover_processing=True)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._current_document_id: int | None = None
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="document-processing-queue",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def enqueue(self, document_id: int, force: bool = False) -> QueueStatus:
        result = self.store.enqueue(document_id, force=force)
        status = self.store.status()
        return QueueStatus(
            document_id=document_id,
            accepted=bool(result["accepted"]),
            queued=bool(result["queued"]),
            status=str(result["status"]),
            queue_size=int(status["queued"]) + int(status["retry"]),
        )

    def exhausted_document_ids(self) -> set[int]:
        return self.store.exhausted_document_ids()

    def snapshot(self) -> dict:
        status = self.store.status()
        with self._lock:
            current = self._current_document_id
        return {
            "current_document_id": current,
            "queue_size": int(status["queued"]) + int(status["retry"]),
            "queued": int(status["queued"]),
            "retry": int(status["retry"]),
            "processing": int(status["processing"]),
            "done": int(status["done"]),
            "dead": int(status["dead"]),
            "current_job": status["current"],
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                document_id = self.store.claim_next()
            except Exception:
                # A transient SQLite/IO error must not kill the only consumer:
                # the thread would stop working while /ready still reports ok.
                logger.exception("Queue claim failed.")
                document_id = None

            if document_id is None:
                self._stop.wait(max(1, settings.queue_poll_interval_seconds))
                continue

            with self._lock:
                self._current_document_id = document_id

            try:
                logger.info("Processing queued document %s.", document_id)
                result = self.worker.process_once(
                    document_id=document_id,
                    force=self.store.is_forced(document_id),
                )
                logger.info("Document %s finished with status %s.", document_id, result)

                if result in RETRY_STATUSES:
                    retry_scheduled = self.store.mark_retry(
                        document_id=document_id,
                        error=f"Worker returned {result}",
                        max_attempts=settings.queue_max_attempts,
                        base_delay_seconds=settings.queue_retry_base_seconds,
                        max_delay_seconds=settings.queue_retry_max_seconds,
                    )
                    if retry_scheduled:
                        logger.warning(
                            "Document %s scheduled for retry after status %s.",
                            document_id,
                            result,
                        )
                    else:
                        logger.error(
                            "Document %s reached the maximum retry count.",
                            document_id,
                        )
                else:
                    self.store.mark_done(document_id)
            except Exception as exc:
                logger.exception("Queued processing failed for document %s.", document_id)
                retry_scheduled = self.store.mark_retry(
                    document_id=document_id,
                    error=str(exc),
                    max_attempts=settings.queue_max_attempts,
                    base_delay_seconds=settings.queue_retry_base_seconds,
                    max_delay_seconds=settings.queue_retry_max_seconds,
                )
                if not retry_scheduled:
                    logger.error(
                        "Document %s moved to DEAD after maximum attempts.",
                        document_id,
                    )
            finally:
                with self._lock:
                    self._current_document_id = None
