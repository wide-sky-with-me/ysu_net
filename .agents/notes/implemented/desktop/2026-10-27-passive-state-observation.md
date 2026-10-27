# 独立只读状态观察与身份缓存

日期：2026-10-27<br>
状态：已写开发源码，待云端格式化与全回归；未新发行、未现场确认<br>
范围：Windows / Linux / macOS 共用 Rust Worker 与桌面事件提示，不改变 CLI 后台或认证授权

## 背景

网页门户或其他设备可改变当前会话，而桌面没有操作时旧状态和账户详情仍可能留在界面。用户批准独立只读观察，但没有因此授权登录、下线、换号、启用自动重连或发布新版本；正式 0.2.2 安装包不含本轮改进。

另有 Win11 API 模式在网页下线后报告 `redirect_blocked`。静态分析发现，已有受限 HTTPS 规范化只接入了 header 导航，API bootstrap 的 HTML / meta / JS 解析没有复用它；已补源码，不等于确认远端真实 URL 或现场根因。

## 选择与取舍

- 观察在原生 Worker 串行运行，与 auto 开关和自动认证退避独立；不用前端轮询作为唯一时钟，避免关闭 WebView / 托盘驻留后丢失观察，也不复用 auto 的变更授权。代价是关闭自动重连仍会发生有界只读网络查询。
- 焦点、可见性和网络事件只提示尽早查询，不从 `navigator`、网络事件或 IPC ACK 产生在线结论；结果只通过正常单调快照发布。前端合并突发提示，原生成功短冷却、失败后台退避并限制前台提示速率，避免失败风暴；不以一次提示清除失败计数或重排认证 / 轮换。
- 使用缓存 Config 的临时 API 副本，不读取配置磁盘、不保存临时 backend，不启 Chromium、不拉私有 Info。按保存的 browser backend 被动查询会启动浏览器且无法满足短预算，故不采用；手动 / auto 仍保留用户选择。API 无法确认就未知，不自动转认证或建议切 browser 规避。
- 不每轮读取账户详情：仅按实际 user / service / IP 绑定缓存；身份变化时旧详情及旧身份错误作废，未知清详情但保留最近身份，同身份读取错误可继续有效，确认离线清旧详情及错误。不修改保存账号；新账户详情需显式查询，不能用旧额度冒充新身份。
- 手动任务优先，观察不占手动队列容量，并复用已有状态采样。门闩拒绝后保留提示、推迟观察期限，避免过期计时器忙等；观察与认证仍不能并发。安装准入遇在途短读会拒绝，读完再试，不强行打断；空闲更新阻止新观察。退出 / force-stop 取消在途 future、RAII 释放门闩，不迟发结果。
- 不为每次被动读设 busy、成功浮层或成功日志；失败使用固定脱敏分类和限频日志。代价是用户主要通过状态变化感知观察，不能以没有提示解释为网络已确认。具体周期、预算与退避数值仅在[运行语义](../../../../docs/tauri-desktop.md#独立只读状态观察开发源码)维护。

## API 导航边界

API HTML resolver 复用原有窄规范化，不增加 HTTP 许可：只处理实际响应终点为精确入口的无 body GET、同 host / 默认端口、固定目标路径及受限 sessionId，在可信检查前规范为 HTTPS；其他 TLS、POST、API、CAS 和跳转边界不变。

这补的是合成导航兼容路径，不是对未知远端 URL 的放行，也未修复 Browser 分支另有的缺口。不能据此宣称 Win11 现场已恢复，不能要求用户公开会话 URL 或原始认证材料。

## 实现与待验证

[原生观察器](../../../../desktop/src-tauri/src/runtime_observer.rs)、[串行运行器](../../../../desktop/src-tauri/src/runtime.rs)、[事件桥](../../../../desktop/src/lib/observation.ts)与[页面接入](../../../../desktop/src/App.svelte)；[API resolver](../../../../desktop/crates/ysu-auth/src/protocol.rs)和[原可信导航边界](../../../../desktop/crates/ysu-auth/src/transport.rs)。

已写[原生反例](../../../../desktop/src-tauri/src/runtime_observer_tests.rs)、[TS 合并 / 清理反例](../../../../desktop/src/lib/observation.test.ts)、[预览回归](../../../../desktop/tests/state_observer_preview.py)与[API 导航反例](../../../../desktop/crates/ysu-auth/src/regression_tests.rs)，但尚未运行；全部产品测试、格式化与构建只走 GitHub Actions。纯 Demo / Web 不发送原生观察，原生 Demo 只读内存；合成事件、内存状态与回环夹具都不证明真实校园网或系统网络变化已验收。

本次只做源码与文档静态核对，不连接校园网、不改本机配置或凭据、不运行本机产品。现行运行说明归[桌面运行语义](../../../../docs/tauri-desktop.md#独立只读状态观察开发源码)，历史诊断与更新门闩理由继续见[既有决策](2026-10-22-diagnostics-and-update-lifecycle.md)，不改其历史结论。
