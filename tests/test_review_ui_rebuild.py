
from app.config import settings
from app.db import Database
from app.db import STATUS_AUTO_APPROVED
from app.review_ui import save_document


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path))
    db = Database(str(tmp_path))
    db.insert_document(
        paperless_id=42,
        file_hash="hash-42",
        title="Rechnung_Amazon_Bueromaterial_2026-05-12",
        correspondent="Amazon",
        document_type="Rechnung",
        tags=["Steuer"],
        export_path="",
        status=STATUS_AUTO_APPROVED,
        subject="Bueromaterial",
        document_date="2026-05-12",
    )
    return Database(str(tmp_path))


def stored_title(tmp_path):
    row = Database(str(tmp_path)).conn.execute(
        "SELECT title, tags FROM documents WHERE paperless_id = 42"
    ).fetchone()
    return row["title"]


def test_typing_a_title_keeps_it_unchanged(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)

    save_document(
        item_id=1,
        title="Eigener_Name",
        correspondent="Amazon",
        document_type="Rechnung",
        tags="Steuer",
        apply_to_paperless=False,
        correction_reason='test',
    )

    assert stored_title(tmp_path) == "Eigener_Name"


def test_rebuild_button_replaces_the_typed_title(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)

    save_document(
        item_id=1,
        title="Eigener_Name",
        correspondent="Amazon",
        document_type="Rechnung",
        tags="Steuer",
        apply_to_paperless=False,
        correction_reason='test',
        rebuild_title=True,
    )

    assert stored_title(tmp_path) == "Rechnung_Amazon_Bueromaterial_2026-05-12"
