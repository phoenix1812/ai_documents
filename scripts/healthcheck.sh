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
curl -fsS http://localhost:8090/ >/dev/null \
  && echo "✅ Review UI erreichbar" \
  || echo "❌ Review UI nicht erreichbar"

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