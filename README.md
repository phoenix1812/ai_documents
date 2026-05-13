# AI Documents

AI Documents ist ein lokaler, eventbasierter Dokumenten-Klassifizierer für **paperless-ngx**.  
Nach dem Import eines Dokuments ruft Paperless einen Post-Consume-Hook auf. Dieser triggert einen kleinen Python-HTTP-Service, der das Dokument aus Paperless lädt, den OCR-Text mit **Ollama** klassifiziert, das Ergebnis validiert und die PDF-Datei strukturiert exportiert.

Das Ziel: Dokumente automatisch, lokal und ohne Cloud-Kosten vorsortieren.

---

## Features

- Eventbasierte Verarbeitung über Paperless `POST_CONSUME_SCRIPT`
- Lokale LLM-Klassifizierung über Ollama
- Strukturierter Export nach Dokumenttyp und Korrespondent
- Review-Ordner für unsichere Klassifizierungen
- Duplikaterkennung per SHA256-Dateihash
- Persistenter Verarbeitungsstatus in SQLite
- Docker-Compose-Setup mit Paperless, PostgreSQL, Redis, Ollama und AI-Worker
- Minimaler Healthcheck-Endpunkt
- Basistest für das Klassifizierungsmodell

---

## Architektur

```text
paperless-ngx
    |
    | post-consume script
    v
scripts/post-consume-ai-worker.sh
    |
    | POST /process {"document_id": ...}
    v
app/main.py
    |
    v
app/worker.py
    |
    v
app/classifier.py
    |
    +--> Paperless API: Dokument + OCR + PDF laden
    +--> SHA256: Duplikate erkennen
    +--> Ollama: OCR-Text klassifizieren
    +--> Validator: Ergebnis prüfen
    +--> Exporter: PDF speichern
    +--> SQLite: Status protokollieren
```

---

## Verzeichnisstruktur

```text
.
├── app/
│   ├── main.py              # HTTP-Trigger-Server
│   ├── worker.py            # Eventbasierter Worker
│   ├── classifier.py        # Hauptpipeline für Dokumentverarbeitung
│   ├── paperless_client.py  # Paperless-ngx API Client
│   ├── ollama_client.py     # Ollama Client
│   ├── validator.py         # Validierung der LLM-Ergebnisse
│   ├── exporter.py          # Exportpfade und Dateinamen
│   ├── db.py                # SQLite-Statusdatenbank
│   ├── models.py            # Pydantic-Modelle
│   ├── prompts.py           # System- und User-Prompts
│   └── logging_config.py    # Logging-Konfiguration
├── scripts/
│   └── post-consume-ai-worker.sh
├── tests/
│   └── test_classifier.py
├── docker-compose.yml
├── dockerfile
└── requirements.txt
```

---

## Voraussetzungen

- Docker und Docker Compose
- Ein lokal lauffähiges Ollama-Modell
- Ausreichend Speicherplatz für Paperless, Export und Ollama-Modelle

Empfohlenes Modell für den Start:

```bash
docker exec -it ollama ollama pull llama3
```

Alternativ kannst du kleinere oder spezialisierte Modelle verwenden, z. B. `llama3.1`, `mistral`, `qwen2.5` oder ein deutschsprachig stärkeres Modell.

---

## Konfiguration

Lege im Projektverzeichnis eine `.env` Datei an:

```env
PAPERLESS_URL=http://paperless:8000
PAPERLESS_TOKEN=DEIN_PAPERLESS_API_TOKEN

OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3

EXPORT_PATH=/exports
DB_PATH=/data

CONFIDENCE_THRESHOLD=0.75
MIN_TITLE_LENGTH=8

TRIGGER_PORT=8080
```

### Wichtige Variablen

| Variable | Beschreibung | Standard |
|---|---|---|
| `PAPERLESS_URL` | URL der Paperless-Instanz | `http://localhost:8000` |
| `PAPERLESS_TOKEN` | Paperless API Token | leer |
| `OLLAMA_URL` | Ollama API URL | `http://ollama:11434` |
| `OLLAMA_MODEL` | Modell für Klassifizierung | `llama3` |
| `EXPORT_PATH` | Zielordner für exportierte PDFs | `/exports` |
| `DB_PATH` | Pfad für SQLite-Datenbank | `/data` |
| `CONFIDENCE_THRESHOLD` | Mindestvertrauen für Auto-Export | `0.75` |
| `MIN_TITLE_LENGTH` | Mindestlänge für automatisch akzeptierte Titel | `8` |
| `TRIGGER_PORT` | Port des AI-Worker HTTP-Servers | `8080` |

---

## Start

```bash
docker compose up -d --build
```

Danach Paperless öffnen:

```text
http://localhost:8000
```

