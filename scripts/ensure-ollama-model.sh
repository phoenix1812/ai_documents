#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

[ -f .env ] || { echo "❌ .env fehlt"; exit 1; }
set -a
source .env
set +a

MODEL="${OLLAMA_MODEL:-}"
[ -n "$MODEL" ] || { echo "❌ OLLAMA_MODEL fehlt"; exit 1; }

# Ensure the Ollama service exists before pulling the model.
docker compose up -d ollama

echo "➡️  Prüfe Ollama-Modell: $MODEL"
if docker compose exec -T ollama ollama list | awk 'NR > 1 {print $1}' | grep -Fxq "$MODEL"; then
  echo "✅ Modell bereits vorhanden: $MODEL"
  exit 0
fi

echo "➡️  Lade Modell: $MODEL"
docker compose exec -T ollama ollama pull "$MODEL"
echo "✅ Modell bereit: $MODEL"
