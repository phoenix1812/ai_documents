from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseModel):
    paperless_url: str = os.getenv("PAPERLESS_URL", "")
    paperless_token: str = os.getenv("PAPERLESS_TOKEN", "")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    export_path: str = os.getenv("EXPORT_PATH", "./exports")
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "30"))


settings = Settings()