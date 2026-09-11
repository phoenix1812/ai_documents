# AI Documents

AI Documents ist ein lokaler, eventbasierter Dokumenten-Klassifizierer fuer
`paperless-ngx`.

Paperless importiert und verwaltet die Dokumente. Nach dem Consume triggert ein
Post-Consume-Script den AI-Worker. Der Worker laedt OCR-Text und PDF-Bytes aus
Paperless, klassifiziert den Inhalt lokal mit Ollama, validiert das Ergebnis und
schreibt fachliche Metadaten zurueck nach Paperless.

Paperless bleibt die Single Source of Truth. PDFs werden nicht separat exportiert.

## Features

- Eventbasierte Verarbeitung per Paperless `POST_CONSUME_SCRIPT`
- Single-Worker-Queue fuer serielle Ollama-Verarbeitung
- Lokale Klassifikation ueber Ollama
- Automatisches Setzen fachlicher Paperless-Metadaten:
  - Titel
  - Korrespondent
  - Dokumenttyp
  - fachliche Tags
- Serverseitige, stabile Titelgenerierung
- Validierung vor automatischem Schreiben nach Paperless
- Review-UI fuer unsichere, fehlgeschlagene und manuell zu pruefende Dokumente
- Retry und Reprocess ueber denselben Queue-Trigger wie Paperless
- Duplikaterkennung per PDF-SHA256
- Wahrscheinliche Duplikaterkennung per normalisiertem OCR-SHA256
- SQLite-Audit fuer Status, Fehler, Review-Entscheidungen und Korrekturen
- Docker-Compose-Setup mit Paperless, PostgreSQL, Redis, Ollama, AI-Worker und Review-UI

## Architektur

```text
paperless-ngx
  |
  | POST_CONSUME_SCRIPT
  v
scripts/post-consume-ai-worker.sh
  |
  | POST /process {"document_id": ...}
  v
app/main.py
  |
  | enqueue(document_id)
  v
app/document_queue.py
  |
  | genau ein Dokument gleichzeitig
  v
app/worker.py
  |
  v
app/classifier.py
  |
  +--> Paperless API: Dokument, OCR und PDF-Bytes laden
  +--> PDF-Hash und OCR-Hash pruefen
  +--> Ollama: OCR-Kontext klassifizieren
  +--> classifier.py: finalen Titel bauen
  +--> validator.py: Ergebnis pruefen
  +--> Paperless API: Metadaten aktualisieren
  +--> SQLite: Status und Review-Daten speichern
```

Die Review-UI laeuft als eigener Prozess. Reprocess und Retry klassifizieren
nicht inline, sondern senden ebenfalls `POST /process` an den AI-Worker. Dadurch
bleiben Ollama-Aufrufe zentral serialisiert.

## Services

| Service | Zweck | Port |
| --- | --- | --- |
| `paperless` | Paperless Web UI und API | `127.0.0.1:8000` |
| `ai-worker` | Trigger-Server und Queue-Verarbeitung | intern `8080` |
| `ai-review-ui` | Review-UI fuer Status, Korrektur und Reprocess | `127.0.0.1:8090` |
| `ollama` | Lokales LLM | intern `11434` |
| `db` | PostgreSQL fuer Paperless | intern |
| `redis` | Redis fuer Paperless | intern |

## Einrichtung

1. `.env` aus der Vorlage erstellen:

```bash
cp .env.example .env
```

2. Werte in `.env` anpassen:

```text
POSTGRES_PASSWORD=...
PAPERLESS_ADMIN_USER=...
PAPERLESS_ADMIN_PASSWORD=...
PAPERLESS_SECRET_KEY=...
PAPERLESS_TOKEN=...
REVIEW_UI_USERNAME=...
REVIEW_UI_PASSWORD=...
OLLAMA_MODEL=llama3
DRY_RUN=true

# Persistent queue / reconciliation
QUEUE_MAX_ATTEMPTS=10
QUEUE_RETRY_BASE_SECONDS=30
QUEUE_RETRY_MAX_SECONDS=1800
RECONCILIATION_INTERVAL_SECONDS=600
```

