"""Pydantic models used across the application.

The LLM extracts structured document metadata. The final Paperless title is
generated server-side in classifier.py so titles stay deterministic.
"""

from typing import List

from pydantic import BaseModel
from pydantic import Field


class ClassificationResult(BaseModel):
    """Structured document classification result returned by Ollama."""

    document_type: str = "Sonstiges"
    correspondent: str = "Unbekannt"

    # The LLM may suggest a title, but classifier.py overwrites it with a
    # deterministic title before Paperless is updated.
    title: str = "Unbenanntes_Dokument"

    subject: str | None = None
    document_date: str | None = None
    due_date: str | None = None
    service_period: str | None = None

    amount: str | None = None
    invoice_number: str | None = None
    customer_number: str | None = None
    contract_number: str | None = None

    tags: List[str] = Field(default_factory=list)

    confidence: float = 0.5
    reason: str | None = None
