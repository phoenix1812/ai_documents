"""Health/readiness helpers for the AI worker."""
from __future__ import annotations
import requests
from app.config import settings
from app.queue_store import QueueStore


def health_payload(queue_store: QueueStore) -> dict:
    return {
        "status": "ok",
        "database": queue_store.db.integrity_check(),
        "queue": queue_store.snapshot(),
    }


def readiness_payload(queue_store: QueueStore) -> tuple[dict, int]:
    paperless_ok = False
    ollama_ok = False
    try:
        response = requests.get(settings.paperless_healthcheck_url, timeout=3)
        paperless_ok = response.status_code < 500
    except requests.RequestException:
        pass
    try:
        response = requests.get(f"{settings.ollama_url}/api/tags", timeout=3)
        ollama_ok = response.status_code < 500
    except requests.RequestException:
        pass
    db_ok = queue_store.db.integrity_check() == "ok"
    ready = paperless_ok and ollama_ok and db_ok
    return {
        "status": "ready" if ready else "not_ready",
        "paperless": "ok" if paperless_ok else "unavailable",
        "ollama": "ok" if ollama_ok else "unavailable",
        "database": "ok" if db_ok else "error",
        "queue": queue_store.snapshot(),
    }, 200 if ready else 503
