"""
Pydantic models used across the application.

Contains structured validation models for LLM classification output.
"""

from typing import List

from pydantic import BaseModel
from pydantic import Field


class ClassificationResult(BaseModel):
    """Structured document classification result returned by Ollama."""

    document_type: str = "Sonstiges"
    correspondent: str = "Unbekannt"
    title: str = "Unbenanntes_Dokument"
    subject: str | None = None
    document_date: str | None = None
    amount: str | None = None
    tags: List[str] = Field(default_factory=list)
    confidence: float = 0.5
    reason: str | None = None
