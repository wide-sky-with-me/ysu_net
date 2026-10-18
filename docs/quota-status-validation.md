# 流量状态标签验收

日期：2026-10-16。范围：连接页删除左侧自动重连的常规说明，将右侧剩余流量等信息从自动换号卡片中独立为状态标签。保持现有 FlClash 风格、认证与轮换行为；不安装、提交、推送或发布。

## 实现

- 自动重连保留标题和开关，隐藏已知的日常监测、开关与成功消息；异常、认证暂停和未识别的新消息继续显示，含必要的重试等待。外部服务提示仍由主连接卡展示。
- 独立标签放在自动化区底部；宽窗口占右栏，紧凑窗口横跨两个开关。保留门户文字与单位、额度未知、不限量及零值舍入复核提示，使用有名称的 `role="status"`。
- 仅收紧紧凑视图的分区间距，为标签留出空间；700×560 的外部服务、空账号和忙碌场景仍完整显示关键操作。

当前显示规则由[展示函数](../desktop/src/lib/presentation.ts)与[单测](../desktop/src/lib/presentation.test.ts)约束；账号操作、认证核心和协议未改。未使用泛化关键词过滤异常消息。

## 本轮验证

| 检查 | 结果 |
| --- | --- |
| Svelte / TypeScript 检查 | 0 错误、0 警告 |
| 前端单测 / 构建入口测试 | 54/54（含新增展示测试 12 项）、5/5 |
| 生产前端构建 | 通过 |
| 新增标签回归 | 修改前 76/110，34 项失败；修改后 110/110 |
| 网格 / 可访问性回归 | 10 布局、18 对比检查、5 紧凑状态通过；Tab 顺序与可访问性媒体检查通过 |
| 账号细节回归 | 31/31 |
| 多账号交互 | 9 组、10 布局通过 |
| 逐页评审 | 27/27 |
| 网页模拟冒烟 | 通过，无页面错误、外部请求或网页存储 |
| Linux 离线原生构建 / 冒烟 | 通过；渲染、账号热切换、重连/轮换、后台托盘、窗口重建及退出清理通过 |

新增[标签回归](../desktop/tests/quota_status_preview.py)覆盖浅深主题、1000/700/390/320px，以及四种额度状态、原始 GiB 单位、零值复核和异常重试提示。基线模式仅完整记录失败，`ok:false` 保留，未当作通过。因用户要求迁移文案，将既有对比度与全宽文字检查移至实际标签，保留阈值，并要求唯一标签实际存在，避免空集合误通过；账号行为断言未放宽。

截图：[最终紧凑效果](../dist/quota-status-validation/connection-final.png)、[宽窗口](../dist/quota-status-validation/grid/connection-light-1000.png)、[深色](../dist/quota-status-validation/after/connection-dark-1000.png)、[零值](../dist/quota-status-validation/after/zero_reported-light-700.png)、[异常重试](../dist/quota-status-validation/after/reconnect-warning-light-700.png)。本轮[构建日志](../dist/quota-status-validation/frontend-build.log)和[浏览器日志](../dist/quota-status-validation/browser-regression.log)独立保存；浏览器为 Chrome 154.0.8037.97，数据来自离线模拟与隔离的原生协议桩。

## 原生与证据边界

SDK 内离线 `--no-bundle` 构建通过，编译耗时 1m34s；[二进制元数据](../dist/quota-status-validation/binary.json)记录 SHA256。[Linux 原生报告](../dist/quota-status-validation/native/acceptance.json)确认渲染、核心 IPC、连接/切换、账号管理、轮换、窗口销毁与重建、关闭后的托盘操作和退出清理通过，没有认证旁车。原生构建严格位于浏览器回归之后，按[前端哈希](../dist/quota-status-validation/web-tested-sha256.json)比对确认同一前端。

已看图核对[原生菜单与窗口](../dist/quota-status-validation/native/native-tray-menu.png)；菜单有遮挡，不作为标签完整文案的视觉证明。[首次可见阶段截图](../dist/quota-status-validation/native/native-visible.png)为黑屏，保留但排除为视觉成功证据。原生测试使用受控 D-Bus/Xvfb、默认 1000×720 窗口；紧凑布局和标签文案通过浏览器核对。Linux `tooltip_supported:false`，未声称完成真实系统悬停测试。

[展示层核对](../dist/quota-status-validation/presentation-check.json)确认 App 脚本仅增加展示函数导入与派生消息，原操作脚本、账号组件和额度模板正文保持一致；前一轮清单中 16 个归档证据文件保持原哈希。

同一套共用前端适用于三平台；Windows/macOS 原生、真实系统面板/悬停、真实校园网认证、完整 Rust/Python 回归及长稳测试未执行。本次未改额度解析、单位、自动换号判据或 CLI。前一轮[细节验收](desktop-detail-validation.md)及其归档保留原貌，不刷新历史哈希。

## 复跑

先构建前端并运行自己的本地 Vite preview，再运行 `.venv/bin/python desktop/tests/quota_status_preview.py --output dist/quota-status-replay`。运行后停止自有预览进程；使用技能助手时以 `--server 'exec node desktop/node_modules/vite/bin/vite.js preview desktop --host 127.0.0.1 --strictPort --port 1423'` 启动，确保终止到实际服务进程。原生构建和自检沿用[桌面开发文档](tauri-desktop.md)，输出到新的目录，不覆盖本轮或历史证据。
