"""HTTP trigger server for Paperless post-consume events."""
from __future__ import annotations
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from app.config import settings
from app.document_queue import DocumentProcessingQueue
from app.health import health_payload, readiness_payload
from app.logging_config import setup_logging
from app.reconciler import Reconciler
from app.worker import Worker

logger = logging.getLogger(__name__)
processing_queue: DocumentProcessingQueue | None = None
reconciler: Reconciler | None = None

class TriggerHandler(BaseHTTPRequestHandler):
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
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, health_payload(processing_queue.store if processing_queue else None))
            return
        if parsed.path == "/ready":
            payload, status = readiness_payload(processing_queue.store if processing_queue else None)
            self._send_json(status, payload)
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/process":
            try:
                if processing_queue is None:
                    raise RuntimeError("Processing queue not initialized")
                document_id = self._extract_document_id(parsed.query)
                status = processing_queue.enqueue(document_id)
                self._send_json(202, {
                    "document_id": status.document_id,
                    "accepted": status.accepted,
                    "queued": status.queued,
                    "status": status.status,
                    "queue_size": status.queue_size,
                })
            except Exception as exc:
                logger.exception("Failed to accept triggered document")
                self._send_json(400, {"error": str(exc)})
            return
        if parsed.path == "/reconcile":
            try:
                if reconciler is None:
                    raise RuntimeError("Reconciler not initialized")
                params = parse_qs(parsed.query)
                include_existing = params.get("include_existing", ["false"])[0].lower() in {"1", "true", "yes", "on"}
                result = reconciler.reconcile(include_existing=include_existing)
                self._send_json(200, result)
            except Exception as exc:
                logger.exception("Reconciliation failed")
                self._send_json(500, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not_found"})

    def _extract_document_id(self, query: str) -> int:
        params = parse_qs(query)
        if "document_id" in params:
            return int(params["document_id"][0])
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Missing document_id")
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if "document_id" not in payload:
            raise ValueError("Missing document_id")
        return int(payload["document_id"])

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    global processing_queue, reconciler
    setup_logging()
    worker = Worker()
    processing_queue = DocumentProcessingQueue(worker=worker)
    reconciler = Reconciler(processing_queue.store)
    reconciler.start()
    server = ThreadingHTTPServer(("0.0.0.0", settings.trigger_port), TriggerHandler)
    logger.info("AI trigger server started on port %s.", settings.trigger_port)
    try:
        server.serve_forever()
    finally:
        reconciler.stop()
        processing_queue.stop()

if __name__ == "__main__":
    main()
