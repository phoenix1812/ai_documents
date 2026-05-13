# AI Documents

AI Documents ist ein lokaler, eventbasierter Dokumenten-Klassifizierer für **paperless-ngx**.

Nach dem Import eines Dokuments ruft Paperless einen Post-Consume-Hook auf. Dieser triggert einen kleinen Python-HTTP-Service, der das Dokument aus Paperless lädt, den OCR-Text mit **Ollama** klassifiziert, das Ergebnis validiert und die Metadaten direkt in Paperless aktualisiert.

Paperless bleibt dabei die **Single Source of Truth**. PDFs werden nicht mehr zusätzlich exportiert.

---

## Features

- Eventbasierte Verarbeitung über Paperless `POST_CONSUME_SCRIPT`
- Lokale LLM-Klassifizierung über Ollama
- Paperless als zentrale Dokumentenablage
- Automatisches Setzen von Paperless-Metadaten:
  - Titel
  - Korrespondent
  - Dokumenttyp
  - fachliche Tags
- Serverseitige Titelgenerierung mit `_` statt Leerzeichen
- Keine Review- oder Workflow-Tags in Paperless
- Review-Status ausschließlich in SQLite und Review-UI
- Duplikaterkennung per SHA256-Dateihash
- Persistenter Verarbeitungsstatus in SQLite
- Docker-Compose-Setup mit Paperless, PostgreSQL, Redis, Ollama, AI-Worker und Review-UI

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
  +--> Paperless API: Dokument + OCR + PDF-Bytes laden
  +--> SHA256: Duplikate erkennen
  +--> Ollama: OCR-Text klassifizieren
  +--> classifier.py: stabilen Titel bauen
  +--> Validator: Ergebnis prüfen
  +--> Paperless API: Metadaten aktualisieren
  +--> SQLite: Status für Review-UI protokollieren
```

---

## Wichtige Designentscheidung

Paperless speichert nur fachliche Dokumenten-Metadaten:

```text
Titel
Korrespondent
Dokumenttyp
fachliche Tags
```

Workflow-Zustände bleiben in der lokalen SQLite-Datenbank:

```text
AUTO_APPROVED
DONE
DRY_RUN
IGNORED
MANUALLY_APPROVED
NEEDS_REVIEW
REVIEW_REQUIRED
```

Dadurch landen keine technischen Tags wie `ai_review`, `needs-ai-review` oder `review` in Paperless.

---

## Titel-Format

Der finale Paperless-Titel wird serverseitig gebaut, nicht direkt vom LLM übernommen.

Schema:

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
- keine `[Review]`-Präfixe
- keine technischen Workflow-Informationen im Titel
- maximale Länge: 120 Zeichen

---

## Verzeichnisstruktur

```text
.
├── app/
│   ├── main.py
│   ├── worker.py
│   ├── classifier.py
│   ├── paperless_client.py
│   ├── ollama_client.py
│   ├── validator.py
│   ├── db.py
│   ├── models.py
│   ├── prompts.py
│   └── logging_config.py
├── scripts/
│   └── post-consume-ai-worker.sh
├── tests/
│   └── test_classifier.py
├── docker-compose.yml
├── dockerfile
├── requirements.txt
└── .env.example
```

Hinweis: `app/exporter.py` wird für diese Variante nicht mehr benötigt, weil keine PDFs mehr exportiert werden.

---

## Voraussetzungen

- Docker und Docker Compose
- Ein lokal lauffähiges Ollama-Modell
- Paperless API Token

Empfohlenes Modell für den Start:

```bash
docker exec -it ollama ollama pull llama3
```

Alternativ kannst du kleinere oder spezialisierte Modelle verwenden, z. B. `llama3.1`, `mistral`, `qwen2.5` oder ein deutschsprachig stärkeres Modell.

---

## Konfiguration

Lege im Projektverzeichnis eine `.env` Datei an. Du kannst `.env.example` kopieren:

```bash
cp .env.example .env
```

Beispiel:

```env
PAPERLESS_URL=http://paperless:8000
PAPERLESS_PUBLIC_URL=http://localhost:8000
PAPERLESS_TOKEN=DEIN_PAPERLESS_API_TOKEN
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=llama3
DB_PATH=/data
CONFIDENCE_THRESHOLD=0.75
MIN_TITLE_LENGTH=8
DRY_RUN=false
TRIGGER_PORT=8080
REVIEW_UI_PORT=8090
```

### Wichtige Variablen

| Variable | Beschreibung | Standard |
|---|---|---|
| `PAPERLESS_URL` | interne Paperless-URL im Docker-Netzwerk | `http://localhost:8000` |
| `PAPERLESS_PUBLIC_URL` | URL für Links in der Review-UI | Wert von `PAPERLESS_URL` |
| `PAPERLESS_TOKEN` | Paperless API Token | leer |
| `OLLAMA_URL` | Ollama API URL | `http://ollama:11434` |
| `OLLAMA_MODEL` | Modell für Klassifizierung | `llama3` |
| `DB_PATH` | Pfad für SQLite-Datenbank | `/data` |
| `CONFIDENCE_THRESHOLD` | Mindestvertrauen für Auto-Approval | `0.75` |
| `MIN_TITLE_LENGTH` | Mindestlänge für automatisch akzeptierte Titel | `8` |
| `DRY_RUN` | Klassifizierung speichern, aber Paperless nicht ändern | `false` |
| `TRIGGER_PORT` | Port des AI-Worker HTTP-Servers | `8080` |
| `REVIEW_UI_PORT` | Port der Review-UI | `8090` |

---

## Start

```bash
docker compose up -d --build
```

Danach Paperless öffnen:

```text
http://localhost:8000
```

Review-UI öffnen:

```text
http://localhost:8090
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

## Review-Logik

Ein Dokument landet in der Review-UI, wenn z. B.:

- die Confidence zu niedrig ist
- der Titel zu kurz oder generisch ist
- Platzhalter wie `Unbekannt`, `Unbenannt`, `Sonstiges` verwendet wurden
- der Dokumenttyp nicht zur erlaubten Taxonomie passt
- ein technischer Workflow-Tag erkannt wurde

Wichtig: Der Review-Zustand wird nicht in Paperless geschrieben. Es gibt also kein `ai_review`-Tag und kein `[Review]` im Titel.

---

## Erlaubte Dokumenttypen

Aktuell sind folgende Dokumenttypen vorgesehen:

- `Rechnung`
- `Vertrag`
- `Versicherung`
- `Steuer`
- `Bank`
- `Sonstiges`

Die Liste kann in `app/validator.py` und `app/prompts.py` angepasst werden.

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

---

## Sicherheitshinweise

- `PAPERLESS_TOKEN` niemals committen
- Standardpasswörter ändern
- SQLite-Datenbank regelmäßig sichern
- Den AI-Worker nicht öffentlich ins Internet stellen
- LLM-Ausgaben immer validieren, bevor Metadaten geändert werden
- Paperless bleibt die primäre Dokumentenablage

---

## Status

Das Projekt ist ein funktionaler Prototyp für lokale, KI-gestützte Dokumentenklassifizierung mit Paperless und Ollama.
