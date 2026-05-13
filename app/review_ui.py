"""FastAPI Review UI for AI Documents."""

import json
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import (
    Database,
    FAILED_STATUSES,
    REVIEW_STATUSES,
    STATUS_DONE,
    STATUS_DRY_RUN,
    STATUS_IGNORED,
    STATUS_NEEDS_REVIEW,
)
from app.paperless_client import PaperlessClient
from app.reprocess import reprocess_paperless_document, retry_failed_document


app = FastAPI(title="AI Documents Review UI")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def get_db() -> Database:
    return Database(settings.db_path)


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
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


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
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.60:
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
    return item


def normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for raw in items if (item := normalize_item(raw)) is not None]


def get_item_or_404(document_db_id: int) -> dict[str, Any]:
    item = normalize_item(get_db().get_document_row(document_db_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item


@app.get("/")
def dashboard(request: Request):
    db = get_db()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "counts": db.dashboard_counts(),
            "recent": normalize_items(db.recent_documents(limit=12)),
        },
    )


@app.get("/review")
def review_queue(request: Request, status: str | None = None):
    db = get_db()
    items = db.list_by_statuses((status,), limit=100) if status else db.list_by_statuses(REVIEW_STATUSES, limit=100)
    return templates.TemplateResponse(
        "review_list.html",
        {
            "request": request,
            "items": normalize_items(items),
            "selected_status": status,
            "status_needs_review": STATUS_NEEDS_REVIEW,
            "status_dry_run": STATUS_DRY_RUN,
        },
    )


@app.get("/failed")
def failed_queue(request: Request):
    items = normalize_items(get_db().list_by_statuses(FAILED_STATUSES, limit=100))
    return templates.TemplateResponse("failed_list.html", {"request": request, "items": items})


@app.get("/items/{item_id}")
def detail(request: Request, item_id: int):
    return templates.TemplateResponse(
        "review_detail.html",
        {
            "request": request,
            "item": get_item_or_404(item_id),
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
    db = get_db()
    item = get_item_or_404(item_id)
    if item["status"] not in {STATUS_NEEDS_REVIEW, STATUS_DRY_RUN}:
        raise HTTPException(status_code=400, detail="Only review items can be approved")

    clean_title = title.strip()
    clean_correspondent = correspondent.strip()
    clean_document_type = document_type.strip()
    tag_list = parse_tags(tags)
    if not clean_title:
        raise HTTPException(status_code=400, detail="Title must not be empty")

    db.update_document_values(item_id, clean_title, clean_correspondent, clean_document_type, tag_list)
    message = "Approved via Review UI"

    if apply_to_paperless:
        payload = PaperlessClient().update_document_metadata_by_names(
            document_id=int(item["paperless_id"]),
            title=clean_title,
            correspondent=clean_correspondent,
            document_type=clean_document_type,
            tags=tag_list,
        )
        message = f"Approved via Review UI and applied to Paperless: {payload}"

    db.insert_review_decision(
        document_db_id=item_id,
        paperless_id=int(item["paperless_id"]),
        action="approved",
        original_ai_title=item.get("title"),
        original_ai_correspondent=item.get("correspondent"),
        original_ai_document_type=item.get("document_type"),
        original_ai_tags=item.get("tags_list") or [],
        final_title=clean_title,
        final_correspondent=clean_correspondent,
        final_document_type=clean_document_type,
        final_tags=tag_list,
    )
    db.update_status(item_id, STATUS_DONE, message)
    return RedirectResponse("/review", status_code=303)


@app.post("/items/{item_id}/reject")
def reject(item_id: int, reason: str = Form(default="Manuell abgelehnt")):
    db = get_db()
    item = get_item_or_404(item_id)
    if item["status"] not in {STATUS_NEEDS_REVIEW, STATUS_DRY_RUN}:
        raise HTTPException(status_code=400, detail="Only review items can be rejected")

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
    db.update_status(item_id, STATUS_NEEDS_REVIEW, f"Rejected via Review UI: {reason}")
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/ignore")
def ignore_failed(item_id: int):
    db = get_db()
    item = get_item_or_404(item_id)
    if item["status"] not in FAILED_STATUSES:
        raise HTTPException(status_code=400, detail="Only FAILED items can be ignored")
    db.update_status(item_id, STATUS_IGNORED, "Ignored via Review UI")
    return RedirectResponse("/failed", status_code=303)


@app.post("/items/{item_id}/retry")
def retry_failed(item_id: int):
    item = get_item_or_404(item_id)
    if item["status"] not in FAILED_STATUSES:
        raise HTTPException(status_code=400, detail="Only FAILED items can be retried")
    retry_failed_document(item_id)
    return RedirectResponse("/failed", status_code=303)


@app.get("/reprocess")
def reprocess_form(request: Request):
    return templates.TemplateResponse("reprocess.html", {"request": request, "result": None, "error": None})


@app.post("/reprocess")
def reprocess_submit(request: Request, paperless_id: int = Form(...)):
    try:
        result = reprocess_paperless_document(int(paperless_id))
        return templates.TemplateResponse(
            "reprocess.html",
            {"request": request, "result": f"Paperless-ID {paperless_id} verarbeitet: {result}", "error": None},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "reprocess.html",
            {"request": request, "result": None, "error": str(exc)},
            status_code=500,
        )


@app.get("/learning")
def learning(request: Request):
    decisions = get_db().learning_summary(limit=50)
    return templates.TemplateResponse("learning.html", {"request": request, "decisions": decisions})


@app.get("/health")
def health():
    return {"status": "ok", "db_path": settings.db_path}
