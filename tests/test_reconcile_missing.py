from app import reconcile_missing


def test_get_db_path_accepts_db_directory(monkeypatch, tmp_path):
    db_file = tmp_path / "documents.db"
    db_file.write_text("", encoding="utf-8")

    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.setattr(reconcile_missing.settings, "db_path", str(tmp_path))

    assert reconcile_missing.get_db_path() == str(db_file)
