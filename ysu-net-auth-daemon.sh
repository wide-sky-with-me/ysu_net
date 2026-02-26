#!/usr/bin/env bash
set -euo pipefail

NET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${YSU_NET_ENV_FILE:-/etc/ysu-net-auth.env}"

if [[ -r "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

PY="${YSU_NET_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PY="python3"
  else
    PY="python"
  fi
fi

LOGIN_SCRIPT="${YSU_NET_LOGIN_SCRIPT:-$NET_DIR/ysu_api.py}"
SERVICE_NAME="${YSU_SERVICE:-校园网}"
CHECK_INTERVAL_SEC="${YSU_NET_CHECK_INTERVAL_SEC:-15}"
RETRY_SLEEP_SEC="${YSU_NET_RETRY_SLEEP_SEC:-30}"
MAX_WAIT_SEC="${YSU_NET_MAX_WAIT_SEC:-60}"
DEBUG_FLAG=""
if [[ "${YSU_NET_DEBUG:-0}" == "1" ]]; then
  DEBUG_FLAG="--debug"
fi

if [[ ! -f "$LOGIN_SCRIPT" ]]; then
  echo "[FATAL] missing login script: $LOGIN_SCRIPT"
  exit 1
fi

if [[ -z "${YSU_USER:-}" || -z "${YSU_PASS:-}" ]]; then
  echo "[WARN] YSU_USER/YSU_PASS not set (check $ENV_FILE)"
fi

echo "[INFO] daemon started: login_script=$LOGIN_SCRIPT service=$SERVICE_NAME interval=${CHECK_INTERVAL_SEC}s"

while true; do
  ts="$(date '+%F %T')"

  if "$PY" "$LOGIN_SCRIPT" status >/dev/null 2>&1; then
    echo "[$ts] online"
    sleep "$CHECK_INTERVAL_SEC"
    continue
  fi

  echo "[$ts] offline -> login (service=$SERVICE_NAME)"

  if [[ -z "${YSU_USER:-}" || -z "${YSU_PASS:-}" ]]; then
    echo "[$ts] missing credentials -> sleep ${RETRY_SLEEP_SEC}s"
    sleep "$RETRY_SLEEP_SEC"
    continue
  fi

  if "$PY" "$LOGIN_SCRIPT" login --service "$SERVICE_NAME" --max-wait "$MAX_WAIT_SEC" $DEBUG_FLAG; then
    echo "[$ts] login ok"
    sleep "$CHECK_INTERVAL_SEC"
  else
    echo "[$ts] login failed -> sleep ${RETRY_SLEEP_SEC}s"
    sleep "$RETRY_SLEEP_SEC"
  fi
done
