## YSU Net v0.2.0

本版将桌面由 Qt 迁移到 Tauri，并保留独立 Python CLI。发布门槛为 Linux x64、Windows x64、macOS arm64 / x64 四个平台的构建、原生与安装验收全部成功；实际 CI 结果以对应运行为准。旧 `v0.1.0` 标签与 Qt 附件保留，不覆盖。

桌面客户端迁移为 Tauri 2 + Svelte + Rust，三平台共用界面与认证后台，不再依赖 Python、Node 或 Playwright 认证运行时。独立 Linux Python CLI 保留，版本同为 **0.2.0**；原 Qt 客户端（`ysu-gui`）停止维护。

### 主要变化

- 认证、自动重连、运营商切换与多账号热切换由 Rust 原生后台执行；登录、切换以独立查询确认，未知状态不自动登录。
- 可选零流量自动换号：仅门户连续报告零剩余流量时才尝试备用账号，缺失余量不猜测。CLI 同步提供多账号管理和热切换入口。
- 修复 Rust 只读查询中的旧门户 HTTP 导航：仅精确可信入口的同主机、受限路径 GET 引导规范到 HTTPS，不放宽通用 API / CAS / POST / TLS 边界。
- 账户页区分未知、确认离线、未读取和读取失败；失败显示公共错误与只读重试，成功清错，不伪造在线或离线。门户缺项继续显示“门户未提供”。
- 原生托盘、用户登录自启与共享浅色 / 深色界面；可选浏览器认证通过私有管道驱动本机 Edge / Chrome，不开放认证调试端口。

### 安装与升级

| 系统 | 附件与迁移 |
| --- | --- |
| Windows 10 / 11 x64 | NSIS 当前用户安装，无需管理员；先关闭旧 Qt 版自启并卸载旧 Inno Setup 版，两种安装器不会互相替换。使用系统 WebView2。 |
| Ubuntu 22.04 及更新，x86_64 | `.deb`，包名仍为 `ysu-net`；0.2.0 高于旧 0.1.0，使用 `apt install` 正常升级，无需 `--reinstall`。 |
| macOS 13.5 及更新 | arm64（Apple 芯片）和 x64（Intel）分别提供 `.dmg`，退出旧程序后拖入“应用程序”替换。 |
| Python / Linux 命令行 | 0.2.0 wheel、源码包，或按 README 从源码安装；不作为桌面运行时。 |

Windows / macOS 安装包未签名，系统可能提示未知发布者或要求在“系统设置 → 隐私与安全性”中确认。发布后按附件 `SHA256SUMS` 核对摘要。不要从旧 `v0.1.0` Qt 附件安装新版；完整说明见[迁移文档](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md#桌面-v020-升级)。

### 验证范围

发布流程要求四个平台通过前端 / Rust 测试、真实 Chrome 认证夹具、原生窗口冒烟与实际安装、启动、卸载验收；这是一条发布门槛，不是本轮 CI 的通过声明，也不等于校园网全场景已测。

[2026-10-21 Windows 本机只读验收](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/windows-readonly-fix-2026-10-21.md)已确认中国联通在线并成功读取账户；门户没有给出剩余流量和余额，页面没有补造零值或不限量。该记录对应当时 0.1.0 开发快照，验证查询修复，不冒充 v0.2.0 安装或四平台 CI 结果。

本次真实机器未执行登录、下线、切换账号 / 服务、自动重连或账号池轮换；浏览器认证、物理断网恢复、其他运营商及长稳运行不据此声称通过。历史 CLI 和桌面验收仅代表其记录的版本与环境。

### 反馈

用法问答见 [Discussions](https://github.com/wide-sky-with-me/ysu_net/discussions)，可复现故障见 [Issues](https://github.com/wide-sky-with-me/ysu_net/issues/new/choose)。公开前移除账号、密码、会话、设备地址和本机路径。
