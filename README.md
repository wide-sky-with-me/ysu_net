# ysu-net · 燕山大学校园网管理工具

项目分为 **Linux 命令行版（Shell / Python）** 与 **Tauri 图形版（Windows / Linux / macOS / Rust 认证）**。两种产品保持配置和认证语义兼容，不再共用 Python 桌面旁车。入口与职责见[项目架构](docs/architecture.md)。

命令行统一使用 `ysu`，支持 Linux + Python 3.12；systemd 管理后台服务，无 systemd 时可用前台守护。默认 API 认证，浏览器认证按需安装。终端交互参考 [clash-for-linux](https://github.com/wnlen/clash-for-linux)，认证使用本项目的 Portal / CAS 实现。

默认 API 后端的校园网认证闭环、中国移动切换和用户级后台服务已有历史验收记录。支持 `ysu info` 查看门户账户信息，`ysu doctor` / `ysu doctor --network` 诊断环境和连接。命令与菜单见[使用说明](docs/usage.md)，历史实测范围见[真实网络验收](docs/live-test.md)与[远端部署验收](docs/deployment-test.md)，不作为新桌面版本的验收成绩。
可以先在非校园网环境安装、配置和运行 `ysu doctor`；登录和真实状态查询需要接入校园网。
敏感资料处理、审计范围与发布前检查见[敏感信息与发布检查](docs/security.md)。

## 桌面版（Windows / Linux / macOS）

自 **v0.2.0** 起，桌面版采用 **Tauri 2 + Svelte + 全 Rust 认证和后台**：三平台共用界面与原生逻辑，不依赖 Python、Node 或 Playwright 认证运行时。正式安装包从 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载；云端构建见[Tauri 桌面说明](docs/tauri-desktop.md#构建前提)，界面见[设计说明](docs/rust-desktop-design.md)。

支持[多账号热切换与可选流量换号](docs/accounts.md)：界面管理账号，CLI/守护复用账号簿；仅确认门户连续报告零剩余流量时自动尝试备用账号，缺失流量不猜测。

认证、诊断与平台限制见[Tauri 运行语义](docs/tauri-desktop.md#运行语义)；当次成绩与历史现场证据见[桌面验收导航](docs/desktop-acceptance.md)，不把已有在线会话读取、离线 Demo 或旧版成绩当作当前登录与升级成功。

0.2.2 集中侧栏“关于”、随包日志、连接光环与操作浮层，修复检查更新时的 TLS provider 初始化崩溃；在线运营商显示和自启 / 设置反馈以核心及原生回读为准。客户端支持有条件的差分传输，但**本次 0.2.2 公开资产只有完整包，没有差分附件**；无可信基线首更仍走整包，后续补丁与还原整包都须通过原公钥和受签名版本验证，失败仅下载阶段最多回退一次整包。交互规则见[设计说明](docs/rust-desktop-design.md)，平台、缓存和信任边界见[软件更新](docs/updates.md)。

### 发行与候选状态

**正式 v0.2.2 已发布并成为 Latest**，下载以 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 为准；标签源码、云端签名、公开资产复核状态及未覆盖范围见[0.2.2 发布验收](docs/desktop-release-0.2.2.md)。正式发布不等于真实校园网登录、软件内跨版本原位升级或失败回滚已通过。升级前先看[迁移说明](docs/migration.md#桌面-v022-升级)；旧版若点击检查更新就退出，可从正式 Release 手工安装，不关闭 TLS 校验或验签。

当前开发源码版本仍为 0.2.2，已回归的[只读观察与账户来源绑定](docs/tauri-desktop.md#独立只读状态观察开发源码)及本轮尚待 CI 的[精确门户来源变体与分类诊断](docs/tauri-desktop.md#门户导航与诊断开发源码)均未新发行、未部署或确认 Win11 现场，正式 0.2.2 安装包不含这些开发改进。

编译、打包和产品测试只在 GitHub Actions 执行；开发构建使用独立构建分支，不打版本标签、不发布正式 Release。云端失败不回退本机编译，本机只按授权下载、校验云端产物并做安装 / 运行验收。工作流见[原生桌面 CI](https://github.com/wide-sky-with-me/ysu_net/actions/workflows/tauri.yml)，实际成绩与未覆盖范围见[桌面验收导航](docs/desktop-acceptance.md)。

原 Qt 图形版（`ysu-gui`）及 Python 桌面原型已从源码移除。`v0.1.0` 标签和 Qt 附件保留历史，不作为新版下载入口。Windows 旧 Inno 版与当前用户 NSIS 版不互相替换；旧 0.2.1 候选也不能等待同版本自动升级，应按[迁移说明](docs/migration.md#桌面-v021-及旧候选包)手动安装正式版。Linux `.deb` 继续按系统包升级，macOS 13.5+ 按 Apple 芯片 / Intel 分包；更新包签名不等于 Windows 发布者签名或 Apple 签名 / 公证。安装前提见[桌面客户端](docs/wiki/Desktop-Client.md)。

## 选择版本与交流入口

- **Linux 命令行版**：以下安装步骤使用默认分支 `main`，适合终端、服务器和 systemd 后台运行。
- **三平台桌面版**：选择正式 Release 中与系统、架构对应的附件；正式版与开发工作树的区别见[发行与候选状态](#发行与候选状态)，云端构建见[Tauri 说明](docs/tauri-desktop.md#构建前提)。独立 Python CLI 不是桌面运行时。
- **入门与排障**：[Wiki 源文档](docs/wiki/Home.md) · [GitHub Wiki](https://github.com/wide-sky-with-me/ysu_net/wiki) · [支持与反馈](SUPPORT.md)。
- **社区协作**：[Discussions 问答与建议](https://github.com/wide-sky-with-me/ysu_net/discussions) · [Issue 故障反馈](https://github.com/wide-sky-with-me/ysu_net/issues/new/choose) · [贡献指南](CONTRIBUTING.md) · [安全问题私密报告](SECURITY.md)。

公开反馈前按[脱敏清单](docs/security.md#公开反馈的脱敏清单)检查正文、日志与截图。普通输出不等于匿名报告；无需提供真实账号、密码、会话、IP/MAC 或完整配置。

## 快速开始

先准备 Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后执行：

```bash
git clone https://github.com/wide-sky-with-me/ysu_net.git
cd ysu_net
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
```

安装会创建 `.venv`、按 `uv.lock` 安装依赖、注册用户级服务，并生成 `~/.local/bin/ysu`、`ysuon`、`ysuoff`。
请将 `~/.local/bin` 加入 PATH。安装依赖需要互联网；安装过程不访问校园网，不自动登录或启动服务。
**安装后请保留项目目录和 `.venv`，管理命令及服务直接引用这里的文件。**
上面的 PATH 设置只影响当前终端。需要长期生效时，将同一行加入 Bash 的 `~/.bashrc`
或 Zsh 的 `~/.zshrc`，然后重新打开终端。

```bash
ysu config account          # 交互输入账号密码（密码不回显）
ysu service                 # 选择校园网 / 移动 / 联通 / 电信
ysu doctor                  # 仅检查本地环境
ysu login                   # 在校园网内手动验证登录
ysu on                      # 开启后台自动重连
ysu boot on                 # 可选：启用自启
```

直接执行 `ysu` 打开交互菜单；非交互终端中显示帮助。开发版主菜单 **16** 或 `ysu accounts` 进入[多账号管理与流量自动换号](docs/accounts.md#shell-版交互菜单)。
只安装 Python 环境而不注册服务：`uv sync --locked`，然后运行 `uv run ysu <命令>`。
也支持 `uv run python -m ysu_net <命令>`；安装注册后的 `ysu` 可从任意目录运行。

终端输出会用颜色区分成功、提示和失败；菜单显示当前服务及账号配置状态，进入菜单不会自动访问网络。
耗时操作会显示等待提示，诊断会汇总通过和待处理项。设置 `NO_COLOR=1` 或 `TERM=dumb` 可关闭颜色，
重定向或管道输出自动使用纯文本。`status/info --raw` 只输出原始 JSON，不附加标题或进度信息。
`ysu config show` 在终端中显示中文配置摘要，重定向时保留 JSON；也可用 `ysu config show --raw` 显式获取 JSON。

其他安装方式：

```bash
bash install.sh --browser       # 额外安装 Playwright 和 Chromium
bash install.sh --no-service    # 只安装命令，适合没有 systemd / 用户总线的环境
bash install.sh --offline       # 使用已有 uv、Python 和依赖缓存；不联网下载
sudo env PATH="$PATH" bash install.sh --system  # 系统级服务
```

系统级安装的命令位于 `/usr/local/bin`，配置位于 `/etc/ysu-net/config.json`；
使用 `sudo ysu ...` 管理。系统服务以 root 运行，应使用可信且受控的项目目录。
用户级配置位于 `${XDG_CONFIG_HOME:-~/.config}/ysu-net/config.json`。
同一台机器建议只启用一种安装范围，避免两个服务同时操作校园网。

用户服务随用户管理器启动。需要在未登录时也自动连接，可由管理员执行
`sudo loginctl enable-linger <用户名>`；安装器不会自动修改此系统设置。
如果 `systemctl --user` 无法连接用户总线，请登录本机用户会话，或使用 `--no-service`。

## 项目结构

源码按 Python 命令行、Rust 桌面认证与后台、共用 Svelte 前端及平台集成分层。目录、命令名称和构建链路统一维护在[项目架构](docs/architecture.md)，不按操作系统复制界面。

账号配置、锁文件位于用户或系统配置目录，`.venv` 和构建产物不提交到仓库。
旧版根目录认证脚本、守护脚本及 `requirements.txt` 已移除，迁移方式见下文链接。

## 文档导航

- [产品入口与项目架构](docs/architecture.md)：命令行与三平台桌面的关系、目录职责和兼容边界。
- [命令行使用与配置](docs/usage.md)：完整命令、日常操作、配置和故障排查。
- [更新、卸载与旧版迁移](docs/migration.md)：命令重装、旧服务清理与入口变更。
- [Tauri 桌面版](docs/tauri-desktop.md)：云端构建、运行与演示；历次证据见[桌面验收导航](docs/desktop-acceptance.md)，视觉与更新语义分别见[设计说明](docs/rust-desktop-design.md)和[更新说明](docs/updates.md)。
- [开发与验证](docs/development.md)：模块职责、云端离线测试与 Python 分发构建。

## 云端验证

以下命令仅由 GitHub Actions runner 执行；本机不运行产品构建或测试。

```bash
uv sync --locked --extra browser
uv run --extra browser python -m unittest discover -s tests -v
```

连接相关单元测试使用 mock，不需要校园网、真实账号或浏览器运行时。真实 API / 校园网认证验收独立执行，结果与未覆盖场景见[验收记录](docs/live-test.md)。
