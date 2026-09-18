#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_FILE="${1:-}"
[ -n "$BACKUP_FILE" ] || { echo "Nutzung: ./scripts/restore.sh ./backups/ai_documents_YYYY-MM-DD_HH-MM-SS.tar.gz"; exit 1; }
[ -f "$BACKUP_FILE" ] || { echo "❌ Backup-Datei nicht gefunden: $BACKUP_FILE"; exit 1; }
[ -f ".env" ] || { echo "❌ .env fehlt"; exit 1; }

set -a
source .env
set +a

POSTGRES_DB="${POSTGRES_DB:-paperless}"
POSTGRES_USER="${POSTGRES_USER:-paperless}"
PAPERLESS_DATA_PATH="${PAPERLESS_DATA_PATH:-./paperless-data}"
PAPERLESS_MEDIA_PATH="${PAPERLESS_MEDIA_PATH:-./paperless-media}"
AI_DATA_PATH="${AI_DATA_PATH:-./data}"
RESTORE_TMP="./restore_tmp"

echo "⚠️  Restore überschreibt lokale Daten."
read -r -p "Fortfahren? Tippe JA: " confirm
[ "$confirm" = "JA" ] || { echo "Abgebrochen."; exit 1; }

rm -rf "$RESTORE_TMP"
mkdir -p "$RESTORE_TMP"
trap 'rm -rf "$RESTORE_TMP"' EXIT

tar -xzf "$BACKUP_FILE" -C "$RESTORE_TMP"
BACKUP_DIR="$(find "$RESTORE_TMP" -mindepth 1 -maxdepth 1 -type d -name 'ai_documents_*' | head -n 1)"
[ -n "$BACKUP_DIR" ] || { echo "❌ Backup-Inhalt nicht gefunden"; exit 1; }

for file in paperless.dump paperless-data.tar.gz paperless-media.tar.gz ai-data.tar.gz; do
  [ -f "$BACKUP_DIR/$file" ] || { echo "❌ Backup unvollständig: $file fehlt"; exit 1; }
done

echo "➡️  Stoppe Dienste"
docker compose down

restore_archive() {
  local archive="$1"
  local target="$2"
  local parent
  parent="$(dirname "$target")"
  mkdir -p "$parent"
  rm -rf "$target"
  tar -xzf "$archive" -C "$parent"
}

echo "➡️  Stelle Dateien wieder her"
restore_archive "$BACKUP_DIR/paperless-data.tar.gz" "$PAPERLESS_DATA_PATH"
restore_archive "$BACKUP_DIR/paperless-media.tar.gz" "$PAPERLESS_MEDIA_PATH"
restore_archive "$BACKUP_DIR/ai-data.tar.gz" "$AI_DATA_PATH"

echo "➡️  Starte PostgreSQL"
docker compose up -d db

for _ in {1..30}; do
  if docker compose exec -T db pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "➡️  Stelle PostgreSQL wieder her"
docker compose exec -T db dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" --if-exists
docker compose exec -T db createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
docker compose cp "$BACKUP_DIR/paperless.dump" db:/tmp/paperless.dump
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/paperless.dump
docker compose exec -T db rm -f /tmp/paperless.dump

echo "➡️  Starte Stack"
docker compose up -d

echo "✅ Restore fertig"
