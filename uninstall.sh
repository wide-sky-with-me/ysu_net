#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
exec "${YSU_NET_PYTHON:-$ROOT_DIR/.venv/bin/python}" -m ysu_net.manager.install --uninstall "$@"