3. Umgebung pruefen:

```bash
scripts/check-env.sh
```

4. Gewuenschtes Ollama-Modell laden:

```bash
scripts/ensure-ollama-model.sh
```

5. Stack starten:

```bash
docker compose up -d --build
```

6. Healthchecks pruefen:

```bash
scripts/healthcheck.sh
```

## Empfohlener erster Betrieb

Starte neue Installationen zuerst mit:

```text
DRY_RUN=true
```

Damit klassifiziert AI Documents die Dokumente und schreibt den Status in
SQLite, aktualisiert aber noch keine Paperless-Metadaten. Pruefe danach die
Review-UI unter:

```text
http://localhost:8090
```

Wenn die Ergebnisse passen, setze:

```text
DRY_RUN=false
```

und starte die Container neu:

```bash
docker compose up -d --build
```

## Verarbeitung testen

AI-Worker-Healthcheck:

```bash
docker compose exec paperless curl -fsS http://ai-worker:8080/health
```

Ein einzelnes Dokument manuell einreihen:

```bash
docker compose exec paperless curl -fsS \
  -X POST http://ai-worker:8080/process \
  -H "Content-Type: application/json" \
  -d '{"document_id": 123}'
```

Beispielantwort:

```json
{
  "document_id": 123,
  "accepted": true,
  "queued": true,
  "status": "QUEUED",
  "queue_size": 1
}
```

Der Queue-Status erscheint im Healthcheck:

```json
{
  "status": "ok",
  "queue": {
    "current_document_id": 123,
    "queue_size": 2,
    "queued_or_running": [123, 124, 125]
  }
}
```

## Review-Workflow

Die Review-UI bietet:

- Dashboard mit Statusuebersicht
- Review-Liste fuer `NEEDS_REVIEW`, `REVIEW_REQUIRED` und `DRY_RUN`
- Fehlerliste mit Retry und Ignorieren
- Detailansicht mit OCR-Auszug, Paperless-Link und Metadatenformular
- Korrektur automatisch freigegebener Dokumente
- Manuelles Reprocess einer Paperless-ID
- Learning-Ansicht mit gespeicherten Review-Entscheidungen

Beim Speichern kann die Korrektur optional direkt nach Paperless geschrieben
werden. Review-Entscheidungen bleiben zusaetzlich in SQLite nachvollziehbar.

## Statuswerte

| Status | Bedeutung |
| --- | --- |
| `AUTO_APPROVED` | Validierung bestanden und Metadaten nach Paperless geschrieben |
| `DRY_RUN` | Klassifiziert, aber wegen `DRY_RUN=true` nicht nach Paperless geschrieben |
| `NEEDS_REVIEW` | Klassifikation ist plausibel, aber nicht sicher genug fuer Auto-Apply |
| `REVIEW_REQUIRED` | Manuell abgelehnt oder weiter klaerungsbeduerftig |
| `MANUALLY_APPROVED` | In der Review-UI manuell gespeichert/freigegeben |
| `SKIPPED_DUPLICATE` | PDF- oder OCR-Duplikat erkannt |
| `FAILED_OCR` | Kein OCR-Inhalt vorhanden |
| `FAILED_LLM` | LLM-Antwort war nicht verarbeitbar |
| `FAILED_API` | Paperless/Ollama/API-Aufruf fehlgeschlagen |
| `FAILED` | Unerwarteter Fehler |
| `IGNORED` | Fehler wurde manuell ignoriert |

## Duplikaterkennung

AI Documents prueft zwei Stufen:

1. Exaktes Duplikat:

```text
sha256(PDF-Bytes)
```

2. Wahrscheinliches Duplikat:

```text
sha256(normalisierter OCR-Text)
```

Beim Reprocess wird das aktuelle Paperless-Dokument aus der Duplikatpruefung
ausgeschlossen. Dadurch wird ein Dokument nicht faelschlich als Duplikat von
sich selbst markiert.

## Titel-Format

Der finale Titel wird serverseitig aus strukturierten Feldern gebaut:

```text
Dokumenttyp_Korrespondent_Thema_Datum_Betrag
```

Beispiele:

