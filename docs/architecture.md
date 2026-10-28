# 产品入口与项目架构

[返回首页](../README.md) · [命令行使用](usage.md) · [桌面开发](tauri-desktop.md) · [开发验证](development.md)

## 两个产品

项目分为 **Shell 命令行版** 与 **Tauri 图形版**。Windows、Linux、macOS 是图形版的发行目标，不是三套产品。自 `v0.2.0` 起，桌面由 Qt 迁移为 Tauri，独立 Python CLI 同步版本；旧 `v0.1.0` Qt 标签与附件保留历史，不覆盖。

| 产品 | 入口 | 认证实现与运行时 |
| --- | --- | --- |
| Shell 命令行版 | `ysu`、`python -m ysu_net` | Python；Shell 负责安装和命令包装，不复制 Bash 认证 |
| Tauri 图形版 | `ysu-net` / 系统应用图标 | Svelte 界面 + Rust 原生后台 + Rust 认证库；无 Python/Node 认证旁车 |

`ysuon`、`ysuoff` 是 CLI 快捷方式。原 Qt 客户端（`ysu-gui`）与 Python JSONL 桌面原型已移除。Vite、浏览器演示和原生演示属于 GitHub Actions runner 的开发验收链路，不另行分发为 Web 产品；本机不启动开发或预览服务。

新的桌面认证实现替代此前 Python 旁车方案，原因见 [Rust 桌面决策](../.agents/notes/proposals/desktop/2026-10-14-rust-desktop.md)。

## 代码边界

```text
ysu_net/
├── install.sh / uninstall.sh        CLI 安装、卸载
├── src/ysu_net/
│   ├── auth/                       Python CLI 认证、账户解析
│   └── manager/                    CLI、配置、锁、守护与 systemd
├── desktop/
│   ├── src/                        三平台共用 Svelte 界面与 IPC 类型
│   ├── crates/ysu-auth/             Rust Portal/CAS、状态、切换、账户、CDP
│   ├── src-tauri/src/               Rust 后台、配置、窗口、托盘、自启
│   └── scripts/desktop.mjs          Node/Rust 原生构建入口
├── packaging/                      构建及浏览器、原生验收工具
├── tests/                          Python CLI 回归
└── docs/                           当前说明与独立的历史验收
```

[前端](../desktop/src/App.svelte)不处理认证协议或持久化密码。[原生后台](../desktop/src-tauri/src/runtime.rs)串行调度认证与重连，[认证库](../desktop/crates/ysu-auth/src/lib.rs)负责协议及结果核验，[配置层](../desktop/src-tauri/src/storage.rs)负责兼容存储和锁。[Tauri 主程序](../desktop/src-tauri/src/main.rs)集中系统集成；平台差异不扩散为三份界面。

两种语言不再共享同一认证执行器；变更协议时必须同时评估 Python 与 Rust，通过对应回归维护相同状态、账户和失败恢复语义。未知状态不当作离线，认证成功不以提交表单或收到 IPC 确认为依据。行为细节见[桌面运行语义](tauri-desktop.md#运行语义)与[CLI 开发](development.md)。

DNS 回退的已核验域名与地址由[包内 JSON](../src/ysu_net/auth/campus-addresses.json)统一维护，Rust 编译时嵌入，Python 默认 API 随包读取；解析、TLS 与各后端覆盖范围集中见[网络语义](tauri-desktop.md#dns-失败时的备用-ip开发源码云端待验)。该开发改动尚未云端验收或发行。

## 配置与进程

新桌面沿用 CLI 的配置字段、默认路径和运行锁协议。配置写锁与认证/守护运行锁分开，保存设置不争夺整个守护生命周期。共享配置不表示同时启用两套自动重连：同一配置只由一个运行器管理。多账号权威、账号簿与 Python 文件控制通道的适用范围集中见[多账号说明](accounts.md)。

CLI 的 Linux systemd 服务面向无桌面运行；图形版的托盘和用户登录自启面向桌面会话。配置目录、演示隔离、退出与自启行为集中见[桌面说明](tauri-desktop.md)，安装器仍按[CLI 安装方式](../README.md#快速开始)工作。

## 构建与发行边界

编译、打包与产品测试仅在 GitHub Actions runner 执行，平台构建 SDK 也只作为 runner 前提；云端失败不回退本地编译。本机只下载、校验云端产物并安装或运行，纯文档修改只做静态核对。开发构建使用独立分支，不打版本标签、不发布正式 Release。

| 链路 | 职责 | 入口 |
| --- | --- | --- |
| Python CLI 分发 | runner 生成 wheel / 源码包；保留现有安装器和依赖 | [pyproject.toml](../pyproject.toml)、runner 中的 `uv build` |
| Rust 桌面构建 | 对应平台 runner 构建原生程序及安装包，不冻结 Python | [desktop.mjs](../desktop/scripts/desktop.mjs)、[Tauri CI](../.github/workflows/tauri.yml) |

Tauri CI 定义四平台构建和离线验收；Linux `.deb` 与 Windows NSIS 安装包还会在运行器上实际安装，核对安装位置、卸载登记、菜单入口与图标，从安装位置运行原生冒烟后卸载并确认清理；macOS arm64 / x64 分别挂载 `.dmg`，核对应用与“应用程序”快捷方式，复制到 /Applications 后核对包标识、版本、最低系统、图标与本机架构，运行原生冒烟后删除。推送 `v*` 标签时，Release 作业依赖四个平台构建、原生与安装验收全部成功，再发布 Tauri 安装包、独立 Python 分发包和 `SHA256SUMS`。定义存在不代表本轮对应系统已经跑通，实际结果以对应 CI 运行为准。

Linux 包名仍为 `ysu-net`，0.2.0 高于旧 Qt 0.1.0，正常升级无需 `--reinstall`。Windows 旧 Inno Setup 与新版当前用户 NSIS 不会互相替换，先关闭旧自启、退出并卸载旧版；macOS 13.5+ 按 arm64 / x64 分包。Windows / macOS 安装包未签名，完整迁移要求见[迁移说明](migration.md#桌面-v020-升级)。

## 文档归属

首页负责两个产品的导航，架构页负责边界，桌面说明负责云端构建和运行语义，[设计说明](rust-desktop-design.md)负责视觉依据，[桌面验收导航](desktop-acceptance.md)串联各阶段证据与未覆盖范围。带日期的验收只对应当时源码与样本；此前 Python 图形版的校内成绩和旧旁车包不作为 Rust 桌面验收证据。
