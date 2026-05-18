"""Single-worker queue for event-driven document processing.

Paperless may trigger multiple post-consume calls in quick succession. This queue
accepts those requests immediately, deduplicates queued/running document IDs and
processes them sequentially in one worker thread.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

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
    """Process Paperless documents sequentially in a single background worker."""

    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        self._queue: queue.Queue[int] = queue.Queue()
        self._lock = threading.Lock()
        self._queued_or_running: set[int] = set()
        self._current_document_id: int | None = None
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="document-processing-queue",
        )
        self._thread.start()

    def enqueue(self, document_id: int) -> QueueStatus:
        """Add a document to the queue unless it is already queued or running."""
        with self._lock:
            if document_id in self._queued_or_running:
                return QueueStatus(
                    document_id=document_id,
                    accepted=True,
                    queued=False,
                    status="ALREADY_QUEUED_OR_RUNNING",
                    queue_size=self._queue.qsize(),
                )

            self._queued_or_running.add(document_id)
            self._queue.put(document_id)

            return QueueStatus(
                document_id=document_id,
                accepted=True,
                queued=True,
                status="QUEUED",
                queue_size=self._queue.qsize(),
            )

    def snapshot(self) -> dict:
        """Return a small status snapshot for health/debug endpoints."""
        with self._lock:
            return {
                "current_document_id": self._current_document_id,
                "queue_size": self._queue.qsize(),
                "queued_or_running": sorted(self._queued_or_running),
            }

    def _run(self) -> None:
        while True:
            document_id = self._queue.get()
            with self._lock:
                self._current_document_id = document_id

            try:
                logger.info("Queued processing started for document %s.", document_id)
                result = self.worker.process_once(document_id=document_id)
                logger.info(
                    "Queued processing finished for document %s: %s.",
                    document_id,
                    result,
                )
            except Exception:
                logger.exception("Queued processing failed for document %s.", document_id)
            finally:
                with self._lock:
                    self._queued_or_running.discard(document_id)
                    self._current_document_id = None
                self._queue.task_done()
