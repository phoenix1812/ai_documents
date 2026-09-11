"""Central configuration for the AI Documents worker."""
from __future__ import annotations
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.paperless_url = os.getenv("PAPERLESS_URL", "http://paperless:8000").rstrip("/")
        self.paperless_public_url = os.getenv("PAPERLESS_PUBLIC_URL", self.paperless_url).rstrip("/")
        self.paperless_token = os.getenv("PAPERLESS_TOKEN", "")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        self.db_path = os.getenv("DB_PATH", "/data")
        self.confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
        self.min_title_length = int(os.getenv("MIN_TITLE_LENGTH", "8"))
        self.dry_run = _bool("DRY_RUN", False)
        self.paperless_healthcheck_url = os.getenv("PAPERLESS_HEALTHCHECK_URL", self.paperless_url)
        self.trigger_port = int(os.getenv("TRIGGER_PORT", "8080"))
        self.review_ui_port = int(os.getenv("REVIEW_UI_PORT", "8090"))
        self.review_ui_username = os.getenv("REVIEW_UI_USERNAME", "")
        self.review_ui_password = os.getenv("REVIEW_UI_PASSWORD", "")
        self.queue_max_attempts = int(os.getenv("QUEUE_MAX_ATTEMPTS", "10"))
        self.queue_stale_after_seconds = int(os.getenv("QUEUE_STALE_AFTER_SECONDS", "900"))
        self.queue_poll_seconds = float(os.getenv("QUEUE_POLL_SECONDS", "1"))
        self.retry_base_seconds = int(os.getenv("RETRY_BASE_SECONDS", "30"))
        self.retry_max_seconds = int(os.getenv("RETRY_MAX_SECONDS", "900"))
        self.reconcile_enabled = _bool("RECONCILE_ENABLED", True)
        self.reconcile_interval_seconds = int(os.getenv("RECONCILE_INTERVAL_SECONDS", "600"))
        self.reconcile_initial_import = _bool("RECONCILE_INITIAL_IMPORT", False)
        self.reconcile_page_limit = int(os.getenv("RECONCILE_PAGE_LIMIT", "100"))
        self.backup_dir = os.getenv("BACKUP_DIR", "./backups")


settings = Settings()
