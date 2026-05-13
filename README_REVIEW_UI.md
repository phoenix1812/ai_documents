# Review UI Patch

## Enthalten

- `app/review_ui.py`
- `app/templates/review_list.html`
- `app/templates/review_detail.html`
- `app/static/review.css`
- aktualisierte `requirements.txt`
- Docker-Compose-Snippet für `ai-review-ui`
- Hinweis für `app/config.py`

## Einbau

### 1. Dateien kopieren

Kopiere die Ordner und Dateien aus diesem Patch in dein Repo.

### 2. requirements.txt ersetzen

Die neue `requirements.txt` enthält zusätzlich:

- fastapi
- uvicorn
- jinja2
- python-multipart

### 3. config.py ergänzen

In `Settings.__init__()` ergänzen:

```python
# Review UI
self.review_ui_port = int(
    os.getenv(
        "REVIEW_UI_PORT",
        "8090",
    )
)
```

### 4. docker-compose.yml erweitern

Den Inhalt aus `docker-compose.review-ui-snippet.yml` unter `services:` einfügen.

### 5. Container neu bauen

```bash
docker compose down
docker compose up -d --build
```

### 6. UI öffnen

```text
http://localhost:8090
```

## Was die UI kann

- `NEEDS_REVIEW` anzeigen
- `DRY_RUN` anzeigen
- Details ansehen
- Eintrag ablehnen
- Eintrag freigeben
- optional den Titel direkt nach Paperless übernehmen

## Einschränkung

Aktuell wird beim Übernehmen nach Paperless nur der Titel gesetzt.

Warum?

Paperless-ngx erwartet für Tags, Dokumenttypen und Korrespondenten meistens IDs.
Dafür brauchen wir als nächsten Schritt ein Mapping:

- Name → Tag-ID
- Name → Document-Type-ID
- Name → Correspondent-ID
