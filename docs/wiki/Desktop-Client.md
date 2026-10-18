# 桌面客户端（Windows / Linux / macOS）

[返回导航](Home.md) · [排障](Troubleshooting.md) · [隐私与反馈](Privacy-and-Reporting.md)

## 版本

桌面客户端基于 Tauri 2 + Rust，Windows、Linux、macOS 共用同一套界面与认证实现，不依赖 Python、Node 或 Playwright。新版发布前请按 [Tauri 桌面说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提) 从源码构建。

原 Qt 客户端（`v0.1.0` 附件、`ysu-gui`）已停止维护，源码已移除。Windows 上请先卸载旧 Qt 版再安装新版；Ubuntu 新包与旧包同名，用 `sudo apt install --reinstall ./<新包>.deb` 替换。

## 第一次连接

在“设置 → 校园网账号”中保存账号密码，默认使用 API 认证。回到“连接”页点击连接，分别观察界面状态和实际网络连通性。需要自动重连时再打开开关；重连、断开、运营商切换和账号切换都会影响当前连接。流量与余额按门户原文展示，缺失字段不是零。

同一配置一次只由一个重连进程管理。Linux 的命令行后台服务已运行时，先停止守护，再交给桌面客户端；不要同时启动两套自动重连。

## 已知验证边界

CI 中的构建、启动与截图不等于所有校园网认证场景已验证。校内认证、浏览器认证、其他运营商和长稳运行应按真实反馈逐项确认；反馈时写明已测与未测范围。
