# AI Documents – Home Go-Live (P0/P1)

This checklist is for the private home deployment on the Mac with Paperless storage on local/NAS paths.

## 1. Before changing the running stack

```bash
docker compose ps
docker compose images
```

Confirm the currently running Paperless version before accepting the pinned `3.1.3` image. Paperless v3 upgrades require a compatible 2.20.15 starting point.

## 2. Configure `.env`

```bash
cp .env.example .env
```

Set real values for:

- `POSTGRES_PASSWORD`
- `PAPERLESS_ADMIN_PASSWORD`
- `PAPERLESS_SECRET_KEY`
- `PAPERLESS_TOKEN`
- `REVIEW_UI_PASSWORD`
- `PAPERLESS_PUBLIC_URL`
- `PAPERLESS_CONSUME_PATH`
- `PAPERLESS_DATA_PATH`
- `PAPERLESS_MEDIA_PATH`

For the NAS consume path, use the final mounted macOS path, for example `/Volumes/...`, and keep polling enabled.

## 3. Validate the host configuration

```bash
scripts/check-env.sh
```

This must pass before starting the stack.

## 4. Start Ollama and install the configured model

```bash
scripts/ensure-ollama-model.sh
```

The model named by `OLLAMA_MODEL` must appear in `ollama list`.

## 5. Start/rebuild the stack

```bash
docker compose up -d --build
```

Then:

```bash
scripts/healthcheck.sh
```

The AI worker `/ready` endpoint is only healthy when Paperless, SQLite and the configured Ollama model are available.

## 6. First live validation: DRY_RUN

Keep:

```env
DRY_RUN=true
```

Process 5–10 representative documents and inspect the Review UI:

```text
http://localhost:8090
```

Only switch to `DRY_RUN=false` after the classification, titles, correspondents, document types and tags are correct.

## 7. Test crash recovery

Queue a document and, while it is processing:

```bash
docker compose restart ai-worker
```

After restart, the job must return from `PROCESSING` to `QUEUED` and continue.

Do not use `/health` as a recovery mechanism: health checks are intentionally read-only with respect to queue state.

## 8. Test the NAS consume path

Copy one test PDF into the configured consume directory and verify:

1. Paperless consumes it.
2. OCR completes.
3. The post-consume hook returns quickly.
4. AI worker queues the Paperless ID.
5. AI classification completes.
6. Paperless metadata is updated when `DRY_RUN=false`.

The v3 polling configuration is intentional for SMB/NFS/network-backed consume directories.

## 9. Test backup

```bash
./scripts/backup.sh
```

Verify that the resulting archive exists and contains:

- PostgreSQL dump
- Paperless data
- Paperless media
- AI SQLite data
- compose/config/scripts
- manifest

## 10. Restore test

Do a restore test before considering the system production-ready. Use a test copy/backup where possible because restore overwrites the configured data directories.

```bash
./scripts/restore.sh ./backups/ai_documents_YYYY-MM-DD_HH-MM-SS.tar.gz
```

## Production state

The project is P0/P1-ready when all ten steps above pass. The remaining work is operational rather than architectural: periodic backups, reviewing AI classifications, and deliberately upgrading pinned images.
