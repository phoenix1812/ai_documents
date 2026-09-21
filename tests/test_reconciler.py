from types import SimpleNamespace

from app import reconciler as reconciler_module
from app.config import settings
from app.db import STATUS_AUTO_APPROVED
from app.db import STATUS_DRY_RUN
from app.db import STATUS_FAILED_API
from app.db import STATUS_FAILED_LLM
from app.db import STATUS_FAILED_OCR
from app.db import Database
from app.reconciler import BASELINE_META_KEY, Reconciler


class FakePaperless:
    def __init__(self, documents):
        self.documents = documents

    def get_documents(self):
        return self.documents


class FakeQueue:
    def __init__(self, exhausted=()):
        self.enqueued = []
        self.exhausted = set(exhausted)

    def enqueue(self, document_id):
        self.enqueued.append(document_id)
        return SimpleNamespace(queued=True)

    def exhausted_document_ids(self):
        return self.exhausted


def make_reconciler(monkeypatch, tmp_path, documents, exhausted=()):
    monkeypatch.setattr(reconciler_module, "PaperlessClient", lambda: FakePaperless(documents))
    monkeypatch.setattr(reconciler_module, "Database", lambda path: Database(str(tmp_path)))
    queue = FakeQueue(exhausted)
    return Reconciler(queue), queue


def test_existing_stock_is_not_imported_automatically(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "reconcile_initial_import", False)
    reconciler, queue = make_reconciler(
        monkeypatch, tmp_path, [{"id": 1}, {"id": 2}, {"id": 3}]
    )

    result = reconciler.reconcile_once()

    assert result["queued"] == 0
    assert result["preexisting_ignored"] == 3
    assert queue.enqueued == []
    assert reconciler.db.get_meta(BASELINE_META_KEY) == "3"

    # Documents created after the frozen baseline are still picked up.
    reconciler.paperless.documents = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    reconciler.reconcile_once()

    assert queue.enqueued == [4]


def test_initial_import_flag_allows_full_backfill(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "reconcile_initial_import", True)
    reconciler, queue = make_reconciler(
        monkeypatch, tmp_path, [{"id": 7}, {"id": 8}]
    )

    reconciler.reconcile_once()

    assert queue.enqueued == [7, 8]
    assert reconciler.db.get_meta(BASELINE_META_KEY) is None


def test_exhausted_jobs_are_not_revived(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "reconcile_initial_import", True)
    reconciler, queue = make_reconciler(
        monkeypatch, tmp_path, [{"id": 20}, {"id": 21}], exhausted={20}
    )

    result = reconciler.reconcile_once()

    # Requeuing a DEAD job resets its attempt counter, so doing it on every
    # pass would restart the full retry budget forever.
    assert queue.enqueued == [21]
    assert result["exhausted_ignored"] == 1


def test_failures_are_final_for_reconciliation(tmp_path):
    db = Database(str(tmp_path))

    for paperless_id, status in (
        (30, STATUS_FAILED_OCR),
        (31, STATUS_FAILED_LLM),
        (32, STATUS_FAILED_API),
    ):
        db.insert_document(
            paperless_id=paperless_id,
            file_hash=f"hash-{paperless_id}",
            title="",
            correspondent="",
            document_type="",
            export_path="",
            status=status,
        )

    for paperless_id in (30, 31, 32):
        assert db.exists_paperless_id(paperless_id) is True


def test_reconcile_disabled_does_not_start_thread(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "reconcile_enabled", False)
    reconciler, _ = make_reconciler(monkeypatch, tmp_path, [])
    started = []
    monkeypatch.setattr(
        reconciler_module.threading.Thread, "start", lambda self: started.append(self.name)
    )

    reconciler.start()

    assert started == []


def test_legacy_app_meta_table_gets_migrated(tmp_path):
    import sqlite3

    db_file = tmp_path / "documents.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()

    db = Database(str(tmp_path))
    db.set_meta("probe", "1")

    assert db.get_meta("probe") == "1"


def test_dry_run_rows_are_final_only_in_dry_run_mode(monkeypatch, tmp_path):
    db = Database(str(tmp_path))
    db.insert_document(
        paperless_id=10,
        file_hash="hash-10",
        title="Rechnung_Test",
        correspondent="Test",
        document_type="Rechnung",
        export_path="",
        status=STATUS_DRY_RUN,
    )

    monkeypatch.setattr(settings, "dry_run", True)
    assert db.exists_paperless_id(10) is True

    # Switching to live mode must reprocess the document instead of leaving the
    # classified-but-never-written state behind forever.
    monkeypatch.setattr(settings, "dry_run", False)
    assert db.exists_paperless_id(10) is False

    db.insert_document(
        paperless_id=11,
        file_hash="hash-11",
        title="Rechnung_Test2",
        correspondent="Test",
        document_type="Rechnung",
        export_path="",
        status=STATUS_AUTO_APPROVED,
    )
    assert db.exists_paperless_id(11) is True