```text
Rechnung_Amazon_Bueromaterial_2026-05-12_84,99_EUR
Brief_Finanzamt_Steuerbescheid_2025
Vertrag_Vodafone_Glasfaser
Versicherung_Allianz_KFZ_2026
```

Regeln:

- keine Leerzeichen
- `_` als Trenner
- keine `[Review]`-Praefixe
- keine technischen Workflow-Informationen
- maximale Laenge: 120 Zeichen

## Konfiguration

Wichtige Variablen:

| Variable | Bedeutung |
| --- | --- |
| `PAPERLESS_URL` | Interne Paperless-URL fuer API-Aufrufe |
| `PAPERLESS_PUBLIC_URL` | Oeffentliche URL fuer Paperless und Links aus der Review-UI |
| `PAPERLESS_TOKEN` | Paperless API-Token |
| `OLLAMA_URL` | Interne Ollama-URL |
| `OLLAMA_MODEL` | Modellname fuer Klassifikation |
| `DB_PATH` | Verzeichnis fuer `documents.db` |
| `AI_WORKER_TRIGGER_URL` | Queue-Trigger des AI-Workers |
| `CONFIDENCE_THRESHOLD` | Mindestvertrauen fuer Auto-Approval |
| `MIN_TITLE_LENGTH` | Mindestlaenge fuer gueltige Titel |
| `DRY_RUN` | Klassifizieren ohne Paperless-Update |
| `REVIEW_UI_USERNAME` | Basic-Auth-Benutzer der Review-UI |
| `REVIEW_UI_PASSWORD` | Basic-Auth-Passwort der Review-UI |

`SQLITE_PATH` wird fuer alte Setups weiterhin akzeptiert. Intern verwendet die
App aber `DB_PATH` als Verzeichnis und legt darin `documents.db` an.

## Entwicklung

Python-Version passend zum Dockerfile:

```text
Python 3.12
```

Lokales Setup:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

Tests:

```bash
python -m pytest -q
python -m compileall -q app tests
```

## Verzeichnisstruktur

```text
.
├── app/
│   ├── main.py
│   ├── document_queue.py
│   ├── worker.py
│   ├── classifier.py
│   ├── paperless_client.py
│   ├── ollama_client.py
│   ├── validator.py
│   ├── db.py
│   ├── hash_store.py
│   ├── models.py
│   ├── prompts.py
│   ├── reprocess.py
│   ├── reconcile_missing.py
│   ├── review_ui.py
│   └── logging_config.py
├── scripts/
│   ├── post-consume-ai-worker.sh
│   ├── check-env.sh
│   ├── healthcheck.sh
│   ├── backup.sh
│   └── restore.sh
├── tests/
├── docker-compose.yml
├── dockerfile
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Sicherheit und Betrieb

- `PAPERLESS_TOKEN` und `.env` niemals committen
- Standardpasswoerter vor dem Betrieb aendern
- Review-UI nicht oeffentlich ins Internet stellen
- AI-Worker nur intern im Docker-Netz verwenden
- SQLite-Datenbank und Paperless-Daten regelmaessig sichern
- Neue Setups zuerst mit `DRY_RUN=true` testen
- LLM-Ergebnisse stichprobenartig ueber die Review-UI pruefen

## Produktionshinweise

- Die Verarbeitungsqueue ist persistent in SQLite und ueberlebt Container-Neustarts.
- `PROCESSING`-Jobs werden nur beim Start des AI-Workers recovered; ein Healthcheck
  veraendert niemals den Queue-Zustand.
- Reconciliation laeuft periodisch und arbeitet gegen die Paperless-API.
- Das konfigurierte Ollama-Modell ist Bestandteil des Readiness-Checks.
- Fuer NAS/SMB/NFS-Consume-Pfade wird Paperless v3 mit Polling betrieben.
- Vor dem ersten echten Betrieb mit `DRY_RUN=true` testen und anschliessend ein
  Backup/Restore einmal erfolgreich durchspielen.
- Gespeicherte Review-Entscheidungen werden noch nicht automatisch in Prompts
  oder Regeln zurueckgespielt.
