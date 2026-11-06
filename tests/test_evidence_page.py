"""#57: the question layer as a page.

Two environmental facts this file works around, both measured on 2026-11-04:

* the host venv carries starlette 1.0.0 / fastapi 0.136.1 while the pinned image
  (requirements.txt: fastapi==0.115.12) runs starlette 0.46.2. The old
  ``TemplateResponse(name, context)`` call every route in this project uses still
  renders in the image (proved there: 1731 bytes for /learning) and raises
  TypeError on the host. So the fixture renders through the same Jinja
  environment instead of through starlette's response wrapper.
* httpx is not a dependency here, so there is no TestClient. The route is called
  directly with a hand-built request, and Paperless is a fake that implements
  only the four GET-shaped methods - which the last test asserts against,
  because "answering cannot change the archive" is the claim being made.

Every archive sample in this file is synthetic.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests
from starlette.requests import Request

from app import review_ui
from app.config import settings
from app.db import Database
from app.review_ui import EVIDENCE_OFFLINE_NOTE
from app.review_ui import EVIDENCE_READONLY_NOTE
from app.review_ui import archive_words
from app.review_ui import evidence_page
from app.review_ui import templates

READ_ONLY_ATTRS = {
    "count_documents",
    "list_correspondents",
    "read_document",
    "search_documents",
    "uses_readonly_token",
}

CORRESPONDENTS = [
    {"id": 12, "name": "Beispielwerk Gesellschaft"},
    {"id": 7, "name": "Fiktivkasse Nord"},
]

FEED = {
    "id": 900,
    "title": "Gutschrift Beispielwerk Gesellschaft",
    "correspondent_name": "Beispielwerk Gesellschaft",
    "created": "2025-03-04T00:00:00+01:00",
    "content": "Einspeisung\nVerguetung netto 84,30 EUR\n",
}

QUESTION = "Was brachte die Einspeisung 2025"


class FakePaperless:
    """The four read paths the page may use, with what the archive answers."""

    uses_readonly_token = True

    def __init__(self, *, unreachable: bool = False) -> None:
        self.unreachable = unreachable
        self.searched: list[str] = []
        self.opened: list[int] = []

    def list_correspondents(self) -> list[dict[str, Any]]:
        if self.unreachable:
            raise requests.ConnectionError("Paperless antwortet nicht")
        return list(CORRESPONDENTS)

    def count_documents(self) -> int:
        return 1

    def search_documents(
        self,
        term: str,
        *,
        correspondent_id: int | None = None,
        created_gte: str | None = None,
        created_lte: str | None = None,
        page_size: int = 30,
    ) -> list[dict[str, Any]]:
        self.searched.append(term)
        if term.startswith("einspeis") or term.startswith("verguet"):
            return [{"id": 900, "created": FEED["created"]}]
        return []

    def read_document(self, document_id: int) -> dict[str, Any]:
        self.opened.append(document_id)
        return dict(FEED)


class OnlyRead:
    """Hands out the fake and records every attribute the page asked for."""

    def __init__(self, target: FakePaperless) -> None:
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "touched", set())

    def __getattr__(self, name: str) -> Any:
        self.touched.add(name)  # type: ignore[attr-defined]
        return getattr(self.target, name)


def _request() -> Request:
    scope = {
        "type": "http",
        "app": review_ui.app,
        "path": "/evidence",
        "raw_path": b"/evidence",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "method": "GET",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 12345),
        "root_path": "",
    }
    return Request(scope)


@pytest.fixture()
def page(tmp_path, monkeypatch):
    """The evidence route over a temporary database and one fake archive."""

    fake = FakePaperless()
    client = OnlyRead(fake)
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(settings, "paperless_public_url", "http://paperless.example")
    monkeypatch.setattr(review_ui, "PaperlessClient", lambda: client)

    def render(name: str, context: dict[str, Any]) -> Any:
        body = templates.env.get_template(name).render(context)
        return type("Rendered", (), {"body": body.encode()})()

    monkeypatch.setattr(templates, "TemplateResponse", render)

    def ask(question: str | None = None) -> str:
        return evidence_page(_request(), q=question).body.decode()

    ask.fake = fake  # type: ignore[attr-defined]
    ask.client = client  # type: ignore[attr-defined]
    ask.db = Database(str(tmp_path))
    yield ask
    ask.db.close()


def test_an_empty_question_searches_nothing(page) -> None:
    body = page()

    assert "Belege" in body
    assert page.fake.searched == []
    assert page.fake.opened == []
    assert "Noch keine Frage gestellt." in body


def test_the_question_shows_its_line_its_figure_and_the_variants_tried(page) -> None:
    body = page(QUESTION)

    assert "84,30" in body
    assert "Z2" in body
    assert "netto" in body
    assert "einspeis" in body
    assert "Gutschrift Beispielwerk Gesellschaft" in body
    assert "http://paperless.example/documents/900" in body
    assert "Suchvarianten" in body


def test_question_and_variants_are_remembered_and_offer_themselves_again(page) -> None:
    page(QUESTION)

    history = page.db.recent_searches(limit=5)
    assert [entry["query"] for entry in history] == [QUESTION]
    assert "einspeis" in history[0]["variants"]
    assert history[0]["candidates"] == 1

    body = page()
    assert f'href="/evidence?q={QUESTION.replace(" ", "%20")}"' in body


def test_only_read_paths_of_the_client_are_touched(page) -> None:
    page(QUESTION)

    assert page.client.touched <= READ_ONLY_ATTRS


def test_the_worker_token_fall_back_is_said_out_loud(monkeypatch, tmp_path) -> None:
    fake = FakePaperless()
    fake.uses_readonly_token = False
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    monkeypatch.setattr(review_ui, "PaperlessClient", lambda: OnlyRead(fake))

    def render(name: str, context: dict[str, Any]) -> Any:
        return type("Rendered", (), {"body": templates.env.get_template(name).render(context).encode()})()

    monkeypatch.setattr(templates, "TemplateResponse", render)

    body = evidence_page(_request(), q=None).body.decode()
    assert EVIDENCE_READONLY_NOTE[:30] in body


def test_a_read_only_token_needs_no_banner(page) -> None:
    assert "PAPERLESS_TOKEN_READONLY" not in page()


def test_an_unreachable_archive_answers_with_a_note_and_no_history(page, monkeypatch) -> None:
    monkeypatch.setattr(page.fake, "unreachable", True)

    body = page(QUESTION)

    assert EVIDENCE_OFFLINE_NOTE[:25] in body
    assert page.db.recent_searches(limit=5) == []


def test_the_vocabulary_comes_from_the_archives_own_words(tmp_path) -> None:
    db = Database(str(tmp_path))
    try:
        db.insert_document(
            paperless_id=901,
            file_hash="synthetisch-1",
            title="Vorauszahlungsbescheid Beispielwerk Gesellschaft",
            correspondent="Beispielwerk Gesellschaft",
            document_type="Steuer",
            export_path="",
            ocr_excerpt="Vorauszahlungen 2026 netto 100,00 EUR",
        )
        words = archive_words(db)
    finally:
        db.close()

    assert "vorauszahlungsbescheid" in words
    assert "vorauszahlungen" in words
    assert "beispielwerk" in words


def test_a_figure_offers_its_own_click(page) -> None:
    """An answer can be confirmed as a document or as the figure inside it."""

    body = page(QUESTION)

    assert '/evidence/verdict' in body
    assert 'name="paperless_id" value="900"' in body
    assert 'name="line_number" value="2"' in body
    assert 'name="amount_value" value="84,30"' in body
    assert "das ist die Antwort" in body
    assert "richtiges Dokument" in body


def test_a_stored_judgement_is_shown_rather_than_asked_again(page) -> None:
    from app.db import VERDICT_ANSWER
    from app.db import VERDICT_HIT

    page(QUESTION)
    key = page.db.recent_searches(limit=1)[0]["question_key"]
    page.db.record_verdict(key, 900, VERDICT_HIT)
    page.db.record_verdict(key, 900, VERDICT_ANSWER, 2, "84,30")

    body = page(QUESTION)

    assert "Dein Urteil zu diesem Dokument" in body
    assert "von dir bestätigt am" in body
    assert "richtiges Dokument" not in body
    assert "das ist die Antwort" not in body


def test_a_judgement_under_other_words_is_not_offered(page) -> None:
    """The key is shown because a miss has to be explainable."""

    from app.db import VERDICT_HIT

    page.db.record_search("andere frage", [], 1, 1, "ganz|anders|..")
    page.db.record_verdict("ganz|anders|..", 900, VERDICT_HIT)

    body = page(QUESTION)

    assert "richtiges Dokument" in body
    assert "Merksatz dieser Frage:" in body


def test_the_history_shows_which_questions_were_answered(page) -> None:
    from app.db import VERDICT_ANSWER

    body = page(QUESTION)
    key = page.db.recent_searches(limit=1)[0]["question_key"]
    page.db.record_verdict(key, 900, VERDICT_ANSWER, 2, "84,30")

    body = page()

    assert "<th>Bestätigt</th>" in body
    assert ">1</td>" in body
