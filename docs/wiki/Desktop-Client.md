# 桌面客户端（Windows / Linux / macOS）

[返回导航](Home.md) · [排障](Troubleshooting.md) · [隐私与反馈](Privacy-and-Reporting.md)

## 版本

自 **v0.2.0** 起，桌面采用 Tauri 2 + Rust，Windows、Linux、macOS 共用界面与认证后台，不依赖 Python、Node 或 Playwright 认证运行时；没有 Python `gui` 安装依赖。独立 Linux Python CLI 同步为 0.2.0。

下载[对应版本 Release](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.0)中与系统、架构对应的附件并核对 `SHA256SUMS`。发布流程要求四平台构建、原生与安装验收全部成功，实际结果以对应 CI 运行为准；尚无附件时按 [Tauri 构建说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提)从源码构建。

| 系统 | 安装与旧版迁移 |
| --- | --- |
| Windows 10 / 11 x64 | 新版 NSIS 按当前用户安装，无需管理员；先关闭旧 Qt 自启、退出并卸载旧 Inno Setup 版，两种安装器不会互相替换。使用系统 WebView2。 |
| Ubuntu 22.04 及更新，x86_64 | 使用 `.deb` 正常升级；包名仍为 `ysu-net`，0.2.0 高于旧 0.1.0，无需 `--reinstall`。 |
| macOS 13.5 及更新 | 分别提供 arm64（Apple 芯片）和 x64（Intel）`.dmg`，退出旧程序后替换“应用程序”中的客户端。 |

Windows / macOS 安装包未签名，首次启动可能有系统提示。原 Qt（`v0.1.0` 附件、`ysu-gui`）停止维护，标签和附件保留历史，不覆盖。完整操作与配置保护见[迁移说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md#桌面-v020-升级)。

## 第一次连接

在“设置 → 校园网账号”中保存账号密码，默认使用 API 认证。回到“连接”页点击连接，分别观察界面状态和实际网络连通性。需要自动重连时再打开开关；重连、断开、运营商切换和账号切换都会影响当前连接。套餐、流量与其他条目按门户原文展示，缺失流量不是零，不补造账户余额。

同一配置一次只由一个重连进程管理。Linux 的命令行后台服务已运行时，先停止守护，再交给桌面客户端；不要同时启动两套自动重连。

## 已知验证边界

[2026-10-21 Windows 本机只读验收](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/windows-readonly-fix-2026-10-21.md)在当时的 0.1.0 开发快照上确认中国联通在线、成功读取账户；门户没有给出剩余流量与余额，页面显示“门户未提供”。它不是 v0.2.0 四平台 CI 成绩。

该轮真实机器未执行登录、下线、切换账号 / 服务、自动重连或轮换；浏览器认证、物理断网恢复、其他运营商和长稳运行仍应分别验收。查询未知不等于已确认离线，账户读取失败可用页面只读重试；信息查询不主动登录或下线。
