# AI Documents

AI Documents ist ein lokaler, eventbasierter Dokumenten-Klassifizierer für **paperless-ngx**.
Nach dem Import eines Dokuments ruft Paperless einen Post-Consume-Hook auf. Dieser triggert einen kleinen Python-HTTP-Service, der das Dokument aus Paperless lädt, den OCR-Text mit **Ollama** klassifiziert, das Ergebnis validiert und die Metadaten direkt in Paperless schreibt.

**Paperless ist die Single Source of Truth.** PDFs werden nicht mehr in einen separaten Exportordner kopiert.

---

## Features

- Eventbasierte Verarbeitung über Paperless `POST_CONSUME_SCRIPT`
- Lokale LLM-Klassifizierung über Ollama
- Schreibt Titel, Korrespondent, Dokumenttyp und Tags direkt nach Paperless
- Review-Markierung über Paperless-Tag `needs-ai-review`
- Duplikaterkennung per SHA256-Dateihash
- Persistenter Verarbeitungsstatus in SQLite
- Docker-Compose-Setup mit Paperless, PostgreSQL, Redis, Ollama und AI-Worker
- Minimaler Healthcheck-Endpunkt
- Review UI für Korrekturen und erneutes Anwenden auf Paperless

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
  |--> Paperless API: Dokument + OCR + PDF-Download nur für Hash laden
  |--> SHA256: Duplikate erkennen
  |--> Ollama: OCR-Text klassifizieren
  |--> Validator: Ergebnis prüfen
  |--> Paperless API: Metadaten aktualisieren
  |--> SQLite: Status protokollieren
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
- Ausreichend Speicherplatz für Paperless und Ollama-Modelle

Empfohlenes Modell für den Start:

```bash
docker exec -it ollama ollama pull llama3
```

Alternativ kannst du kleinere oder spezialisierte Modelle verwenden, z. B. `llama3.1`, `mistral`, `qwen2.5` oder ein deutschsprachig stärkeres Modell.

---

## Konfiguration

Lege im Projektverzeichnis eine `.env` Datei an. Als Vorlage kannst du `.env.example` verwenden:

```env
PAPERLESS_URL=http://paperless:8000
PAPERLESS_PUBLIC_URL=http://localhost:8000
PAPERLESS_TOKEN=DEIN_PAPERLESS_API_TOKEN
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3
DB_PATH=/data
CONFIDENCE_THRESHOLD=0.75
MIN_TITLE_LENGTH=8
TRIGGER_PORT=8080
REVIEW_UI_PORT=8090
DRY_RUN=false
```

### Wichtige Variablen

| Variable | Beschreibung | Standard |
|---|---|---|
| `PAPERLESS_URL` | Interne URL der Paperless-Instanz | `http://localhost:8000` |
| `PAPERLESS_PUBLIC_URL` | URL für Links in der Review UI | Wert von `PAPERLESS_URL` |
| `PAPERLESS_TOKEN` | Paperless API Token | leer |
| `OLLAMA_URL` | Ollama API URL | `http://ollama:11434` |
| `OLLAMA_MODEL` | Modell für Klassifizierung | `llama3` |
| `DB_PATH` | Pfad für SQLite-Datenbank | `/data` |
| `CONFIDENCE_THRESHOLD` | Mindestvertrauen für Auto-Approval | `0.75` |
| `MIN_TITLE_LENGTH` | Mindestlänge für automatisch akzeptierte Titel | `8` |
| `TRIGGER_PORT` | Port des AI-Worker HTTP-Servers | `8080` |
| `REVIEW_UI_PORT` | Port der Review UI | `8090` |
| `DRY_RUN` | Klassifizieren ohne Paperless-Metadaten zu ändern | `false` |

---

## Start

```bash
docker compose up -d --build
```

Danach Paperless öffnen:

```text
http://localhost:8000
```

Die Admin-Zugangsdaten solltest du über `.env` setzen:

```env
PAPERLESS_ADMIN_USER=admin
PAPERLESS_ADMIN_PASSWORD=ein-sicheres-passwort
POSTGRES_PASSWORD=ein-sicheres-db-passwort
```

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

## Paperless als Single Source of Truth

Valide Klassifizierungen werden direkt in Paperless geschrieben:

- Titel
- Korrespondent
- Dokumenttyp
- Tags

Unsichere Klassifizierungen werden nicht exportiert. Sie erhalten in Paperless:

- Titelpräfix `[Review]`
- Tag `needs-ai-review`
- optional bereits erkannte Metadaten wie Korrespondent, Dokumenttyp und Tags

Ein Dokument landet im Review, wenn z. B.:

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

## Sicherheitshinweise

- `PAPERLESS_TOKEN` niemals committen
- Standardpasswörter ändern
- SQLite-Datenbank regelmäßig sichern
- Den AI-Worker nicht öffentlich ins Internet stellen
- LLM-Ausgaben immer validieren, bevor Metadaten automatisch geändert werden

---

## Status

Das Projekt ist ein funktionaler Prototyp für lokale, KI-gestützte Dokumentenklassifizierung mit Paperless und Ollama.
Für produktiven Einsatz sollten Tests, Konfigurationsvalidierung, Secrets-Handling und Monitoring weiter ausgebaut werden.
