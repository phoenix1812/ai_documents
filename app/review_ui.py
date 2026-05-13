"""
Simple FastAPI review UI for AI Documents.

Features:
- list documents in NEEDS_REVIEW and DRY_RUN
- show details of one review item
- approve or reject entries
- apply title, correspondent, document type and tags to Paperless
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import (
    STATUS_DONE,
    STATUS_DRY_RUN,
    STATUS_NEEDS_REVIEW,
)
from app.paperless_client import PaperlessClient


DB_FILE = Path(settings.db_path) / "documents.db"

app = FastAPI(title="AI Documents Review UI")

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def parse_tags(value: Any) -> list[str]:
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

        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    return []


def normalize_item(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    item = dict(row)
    item["tags_list"] = parse_tags(item.get("tags"))
    item["tags_display"] = ", ".join(item["tags_list"])
    return item


def get_review_items(status: str | None = None) -> list[dict[str, Any]]:
    allowed_statuses = [STATUS_NEEDS_REVIEW, STATUS_DRY_RUN]

    conn = get_connection()
    try:
        if status:
            rows = conn.execute(
                """
                SELECT *
                FROM documents
                WHERE status = ?
                ORDER BY processed_at DESC, id DESC
                LIMIT 100
                """,
                (status,),
            ).fetchall()
        else:
            placeholders = ",".join("?" for _ in allowed_statuses)
            rows = conn.execute(
                f"""
                SELECT *
                FROM documents
                WHERE status IN ({placeholders})
                ORDER BY processed_at DESC, id DESC
                LIMIT 100
                """,
                allowed_statuses,
            ).fetchall()

        return [
            item
            for row in rows
            if (item := normalize_item(row)) is not None
        ]
    finally:
        conn.close()


def get_item(item_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM documents
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
    finally:
        conn.close()

    item = normalize_item(row)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    return item


def update_item_status(
    item_id: int,
    status: str,
    error_message: str | None = None,
) -> None:
    conn = get_connection()
    try:
        result = conn.execute(
            """
            UPDATE documents
            SET status = ?,
                error_message = ?,
                processed_at = datetime('now')
            WHERE id = ?
            """,
            (status, error_message, item_id),
        )
        conn.commit()
    finally:
        conn.close()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Review item not found")


def update_item_values(
    item_id: int,
    title: str,
    correspondent: str,
    document_type: str,
    tags: list[str],
) -> None:
    conn = get_connection()
    try:
        result = conn.execute(
            """
            UPDATE documents
            SET title = ?,
                correspondent = ?,
                document_type = ?,
                tags = ?,
                processed_at = datetime('now')
            WHERE id = ?
            """,
            (
                title,
                correspondent,
                document_type,
                json.dumps(tags, ensure_ascii=False),
                item_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Review item not found")


@app.get("/")
def index(request: Request, status: str | None = None):
    items = get_review_items(status=status)

    return templates.TemplateResponse(
        "review_list.html",
        {
            "request": request,
            "items": items,
            "selected_status": status,
            "status_needs_review": STATUS_NEEDS_REVIEW,
            "status_dry_run": STATUS_DRY_RUN,
        },
    )


@app.get("/items/{item_id}")
def detail(request: Request, item_id: int):
    item = get_item(item_id)

    return templates.TemplateResponse(
        "review_detail.html",
        {
            "request": request,
            "item": item,
            "status_needs_review": STATUS_NEEDS_REVIEW,
            "status_dry_run": STATUS_DRY_RUN,
        },
    )


@app.post("/items/{item_id}/approve")
def approve(
    item_id: int,
    title: str = Form(...),
    correspondent: str = Form(""),
    document_type: str = Form(""),
    tags: str = Form(""),
    apply_to_paperless: bool = Form(default=False),
):
    item = get_item(item_id)

    if item["status"] not in {STATUS_NEEDS_REVIEW, STATUS_DRY_RUN}:
        raise HTTPException(
            status_code=400,
            detail="Only NEEDS_REVIEW and DRY_RUN items can be approved",
        )

    clean_title = title.strip()
    clean_correspondent = correspondent.strip()
    clean_document_type = document_type.strip()
    tag_list = parse_tags(tags)

    if not clean_title:
        raise HTTPException(
            status_code=400,
            detail="Title must not be empty",
        )

    update_item_values(
        item_id=item_id,
        title=clean_title,
        correspondent=clean_correspondent,
        document_type=clean_document_type,
        tags=tag_list,
    )

    message = "Approved via Review UI"

    if apply_to_paperless:
        client = PaperlessClient()
        payload = client.update_document_metadata_by_names(
            document_id=int(item["paperless_id"]),
            title=clean_title,
            correspondent=clean_correspondent,
            document_type=clean_document_type,
            tags=tag_list,
        )
        message = f"Approved via Review UI and applied to Paperless: {payload}"

    update_item_status(
        item_id=item_id,
        status=STATUS_DONE,
        error_message=message,
    )

    return RedirectResponse("/", status_code=303)


@app.post("/items/{item_id}/reject")
def reject(
    item_id: int,
    reason: str = Form(default="Manuell abgelehnt"),
):
    item = get_item(item_id)

    if item["status"] not in {STATUS_NEEDS_REVIEW, STATUS_DRY_RUN}:
        raise HTTPException(
            status_code=400,
            detail="Only NEEDS_REVIEW and DRY_RUN items can be rejected",
        )

    update_item_status(
        item_id=item_id,
        status=STATUS_NEEDS_REVIEW,
        error_message=f"Rejected via Review UI: {reason}",
    )

    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "db": str(DB_FILE)}
