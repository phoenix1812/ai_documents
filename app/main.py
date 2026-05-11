"""
Application entrypoint.

Starts a tiny HTTP trigger server.
Paperless calls this server from its post-consume script
whenever a new document was consumed.

Important:
- /process returns immediately with HTTP 202.
- The actual document processing runs asynchronously in a background thread.
- This prevents Paperless/curl from timing out and avoids BrokenPipeError noise.
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.parse import urlparse

from app.config import settings
from app.logging_config import setup_logging
from app.worker import Worker


logger = logging.getLogger(__name__)
worker: Worker | None = None

_processing_lock = threading.Lock()
_processing_documents: set[int] = set()


class TriggerHandler(BaseHTTPRequestHandler):
    """
    HTTP handler for event-driven document processing.
    """

    def _send_json(
        self,
        status_code: int,
        payload: dict,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")

        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        except (
            BrokenPipeError,
            ConnectionResetError,
        ):
            # Client closed the connection before reading the response.
            # This can happen with short-lived post-consume callers and should
            # not be treated as a failed document processing attempt.
            logger.warning(
                "Client disconnected before response could be sent."
            )

    def do_GET(self) -> None:
        """
        Health endpoint.
        """

        if self.path == "/health":
            self._send_json(
                200,
                {"status": "ok"},
            )
            return

        self._send_json(
            404,
            {"error": "not_found"},
        )

    def do_POST(self) -> None:
        """
        Trigger processing for one document.

        Accepted input:
        - POST /process?document_id=123
        - POST /process with JSON body {"document_id": 123}
        """

        parsed = urlparse(self.path)

        if parsed.path != "/process":
            self._send_json(
                404,
                {"error": "not_found"},
            )
            return

        try:
            if worker is None:
                raise RuntimeError("Worker not initialized")

            document_id = self._extract_document_id(parsed.query)

            started = self._start_processing_thread(document_id)

            self._send_json(
                202,
                {
                    "document_id": document_id,
                    "accepted": True,
                    "started": started,
                    "status": (
                        "PROCESSING_STARTED"
                        if started
                        else "ALREADY_PROCESSING"
                    ),
                },
            )

        except Exception as exc:
            logger.exception("Failed to accept triggered document")
            self._send_json(
                400,
                {"error": str(exc)},
            )

    def _start_processing_thread(
        self,
        document_id: int,
    ) -> bool:
        """
        Start asynchronous processing unless this document is already running.
        """

        with _processing_lock:
            if document_id in _processing_documents:
                logger.info(
                    "Document %s is already being processed.",
                    document_id,
                )
                return False

            _processing_documents.add(document_id)

        thread = threading.Thread(
            target=_process_document_background,
            args=(document_id,),
            daemon=True,
            name=f"process-document-{document_id}",
        )
        thread.start()

        return True

    def _extract_document_id(
        self,
        query: str,
    ) -> int:
        params = parse_qs(query)

        if "document_id" in params:
            return int(params["document_id"][0])

        content_length = int(
            self.headers.get("Content-Length", "0")
        )

        if content_length <= 0:
            raise ValueError("Missing document_id")

        raw_body = self.rfile.read(content_length)
        payload = json.loads(raw_body.decode("utf-8"))

        if "document_id" not in payload:
            raise ValueError("Missing document_id")

        return int(payload["document_id"])

    def log_message(
        self,
        format: str,
        *args,
    ) -> None:
        """
        Route HTTP server logs through application logging.
        """

        logger.info(
            "%s - %s",
            self.address_string(),
            format % args,
        )


def _process_document_background(
    document_id: int,
) -> None:
    """
    Process one document outside the HTTP request lifecycle.
    """

    try:
        if worker is None:
            raise RuntimeError("Worker not initialized")

        logger.info(
            "Background processing started for document %s.",
            document_id,
        )

        result = worker.process_once(
            document_id=document_id,
        )

        logger.info(
            "Background processing finished for document %s: %s.",
            document_id,
            result,
        )

    except Exception:
        logger.exception(
            "Background processing failed for document %s.",
            document_id,
        )

    finally:
        with _processing_lock:
            _processing_documents.discard(document_id)


def main() -> None:
    """
    Start HTTP trigger server.
    """

    global worker

    setup_logging()
    worker = Worker()

    server = ThreadingHTTPServer(
        ("0.0.0.0", settings.trigger_port),
        TriggerHandler,
    )

    logger.info(
        "AI trigger server started on port %s.",
        settings.trigger_port,
    )

    server.serve_forever()


if __name__ == "__main__":
    main()
