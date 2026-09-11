# AI Documents – P0/P1 Production/Home-Ready

The current tree implements the P0 reliability layer and the main P1 home-production hardening:

1. Persistent SQLite-backed processing queue.
2. Recovery of jobs that were PROCESSING during a container crash/restart.
3. Exponential retry with a configurable maximum attempt count.
4. Periodic Paperless <-> AI database reconciliation.
5. Real health/readiness checks for Paperless, Ollama and SQLite.
6. Immediate trigger retries in the Paperless post-consume script.
7. Automated backup/restore for SQLite, PostgreSQL, Paperless media and data.
8. Ollama model-aware readiness checks.
9. Explicit Paperless v3 secret key and NAS polling/stability configuration.
10. Pinned Paperless/Ollama image versions.
11. Queue safety tests for restart, health-check isolation, force-requeue and retry/dead states.

## Current implementation

The files are already integrated in this repository. The following files contain the production changes:



- `app/config.py`
- `app/main.py`
- `app/document_queue.py`
- `docker-compose.yml`
- `scripts/post-consume-ai-worker.sh`

The classifier, Paperless client and review UI remain unchanged in their core responsibilities.

## Important

The persistent queue uses the existing `./data/documents.db` file. It creates
a new table called `processing_jobs` and is compatible with the existing
SQLite database layer.

On startup:

- PROCESSING jobs are reset to QUEUED.
- The worker resumes pending jobs.
- After the initial delay, reconciliation scans Paperless and queues documents
  that have not reached a final AI status.

Failed jobs use exponential backoff:

- 30 seconds
- 60 seconds
- 120 seconds
- ...
- capped by `QUEUE_RETRY_MAX_SECONDS`

After `QUEUE_MAX_ATTEMPTS`, a job becomes `DEAD`. The existing Review UI can
still be used to inspect/retry the corresponding failed document.

## Recommended .env additions

```env
DB_PATH=/data

QUEUE_POLL_INTERVAL_SECONDS=2
QUEUE_MAX_ATTEMPTS=10
QUEUE_RETRY_BASE_SECONDS=30
QUEUE_RETRY_MAX_SECONDS=1800

RECONCILIATION_INTERVAL_SECONDS=600
RECONCILIATION_START_DELAY_SECONDS=30

HEALTHCHECK_TIMEOUT_SECONDS=3
```

## Test after deployment

```bash
docker compose up -d --build

curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/ready
curl http://127.0.0.1:8080/live
```

Manual reconciliation:

```bash
curl -X POST http://127.0.0.1:8080/reconcile
```

The trigger remains:

```bash
curl -X POST http://127.0.0.1:8080/process \
  -H 'Content-Type: application/json' \
  -d '{"document_id": 123}'
```

## Crash recovery test

1. Queue a document.
2. While it is processing, run:
   `docker compose restart ai-worker`
3. Start the container again.
4. Check `/health`.
5. The job should return to QUEUED and be processed.

## Backup

Make the script executable:

```bash
chmod +x scripts/backup.sh
```

Run:

```bash
./scripts/backup.sh
```

Recommended: execute it once per day with the Synology Task Scheduler or host
cron. Store the `backups/` directory on a different physical storage target
if possible.

## One deliberate design choice

Paperless remains the source of truth. Reconciliation does not overwrite
Paperless metadata; it only finds documents that have no final AI processing
state and puts them into the persistent queue.
