from pydantic import BaseModel, Field
from typing import List


class ClassificationResult(BaseModel):
    document_type: str = "Sonstiges"
    correspondent: str = "Unbekannt"
    title: str = "Unbenanntes Dokument"
    tags: List[str] = Field(default_factory=list)
    confidence: float = 0.5