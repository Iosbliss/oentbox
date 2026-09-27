#!/bin/bash
# Shared alerting helper for oentbox ops scripts.
# Config is read from /opt/oentbox/ops/alert.conf first, then /opt/oentbox/.env.
# See /opt/oentbox/ops/alert.conf.example for the supported settings.
ALERT_LOG=${ALERT_LOG:-/var/log/oentbox-alerts.log}
ALERT_STATE_DIR=${ALERT_STATE_DIR:-/var/lib/oentbox-alerts}
ALERT_REPEAT_SECONDS=${ALERT_REPEAT_SECONDS:-86400}

alert_config() {
  for f in /opt/oentbox/ops/alert.conf /opt/oentbox/.env; do
    [ -f "$f" ] || continue
    set -a
    . "$f" 2>/dev/null || true
    set +a
  done
}

alert_channels() {
  local ch=""
  [ -n "${ALERT_WEBHOOK_URL:-}" ] && ch="$ch ${ALERT_WEBHOOK_KIND:-slack}-webhook"
  if [ -n "${ALERT_TELEGRAM_TOKEN:-}" ] && [ -n "${ALERT_TELEGRAM_CHAT_ID:-}" ]; then ch="$ch telegram"; fi
  if [ -n "${ALERT_EMAIL_TO:-}" ] && [ -n "${ALERT_SMTP_HOST:-}" ]; then ch="$ch email"; fi
  echo "${ch# }"
}

alert_log() {
  printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$ALERT_LOG" 2>/dev/null || true
}

send_alert() {
  local subject="$1" body="${2:-}" text=""
  text="[oentbox $(hostname)] $subject"
  [ -n "$body" ] && text="$text
$body"
  alert_log "ALERT $subject"
  [ -n "$body" ] && printf '%s\n' "$body" | while IFS= read -r l; do alert_log "  $l"; done

  local channels
  channels=$(alert_channels)
  if [ -z "$channels" ]; then
    alert_log "(no alert channel configured - log + systemd unit failure only)"
    return 0
  fi

  if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
    local kind=${ALERT_WEBHOOK_KIND:-slack} payload="" ok=1
    case "$kind" in
      ntfy)
        curl -sS -m 15 --data-binary "$text" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1 || ok=0
        ;;
      discord)
        payload=$(ALERT_TEXT="$text" /usr/bin/python3 -c 'import json,os;print(json.dumps({"content":os.environ["ALERT_TEXT"]}))' 2>/dev/null)
        [ -n "$payload" ] && curl -sS -m 15 -X POST -H 'Content-Type: application/json' --data-binary "$payload" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1 || ok=0
        ;;
      *)
        payload=$(ALERT_TEXT="$text" /usr/bin/python3 -c 'import json,os;print(json.dumps({"text":os.environ["ALERT_TEXT"]}))' 2>/dev/null)
        if [ -n "$payload" ]; then
          curl -sS -m 15 -X POST -H 'Content-Type: application/json' --data-binary "$payload" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1 || ok=0
        else
          ok=0
        fi
        ;;
    esac
    if [ "$ok" = 1 ]; then alert_log "webhook ($kind) alert sent"; else alert_log "webhook ($kind) alert FAILED"; fi
  fi

  if [ -n "${ALERT_TELEGRAM_TOKEN:-}" ] && [ -n "${ALERT_TELEGRAM_CHAT_ID:-}" ]; then
    if curl -sS -m 15 -X POST --data-urlencode "chat_id=${ALERT_TELEGRAM_CHAT_ID}" --data-urlencode "text=$text" \
        "https://api.telegram.org/bot${ALERT_TELEGRAM_TOKEN}/sendMessage" >/dev/null 2>&1; then
      alert_log "telegram alert sent"
    else
      alert_log "telegram alert FAILED"
    fi
  fi

  if [ -n "${ALERT_EMAIL_TO:-}" ] && [ -n "${ALERT_SMTP_HOST:-}" ]; then
    if ALERT_TO="$ALERT_EMAIL_TO" ALERT_TEXT="$text" /usr/bin/python3 "$(dirname "${BASH_SOURCE[0]}")/send_alert_email.py" >> "$ALERT_LOG" 2>&1; then
      alert_log "email alert sent"
    else
      alert_log "email alert FAILED"
    fi
  fi
}

# Alert once per distinct failure; re-alert at most every ALERT_REPEAT_SECONDS.
send_alert_dedup() {
  local key="$1" subject="$2" body="${3:-}" sig="" prev_sig="" prev_ts="" now_ts=0 state=""
  mkdir -p "$ALERT_STATE_DIR" 2>/dev/null || true
  state="$ALERT_STATE_DIR/$key"
  sig=$(printf '%s' "$body" | md5sum | cut -d' ' -f1)
  now_ts=$(date +%s)
  if [ -f "$state" ]; then
    prev_sig=$(sed -n 1p "$state" 2>/dev/null)
    prev_ts=$(sed -n 2p "$state" 2>/dev/null)
    if [ "$sig" = "$prev_sig" ] && [ -n "$prev_ts" ] && [ $(( now_ts - prev_ts )) -lt "$ALERT_REPEAT_SECONDS" ]; then
      alert_log "ALERT $subject suppressed (same failure, last sent $(( now_ts - prev_ts ))s ago)"
      return 0
    fi
  fi
  printf '%s\n%s\n' "$sig" "$now_ts" > "$state" 2>/dev/null || true
  send_alert "$subject" "$body"
}

# Send a one-off recovery notice if this check group was previously failing.
alert_recovered() {
  local key="$1" subject="$2"
  if [ -f "$ALERT_STATE_DIR/$key" ]; then
    rm -f "$ALERT_STATE_DIR/$key" 2>/dev/null || true
    send_alert "$subject" "previous failure has cleared"
  fi
}
