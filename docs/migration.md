# 更新、卸载与旧版迁移

[返回首页](../README.md) · [使用与配置](usage.md) · [开发说明](development.md)

## 桌面 v0.2.3 升级

0.2.3 的发行进度和验证范围见[发布记录](desktop-release-0.2.3.md)。沿用 0.2.1 / 0.2.2 正式更新公钥、账号簿和配置格式；Windows / macOS 可主动检查更新或安装正式附件，Linux 使用对应 `.deb` 手动升级。旧候选、旧 Qt / Inno 安装及旧信任锚仍按下文迁移，不替换公钥或关闭 TLS / 验签。

升级前备份配置、退出旧客户端并停止另一套重连器。新版本可在校园 DNS 失败时使用核验地址连接，仍按原域名验证证书，不需要把配置域名改成 IP。账号切换以退出旧账号、登录目标并独立核验为准；不要根据按钮完成或服务 HTTP 200 判断成功。差分是否可用以实际发布清单和本机可信缓存为准，完整规则归[更新说明](updates.md#差分传输与一次回退)。

## 桌面 v0.2.2 升级

[正式 v0.2.2](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.2) 已发布并成为 Latest，标签源码、云端签名和公开附件核对见[发布验收](desktop-release-0.2.2.md)。本轮没有在本机安装新客户端，也未操作本机账号、配置、自启或认证状态；发布完成不等于真实软件内升级已验收。

- 正式 0.2.1 → 0.2.2 **沿用原正式更新公钥，不换信任锚**。Windows / macOS 用户可在 0.2.1 的“设置 → 外观与启动”中主动检查并确认，或手动安装对应正式附件；0.2.2 的更新入口在侧栏“关于”。旧版若点击检查更新就退出，可直接从正式 Release 手工升级，不通过关闭 TLS 校验、验签或更换公钥绕过。
- 本次 0.2.2 公开清单没有差分附件，只有完整更新包；0.2.1 客户端自身也只会下载整包。0.2.2 后续只有精确匹配的可信缓存与收益达标补丁才能差分；手动安装不保证建立缓存，无基线时直接新整包，不先下载旧包。双验签、一次下载回退及缓存配额统一见[更新说明](updates.md#差分传输与一次回退)，安装失败不会触发二次安装。
- Linux `.deb` 继续从 Releases 下载并按系统包手动升级，不提供原位安装或差分目标；Python CLI 更新方式不变。macOS 仍按 Apple 芯片 / Intel 分包，Windows 使用当前用户 NSIS；更新包签名不替代 Windows 发布者签名或 Apple 签名 / 公证。
- 升级前自行备份本机配置并退出旧客户端，不同时运行两套重连器；原账号与有效外观偏好不需要手工迁移。“自启后进入托盘”缺项沿用旧托盘启动行为，读取不重写自启项，新开关也不擅自启用原本关闭的自启或隐藏当前窗口。

0.2.0 和使用旧公钥的 0.2.1 候选仍按下一节手动安装正式版。真实签名载荷的跨版本原位升级、Windows / macOS 安装失败回滚及本轮校园网新登录尚未验收，不能用普通安装、Mock 或纯文本差分夹具代替；本页不承诺实际升级已经成功。

## 桌面 v0.2.1 及旧候选包

0.2.0 没有软件内更新入口，首次升级到 0.2.1 需从[正式 Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest)手动下载安装。此前自行构建或分发的 **0.2.1 候选包也必须手动安装正式版并重启**：首次正式更新发行建立了新的签名公钥基线，旧候选不会自动信任它，不能通过关闭验签或修改源来绕过。

备份本机配置后退出旧客户端，再按系统、架构安装正式附件，避免两套重连器并行；同版本候选不要等待软件内“0.2.1 → 0.2.1”更新。配置和账号资料不要上传到反馈。首次信任锚及维护约束见[决策](../.agents/notes/implemented/desktop/2026-10-24-first-signed-release-trust-anchor.md)，后续软件内更新的支持范围与限制见[更新指南](updates.md)。

## 桌面 v0.2.0 升级

自 **0.2.0** 起，桌面由 Qt 迁移为 Tauri，[对应 Release](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.0)的附件由四平台构建、原生和安装验收全部成功后发布。旧 `v0.1.0` Qt 附件、标签及历史验收保留，不替换为新版内容。升级前备份本机配置，关闭旧版自启并退出旧客户端，避免新旧重连器并行；不要把配置上传到反馈。

| 系统 | 从旧 Qt 0.1.0 迁移到 Tauri 0.2.0 |
| --- | --- |
| Windows 10 / 11 x64 | 先卸载旧 Inno Setup 版，再运行新版 NSIS 安装程序；两种安装器不会互相替换。新版按当前用户安装，不要求管理员权限，使用系统 WebView2；不要沿用指向旧程序的自启项。 |
| Ubuntu 22.04 及更新，x86_64 | 包名仍为 `ysu-net`；下载新版 `.deb` 后用 `sudo apt install ./新包.deb`（替换为实际文件名）正常升级。0.2.0 高于旧 0.1.0，无需 `--reinstall`。 |
| macOS 13.5 及更新 | 按 Apple 芯片（arm64）或 Intel（x64）选择各自 `.dmg`，退出旧程序后替换“应用程序”中的客户端；不是通用二进制。 |

Windows / macOS 安装包未签名，可能出现发布者或首次启动提示；仅从对应 Release 下载并核对附件 `SHA256SUMS`，按系统提示处理。Python `gui` 依赖和 `ysu-gui` 入口已移除，安装桌面版不需要 Python 环境；Linux Python CLI 独立保留，版本同步为 0.2.0。桌面构建与配置路径见[Tauri 说明](tauri-desktop.md)。

## 更新 Linux 命令行安装

在原项目目录更新。先停止重连，让代码和依赖更新完再启动；`ysu stop` 不会主动下线。

```bash
ysu stop
git pull --ff-only
bash install.sh                # 浏览器用户追加 --browser
ysu doctor
ysu on
```

重新安装会更新命令包装脚本和 systemd 单元，保留账号配置。项目目录和 `.venv` 需要保留。
仅拉取源码不会重写已生成的旧包装器；更新[命令启动隔离](development.md#模块职责)也需重新执行安装器。
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

## 多账号兼容

0.2.0 的[多账号能力](accounts.md)保留原活动配置格式，新增同目录 `config.accounts.json` 及 Python 所有者私有控制通道。查看旧配置不迁移；旧发行版仍可读取活动配置，但不会识别账号簿或热切换通道。更新守护后才可经 CLI 控制持锁进程；遇旧所有者未确认时停止旧进程再接管，不删除锁文件。

回退保留原活动配置和账号簿，其他保存账号不会自动写回旧单账号界面。当前 Rust 桌面没有接入 Python 文件通道，两种产品分别从自身入口切换；不要同时开启两套自动管理。

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