Standardwerte aus `docker-compose.yml`:

```text
Benutzer: admin
Passwort: changeme
```

> Für produktive Nutzung solltest du diese Zugangsdaten unbedingt ändern.

---

## Verarbeitung testen

Healthcheck:

```bash
curl http://localhost:8080/health
```

Ein einzelnes Dokument manuell triggern:

```bash
curl -X POST http://localhost:8080/process \
  -H "Content-Type: application/json" \
  -d '{"document_id": 123}'
```

Alternativ per Query-Parameter:

```bash
curl -X POST "http://localhost:8080/process?document_id=123"
```

---

## Exportlogik

Valide Klassifizierungen werden so abgelegt:

```text
exports/
└── <document_type>/
    └── <correspondent>/
        └── <title>_<tag1>_<tag2>.pdf
```

Unsichere Klassifizierungen landen im Review-Ordner:

```text
exports/
└── _REVIEW/
    └── 2026-05-13_review_doc-123_low_confidence_a1b2c3d4.pdf
```

Ein Dokument wird in den Review verschoben, wenn z. B.:

- die Confidence zu niedrig ist
- der Titel zu kurz ist
- Platzhalter wie `Unbekannt`, `Unbenannt`, `Sonstiges` verwendet wurden
- der Dokumenttyp nicht zur erlaubten Taxonomie passt

---

## Erlaubte Dokumenttypen

Aktuell sind folgende Dokumenttypen vorgesehen:

- `Rechnung`
- `Vertrag`
- `Versicherung`
- `Steuer`
- `Bank`
- `Sonstiges`

Die Liste kann in `app/validator.py` angepasst werden.

---

## Entwicklung

### Abhängigkeiten lokal installieren

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Unter Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Tests ausführen

```bash
pytest
```

Falls `pytest` noch nicht in den Anforderungen enthalten ist:

```bash
pip install pytest
pytest
```

---

## Verbesserungsideen

### Kurzfristig

- `.env.example` ergänzen
- `pytest`, `ruff` und `mypy` in die Dev-Abhängigkeiten aufnehmen
- GitHub Actions für Tests und Linting einrichten
- Dockerfile härten: Non-root User, Healthcheck, gepinnte Base-Image-Version
- Paperless Admin-Passwort nicht fest in `docker-compose.yml` hinterlegen
- Konfiguration mit Pydantic Settings statt manueller `os.getenv`-Logik
- Tests für Validator, Exporter, DB und Clients ergänzen
- Timeouts, Retry-Verhalten und Fehlerstatus genauer testen

### Mittelfristig

- Taxonomie konfigurierbar machen, z. B. über YAML/JSON
- Paperless-Metadaten vollständig setzen: Korrespondent, Dokumenttyp, Tags
- Mapping von Namen zu Paperless-IDs implementieren
- Review-Dashboard oder CLI für unsichere Dokumente bauen
- Feedback-Loop: manuelle Korrekturen speichern und für bessere Prompts nutzen
- Batch-Modus für bereits vorhandene Paperless-Dokumente
- Reprocessing-Funktion für fehlgeschlagene Dokumente
- Bessere Statusübersicht über SQLite oder kleine Web-UI

### Langfristig

- Mehrstufige Klassifizierung:
  1. Dokumenttyp erkennen
  2. Korrespondent extrahieren
  3. Titel und Datum ableiten
  4. Tags bestimmen
- OCR-Qualitätsbewertung vor der Klassifizierung
- Optionales Embedding/RAG-System für ähnliche Dokumente
- Regelbasierte Vorfilter für bekannte Absender
- Automatische Datums-, Betrags- und Vertragsnummernextraktion
- Multi-Tenant- oder Familien-/Haushaltsprofile
- Backup- und Exportstrategie für Datenbank und Klassifizierungshistorie

---

## Sicherheitshinweise

- `PAPERLESS_TOKEN` niemals committen
- Standardpasswörter ändern
- Exportordner und SQLite-Datenbank regelmäßig sichern
- Den AI-Worker nicht öffentlich ins Internet stellen
- LLM-Ausgaben immer validieren, bevor Dateien automatisch verschoben oder Metadaten geändert werden

---

## Status

Das Projekt ist ein funktionaler Prototyp für lokale, KI-gestützte Dokumentenklassifizierung mit Paperless und Ollama.  
Für produktiven Einsatz sollten Tests, Konfigurationsvalidierung, Secrets-Handling und Monitoring weiter ausgebaut werden.

---

## Lizenz

Aktuell ist keine Lizenzdatei im Repository enthalten.  
Wenn das Projekt öffentlich weiterentwickelt werden soll, sollte eine passende Lizenz ergänzt werden, z. B. MIT, Apache-2.0 oder GPL-3.0.
