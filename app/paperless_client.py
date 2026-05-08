"""
Paperless-ngx REST API client.

Responsible for:
- loading documents
- updating metadata
- downloading PDFs
"""

from typing import Dict
from typing import List

import requests

from app.config import settings


class PaperlessClient:
    """
    Client wrapper for the Paperless API.
    """

    def __init__(self) -> None:
        self.base_url = settings.paperless_url

        self.headers = {
            "Authorization": (
                f"Token {settings.paperless_token}"
            )
        }

    def get_documents(self) -> List[Dict]:
        """
        Load all available documents.
        """

        response = requests.get(
            f"{self.base_url}/api/documents/",
            headers=self.headers,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()["results"]

    def get_document(
        self,
        document_id: int,
    ) -> Dict:
        """
        Load a single document.
        """

        response = requests.get(
            (
                f"{self.base_url}"
                f"/api/documents/{document_id}/"
            ),
            headers=self.headers,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()

    def update_document(
        self,
        document_id: int,
        payload: Dict,
    ) -> None:
        """
        Update document metadata.
        """

        response = requests.patch(
            (
                f"{self.base_url}"
                f"/api/documents/{document_id}/"
            ),
            headers=self.headers,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

    def download_document(
        self,
        document_id: int,
        target_path: str,
    ) -> None:
        """
        Download original document PDF.
        """

        response = requests.get(
            (
                f"{self.base_url}"
                f"/api/documents/"
                f"{document_id}/download/"
            ),
            headers=self.headers,
            timeout=60,
        )

        response.raise_for_status()

        with open(target_path, "wb") as file:
            file.write(response.content)