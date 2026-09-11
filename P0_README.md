# AI Documents – P0 Home/Production Hardening

This package is designed for the current `phoenix1812/ai_documents` architecture. Paperless remains the source of truth; AI workflow state is stored locally in SQLite.

## What P0 adds

1. Persistent SQLite job queue (`jobs`).
2. Recovery of stale `PROCESSING` jobs after an AI-worker restart.
3. Exponential retry/backoff for transient worker failures.
4. Periodic Paperless reconciliation.
5. Safe initial baseline: existing Paperless documents are NOT imported automatically when `RECONCILE_INITIAL_IMPORT=false`.
6. `/health` and `/ready` endpoints.
7. Docker healthcheck.
8. Manual `/reconcile` endpoint; use `?include_existing=true` only when you intentionally want to import existing Paperless documents.
9. Backup script for SQLite + PostgreSQL + Paperless data/media.
10. Reset script that deletes only AI SQLite state and leaves Paperless intact.

## Files to copy

Replace these files in the repository:

- `app/db.py`
- `app/config.py`
- `app/document_queue.py`
- `app/worker.py`
- `app/main.py`
- `docker-compose.yml`
- `scripts/post-consume-ai-worker.sh`

Add:

- `app/queue_store.py`
- `app/reconciler.py`
- `app/health.py`
- `scripts/backup.sh`
- `scripts/reset-ai-data.sh`
- `P0.env.example`

Do not delete or replace the existing classifier, review UI, Paperless client, Ollama client, validator, templates, or static assets.

## Clean initial start

If the intention is a completely empty AI state while keeping all Paperless documents:

```bash
chmod +x scripts/reset-ai-data.sh scripts/backup.sh
./scripts/reset-ai-data.sh
```

The reset removes:

- `data/documents.db`
- `data/documents.db-wal`
- `data/documents.db-shm`

It does NOT remove PostgreSQL, Paperless media, Paperless data, Redis, or Ollama models.

After startup the SQLite database will contain the empty tables:

- `documents`
- `review_decisions`
- `jobs`
- `app_meta`

## Initial reconciliation behaviour

With:

```text
RECONCILE_INITIAL_IMPORT=false
```

the first reconciliation only establishes a baseline. Existing Paperless documents are not queued.

New documents continue to be queued by the Paperless post-consume hook. The periodic reconciler also catches documents created after the baseline if a trigger was missed while the AI worker was unavailable.

To deliberately import ALL existing Paperless documents, use:

```bash
curl -X POST 'http://127.0.0.1:8080/reconcile?include_existing=true'
```

## Verify the database

```bash
docker exec ai-worker python -c "import sqlite3; c=sqlite3.connect('/data/documents.db'); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall())"
```

Expected:

```text
app_meta
 documents
 jobs
 review_decisions
 sqlite_sequence
```

## Health

```bash
curl http://127.0.0.1:8080/health
curl -i http://127.0.0.1:8080/ready
```

`/health` is a local process/database health endpoint. `/ready` also checks Paperless and Ollama.

## Crash recovery test

1. Trigger a document:

```bash
curl -X POST http://127.0.0.1:8080/process \\
  -H 'Content-Type: application/json' \\
  -d '{"document_id": 123}'
```

2. Check the job:

```bash
docker exec ai-worker python -c "import sqlite3; c=sqlite3.connect('/data/documents.db'); c.row_factory=sqlite3.Row; print([dict(r) for r in c.execute(\"SELECT * FROM jobs ORDER BY id DESC LIMIT 5\")])"
```

3. During processing restart the worker:

```bash
docker restart ai-worker
```

4. The job must reappear as `QUEUED`/`PROCESSING` and finish. It must not disappear.

## Ollama outage test

Stop Ollama, trigger a document, and inspect `jobs`:

```bash
docker stop ollama
curl -X POST http://127.0.0.1:8080/process -H 'Content-Type: application/json' -d '{"document_id": 123}'
```

The job should enter `RETRY` with a future `available_at` value. Start Ollama again:

```bash
docker start ollama
```

The worker should retry automatically.

## Backup

Run from the repository root:

```bash
./scripts/backup.sh
```

The script creates a compressed backup containing AI SQLite state, a PostgreSQL dump, and Paperless data/media when the configured host directories exist.

## Important

Do not expose the AI worker to the public Internet. The supplied compose file binds it to `127.0.0.1:8080` on the host. Paperless reaches it internally through `http://ai-worker:8080/process`.
