#!/bin/bash
# Safe deploy/update for oentbox: config guard, migrations, static rebuild with leak guard,
# service restart and post-deploy verification. Run as root: /opt/oentbox/ops/deploy.sh
set -uo pipefail
APP=/opt/oentbox
LOG=/var/log/oentbox-deploy.log
cd "$APP" || exit 1
. "$APP/ops/lib_alert.sh"
alert_config
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
fail() { say "ABORT: $*"; send_alert "oentbox deploy aborted" "$*"; exit 1; }

say "=== deploy start (git $(git rev-parse --short HEAD 2>/dev/null || echo unknown)) ==="

# 1. config guard: static dirs must never include the project root again
if ! out=$(/usr/bin/python3 ops/guard_static_dirs.py config/settings.py 2>&1); then
  fail "$out"
fi
say "OK   static dirs config guard"

set -a
. "$APP/.env"
set +a

# 2. system checks
.venv/bin/python manage.py check || fail "django system check failed"
say "OK   django system check"

# 3. rollback aid: snapshot current staticfiles (keep the 3 most recent)
tar -czf "/root/oentbox-staticfiles-$(date +%Y%m%d%H%M%S).tgz" -C "$APP" staticfiles 2>/dev/null || true
ls -1t /root/oentbox-staticfiles-*.tgz 2>/dev/null | tail -n +4 | xargs -r rm -f

# 4. migrations + static rebuild
.venv/bin/python manage.py migrate --noinput || fail "migrations failed"
say "OK   migrations applied"
.venv/bin/python manage.py collectstatic --noinput >/dev/null || fail "collectstatic failed"
say "OK   collectstatic"

# 5. leak guard: nothing sensitive may be web-served
if ! out=$(/usr/bin/python3 ops/scan_staticfiles.py 2>&1); then
  fail "leak guard tripped: $out"
fi
say "OK   leak guard"

# 5b. the service user must be able to read the code and boot the app.
# A root-only file or an import error here is a 502 the moment gunicorn restarts,
# so catch it before restarting anything.
chgrp -R www-data "$APP"/core "$APP"/config "$APP"/templates "$APP"/static "$APP"/ops 2>/dev/null || true
chmod -R g+r "$APP"/core "$APP"/config "$APP"/templates "$APP"/static "$APP"/ops 2>/dev/null || true
if ! runuser -u www-data -- bash -c "cd $APP && set -a && . ./.env && set +a && .venv/bin/python -c 'import config.wsgi'" >/dev/null 2>&1; then
  say "ABORT: the app cannot be imported as www-data"
  runuser -u www-data -- bash -c "cd $APP && set -a && . ./.env && set +a && .venv/bin/python -c 'import config.wsgi'" 2>&1 | tail -6 | tee -a "$LOG"
  fail "app fails to import as www-data (file permissions or import error) - refusing to restart"
fi
say "OK   app imports as the service user"

# 6. restart + verify
systemctl restart oentbox oentbox-celery || fail "service restart failed"
sleep 4
say "OK   services restarted"

# 6b. pre-warm the poster cache so visitors never trigger the optimiser
if [ -f "$APP"/ops/warm_images.py ]; then
  nohup runuser -u www-data -- "$APP"/.venv/bin/python "$APP"/ops/warm_images.py     >> /var/log/oentbox-warm.log 2>&1 &
  say "OK   poster cache warm started in background"
fi
if ops/health_check.sh >/dev/null 2>&1; then
  say "=== deploy verified OK ==="
else
  say "=== deploy finished but POST-DEPLOY HEALTH CHECK FAILED ==="
  send_alert "oentbox deploy health check failed" "$(tail -20 /var/log/oentbox-health.log 2>/dev/null)"
  exit 1
fi
