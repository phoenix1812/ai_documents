"""Reprocessing helpers used by the Review UI and future CLI/jobs."""

from app.classifier import DocumentClassifier
from app.config import settings
from app.db import Database


def reprocess_paperless_document(paperless_id: int) -> str:
    classifier = DocumentClassifier()
    return classifier.process_document(paperless_id)


def retry_failed_document(document_db_id: int) -> str:
    db = Database(settings.db_path)
    row = db.get_document_row(document_db_id)

    if row is None:
        raise ValueError(f"Document DB row not found: {document_db_id}")

    paperless_id = row.get("paperless_id")
    if not paperless_id:
        raise ValueError(f"Document DB row has no paperless_id: {document_db_id}")

    db.increment_retry(document_db_id)
    return reprocess_paperless_document(int(paperless_id))
