from app.queue_store import (
    STATE_PROCESSING,
    STATE_QUEUED,
    PersistentQueueStore,
)


def test_queue_operations_close_their_connections(monkeypatch, tmp_path):
    import sqlite3

    import pytest

    store = PersistentQueueStore(str(tmp_path))
    opened = []
    real_connect = store._connect

    def spy():
        conn = real_connect()
        opened.append(conn)
        return conn

    monkeypatch.setattr(store, "_connect", spy)

    store.enqueue(7)
    store.claim_next()
    store.mark_done(7)
    store.status()

    # "with conn" only commits, so a leaked connection here would mean one
    # open file handle per queue operation for the life of the worker.
    assert len(opened) >= 4
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_queue_persists_and_recovers_processing_jobs(tmp_path):
    store = PersistentQueueStore(str(tmp_path))
    assert store.enqueue(123)["status"] == STATE_QUEUED
    assert store.claim_next() == 123
    assert store.status()["processing"] == 1

    # A fresh application instance explicitly performs startup recovery.
    recovered = PersistentQueueStore(str(tmp_path), recover_processing=True)
    assert recovered.status()["processing"] == 0
    assert recovered.status()["queued"] == 1
    assert recovered.claim_next() == 123


def test_health_store_initialization_does_not_recover_active_job(tmp_path):
    store = PersistentQueueStore(str(tmp_path))
    store.enqueue(123)
    assert store.claim_next() == 123

    health_store = PersistentQueueStore(str(tmp_path), recover_processing=False)
    assert health_store.status()["processing"] == 1


def test_force_requeue_resets_attempts_but_never_interrupts_processing(tmp_path):
    store = PersistentQueueStore(str(tmp_path))
    store.enqueue(123)
    assert store.claim_next() == 123
    result = store.enqueue(123, force=True)
    assert result["status"] == "ALREADY_PROCESSING"
    assert store.status()["processing"] == 1

    store.mark_retry(123, "temporary", 10, 1, 10)
    result = store.enqueue(123, force=True)
    assert result["queued"] is True
    assert store.claim_next() == 123


def test_retry_moves_to_dead_after_max_attempts(tmp_path):
    store = PersistentQueueStore(str(tmp_path))
    store.enqueue(123)
    assert store.claim_next() == 123
    assert store.mark_retry(123, "boom", 1, 1, 1) is False
    assert store.status()["dead"] == 1


def test_a_forced_job_reaches_the_worker_with_the_order_still_set(tmp_path):
    """The final-status check happens in the worker, not here, so the order has
    to survive the queue hop from the claim to the attempt."""

    store = PersistentQueueStore(str(tmp_path))
    store.enqueue(123, force=True)
    assert store.claim_next() == 123
    assert store.is_forced(123) is True

    store.mark_done(123)
    assert store.is_forced(123) is False


def test_an_ordinary_enqueue_carries_no_force(tmp_path):
    store = PersistentQueueStore(str(tmp_path))
    store.enqueue(123)
    assert store.claim_next() == 123
    assert store.is_forced(123) is False


def test_a_retry_after_a_forced_attempt_is_not_forced_again(tmp_path):
    """The rerun order is spent with the attempt. Its own retry needs no force:
    a failure is not a final status."""

    store = PersistentQueueStore(str(tmp_path))
    store.enqueue(123, force=True)
    assert store.claim_next() == 123
    assert store.mark_retry(123, "temporary", 10, 1, 10) is True
    assert store.is_forced(123) is False


def test_a_queue_from_before_the_force_column_stays_usable(tmp_path):
    """The deployed database has no force column yet, so startup has to add it
    instead of failing on the first INSERT that names the column."""

    import sqlite3

    db_file = tmp_path / "documents.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE processing_jobs (
            document_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            next_attempt_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO processing_jobs (document_id, state, created_at, updated_at) "
        "VALUES (123, 'DONE', '2026-09-22T00:00:00+00:00', '2026-09-22T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    store = PersistentQueueStore(str(tmp_path))
    assert store.is_forced(123) is False
    assert store.enqueue(123, force=True)["queued"] is True
    assert store.claim_next() == 123
    assert store.is_forced(123) is True
