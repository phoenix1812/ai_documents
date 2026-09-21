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
- Persistente Queue in SQLite inkl. Crash-Recovery, Exponential Backoff und DEAD-Status
- Periodischer Abgleich zwischen Paperless-Bestand und AI-Datenbank (`app/reconciler.py`)
- Schutz des Bestands: `RECONCILE_INITIAL_IMPORT=false` importiert vorhandene
  Dokumente nicht automatisch, sondern erst ab der beim ersten Lauf gemerkten
  Paperless-ID
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
app/main.py (HTTP-Trigger, Port 8080 im Docker-Netz)
  |
  | enqueue(document_id)
  v
app/document_queue.py  <->  app/queue_store.py (SQLite-Tabelle processing_jobs)
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


app/reconciler.py (Background-Thread, alle RECONCILIATION_INTERVAL_SECONDS)
  |
  | vergleicht Paperless-Bestand mit der AI-Datenbank
  v
app/document_queue.py
```

Die Review-UI laeuft als eigener Prozess. Reprocess und Retry klassifizieren
nicht inline, sondern senden ebenfalls `POST /process` an den AI-Worker. Dadurch
bleiben Ollama-Aufrufe zentral serialisiert.

`GET /health`, `GET /live` und `GET /ready` liefert `app/health.py`. `/ready` ist
der einzige Endpoint, der den Stack als ganzes bewertet (Paperless, Ollama-
Modell, SQLite-Integritaet, Queue-Integritaet) und damit der Docker-Healthcheck
ist. Healthchecks veraendern bewusst keinen Queue-Zustand.

## Services

| Service | Zweck | Port |
| --- | --- | --- |
| `paperless` | Paperless Web UI und API | `127.0.0.1:8000` |
| `ai-worker` | Trigger-Server, Queue-Verarbeitung, Health/Ready | `8080` nur im Docker-Netz, nicht publiziert |
| `ai-review-ui` | Review-UI fuer Status, Korrektur und Reprocess | `127.0.0.1:8090` |
| `ollama` | Lokales LLM | `11434` nur im Docker-Netz |
| `db` | PostgreSQL fuer Paperless | intern |
| `redis` | Redis fuer Paperless | intern |

`ai-worker` und `ai-review-ui` werden aus demselben Image gebaut (`dockerfile`);
`.dockerignore` haelt Secrets, `.env` und Datenverzeichnisse daraus fern.

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
RECONCILE_ENABLED=true
RECONCILE_INITIAL_IMPORT=false
```

`DRY_RUN` muss gesetzt und entweder `true` oder `false` sein; `scripts/check-env.sh`
prueft das. `EXPORT_PATH` und `POLL_INTERVAL` in einer alten `.env` werden vom
aktuellen Code nicht mehr gelesen und haben keine Entsprechung mehr in
`app/config.py`.

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

Im Live-Modus (`DRY_RUN=false`) gilt der Status `DRY_RUN` nicht mehr als
abgeschlossen: Der Reconciler und `POST /process` holen diese Dokumente erneut
ab und schreiben die Metadaten jetzt nach Paperless. Ein umstaendliches
Nachziehen ist nicht noetig.

## Verarbeitung testen

Der AI-Worker publiziert keinen Port auf dem Host. Endpunkte also von innen
ansprechen:

```bash
docker compose exec paperless curl -fsS http://ai-worker:8080/health
docker compose exec paperless curl -fsS http://ai-worker:8080/ready
docker compose exec paperless curl -fsS http://ai-worker:8080/live
```

Manueller Reconciliation-Lauf (achtet dabei den Baseline-Schutz des Bestands):

