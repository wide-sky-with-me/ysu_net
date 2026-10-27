# 精确门户来源变体与无地址导航诊断

日期：2026-10-27<br>
状态：已写开发源码，待云端格式化与新完整候选回归；未新发行、未部署、未确认 Win11 现场<br>
范围：共享 Rust 导航策略及固定分类诊断，不改变认证凭据用途、TLS 信任或 CLI 导航政策

## 新证据与旧决定

[111 只读记录](../../../../docs/portal-navigation-review-2026-10-27.md)保留三份安全收据的结论：普通无 query 来源已符合旧 API 窄规范化；真实 `mode=history` 完整来源与同门户旧 HTTP 目标的组合此前不匹配。此次有实际组合证据，不再只凭外部工具默认入口推断。index 完整样本未选到静态候选，不支持改 parser 或盲加 failover。

本决定局部增补[既有导航 / 诊断约束](2026-10-22-diagnostics-and-update-lifecycle.md)，不回写旧决策或[已交付认证链审查](../../../../docs/auth-flow-review-2026-10-27.md)；旧记录当时没有该组合证据是历史事实，不以新证据改成当时已经支持。

## 选择与取舍

- 来源只允许配置 endpoint 派生的两个完整 Url 值：原无 query 入口及其唯一精确 `mode=history` 变体。不先剥除 query，不通配额外 / 重复 / 编码参数、域名或路径，避免把未知来源借历史参数名变成可信引导。
- 保留原无 body GET、HTTPS base 默认端口、同 host 的默认 HTTP 端口、固定目标路径和唯一有效 SID 等限制；先转换 HTTPS，再执行原 allowed 检查，绝不因此发明文 HTTP，也不清改目标 query。API HTTP Location 与 HTML resolver 共用一个 checked 入口，避免两处 guard 继续漂移。
- Browser 仅在明确 bootstrap 阶段、主 CDP session / 主 frame Document、实际 GET 无 body 的 HTTP Location 上使用同策略，且真正替换响应 Header 为 HTTPS 目标。CAS、iframe、子资源、其他方法不共享例外；没有证据证明 Browser HTML / JS 来源，故不补它们。
- 导航失败只附可选的闭集 enum / bool 分类；严格 origin 的 `role` 与精确 host 的 `host_role` 分开，避免同门户 HTTP 和外站 HTTP 都归 other 后丢失线索，但两者均不授权。不附原 URL、host、path、query 值、Cookie、票据、账号或密码；无 metadata 时旧 JSON / 日志保持原样，原 code / reason / stage / operation 不变，分类不足以证明具体目标或认证根因。

不照抄 Shell / Requests 的宽松跳转：任意 HTTP、去 query 后比较、跨域或 substring 判可信会扩大信任边界。也不通过盲重试、改变入口列表或新增 direct SSO / 凭据分支掩盖导航失败；本次证据在门户 bootstrap，不证明后续 CAS / 加密代际需要改变。

代价是仍拒绝尚无证据的其他来源变体，需要后续脱敏分类和明确授权的新样本；不能许诺“所有门户跳转都兼容”。新日志刻意放弃原地址定位精度，以避免公开诊断变成会话或凭据通道。

## 实现与归属

现行完整限制只在[运行说明](../../../../docs/tauri-desktop.md#门户导航与诊断开发源码)维护。[共享导航检查](../../../../desktop/crates/ysu-auth/src/transport.rs)、[API HTML resolver](../../../../desktop/crates/ysu-auth/src/protocol.rs)、[Browser 响应分派](../../../../desktop/crates/ysu-auth/src/browser.rs)与[错误诊断](../../../../desktop/crates/ysu-auth/src/diagnostic.rs)是对应实现入口。

[导航诊断类型](../../../../desktop/crates/ysu-auth/src/navigation_diagnostic.rs)与[Native 固定格式](../../../../desktop/src-tauri/src/runtime.rs)负责无原始材料输出；政策与诊断分开，不为新增观测字段放宽导航，也不把 metadata 塞进账户 Info。

已补[共享合成夹具](../../../../tests/fixtures/portal-entry-variants.json)、[Rust 策略矩阵](../../../../desktop/crates/ysu-auth/src/regression_tests.rs)、[CDP Header 序列化纯反例](../../../../desktop/crates/ysu-auth/src/browser.rs)、[Python SID 提取回归](../../../../tests/test_portal_entry_variants.py)及[导航隐私 / None 兼容反例](../../../../desktop/crates/ysu-auth/src/navigation_diagnostic_tests.rs)，Native formatter 反例仍在上述运行器文件中；新增测试尚未运行，不能表述为真实浏览器或产品已通过。

## 验证边界

安全采样使用独立 Requests 观察器，不是 Rust / CLI 产品；111 当时已在线，没有网页下线、离线复现、凭据投递或同机 A/B。Python HTMLParser 不是 Rust scraper，同 regex 顺序和完整 631 字节样本也不证明解析器全等。

既有产品 `1a81` 的云端通过只属于旧候选；本次新导航候选尚待云端格式化、编译及完整产品回归。所有产品 / 单元 / 浏览器验证只走 GitHub Actions，本机仅静态文档核对；本轮无新发行、安装部署或 Win11 现场恢复成绩。
