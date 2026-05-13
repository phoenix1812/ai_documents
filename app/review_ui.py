"""
Simple FastAPI review UI for AI Documents.

Features:
- list documents in NEEDS_REVIEW and DRY_RUN
- show details of one review item
- approve or reject entries
- optional Paperless update on approve

Start locally:
    uvicorn app.review_ui:app --host 0.0.0.0 --port 8090
"""

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


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


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

        return [dict(row) for row in rows]
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

    item = row_to_dict(row)
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


def update_paperless_title(item: dict[str, Any]) -> None:
    """
    Minimal safe Paperless update.

    Currently only the title is updated, because Paperless tags,
    correspondents and document types require ID mapping.
    """
    paperless_id = item.get("paperless_id")
    title = item.get("title")

    if not paperless_id:
        raise ValueError("Missing paperless_id")

    if not title:
        raise ValueError("Missing title")

    client = PaperlessClient()
    client.update_document(
        document_id=int(paperless_id),
        payload={"title": title},
    )


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
    apply_to_paperless: bool = Form(default=False),
):
    item = get_item(item_id)

    if item["status"] not in {STATUS_NEEDS_REVIEW, STATUS_DRY_RUN}:
        raise HTTPException(
            status_code=400,
            detail="Only NEEDS_REVIEW and DRY_RUN items can be approved",
        )

    if apply_to_paperless:
        update_paperless_title(item)

    update_item_status(
        item_id=item_id,
        status=STATUS_DONE,
        error_message=(
            "Approved via Review UI"
            if not apply_to_paperless
            else "Approved via Review UI and applied to Paperless"
        ),
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
