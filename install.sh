#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
SYNC_ARGS=(--locked)
INSTALL_ARGS=()
BROWSER=0
for arg in "$@"; do
  case "$arg" in
    --browser) BROWSER=1; SYNC_ARGS+=(--extra browser) ;;
    --offline) SYNC_ARGS+=(--offline) ;;
    --system|--no-service) INSTALL_ARGS+=("$arg") ;;
    -h|--help)
      echo "用法：bash install.sh [--system] [--no-service] [--browser] [--offline]"
      echo "默认普通用户安装；--offline 使用已有 uv/Python/依赖缓存。"
      exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done
if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv，请先安装 uv 并加入 PATH：https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 2
fi
printf '\n[1/2] 准备 Python 环境和项目依赖…\n' >&2
if ! uv sync "${SYNC_ARGS[@]}"; then
  printf '\n[失败] 依赖安装未完成，请根据上方错误检查网络或缓存，再重新运行安装命令。\n' >&2
  exit 2
fi
if (( BROWSER )); then
  if [[ " ${SYNC_ARGS[*]} " == *" --offline "* ]]; then
    echo "离线模式不下载 Chromium，请预先安装对应浏览器运行时。"
  else
    printf '\n[进行中] 安装 Chromium 浏览器，首次下载可能需要几分钟…\n' >&2
    if ! .venv/bin/python -m playwright install chromium; then
      printf '\n[失败] 浏览器安装未完成。请根据上方错误处理后重新安装，或不带 --browser 使用 API 方式。\n' >&2
      exit 2
    fi
  fi
fi
printf '\n[2/2] 安装管理命令和运行配置…\n' >&2
exec .venv/bin/python -m ysu_net.manager.install "${INSTALL_ARGS[@]}"
