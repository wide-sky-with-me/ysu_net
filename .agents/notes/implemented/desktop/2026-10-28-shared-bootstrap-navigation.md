# 共用门户引导导航解析

日期：2026-10-28。状态：开发源码已实施；格式、编译、回归及真实 Rust 验收待执行，未提交或部署。

范围：Rust 认证库 API 与 Chromium/CDP 后端。现行条件归[桌面运行语义](../../../../docs/tauri-desktop.md#离线-captive-与-cas-表单)，实际轨迹和限制归[Shell 跳转对照](../../../../docs/portal-redirect-parity-2026-10-28.md)。

## 背景

正式 v0.2.2 Python API 使用 Requests 自动跟随 HTTP 重定向，并单独解析 captive 页的下一跳；Rust 关闭 reqwest 自动重定向，由自己的有界循环处理 301/302/303/307/308，不能将其定性为完全没有跟随能力。21 的成功 Shell 轨迹包含离线 HTTP captive 与在线旧版 HTTP 主页面两种路径。

此前开发源码已把匿名 captive 解析器接到 HTTP Location，但 API 的 HTML 导航仍只调用同步旧地址规范化；Chromium 遇到 HTML/脚本中的同类 HTTP 入口时，也会先因通用 URL 检查而停止。不同表示方式不应得到不同的门户许可。

## 选择与替代方案

- 在 Transport 统一异步解析入口，按相同来源、目标、方法和 body 条件选择匿名 captive 解析或旧地址 HTTPS 规范化；API Location、API HTML、Browser 主 Document Location 共用。错误保留闭集导航类型，不保存原始 URL。
- Browser 在 bootstrap 主 session / 主 frame、无 body GET、200 text/html 下识别已有解析器支持的静态导航；仅对已许可的两个 HTTP 形状生成受控 302 HTTPS Location 并清空 body，沿用原重定向预算和 CDP 响应头序列化。普通 HTTPS HTML、CAS、iframe、子资源及其他方法保持原处理。
- 匿名客户端、精确无 query 来源和根目标、共享单次机会、HTTPS 同源 index 提示、响应大小和 deadline 均不扩张。本文仅补齐[离线 captive 决策](2026-10-27-offline-captive-bootstrap.md)的接线与表示覆盖；其余限制继续有效，history 来源的 captive 仍不接受。

未选择 Requests 式无限制自动跟随：Rust 仍需在每一跳执行来源校验、Cookie / XSRF 重算及认证 body 跨站重放检查。未选择只修 API：桌面 Browser 后端同样经过 Rust Fetch 传输层。未选择直接执行 HTTP captive 脚本或关闭 TLS：匿名页面仅能提示重新访问 HTTPS 门户，不能提供认证事实。

## 后果与验证

开发源码新增 HTML 兼容分支，没有扩大任意 HTTP 访问。静态 HTML 解析不执行动态 JS；未观察的入口和脚本变体仍可能失败。21 已保存轨迹不含页面、Location 或 query 值，不能证明其 captive 根路径；精确根目标来自 123 原采样，不能用 21 的角色轨迹扩张许可。

实现：[Transport](../../../../desktop/crates/ysu-auth/src/transport.rs)、[API](../../../../desktop/crates/ysu-auth/src/protocol.rs)、[Browser](../../../../desktop/crates/ysu-auth/src/browser.rs)。回归源码：[单次解析及负例](../../../../desktop/crates/ysu-auth/src/captive_tests.rs)、[API HTML](../../../../desktop/crates/ysu-auth/src/regression_tests.rs)与 Browser 内部导航测试。单次机会预先耗尽的测试证明各入口调用同一解析器而不连接校园网；Browser 测试核对实际 302、Location、空 body 及序列化响应头。

用户选择只保留源码，因此本次仅静态核对；新增测试没有执行。之后需以同一云端提交的认证库 / 探针与 Tauri 产物分别验收 Linux 真实登录链和 Windows 导航，当前不能宣称原 Windows 故障已复现或修复验收通过。

2026-10-28 后续验证：共用导航回归及四平台原生 / Chromium 门禁已通过，21 API 真实闭环与 Windows API 只读导航已验证；没有将 API 成绩认作 Browser 后端现场登录。0.2.3 已正式发布，源码、运行编号、公开资产与未覆盖项归[发行记录](../../../../docs/desktop-release-0.2.3.md)。
