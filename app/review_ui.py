"""
FastAPI Review UI for AI Documents.

Includes:
- dashboard
- review queue
- failed queue
- all documents / audit view
- editing approved documents
- manual reprocess
- review learning
"""

import json
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import (
    APPROVED_STATUSES,
    Database,
    FAILED_STATUSES,
    REVIEW_STATUSES,
    STATUS_AUTO_APPROVED,
    STATUS_DONE,
    STATUS_DRY_RUN,
    STATUS_IGNORED,
    STATUS_MANUALLY_APPROVED,
    STATUS_NEEDS_REVIEW,
    STATUS_REVIEW_REQUIRED,
)
from app.paperless_client import PaperlessClient
from app.reprocess import reprocess_paperless_document, retry_failed_document


app = FastAPI(title="AI Documents Review UI")

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


ALL_STATUS_FILTERS = (
    STATUS_AUTO_APPROVED,
    STATUS_MANUALLY_APPROVED,
    STATUS_DONE,
    STATUS_NEEDS_REVIEW,
    STATUS_REVIEW_REQUIRED,
    STATUS_DRY_RUN,
    *FAILED_STATUSES,
    STATUS_IGNORED,
)


def get_db() -> Database:
    return Database(settings.db_path)


def parse_tags(value: Any) -> list[str]:
    return Database.parse_json_list(value)


def format_confidence(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.0f} %"
    except (TypeError, ValueError):
        return "—"


def confidence_class(value: Any) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return "unknown"

    if confidence >= 0.90:
        return "high"
    if confidence >= 0.70:
        return "medium"
    return "low"


def normalize_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None

    item = dict(item)
    item["tags_list"] = parse_tags(item.get("tags"))
    item["tags_display"] = ", ".join(item["tags_list"])
    item["confidence_display"] = format_confidence(item.get("confidence"))
    item["confidence_class"] = confidence_class(item.get("confidence"))
    item["is_editable"] = item.get("status") in {
        STATUS_AUTO_APPROVED,
        STATUS_MANUALLY_APPROVED,
        STATUS_DONE,
        STATUS_NEEDS_REVIEW,
        STATUS_REVIEW_REQUIRED,
        STATUS_DRY_RUN,
    }
    return item


def normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for raw in items if (item := normalize_item(raw)) is not None]


def get_item_or_404(document_db_id: int) -> dict[str, Any]:
    item = normalize_item(get_db().get_document_row(document_db_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return item


def save_correction(
    item_id: int,
    item: dict[str, Any],
    clean_title: str,
    clean_correspondent: str,
    clean_document_type: str,
    tag_list: list[str],
    action: str,
    reason: str | None = None,
) -> None:
    db = get_db()
    db.insert_review_decision(
        document_db_id=item_id,
        paperless_id=int(item["paperless_id"]),
        action=action,
        original_ai_title=item.get("title"),
        original_ai_correspondent=item.get("correspondent"),
        original_ai_document_type=item.get("document_type"),
        original_ai_tags=item.get("tags_list") or [],
        final_title=clean_title,
        final_correspondent=clean_correspondent,
        final_document_type=clean_document_type,
        final_tags=tag_list,
        reason=reason,
    )


@app.get("/")
def dashboard(request: Request):
    db = get_db()
    counts = db.dashboard_counts()
    recent = normalize_items(db.recent_documents(limit=12))

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "counts": counts,
            "recent": recent,
        },
    )


@app.get("/documents")
def documents(
    request: Request,
    status: str | None = None,
    q: str | None = None,
):
    db = get_db()
    items = normalize_items(
        db.list_documents(
            status=status,
            query=q,
            limit=250,
        )
    )

    return templates.TemplateResponse(
        "documents.html",
        {
            "request": request,
            "items": items,
            "selected_status": status,
            "query": q or "",
            "status_filters": ALL_STATUS_FILTERS,
        },
    )


@app.get("/review")
def review_queue(request: Request, status: str | None = None):
    db = get_db()

    if status:
        items = db.list_by_statuses((status,), limit=100)
    else:
        items = db.list_by_statuses(REVIEW_STATUSES, limit=100)

    return templates.TemplateResponse(
        "review_list.html",
        {
            "request": request,
            "items": normalize_items(items),
            "selected_status": status,
            "status_needs_review": STATUS_NEEDS_REVIEW,
            "status_review_required": STATUS_REVIEW_REQUIRED,
            "status_dry_run": STATUS_DRY_RUN,
        },
    )


@app.get("/auto-approved")
def auto_approved(request: Request):
    db = get_db()
    items = normalize_items(
        db.list_by_statuses((STATUS_AUTO_APPROVED,), limit=100)
    )

    return templates.TemplateResponse(
        "documents.html",
        {
            "request": request,
            "items": items,
            "selected_status": STATUS_AUTO_APPROVED,
            "query": "",
            "status_filters": ALL_STATUS_FILTERS,
            "headline": "Letzte Auto-Approvals",
            "subline": "Hier kannst du automatisch freigegebene Dokumente nachträglich prüfen und korrigieren.",
        },
    )


