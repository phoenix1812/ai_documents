"""Hash helpers for duplicate detection."""

from __future__ import annotations

import hashlib
import re
import unicodedata


def sha256(data: bytes) -> str:
    """Return SHA256 for raw bytes."""
    return hashlib.sha256(data).hexdigest()


def normalize_ocr_text(content: str) -> str:
    """Normalize OCR text so the same recognized text hashes identically.

    Both duplicate levels compare hashes for exact equality. The PDF hash
    catches binary duplicates; the OCR hash catches documents whose PDF bytes
    differ but whose normalized text is character-for-character the same. A
    rescan of the same page produces different OCR text and is therefore not
    detected.
    """
    text = unicodedata.normalize("NFKC", content or "")
    text = text.lower()
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9äöüß€.,:;@/()\- ]", "", text)
    return text.strip()


def ocr_sha256(content: str) -> str:
    """Return SHA256 for normalized OCR text."""
    normalized = normalize_ocr_text(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
