# 更新、卸载与旧版迁移

[返回首页](../README.md) · [使用与配置](usage.md) · [开发说明](development.md)

## 更新当前安装

在原项目目录更新。先停止重连，让代码和依赖更新完再启动；`ysu stop` 不会主动下线。

```bash
ysu stop
git pull --ff-only
bash install.sh                # 浏览器用户追加 --browser
ysu doctor
ysu on
```

重新安装会更新命令包装脚本和 systemd 单元，保留账号配置。项目目录和 `.venv` 需要保留。
如果已经拉取代码导致旧命令找不到 `ysu.py`，直接运行以下命令后继续安装：

```bash
systemctl --user stop ysu-net.service
bash install.sh
```

系统级安装对应使用 `sudo systemctl stop ysu-net.service`、
`sudo env PATH="$PATH" bash install.sh --system` 和 `sudo ysu on`。
浏览器用户安装时追加 `--browser`。前台模式先按 Ctrl+C 停止守护，
更新时保留 `--no-service`，最后重新运行 `ysu daemon`。
如果 `git pull --ff-only` 提示存在本地修改或分支分歧，请先处理本地修改。

## 本次目录调整

| 旧入口或文件 | 新位置或用法 |
| --- | --- |
| `ysu.py` | `uv run ysu` 或 `uv run python -m ysu_net` |
| `ysu_api.py` | `src/ysu_net/auth/api.py`；运行 `uv run python -m ysu_net.auth.api ...` |
| `ysu_browser.py` | `src/ysu_net/auth/browser.py`；运行 `uv run --extra browser python -m ysu_net.auth.browser ...` |
| `ysu_common.py` | `src/ysu_net/auth/common.py` |
| `ysu_manager/` | `src/ysu_net/manager/` |
| `requirements.txt` | 已删除；使用 `uv sync --locked`，依赖以 `pyproject.toml` 和 `uv.lock` 为准 |
| `ysu-net-auth-*.sh` | 已删除；使用 `install.sh`、`uninstall.sh` 和 `ysu daemon` |

Python 导入对应调整为 `ysu_net.auth.api`、`ysu_net.auth.browser` 和 `ysu_net.manager`。
旧入口文件不会保留额外的兼容副本，调用它们的自定义脚本、定时任务和服务需要更新。
依赖 uv 之外的工具时，也可 `python -m pip install -e .`，浏览器依赖用
`python -m pip install -e '.[browser]'`；这两条命令不使用 `uv.lock`，可复现安装仍推荐 uv。

## 更早的 ysu-net-auth.service 迁移

如果安装过旧版 `ysu-net-auth-install.sh`，先停止并移除旧服务，避免两套守护同时登录：

```bash
sudo systemctl disable --now ysu-net-auth.service
sudo rm -f /etc/systemd/system/ysu-net-auth.service
sudo systemctl daemon-reload
```

以上只适用于旧服务 `ysu-net-auth.service`，新服务名为 `ysu-net.service`。
曾自定义旧服务名的用户需替换成自己实际使用的名称。
旧配置 `/etc/ysu-net-auth.env` 保留，不会作为 shell 文件执行或自动导入。
随后重新安装并交互配置账号：

```bash
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
ysu config account
ysu service
ysu doctor
# 接入校园网后
ysu on
```

## 卸载

在项目目录执行：

```bash
bash uninstall.sh                  # 删除用户级服务和命令，保留账号配置
bash uninstall.sh --purge          # 同时删除账号配置
sudo env PATH="$PATH" bash uninstall.sh --system  # 系统级卸载
```

卸载会先停止服务，保留当前校园网连接、源码和 `.venv`；想下线先执行 `ysu off`。
如果正在运行前台守护，先在对应终端按 Ctrl+C。
卸载器保留 `.venv` 中的开发入口；删除项目的 `.venv` 或源码属于后续手动清理。