@app.get("/failed")
def failed_queue(request: Request):
    db = get_db()
    items = normalize_items(db.list_by_statuses(FAILED_STATUSES, limit=100))

    return templates.TemplateResponse(
        "failed_list.html",
        {
            "request": request,
            "items": items,
        },
    )


@app.get("/items/{item_id}")
def detail(request: Request, item_id: int):
    item = get_item_or_404(item_id)

    return templates.TemplateResponse(
        "review_detail.html",
        {
            "request": request,
            "item": item,
            "approved_statuses": APPROVED_STATUSES,
            "review_statuses": REVIEW_STATUSES,
        },
    )


@app.post("/items/{item_id}/save")
def save_document(
    item_id: int,
    title: str = Form(...),
    correspondent: str = Form(""),
    document_type: str = Form(""),
    tags: str = Form(""),
    apply_to_paperless: bool = Form(default=False),
    correction_reason: str = Form(default="Manuelle Korrektur"),
):
    db = get_db()
    item = get_item_or_404(item_id)

    if not item["is_editable"]:
        raise HTTPException(
            status_code=400,
            detail="This document status is not editable",
        )

    clean_title = title.strip()
    clean_correspondent = correspondent.strip()
    clean_document_type = document_type.strip()
    tag_list = parse_tags(tags)

    if not clean_title:
        raise HTTPException(status_code=400, detail="Title must not be empty")

    db.update_document_values(
        document_db_id=item_id,
        title=clean_title,
        correspondent=clean_correspondent,
        document_type=clean_document_type,
        tags=tag_list,
    )

    message = "Saved via Review UI"

    if apply_to_paperless:
        client = PaperlessClient()
        payload = client.update_document_metadata_by_names(
            document_id=int(item["paperless_id"]),
            title=clean_title,
            correspondent=clean_correspondent,
            document_type=clean_document_type,
            tags=tag_list,
        )
        message = f"Saved via Review UI and applied to Paperless: {payload}"

    action = (
        "corrected_auto_approved"
        if item.get("status") == STATUS_AUTO_APPROVED
        else "saved"
    )

    save_correction(
        item_id=item_id,
        item=item,
        clean_title=clean_title,
        clean_correspondent=clean_correspondent,
        clean_document_type=clean_document_type,
        tag_list=tag_list,
        action=action,
        reason=correction_reason,
    )

    db.update_status(
        document_db_id=item_id,
        status=STATUS_MANUALLY_APPROVED,
        error_message=message,
    )

    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/approve")
def approve(
    item_id: int,
    title: str = Form(...),
    correspondent: str = Form(""),
    document_type: str = Form(""),
    tags: str = Form(""),
    apply_to_paperless: bool = Form(default=False),
):
    return save_document(
        item_id=item_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        apply_to_paperless=apply_to_paperless,
        correction_reason="Manuell freigegeben",
    )


@app.post("/items/{item_id}/reject")
def reject(
    item_id: int,
    reason: str = Form(default="Manuell abgelehnt"),
):
    db = get_db()
    item = get_item_or_404(item_id)

    if item["status"] not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Only review items can be rejected",
        )

    db.insert_review_decision(
        document_db_id=item_id,
        paperless_id=int(item["paperless_id"]),
        action="rejected",
        original_ai_title=item.get("title"),
        original_ai_correspondent=item.get("correspondent"),
        original_ai_document_type=item.get("document_type"),
        original_ai_tags=item.get("tags_list") or [],
        final_title=None,
        final_correspondent=None,
        final_document_type=None,
        final_tags=None,
        reason=reason,
    )

    db.update_status(
        document_db_id=item_id,
        status=STATUS_REVIEW_REQUIRED,
        error_message=f"Rejected via Review UI: {reason}",
    )

    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/ignore")
def ignore_failed(item_id: int):
    db = get_db()
    item = get_item_or_404(item_id)

    if item["status"] not in FAILED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Only FAILED items can be ignored",
        )

    db.update_status(
        document_db_id=item_id,
        status=STATUS_IGNORED,
        error_message="Ignored via Review UI",
    )

    return RedirectResponse("/failed", status_code=303)


@app.post("/items/{item_id}/retry")
def retry_failed(item_id: int):
    item = get_item_or_404(item_id)

    if item["status"] not in FAILED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Only FAILED items can be retried",
        )

    retry_failed_document(item_id)
    return RedirectResponse("/failed", status_code=303)


@app.get("/reprocess")
def reprocess_form(request: Request):
    return templates.TemplateResponse(
        "reprocess.html",
        {
            "request": request,
            "result": None,
            "error": None,
        },
    )


@app.post("/reprocess")
def reprocess_submit(
    request: Request,
    paperless_id: int = Form(...),
):
    try:
        result = reprocess_paperless_document(int(paperless_id))
        return templates.TemplateResponse(
            "reprocess.html",
            {
                "request": request,
                "result": f"Paperless-ID {paperless_id} verarbeitet: {result}",
                "error": None,
            },
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "reprocess.html",
            {
                "request": request,
                "result": None,
                "error": str(exc),
            },
            status_code=500,
        )


@app.get("/learning")
def learning(request: Request):
    db = get_db()
    decisions = db.learning_summary(limit=50)

    return templates.TemplateResponse(
        "learning.html",
        {
            "request": request,
            "decisions": decisions,
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "db_path": settings.db_path}
