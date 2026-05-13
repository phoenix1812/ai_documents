"""
Paperless-ngx REST API client.

Responsible for:
- loading documents
- downloading PDFs
- updating metadata
- resolving names to Paperless IDs
- creating missing tags, document types and correspondents
"""

from typing import Any

import requests

from app.config import settings


class PaperlessClient:
    """Client wrapper for the Paperless API."""

    def __init__(self) -> None:
        self.base_url = settings.paperless_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {settings.paperless_token}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Load all results from a paginated Paperless endpoint."""
        url = self._url(path)
        results: list[dict[str, Any]] = []

        while url:
            response = requests.get(
                url,
                headers=self.headers,
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

    def get_or_create_document_type_id(self, name: str) -> int | None:
        return self._get_or_create_named_id("/api/document_types/", name)

    def get_or_create_correspondent_id(self, name: str) -> int | None:
        return self._get_or_create_named_id("/api/correspondents/", name)

    def get_documents(self) -> list[dict[str, Any]]:
        """Load all available documents."""
        return self._get_paginated("/api/documents/")

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

    def download_document(self, document_id: int) -> bytes:
        """Download document as raw bytes."""
        response = requests.get(
            self._url(f"/api/documents/{document_id}/download/"),
            headers=self.headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.content
