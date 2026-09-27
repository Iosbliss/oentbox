#!/bin/bash
# Shared alerting helper for oentbox ops scripts.
# Config is read from /opt/oentbox/ops/alert.conf first, then /opt/oentbox/.env.
# See /opt/oentbox/ops/alert.conf.example for the supported settings.
ALERT_LOG=${ALERT_LOG:-/var/log/oentbox-alerts.log}
ALERT_UNDELIVERED_LOG=${ALERT_UNDELIVERED_LOG:-/var/log/oentbox-alerts-undelivered.log}
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

# Send an alert through every configured channel.
# Returns 0 if at least one channel accepted it, 1 if a configured channel failed
# (so callers can retry instead of silently losing the alert).
send_alert() {
  local subject="$1" body="${2:-}" text="" configured=0 delivered=0
  text="[oentbox $(hostname)] $subject"
  [ -n "$body" ] && text="$text
$body"
  alert_log "ALERT $subject"
  [ -n "$body" ] && printf '%s\n' "$body" | while IFS= read -r l; do alert_log "  $l"; done

  local channels kind payload http
  channels=$(alert_channels)
  if [ -z "$channels" ]; then
    alert_log "(no alert channel configured - log + systemd unit failure only)"
    return 0
  fi

  if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
    configured=$((configured + 1))
    kind=${ALERT_WEBHOOK_KIND:-slack}
    http=""
    case "$kind" in
      ntfy)
        http=$(curl -sS -f -m 15 -o /dev/null -w '%{http_code}' --data-binary "$text" "$ALERT_WEBHOOK_URL" 2>/dev/null) || http=""
        ;;
      discord)
        payload=$(ALERT_TEXT="$text" /usr/bin/python3 -c 'import json,os;print(json.dumps({"content":os.environ["ALERT_TEXT"]}))' 2>/dev/null)
        [ -n "$payload" ] && http=$(curl -sS -f -m 15 -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data-binary "$payload" "$ALERT_WEBHOOK_URL" 2>/dev/null) || http=""
        ;;
      *)
        payload=$(ALERT_TEXT="$text" /usr/bin/python3 -c 'import json,os;print(json.dumps({"text":os.environ["ALERT_TEXT"]}))' 2>/dev/null)
        [ -n "$payload" ] && http=$(curl -sS -f -m 15 -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data-binary "$payload" "$ALERT_WEBHOOK_URL" 2>/dev/null) || http=""
        ;;
    esac
    if [ -n "$http" ]; then
      alert_log "webhook ($kind) alert delivered (HTTP $http)"
      delivered=$((delivered + 1))
    else
      alert_log "webhook ($kind) alert FAILED (no 2xx response from $ALERT_WEBHOOK_URL)"
    fi
  fi

  if [ -n "${ALERT_TELEGRAM_TOKEN:-}" ] && [ -n "${ALERT_TELEGRAM_CHAT_ID:-}" ]; then
    configured=$((configured + 1))
    http=$(curl -sS -f -m 15 -o /dev/null -w '%{http_code}' -X POST \
      --data-urlencode "chat_id=${ALERT_TELEGRAM_CHAT_ID}" --data-urlencode "text=$text" \
      "https://api.telegram.org/bot${ALERT_TELEGRAM_TOKEN}/sendMessage" 2>/dev/null) || http=""
    if [ -n "$http" ]; then
      alert_log "telegram alert delivered (HTTP $http)"
      delivered=$((delivered + 1))
    else
      alert_log "telegram alert FAILED"
    fi
  fi

  if [ -n "${ALERT_EMAIL_TO:-}" ] && [ -n "${ALERT_SMTP_HOST:-}" ]; then
    configured=$((configured + 1))
    if ALERT_TO="$ALERT_EMAIL_TO" ALERT_TEXT="$text" /usr/bin/python3 "$(dirname "${BASH_SOURCE[0]}")/send_alert_email.py" >> "$ALERT_LOG" 2>&1; then
      alert_log "email alert delivered to $ALERT_EMAIL_TO"
      delivered=$((delivered + 1))
    else
      alert_log "email alert FAILED"
    fi
  fi

  if [ "$delivered" = 0 ]; then
    alert_log "DELIVERY FAILED on all $configured configured channel(s) - alert kept in $ALERT_UNDELIVERED_LOG"
    {
      printf '=== %s %s\n' "$(date '+%F %T')" "$subject"
      printf '%s\n' "$body"
    } >> "$ALERT_UNDELIVERED_LOG" 2>/dev/null || true
    return 1
  fi
  return 0
}

# Alert once per distinct failure; re-alert at most every ALERT_REPEAT_SECONDS.
# The dedup state is only recorded when delivery actually succeeded, so an
# undelivered alert is retried on the next run instead of being suppressed.
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
      alert_log "ALERT $subject suppressed (same failure, last delivered $(( now_ts - prev_ts ))s ago)"
      return 0
    fi
  fi
  if send_alert "$subject" "$body"; then
    printf '%s\n%s\n' "$sig" "$now_ts" > "$state" 2>/dev/null || true
    return 0
  fi
  alert_log "ALERT $subject not deduplicated (delivery failed - will retry next run)"
  return 1
}

# Send a one-off recovery notice if this check group was previously failing.
alert_recovered() {
  local key="$1" subject="$2"
  if [ -f "$ALERT_STATE_DIR/$key" ]; then
    rm -f "$ALERT_STATE_DIR/$key" 2>/dev/null || true
    send_alert "$subject" "previous failure has cleared"
  fi
}
