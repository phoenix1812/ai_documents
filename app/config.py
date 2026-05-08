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
            "http://host.docker.internal:11434",
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

        # Worker
        self.poll_interval = int(
            os.getenv(
                "POLL_INTERVAL",
                "10",
            )
        )


settings = Settings()