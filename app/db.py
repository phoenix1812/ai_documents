"""
Robust SQLite database layer for AI Documents.

Supports:
- document tracking
- review UI
- audit/history view
- manual corrections of already approved documents
- retry/reprocess
- review-learning log
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


STATUS_DONE = "DONE"
STATUS_AUTO_APPROVED = "AUTO_APPROVED"
STATUS_MANUALLY_APPROVED = "MANUALLY_APPROVED"
STATUS_FAILED = "FAILED"
STATUS_FAILED_OCR = "FAILED_OCR"
STATUS_FAILED_LLM = "FAILED_LLM"
STATUS_FAILED_EXPORT = "FAILED_EXPORT"
STATUS_FAILED_API = "FAILED_API"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATUS_SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
STATUS_DRY_RUN = "DRY_RUN"
STATUS_IGNORED = "IGNORED"

FAILED_STATUSES = (
    STATUS_FAILED,
    STATUS_FAILED_OCR,
    STATUS_FAILED_LLM,
    STATUS_FAILED_EXPORT,
    STATUS_FAILED_API,
)

REVIEW_STATUSES = (
    STATUS_NEEDS_REVIEW,
    STATUS_REVIEW_REQUIRED,
    STATUS_DRY_RUN,
)

APPROVED_STATUSES = (
    STATUS_DONE,
    STATUS_AUTO_APPROVED,
    STATUS_MANUALLY_APPROVED,
)

FINAL_STATUSES = (
    STATUS_DONE,
    STATUS_AUTO_APPROVED,
    STATUS_MANUALLY_APPROVED,
    STATUS_SKIPPED_DUPLICATE,
    STATUS_NEEDS_REVIEW,
    STATUS_REVIEW_REQUIRED,
    STATUS_DRY_RUN,
    STATUS_IGNORED,
)


class Database:
    def __init__(self, db_path: str) -> None:
        Path(db_path).mkdir(parents=True, exist_ok=True)
        self.db_file = Path(db_path) / "documents.db"

        self.conn = sqlite3.connect(
            self.db_file,
            check_same_thread=False,
            timeout=30,
        )
        self.conn.row_factory = sqlite3.Row

        self._configure_sqlite()
        self._init_db()

    def _configure_sqlite(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat(timespec="seconds")

    @staticmethod
    def _json_list(values: list[str] | None) -> str:
        return json.dumps(values or [], ensure_ascii=False)

    @staticmethod
    def parse_json_list(value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []

            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [
                        str(item).strip()
                        for item in parsed
                        if str(item).strip()
                    ]
            except json.JSONDecodeError:
                pass

            return [item.strip() for item in value.split(",") if item.strip()]

        return []

    def _column_exists(self, table: str, column: str) -> bool:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    def _add_column_if_missing(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        if not self._column_exists(table, column):
            self.conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
            self.conn.commit()

    def _init_db(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paperless_id INTEGER,
                file_hash TEXT UNIQUE,
                title TEXT,
                correspondent TEXT,
                document_type TEXT,
                tags TEXT DEFAULT '[]',
                confidence REAL,
                reason TEXT,
                original_title TEXT,
                ocr_excerpt TEXT,
                paperless_url TEXT,
                export_path TEXT,
                status TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                last_retry_at TEXT,
                created_at TEXT,
                processed_at TEXT
            )
        """)

        for column, definition in (
            ("tags", "TEXT DEFAULT '[]'"),
            ("confidence", "REAL"),
            ("reason", "TEXT"),
            ("original_title", "TEXT"),
            ("ocr_excerpt", "TEXT"),
            ("paperless_url", "TEXT"),
            ("retry_count", "INTEGER DEFAULT 0"),
            ("last_retry_at", "TEXT"),
        ):
            self._add_column_if_missing("documents", column, definition)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS review_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_db_id INTEGER,
                paperless_id INTEGER,
                action TEXT NOT NULL,
                original_ai_title TEXT,
                original_ai_correspondent TEXT,
                original_ai_document_type TEXT,
                original_ai_tags TEXT DEFAULT '[]',
                final_title TEXT,
                final_correspondent TEXT,
                final_document_type TEXT,
                final_tags TEXT DEFAULT '[]',
                reason TEXT,
                created_at TEXT NOT NULL
            )
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_paperless_id
            ON documents (paperless_id)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_file_hash
            ON documents (file_hash)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_status
            ON documents (status)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_processed_at
            ON documents (processed_at)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_review_decisions_paperless_id
            ON review_decisions (paperless_id)
        """)

        self.conn.commit()

    @staticmethod
    def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return dict(row)

    def exists_hash(self, file_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM documents WHERE file_hash = ? LIMIT 1",
            (file_hash,),
        ).fetchone()
        return row is not None

    def exists_paperless_id(
        self,
        paperless_id: int,
        statuses: tuple[str, ...] = FINAL_STATUSES,
    ) -> bool:
        placeholders = ", ".join("?" for _ in statuses)
        row = self.conn.execute(
            f"""
            SELECT 1
            FROM documents
            WHERE paperless_id = ?
              AND status IN ({placeholders})
            LIMIT 1
            """,
            (paperless_id, *statuses),
        ).fetchone()
        return row is not None

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
        now = self._now()

        self.conn.execute("""
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
                retry_count,
                created_at,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                (SELECT retry_count FROM documents WHERE file_hash = ?),
                0
            ), ?, ?)
        """, (
            paperless_id,
            file_hash,
            title,
            correspondent,
            document_type,
            self._json_list(tags),
            confidence,
            reason,
            original_title,
            ocr_excerpt,
            paperless_url,
            export_path,
            status,
            error_message,
            file_hash,
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
        now = self._now()
        synthetic_hash = f"{status}-{paperless_id}-{now}"

        self.conn.execute("""
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
                retry_count,
                created_at,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            paperless_id,
            synthetic_hash,
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
            0,
            now,
            now,
        ))
        self.conn.commit()

    def list_by_statuses(
        self,
        statuses: tuple[str, ...],
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not statuses:
            return []

        placeholders = ", ".join("?" for _ in statuses)
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM documents
            WHERE status IN ({placeholders})
            ORDER BY processed_at DESC, id DESC
            LIMIT ?
            """,
            (*statuses, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_documents(
        self,
        status: str | None = None,
        query: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM documents"
        params: list[Any] = []
        where: list[str] = []

        if status:
            where.append("status = ?")
            params.append(status)

        if query:
            like = f"%{query.strip()}%"
            where.append("""
                (
                    title LIKE ?
                    OR original_title LIKE ?
                    OR correspondent LIKE ?
                    OR document_type LIKE ?
                    OR tags LIKE ?
                    OR CAST(paperless_id AS TEXT) LIKE ?
                )
            """)
            params.extend([like, like, like, like, like, like])

        if where:
            sql += " WHERE " + " AND ".join(where)

        sql += " ORDER BY processed_at DESC, id DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_document_row(self, document_db_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_db_id,),
        ).fetchone()
        return self.row_to_dict(row)

    def get_latest_for_paperless_id(
        self,
        paperless_id: int,
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT *
            FROM documents
            WHERE paperless_id = ?
            ORDER BY processed_at DESC, id DESC
            LIMIT 1
            """,
            (paperless_id,),
        ).fetchone()
        return self.row_to_dict(row)

    def update_document_values(
        self,
        document_db_id: int,
        title: str,
        correspondent: str,
        document_type: str,
        tags: list[str],
    ) -> None:
        result = self.conn.execute(
            """
            UPDATE documents
            SET title = ?,
                correspondent = ?,
                document_type = ?,
                tags = ?,
                processed_at = ?
            WHERE id = ?
            """,
            (
                title,
                correspondent,
                document_type,
                self._json_list(tags),
                self._now(),
                document_db_id,
            ),
        )
        self.conn.commit()

        if result.rowcount == 0:
            raise ValueError(f"Document DB row not found: {document_db_id}")

    def update_status(
        self,
        document_db_id: int,
        status: str,
        error_message: str | None = None,
    ) -> None:
        result = self.conn.execute(
            """
            UPDATE documents
            SET status = ?,
                error_message = ?,
                processed_at = ?
            WHERE id = ?
            """,
            (status, error_message, self._now(), document_db_id),
        )
        self.conn.commit()

        if result.rowcount == 0:
            raise ValueError(f"Document DB row not found: {document_db_id}")

    def increment_retry(self, document_db_id: int) -> None:
        now = self._now()
        result = self.conn.execute(
            """
            UPDATE documents
            SET retry_count = COALESCE(retry_count, 0) + 1,
                last_retry_at = ?,
                processed_at = ?
            WHERE id = ?
            """,
            (now, now, document_db_id),
        )
        self.conn.commit()

        if result.rowcount == 0:
            raise ValueError(f"Document DB row not found: {document_db_id}")

    def dashboard_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM documents
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        return {row["status"] or "UNKNOWN": int(row["count"]) for row in rows}

    def recent_documents(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM documents
            ORDER BY processed_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_review_decision(
        self,
        document_db_id: int,
        paperless_id: int,
        action: str,
        original_ai_title: str | None,
        original_ai_correspondent: str | None,
        original_ai_document_type: str | None,
        original_ai_tags: list[str] | None,
        final_title: str | None,
        final_correspondent: str | None,
        final_document_type: str | None,
        final_tags: list[str] | None,
        reason: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO review_decisions (
                document_db_id,
                paperless_id,
                action,
                original_ai_title,
                original_ai_correspondent,
                original_ai_document_type,
                original_ai_tags,
                final_title,
                final_correspondent,
                final_document_type,
                final_tags,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_db_id,
                paperless_id,
                action,
                original_ai_title,
                original_ai_correspondent,
                original_ai_document_type,
                self._json_list(original_ai_tags),
                final_title,
                final_correspondent,
                final_document_type,
                self._json_list(final_tags),
                reason,
                self._now(),
            ),
        )
        self.conn.commit()

    def learning_summary(self, limit: int = 25) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM review_decisions
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def integrity_check(self) -> str:
        row = self.conn.execute("PRAGMA integrity_check").fetchone()
        if row is None:
            return "unknown"
        return str(row[0])

    def close(self) -> None:
        self.conn.close()
