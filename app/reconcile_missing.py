import os
import sqlite3
import time
from urllib.parse import urlencode

import requests

from app.config import settings
from app.reprocess import reprocess_paperless_document


LIMIT = 100


def get_db_path() -> str:
    candidates = [
        os.getenv("SQLITE_PATH"),
        getattr(settings, "db_path", None),
        "/data/documents.db",
        "/app/data/documents.db",
        "./data/documents.db",
    ]

    for path in candidates:
        if path and os.path.exists(path):
            return path

    raise RuntimeError(
        "Keine SQLite-Datenbank gefunden. Geprüft wurden: "
        + ", ".join(str(p) for p in candidates if p)
    )


def get_known_paperless_ids() -> set[int]:
    db_path = get_db_path()
    print(f"📄 Nutze SQLite-Datenbank: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT paperless_id FROM documents WHERE paperless_id IS NOT NULL"
        ).fetchall()
        return {int(row[0]) for row in rows}
    finally:
        conn.close()


def fetch_latest_paperless_documents() -> list[dict]:
    url = settings.paperless_url.rstrip("/") + "/api/documents/"

    params = {
        "page_size": LIMIT,
        "ordering": "-created",
    }

    response = requests.get(
        url + "?" + urlencode(params),
        headers={
            "Authorization": f"Token {settings.paperless_token}",
        },
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    return payload.get("results", [])


def main() -> None:
    known_ids = get_known_paperless_ids()
    documents = fetch_latest_paperless_documents()

    missing = [
        document
        for document in documents
        if int(document["id"]) not in known_ids
    ]

    if not missing:
        print("✅ Keine fehlenden Dokumente gefunden.")
        return

    print(f"🔎 Fehlende Dokumente gefunden: {len(missing)}")

    for document in reversed(missing):
        paperless_id = int(document["id"])
        title = document.get("title") or "Ohne Titel"

        print(f"➡️  Verarbeite Paperless-ID {paperless_id}: {title}")

        try:
            reprocess_paperless_document(paperless_id)
            print(f"✅ Paperless-ID {paperless_id} verarbeitet")
        except Exception as exc:
            print(f"❌ Fehler bei Paperless-ID {paperless_id}: {exc}")

        time.sleep(2)


if __name__ == "__main__":
    main()