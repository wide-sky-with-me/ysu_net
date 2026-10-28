# 离线 captive 引导、验证码范围与服务拒绝

日期：2026-10-27。状态：开发源码已实施，云端验证待执行；未发行、未部署。

范围：三平台共用 Rust API / Browser 导航及动作检查，Python CLI 的表单与动作语义。现行行为唯一维护在[桌面运行语义](../../../../docs/tauri-desktop.md#离线-captive-与-cas-表单)。

## 背景与真实证据

[123 受控采样](../../../../docs/portal-123-review-2026-10-27.md)发现，在线时的同门户主页面旧跳转不能代表离线链。离线后固定 HTTPS redirect 入口转向固定 HTTP captive 根；强行改为同 IP 的 HTTPS 会遇到证书校验失败。history 入口也转向 captive，不能用更换参数绕过。

匿名 captive 页面返回静态 JS 导航提示，指向 HTTPS 门户 index；门户再签发会话，查询确认离线。CAS 页有多个复用 captchaDiv 的登录表单，其他登录方式的容器与密码表单的隐藏容器不能合并判断。服务选择实际返回 code=200、data.authResult=fail / authMessage=认证失败，旧实现仍继续 userOnline。

本决定局部替代[原导航决策](2026-10-27-portal-entry-variants.md)中 bootstrap 一概不发送 HTTP 的限制；其普通旧地址 HTTPS 规范化、精确来源、TLS、凭据与诊断约束继续有效。旧只读在线结论保留原貌。

## 选择与替代方案

- 不修改通用 allowed。专用解析器仅处理实测完整来源与固定无 query 根目标，GET 无 body；匿名客户端没有 Cookie jar，不继承 Origin / Referer / Authorization 等头，不跟随响应重定向，不执行脚本。每个 Transport 及其克隆共享一次机会，响应大小与时限复用原约束。
- 只把页面解析为同门户固定 HTTPS index 的提示，拒绝直接携带 SID、flow SID、ticket、userinfo 或 fragment；HTTPS 门户重新生成会话。HTTP 内容可被网络篡改，因此不能成为认证成功、离线或身份的证据。
- API 与 Browser 共用解析器。Browser 只在原有 bootstrap 主 Document 上调用，并以 HTTPS index 替换 Location，不让 Chromium 运行匿名 HTTP 页面。CAS、iframe、子资源、其他方法均不接入。
- API 验证码以所选密码 form 与独立挑战为范围，保留真实可见挑战和接口 true 的优先级；Browser 已有实际可见性判断，继续使用。Python 修复完整属性解析并保持同等范围。
- 两端识别 authResult / authMessage 的真实业务信封，存在的 authResult 仅接受 success；拒绝或未知值均阻止下一步。服务被拒时立即停止，不能靠最终轮询掩盖之前多发的上线请求。

放弃的方案：关闭 TLS 校验会改变凭据传输信任；任意 HTTP / URL 通配会扩张边界；history 换入口实测仍走 captive；盲目增加重试不能修复确定的策略拒绝；全页验证码合并会混入其他登录方式；看到 HTTP 200 就继续动作会丢失业务拒绝。

## 后果与验证

代价是离线引导包含一次匿名明文请求，提示可被篡改或阻断；它永远不携带账号、密码或会话，后续仍须 HTTPS 与独立核验。只支持已观察到的普通来源 / 固定根目标，history 带 query 的 captive 仍拒绝，不宣称覆盖所有门户变体。

实现：[Transport](../../../../desktop/crates/ysu-auth/src/transport.rs)、[Browser 接线](../../../../desktop/crates/ysu-auth/src/browser.rs)、[CAS / 动作解析](../../../../desktop/crates/ysu-auth/src/protocol.rs)、[Python API](../../../../src/ysu_net/auth/api.py)与[共用动作检查](../../../../src/ysu_net/auth/common.py)。回归：[匿名客户端及边界](../../../../desktop/crates/ysu-auth/src/captive_tests.rs)、[Rust 合同](../../../../desktop/crates/ysu-auth/src/live_contract_tests.rs)与[Python 合同](../../../../tests/test_live_contracts.py)。

本地仅执行静态核对，云端产品 / 格式 / 单元检查待授权提交独立构建分支后执行。真实采样运行的是独立观察器及受限 Python worker，不是 Rust 产品。123 测试账号已通过 CAS，但校园网服务拒绝，连接尚未恢复；不能把采样器修正或真实协议样本宣称为 Rust 登录成功。

2026-10-28 补证：用户授权在 123 安装正式 v0.2.2 Python CLI；源码与标签 25 文件一致。正常入口保持原 HTTP 请求语义，在进程内 DNS 覆盖及被动观察下，对相同 111 输入也得到 status=1 → login=3 → status=1，CAS 成功后 serviceLogin 拒绝。该拒绝不能定性为 Rust 专属或配置无效，历史成功条件仍需对齐；详细范围与安装 / DNS 限制归[补证](../../../../docs/portal-123-review-2026-10-27.md#2026-10-28-正式-python-cli-对照补证)。此结果不改变专用引导、验证码范围及服务拒绝即停止的源码选择，也不构成新 Rust 产品通过。

2026-10-28 接线补齐：[共用导航决策](2026-10-28-shared-bootstrap-navigation.md)使 API Location / HTML 与 Browser 引导共用解析入口，并处理 Browser 已许可的静态 HTML 跳转；只替代本文接线覆盖范围，不改变匿名请求、来源 / 目标及 TLS 条件。新源码仍待云端验证。
