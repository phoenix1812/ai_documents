"""
SQLite database layer for document tracking.

Stores:
- processed Paperless document IDs
- classification suggestions
- review metadata
- safety/status information
"""

import json
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

    def _column_exists(self, table: str, column: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cursor.fetchall())

    def _add_column_if_missing(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        if not self._column_exists(table, column):
            cursor = self.conn.cursor()
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def _init_db(self) -> None:
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paperless_id INTEGER,
                file_hash TEXT UNIQUE,
                title TEXT,
                correspondent TEXT,
                document_type TEXT,
                tags TEXT,
                confidence REAL,
                reason TEXT,
                original_title TEXT,
                ocr_excerpt TEXT,
                paperless_url TEXT,
                export_path TEXT,
                status TEXT,
                error_message TEXT,
                created_at TEXT,
                processed_at TEXT
            )
        """)

        self._add_column_if_missing(
            "documents",
            "tags",
            "TEXT DEFAULT '[]'",
        )
        self._add_column_if_missing(
            "documents",
            "confidence",
            "REAL",
        )
        self._add_column_if_missing(
            "documents",
            "reason",
            "TEXT",
        )
        self._add_column_if_missing(
            "documents",
            "original_title",
            "TEXT",
        )
        self._add_column_if_missing(
            "documents",
            "ocr_excerpt",
            "TEXT",
        )
        self._add_column_if_missing(
            "documents",
            "paperless_url",
            "TEXT",
        )

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_paperless_id
            ON documents (paperless_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_status
            ON documents (status)
        """)

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
        tags: list[str] | None = None,
        confidence: float | None = None,
        reason: str | None = None,
        original_title: str | None = None,
        ocr_excerpt: str | None = None,
        paperless_url: str | None = None,
    ) -> None:
        cursor = self.conn.cursor()
        now = self._now()
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        cursor.execute("""
            INSERT OR REPLACE INTO documents (
                paperless_id,
                file_hash,
                title,
                correspondent,
                document_type,
                tags,
                confidence,
                reason,
                original_title,
                ocr_excerpt,
                paperless_url,
                export_path,
                status,
                error_message,
                created_at,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            paperless_id,
            file_hash,
            title,
            correspondent,
            document_type,
            tags_json,
            confidence,
            reason,
            original_title,
            ocr_excerpt,
            paperless_url,
            export_path,
            status,
            error_message,
            now,
            now,
        ))

        self.conn.commit()

    def mark_failed(
        self,
        paperless_id: int,
        error_message: str,
        status: str = STATUS_FAILED,
    ) -> None:
        cursor = self.conn.cursor()
        now = self._now()

        cursor.execute("""
            INSERT INTO documents (
                paperless_id,
                file_hash,
                title,
                correspondent,
                document_type,
                tags,
                confidence,
                reason,
                original_title,
                ocr_excerpt,
                paperless_url,
                export_path,
                status,
                error_message,
                created_at,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            paperless_id,
            f"{status}-{paperless_id}-{now}",
            "",
            "",
            "",
            "[]",
            None,
            None,
            None,
            None,
            None,
            "",
            status,
            error_message,
            now,
            now,
        ))

        self.conn.commit()
