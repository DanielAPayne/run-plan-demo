#!/bin/sh
# The watchdog. It runs outside n8n and checks three things every minute:
#   1. n8n answers its health check;
#   2. the automation's heartbeat is fresh (it writes one every 5 minutes);
#   3. a daily test has passed in the last 26 hours.
# A problem opens one incident and sends one alert. When the problem clears, the incident is closed.

HEARTBEAT_MAX_AGE=720      # seconds: two missed heartbeats plus slack
DAILY_TEST_MAX_AGE=93600   # seconds: 26 hours
GRACE=900                  # seconds after this script starts before 2 and 3 are judged
START=$(date +%s)

# -q matters: without it psql also prints the command tag ("UPDATE 0"), and "nothing changed"
# would look like a result. That bug sent a RESOLVED alert every minute on the first night.
q() { psql -X -q -At -v ON_ERROR_STOP=1 -c "$1" 2>/dev/null; }

alert() {
  # $1 subject, $2 text. Sent straight to the alert channel, so it doesn't depend on n8n or on the email service.
  wget -q -T 5 -O /dev/null --header 'Content-Type: application/json' \
    --post-data "{\"From\":{\"Email\":\"watchdog@rundemo.test\",\"Name\":\"Watchdog\"},\"To\":[{\"Email\":\"ops@rundemo.test\"}],\"Subject\":\"$1\",\"Text\":\"$2\"}" \
    http://alertbox:8025/api/v1/send || echo "$(date -Iseconds) alert not delivered: $1"
}

open_incident() {
  # $1 kind, $2 message
  n=$(q "SELECT count(*) FROM incidents WHERE source = 'watchdog' AND node = '$1' AND resolved_at IS NULL")
  if [ "$n" = "0" ]; then
    q "INSERT INTO incidents (source, workflow, node, message) VALUES ('watchdog', '(outside n8n)', '$1', '$2')" >/dev/null
    alert "ALERT: $1" "$2"
    echo "$(date -Iseconds) opened: $1: $2"
  fi
}

resolve_incident() {
  # $1 kind
  r=$(q "UPDATE incidents SET resolved_at = now(), resolution = 'cleared; seen by the watchdog' WHERE source = 'watchdog' AND node = '$1' AND resolved_at IS NULL RETURNING id")
  if [ -n "$r" ]; then
    alert "RESOLVED: $1" "The check passes again."
    echo "$(date -Iseconds) resolved: $1"
  fi
}

echo "$(date -Iseconds) watchdog started"
while true; do
  if wget -q -T 5 -O /dev/null http://n8n:5678/healthz; then
    resolve_incident n8n-down
  else
    open_incident n8n-down "n8n did not answer its health check"
  fi

  now=$(date +%s)
  if [ $((now - START)) -gt "$GRACE" ]; then
    age=$(q "SELECT coalesce(extract(epoch FROM now() - max(at))::int, 999999) FROM heartbeats")
    if [ -n "$age" ]; then
      if [ "$age" -gt "$HEARTBEAT_MAX_AGE" ]; then
        open_incident heartbeat-stale "No heartbeat from the automation for ${age} seconds"
      else
        resolve_incident heartbeat-stale
      fi
    fi

    # Only judged once the automation is more than 26 hours old.
    t=$(q "SELECT CASE WHEN (SELECT min(at) FROM heartbeats) > now() - interval '26 hours' THEN 0
                       ELSE coalesce((SELECT extract(epoch FROM now() - max(at))::int FROM checks WHERE kind = 'daily-test' AND passed), 999999) END")
    if [ -n "$t" ]; then
      if [ "$t" -gt "$DAILY_TEST_MAX_AGE" ]; then
        open_incident daily-test-missing "No passing daily test for ${t} seconds"
      else
        resolve_incident daily-test-missing
      fi
    fi
  fi

  sleep 60
done
