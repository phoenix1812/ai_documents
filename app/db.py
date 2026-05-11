"""
SQLite database layer for document tracking.
"""

import sqlite3
from pathlib import Path
from datetime import datetime


STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"


class Database:
    def __init__(self, db_path: str) -> None:
        Path(db_path).mkdir(parents=True, exist_ok=True)

        self.db_file = Path(db_path) / "documents.db"
        self.conn = sqlite3.connect(
            self.db_file,
            check_same_thread=False,
        )
        self._init_db()

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
                export_path TEXT,
                status TEXT,
                error_message TEXT,
                created_at TEXT,
                processed_at TEXT
            )
        """)

        self.conn.commit()

    def exists_hash(self, file_hash: str) -> bool:
        cursor = self.conn.cursor()

        cursor.execute(
            "SELECT 1 FROM documents WHERE file_hash = ?",
            (file_hash,),
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

        cursor.execute("""
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            paperless_id,
            file_hash,
            title,
            correspondent,
            document_type,
            export_path,
            status,
            error_message,
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat(),
        ))

        self.conn.commit()

    def mark_failed(
        self,
        paperless_id: int,
        error_message: str,
    ) -> None:
        cursor = self.conn.cursor()

        cursor.execute("""
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            paperless_id,
            f"FAILED-{paperless_id}-{datetime.utcnow().isoformat()}",
            "",
            "",
            "",
            "",
            STATUS_FAILED,
            error_message,
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat(),
        ))

        self.conn.commit()