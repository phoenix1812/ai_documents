"""Hash helpers for duplicate detection."""

from __future__ import annotations

import hashlib
import re
import unicodedata


def sha256(data: bytes) -> str:
    """Return SHA256 for raw bytes."""
    return hashlib.sha256(data).hexdigest()


def normalize_ocr_text(content: str) -> str:
    """Normalize OCR text so visually identical scans produce similar hashes.

    The PDF hash catches exact binary duplicates. The OCR hash catches probable
    duplicates where the PDF bytes differ but the recognized text is effectively
    the same.
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
