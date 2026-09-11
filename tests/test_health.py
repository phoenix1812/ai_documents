from app import health


class Response:
    status_code = 200

    def json(self):
        return {"models": [{"name": "llama3:latest"}]}

    def raise_for_status(self):
        return None


def test_ollama_check_requires_configured_model(monkeypatch):
    monkeypatch.setattr(health.settings, "ollama_model", "llama3")
    monkeypatch.setattr(health.requests, "get", lambda *args, **kwargs: Response())
    result = health._ollama_check()
    assert result["status"] == "ok"
    assert result["model_available"] is True


def test_ollama_check_fails_when_model_is_missing(monkeypatch):
    monkeypatch.setattr(health.settings, "ollama_model", "missing-model")

    class EmptyResponse(Response):
        def json(self):
            return {"models": []}

    monkeypatch.setattr(health.requests, "get", lambda *args, **kwargs: EmptyResponse())
    result = health._ollama_check()
    assert result["status"] == "error"
    assert result["model_available"] is False
