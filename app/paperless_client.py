import requests
from typing import Dict, List

from app.config import settings


class PaperlessClient:
    def __init__(self) -> None:
        self.base_url = settings.paperless_url

        self.headers = {
            "Authorization": (
                f"Token {settings.paperless_token}"
            )
        }

    def get_documents(self) -> List[Dict]:
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
        response = requests.get(
            f"{self.base_url}/api/documents/{document_id}/",
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
        response = requests.patch(
            f"{self.base_url}/api/documents/{document_id}/",
            headers=self.headers,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()