"""Where the classification proposal comes from.

The pipeline in app/classifier.py refines, titles, validates and queues a
proposal; only this module depends on a model. PROPOSAL_SOURCE=rules drops the
model and keeps the rest byte for byte, including the review queue.

Measured over the operator's 76 approved documents: the sender lookup answers
65 of 76 correctly and never wrongly (the 11 misses are first-time senders, the
same ones a trained classifier cannot answer either), and his own approval
history gives a unique document type for 50 of 76. Everything not covered by
those two signals stays an explicit gap, so the validator routes the document to
the review UI instead of inventing a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol

from app.config import settings
from app.db import Database
from app.models import ClassificationResult
from app.paperless_client import PaperlessClient
from app.paperless_client import to_display_case


@dataclass(frozen=True)
class ProposalRequest:
    """Everything a proposer may look at, already fetched by the pipeline."""

    document_id: int
    content: str
    ocr_excerpt: str
    document: dict[str, Any]


class ProposalSource(Protocol):
    def classify(self, request: ProposalRequest) -> ClassificationResult: ...


class OllamaProposalSource:
    """The model-backed proposer: hands the raw OCR text to Ollama unchanged."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            # Imported here so a rules-only deployment never needs the package.
            from app.ollama_client import OllamaClient

            client = OllamaClient()
        self.client = client

    def classify(self, request: ProposalRequest) -> ClassificationResult:
        return self.client.classify(request.content)


class RulesProposalSource:
    """Proposal from his own Paperless records: sender list and approval history."""

    def __init__(self, paperless: PaperlessClient, db: Database) -> None:
        self.paperless = paperless
        self.db = db

    def classify(self, request: ProposalRequest) -> ClassificationResult:
        correspondent = self.paperless.correspondent_from_text(request.ocr_excerpt)
        if correspondent:
            correspondent = to_display_case(
                self.paperless.resolve_correspondent_name(correspondent)
                or correspondent
            )

        document_type, support, distinct_types = self.db.type_kernel(correspondent)
        document_date = self._title_date(request)

        # A field he has no evidence for stays at the model default, which the
        # validator knows as a placeholder - so the document lands in the review
        # UI with an empty proposal instead of a guessed one.
        proposed: dict[str, Any] = {"tags": []}
        if correspondent:
            proposed["correspondent"] = correspondent
        if document_type:
            proposed["document_type"] = document_type
        if document_date:
            proposed["document_date"] = document_date

        confidence = self._confidence(correspondent, document_type)
        if confidence is not None:
            proposed["confidence"] = confidence

        proposed["reason"] = self._reason(
            correspondent, document_type, support, distinct_types
        )
        return ClassificationResult(**proposed)

    def _title_date(self, request: ProposalRequest) -> str | None:
        if settings.proposal_date_source != "paperless_created":
            return None

        # Paperless parsed a date while consuming and returns it as ISO date, so
        # the title keeps its date component without a model reading the letter.
        created = request.document.get("created")
        if not created:
            return None

        return str(created).strip() or None

    def _confidence(
        self, correspondent: str | None, document_type: str | None
    ) -> float | None:
        if correspondent and document_type:
            return settings.rules_confidence_matching

        if correspondent or document_type:
            return settings.rules_confidence_partial

        # Nothing found: keep the ClassificationResult default, which is below
        # CONFIDENCE_THRESHOLD and therefore a review case.
        return None

    @staticmethod
    def _reason(
        correspondent: str | None,
        document_type: str | None,
        support: int,
        distinct_types: int,
    ) -> str:
        parts = ["Regeln statt Modell"]
        parts.append(
            f"Absender aus deinem Bestand: {correspondent}"
            if correspondent
            else "Absender offen - Erstkontakt mit diesem Sender"
        )
        if document_type:
            parts.append(f"Typ aus deinen Freigaben: {document_type} ({support} Belege)")
        elif distinct_types > 1:
            parts.append(f"Typ offen - du hast {distinct_types} Typen fuer diesen Sender freigegeben")
        else:
            parts.append("Typ offen - keine Freigabe fuer diesen Sender")

        return " | ".join(parts)


def build_proposal_source(paperless: PaperlessClient, db: Database) -> ProposalSource:
    name = settings.proposal_source

    if name == "rules":
        return RulesProposalSource(paperless, db)

    if name == "ollama":
        return OllamaProposalSource()

    raise ValueError(
        f"Unknown PROPOSAL_SOURCE {name!r}: expected 'ollama' or 'rules'."
    )
