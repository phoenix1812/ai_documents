from app import reprocess


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_enqueue_paperless_document_posts_to_worker_queue(monkeypatch):
    calls = []
    monkeypatch.setattr(
        reprocess.settings,
        "ai_worker_trigger_url",
        "http://ai-worker:8080/process",
    )

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse({"status": "QUEUED", "queue_size": 3})

    monkeypatch.setattr(reprocess.requests, "post", fake_post)

    result = reprocess.enqueue_paperless_document(123)

    assert result == "QUEUED (queue_size=3)"
    assert calls == [
        ("http://ai-worker:8080/process", {"document_id": 123}, 10)
    ]
