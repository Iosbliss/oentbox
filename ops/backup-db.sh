#!/bin/bash
set -euo pipefail
cd /opt/oentbox
set -a; . ./.env; set +a
STAMP=$(date +%F-%H%M)
DIR=/opt/oentbox/backups
mkdir -p "$DIR"
PGPASSWORD="$DB_PASSWORD" pg_dump -U "$DB_USER" -h "$DB_HOST" "$DB_NAME" | gzip > "$DIR/oentbox-db-$STAMP.sql.gz"
chmod 600 "$DIR"/oentbox-db-*.sql.gz
ls -1t "$DIR"/oentbox-db-*.sql.gz | tail -n +8 | xargs -r rm -f
echo "$(date) backup ok: oentbox-db-$STAMP.sql.gz"