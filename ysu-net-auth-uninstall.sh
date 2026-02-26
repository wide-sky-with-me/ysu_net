#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${YSU_NET_SERVICE_NAME:-ysu-net-auth.service}"
UNIT_PATH="/etc/systemd/system/$SERVICE_NAME"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "[ERROR] systemctl not found"
  exit 1
fi

sudo systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true

if [[ -f "$UNIT_PATH" ]]; then
  sudo rm -f "$UNIT_PATH"
fi

sudo systemctl daemon-reload
sudo systemctl reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true

echo "[OK] uninstalled: $SERVICE_NAME"
echo "[INFO] unit removed: $UNIT_PATH"
echo "[INFO] config kept: ${YSU_NET_ENV_FILE:-/etc/ysu-net-auth.env}"

