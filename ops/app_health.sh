#!/bin/bash
# oentbox application health: celery worker + catalog/scraper/download checks.
cd /opt/oentbox || exit 1
LOG=/var/log/oentbox-app-health.log
. /opt/oentbox/ops/lib_alert.sh
alert_config
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

set -a
. /opt/oentbox/.env 2>/dev/null
set +a

celery_ok=1
if ! timeout 40 /opt/oentbox/.venv/bin/celery -A config inspect ping -t 8 >/dev/null 2>&1; then
  celery_ok=0
  say "FAIL celery worker not responding"
else
  say "OK   celery worker responds"
fi

out=$(/opt/oentbox/.venv/bin/python /opt/oentbox/ops/app_checks.py 2>&1)
rc=$?
say "$out"

# Stable signature: only the FAIL lines, so repeated identical failures dedupe.
body=$(printf '%s\n' "$out" | grep -E "^FAIL" | head -10)
[ "$celery_ok" = 0 ] && body=$(printf '%s\nFAIL celery worker not responding' "$body")
[ "$rc" != 0 ] && body=$(printf '%s\nFAIL app_checks.py exited with status %s' "$body" "$rc")

if [ "$celery_ok" = 0 ] || [ "$rc" != 0 ]; then
  say "=== APP HEALTH FAILED ==="
  send_alert_dedup app-health "oentbox app health FAILED" "$body"
else
  say "=== app health passed ==="
  alert_recovered app-health "oentbox app health RECOVERED"
fi

if [ "$celery_ok" = 0 ] || [ "$rc" != 0 ]; then
  exit 1
fi
exit 0
