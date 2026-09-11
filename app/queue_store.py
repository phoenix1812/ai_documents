"""Persistent SQLite-backed job queue for AI Documents.

The application queue itself is intentionally single-worker, but its state is
persisted so Docker/container restarts cannot silently lose pending jobs.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STATE_QUEUED = "QUEUED"
STATE_PROCESSING = "PROCESSING"
STATE_DONE = "DONE"
STATE_RETRY = "RETRY"
STATE_DEAD = "DEAD"


class PersistentQueueStore:
    def __init__(self, db_path: str, *, recover_processing: bool = False) -> None:
        Path(db_path).mkdir(parents=True, exist_ok=True)
        self.db_file = Path(db_path) / "documents.db"
        self._lock = threading.Lock()
        self._init_db(recover_processing=recover_processing)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _parse(value: str) -> datetime:
        return datetime.fromisoformat(value)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self, *, recover_processing: bool = False) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_jobs (
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
                """
                CREATE INDEX IF NOT EXISTS idx_processing_jobs_ready
                ON processing_jobs(state, next_attempt_at, updated_at)
                """
            )
            if recover_processing:
                now = self._now()
                conn.execute(
                    """
                    UPDATE processing_jobs
                    SET state = ?, updated_at = ?, next_attempt_at = ?
                    WHERE state = ?
                    """,
                    (STATE_QUEUED, now, now, STATE_PROCESSING),
                )
            conn.commit()

    def enqueue(self, document_id: int, force: bool = False) -> dict[str, Any]:
        if document_id <= 0:
            raise ValueError("document_id must be greater than 0")

        now = self._now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE document_id = ?",
                (document_id,),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO processing_jobs
                    (document_id, state, attempts, created_at, updated_at, next_attempt_at)
                    VALUES (?, ?, 0, ?, ?, ?)
                    """,
                    (document_id, STATE_QUEUED, now, now, now),
                )
                conn.commit()
                return {
                    "document_id": document_id,
                    "accepted": True,
                    "queued": True,
                    "status": STATE_QUEUED,
                }

            state = row["state"]
            if state == STATE_PROCESSING:
                return {
                    "document_id": document_id,
                    "accepted": True,
                    "queued": False,
                    "status": "ALREADY_PROCESSING",
                }

            if state == STATE_QUEUED and not force:
                return {
                    "document_id": document_id,
                    "accepted": True,
                    "queued": False,
                    "status": f"ALREADY_{state}",
                }

            conn.execute(
                """
                UPDATE processing_jobs
                SET state = ?, attempts = 0, last_error = NULL, updated_at = ?, next_attempt_at = ?
                WHERE document_id = ?
                """,
                (STATE_QUEUED, now, now, document_id),
            )
            conn.commit()
            return {
                "document_id": document_id,
                "accepted": True,
                "queued": True,
                "status": STATE_QUEUED,
            }

    def claim_next(self) -> int | None:
        now = self._now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT document_id
                FROM processing_jobs
                WHERE state IN (?, ?)
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY updated_at ASC, document_id ASC
                LIMIT 1
                """,
                (STATE_QUEUED, STATE_RETRY, now),
            ).fetchone()

            if row is None:
                return None

            document_id = int(row["document_id"])
            updated = conn.execute(
                """
                UPDATE processing_jobs
                SET state = ?, attempts = attempts + 1, updated_at = ?
                WHERE document_id = ?
                  AND state IN (?, ?)
                """,
                (
                    STATE_PROCESSING,
                    now,
                    document_id,
                    STATE_QUEUED,
                    STATE_RETRY,
                ),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return None

            conn.commit()
            return document_id

    def mark_done(self, document_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET state = ?, last_error = NULL, updated_at = ?, next_attempt_at = NULL
                WHERE document_id = ? AND state = ?
                """,
                (STATE_DONE, self._now(), document_id, STATE_PROCESSING),
            )
            conn.commit()

    def mark_retry(
        self,
        document_id: int,
        error: str,
        max_attempts: int,
        base_delay_seconds: int,
        max_delay_seconds: int,
    ) -> bool:
        now = self._now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM processing_jobs WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                return False

            attempts = int(row["attempts"])
            if attempts >= max_attempts:
                conn.execute(
                    """
                    UPDATE processing_jobs
                    SET state = ?, last_error = ?, updated_at = ?, next_attempt_at = NULL
                    WHERE document_id = ? AND state = ?
                    """,
                    (STATE_DEAD, error[:4000], now, document_id, STATE_PROCESSING),
                )
                conn.commit()
                return False

            delay = min(
                max_delay_seconds,
                base_delay_seconds * (2 ** max(0, attempts - 1)),
            )
            next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)
            conn.execute(
                """
                UPDATE processing_jobs
                SET state = ?, last_error = ?, updated_at = ?, next_attempt_at = ?
                WHERE document_id = ? AND state = ?
                """,
                (
                    STATE_RETRY,
                    error[:4000],
                    now,
                    next_attempt.isoformat(timespec="seconds"),
                    document_id,
                    STATE_PROCESSING,
                ),
            )
            conn.commit()
            return True

    def mark_dead(self, document_id: int, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET state = ?, last_error = ?, updated_at = ?, next_attempt_at = NULL
                WHERE document_id = ?
                """,
                (STATE_DEAD, error[:4000], self._now(), document_id),
            )
            conn.commit()

    def recover_processing(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE processing_jobs
                SET state = ?, updated_at = ?, next_attempt_at = ?
                WHERE state = ?
                """,
                (STATE_QUEUED, self._now(), self._now(), STATE_PROCESSING),
            )
            conn.commit()
            return int(cursor.rowcount)

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS count FROM processing_jobs GROUP BY state"
            ).fetchall()
            counts = {str(row["state"]): int(row["count"]) for row in rows}

            current = conn.execute(
                """
                SELECT document_id, attempts, updated_at
                FROM processing_jobs
                WHERE state = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (STATE_PROCESSING,),
            ).fetchone()

            return {
                "counts": counts,
                "queued": counts.get(STATE_QUEUED, 0),
                "retry": counts.get(STATE_RETRY, 0),
                "processing": counts.get(STATE_PROCESSING, 0),
                "dead": counts.get(STATE_DEAD, 0),
                "done": counts.get(STATE_DONE, 0),
                "current": dict(current) if current else None,
            }

    def list_recoverable(self, limit: int = 100) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT document_id
                FROM processing_jobs
                WHERE state IN (?, ?)
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (STATE_QUEUED, STATE_RETRY, limit),
            ).fetchall()
            return [int(row["document_id"]) for row in rows]

    def integrity_check(self) -> str:
        with self._connect() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return str(row[0]) if row else "unknown"
