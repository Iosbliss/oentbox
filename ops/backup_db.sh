#!/bin/bash
# Nightly PostgreSQL backup for oentbox: pg_dump, archive validation, retention,
# full restore verification and alerting on failure.
#   ops/backup_db.sh                 run a backup (used by the systemd timer)
#   ops/backup_db.sh --verify-restore [dump]   restore the newest/latest dump and check it
set -uo pipefail

APP=/opt/oentbox
DEST=${BACKUP_DIR:-/var/backups/oentbox}
KEEP_DAILY=${BACKUP_KEEP_DAILY:-7}
KEEP_WEEKLY=${BACKUP_KEEP_WEEKLY:-4}
MIN_BYTES=${BACKUP_MIN_BYTES:-1000000}
LOG=/var/log/oentbox-backup.log

. "$APP/ops/lib_alert.sh"
alert_config
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
fail() { say "FAIL $*"; send_alert_dedup backup "oentbox database backup FAILED" "$*" >/dev/null 2>&1 || true; exit 1; }

set -a
. "$APP/.env"
set +a
DB=${DB_NAME:-oentbox}
DBUSER=${DB_USER:-oentbox}
PGHOST=${DB_HOST:-127.0.0.1}
PGPORT=${DB_PORT:-5432}
export PGPASSWORD="${DB_PASSWORD:-}"

newest_dump() { ls -1t "$DEST"/oentbox-*.dump 2>/dev/null | head -1; }

verify_restore() {
  local dump="${1:-$(newest_dump)}" tmpdb movies
  [ -n "$dump" ] && [ -f "$dump" ] || fail "no dump available to verify"
  tmpdb="oentbox_verify_$$"
  say "verifying restore of $(basename "$dump") into $tmpdb"
  runuser -u postgres -- dropdb --if-exists "$tmpdb" >/dev/null 2>&1 || true
  runuser -u postgres -- createdb "$tmpdb" >/dev/null 2>&1 || fail "cannot create verification database"
  if ! runuser -u postgres -- pg_restore --no-owner --no-privileges -d "$tmpdb" "$dump" >/dev/null 2>&1; then
    runuser -u postgres -- dropdb --if-exists "$tmpdb" >/dev/null 2>&1 || true
    fail "restore of $(basename "$dump") into $tmpdb failed"
  fi
  movies=$(runuser -u postgres -- psql -tAc "select count(*) from core_movie" "$tmpdb" 2>/dev/null | tr -d ' ')
  runuser -u postgres -- dropdb --if-exists "$tmpdb" >/dev/null 2>&1 || true
  if [ -z "$movies" ] || [ "$movies" -lt 1000 ]; then
    fail "restored database only contains ${movies:-0} movies"
  fi
  say "OK   restore verified: $movies movies readable from the restored copy"
}

if [ "${1:-}" = "--verify-restore" ]; then
  verify_restore "${2:-}"
  exit $?
fi

mkdir -p "$DEST" || fail "cannot create $DEST"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$DEST/oentbox-$STAMP.dump"
TMP="$OUT.part"

say "=== backup start (db=$DB at $PGHOST:$PGPORT) ==="
if ! pg_dump -h "$PGHOST" -p "$PGPORT" -U "$DBUSER" -Fc --no-owner --no-privileges -f "$TMP" "$DB"; then
  rm -f "$TMP"
  fail "pg_dump failed for database $DB"
fi
mv "$TMP" "$OUT" || fail "cannot finalise $OUT"
# let the postgres system user read the dump for restore verification
chown root:postgres "$OUT" 2>/dev/null || true
chmod 640 "$OUT"

SIZE=$(stat -c %s "$OUT")
[ "$SIZE" -ge "$MIN_BYTES" ] || fail "dump is suspiciously small ($SIZE bytes, minimum $MIN_BYTES)"
if ! pg_restore --list "$OUT" >/dev/null 2>&1; then
  fail "pg_restore cannot read the dump archive"
fi
TABLES=$(pg_restore --list "$OUT" 2>/dev/null | grep -c 'TABLE DATA')
say "OK   dump written: $OUT ($(numfmt --to=iec "$SIZE"), $TABLES tables with data)"

if [ "$(date +%u)" = 7 ]; then
  cp -p "$OUT" "$DEST/weekly-oentbox-$STAMP.dump" && say "OK   weekly long-term copy kept"
  verify_restore "$OUT"
fi

OLD=$(ls -1t "$DEST"/oentbox-*.dump 2>/dev/null | tail -n +$((KEEP_DAILY + 1)))
if [ -n "$OLD" ]; then
  echo "$OLD" | xargs -r rm -f
  say "OK   pruned $(echo "$OLD" | wc -l) daily dump(s) beyond $KEEP_DAILY"
fi
OLDW=$(ls -1t "$DEST"/weekly-oentbox-*.dump 2>/dev/null | tail -n +$((KEEP_WEEKLY + 1)))
if [ -n "$OLDW" ]; then
  echo "$OLDW" | xargs -r rm -f
  say "OK   pruned $(echo "$OLDW" | wc -l) weekly dump(s) beyond $KEEP_WEEKLY"
fi

say "=== backup complete ($(ls -1 "$DEST"/*.dump 2>/dev/null | wc -l) dump(s) retained) ==="
alert_recovered backup "oentbox database backup RECOVERED"