```bash
docker compose exec paperless curl -fsS -X POST http://ai-worker:8080/reconcile
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

`/health` liefert die Abhaengigkeiten und den Queue-Zustand:

```json
{
  "status": "ok",
  "paperless": {"status": "ok", "http_status": 200},
  "ollama": {"status": "ok", "model": "gemma3:4b", "model_available": true},
  "database": {"status": "ok", "integrity": "ok", "path": "/data"},
  "queue_database": {"status": "ok", "integrity": "ok"},
  "queue": {
    "current_document_id": 123,
    "queue_size": 2,
    "queued": 1,
    "retry": 1,
    "processing": 1,
    "done": 40,
    "dead": 0,
    "current_job": {"document_id": 123, "attempts": 1, "updated_at": "2026-09-20T09:12:03+00:00"}
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
| `DRY_RUN` | Klassifiziert, aber wegen `DRY_RUN=true` nicht nach Paperless geschrieben. Gilt nur im Testmodus als abgeschlossen; im Live-Modus wird das Dokument erneut verarbeitet |
| `NEEDS_REVIEW` | Klassifikation ist plausibel, aber nicht sicher genug fuer Auto-Apply |
| `REVIEW_REQUIRED` | In der Review-UI als klaerungsbeduerftig markiert |
| `MANUALLY_APPROVED` | In der Review-UI manuell gespeichert/freigegeben |
| `SKIPPED_DUPLICATE` | PDF- oder OCR-Duplikat erkannt |
| `FAILED_OCR` | Kein OCR-Inhalt vorhanden (endgueltig) |
| `FAILED_LLM` | LLM-Antwort war nicht verarbeitbar (endgueltig) |
| `FAILED_API` | Paperless/Ollama/API-Aufruf fehlgeschlagen (wiederholbar) |
| `FAILED` | Unerwarteter Fehler (wiederholbar) |
| `IGNORED` | Fehler wurde manuell ignoriert |

`DONE` ist als Statuswert noch definiert und wird in der Review-UI mitgefuehrt,
vom aktuellen Klassifikationspfad aber nicht geschrieben.

Nur wiederholbare Fehler (`FAILED`, `FAILED_API`) laufen durch das Retry-System
mit Backoff, bis `QUEUE_MAX_ATTEMPTS` erreicht ist und der Job `DEAD` wird.
Endgueltige Fehler (`FAILED_OCR`, `FAILED_LLM`) bleiben sofort endgueltig: Ein
dokument ohne Textschicht oder eine Antwort, die bei temperature 0 nicht zu
parsen ist, wird auch im zehnten Versuch nicht besser, und die serielle Queue
wuerde von einem einzigen kaputten PDF blockiert. Der Abgleich ueberspringt
`DEAD`-Jobs, sonst wuerde jeder Zyklus dieselben Dokumente erneut einreihen.
Ein Neustart ist bewusst dem Menschen vorbehalten (Retry in der Review-UI, der
das Retry-Budget zuruecksetzt). Alle uebrigen Statusse gelten im jeweils aktiven
Modus als endgueltig.

## Queue-Zustaende

`processing_jobs` in SQLite kennt `QUEUED`, `PROCESSING`, `RETRY`, `DONE` und
`DEAD`. `DONE` bedeutet hier "ein Versuch ist durchgelaufen" – der fachliche
Status steht in der `documents`-Tabelle.

Der Worker-Idempotenzschutz vergleicht den vorhandenen Row mit einer eigenen
Statusmenge (`reprocessable_statuses`): Ein Fehler blockiert keinen geplanten
Versuch, sonst wuerde jeder Retry sofort als `ALREADY_PROCESSED` enden. Der
periodische Abgleich nutzt dagegen `final_statuses`, wo Fehler endgueltig sind.

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

Beide Stufen vergleichen Hashes auf **exakte Gleichheit**, es gibt keine
Aehnlichkeits- oder Unschaerfeprüfung. „Wahrscheinlich" heisst nur, dass die
PDF-Bytes unterschiedlich sind, der normalisierte OCR-Text aber Zeiger fuer
Zeiger identisch sein muss. Ein erneuter Scan desselben Blatts wird dadurch
regelmaendig *nicht* als Duplikat erkannt: Scanner-OCR wiederholt Kopfzeilen
und liest Randobjekte anders. Die Stufen 1 und 2 erkennen also Neu-Importe
derselben Datei, nicht Neu-Scans.
Gemessen am 2026-09-21 an einem iPad-PDF und seinem Scan: 964 vs. 1209 Zeichen,
Aehnlichkeit 0.65, beide Hashes verschieden.

Beim Reprocess wird das aktuelle Paperless-Dokument aus der Duplikatpruefung
ausgeschlossen. Dadurch wird ein Dokument nicht faelschlich als Duplikat von
sich selbst markiert.

### Was mit einem Duplikat passiert

Der Worker loescht und klassifiziert nichts an dieser Stelle. Paperless hat das
Dokument zu diesem Zeitpunkt schon selbst aufgenommen, also kann die Pipeline
die Aufnahme nicht mehr verhindern - nur sichtbar machen, dass es ein Duplikat
ist:

- Tag `Duplikat` (vorhandene Tags bleiben erhalten)
- Paperless-Notiz mit Verweis auf das Original, zum Beispiel
  `Duplikat von #38 (Versicherung_Allianz): identischer OCR-Text.`
- SQLite-Zeile mit `SKIPPED_DUPLICATE`, `duplicate_of_paperless_id` und
  `duplicate_reason`

In der Review-UI zeigt „Alle Dokumente" bei solchen Zeilen zusaetzlich
`Duplikat von #38` als Link auf das Original, und der Statusfilter
`SKIPPED_DUPLICATE` listet alle Funde auf, um sie selbst zu loeschen.
Loeschen bleibt Handarbeit. Im Dry-Run unterbleibt der Schreibzugriff auf
Paperless; ein fehlgeschlagenes Markieren macht aus dem `SKIPPED_DUPLICATE`
keinen Fehler, sondern steht in der Fehlermeldung der Zeile.

## Titel-Format

Der finale Titel wird serverseitig aus strukturierten Feldern gebaut:

```text
Dokumenttyp_Korrespondent_Thema_Datum
```

Beispiele:

```text
Rechnung_Amazon_Bueromaterial_2026-05-12
Brief_Finanzamt_Steuerbescheid_2025
Vertrag_Vodafone_Glasfaser
Versicherung_Allianz_KFZ_2026
```

Regeln:

- keine Leerzeichen
- `_` als Trenner
- kein Betrag: `amount` wird weiter extrahiert und in der Review-UI angezeigt,
  steht aber bewusst nicht im Titel, weil Geldbeträge keinen aussagekräftigen
  Dateinamen ergeben
- keine `[Review]`-Praefixe
- keine technischen Workflow-Informationen
- maximale Laenge: 120 Zeichen

`subject` und `document_date` speichert die Queue zusaetzlich in SQLite. Dafuer
gibt es in der Review-UI die Schaltflaeche „Titel aus Feldern neu bauen": Sie
ersetzt den Titel durch das Ergebnis dieser Regel. Ein manuell getippter Titel
wird ohne Klick auf diese Schaltflaeche nie veroendert. Zeilen, die vor diesen
beiden Spalten angelegt wurden, haben kein Thema und kein Datum gespeichert;
ihr neu gebauter Titel enthaelt deshalb nur Dokumenttyp und Korrespondent.

## Konfiguration

Wichtige Variablen:

| Variable | Bedeutung |
| --- | --- |
| `PAPERLESS_URL` | Interne Paperless-URL fuer API-Aufrufe |
| `PAPERLESS_PUBLIC_URL` | Oeffentliche URL fuer Paperless und Links aus der Review-UI |
| `PAPERLESS_TOKEN` | Paperless API-Token |
| `PAPERLESS_HEALTHCHECK_URL` | Abweichende URL fuer den Paperless-Healthcheck, Standard `PAPERLESS_URL` |
| `OLLAMA_URL` | Interne Ollama-URL |
| `OLLAMA_MODEL` | Modellname fuer Klassifikation und Readiness-Check |
| `OLLAMA_NUM_CTX` | Kontextfenster pro Klassifikation, Standard `8192` |
| `OCR_MAX_CHARS` | OCR-Zeichen im Prompt; leer leitet den Wert aus `OLLAMA_NUM_CTX` ab |
| `DB_PATH` | Verzeichnis fuer `documents.db` |
| `AI_WORKER_TRIGGER_URL` | Queue-Trigger des AI-Workers |
| `TRIGGER_PORT` | Port des Trigger-Servers, im Compose-Setup `8080` |
| `CONFIDENCE_THRESHOLD` | Mindestvertrauen fuer Auto-Approval |
| `MIN_TITLE_LENGTH` | Mindestlaenge fuer gueltige Titel |
| `DRY_RUN` | `true` = klassifizieren ohne Paperless-Update. Muss gesetzt sein |
| `REVIEW_UI_USERNAME` | Basic-Auth-Benutzer der Review-UI |
| `REVIEW_UI_PASSWORD` | Basic-Auth-Passwort der Review-UI |
| `REVIEW_UI_PORT` | Port der Review-UI, im Compose-Setup `8090` |
| `QUEUE_POLL_INTERVAL_SECONDS` | Interval fuer den Queue-Claim, Standard `2` |
| `QUEUE_MAX_ATTEMPTS` | Versuche, bevor ein Job `DEAD` wird, Standard `10` |
| `QUEUE_RETRY_BASE_SECONDS` | Basis fuer den exponentiellen Backoff, Standard `30` |
| `QUEUE_RETRY_MAX_SECONDS` | Obergrenze des Backoffs, Standard `1800` |
| `RECONCILE_ENABLED` | `false` deaktiviert den periodischen Reconciliation-Thread; `POST /reconcile` bleibt moeglich |
| `RECONCILE_INITIAL_IMPORT` | `false` (Standard) importiert den vorhandenen Paperless-Bestand nicht automatisch |
| `RECONCILIATION_INTERVAL_SECONDS` | Abstand der Abgleichlaeufe, Standard `600` |
| `RECONCILIATION_START_DELAY_SECONDS` | Startverzoegerung nach dem Hochfahren, Standard `30` |
| `HEALTHCHECK_TIMEOUT_SECONDS` | Timeout der Health-/Ready-Pruefungen, Standard `3` |

`SQLITE_PATH` wird fuer alte Setups weiterhin akzeptiert. Intern verwendet die
App aber `DB_PATH` als Verzeichnis und legt darin `documents.db` an.

### Kontextfenster und lange OCR-Texte

Die Kuerzung des OCR-Textes muss zum Modellfenster passen. Ollama laedt gemma3
standardmaessig mit 4096 Token; ein Steuerbescheid mit rund 9.000 OCR-Zeichen
fuellt das Fenster damit allein, die JSON-Antwort wird nach 42 Token
abgebrochen (`done_reason: length`) und `json.loads` meldet `Unterminated
string` - als Fehlerbild ein `FAILED_LLM` ohne Titel. Deshalb uebergibt der
Worker `num_ctx` aus `OLLAMA_NUM_CTX` (Standard 8192) und leitet daraus das
OCR-Budget ab: `(num_ctx - 1500) * 2.2` Zeichen, bei 8192 also rund 14.700.

Passt die Antwort trotzdem nicht, wird ein zweiter Versuch mit der Haelfte des
Budgets gemacht und erst danach `FAILED_LLM`. Frueher sendete der Client
fuenf mal denselben Prompt, weil `temperature: 0` die Kuerzung reproduziert -
bei 4.000 Eingabe-Token war das spuerbare Rechenzeit ohne neues Ergebnis.

Sichtbar im Betrieb: `docker exec ollama ollama ps` zeigt die tatsaechlich
geladene Kontextgroesse, und `Invalid JSON from Ollama. Output length: ...` im
Worker-Log meldet den Abbruch. Groessere Fenster kosten RAM und CPU-Zeit pro
Dokument, also hochsetzen statt OCR-Texte zu zerhacken, solange die VM es hergibt.

### Bestand nachtraeglich verarbeiten

Standardmaessig bleibt dein Paperless-Bestand unangetastet: Beim ersten
Reconciliation-Lauf merkt sich der Worker in der Tabelle `app_meta` die hoechste
bis dahin vorhandene Paperless-ID (`reconcile_baseline_document_id`) und
ueberspringt alles darunter. Neue Dokumente werden ganz normal per
Post-Consume-Trigger verarbeitet.

Den Bestand holst du gezielt nach, indem du entweder

```bash
scripts/reconcile_missing.sh
```

ausfuehrst (verarbeitet die neuesten fehlenden Dokumente, Page-Size 100), oder
indem du `RECONCILE_INITIAL_IMPORT=true` setzt und neu startest. Fuer eine
weitere Testphase danach zurueck auf `false`; die gesetzte Baseline bleibt
bestehen, bis du `scripts/reset-ai-data.sh` nutzt.

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

Ein Neu-Bauen der Pins auf einem neueren Python als 3.12 schlaegt fehl
(`pydantic-core` hat dafuer keine Wheels); die Pins sind bewusst auf das
Dockerfile-Bild gesetzt.

## Verzeichnisstruktur

```text
.
├── app/
│   ├── main.py               # HTTP-Trigger (/process, /health, /live, /ready, /reconcile)
│   ├── config.py             # zentrale Umgebungskonfiguration
│   ├── document_queue.py     # Single-Worker-Loop ueber der persistenten Queue
│   ├── queue_store.py        # SQLite-Tabelle processing_jobs (Claim, Retry, DEAD)
│   ├── worker.py             # verarbeitet genau ein Dokument pro Aufruf
│   ├── classifier.py         # OCR laden, klassifizieren, Titel bauen, zurueckschreiben
│   ├── models.py             # Datenmodell der Klassifikation
│   ├── prompts.py            # Ollama-Prompts
│   ├── ollama_client.py      # Ollama-Aufrufe
│   ├── paperless_client.py   # Paperless-API-Client
│   ├── validator.py          # Prueft Ergebnisse vor Auto-Apply
│   ├── db.py                 # documents-, review_decisions- und app_meta-Tabelle
│   ├── hash_store.py         # PDF-/OCR-Hashbildung fuer die Duplikaterkennung
│   ├── health.py             # Health- und Readiness-Checks
│   ├── reconciler.py         # periodischer Paperless-Abgleich inkl. Bestandsschutz
│   ├── reconcile_missing.py  # einmaliger, manueller Nachlauf (scripts/reconcile_missing.sh)
│   ├── reprocess.py          # Reprocess/Retry ueber denselben Queue-Trigger
│   ├── review_ui.py          # FastAPI-Review-UI mit Basic-Auth
│   ├── logging_config.py     # Logging-Setup
│   ├── static/
│   └── templates/
├── scripts/
│   ├── post-consume-ai-worker.sh
│   ├── check-env.sh
│   ├── healthcheck.sh
│   ├── ensure-ollama-model.sh
│   ├── backup.sh
│   ├── restore.sh
│   ├── reconcile_missing.sh
│   └── reset-ai-data.sh
├── tests/
├── docker-compose.yml
├── dockerfile
├── .dockerignore
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── GO_LIVE.md
└── P0_README.md
```

## Sicherheit und Betrieb

- `PAPERLESS_TOKEN` und `.env` niemals committen (`.gitignore` deckt `.env` ab)
- `.dockerignore` haelt `.env`, Datenverzeichnisse und `.git` aus dem Image – beim
  Anlegen neuer Build-Kontexte mit `COPY . .` nicht entfernen
- Standardpasswoerter vor dem Betrieb aendern; `scripts/check-env.sh` prueft
  Platzhalterwerte
- Review-UI nicht oeffentlich ins Internet stellen, sie hoert auf `127.0.0.1:8090`
- AI-Worker nur intern im Docker-Netz verwenden, er hat keinen publizierten Port
- SQLite-Datenbank und Paperless-Daten regelmaessig sichern (`scripts/backup.sh`);
  die `.env` ist standardmaessig **nicht** im Archiv, weil sie alle Secrets
  enthaelt. Mit `INCLUDE_ENV_BACKUP=1 scripts/backup.sh` laesst sie sich
  ausdruecklich ergaenzen – das Archiv dann wie einen Secret behandeln
  (`scripts/restore.sh` spielt sie niemals zurueck ein)
- Neue Setups zuerst mit `DRY_RUN=true` testen
- LLM-Ergebnisse stichprobenartig ueber die Review-UI pruefen

## Produktionshinweise

- Die Verarbeitungsqueue ist persistent in SQLite und ueberlebt Container-Neustarts.
- `PROCESSING`-Jobs werden nur beim Start des AI-Workers recovered; ein Healthcheck
  veraendert niemals den Queue-Zustand.
- Reconciliation laeuft periodisch und arbeitet gegen die Paperless-API. Der
  vorhandene Bestand wird dabei nicht automatisch umgetitelt (siehe
  `RECONCILE_INITIAL_IMPORT`).
- Der Abgleich laedt den kompletten Paperless-Dokumentenbestand und prueft jede
  ID gegen SQLite. Ab einigen tausend Dokumenten ist das alle zehn Minuten spuerbar.
- Das konfigurierte Ollama-Modell ist Bestandteil des Readiness-Checks.
- Fuer NAS/SMB/NFS-Consume-Pfade wird Paperless v3 mit Polling betrieben.
- **Netzwerk-Mounts fuer `PAPERLESS_MEDIA_PATH`/`PAPERLESS_DATA_PATH` nur per SMB,
  nie per AFP.** Docker Desktop kann einem AFP-Mount nicht in den Mountpoint
  folgen: Der Bind existiert im Container, zeigt aber ein leeres Verzeichnis,
  obwohl der Host Dateien sieht. Paperless meldet dann 404 beim Download und
  `HTTP 400 [Errno 17] File exists` beim Loeschen, ohne dass ein Fehler im Code
  steckt. Zusaetzlich muss die Freigabe gemountet sein, *bevor* Docker Desktop
  startet, weil die File-Sharing-Views beim Engine-Start aufgebaut werden.
  Prüfen laesst sich das mit zwei Befehlen: `find /Volumes/.../media -type f | wc -l`
  auf dem Host gegen `docker compose exec paperless find /usr/src/paperless/media
  -type f | wc -l`. Beide Zahlen muessen uebereinstimmen. Nach einem Wechsel des
  Protokolls reicht ein Neustart von Docker Desktop; `--force-recreate` allein
  hilft nicht.
- Der SMB-Mount entsteht bei jeder Anmeldung durch ein LaunchAgent
  (`~/Library/LaunchAgents/local.qoder.mount-nas-home.plist`, Skript
  `~/Library/Application Support/nas-mount/mount-nas-home.sh`, Log
  `~/Library/Logs/nas-mount.log`). Bewusst kein Eintrag unter „Anmeldeobjekte →
  Beim Anmelden oeffnen": diese Liste war auf dem Rechner leer, und
  `TALLogoutSavesState=false` schaltet Apples eigenes Wiederverbinden ab - das
  ist der Grund, warum der alte Mount nach jedem Neustart fehlte. Das Skript
  wartet auf Port 445 und mountet per `open "smb://…"`; ein eigenes `mkdir` unter
  `/Volumes` scheitert ohne Root mit „Permission denied", der Finder legt den
  Mountpoint dagegen selbst an. Verifiziert ist der Agent bis auf den Fall „Mount
  fehlt nach dem Boot" (2026-09-21): der laeuft erst beim naechsten echten Login
  los, ein vorheriger Manuelltest war nicht moeglich, ohne die laufende
  Containersicht zu zerstoeren.
- **Die Freigabe nicht neu mounten, waehrend Docker laeuft:** ein Remount der
  SMB-Sitzung entwertet die beim Engine-Start aufgebauten File-Sharing-Views.
  Beobachtet am 2026-09-21: Host sah 14 Dateien, der Container antwortete mit
  `Operation not permitted`. Geholfen hat nur ein Neustart von Docker Desktop.
  Reihenfolge ist also: mounten (macht das LaunchAgent), dann Docker starten.
- `scripts/healthcheck.sh` meldet Protokoll und vergleicht die Dateizahl von Host
  und Container; geloeschte Netzwerkdateien hinterlassen dabei
  `.smbdelete*`/`.afpDeleted*`-Marker, die auf beiden Seiten ausgeblendet werden -
  sonst vergleicht man Muell statt Medien. Bei „Host > 0, Container = 0" ist die
  Freigabe schuld, nicht die Anwendung.
- Geloeschte Dateien hinterlassen auf Netzwerkfreigaben Muell wie
  `.smbdelete*` und `.afpDeleted*`; `scripts/backup.sh` schliesst beide Muster aus.
- Vor dem ersten echten Betrieb mit `DRY_RUN=true` testen und anschliessend ein
  Backup/Restore einmal erfolgreich durchspielen. Getestet am 2026-09-21 mit
  Markern in allen drei Speichern (Datei, SQLite, PostgreSQL): alle drei waren
  nach dem Restore zurueckgerollt, Host- und Container-Sicht auf die Media-Freigabe
  stimmten ueberein.
- `AI_DATA_PATH` und `POSTGRES_DATA_PATH` liegen verschachtelt
  (`./data` und `./data/postgres`). `scripts/backup.sh` haelt den laufenden Cluster
  deshalb aus dem AI-Archiv raus (ein Tar eines laufenden Clusters ist inkonsistent)
  und `scripts/restore.sh` schliesst ihn beim Auspacken zusaetzlich aus - die
  PostgreSQL-Daten kommen ausschliesslich aus `paperless.dump`. Neue Setups sollten
  die beiden Pfade trennen.
- Restore ueber ein Netzwerk-Verzeichnis loescht nicht hart `rm -rf`: SMB/AFP halten
  `.smbdelete*`/`.afpDeleted*`-Marker offen, bis der Client den Handle freigibt, und
  ein Abbruch mitten im Restore waer schlechter als zurueckbleibender Muell.
- Gespeicherte Review-Entscheidungen werden noch nicht automatisch in Prompts
  oder Regeln zurueckgespielt.
- Die Umgebungsvariablen `EXPORT_PATH` und `POLL_INTERVAL` (und damit ein
  Export-Zweig aus frueheren Versionen) sind Altlasten ohne Bezug zum aktuellen
  Codepfad; `app/exporter.py` wurde entfernt. Die Verzeichnisse `export/`,
  `exports/` und `paperless-export/` koennen alte Artefakte enthalten und werden
  vom Stack nicht mehr geschrieben.
