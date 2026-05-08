"""
Central application configuration.

Loads environment variables from the .env file
and exposes strongly typed runtime settings.
"""

from dotenv import load_dotenv
from pydantic import BaseModel

import os


# Load .env file
load_dotenv()


class Settings(BaseModel):
    """
    Strongly typed application settings.
    """

    paperless_url: str = os.getenv(
        "PAPERLESS_URL",
        "",
    )

    paperless_token: str = os.getenv(
        "PAPERLESS_TOKEN",
        "",
    )

    ollama_model: str = os.getenv(
        "OLLAMA_MODEL",
        "qwen2.5:7b",
    )

    ollama_url: str = os.getenv(
        "OLLAMA_URL",
        "http://host.docker.internal:11434",
    )

    export_path: str = os.getenv(
        "EXPORT_PATH",
        "/exports",
    )

    poll_interval: int = int(
        os.getenv("POLL_INTERVAL", "30")
    )


# Global application settings instance
settings = Settings()