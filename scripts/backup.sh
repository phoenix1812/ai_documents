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

# Retention: Anzahl Aufbewahreter Archive. 0 = alle behalten.
BACKUP_KEEP="${BACKUP_KEEP:-7}"
case "$BACKUP_KEEP" in
  ''|*[!0-9]*) echo "❌ BACKUP_KEEP muss eine Zahl sein (getrocknet: $BACKUP_KEEP)"; exit 1 ;;
esac

# WAL-sichere SQLite-Kopien: beide Datenbanken laufen im WAL-Modus, die live
# getarnten Dateien koennen dabei mitten im Schreibvorgang erwischt werden.
# 3.27+ kann VACUUM INTO, das die Quelle unveraendert laesst.
SQLITE_CLI="${SQLITE_CLI:-/usr/bin/sqlite3}"
[ -x "$SQLITE_CLI" ] || { echo "❌ sqlite3 nicht gefunden: $SQLITE_CLI"; exit 1; }

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

# Ein abgebrochener pg_dump hinterlaesst eine duerre Datei, die erst beim Restore
# auffaellt. Header und Mindestgroesse werden hier geprueft, nicht spaeter.
[ -s "$BACKUP_DIR/paperless.dump" ] || { echo "❌ paperless.dump ist leer"; exit 1; }
[ "$(head -c 5 "$BACKUP_DIR/paperless.dump")" = "PGDMP" ] || { echo "❌ paperless.dump hat keinen PGDMP-Header"; exit 1; }
PG_DUMP_SIZE="$(wc -c < "$BACKUP_DIR/paperless.dump" | tr -d ' ')"
echo "ℹ️  paperless.dump: $PG_DUMP_SIZE Bytes"

archive_dir() {
  local source="$1"
  local target="$2"
  local abs
  abs="$(cd "$(dirname "$source")" && pwd)/$(basename "$source")"
  [ -d "$abs" ] || { echo "❌ Backup-Quelle fehlt: $source"; exit 1; }
  shift 2
  # COPYFILE_DISABLE verhindert, dass macOS bsdtar fuer jede Datei mit einem
  # xattr (com.apple.provenance) ein AppleDouble-Duplikat `._name` mit ablegt -
  # im letzten Lauf 476 stuueck, die beim Restore als Mull im Medienverzeichnis
  # gelandet waeren. Ein --exclude='._*' traefe dagegen echte Dateien wie
  # paperless-data/log/.__paperless.lock.
  COPYFILE_DISABLE=1 tar \
    --exclude='.afpDeleted*' --exclude='.smbdelete*' --exclude='@eaDir' --exclude='.DS_Store' \
    "$@" \
    -czf "$BACKUP_DIR/$target.tar.gz" \
    -C "$(dirname "$abs")" "$(basename "$abs")"
}

echo "➡️  Sichere Paperless-Daten"
archive_dir "$PAPERLESS_DATA_PATH" paperless-data
archive_dir "$PAPERLESS_MEDIA_PATH" paperless-media

echo "➡️  Sichere AI-SQLite-Daten"
# WAL-sichere Kopien statt der live Dateien: VACUUM INTO liest die Quelle
# konsistent (auch mit offener WAL) und schreibt eine einzelne datei ohne
# -wal/-shm. Die live Dateien bleiben im Archiv draussen, restore.sh setzt die
# Snapshots wieder ein.
mkdir -p "$BACKUP_DIR/sqlite"
snapshot_sqlite() {
  local source="$1" target="$2"
  [ -f "$source" ] || { echo "ℹ️  Keine SQLite-Datenbank, uebersprungen: $source"; return 0; }
  case "$target" in
    *\'*) echo "❌ Zielpfad enthaelt ein Apostroph: $target"; exit 1 ;;
  esac
  "$SQLITE_CLI" "$source" "VACUUM INTO '$target'"
  local check
  check="$("$SQLITE_CLI" "$target" 'PRAGMA integrity_check;' | head -n 1)"
  [ "$check" = "ok" ] || { echo "❌ Snapshot nicht intakt: $target ($check)"; exit 1; }
  echo "ℹ️  Snapshot: $(basename "$target") ($(wc -c < "$target" | tr -d ' ') Bytes, integrity_check ok)"
}
snapshot_sqlite "$AI_DATA_PATH/documents.db" "$BACKUP_DIR/sqlite/documents.db"
snapshot_sqlite "$AI_DATA_PATH/queue.db/documents.db" "$BACKUP_DIR/sqlite/queue-documents.db"

