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
12. Stock protection: `RECONCILE_ENABLED` and `RECONCILE_INITIAL_IMPORT` are read by
    the reconciler, and `.dockerignore` keeps `.env` and host data out of the build image.

## Current implementation

The files are already integrated in this repository. The following files contain the production changes:

- `app/config.py`
- `app/main.py`
- `app/document_queue.py`
- `app/queue_store.py`
- `app/health.py`
- `app/reconciler.py`
- `app/db.py`
- `docker-compose.yml`
- `.dockerignore`
- `scripts/post-consume-ai-worker.sh`
- `scripts/check-env.sh`

The classifier, Paperless client and review UI remain unchanged in their core responsibilities.

## Important

The persistent queue uses the existing `./data/documents.db` file. It creates
a new table called `processing_jobs` and is compatible with the existing
SQLite database layer. Reconciliation stores its stock baseline in a second new
table, `app_meta`.

On startup:

- PROCESSING jobs are reset to QUEUED.
- The worker resumes pending jobs.
- After the initial delay, reconciliation scans Paperless and queues documents
  that have not reached a final AI status — but only above the baseline ID that
  `RECONCILE_INITIAL_IMPORT=false` freezes on the first cycle.

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

RECONCILE_ENABLED=true
RECONCILE_INITIAL_IMPORT=false
RECONCILIATION_INTERVAL_SECONDS=600
RECONCILIATION_START_DELAY_SECONDS=30

HEALTHCHECK_TIMEOUT_SECONDS=3
```

## Test after deployment

The trigger server has no published host port, so run these from inside the
Docker network:

```bash
docker compose up -d --build

docker compose exec paperless curl -fsS http://ai-worker:8080/health
docker compose exec paperless curl -fsS http://ai-worker:8080/ready
docker compose exec paperless curl -fsS http://ai-worker:8080/live
```

Manual reconciliation:

```bash
docker compose exec paperless curl -fsS -X POST http://ai-worker:8080/reconcile
```

The trigger remains:

```bash
docker compose exec paperless curl -fsS -X POST http://ai-worker:8080/process \
  -H 'Content-Type: application/json' \
  -d '{"document_id": 123}'
```

## Crash recovery test

1. Queue a document.
2. While it is processing, run:
   `docker compose restart ai-worker`
3. Start the container again.
4. Check `/health` (see the `docker compose exec` form above).
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
if possible. The archive includes `env.backup`, so it contains every secret in
`.env` and must be stored accordingly.

## Deliberate design choices

Paperless remains the source of truth. Reconciliation does not overwrite
Paperless metadata; it only finds documents that have no final AI processing
state and puts them into the persistent queue.

"Final" depends on the active mode. In live mode (`DRY_RUN=false`) a `DRY_RUN`
row is not final, so documents that were only classified during the test phase
are picked up again and written for real.

With `RECONCILE_INITIAL_IMPORT=false`, the highest Paperless ID present at the
first reconciliation cycle is stored in `app_meta` and permanently excluded from
automatic processing. An existing archive is therefore never retitled by a
background thread; `scripts/reconcile_missing.sh` stays the explicit opt-in.
