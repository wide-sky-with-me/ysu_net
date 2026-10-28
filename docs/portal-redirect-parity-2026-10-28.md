# Shell 跳转轨迹与 Rust 导航对照

日期：2026-10-28。状态：已复核真实 Shell 收据并补齐 Rust 开发源码；新 Rust 未编译、未运行，Windows 原故障未重新采样。

## 证据来源

采用[21 同机对照](portal-21-review-2026-10-28.md)中正式 v0.2.2 云端 wheel 的 `cloud_login` / `cloud_logout` 脱敏轨迹，结合[123 离线采样](portal-123-review-2026-10-27.md)和 v0.2.2 标签源码。21 当轮完成真实离线登录、在线退出、独立状态核验及原连接恢复；本次重新读取已保存收据，没有再次下线或提交校园网密码。

21 轨迹是 Requests Session.send 的被动观察，包含自动跟随产生的嵌套请求；外层 send 的 response 记录的是最终响应。没有保存每个中间 Location、页面或 query 值，因此不能从相邻事件推断缺失的中间状态码或确切参数。

| 场景 | 实际请求顺序及可见结果 |
| --- | --- |
| 离线登录前导航 | HTTPS index（无 query，200）→ HTTPS redirect → HTTP captive（无 query，200）→ HTTPS index（有 query）→ HTTPS main（200）→ 状态查询确认 offline |
| 在线退出前导航 | HTTPS index（无 query，200）→ HTTPS redirect → HTTP main（308）→ HTTPS main（200）→ 状态查询确认 online，随后才执行 offline POST |

21 观察器将 captive 路径归为 other，不能据此证明是根路径；`http://124.124.124.124/` 的精确允许形状依据是 123 原采样。两机条件不同，本文不扩张到任意 captive 路径。

## 实现差异与本次修改

正式 Python 的 `open_portal_get_session` 明确使用 `allow_redirects=True`，到达 captive 后还调用页面导航解析器，再请求 HTTPS 门户。它既有 HTTP 自动跟随，也有单独的 captive 页面处理。

正式 Rust 虽然设置 `Policy::none()`，但 `follow_inner` 自己处理 301/302/303/307/308，并有可信旧主页面的 HTTPS 规范化。缺口是固定离线 HTTP captive 没有等价处理；此前开发源码已加入匿名解析，但只接到 HTTP Location，HTML 分支仍未统一。

本次在[共用 Transport](../desktop/crates/ysu-auth/src/transport.rs)增加统一异步导航解析，接入 API Location、[API HTML](../desktop/crates/ysu-auth/src/protocol.rs)与[Browser](../desktop/crates/ysu-auth/src/browser.rs)。Browser 对 bootstrap 主 Document 内已许可的静态 HTTP 跳转生成 302 HTTPS Location、清空页面 body，再交给原重定向检查和 CDP；Chromium 不运行匿名 HTTP 页。普通 HTTPS 页面和 CAS 继续原有处理。

已补回归源码：API 的 meta refresh / location href / assign / replace；共用解析器的单次限制、导航类型和方法 / 来源负例；Browser 的实际响应头、空 body、Cookie 保留及非主文档 / 非 HTML / POST 不改写。行为唯一说明归[桌面运行语义](tauri-desktop.md#离线-captive-与-cas-表单开发源码云端待验)，取舍归[决策](../.agents/notes/implemented/desktop/2026-10-28-shared-bootstrap-navigation.md)。

## 验证与限制

本次本地只做差异空白、社区文档、链接和源码调用点静态核对。按用户“先只保留源码修改”的选择，没有提交、推送、触发 GitHub Actions，未在本机运行 Cargo、rustfmt 或产品测试；新增回归仍待云端执行。[无界面 Rust 探针](rust-auth-probe.md)也还没有本轮云端产物。

曾在 21 在线时尝试一次无凭据、无 Cookie 的 HTTP captive GET，UTC 03:33:47 得到 URLError，未取得页面，不能作为解析通过或离线路径复现。没有因此再次下线或改动远端配置。本地忽略目录 `build/redirect-parity-20261028/` 保留失败收据、基线和本次静态核对结果；此前成功轨迹仍在 `build/shell-cycle-21-20261028/`。

这些差异与用户描述的跳转问题相符，但缺少原 Windows 故障版本和失败一跳的实际证据，不能证明所有旧报错都由同一原因导致。123 的 CAS 后服务拒绝是另一项已有证据，不能通过导航修复宣称消除。
