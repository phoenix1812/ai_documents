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
echo "== Medien-Mount (Host vs. Container) =="
# Docker Desktop kann einem AFP-Mount nicht in den Mountpoint folgen: Der Bind
# existiert, ist aber leer, obwohl der Host Dateien sieht. Paperless antwortet
# dann mit 404 beim Download, ohne dass ein Fehler im Code steckt.
MEDIA_PATH="${PAPERLESS_MEDIA_PATH:-./paperless-media}"
# Delete-Marker von SMB/AFP-Zaehlen nicht als Medien, sonst vergleicht man Muell.
host_files="$(find "$MEDIA_PATH" -type f -not -name '.smbdelete*' -not -name '.afpDeleted*' 2>/dev/null | wc -l | tr -d ' ')"
case "$MEDIA_PATH" in
  /Volumes/*)
    vol="/$(printf '%s' "$MEDIA_PATH" | cut -d/ -f2,3)"
    fs_type="$(mount | awk -v v=" on $vol " 'index($0, v) { print $4; exit }' | tr -d '(,) ')"
    [ -n "$fs_type" ] || fs_type="kein Mount unter $vol"
    echo "Protokoll: $fs_type"
    [ "$fs_type" = "afpfs" ] && echo "❌ AFP: Docker Desktop sieht den Inhalt nicht – auf SMB ummounten (smb://…)"
    ;;
  *)
    fs_type="lokal"
    ;;
esac
container_files="$(docker compose exec -T paperless sh -c \
  "find /usr/src/paperless/media -type f -not -name '.smbdelete*' -not -name '.afpDeleted*' 2>/dev/null | wc -l | tr -d ' '" 2>/dev/null || echo '')"
echo "Dateien: Host=$host_files Container=${container_files:-nicht ermittelbar}"
if [ -z "$container_files" ]; then
  echo "❌ Container nicht erreichbar für den Abgleich"
elif [ "$host_files" != "$container_files" ]; then
  echo "❌ Host und Container sehen unterschiedliche Medien – Mount defekt, nicht die Anwendung"
else
  echo "✅ Medien-Mount konsistent"
fi

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