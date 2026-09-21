"""The worker guard must not swallow a scheduled retry.

A failed attempt writes a FAILED_* row before the queue retries, so treating that
row as "already processed" makes every retry return ALREADY_PROCESSED and the
document is never classified again.
"""

from types import SimpleNamespace

import pytest

from app.db import Database
from app.db import STATUS_FAILED_API
from app.db import STATUS_FAILED_LLM
from app.db import STATUS_NEEDS_REVIEW
from app.db import STATUS_SKIPPED_DUPLICATE
from app.db import final_statuses
from app.db import reprocessable_statuses
from app.worker import Worker


@pytest.fixture
def worker_with_db(tmp_path, monkeypatch):
    db = Database(str(tmp_path))
    worker = Worker.__new__(Worker)
    worker.classifier = SimpleNamespace(
        db=db,
        process_document=lambda **kwargs: STATUS_NEEDS_REVIEW,
    )
    monkeypatch.setattr(worker, "wait_for_paperless", lambda: None)
    return worker, db


def insert(db, paperless_id, status):
    db.insert_document(
        paperless_id=paperless_id,
        file_hash=f"hash-{paperless_id}",
        title="",
        correspondent="",
        document_type="",
        export_path="",
        status=status,
    )


def test_failed_row_is_processed_again(worker_with_db):
    worker, db = worker_with_db
    insert(db, 40, STATUS_FAILED_API)

    assert worker.process_once(document_id=40) == STATUS_NEEDS_REVIEW


def test_successful_row_is_not_processed_again(worker_with_db):
    worker, db = worker_with_db
    insert(db, 41, STATUS_SKIPPED_DUPLICATE)

    assert worker.process_once(document_id=41) == "ALREADY_PROCESSED"


def test_deterministic_failure_is_still_retried_on_demand(worker_with_db):
    worker, db = worker_with_db
    insert(db, 42, STATUS_FAILED_LLM)

    assert worker.process_once(document_id=42) == STATUS_NEEDS_REVIEW


def test_reconciliation_still_treats_failures_as_final():
    final = set(final_statuses(dry_run=True))
    reprocessable = set(reprocessable_statuses(dry_run=True))

    assert STATUS_FAILED_API in final
    assert STATUS_FAILED_API not in reprocessable
    assert STATUS_SKIPPED_DUPLICATE in reprocessable
