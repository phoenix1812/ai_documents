"""Central configuration loader."""

import os

TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in TRUE_VALUES


class Settings:
    def __init__(self) -> None:
        self.paperless_url = os.getenv("PAPERLESS_URL", "http://localhost:8000").rstrip("/")
        self.paperless_public_url = os.getenv(
            "PAPERLESS_PUBLIC_URL", self.paperless_url
        ).rstrip("/")
        self.paperless_token = os.getenv("PAPERLESS_TOKEN", "")
        self.ai_worker_trigger_url = os.getenv(
            "AI_WORKER_TRIGGER_URL", "http://ai-worker:8080/process"
        )

        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")

        # Directory containing documents.db.
        self.db_path = os.getenv("DB_PATH", "/data")

        self.confidence_threshold = float(
            os.getenv("CONFIDENCE_THRESHOLD", "0.75")
        )
        self.min_title_length = int(os.getenv("MIN_TITLE_LENGTH", "8"))

        self.dry_run = os.getenv("DRY_RUN", "false").lower() in {
            "1", "true", "yes", "on"
        }

        self.paperless_healthcheck_url = os.getenv(
            "PAPERLESS_HEALTHCHECK_URL", self.paperless_url
        )

        self.trigger_port = int(os.getenv("TRIGGER_PORT", "8080"))

        self.review_ui_port = int(os.getenv("REVIEW_UI_PORT", "8090"))
        self.review_ui_username = os.getenv("REVIEW_UI_USERNAME", "")
        self.review_ui_password = os.getenv("REVIEW_UI_PASSWORD", "")

        # Persistent queue.
        self.queue_poll_interval_seconds = int(
            os.getenv("QUEUE_POLL_INTERVAL_SECONDS", "2")
        )
        self.queue_max_attempts = int(
            os.getenv("QUEUE_MAX_ATTEMPTS", "10")
        )
        self.queue_retry_base_seconds = int(
            os.getenv("QUEUE_RETRY_BASE_SECONDS", "30")
        )
        self.queue_retry_max_seconds = int(
            os.getenv("QUEUE_RETRY_MAX_SECONDS", "1800")
        )

        # Paperless <-> AI database reconciliation.
        self.reconcile_enabled = _env_bool("RECONCILE_ENABLED", True)
        self.reconcile_initial_import = _env_bool("RECONCILE_INITIAL_IMPORT", False)
        self.reconciliation_interval_seconds = int(
            os.getenv("RECONCILIATION_INTERVAL_SECONDS", "600")
        )
        self.reconciliation_start_delay_seconds = int(
            os.getenv("RECONCILIATION_START_DELAY_SECONDS", "30")
        )

        # Health endpoint.
        self.healthcheck_timeout_seconds = int(
            os.getenv("HEALTHCHECK_TIMEOUT_SECONDS", "3")
        )


settings = Settings()
