#!/usr/bin/env bash
set -euo pipefail

NET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="${YSU_NET_SERVICE_NAME:-ysu-net-auth.service}"
UNIT_PATH="/etc/systemd/system/$SERVICE_NAME"
ENV_PATH="${YSU_NET_ENV_FILE:-/etc/ysu-net-auth.env}"
DAEMON_SCRIPT="$NET_DIR/ysu-net-auth-daemon.sh"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "[ERROR] systemctl not found"
  exit 1
fi

if [[ ! -f "$DAEMON_SCRIPT" ]]; then
  echo "[ERROR] missing $DAEMON_SCRIPT"
  exit 1
fi

chmod +x "$DAEMON_SCRIPT" || true

if [[ ! -f "$ENV_PATH" ]]; then
  sudo install -m 600 /dev/null "$ENV_PATH"
  sudo bash -lc "cat > '$ENV_PATH' << 'EOF'
YSU_USER=
YSU_PASS=
YSU_SERVICE=校园网
YSU_NET_CHECK_INTERVAL_SEC=15
YSU_NET_RETRY_SLEEP_SEC=30
YSU_NET_MAX_WAIT_SEC=60
YSU_NET_DEBUG=0
EOF"
  echo "[OK] created $ENV_PATH"
else
  echo "[OK] env exists: $ENV_PATH"
fi

sudo bash -lc "cat > '$UNIT_PATH' << 'EOF'
[Unit]
Description=YSU network authentication daemon
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
EnvironmentFile=-$ENV_PATH
WorkingDirectory=$NET_DIR
ExecStart=/usr/bin/env bash $DAEMON_SCRIPT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo "[OK] installed and started: $SERVICE_NAME"
echo "[INFO] view logs: sudo journalctl -u $SERVICE_NAME -f"
echo "[INFO] edit config: sudo editor $ENV_PATH"

