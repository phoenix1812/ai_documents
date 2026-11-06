"""
Paperless-ngx REST API client.

Responsible for:
- loading documents
- downloading PDFs
- updating metadata
- resolving names to Paperless IDs
- creating missing tags, document types and correspondents
- marking a detected duplicate with a tag and a note about its original
"""

from __future__ import annotations

import re
from typing import Any

import requests

from app.config import settings

DUPLICATE_TAG_NAME = "Duplikat"

# Below this length a name is too generic to be matched by containment: "AXA"
# would happily swallow "AXA Krankenversicherung AG" and "Kasse" everything.
MIN_CONTAINMENT_MATCH_CHARS = 6

# How far into the document the sender lookup reads. A letterhead is at the top;
# below this window a known name is more likely the recipient, a utility
# reference or, as on paperless 90, "Messstellenbetreiber: NEW Netz GmbH" - a
# third party that would overwrite the real issuer.
SENDER_HEAD_CHARS = 300


def normalize_name(value: str | None) -> str:
    """Case- and punctuation-insensitive form used to compare Paperless names."""

    return re.sub(r"[^0-9a-zäöüß]+", " ", (value or "").casefold()).strip()


VOWEL_RE = re.compile(r"[aeiouäöüéèêàù]", re.IGNORECASE)


def to_display_case(name: str | None) -> str:
    """Turn a shouted sender name into initial-capitals form.

    German letterheads set whole company names in capitals and a 4B model copies
    that, which produced "MANN GEBÄUDETECHNIK" next to the real "Mann
    Gebäudetechnik GmbH". A name containing any lowercase letter keeps its
    spelling: that is the issuer's own styling, as in "ALTE LEIPZIGER
    Versicherung Aktiengesellschaft". Tokens without a vowel and single letters
    stay uppercase because they are abbreviations (BKK, AG, "a.G.").

    Only spellings that do not exist in Paperless yet reach this form - an
    established one is picked earlier by resolve_existing_name, which compares
    case-insensitively.
    """

    value = (name or "").strip()
    letters = [char for char in value if char.isalpha()]
    if not letters or not all(char.isupper() for char in letters):
        return value

    def capitalize_token(match: re.Match[str]) -> str:
        token = match.group(0)
        if len(token) == 1 or not VOWEL_RE.search(token):
            return token
        return token[0] + token[1:].lower()

    return re.sub(r"\w+", capitalize_token, value)


