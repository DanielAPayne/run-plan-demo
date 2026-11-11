#!/bin/sh
# Bring the demo up from nothing, or re-apply the workflows after a change.
# Safe to run again: imports overwrite by id, and the owner account is created only once.
set -e
cd "$(dirname "$0")/.."
python3 -I workflows/build.py
docker compose up -d
printf 'waiting for n8n'
n=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' rundemo-n8n-1 2>/dev/null)" = "healthy" ]; do
  n=$((n+1)); [ $n -gt 90 ] && { echo " n8n did not become healthy"; exit 1; }
  printf '.'; sleep 2
done
echo " ok"
# The editor's owner account: local test values from .env, never printed.
. ./.env
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:5678/rest/owner/setup \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$N8N_OWNER_EMAIL\",\"firstName\":\"Demo\",\"lastName\":\"Owner\",\"password\":\"$N8N_OWNER_PASSWORD\"}")
echo "owner setup: HTTP $code (200 = created, 400 = already set up)"
docker compose exec -T n8n n8n import:credentials --input=/demo/credentials.json 2>&1 | tail -1
docker compose exec -T n8n n8n import:workflow --separate --input=/demo/workflows 2>&1 | tail -1
for f in workflows/out/*.json; do
  id=$(basename "$f" .json)
  docker compose exec -T n8n n8n publish:workflow --id="$id" 2>&1 | tail -1
done
# Published triggers and webhooks are registered when n8n starts.
# The watchdog is paused for this planned restart, so it doesn't record it as an outage.
docker compose stop watchdog >/dev/null 2>&1
docker compose restart n8n >/dev/null 2>&1
printf 'restarting n8n'
n=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' rundemo-n8n-1 2>/dev/null)" = "healthy" ]; do
  n=$((n+1)); [ $n -gt 90 ] && { echo " n8n did not become healthy"; exit 1; }
  printf '.'; sleep 2
done
echo " ok"
docker compose start watchdog >/dev/null 2>&1
docker compose ps --format 'table {{.Name}}\t{{.Status}}'
