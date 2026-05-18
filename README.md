# AI Documents

AI Documents ist ein lokaler, eventbasierter Dokumenten-Klassifizierer für **paperless-ngx**.

Nach dem Import eines Dokuments ruft Paperless einen Post-Consume-Hook auf. Dieser triggert einen kleinen Python-HTTP-Service, der das Dokument aus Paperless lädt, den OCR-Text mit **Ollama** klassifiziert, das Ergebnis validiert und die Metadaten direkt in Paperless aktualisiert.

Paperless bleibt dabei die **Single Source of Truth**. PDFs werden nicht zusätzlich exportiert.

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
- Verarbeitung über eine zentrale Single-Worker-Queue
- Duplikaterkennung per PDF-SHA256
- Zusätzliche wahrscheinliche Duplikaterkennung per normalisiertem OCR-SHA256
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
  | enqueue(document_id)
  v
app/document_queue.py
  |
  | exactly one document at a time
  v
app/worker.py
  |
  v
app/classifier.py
  |
  +--> Paperless API: Dokument + OCR + PDF-Bytes laden
  +--> PDF-SHA256: exakte Duplikate erkennen
  +--> OCR-SHA256: wahrscheinliche Duplikate erkennen
  +--> Ollama: OCR-Text klassifizieren
  +--> classifier.py: stabilen Titel bauen
  +--> Validator: Ergebnis prüfen
  +--> Paperless API: Metadaten aktualisieren
  +--> SQLite: Status für Review-UI protokollieren
```

---

## Queue-Verarbeitung

`/process` startet keinen eigenen Thread pro Dokument mehr. Stattdessen wird die `document_id` in eine zentrale Queue gelegt.

Vorteile:

- keine parallelen Ollama-Aufrufe
- weniger SQLite-Lock-Probleme
- keine Race Conditions beim gleichen Dokument
- Paperless bekommt sofort HTTP `202 Accepted`
- die Verarbeitung läuft trotzdem asynchron weiter

Der Healthcheck zeigt den Queue-Zustand:

```bash
curl http://localhost:8080/health
```

Beispiel:

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

---

## Duplikaterkennung

Es gibt jetzt zwei Stufen:

### 1. Exaktes Duplikat per PDF-Hash

```text
sha256(PDF-Bytes)
```

Erkennt identische Dateien.

### 2. Wahrscheinliches Duplikat per OCR-Hash

```text
sha256(normalisierter OCR-Text)
```

Erkennt Fälle, in denen die PDF-Datei anders ist, aber der Text praktisch gleich bleibt, z. B.:

- neu gescannte Kopie
- andere PDF-Kompression
- neu erzeugte PDF-Datei mit gleichem Inhalt

In SQLite werden zusätzlich gespeichert:

```text
ocr_hash
duplicate_of_paperless_id
duplicate_reason
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
SKIPPED_DUPLICATE
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

## Start

```bash
docker compose up -d --build
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

## Sicherheitshinweise

- `PAPERLESS_TOKEN` niemals committen
- Standardpasswörter ändern
- SQLite-Datenbank regelmäßig sichern
- Den AI-Worker nicht öffentlich ins Internet stellen
- LLM-Ausgaben immer validieren, bevor Metadaten geändert werden
- Paperless bleibt die primäre Dokumentenablage
