"""
Central configuration loader.

All values are read from environment variables so the application can be
configured differently for local development, Docker Compose and production.
"""

import os


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        # Paperless
        self.paperless_url = os.getenv(
            "PAPERLESS_URL",
            "http://localhost:8000",
        )
        self.paperless_public_url = os.getenv(
            "PAPERLESS_PUBLIC_URL",
            self.paperless_url,
        ).rstrip("/")
        self.paperless_token = os.getenv(
            "PAPERLESS_TOKEN",
            "",
        )

        # Ollama
        self.ollama_model = os.getenv(
            "OLLAMA_MODEL",
            "llama3",
        )
        self.ollama_url = os.getenv(
            "OLLAMA_URL",
            "http://ollama:11434",
        )

        # Paths
        self.db_path = os.getenv(
            "DB_PATH",
            "/data",
        )

        # Classification
        self.confidence_threshold = float(
            os.getenv(
                "CONFIDENCE_THRESHOLD",
                "0.75",
            )
        )
        self.min_title_length = int(
            os.getenv(
                "MIN_TITLE_LENGTH",
                "8",
            )
        )

        # Safety
        # When enabled, the system stores the classification result in SQLite,
        # but does not write metadata back to Paperless.
        self.dry_run = os.getenv(
            "DRY_RUN",
            "false",
        ).lower() in {"1", "true", "yes", "on"}

        # Startup dependency check
        self.paperless_healthcheck_url = os.getenv(
            "PAPERLESS_HEALTHCHECK_URL",
            self.paperless_url,
        )

        # Event-driven trigger server
        self.trigger_port = int(
            os.getenv(
                "TRIGGER_PORT",
                "8080",
            )
        )

        # Review UI
        self.review_ui_port = int(
            os.getenv(
                "REVIEW_UI_PORT",
                "8090",
            )
        )


settings = Settings()
