"""
Ollama client wrapper.

Responsible for:
- sending prompts
- retry handling
- parsing JSON responses
- validating LLM output
"""

import json
import logging

import ollama
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_fixed

from app.config import settings
from app.models import ClassificationResult
from app.prompts import SYSTEM_PROMPT
from app.prompts import USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class OllamaClient:
    """Wrapper around Ollama chat API."""

    def __init__(self) -> None:
        self.client = ollama.Client(host=settings.ollama_url)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_fixed(2),
        reraise=True,
    )
    def classify(self, content: str) -> ClassificationResult:
        """Send OCR text to Ollama for classification."""

        prompt = USER_PROMPT_TEMPLATE.format(content=content[:12000])

        logger.info("Sending document to Ollama")

        response = self.client.chat(
            model=settings.ollama_model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            format="json",
        )

        raw = response["message"]["content"]

        logger.debug("RAW OLLAMA OUTPUT: %s", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Invalid JSON from Ollama. Output length: %s", len(raw))
            raise

        return ClassificationResult(
            document_type=data.get("document_type", "Sonstiges"),
            correspondent=data.get("correspondent", "Unbekannt"),
            title=data.get("title", "Unbenannt"),
            subject=data.get("subject"),
            document_date=data.get("document_date"),
            amount=data.get("amount"),
            tags=data.get("tags", []),
            confidence=data.get("confidence", 0.5),
            reason=data.get("reason"),
        )
