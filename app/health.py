"""Health and readiness checks for the AI Documents worker."""

from __future__ import annotations

from typing import Any

import requests

from app.config import settings
from app.db import Database
from app.queue_store import PersistentQueueStore


def _http_check(url: str) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=settings.healthcheck_timeout_seconds)
        return {
            "status": "ok" if response.status_code < 400 else "error",
            "http_status": response.status_code,
        }
    except requests.RequestException as exc:
        return {"status": "error", "error": str(exc)}


def _ollama_check() -> dict[str, Any]:
    url = f"{settings.ollama_url.rstrip('/')}/api/tags"
    try:
        response = requests.get(url, timeout=settings.healthcheck_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        models = {str(item.get("name", "")) for item in payload.get("models", [])}
        expected = settings.ollama_model.strip()
        available = expected in models or f"{expected}:latest" in models
        return {
            "status": "ok" if available else "error",
            "http_status": response.status_code,
            "model": expected,
            "model_available": available,
            "models": sorted(models),
            **({} if available else {"error": "required model is not installed"}),
        }
    except (requests.RequestException, ValueError, TypeError) as exc:
        return {"status": "error", "error": str(exc), "model": settings.ollama_model}


def check_health() -> dict[str, Any]:
    # IMPORTANT: health checks must never perform queue recovery. A health
    # request can happen while a job is PROCESSING.
    db = Database(settings.db_path)
    queue_store = PersistentQueueStore(settings.db_path, recover_processing=False)

    try:
        paperless = _http_check(settings.paperless_healthcheck_url)
        ollama = _ollama_check()
        db_integrity = db.integrity_check()
        queue_integrity = queue_store.integrity_check()

        dependencies_ok = (
            paperless["status"] == "ok"
            and ollama["status"] == "ok"
            and db_integrity == "ok"
            and queue_integrity == "ok"
        )

        return {
            "status": "ok" if dependencies_ok else "degraded",
            "paperless": paperless,
            "ollama": ollama,
            "database": {
                "status": "ok" if db_integrity == "ok" else "error",
                "integrity": db_integrity,
                "path": str(settings.db_path),
            },
            "queue_database": {
                "status": "ok" if queue_integrity == "ok" else "error",
                "integrity": queue_integrity,
            },
        }
    finally:
        db.close()
