#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
BACKUP_DIR="${BACKUP_ROOT}/ai_documents_${TIMESTAMP}"

mkdir -p "$BACKUP_DIR"

[ -f ".env" ] || {
  echo "❌ .env fehlt"
  exit 1
}

set -a
source .env
set +a

POSTGRES_DB="${POSTGRES_DB:-paperless}"
POSTGRES_USER="${POSTGRES_USER:-paperless}"

echo "📦 Erstelle Backup in: $BACKUP_DIR"

echo "➡️  Sichere Compose/Env/Skripte"
cp docker-compose.yml "$BACKUP_DIR/docker-compose.yml"
cp .env "$BACKUP_DIR/env.backup"
cp -r scripts "$BACKUP_DIR/scripts"

echo "➡️  Sichere Postgres per pg_dump"
docker compose exec -T db pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom \
  --file=/tmp/paperless.dump

docker compose cp db:/tmp/paperless.dump "$BACKUP_DIR/paperless.dump"
docker compose exec -T db rm -f /tmp/paperless.dump

echo "➡️  Sichere Paperless-Daten"

tar \
  --exclude='.afpDeleted*' \
  --exclude='@eaDir' \
  --exclude='.DS_Store' \
  -czf "$BACKUP_DIR/paperless-data.tar.gz" \
  "${PAPERLESS_DATA_PATH:-./paperless-data}" 2>/dev/null || true

tar \
  --exclude='.afpDeleted*' \
  --exclude='@eaDir' \
  --exclude='.DS_Store' \
  -czf "$BACKUP_DIR/paperless-media.tar.gz" \
  "${PAPERLESS_MEDIA_PATH:-./paperless-media}" 2>/dev/null || true

echo "➡️  Sichere AI-SQLite-Daten"

tar \
  --exclude='.DS_Store' \
  -czf "$BACKUP_DIR/ai-data.tar.gz" \
  ./data 2>/dev/null || true

echo "➡️  Schreibe Manifest"
cat > "$BACKUP_DIR/manifest.txt" <<EOF
Backup: $TIMESTAMP
Postgres DB: $POSTGRES_DB
Postgres User: $POSTGRES_USER
Paperless data: ${PAPERLESS_DATA_PATH:-./paperless-data}
Paperless media: ${PAPERLESS_MEDIA_PATH:-./paperless-media}
AI data: ./data
EOF

echo "➡️  Komprimiere Backup"
tar -czf "${BACKUP_DIR}.tar.gz" -C "$BACKUP_ROOT" "ai_documents_${TIMESTAMP}"
rm -rf "$BACKUP_DIR"

echo "✅ Backup fertig: ${BACKUP_DIR}.tar.gz"