# FlClash 排版验收

日期：2026-10-15，Asia/Shanghai。范围：三平台共用的 Svelte 界面、Linux 原生程序的离线回归；无安装、真实校园认证、提交、推送或发布。

## 来源与取舍

实际查看 [FlClash 固定提交](https://github.com/chen08209/FlClash/tree/03f955382409a4a7ac1f3f92e46d9fcc6d39f106)的官方[浅色预览](../dist/flclash-layout-validation/references/preview.png)、[深色预览](../dist/flclash-layout-validation/references/preview-dark.png)，并读取 `RowCardFrame`、设置项组件与中文说明。取一体导航、无框标题、细边表面与不等宽任务网格，不采用代理、TUN 或速度图表。

连接主卡与自动化侧卡并排，下方账号和运营商各自成卡；紧凑窗口按 DOM 顺序展开。收起大面积彩光，保留 YSU Net 青色和本地字体。账户、设置和日志同步采用同一表面与导航规则。当前取舍由[设计说明](rust-desktop-design.md)维护，本页只记录本次证据。

## 最终网页验证

环境：Linux，真实 Chrome `154.0.8037.97`，生产构建的回环预览，显式离线样例；非开发服务器、非真实认证。

| 检查 | 本次结果 | 证据 |
| --- | --- | --- |
| Svelte / TypeScript | 0 错误、0 警告 | `npm --prefix desktop run check` |
| 前端单元 / 构建入口 | 42 / 5 项通过 | `npm --prefix desktop test`、`npm --prefix desktop run test:build` |
| 生产构建 | 通过，无新增依赖 | [最终构建日志](../dist/flclash-layout-validation/build-final.log) |
| 任务网格 | 10 个浅深布局、5 种紧凑状态、18 组实际表面对比通过，最低 5.05:1 | [报告](../dist/flclash-layout-validation/design-final/flclash-report.json) |
| 逐页评审 | 27/27 通过 | [报告](../dist/flclash-layout-validation/review-final/review-report.json) |
| 布局与色板 | 74 个布局、12 组正文色板对比通过 | [报告](../dist/flclash-layout-validation/layout-final/clean-desktop-report.json) |
| 多账号 | 9 组交互、10 个布局通过 | [报告](../dist/flclash-layout-validation/accounts-final/multi-account-report.json) |
| 既有设计交互 | 8 组交互、19 个布局通过 | [报告](../dist/flclash-layout-validation/interaction-final/frontend-design-report.json) |
| 普通网页及兼容行为 | 通过，未连接原生核心时操作保持禁用 | [报告](../dist/flclash-layout-validation/web-final/browser-report.json) |

新增回归检查宽屏标题对齐、880px 断点两侧、阅读/Tab 顺序、诊断按钮名称、选中悬停、焦点、强制颜色和降低透明度。浏览器报告无页面/控制台异常、无外部请求、无网页存储。上述计数按脚本分别列出，存在交叉覆盖，不相加为独立测试总数。

既有业务和溢出断言保持。旧玻璃脚本的多重彩光、玻璃顶栏及渐变按钮属于已替代的风格合同；其可读性和媒体偏好检查由新脚本接续，不宣称旧风格合同通过，也未修改旧脚本或历史成绩。

## 暴露的问题与复测

初轮逐页检查为 23/27：[原始报告](../dist/flclash-layout-validation/review-first/review-report.json)与截图保持。紧凑侧栏隐藏文字后，诊断图标缺少名称；新增 `aria-label` 与提示，并保留底部状态文字。浏览器认证时保存按钮略超出主区域，收紧提示卡及保存区间距。390px、320px 的删除失败提示贴近视口下沿，增加末端滚动余量。原断言未放宽，最终全部通过。

新增检查还暴露未配置账号状态多出 7px 空白滚动，去掉连接页重复预留的底部空间；[失败截图](../dist/flclash-layout-validation/design/compact-empty-probe.png)与[复测截图](../dist/flclash-layout-validation/design-final/scenario-empty-700.png)分别保留。宽屏截图曾出现标题和卡片边线偏离，统一最大内容宽度并加入对齐断言。自动化区同时移动 DOM，不保留视觉顺序与键盘顺序相反的排布。

## Linux 原生

最终二进制在受控 D-Bus / Xvfb 下通过真实 WebView 自检：渲染、IPC、账号管理与切换、自动重连、轮换、原生托盘菜单属性回读、真实窗口关闭销毁、后台快捷操作、窗口重建与宿主丢失恢复均通过；退出进程树清理完成，无认证旁车。见 [原生报告](../dist/flclash-layout-validation/native-final/acceptance.json)及[菜单截图](../dist/flclash-layout-validation/native-final/native-tray-menu.png)。独立[生命周期报告](../dist/flclash-layout-validation/lifecycle-final/linux-lifecycle.json)确认无宿主最小化回退、单实例、真实 X11 关闭和进程清理通过。Linux tooltip 不支持项如实保留，不据投影字符串声称鼠标悬停已验收。

首轮[启动首帧](../dist/flclash-layout-validation/native-final/native-visible.png)为空白，保持原件，不作为外观通过证据。另用隔离配置的 `--demo`，等待实际绘制后补采[启动状态](../dist/flclash-layout-validation/native-final/native-ready.png)，见[捕获记录](../dist/flclash-layout-validation/native-final/ready-capture.json)和[独立采集器](../dist/flclash-layout-validation/capture_native_ready.py)；该画面仍处于读取核心状态，完整已连接画面见后续菜单截图。补采进程树已清理，未改原生或既有验收脚本。

二进制：[ysu-net](../dist/flclash-layout-validation/bin/ysu-net)，9,241,480 字节，SHA-256 `2aa264238fbf80e290cadeb267ef845821fa8121629fe62c69e200400c8128c7`。原生构建后的全部前端文件与网页验收版本逐文件哈希一致，见[二进制记录](../dist/flclash-layout-validation/binary.json)和[已验收前端清单](../dist/flclash-layout-validation/web-tested-sha256.json)。

App 业务脚本与 13 个原生、账号及既有回归文件的哈希保持，见[核对记录](../dist/flclash-layout-validation/unchanged-business.json)。本轮未修改认证、持久化或托盘业务；未把此前 Rust 单元测试成绩当作本次重跑结果。

## 重放与截图

在项目根目录启动已构建前端的临时 preview，再运行对应脚本；结束后关闭该预览进程。

```sh
npm --prefix desktop run build
npm --prefix desktop run preview -- --host 127.0.0.1 --strictPort --port 1423
.venv/bin/python desktop/tests/flclash_desktop_preview.py --url http://127.0.0.1:1423/ --output dist/flclash-layout-validation/design-final
.venv/bin/python desktop/tests/clean_desktop_preview.py --url http://127.0.0.1:1423/ --output dist/flclash-layout-validation/layout-final
.venv/bin/python desktop/tests/ui_review_preview.py --url http://127.0.0.1:1423/ --output dist/flclash-layout-validation/review-final
.venv/bin/python desktop/tests/multi_account_preview.py --url http://127.0.0.1:1423/ --output dist/flclash-layout-validation/accounts-final
.venv/bin/python desktop/tests/rust_desktop_preview.py --url http://127.0.0.1:1423/ --output dist/flclash-layout-validation/interaction-final
.venv/bin/python packaging/tauri_web_smoke.py --url http://127.0.0.1:1423/ --browser /usr/bin/google-chrome --output dist/flclash-layout-validation/web-final
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs --no-bundle
```

Linux 自检在已有 SDK 内的独立 D-Bus 与 Xvfb 显示运行，传 `LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1`。使用 `build/tauri-venv/bin/python` 运行 `packaging/tauri_smoke.py --binary dist/flclash-layout-validation/bin/ysu-net --output dist/flclash-layout-validation/native-final --capture-desktop`，生命周期脚本使用同一二进制和独立 `lifecycle-final` 目录。

实际生成并看图复核：[浅色连接](../dist/flclash-layout-validation/layout-final/connection-light.png)、[深色连接](../dist/flclash-layout-validation/layout-final/connection-dark.png)、[最小窗口](../dist/flclash-layout-validation/design-final/connection-light-700.png)、[宽屏](../dist/flclash-layout-validation/design-final/connection-light-1280.png)、[账户](../dist/flclash-layout-validation/layout-final/page-账户-light.png)、[设置](../dist/flclash-layout-validation/layout-final/page-设置-light.png)、[日志](../dist/flclash-layout-validation/layout-final/page-日志-light.png)、[认证保存区](../dist/flclash-layout-validation/review-final/authentication-density.png)。截图均为离线样例，不展示真实账号状态。

## 边界

Windows/macOS 仅共享源码，本轮未运行原生窗口、托盘或自启实机验证。Linux 受控 D-Bus/Xvfb 不代表真实桌面面板与悬停行为；未测真实校园认证、签名、公证或安装包发布，未重新执行与样式无关的 Python CLI 及 Rust 全量单元测试。历史验收保持原貌，本轮原始文件和变更差异单独保存在新证据目录。
