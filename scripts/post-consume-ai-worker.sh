#!/usr/bin/env bash
set -euo pipefail

if [ -z "${DOCUMENT_ID:-}" ]; then
  echo "AI worker trigger skipped: DOCUMENT_ID is missing"
  exit 0
fi

python3 - <<'PY'
import json, os, urllib.error, urllib.request
url = os.environ.get("AI_WORKER_TRIGGER_URL", "http://ai-worker:8080/process")
document_id = int(os.environ["DOCUMENT_ID"])
payload = json.dumps({"document_id": document_id}).encode("utf-8")
request = urllib.request.Request(
    url=url, data=payload,
    headers={"Content-Type": "application/json", "Connection": "close"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=3) as response:
        print(f"AI worker accepted document {document_id}: HTTP {response.status} {response.read().decode('utf-8')}")
except urllib.error.URLError as exc:
    # Paperless must not fail merely because the asynchronous AI service is down.
    # Reconciliation and/or the next explicit trigger will recover the document.
    print(f"AI worker trigger failed for document {document_id}: {exc}", file=__import__('sys').stderr)
PY
exit 0
