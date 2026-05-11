#!/usr/bin/env bash
set -euo pipefail

if [ -z "${DOCUMENT_ID:-}" ]; then
  echo "AI worker trigger skipped: DOCUMENT_ID is missing"
  exit 0
fi

python3 - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

url = os.environ.get(
    "AI_WORKER_TRIGGER_URL",
    "http://ai-worker:8080/process",
)

document_id = int(os.environ["DOCUMENT_ID"])

payload = json.dumps({
    "document_id": document_id,
}).encode("utf-8")

request = urllib.request.Request(
    url=url,
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Connection": "close",
    },
    method="POST",
)

try:
    # The server returns immediately with 202 and processes asynchronously.
    # Keep this timeout short so Paperless is never blocked for long.
    with urllib.request.urlopen(request, timeout=3) as response:
        body = response.read().decode("utf-8")
        print(
            f"AI worker accepted document {document_id}: "
            f"HTTP {response.status} {body}"
        )

except urllib.error.URLError as exc:
    print(
        f"AI worker trigger failed for document {document_id}: {exc}",
        file=sys.stderr,
    )
    # Do not fail Paperless consumption because AI post-processing failed.
    sys.exit(0)
PY
