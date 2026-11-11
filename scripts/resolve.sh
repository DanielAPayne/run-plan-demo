#!/bin/sh
# Close an incident with what was done about it.
#   sh scripts/resolve.sh <incident id> "<what fixed it>" [drill]
set -e
cd "$(dirname "$0")/.."
[ -n "$1" ] && [ -n "$2" ] || { echo 'usage: resolve.sh <id> "<what fixed it>" [drill]'; exit 2; }
drill=false; [ "$3" = "drill" ] && drill=true
docker compose exec -T postgres psql -U postgres -d demo -X -At -v ON_ERROR_STOP=1 \
  -v id="$1" -v res="$2" -v drill="$drill" <<'SQL'
UPDATE incidents SET resolved_at = now(), resolution = :'res', is_drill = :'drill'::boolean
WHERE id = :'id'::bigint AND resolved_at IS NULL
RETURNING 'closed incident ' || id || ' after ' || date_trunc('second', resolved_at - opened_at);
SQL
