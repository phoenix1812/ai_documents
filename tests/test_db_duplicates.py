from app.db import Database


def test_duplicate_lookup_excludes_current_paperless_id(tmp_path):
    db = Database(str(tmp_path))

    db.insert_document(
        paperless_id=42,
        file_hash="same-file-hash",
        ocr_hash="same-ocr-hash",
        title="Rechnung_Test",
        correspondent="Test",
        document_type="Rechnung",
        export_path="",
    )

    assert db.get_by_file_hash("same-file-hash", exclude_paperless_id=42) is None
    assert db.get_by_ocr_hash("same-ocr-hash", exclude_paperless_id=42) is None

    assert db.get_by_file_hash("same-file-hash", exclude_paperless_id=43)["paperless_id"] == 42
    assert db.get_by_ocr_hash("same-ocr-hash", exclude_paperless_id=43)["paperless_id"] == 42
