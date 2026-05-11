"""
SQLite database layer for document tracking.

Runs inside Docker container with persistent volume.
"""

import sqlite3
from pathlib import Path
from datetime import datetime


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
                paperless_id INTEGER UNIQUE,
                file_hash TEXT UNIQUE,
                title TEXT,
                correspondent TEXT,
                document_type TEXT,
                export_path TEXT,
                created_at TEXT
            )
        """)

        self.conn.commit()

    def document_exists(self, paperless_id: int) -> bool:
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT 1
            FROM documents
            WHERE paperless_id = ?
            LIMIT 1
            """,
            (paperless_id,),
        )

        return cursor.fetchone() is not None

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
    ) -> None:

        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO documents (
                paperless_id,
                file_hash,
                title,
                correspondent,
                document_type,
                export_path,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            paperless_id,
            file_hash,
            title,
            correspondent,
            document_type,
            export_path,
            datetime.utcnow().isoformat(),
        ))

        self.conn.commit()