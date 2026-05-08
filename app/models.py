"""
Pydantic models used across the application.

Contains structured validation models for
LLM classification output.
"""

from typing import List

from pydantic import BaseModel
from pydantic import Field


class ClassificationResult(BaseModel):
    """
    Structured document classification result.
    Returned by Ollama after document analysis.
    """

    document_type: str = "Sonstiges"
    correspondent: str = "Unbekannt"
    title: str = "Unbenanntes Dokument"
    tags: List[str] = Field(
        default_factory=list
    )

    confidence: float = 0.5