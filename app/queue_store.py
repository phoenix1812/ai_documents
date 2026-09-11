"""Persistent SQLite-backed job queue storage."""
from __future__ import annotations
from app.config import settings
from app.db import Database


class QueueStore:
    def __init__(self) -> None:
        self.db = Database(settings.db_path)

    def enqueue(self, document_id: int) -> bool:
        return self.db.enqueue_job(document_id, settings.queue_max_attempts)

    def recover(self) -> int:
        return self.db.recover_stale_jobs(settings.queue_stale_after_seconds)

    def claim(self):
        return self.db.claim_next_job()

    def finish(self, job_id: int, result_status: str) -> None:
        self.db.finish_job(job_id, result_status)

    def fail(self, job_id: int, error: str, attempt: int) -> bool:
        delay = min(settings.retry_max_seconds, settings.retry_base_seconds * (2 ** max(0, attempt - 1)))
        return self.db.fail_job(job_id, error, delay)

    def snapshot(self) -> dict:
        return self.db.queue_snapshot()

    def get_meta(self, key: str):
        return self.db.get_meta(key)

    def set_meta(self, key: str, value: str) -> None:
        self.db.set_meta(key, value)

    def close(self) -> None:
        self.db.close()
