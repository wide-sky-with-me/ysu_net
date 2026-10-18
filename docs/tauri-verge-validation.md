# Clash 风格预览历史复核（2026-10-14）

以下保留此前仅调整前端时的参考与验证记录。它对应 Python 旁车迁移阶段，不代表后续 Rust 认证版、安装包或新设置界面的成绩。当前说明见 [Tauri 桌面](tauri-desktop.md)，当前视觉记录见 [Rust 桌面设计](rust-desktop-design.md)。

## 界面参考与浏览器复核

2026-10-14 核对 [Clash Verge Rev 官方网站](https://www.clashverge.dev/)及其[官方仓库](https://github.com/clash-verge-rev/clash-verge-rev)。实际阅读仓库当前展示的[浅色预览](https://raw.githubusercontent.com/clash-verge-rev/clash-verge-rev/dev/docs/preview_light.png)、[深色预览](https://raw.githubusercontent.com/clash-verge-rev/clash-verge-rev/dev/docs/preview_dark.png)，以及当前 `dev` 分支的[基础设置](https://github.com/clash-verge-rev/clash-verge-rev/blob/dev/src/components/setting/setting-verge-basic.tsx)和[设置分组/行](https://github.com/clash-verge-rev/clash-verge-rev/blob/dev/src/components/setting/mods/setting-comp.tsx)。官网预览是其展示基线，不宣称为最新发行版实机截图。

借鉴窄侧栏、柔和底色、紧凑分组与右侧控件；保留 YSU Net 身份、青色强调和校园网语义，没有引入代理功能、营销内容、依赖或版本变化。改动仅在 [App.svelte](../desktop/src/App.svelte)、[app.css](../desktop/src/app.css)及原说明页；组件可访问名称和既有交互保留。移除页面副标题、连接状态重复说明、外观与间隔选项的显然解释、核心/宿主实现说明和空状态赘述；仅对与已知在线/离线状态一致的例行消息去重，错误和未知状态消息继续显示。凭据本机保存、留空保留密码、保存/离开清空输入、切换断线、外部管理和无托盘关闭即退出等约束保留。

本次实际执行 `npm --prefix desktop run check`（零错误/警告）、`npm --prefix desktop test`（原有 22 项通过）、`npm --prefix desktop run build` 和 `git diff --check`。既有 [浏览器验收脚本](../packaging/tauri_web_smoke.py)使用 `/usr/bin/google-chrome` 访问构建产物的 Vite preview，通过全部行为断言；未调整测试或后端源码。结果为 [原有验收报告](../dist/tauri-preview/verge-smoke/browser-report.json)与[补充复核报告](../dist/tauri-preview/verge-browser-report.json)。补充复核在页面资源加载完毕后切断浏览器网络，验证系统主题响应、Tab 焦点、确认框 Escape 与焦点恢复、凭据清空、证书/退出确认和普通网页无托盘提示。零外部请求、零页面异常、零控制台错误；浅色选中态文字与底色对比度为 4.95:1，输入边框与字段底色为 3.33:1，不据此宣称完整无障碍验收。

新截图为 [连接浅色](../dist/tauri-preview/verge-connection-light.png)、[连接深色](../dist/tauri-preview/verge-connection-dark.png)、[设置浅色](../dist/tauri-preview/verge-settings-light.png)，均为本次构建的 **Chrome 浏览器预览**（1000 × 720）。实际最小窗口 700 × 560 已复核浅深主题全部页面：无横向溢出，连接操作无需滚动；设置内容纵向滚动且底部操作可达。另有[紧凑浅色](../dist/tauri-preview/verge-compact-light.png)、[紧凑深色](../dist/tauri-preview/verge-compact-dark.png)和[紧凑设置](../dist/tauri-preview/verge-compact-settings-light.png)。旧 `refined-*` 截图未替代本次证据。

共享前端供 Linux、Windows、macOS 桌面使用。本次没有重建原生程序或安装包，也未实测 WebKitGTK、WebView2、WKWebView、Windows 或 macOS；此前 Linux 包不包含这次界面变更，其历史验收不代表新前端原生验收。未提交、推送或发布。
