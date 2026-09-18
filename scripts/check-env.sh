#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

fail() { echo "❌ $1"; exit 1; }
warn() { echo "⚠️  $1"; }
ok() { echo "✅ $1"; }

[ -f ".env" ] || fail ".env fehlt"

set -a
source .env
set +a

required_vars=(
  POSTGRES_PASSWORD
  PAPERLESS_ADMIN_USER
  PAPERLESS_ADMIN_PASSWORD
  PAPERLESS_SECRET_KEY
  PAPERLESS_TOKEN
  PAPERLESS_PUBLIC_URL
  OLLAMA_MODEL
  REVIEW_UI_USERNAME
  REVIEW_UI_PASSWORD
)

for var in "${required_vars[@]}"; do
  value="${!var:-}"
  [ -n "$value" ] || fail "$var fehlt in .env"
done

for var in POSTGRES_PASSWORD PAPERLESS_ADMIN_PASSWORD PAPERLESS_SECRET_KEY PAPERLESS_TOKEN REVIEW_UI_PASSWORD; do
  value="${!var:-}"
  case "$value" in
    change-me|changeme|CHANGE_ME*) fail "$var enthält noch einen Platzhalter" ;;
  esac
done

for var in QUEUE_MAX_ATTEMPTS QUEUE_RETRY_BASE_SECONDS QUEUE_RETRY_MAX_SECONDS RECONCILIATION_INTERVAL_SECONDS; do
  value="${!var:-}"
  [[ "$value" =~ ^[0-9]+$ ]] || fail "$var muss eine positive Ganzzahl sein"
done

# Network-backed consume directories need polling in Paperless v3.
if [[ "${PAPERLESS_CONSUME_PATH:-}" == /Volumes/* ]] || [[ "${PAPERLESS_CONSUME_PATH:-}" == /mnt/* ]]; then
  if [ "${PAPERLESS_CONSUMER_POLLING_INTERVAL:-0}" -le 0 ]; then
    fail "PAPERLESS_CONSUMER_POLLING_INTERVAL muss bei NAS/Netzwerkpfaden > 0 sein"
  fi
fi

docker compose config >/dev/null
ok "docker-compose.yml ist gültig"

for path in \
  "${POSTGRES_DATA_PATH:-./data/postgres}" \
  "${PAPERLESS_DATA_PATH:-./paperless-data}" \
  "${PAPERLESS_MEDIA_PATH:-./paperless-media}" \
  "${PAPERLESS_CONSUME_PATH:-./paperless-consume}" \
  "./data"
do
  if [[ "$path" == /Volumes/* ]]; then
    echo "🔎 Prüfe externes Volume: $path"
    [ -e "$path" ] || fail "Externes Volume nicht gemountet: $path"
    [ -w "$path" ] || fail "Externes Volume nicht beschreibbar: $path"
  else
    mkdir -p "$path"
    [ -w "$path" ] || fail "Pfad nicht beschreibbar: $path"
  fi
done

ok "Produktiv-Check bestanden"
