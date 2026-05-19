#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_FILE="${1:-}"

if [ -z "$BACKUP_FILE" ]; then
  echo "Nutzung: ./scripts/restore.sh ./backups/ai_documents_YYYY-MM-DD_HH-MM-SS.tar.gz"
  exit 1
fi

[ -f "$BACKUP_FILE" ] || {
  echo "❌ Backup-Datei nicht gefunden: $BACKUP_FILE"
  exit 1
}

[ -f ".env" ] || {
  echo "❌ .env fehlt"
  exit 1
}

set -a
source .env
set +a

POSTGRES_DB="${POSTGRES_DB:-paperless}"
POSTGRES_USER="${POSTGRES_USER:-paperless}"

RESTORE_TMP="./restore_tmp"

echo "⚠️  Restore überschreibt lokale Daten."
read -r -p "Fortfahren? Tippe JA: " confirm

[ "$confirm" = "JA" ] || {
  echo "Abgebrochen."
  exit 1
}

rm -rf "$RESTORE_TMP"
mkdir -p "$RESTORE_TMP"

tar -xzf "$BACKUP_FILE" -C "$RESTORE_TMP"
BACKUP_DIR="$(find "$RESTORE_TMP" -maxdepth 1 -type d -name 'ai_documents_*' | head -n 1)"

[ -n "$BACKUP_DIR" ] || {
  echo "❌ Backup-Inhalt nicht gefunden"
  exit 1
}

echo "➡️  Stoppe Dienste"
docker compose down

echo "➡️  Stelle Dateien wieder her"
rm -rf "${PAPERLESS_DATA_PATH:-./paperless-data}"
rm -rf "${PAPERLESS_MEDIA_PATH:-./paperless-media}"
rm -rf ./data

tar -xzf "$BACKUP_DIR/paperless-data.tar.gz" -C .
tar -xzf "$BACKUP_DIR/paperless-media.tar.gz" -C .
tar -xzf "$BACKUP_DIR/ai-data.tar.gz" -C .

echo "➡️  Starte Datenbank"
docker compose up -d db
sleep 8

echo "➡️  Stelle Postgres wieder her"
docker compose exec -T db dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" --if-exists
docker compose exec -T db createdb -U "$POSTGRES_USER" "$POSTGRES_DB"

docker compose cp "$BACKUP_DIR/paperless.dump" db:/tmp/paperless.dump

docker compose exec -T db pg_restore \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --clean \
  --if-exists \
  /tmp/paperless.dump

docker compose exec -T db rm -f /tmp/paperless.dump

echo "➡️  Starte Stack"
docker compose up -d

rm -rf "$RESTORE_TMP"

echo "✅ Restore fertig"