def resolve_existing_name(
    wanted: str,
    existing: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Pick the established spelling for a sender the model named imprecisely.

    A 4B model writes the same issuer in several spellings, and every new
    spelling became a new correspondent in Paperless: the archive now holds
    both "Finanzamt" and "Finanzamt Erkelenz", both "MANN GEBÄUDETECHNIK" and
    "Mann Gebäudetechnik GmbH". The operator's recorded corrections are exactly
    this cleanup, so before creating a name the existing ones are searched for
    an equal or containing spelling and the one with the most documents wins.
    Ambiguous candidates are refused instead of guessed.
    """

    target = normalize_name(wanted)
    if not target:
        return None

    def matches(item: dict[str, Any]) -> bool:
        other = normalize_name(item.get("name"))
        if not other:
            return False
        if other == target:
            return True
        # Only the vague-to-specific direction: the model naming "Finanzamt"
        # stands for the existing "Finanzamt Erkelenz". The reverse - a name
        # more specific than anything on record - is treated as a genuinely new
        # correspondent, because merging it into the shorter existing one would
        # put documents under the wrong sender.
        if len(target) < MIN_CONTAINMENT_MATCH_CHARS:
            return False
        return re.search(rf"(^| ){re.escape(target)}( |$)", other) is not None

    candidates = [item for item in existing if matches(item)]
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: int(item.get("document_count") or 0),
        reverse=True,
    )

    if len(candidates) > 1:
        best = int(candidates[0].get("document_count") or 0)
        runner_up = int(candidates[1].get("document_count") or 0)
        if best == runner_up:
            return None

    return candidates[0]


DUPLICATE_REASON_LABELS = {
    "file_hash": "identische PDF-Datei",
    "ocr_hash": "identischer OCR-Text",
}


def format_duplicate_note(
    original_id: int,
    original_title: str | None,
    duplicate_reason: str,
) -> str:
    """Build the Paperless note that points a duplicate at its original."""

    reason = DUPLICATE_REASON_LABELS.get(duplicate_reason, duplicate_reason)
    title = (original_title or "").strip()

    if title:
        return (
            f"Duplikat von #{original_id} ({title}): {reason}. "
            "Dieses Dokument wurde nicht klassifiziert."
        )

    return (
        f"Duplikat von #{original_id}: {reason}. "
        "Dieses Dokument wurde nicht klassifiziert."
    )


class PaperlessClient:
    """Client wrapper for the Paperless API."""

    def __init__(self) -> None:
        self.base_url = settings.paperless_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {settings.paperless_token}",
            "Content-Type": "application/json",
        }
        # The question layer only reads, so it runs on a token that cannot write.
        # Without one it falls back to the worker token and the page says so: a
        # surface that silently used the write credential would be the one thing
        # D3 was meant to rule out.
        self.readonly_token = settings.paperless_token_readonly or settings.paperless_token
        self.readonly_headers = {
            "Authorization": f"Token {self.readonly_token}",
            "Content-Type": "application/json",
        }
        self.uses_readonly_token = bool(settings.paperless_token_readonly)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get_paginated(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Load all results from a paginated Paperless endpoint."""
        url = self._url(path)
        results: list[dict[str, Any]] = []

        while url:
            response = requests.get(
                url,
                headers=headers or self.headers,
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            # Paperless usually returns paginated objects.
            if isinstance(data, dict) and "results" in data:
                results.extend(data["results"])
                url = data.get("next")
                params = None
            elif isinstance(data, list):
                results.extend(data)
                url = ""
            else:
                raise ValueError(f"Unexpected Paperless response for {path}: {data!r}")

        return results

    def _find_by_name(self, path: str, name: str) -> dict[str, Any] | None:
        """Find one Paperless object by exact case-insensitive name."""
        clean_name = name.strip()
        if not clean_name:
            return None

        candidates = self._get_paginated(
            path,
            params={"search": clean_name},
        )

        for item in candidates:
            if item.get("name", "").strip().lower() == clean_name.lower():
                return item

        return None

    def _create_named_object(self, path: str, name: str) -> dict[str, Any]:
        """Create a Paperless object with a name."""
        response = requests.post(
            self._url(path),
            headers=self.headers,
            json={"name": name.strip()},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _get_or_create_named_id(self, path: str, name: str) -> int | None:
        """Return existing ID for name or create a new object."""
        clean_name = name.strip()
        if not clean_name:
            return None

        existing = self._find_by_name(path, clean_name)
        if existing:
            return int(existing["id"])

        created = self._create_named_object(path, clean_name)
        return int(created["id"])

    def get_or_create_tag_id(self, name: str) -> int | None:
        return self._get_or_create_named_id("/api/tags/", name)

    def unknown_tag_names(self, names: list[str]) -> list[str]:
        """Tags the model proposed that Paperless does not carry under that name.

        Compared by exact normalized name, without containment: tag names are
        short, and "Heizung" inside "Heizungsbau" would silently merge two
        subjects. An unknown name is his decision, not something the worker
        should create on its own.
        """

        existing = {normalize_name(item.get("name")) for item in self._get_paginated("/api/tags/")}
        return [name for name in names if normalize_name(name) not in existing]

    def correspondent_from_text(self, text: str) -> str | None:
        """The correspondent Paperless already carries, if the document head names exactly one.

        Reading the sender off a letterhead is the field this model keeps failing:
        from "Hans-Peter Schiffer-Kueppers, Schornsteinfegermeister, Katharinenstr.
        23, 41836 Hueckelhoven" it returns the address fragment, and because the tag
        kernel is keyed on that string the whole rule chain stops. His senders are a
        closed list and their names are printed in the documents, so the lookup
        replaces the guess. Several known senders in one document stay the model's
        decision: measured on his archive, matching the earliest name was wrong on 15
        of 60 documents while requiring exactly one match was wrong on none.

        Only the head is read, because a name further down is usually someone else:
        on paperless 90 the sole listed name in the whole page was
        "Messstellenbetreiber: NEW Netz GmbH" at character 2135, and the rule
        overwrote the real issuer with it. Measured over 65 documents, cutting at
        ``SENDER_HEAD_CHARS`` keeps every hit the rules chain actually needed and
        drops only three, each of which the model had already answered correctly.
        """

        haystack = normalize_name(text[:SENDER_HEAD_CHARS])
        if not haystack:
            return None

        hits = {
            name
            for name in (
                (item.get("name") or "").strip()
                for item in self._get_paginated("/api/correspondents/")
            )
            if len(normalize_name(name)) >= MIN_CONTAINMENT_MATCH_CHARS
            and normalize_name(name) in haystack
        }
        return hits.pop() if len(hits) == 1 else None

    def resolve_correspondent_name(self, name: str) -> str | None:
        """The spelling Paperless already uses for this sender, if it has one.

        A 4B model copies whatever the OCR shows on the letterhead, so one issuer
        arrives as "WEP Wärme-, Energie- und Prozesstechnik GmbH" and the next
        time as the lowercase fragment "wärme-, energie- und prozesstechnik gmbh"
        that sits behind "WEP GmbH" in the scan (paperless 90 against 92). Kept
        as the model wrote it, that fragment costs three things: a second
        correspondent in Paperless, a second title, and - because the tag kernel
        is keyed on the sender - a rule he has already confirmed going quiet.
        The lookup hands back the established name before any of those consumers
        see the guess. It is the same routine the write path uses, moved earlier;
        ambiguous and merely-shorter names still return None.
        """

        clean_name = (name or "").strip()
        if not clean_name:
            return None

        match = resolve_existing_name(clean_name, self._get_paginated("/api/correspondents/"))
        if match is None:
            return None

        return (match.get("name") or "").strip() or None

    def get_or_create_document_type_id(self, name: str) -> int | None:
        return self._get_or_create_named_id("/api/document_types/", name)

    def get_or_create_correspondent_id(self, name: str) -> int | None:
        """Return the correspondent ID for a name the model may have invented."""

        clean_name = name.strip()
        if not clean_name:
            return None

        match = resolve_existing_name(clean_name, self._get_paginated("/api/correspondents/"))
        if match is not None:
            return int(match["id"])

        return self._get_or_create_named_id("/api/correspondents/", to_display_case(clean_name))

    def get_documents(self) -> list[dict[str, Any]]:
        """Load all available documents."""
        return self._get_paginated("/api/documents/")

    def count_documents(self) -> int:
        """How many documents the archive holds, on one read-only page of size 1.

        The question layer weights a term by how rare it is, so it needs the
        size of the whole archive rather than the size of one result page.
        """
        response = requests.get(
            self._url("/api/documents/"),
            headers=self.readonly_headers,
            params={"page_size": 1},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return int(data.get("count") or 0) if isinstance(data, dict) else len(data)

    def list_correspondents(self) -> list[dict[str, Any]]:
        """Every sender name in the archive, with its id, on the read-only token."""
        return self._get_paginated("/api/correspondents/", headers=self.readonly_headers)

    def search_documents(
        self,
        term: str,
        *,
        correspondent_id: int | None = None,
        created_gte: str | None = None,
        created_lte: str | None = None,
        page_size: int = 30,
    ) -> list[dict[str, Any]]:
        """One read-only search page, GET only.

        Measured against the live API on 2026-11-04: `created__gte` and
        `created__lte` do filter, but on the intake date, and `after`/`before` do
        nothing at all in 3.3.1. A term is therefore searched as it is, without
        this method inventing a period it cannot honour."""
        params: dict[str, Any] = {"query": term, "page_size": page_size}
        if correspondent_id is not None:
            params["correspondent__id"] = correspondent_id
        if created_gte:
            params["created__gte"] = created_gte
        if created_lte:
            params["created__lte"] = created_lte

        response = requests.get(
            self._url("/api/documents/"),
            headers=self.readonly_headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return data.get("results") or []
        return data

    def read_document(self, document_id: int) -> dict[str, Any]:
        """One document with its fulltext, on the read-only credential."""
        response = requests.get(
            self._url(f"/api/documents/{document_id}/"),
            headers=self.readonly_headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def ensure_custom_field(self, name: str, data_type: str) -> int:
        """Return the ID of a custom field, creating it on first use.

        The field belongs to the archive, not to one document, so it is looked up
        by exact name before anything is created.
        """
        existing = self._find_by_name("/api/custom_fields/", name)
        if existing:
            return int(existing["id"])

        response = requests.post(
            self._url("/api/custom_fields/"),
            headers=self.headers,
            json={"name": name.strip(), "data_type": data_type},
            timeout=30,
        )
        response.raise_for_status()
        return int(response.json()["id"])

    def set_custom_field(
        self,
        document_id: int,
        name: str,
        data_type: str,
        value: str,
    ) -> dict[str, Any]:
        """Write one custom field value, keeping every other field on the document.

        The PATCH sends the merged list because Paperless treats it as the whole
        truth: drf_writable_nested deletes every instance that is missing from it
        (``delete_reverse_relations_if_need``), so sending only the new value
        would silently drop the rest.

        A document that already carries this exact value is left untouched, which
        keeps a reprocess from writing to Paperless for nothing.
        """
        field_id = self.ensure_custom_field(name, data_type)

        current = [
            dict(entry) for entry in (self.get_document(document_id).get("custom_fields") or [])
        ]
        for entry in current:
            if int(entry.get("field") or 0) == field_id:
                if str(entry.get("value") or "") == value:
                    return {"field": name, "value": value, "written": False}
                entry["value"] = value
                break
        else:
            current.append({"field": field_id, "value": value})

        self.update_document(
            document_id=document_id,
            payload={"custom_fields": current},
        )
        return {"field": name, "value": value, "written": True}

    def get_document(self, document_id: int) -> dict[str, Any]:
        """Load a single document."""
        response = requests.get(
            self._url(f"/api/documents/{document_id}/"),
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def update_document(
        self,
        document_id: int,
        payload: dict[str, Any],
    ) -> None:
        """Update document metadata."""
        response = requests.patch(
            self._url(f"/api/documents/{document_id}/"),
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

    def delete_document(self, document_id: int) -> str:
        """Delete the document itself in Paperless.

        A document that is already gone is reported instead of raising: the caller
        still wants its own row removed. Every other failure raises, because a
        Paperless document without a row here would be re-queued as new by the
        reconciler (app/reconcile_missing.py).
        """
        response = requests.delete(
            self._url(f"/api/documents/{document_id}/"),
            headers=self.headers,
            timeout=30,
        )

        if response.status_code == 404:
            return "bereits entfernt"

        response.raise_for_status()
        return "geloescht"

    def update_document_metadata_by_names(
        self,
        document_id: int,
        title: str,
        correspondent: str | None = None,
        document_type: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Update Paperless metadata using human-readable names.

        Paperless stores correspondent/document type/tags as IDs.
        This method resolves or creates those IDs and then PATCHes the document.
        """
        payload: dict[str, Any] = {
            "title": title,
        }

        if correspondent:
            correspondent_id = self.get_or_create_correspondent_id(correspondent)
            if correspondent_id is not None:
                payload["correspondent"] = correspondent_id

        if document_type:
            document_type_id = self.get_or_create_document_type_id(document_type)
            if document_type_id is not None:
                payload["document_type"] = document_type_id

        if tags:
            tag_ids: list[int] = []
            seen: set[str] = set()

            for tag in tags:
                clean_tag = tag.strip()
                if not clean_tag:
                    continue

                key = clean_tag.lower()
                if key in seen:
                    continue
                seen.add(key)

                tag_id = self.get_or_create_tag_id(clean_tag)
                if tag_id is not None:
                    tag_ids.append(tag_id)

            payload["tags"] = tag_ids

        self.update_document(
            document_id=document_id,
            payload=payload,
        )

        return payload

    def mark_as_duplicate(
        self,
        document_id: int,
        original_id: int,
        original_title: str | None,
        duplicate_reason: str,
    ) -> dict[str, Any]:
        """Tag a duplicate in Paperless and point a note at its original.

        Existing tags are kept: the PATCH sends the merged list, because
        Paperless replaces the tag set it is given.
        """
        current_tags = list(self.get_document(document_id).get("tags") or [])
        tag_id = self.get_or_create_tag_id(DUPLICATE_TAG_NAME)
        tag_added = tag_id is not None and tag_id not in current_tags

        if tag_added:
            self.update_document(
                document_id=document_id,
                payload={"tags": [*current_tags, tag_id]},
            )

        note = format_duplicate_note(
            original_id=original_id,
            original_title=original_title,
            duplicate_reason=duplicate_reason,
        )
        response = requests.post(
            self._url(f"/api/documents/{document_id}/notes/"),
            headers=self.headers,
            json={"note": note, "is_note": True},
            timeout=30,
        )
        response.raise_for_status()

        return {"tag_added": tag_added, "note": note}

    def download_document(self, document_id: int) -> bytes:
        """Download document as raw bytes."""
        response = requests.get(
            self._url(f"/api/documents/{document_id}/download/"),
            headers=self.headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.content
