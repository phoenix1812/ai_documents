from app.ollama_client import OllamaClient
from app.paperless_client import PaperlessClient


DOCUMENT_TYPE_MAPPING = {
    "Rechnung": 1,
    "Vertrag": 2,
    "Versicherung": 3,
    "Steuer": 4,
    "Bank": 5,
    "Sonstiges": 6,
}


class DocumentClassifier:
    def __init__(self) -> None:
        self.paperless = PaperlessClient()
        self.ollama = OllamaClient()

    def process_document(self, document_id: int) -> None:
        document = self.paperless.get_document(document_id)

        content = document.get("content", "")

        if not content:
            return

        result = self.ollama.classify(content)

        payload = {
            "title": result.title,
            "document_type": DOCUMENT_TYPE_MAPPING.get(
                result.document_type,
                6,
            ),
        }

        self.paperless.update_document(document_id, payload)