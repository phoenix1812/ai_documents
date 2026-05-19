#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  echo "❌ $1"
  exit 1
}

warn() {
  echo "⚠️  $1"
}

ok() {
  echo "✅ $1"
}

[ -f ".env" ] || fail ".env fehlt"

set -a
source .env
set +a

required_vars=(
  POSTGRES_PASSWORD
  PAPERLESS_ADMIN_USER
  PAPERLESS_ADMIN_PASSWORD
  PAPERLESS_TOKEN
)

for var in "${required_vars[@]}"; do
  value="${!var:-}"
  [ -n "$value" ] || fail "$var fehlt in .env"
done

[ "${PAPERLESS_ADMIN_PASSWORD}" != "changeme" ] || fail "PAPERLESS_ADMIN_PASSWORD ist noch 'changeme'"
[ "${POSTGRES_PASSWORD}" != "paperless" ] || warn "POSTGRES_PASSWORD wirkt wie ein Standardwert"

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