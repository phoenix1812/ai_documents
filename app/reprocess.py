"""Reprocessing helpers used by the Review UI and future CLI/jobs."""

import requests

from app.config import settings
from app.db import Database


def enqueue_paperless_document(paperless_id: int, *, force: bool = False) -> str:
    """Submit a document to the AI worker queue.

    Review UI runs in a separate process/container from the trigger server, so
    it must use the same HTTP boundary as Paperless instead of classifying
    inline. That keeps Ollama calls serialized by app.document_queue.

    ``force`` asks the worker to classify the document even when its queue row
    already holds a final status; that is what the reprocess page orders.
    """
    payload: dict[str, int | bool] = {"document_id": paperless_id}
    if force:
        payload["force"] = True

    response = requests.post(
        settings.ai_worker_trigger_url,
        json=payload,
        timeout=10,
    )
    response.raise_for_status()

    body = response.json()
    status = body.get("status", "UNKNOWN")
    queue_size = body.get("queue_size", "unknown")
    return f"{status} (queue_size={queue_size})"


def retry_failed_document(document_db_id: int) -> str:
    db = Database(settings.db_path)
    row = db.get_document_row(document_db_id)

    if row is None:
        raise ValueError(f"Document DB row not found: {document_db_id}")

    paperless_id = row.get("paperless_id")
    if not paperless_id:
        raise ValueError(f"Document DB row has no paperless_id: {document_db_id}")

    db.increment_retry(document_db_id)
    return enqueue_paperless_document(int(paperless_id))
