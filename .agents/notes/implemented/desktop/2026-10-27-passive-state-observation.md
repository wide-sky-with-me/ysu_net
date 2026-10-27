# 独立只读状态观察与身份缓存

日期：2026-10-27<br>
状态：首轮观察 / 导航源码已通过 CI；追加来源绑定的新完整候选待回归；未新发行、未现场确认<br>
范围：Windows / Linux / macOS 共用 Rust Worker 与桌面事件提示，不改变 CLI 后台或认证授权

## 背景

网页门户或其他设备可改变当前会话，而桌面没有操作时旧状态和账户详情仍可能留在界面。用户批准独立只读观察，但没有因此授权登录、下线、换号、启用自动重连或发布新版本；正式 0.2.2 安装包不含本轮改进。

另有 Win11 API 模式在网页下线后报告 `redirect_blocked`。静态分析发现，已有受限 HTTPS 规范化只接入了 header 导航，API bootstrap 的 HTML / meta / JS 解析没有复用它；已补源码，不等于确认远端真实 URL 或现场根因。

## 选择与取舍

- 观察在原生 Worker 串行运行，与 auto 开关和自动认证退避独立；不用前端轮询作为唯一时钟，避免关闭 WebView / 托盘驻留后丢失观察，也不复用 auto 的变更授权。代价是关闭自动重连仍会发生有界只读网络查询。
- 焦点、可见性和网络事件只提示尽早查询，不从 `navigator`、网络事件或 IPC ACK 产生在线结论；结果只通过正常单调快照发布。前端合并突发提示，原生成功短冷却、失败后台退避并限制前台提示速率，避免失败风暴；不以一次提示清除失败计数或重排认证 / 轮换。
- 使用缓存 Config 的临时 API 副本，不读取配置磁盘、不保存临时 backend，不启 Chromium、不拉私有 Info。按保存的 browser backend 被动查询会启动浏览器且无法满足短预算，故不采用；手动 / auto 仍保留用户选择。API 无法确认就未知，不自动转认证或建议切 browser 规避。
- 不每轮读取账户详情：按实际 user / service / IP 作废旧缓存与旧身份错误，未知保留最近身份，确认离线清详情及错误。不修改保存账号；新详情需显式查询，并按下节将返回值绑定到其实际观测来源，不能只依赖之后被动观察碰巧清理。
- 手动任务优先，观察不占手动队列容量，并复用已有状态采样。门闩拒绝后保留提示、推迟观察期限，避免过期计时器忙等；观察与认证仍不能并发。安装准入遇在途短读会拒绝，读完再试，不强行打断；空闲更新阻止新观察。退出 / force-stop 取消在途 future、RAII 释放门闩，不迟发结果。
- 不为每次被动读设 busy、成功浮层或成功日志；失败使用固定脱敏分类和限频日志。代价是用户主要通过状态变化感知观察，不能以没有提示解释为网络已确认。具体周期、预算与退避数值仅在[运行语义](../../../../docs/tauri-desktop.md#独立只读状态观察开发源码)维护。

## 账户来源绑定与残余竞态

首轮 `68f553a4` 通过后，独立审查发现 Info(A) → 独立 Status(B) 仍可能晚写回 A 的详情；之后同 B 的被动状态不再触发身份变化，故仅按全局状态作废缓存不足。本机串行不能禁止远端网页或设备换会话，不能用保存账号限制当前外部账号，也不从中文 `fields` 猜身份。

选择 `InfoObservation { status, info }` 携带实际来源：同 session 的 snapshot → 账户只读 → 再 snapshot 必须身份一致，Native 仍独立 Status，并以 `matches_status` 比较 online / user / service / IP 后才提交成功详情；空字段照实比较，不猜补或增加非空门槛。原 `info()` 仍只返回原 JSON，来源不进 IPC 展示；无凭据读取外部当前账号的能力与严格轮换接口不变。

代价是在线 Info 多一次只读状态查询，仍共享原 lock / deadline 和 Native 总预算，不额外登录、下线、保存或叠加整轮时限；确认离线继续短路且不读账户。独立离线 / 未知及已有 Info 错误优先语义保留；实际 tuple 变化才报 `IdentityMismatch`，后查失败以固定 code 2 / Verification 文案保留原网络 / 响应 / 超时 Reason，不冒充换号。采样不是远端原子事务，缺字段可能掩盖真实变化，也不能保证识别采样间 A→B→A 的 ABA 变化。

## API 导航边界

API HTML resolver 复用原有窄规范化，不增加 HTTP 许可：只处理实际响应终点为精确入口的无 body GET、同 host / 默认端口、固定目标路径及受限 sessionId，在可信检查前规范为 HTTPS；其他 TLS、POST、API、CAS 和跳转边界不变。

这补的是合成导航兼容路径，不是对未知远端 URL 的放行，也未修复 Browser 分支另有的缺口。不能据此宣称 Win11 现场已恢复，不能要求用户公开会话 URL 或原始认证材料。

## 实现与待验证

[原生观察器](../../../../desktop/src-tauri/src/runtime_observer.rs)、[串行运行器与提交配对](../../../../desktop/src-tauri/src/runtime.rs)、[来源类型](../../../../desktop/crates/ysu-auth/src/info_observation.rs)、[AuthClient 读取](../../../../desktop/crates/ysu-auth/src/lib.rs)、[事件桥](../../../../desktop/src/lib/observation.ts)与[页面接入](../../../../desktop/src/App.svelte)；[API resolver](../../../../desktop/crates/ysu-auth/src/protocol.rs)和[原可信导航边界](../../../../desktop/crates/ysu-auth/src/transport.rs)。

首轮源码 `68f553a4` 已通过四平台 Native、Mock 与 Community，含当时的原生观察、[TS 合并 / 清理](../../../../desktop/src/lib/observation.test.ts)、[预览回归](../../../../desktop/tests/state_observer_preview.py)与[API 导航反例](../../../../desktop/crates/ysu-auth/src/regression_tests.rs)范围。追加来源绑定的[库级组合测试](../../../../desktop/crates/ysu-auth/src/info_observation_tests.rs)、[同 session 整链反例](../../../../desktop/crates/ysu-auth/src/info_observation_integration_tests.rs)与[Native 晚写回反例](../../../../desktop/src-tauri/src/runtime_observer_tests.rs)已补源码，新完整候选仍待云端格式化 / 全回归，不把首轮全绿当作新竞态已覆盖。全部产品测试与构建只走 GitHub Actions；Demo / Web、合成事件及回环夹具都不证明真实校园网或系统网络变化已验收。

本次只做源码与文档静态核对，不连接校园网、不改本机配置或凭据、不运行本机产品。现行运行说明归[桌面运行语义](../../../../docs/tauri-desktop.md#独立只读状态观察开发源码)，历史诊断与更新门闩理由继续见[既有决策](2026-10-22-diagnostics-and-update-lifecycle.md)，不改其历史结论。
