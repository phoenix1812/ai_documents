#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
mkdir -p "${BACKUP_DIR:-./backups}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/ai_documents_backup_$STAMP"
mkdir -p "$OUT"

# 1) SQLite AI state. Use SQLite's online backup API inside the running container
# so WAL contents are included consistently.
docker exec ai-worker python -c "import sqlite3; src=sqlite3.connect('/data/documents.db'); dst=sqlite3.connect('/tmp/documents.db.backup'); src.backup(dst); dst.close(); src.close()"
docker cp ai-worker:/tmp/documents.db.backup "$OUT/documents.db"
docker exec ai-worker rm -f /tmp/documents.db.backup

# 2) Paperless PostgreSQL logical backup.
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-paperless}" -d "${POSTGRES_DB:-paperless}" > "$OUT/paperless.sql"

# 3) Paperless media/data are included as tar archives when their host paths exist.
MEDIA_PATH="${PAPERLESS_MEDIA_PATH:-./paperless-media}"
DATA_PATH="${PAPERLESS_DATA_PATH:-./paperless-data}"
[ -d "$MEDIA_PATH" ] && tar -czf "$OUT/paperless-media.tar.gz" -C "$MEDIA_PATH" .
[ -d "$DATA_PATH" ] && tar -czf "$OUT/paperless-data.tar.gz" -C "$DATA_PATH" .

sha256sum "$OUT"/* > "$OUT/SHA256SUMS.txt"
tar -czf "$BACKUP_DIR/ai_documents_backup_$STAMP.tar.gz" -C "$BACKUP_DIR" "$(basename "$OUT")"
rm -rf "$OUT"

echo "Backup created: $BACKUP_DIR/ai_documents_backup_$STAMP.tar.gz"
