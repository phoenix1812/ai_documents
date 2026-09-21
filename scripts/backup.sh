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

# .env contains every secret of the stack (API token, DB and Review UI
# passwords). Backup archives usually leave the host, so copying it is opt-in.
ENV_IN_BACKUP=no
if [ "${INCLUDE_ENV_BACKUP:-0}" = "1" ]; then
  cp .env "$BACKUP_DIR/env.backup"
  chmod 600 "$BACKUP_DIR/env.backup"
  ENV_IN_BACKUP=yes
  echo "⚠️  .env wurde kopiert: Dieses Archiv enthaelt alle Secrets!"
elif [ -f ".env.example" ]; then
  cp .env.example "$BACKUP_DIR/env.template"
fi

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
  shift 2
  tar --exclude='.afpDeleted*' --exclude='.smbdelete*' --exclude='@eaDir' --exclude='.DS_Store' \
    "$@" \
    -czf "$BACKUP_DIR/$target.tar.gz" \
    -C "$(dirname "$abs")" "$(basename "$abs")"
}

echo "➡️  Sichere Paperless-Daten"
archive_dir "$PAPERLESS_DATA_PATH" paperless-data
archive_dir "$PAPERLESS_MEDIA_PATH" paperless-media

echo "➡️  Sichere AI-SQLite-Daten"
# AI_DATA_PATH ist in dieser Konfiguration der Elternordner des PostgreSQL-
# Clusters (POSTGRES_DATA_PATH=./data/postgres). Ein Tar-Archiv eines laufenden
# Clusters ist nicht konsistent - und ein Restore wuerde es zurueck ueber die
# lebende Instanz schreiben. Deshalb bleibt der Cluster draussen.
if [ "$(cd "$POSTGRES_DATA_PATH" 2>/dev/null && pwd)" = "$(cd "$AI_DATA_PATH" 2>/dev/null && pwd)/$(basename "$POSTGRES_DATA_PATH")" ]; then
  echo "ℹ️  PostgreSQL-Daten liegen innerhalb von AI_DATA_PATH – werden aus dem AI-Archiv ausgeschlossen (sind bereits als paperless.dump gesichert)."
fi
archive_dir "$AI_DATA_PATH" ai-data --exclude="$(basename "$AI_DATA_PATH")/$(basename "$POSTGRES_DATA_PATH")"

cat > "$BACKUP_DIR/manifest.txt" <<EOF
Backup: $TIMESTAMP
Postgres DB: $POSTGRES_DB
Postgres User: $POSTGRES_USER
Paperless data: $PAPERLESS_DATA_PATH
Paperless media: $PAPERLESS_MEDIA_PATH
AI data: $AI_DATA_PATH
Paperless image: ${PAPERLESS_IMAGE:-ghcr.io/paperless-ngx/paperless-ngx:3.1.3}
Ollama image: ${OLLAMA_IMAGE:-ollama/ollama:0.34.0}
Secrets (.env) enthalten: $ENV_IN_BACKUP
EOF

tar -czf "${BACKUP_DIR}.tar.gz" -C "$BACKUP_ROOT" "ai_documents_${TIMESTAMP}"
chmod 600 "${BACKUP_DIR}.tar.gz"
rm -rf "$BACKUP_DIR"

echo "✅ Backup fertig: ${BACKUP_DIR}.tar.gz"
