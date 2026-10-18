# 配色验收

2026-10-17（Asia/Shanghai）。范围：优化共用桌面前端的浅深配色；不改布局、字体、文本、认证与轮换判据，不修改应用图标，不安装、提交或发布。

## 显示规则

当前色值统一维护于[设计说明](rust-desktop-design.md)与[样式变量](../desktop/src/app.css)。浅色减轻蓝灰底色，使用雾白画布和松石青强调；深色将输入区下沉、卡片实色化。控件边界比装饰分隔线更明确，箭头和阴影跟随主题，选中项悬停保留原色。

流量已提供或不限量的标签使用青色调，代表已有门户数据，不替代额度文案或核心判据；未知保持中性，报告零值继续使用琥珀色及原复核提示。错误使用莓红，连接成功继续使用绿色与文字/图标。字号、圆角、布局、焦点顺序和动作不变。

## 验证

| 检查 | 本轮结果 |
| --- | --- |
| Svelte / TypeScript / 生产构建 | 0 错误、0 警告；构建通过 |
| 新增色板回归 | 62/62；所测正文最低 4.733:1，所测非文本最低 3.093:1 |
| 网格与可访问性 | 10 布局、18 对比、5 紧凑状态；焦点顺序与高对比/减弱效果检查通过 |
| 跨页布局 | 74 布局、12 正文对比检查通过 |
| 流量标签回归 | 110/110；覆盖未知、已提供、报告零值、不限量及异常重试 |
| 网页模拟冒烟 | 通过；无页面错误、外部请求或网页存储 |

新增[色板回归](../desktop/tests/color_palette_preview.py)针对正文/状态文本、输入边界、焦点、开关和品牌图标设置具体对比阈值；另检查实色卡片、标签色调及悬停。修改前 51/62：7 项对比未达本轮阈值，另 4 项为新增外观合同未满足；后者不代表旧业务缺陷。[基线](../dist/color-palette-validation/before/color-palette-report.json)保留 `ok:false`，不作为通过。检查只覆盖列出的颜色对与状态，不声明完成整站可访问性审计，也不把禁用控件当作普通文本衡量。

[修改后报告](../dist/color-palette-validation/after/color-palette-report.json)、[构建日志](../dist/color-palette-validation/frontend-build.log)、[浏览器日志](../dist/color-palette-validation/browser-regression.log)。[范围核对](../dist/color-palette-validation/scope-check.json)确认非配色 CSS 声明及 App 源码不变，前一轮清单的 22 个非本轮文件保持原哈希。既有断言未改、阈值未放宽；纯样式修改未重复执行 JavaScript/Rust/Python 业务单测。

截图：[浅色宽屏](../dist/color-palette-validation/after/connection-light-1000.png)、[深色宽屏](../dist/color-palette-validation/after/connection-dark-1000.png)、[浅色紧凑](../dist/color-palette-validation/after/connection-light-700.png)、[深色紧凑](../dist/color-palette-validation/after/connection-dark-700.png)；修改前同尺寸材料位于[基线目录](../dist/color-palette-validation/before/)。浏览器为 Chrome 154.0.8037.97，使用离线模拟及隔离协议桩，不访问真实校园网。

## 原生与边界

Linux 离线 `--no-bundle` 构建通过，Rust 编译耗时 1m45s；[二进制元数据](../dist/color-palette-validation/binary.json)记录 SHA256。[原生离线冒烟](../dist/color-palette-validation/native/acceptance.json)验证渲染、账号与重连/轮换操作、后台托盘、窗口关闭与重建以及进程清理通过，没有认证旁车。构建位于浏览器验证之后，按[资源哈希](../dist/color-palette-validation/web-tested-sha256.json)确认嵌入同一套前端。原生测试使用 D-Bus/Xvfb 与默认宽屏浅色；深色和紧凑布局由浏览器核对。Linux `tooltip_supported:false`，未据此声称通过真实系统悬停。

已看图核对[原生菜单与窗口](../dist/color-palette-validation/native/native-tray-menu.png)的配色；菜单有遮挡，不用于证明标签完整文案。[首次可见截图](../dist/color-palette-validation/native/native-visible.png)仍为黑屏，保留但排除为视觉成功证据；不把早期捕获时序视为已修复。

Windows/macOS 共用本轮前端，原生实机、真实系统悬停/面板、真实校园网认证与长稳未测。本轮不评价内存收益，不覆盖打包图标和系统原生菜单配色。历史[流量标签验收](quota-status-validation.md)及其证据保持原貌。

复跑：构建前端，启动自己的 `127.0.0.1:1423` 预览后运行 `.venv/bin/python desktop/tests/color_palette_preview.py --output dist/color-palette-replay`；结束后清理自有服务，输出到新目录，不覆盖本轮或历史记录。
