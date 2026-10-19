# 产品入口与项目架构

[返回首页](../README.md) · [命令行使用](usage.md) · [桌面开发](tauri-desktop.md) · [开发验证](development.md)

## 两个产品

项目分为 **Shell 命令行版** 与 **Tauri 图形版**。Windows、Linux、macOS 是图形版的发行目标，不是三套产品。当前原生迁移在 `feat/rust-desktop` 开发，尚未替换正式发布附件。

| 产品 | 入口 | 认证实现与运行时 |
| --- | --- | --- |
| Shell 命令行版 | `ysu`、`python -m ysu_net` | Python；Shell 负责安装和命令包装，不复制 Bash 认证 |
| Tauri 图形版 | `ysu-net` / 系统应用图标 | Svelte 界面 + Rust 原生后台 + Rust 认证库；无 Python/Node 认证旁车 |

`ysuon`、`ysuoff` 是 CLI 快捷方式。原 Qt 客户端（`ysu-gui`）与 Python JSONL 桌面原型已移除。Vite、浏览器演示和原生演示都是开发验收入口，不另行分发为 Web 产品。

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

## 配置与进程

新桌面沿用 CLI 的配置字段、默认路径和运行锁协议。配置写锁与认证/守护运行锁分开，保存设置不争夺整个守护生命周期。共享配置不表示同时启用两套自动重连：同一配置只由一个运行器管理。多账号权威、账号簿与 Python 文件控制通道的适用范围集中见[多账号说明](accounts.md)。

CLI 的 Linux systemd 服务面向无桌面运行；图形版的托盘和用户登录自启面向桌面会话。配置目录、演示隔离、退出与自启行为集中见[桌面说明](tauri-desktop.md)，安装器仍按[CLI 安装方式](../README.md#快速开始)工作。

## 构建与发行边界

| 链路 | 职责 | 入口 |
| --- | --- | --- |
| Python CLI 分发 | wheel / 源码包；保留现有安装器和依赖 | [pyproject.toml](../pyproject.toml)、`uv build` |
| Rust 桌面构建 | 本平台原生程序及安装包，不冻结 Python | [desktop.mjs](../desktop/scripts/desktop.mjs)、[Tauri CI](../.github/workflows/tauri.yml) |

Tauri CI 定义跨平台构建和离线验收；Linux `.deb` 与 Windows NSIS 安装包还会在运行器上实际安装，核对安装位置、卸载登记、菜单入口与图标，从安装位置运行原生冒烟后卸载并确认清理；推送 `v*` 标签时，同一工作流在各平台构建通过后发布 Tauri 安装包与 Python 分发包，并附 `SHA256SUMS`。定义存在不代表对应系统已经跑通。

Tauri Linux 包沿用旧 Qt 包的 `ysu-net` 包名与 `0.1.0` 版本，同版本替换需 `apt install --reinstall`；Windows 旧 Qt 版由 Inno Setup 安装、新版由 NSIS 安装，二者不会互相替换，需先卸载旧版。发行前仍需提升版本号并处理既有自启项与签名。

## 文档归属

首页负责两个产品的导航，架构页负责边界，桌面说明负责构建和运行语义，[设计说明](rust-desktop-design.md)负责视觉依据。带日期的验收只对应当时源码与样本；此前 Python 图形版的校内成绩和旧旁车包不作为 Rust 桌面验收证据。
