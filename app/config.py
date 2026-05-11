"""
Central configuration loader.

Reads all values from environment variables (.env).
"""

import os


class Settings:
    def __init__(self) -> None:
        # Paperless
        self.paperless_url = os.getenv(
            "PAPERLESS_URL",
            "http://localhost:8000",
        )

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
        self.export_path = os.getenv(
            "EXPORT_PATH",
            "/exports",
        )

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


settings = Settings()
