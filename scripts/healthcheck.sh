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

if [ -n "${REVIEW_UI_USERNAME:-}" ] && [ -n "${REVIEW_UI_PASSWORD:-}" ]; then
  curl -fsS -u "${REVIEW_UI_USERNAME}:${REVIEW_UI_PASSWORD}" -w "\n%{http_code}" "http://localhost:${REVIEW_UI_PORT}/" >/dev/null 2>&1 \
    && echo "✅ Review UI erreichbar (auth)" \
    || echo "❌ Review UI nicht erreichbar (auth)"
else
  curl -fsS -w "\n%{http_code}" "http://localhost:${REVIEW_UI_PORT}/" >/dev/null 2>&1 | grep -q -E "^(200|401|403)$" \
    && echo "✅ Review UI erreichbar" \
    || echo "❌ Review UI nicht erreichbar"
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