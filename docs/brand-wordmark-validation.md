# 品牌字标验收

日期：2026-10-17。范围：共用 Svelte 桌面界面的左上角品牌区，不涉及认证、账号、托盘、偏好存储或其他平台代码。当前布局见[设计说明](rust-desktop-design.md)；[侧栏底部验收](sidebar-footer-validation.md)与更早的配色记录保留原貌，不计入本轮成绩。

## 改动

品牌区原来是通用网络图标加 9px 副标，放在与导航同款的方块里，缺少自身识别度。现改为字标组合：品牌色圆角块内是以笔画绘制的 Y，呼应 YSU；右侧 `YSU Net` 用 780/500 两档字重形成主次，下方 `燕山大学校园网` 提到 11px。

Y 是内联 SVG 路径，不引入图标库、位图或字体文件，随强调色平涂；`aria-hidden` 交给相邻文字承担名称，不重复朗读。副标由 9px 提到 11px 后仍保持次要层级，对比度 5.19:1。

## 范围与复现

产品修改只在[应用组件](../desktop/src/App.svelte)与[公共样式](../desktop/src/app.css)。[范围核对](../dist/brand-wordmark-validation/scope-check.json)逐字比较品牌区以外的 `App.svelte` 与样式表，另外核对 25 个文件保持本轮初始哈希；[差异](../dist/brand-wordmark-validation/changes.diff)与[修改前源码](../dist/brand-wordmark-validation/source-before/)保留基线。

复现命令：`.venv/bin/python desktop/tests/brand_wordmark_preview.py --url http://127.0.0.1:1423/ --output dist/brand-wordmark-validation/after`，预览由项目既有 `with_server.py` 托管 `vite preview desktop`，退出时关闭服务器。

## 结果

`npm --prefix desktop run check` 零错误零警告；`run test` 82/82，`run test:build` 5/5，`run build` 成功，见[构建日志](../dist/brand-wordmark-validation/frontend-build.log)。

- 字标专项 166/166，见[报告](../dist/brand-wordmark-validation/after/brand-wordmark-report.json)。覆盖浅深主题与 1000、881、880、700、521、520、390、320px 宽度：标记为正方形、白 Y 对品牌底 ≥3:1、副标 ≥4.5:1、主标不小于副标且字重差 ≥200；宽屏文字在侧栏内不溢出，880–521px 隐藏文字并把标记居中，520px 及以下恢复横排；品牌块不与导航重叠。六种主题色下标记都跟随 `--brand-fill`。
- 侧栏底部 118/118，见[底栏报告](../dist/brand-wordmark-validation/footer/sidebar-footer-report.json)。
- 逐页回归 32/32，见[逐页报告](../dist/brand-wordmark-validation/review/review-report.json)。
- 任务网格与页面矩阵（10 个布局、18 对对比、74 个布局、12 对文字对比）通过，见[网格报告](../dist/brand-wordmark-validation/layout/flclash-report.json)与[页面报告](../dist/brand-wordmark-validation/pages/clean-desktop-report.json)。
- 主题选择 186/186，见[主题报告](../dist/brand-wordmark-validation/accents/accent-ui-report.json)。
- 浏览器 smoke 全部标志通过，无页面错误、控制台错误、外部请求或网页存储，见[报告](../dist/brand-wordmark-validation/web/browser-report.json)。

完整日志见[浏览器回归](../dist/brand-wordmark-validation/browser-validation.log)。

## 直接看图

- [浅色常规窗口](../dist/brand-wordmark-validation/after/light-1000-720.png)与[深色](../dist/brand-wordmark-validation/after/dark-1000-720.png)。
- [3 倍放大字标](../dist/brand-wordmark-validation/zoom-light-1000.png)，可见笔画与色块关系。
- [窄侧栏 700px](../dist/brand-wordmark-validation/after/light-700-560.png)与[手机宽度 320px](../dist/brand-wordmark-validation/after/light-320-760.png)。

## 原生与边界

Linux release 构建成功（`YSU_SDK_NETWORK=none`、`CARGO_NET_OFFLINE=true`），见[构建日志](../dist/brand-wordmark-validation/native-build.log)；随后在无网络 SDK 的 `dbus-run-session` / `xvfb-run` 环境下执行 `packaging/tauri_smoke.py --capture-desktop`，退出码 0。[原生验收](../dist/brand-wordmark-validation/native/acceptance.json)确认 IPC、账号、偏好保存与恢复、关闭驻留、窗口重建、托盘后台操作与宿主丢失恢复通过，`processes_cleaned` 与 `no_auth_sidecar` 均为 true，见[原生自检日志](../dist/brand-wordmark-validation/native-validation.log)。原生构建产出与浏览器验收的 6 个前端文件哈希一致，记录在[一致性核对](../dist/brand-wordmark-validation/native-assets-check.json)。

完整视觉矩阵来自 Chrome；Linux 原生自检只覆盖生命周期与渲染存在性，不代表真实桌面面板、系统辅助功能或每档宽度已逐一看图。Windows/macOS 原生窗口与系统字体未测，浏览器截图不替代对应平台实机验收。无真实校园认证、安装、发布、提交或推送；CLI/Python/Qt 与 Rust 业务源码未改。
