import pathlib

import pytest
import requests
from fastapi import HTTPException

from app import review_ui
from app.config import settings
from app.db import Database
from app.db import STATUS_MANUALLY_APPROVED
from app.db import STATUS_SKIPPED_DUPLICATE


class FakePaperless:
    def __init__(self, outcome="geloescht", error=None, title="Rechnung_Kopie.pdf"):
        self.outcome = outcome
        self.error = error
        self.title = title
        self.deleted = []

    def get_document(self, document_id):
        if self.error:
            raise self.error
        return {"title": self.title}

    def delete_document(self, document_id):
        if self.error:
            raise self.error
        self.deleted.append(document_id)
        return self.outcome


def prepare(tmp_path, monkeypatch, duplicate_status=STATUS_SKIPPED_DUPLICATE):
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    db = Database(str(tmp_path))
    db.insert_document(
        paperless_id=104,
        file_hash="hash-104",
        title="",
        correspondent="",
        document_type="",
        export_path="",
        status=duplicate_status,
        duplicate_of_paperless_id=45,
        duplicate_reason="pdf_hash",
    )
    db.insert_document(
        paperless_id=45,
        file_hash="hash-45",
        title="Rechnung_Original",
        correspondent="Mann Gebäudetechnik",
        document_type="Rechnung",
        export_path="",
        status=STATUS_MANUALLY_APPROVED,
    )
    dup_id = db.get_latest_for_paperless_id(104)["id"]
    orig_id = db.get_latest_for_paperless_id(45)["id"]

    for item_id, paperless_id in ((dup_id, 104), (orig_id, 45)):
        db.insert_review_decision(
            document_db_id=item_id,
            paperless_id=paperless_id,
            action="saved",
            original_ai_title=None,
            original_ai_correspondent=None,
            original_ai_document_type=None,
            original_ai_tags=[],
            final_title="T",
            final_correspondent="C",
            final_document_type="Rechnung",
            final_tags=["Steuer"],
            reason="test",
        )
    return db, dup_id, orig_id


def use_fake(monkeypatch, fake):
    monkeypatch.setattr(review_ui, "PaperlessClient", lambda *a, **k: fake)


def test_preview_refuses_a_non_duplicate(tmp_path, monkeypatch):
    db, dup_id, orig_id = prepare(tmp_path, monkeypatch)

    preview = db.duplicate_delete_preview(dup_id)
    assert preview["paperless_id"] == 104
    assert preview["decision_count"] == 1
    assert db.duplicate_delete_preview(orig_id) is None


def test_delete_removes_row_and_its_own_decisions(tmp_path, monkeypatch):
    db, dup_id, orig_id = prepare(tmp_path, monkeypatch)

    documents, decisions = db.delete_duplicate_row(dup_id)

    assert (documents, decisions) == (1, 1)
    assert db.get_document_row(dup_id) is None
    # the approved row and its decision history stay untouched
    assert db.get_document_row(orig_id)["status"] == STATUS_MANUALLY_APPROVED
    remaining = db.conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]
    assert remaining == 1


def test_delete_raises_when_the_row_is_not_a_duplicate(tmp_path, monkeypatch):
    db, _dup_id, orig_id = prepare(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        db.delete_duplicate_row(orig_id)

    assert db.get_document_row(orig_id) is not None


def test_confirm_screen_refuses_an_approved_row(tmp_path, monkeypatch):
    _db, _dup_id, orig_id = prepare(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as caught:
        review_ui.get_duplicate_or_404(orig_id)

    assert caught.value.status_code == 400


def test_deletion_stops_when_paperless_refuses(tmp_path, monkeypatch):
    db, dup_id, _orig_id = prepare(tmp_path, monkeypatch)
    use_fake(
        monkeypatch,
        FakePaperless(error=requests.RequestException("Paperless nicht erreichbar")),
    )

    with pytest.raises(HTTPException) as caught:
        review_ui.delete_duplicate(dup_id)

    assert caught.value.status_code == 502
    assert db.get_document_row(dup_id) is not None


def test_deletion_removes_paperless_first_then_the_row(tmp_path, monkeypatch):
    db, dup_id, _orig_id = prepare(tmp_path, monkeypatch)
    fake = FakePaperless()
    use_fake(monkeypatch, fake)

    response = review_ui.delete_duplicate(dup_id)

    assert fake.deleted == [104]
    assert db.get_document_row(dup_id) is None
    assert response.status_code == 303
    assert "notice=geloescht" in response.headers["location"]


def test_a_paperless_document_that_is_already_gone_still_clears_the_row(
    tmp_path, monkeypatch
):
    db, dup_id, _orig_id = prepare(tmp_path, monkeypatch)
    use_fake(monkeypatch, FakePaperless(outcome="bereits entfernt"))

    response = review_ui.delete_duplicate(dup_id)

    assert db.get_document_row(dup_id) is None
    assert "notice=bereits-entfernt" in response.headers["location"]


def test_documents_list_only_accepts_known_notices(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        review_ui.templates, "TemplateResponse", lambda template, context: context
    )

    class FakeRequest:
        pass

    context = review_ui.documents(
        request=FakeRequest(), status=None, q=None, notice="irgendwas", pid=1
    )
    assert context["notice"] is None

    context = review_ui.documents(
        request=FakeRequest(),
        status=STATUS_SKIPPED_DUPLICATE,
        q=None,
        notice="geloescht",
        pid=104,
    )
    assert context["notice"] == "geloescht"
    assert context["notice_pid"] == 104
    assert context["duplicate_status"] == STATUS_SKIPPED_DUPLICATE


def test_confirm_screen_names_both_paperless_cases(tmp_path, monkeypatch):
    _db, dup_id, _orig_id = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        review_ui.templates,
        "TemplateResponse",
        lambda template, context: context,
    )

    class GoneResponse:
        status_code = 404

    class GoneClient(FakePaperless):
        def get_document(self, document_id):
            raise requests.HTTPError(response=GoneResponse())

    use_fake(monkeypatch, GoneClient())
    context = review_ui.confirm_delete_duplicate(request=None, item_id=dup_id)
    assert context["paperless_note"] == review_ui.DELETE_ALREADY_GONE_NOTE

    class DownClient(FakePaperless):
        def get_document(self, document_id):
            raise requests.RequestException("nicht erreichbar")

    use_fake(monkeypatch, DownClient())
    context = review_ui.confirm_delete_duplicate(request=None, item_id=dup_id)
    assert context["paperless_note"] == review_ui.DELETE_UNREACHABLE_NOTE


def test_templates_parse(tmp_path):
    import jinja2

    environment = jinja2.Environment()
    for name in ("delete_duplicate.html", "documents.html", "review_detail.html"):
        text = pathlib.Path("app/templates").joinpath(name).read_text(encoding="utf-8")
        environment.parse(text)
