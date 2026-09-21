"""Retry policy for the document queue.

The worker is single-threaded, so a status that is retried without a chance of
succeeding blocks every other document for the whole retry budget.
"""

from app.db import DETERMINISTIC_FAILURE_STATUSES
from app.db import TRANSIENT_FAILURE_STATUSES
from app.document_queue import RETRY_STATUSES


def test_only_transient_failures_are_retried():
    assert RETRY_STATUSES == set(TRANSIENT_FAILURE_STATUSES)


def test_deterministic_failures_are_never_retried():
    assert not set(DETERMINISTIC_FAILURE_STATUSES) & RETRY_STATUSES
