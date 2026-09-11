from app.queue_store import (
    STATE_PROCESSING,
    STATE_QUEUED,
    PersistentQueueStore,
)


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
