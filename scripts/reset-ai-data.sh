#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

read -r -p "AI-Datenbank wirklich komplett löschen? Paperless bleibt erhalten. [yes/NO] " answer
if [ "$answer" != "yes" ]; then
  echo "Abgebrochen."
  exit 1
fi

docker compose stop ai-worker ai-review-ui >/dev/null
mkdir -p ./data
rm -f ./data/documents.db ./data/documents.db-wal ./data/documents.db-shm

echo "AI-Datenbank gelöscht. Paperless/PostgreSQL/Redis/Ollama wurden nicht gelöscht."
docker compose up -d --build ai-worker ai-review-ui

echo "Warte auf Healthcheck..."
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
    echo "AI worker ist bereit."
    exit 0
  fi
  sleep 2
done

echo "Healthcheck wurde nicht rechtzeitig grün. Prüfe: docker compose logs --tail=100 ai-worker"
exit 1
