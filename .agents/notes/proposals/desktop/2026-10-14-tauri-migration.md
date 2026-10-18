# Tauri 桌面迁移

- 日期：2026-10-14
- 状态：迁移实现及 Linux 离线验收完成；Windows/macOS、真实校园网与正式发布待验收。
- 范围：桌面入口、界面、进程生命周期和构建；保留 CLI、systemd 与现有认证协议。

后续决策：[全 Rust 桌面](2026-10-14-rust-desktop.md)替代本文的 Python 旁车选择；窗口、托盘、状态语义和保留回退的原则继续有效。以下保留当时选择与验收，不作为当前 Rust 包的结论。

## 背景与选择

用户在比较 Qt Widgets、Qt Quick/QML、Tauri 和 Slint 后明确选用 Tauri。目标是现代、轻量的统一桌面体验，同时减少 Windows、Linux、macOS 的长期差异成本。此前保留 Qt Widgets 的评估建议不再作为本次界面路线。

采用 Tauri 2、Svelte 静态前端和 Rust 桌面壳。Rust 管理单实例、托盘、自启和窗口；现有 Python 认证核心通过不含 Qt 的独立旁车复用。凭据仍只由原配置模块保存，不进入日志、快照或前端持久化存储。

认证、独立状态验证、运营商切换失败恢复和自动重连继续使用唯一实现，不在 Svelte 或 Rust 中复制。协议用有界 JSON 行、请求关联编号和递增快照序号；窗口可以销毁重建，状态及重连不依赖 WebView 存活。退出时清理旁车、下载线程和认证进程。

## 已考虑的替代方案

- Qt Widgets 精修：迁移最少，但用户已选用 Tauri。
- Qt Quick/QML + PySide6：可复用 Qt 和认证核心，支持现代界面；保留 Python/Qt 基础开销，需要改变界面及打包。
- Tauri + 全 Rust 认证：移除 Python，但同时重写已验证协议与重连会扩大首次迁移的回归面，暂缓。
- Slint + Rust：无 WebView，具有轻量潜力；需要较大迁移和桌面集成验收，未选用。

## 后果与限制

过渡期同时维护 Rust、Svelte、Python 构建，但只有一套认证逻辑。WebView2、WKWebView、WebKitGTK 的系统依赖和渲染差异仍需验证。小安装包不代表低内存；完整进程树和认证峰值需要发布版实测。

原 Qt 入口暂保留作为回滚和回归对照。未覆盖的新平台不能仅因 CI 定义或框架支持就宣称可用；正式发布、提交和推送需另行执行。

## 验证与实现导航

当前实现说明为 `docs/tauri-desktop.md`，本次构建、内存与离线结果为 `docs/tauri-validation.md`。既有真实校园网记录仅代表当时版本，不用作本次验收证据。

- 新界面：`desktop/src/`
- Rust 桌面壳：`desktop/src-tauri/`
- 无 Qt 核心：`src/ysu_net/desktop/`
- 共享引擎：`src/ysu_net/gui/engine.py`
- 共享认证执行器：`src/ysu_net/manager/backend.py`
- 协议回归：`tests/test_desktop_core.py`
