#!/bin/bash
# oentbox nightly health check: uptime, sensitive-file sentinel, cert expiry, disk, services
LOG=/var/log/oentbox-health.log
FAIL=0
FAIL_LIST=""
. /opt/oentbox/ops/lib_alert.sh
alert_config
say(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
check(){
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    say "OK   $desc"
  else
    say "FAIL $desc"
    FAIL=1
    FAIL_LIST="${FAIL_LIST}FAIL $desc"$'\n'
  fi
}

check "homepage 200"            bash -c '[ "$(curl -sS -o /dev/null -w "%{http_code}" -m 20 https://oentbox.com/)" = "200" ]'
for f in db.sqlite3 settings.py manage.py requirements.txt; do
  # pass when the file is NOT served (404 no-file, 403 blocked by nginx)
  check "sentinel /static/$f blocked" bash -c "[ \"\$(curl -sS -o /dev/null -w \"%{http_code}\" -m 15 https://oentbox.com/static/$f)\" != \"200\" ]"
done
check "no sensitive files in staticfiles" /usr/bin/python3 /opt/oentbox/ops/scan_staticfiles.py
check "static dirs config safe"  /usr/bin/python3 /opt/oentbox/ops/guard_static_dirs.py
check "admin login reachable"   bash -c 'C=$(curl -sS -o /dev/null -w "%{http_code}" -m 15 https://oentbox.com/admin/login/); [ "$C" = "200" ] || [ "$C" = "302" ]'
check "gunicorn socket"         bash -c '[ -S /run/oentbox/oentbox.sock ]'
for s in oentbox oentbox-celery nginx redis-server postgresql; do
  check "service $s active"     bash -c "systemctl is-active $s | grep -q active"
done
check "TLS cert >14 days left"  bash -c 'E=$(curl -sS -m 15 -o /dev/null -w "%{ssl_verify_result}" https://oentbox.com/ 2>/dev/null); D=$(echo | openssl s_client -servername oentbox.com -connect oentbox.com:443 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2); [ -n "$D" ] && [ $(( $(date -d "$D" +%s) - $(date +%s) )) -gt 1209600 ]'
check "disk / below 90%"        bash -c '[ $(df --output=pcent / | tail -1 | tr -dc 0-9) -lt 90 ]'
check "DB reachable"            bash -c 'cd /opt/oentbox && set -a && . ./.env && set +a && .venv/bin/python manage.py check --database default >/dev/null'

if [ "$FAIL" = "1" ]; then
  say "=== HEALTH CHECK FAILED ==="
  send_alert_dedup health "oentbox health check FAILED" "$FAIL_LIST"
else
  say "=== all checks passed ==="
  alert_recovered health "oentbox health check RECOVERED"
fi
exit $FAIL
