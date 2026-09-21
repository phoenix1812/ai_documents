#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== Docker =="
docker compose ps

echo
echo "== AI Worker =="
docker compose exec paperless curl -fsS http://ai-worker:8080/health \
  || echo "❌ AI Worker nicht erreichbar"

echo
echo
echo "== Review UI =="
# Load .env if present so REVIEW_UI_USERNAME/REVIEW_UI_PASSWORD are available
if [ -f .env ]; then
  set -o allexport
  # shellcheck disable=SC1091
  . .env
  set +o allexport
fi

REVIEW_UI_PORT=${REVIEW_UI_PORT:-8090}

# Credentials are handed to curl over stdin, never as argv: command-line
# arguments are visible to every process via `ps` and land in shell history.
check_url() {
  local url="$1"
  shift
  curl --config - -sS -o /dev/null -w '%{http_code}' --max-time 10 "$@" "$url" 2>/dev/null || true
}

if [ -n "${REVIEW_UI_USERNAME:-}" ] && [ -n "${REVIEW_UI_PASSWORD:-}" ]; then
  curl_user_line="$(printf '%s:%s' "$REVIEW_UI_USERNAME" "$REVIEW_UI_PASSWORD" \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
  review_ui_code="$(printf 'user = "%s"\n' "$curl_user_line" \
    | check_url "http://localhost:${REVIEW_UI_PORT}/")"
  case "$review_ui_code" in
    200) echo "✅ Review UI erreichbar (auth)" ;;
    401|403) echo "❌ Review UI antwortet, aber die Anmeldedaten passen nicht (HTTP $review_ui_code)" ;;
    *) echo "❌ Review UI nicht erreichbar (HTTP ${review_ui_code:-kein Response})" ;;
  esac
else
  # /dev/null keeps `--config -` from waiting on an interactive terminal.
  review_ui_code="$(check_url "http://localhost:${REVIEW_UI_PORT}/" < /dev/null)"
  case "$review_ui_code" in
    200) echo "✅ Review UI erreichbar" ;;
    401|403) echo "✅ Review UI erreichbar (erwartet Basic-Auth, keine Credentials gesetzt)" ;;
    *) echo "❌ Review UI nicht erreichbar (HTTP ${review_ui_code:-kein Response})" ;;
  esac
fi

echo
echo "== Paperless =="
curl -fsS http://localhost:8000/ >/dev/null \
  && echo "✅ Paperless erreichbar" \
  || echo "❌ Paperless nicht erreichbar"

echo
echo "== Volumes/Pfade =="
for path in \
  "${POSTGRES_DATA_PATH:-./data/postgres}" \
  "${PAPERLESS_DATA_PATH:-./paperless-data}" \
  "${PAPERLESS_MEDIA_PATH:-./paperless-media}" \
  "./data"
do
  echo "$path"
  du -sh "$path" 2>/dev/null || true
done