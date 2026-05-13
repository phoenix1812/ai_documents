"""Ollama client wrapper.

Responsible for:
- selecting relevant OCR context
- sending prompts
- retry handling
- parsing JSON responses
- normalizing LLM output into ClassificationResult
"""

from __future__ import annotations

import json
import logging
import re

import ollama
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_fixed

from app.config import settings
from app.models import ClassificationResult
from app.prompts import SYSTEM_PROMPT
from app.prompts import USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


KEYWORD_PATTERNS = (
    r"rechnung",
    r"rechnungsnummer",
    r"invoice",
    r"betrag",
    r"gesamtbetrag",
    r"summe",
    r"brutto",
    r"netto",
    r"mwst",
    r"umsatzsteuer",
    r"fällig",
    r"faellig",
    r"zahlbar",
    r"kundennummer",
    r"vertragsnummer",
    r"versicherungsnummer",
    r"policennummer",
    r"aktenzeichen",
    r"steuer",
    r"finanzamt",
    r"bescheid",
    r"vertrag",
    r"kündigung",
    r"kuendigung",
    r"iban",
    r"bic",
    r"kontoauszug",
    r"leistungszeitraum",
    r"zeitraum",
    r"datum",
)


def normalize_ocr_text(content: str) -> str:
    """Normalize OCR text without destroying useful line structure."""

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = []

    for line in content.split("\n"):
        clean_line = re.sub(r"[ \t]+", " ", line).strip()
        if clean_line:
            lines.append(clean_line)

    return "\n".join(lines)


def build_relevant_ocr_context(content: str, max_chars: int = 16000) -> str:
    """Build a useful OCR excerpt for classification.

    Instead of blindly sending content[:12000], keep:
    - the beginning, because sender and title are often there
    - the end, because totals, payment info and signatures are often there
    - lines containing important document keywords
    """

    text = normalize_ocr_text(content)

    if len(text) <= max_chars:
        return text

    head_size = max_chars // 3
    tail_size = max_chars // 3
    keyword_budget = max_chars - head_size - tail_size

    head = text[:head_size]
    tail = text[-tail_size:]

    keyword_regex = re.compile("|".join(KEYWORD_PATTERNS), re.IGNORECASE)
    keyword_lines = []

    for line in text.split("\n"):
        if keyword_regex.search(line):
            keyword_lines.append(line)

    keyword_block = "\n".join(keyword_lines)
    if len(keyword_block) > keyword_budget:
        keyword_block = keyword_block[:keyword_budget]

    parts = [
        "=== ANFANG DES DOKUMENTS ===",
        head,
        "=== RELEVANTE OCR-ZEILEN ===",
        keyword_block,
        "=== ENDE DES DOKUMENTS ===",
        tail,
    ]

    return "\n".join(part for part in parts if part)


def _as_optional_string(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "unbekannt"}:
        return None

    return text


def _as_tags(value: object) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        raw_tags = value
    elif isinstance(value, str):
        raw_tags = re.split(r"[,;]", value)
    else:
        return []

    tags: list[str] = []
    seen: set[str] = set()

    for raw_tag in raw_tags:
        tag = str(raw_tag).strip()
        if not tag:
            continue

        key = tag.lower()
        if key in seen:
            continue

        tags.append(tag)
        seen.add(key)

    return tags


def _coerce_float(value: object, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    if number < 0:
        return 0.0

    if number > 1:
        return 1.0

    return number


def _strip_code_fences(raw: str) -> str:
    """Handle models that still wrap JSON in markdown fences."""

    raw = raw.strip()

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()

    return raw


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

        selected_content = build_relevant_ocr_context(content)
        prompt = USER_PROMPT_TEMPLATE.format(content=selected_content)

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
            options={
                "temperature": 0,
            },
        )

        raw = response["message"]["content"]
        raw = _strip_code_fences(raw)

        logger.debug("RAW OLLAMA OUTPUT: %s", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Invalid JSON from Ollama. Output length: %s", len(raw))
            raise

        return ClassificationResult(
            document_type=str(data.get("document_type") or "Sonstiges").strip(),
            correspondent=str(data.get("correspondent") or "Unbekannt").strip(),
            title=str(data.get("title") or "Unbenanntes_Dokument").strip(),
            subject=_as_optional_string(data.get("subject")),
            document_date=_as_optional_string(data.get("document_date")),
            due_date=_as_optional_string(data.get("due_date")),
            service_period=_as_optional_string(data.get("service_period")),
            amount=_as_optional_string(data.get("amount")),
            invoice_number=_as_optional_string(data.get("invoice_number")),
            customer_number=_as_optional_string(data.get("customer_number")),
            contract_number=_as_optional_string(data.get("contract_number")),
            tags=_as_tags(data.get("tags")),
            confidence=_coerce_float(data.get("confidence"), default=0.5),
            reason=_as_optional_string(data.get("reason")),
        )
