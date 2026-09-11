#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
BACKUP_DIR="${BACKUP_ROOT}/ai_documents_${TIMESTAMP}"

mkdir -p "$BACKUP_DIR"

[ -f ".env" ] || { echo "❌ .env fehlt"; exit 1; }

set -a
source .env
set +a

POSTGRES_DB="${POSTGRES_DB:-paperless}"
POSTGRES_USER="${POSTGRES_USER:-paperless}"
PAPERLESS_DATA_PATH="${PAPERLESS_DATA_PATH:-./paperless-data}"
PAPERLESS_MEDIA_PATH="${PAPERLESS_MEDIA_PATH:-./paperless-media}"
AI_DATA_PATH="${AI_DATA_PATH:-./data}"

for path in "$PAPERLESS_DATA_PATH" "$PAPERLESS_MEDIA_PATH" "$AI_DATA_PATH"; do
  [ -d "$path" ] || { echo "❌ Verzeichnis fehlt: $path"; exit 1; }
done

echo "📦 Erstelle Backup in: $BACKUP_DIR"
cp docker-compose.yml "$BACKUP_DIR/docker-compose.yml"
cp .env "$BACKUP_DIR/env.backup"
cp -r scripts "$BACKUP_DIR/scripts"

echo "➡️  Sichere PostgreSQL"
docker compose exec -T db pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom \
  --file=/tmp/paperless.dump
docker compose cp db:/tmp/paperless.dump "$BACKUP_DIR/paperless.dump"
docker compose exec -T db rm -f /tmp/paperless.dump

archive_dir() {
  local source="$1"
  local target="$2"
  local abs
  abs="$(cd "$(dirname "$source")" && pwd)/$(basename "$source")"
  [ -d "$abs" ] || { echo "❌ Backup-Quelle fehlt: $source"; exit 1; }
  tar --exclude='.afpDeleted*' --exclude='@eaDir' --exclude='.DS_Store' \
    -czf "$BACKUP_DIR/$target.tar.gz" \
    -C "$(dirname "$abs")" "$(basename "$abs")"
}

echo "➡️  Sichere Paperless-Daten"
archive_dir "$PAPERLESS_DATA_PATH" paperless-data
archive_dir "$PAPERLESS_MEDIA_PATH" paperless-media

echo "➡️  Sichere AI-SQLite-Daten"
archive_dir "$AI_DATA_PATH" ai-data

cat > "$BACKUP_DIR/manifest.txt" <<EOF
Backup: $TIMESTAMP
Postgres DB: $POSTGRES_DB
Postgres User: $POSTGRES_USER
Paperless data: $PAPERLESS_DATA_PATH
Paperless media: $PAPERLESS_MEDIA_PATH
AI data: $AI_DATA_PATH
Paperless image: ${PAPERLESS_IMAGE:-ghcr.io/paperless-ngx/paperless-ngx:3.1.3}
Ollama image: ${OLLAMA_IMAGE:-ollama/ollama:0.34.0}
EOF

tar -czf "${BACKUP_DIR}.tar.gz" -C "$BACKUP_ROOT" "ai_documents_${TIMESTAMP}"
rm -rf "$BACKUP_DIR"

echo "✅ Backup fertig: ${BACKUP_DIR}.tar.gz"