# AI_DATA_PATH ist in dieser Konfiguration der Elternordner des PostgreSQL-
# Clusters (POSTGRES_DATA_PATH=./data/postgres). Ein Tar-Archiv eines laufenden
# Clusters ist nicht konsistent - und ein Restore wuerde es zurueck ueber die
# lebende Instanz schreiben. Deshalb bleibt der Cluster draussen, ebenso die
# live SQLite-Dateien zugunsten der Snapshots.
if [ "$(cd "$POSTGRES_DATA_PATH" 2>/dev/null && pwd)" = "$(cd "$AI_DATA_PATH" 2>/dev/null && pwd)/$(basename "$POSTGRES_DATA_PATH")" ]; then
  echo "ℹ️  PostgreSQL-Daten liegen innerhalb von AI_DATA_PATH – werden aus dem AI-Archiv ausgeschlossen (sind bereits als paperless.dump gesichert)."
fi
archive_dir "$AI_DATA_PATH" ai-data \
  --exclude="$(basename "$AI_DATA_PATH")/$(basename "$POSTGRES_DATA_PATH")" \
  --exclude="$(basename "$AI_DATA_PATH")/documents.db*" \
  --exclude="$(basename "$AI_DATA_PATH")/queue.db/documents.db*"

for archive in paperless-data paperless-media ai-data; do
  gzip -t "$BACKUP_DIR/$archive.tar.gz" || { echo "❌ Archiv beschaedigt: $archive.tar.gz"; exit 1; }
done
SQLITE_SNAPSHOTS="$(cd "$BACKUP_DIR/sqlite" && ls -1 2>/dev/null | tr '\n' ' ')"

# Das Manifest nennt das tatsaechlich laufende Bild inklusive Digest, nicht den
# Compose-Default: der kann nach einem Upgrade schon laengst ueberholt sein.
PAPERLESS_RUNNING_IMAGE="$(docker inspect -f '{{.Config.Image}} ({{.Image}})' paperless 2>/dev/null || echo 'unbekannt')"
cat > "$BACKUP_DIR/manifest.txt" <<EOF
Backup: $TIMESTAMP
Postgres DB: $POSTGRES_DB
Postgres User: $POSTGRES_USER
Paperless data: $PAPERLESS_DATA_PATH
Paperless media: $PAPERLESS_MEDIA_PATH
AI data: $AI_DATA_PATH
SQLite-Snapshots (VACUUM INTO): $SQLITE_SNAPSHOTS
PostgreSQL-Dump: $PG_DUMP_SIZE Bytes
Paperless image: $PAPERLESS_RUNNING_IMAGE
Ollama image: ${OLLAMA_IMAGE:-ollama/ollama:0.34.0}
Secrets (.env) enthalten: $ENV_IN_BACKUP
EOF

tar -czf "${BACKUP_DIR}.tar.gz" -C "$BACKUP_ROOT" "ai_documents_${TIMESTAMP}"
chmod 600 "${BACKUP_DIR}.tar.gz"
rm -rf "$BACKUP_DIR"
( cd "$BACKUP_ROOT" && shasum -a 256 "ai_documents_${TIMESTAMP}.tar.gz" > "ai_documents_${TIMESTAMP}.tar.gz.sha256" )

echo "✅ Backup fertig: ${BACKUP_DIR}.tar.gz"

# Retention: die Namen enthalten den Zeitstempel, also ist die lexikalische
# Reihenfolge zugleich die zeitliche.
if [ "$BACKUP_KEEP" -gt 0 ]; then
  total="$(find "$BACKUP_ROOT" -maxdepth 1 -type f -name 'ai_documents_*.tar.gz' | wc -l | tr -d ' ')"
  if [ "$total" -gt "$BACKUP_KEEP" ]; then
    find "$BACKUP_ROOT" -maxdepth 1 -type f -name 'ai_documents_*.tar.gz' \
      | sort | head -n "$((total - BACKUP_KEEP))" \
      | while IFS= read -r old; do
          echo "🧹 Retention, entferne: $(basename "$old")"
          rm -f -- "$old" "$old.sha256"
        done
  fi
  echo "ℹ️  Retention: $BACKUP_KEEP Archive werden behalten."
else
  echo "ℹ️  Retention deaktiviert (BACKUP_KEEP=0), alle Archive bleiben liegen."
fi
