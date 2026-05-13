"""SQLite database layer for document tracking."""

import sqlite3
from datetime import datetime
from pathlib import Path


STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"
STATUS_FAILED_OCR = "FAILED_OCR"
STATUS_FAILED_LLM = "FAILED_LLM"
STATUS_FAILED_EXPORT = "FAILED_EXPORT"
STATUS_FAILED_API = "FAILED_API"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
STATUS_DRY_RUN = "DRY_RUN"

FINAL_STATUSES = (
    STATUS_DONE,
    STATUS_SKIPPED_DUPLICATE,
    STATUS_NEEDS_REVIEW,
    STATUS_DRY_RUN,
)


class Database:
    """Small SQLite wrapper used to persist document processing state."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).mkdir(parents=True, exist_ok=True)
        self.db_file = Path(db_path) / "documents.db"
        self.conn = sqlite3.connect(
            self.db_file,
            check_same_thread=False,
        )
        self._init_db()

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    def _init_db(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paperless_id INTEGER,
                file_hash TEXT UNIQUE,
                title TEXT,
                correspondent TEXT,
                document_type TEXT,
                export_path TEXT,
                status TEXT,
                error_message TEXT,
                created_at TEXT,
                processed_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_paperless_id
            ON documents (paperless_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_status
            ON documents (status)
            """
        )
        self.conn.commit()

    def exists_hash(self, file_hash: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT 1 FROM documents WHERE file_hash = ?",
            (file_hash,),
        )
        return cursor.fetchone() is not None

    def exists_paperless_id(
        self,
        paperless_id: int,
        statuses: tuple[str, ...] = FINAL_STATUSES,
    ) -> bool:
        """Return True if a Paperless document already reached a final state.

        This replaces the old in-memory worker set and survives restarts.
        """
        cursor = self.conn.cursor()
        placeholders = ", ".join("?" for _ in statuses)
        cursor.execute(
            f"""
            SELECT 1
            FROM documents
            WHERE paperless_id = ?
              AND status IN ({placeholders})
            LIMIT 1
            """,
            (paperless_id, *statuses),
        )
        return cursor.fetchone() is not None

    def insert_document(
        self,
        paperless_id: int,
        file_hash: str,
        title: str,
        correspondent: str,
        document_type: str,
        export_path: str,
        status: str = STATUS_DONE,
        error_message: str | None = None,
    ) -> None:
        cursor = self.conn.cursor()
        now = self._now()
        cursor.execute(
            """
            INSERT OR REPLACE INTO documents (
                paperless_id,
                file_hash,
                title,
                correspondent,
                document_type,
                export_path,
                status,
                error_message,
                created_at,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paperless_id,
                file_hash,
                title,
                correspondent,
                document_type,
                export_path,
                status,
                error_message,
                now,
                now,
            ),
        )
        self.conn.commit()

    def mark_failed(
        self,
        paperless_id: int,
        error_message: str,
        status: str = STATUS_FAILED,
    ) -> None:
        cursor = self.conn.cursor()
        now = self._now()
        cursor.execute(
            """
            INSERT INTO documents (
                paperless_id,
                file_hash,
                title,
                correspondent,
                document_type,
                export_path,
                status,
                error_message,
                created_at,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paperless_id,
                f"{status}-{paperless_id}-{now}",
                "",
                "",
                "",
                "",
                status,
                error_message,
                now,
                now,
            ),
        )
        self.conn.commit()
