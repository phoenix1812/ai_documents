"""Application entrypoint for the event-driven AI document worker.

Paperless calls this HTTP server from its post-consume script whenever a new
Document was consumed.

Important:
- /process returns immediately with HTTP 202.
- Requests are put into a single background queue.
- Exactly one document is processed at a time.
- This avoids concurrent Ollama calls, SQLite write contention and duplicate
  processing races.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.parse import urlparse

from app.config import settings
from app.document_queue import DocumentProcessingQueue
from app.logging_config import setup_logging
from app.worker import Worker

logger = logging.getLogger(__name__)

processing_queue: DocumentProcessingQueue | None = None


class TriggerHandler(BaseHTTPRequestHandler):
    """HTTP handler for event-driven document processing."""

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.warning("Client disconnected before response could be sent.")

    def do_GET(self) -> None:
        """Health endpoint."""
        if self.path == "/health":
            payload = {"status": "ok"}
            if processing_queue is not None:
                payload["queue"] = processing_queue.snapshot()
            self._send_json(200, payload)
            return

        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        """Trigger processing for one document.

        Accepted input:
        - POST /process?document_id=123
        - POST /process with JSON body {"document_id": 123}
        """
        parsed = urlparse(self.path)
        if parsed.path != "/process":
            self._send_json(404, {"error": "not_found"})
            return

        try:
            if processing_queue is None:
                raise RuntimeError("Processing queue not initialized")

            document_id = self._extract_document_id(parsed.query)
            status = processing_queue.enqueue(document_id)
            self._send_json(
                202,
                {
                    "document_id": status.document_id,
                    "accepted": status.accepted,
                    "queued": status.queued,
                    "status": status.status,
                    "queue_size": status.queue_size,
                },
            )
        except Exception as exc:
            logger.exception("Failed to accept triggered document")
            self._send_json(400, {"error": str(exc)})

    def _extract_document_id(self, query: str) -> int:
        params = parse_qs(query)
        if "document_id" in params:
            return int(params["document_id"][0])

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Missing document_id")

        raw_body = self.rfile.read(content_length)
        payload = json.loads(raw_body.decode("utf-8"))
        if "document_id" not in payload:
            raise ValueError("Missing document_id")

        return int(payload["document_id"])

    def log_message(self, format: str, *args) -> None:
        """Route HTTP server logs through application logging."""
        logger.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    """Start HTTP trigger server."""
    global processing_queue

    setup_logging()
    worker = Worker()
    processing_queue = DocumentProcessingQueue(worker=worker)

    server = ThreadingHTTPServer(("0.0.0.0", settings.trigger_port), TriggerHandler)
    logger.info("AI trigger server started on port %s.", settings.trigger_port)
    server.serve_forever()


if __name__ == "__main__":
    main()
