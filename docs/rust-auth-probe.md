# 无界面验证 Rust 认证链

状态：已使用云端产物在 21 完成共用 Rust 认证库的真实登录 / 退出与 Shell 独立核验，并在 Windows 运行无凭据原生 status。源码、摘要、云端矩阵和结果边界归[0.2.3 发布记录](desktop-release-0.2.3.md)；[21 Shell 轨迹](portal-21-review-2026-10-28.md)保留为历史对照来源。

## 实际验证对象

[`auth_probe`](../desktop/crates/ysu-auth/examples/auth_probe.rs)直接调用桌面共用的 `ysu_auth::AuthClient`，复用同一个 Portal / CAS / Cookie / 加密 / DNS / 跳转实现，不加载 Tauri、WebView 或前端。API 后端无需图形会话；配置为 browser 时仍需系统 Edge / Chrome，使用库原有的无界面 CDP 及私有管道，不另写浏览器逻辑。

| 命令 | 前提 | 成功证据 |
| --- | --- | --- |
| `ysu-auth-probe status` | 配置有效；可无账号密码 | 新会话查询，在线退出码 0、明确离线 1；未知为库错误 |
| `ysu-auth-probe login` | 前查明确离线、配置有凭据 | 真实 `AuthClient::login` 成功后，再以新 Transport / Jar 查询，在线身份及服务均与配置一致 |
| `ysu-auth-probe logout` | 前查在线，且身份 / 服务与配置一致 | 真实 `AuthClient::logout` 成功后，再以新 Transport / Jar 查询到明确离线 |

已在线的 login、已离线的 logout 返回前提未满足，不能被算成新的登录 / 退出通过。工具比产品的幂等入口严格，这是验证合同，不改变 GUI 的原有行为。前查、动作及后查共用配置 `operation_timeout` 的外层总预算；取消或超时不能保证撤销远端已接受的动作，控制器仍须独立查询和恢复。

只从关闭后的 stdin 管道读取一份原 Config JSON，上限 64 KiB；不接受命令行凭据、配置文件参数或交互终端粘贴，未知参数 / 字段、无效配置和关闭 TLS 校验均在网络请求前拒绝。输入字节缓冲在使用后清零，工具不写配置、Cookie、页面或会话文件；它不接管用户原本已保存的配置文件。

stdout 仅一份 schema=1 JSON：action、phase、outcome、code、before / after 证明与可选固定 diagnostic。phase 区分 input / before / action / after；状态证明只含 online、闭集 service token、owner_matches_config、service_matches_config，不输出账号、IP、任意服务名或响应消息。库错误只输出原 operation / stage / reason / navigation 固定分类，不输出 AuthError.message。

## 云端构建与离线回归

独立的[Headless Rust authentication](../.github/workflows/rust-auth.yml)在 Linux x64、Windows x64、macOS arm64 / x64 上执行认证库、验证入口单元回归和实际二进制输入验收，再构建普通 release example，不启用 local-fixtures，也不需要 GTK / WebView / 前端生产构建。原 Tauri 产品门禁保留，真实 Chromium 夹具仍由 Tauri CI 执行；独立探针成功不能代替全部产品 CI。

以下命令只在 GitHub Actions runner 执行：

```bash
cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --all --check
cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml
cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml --example auth_probe
cargo build --locked --release --no-default-features --manifest-path desktop/crates/ysu-auth/Cargo.toml --example auth_probe
```

例子里的测试需显式 `--example auth_probe` 执行；默认 cargo test 仅保证例子可编译，规则见[Cargo 官方说明](https://doc.rust-lang.org/cargo/commands/cargo-test.html#target-selection)。现有 format-only 云端作业新增收集 examples，便于下载格式化后的源码，不在本机运行 rustfmt。

- [`auth_probe_tests.rs`](../desktop/crates/ysu-auth/examples/support/auth_probe_tests.rs)：输入边界、拒绝幂等空操作、前后身份 / 服务条件和输出脱敏。
- [`live_contract_tests.rs`](../desktop/crates/ysu-auth/src/live_contract_tests.rs)：合成的 index 无 SID → redirect → CAS CBC → 移动 serviceLogin / userOnline → SAM Cookie → offline 与独立查询；采用 21 已观察的成功业务信封，并保留 123 拒绝后零 userOnline 的反例。
- 既有[导航来源回归](../desktop/crates/ysu-auth/src/regression_tests.rs)、[captive 解析与匿名请求](../desktop/crates/ysu-auth/src/captive_tests.rs)、[表单样本](../tests/fixtures/cas-login-methods.json)和 Browser CDP 回归继续约束已观察到的跳转及验证码范围。成功整链夹具使用回环 HTTP，不能冒称真实 TLS / captive 固定地址的整链验收。
- [`auth_probe_smoke.py`](../packaging/auth_probe_smoke.py)：在 runner 运行实际二进制的八种无效输入，检查错误发生在 input 阶段且合成私密值不外泄；端点使用回环，无校园网和真实凭据。

开发 artifact 为 `ysu-auth-probe-<平台>`，保留 7 天，包含二进制、SHA256SUMS、manifest.json。清单关联完整源码 commit、平台 / 架构、profile / features、认证库锁文件与共享地址表摘要；下载后核对来源和摘要再运行。没有版本标签、Release 发布或用户安装 / 自启行为。

## 真实环境对照与剩余项

云端产物就绪后，21 使用本机已验证的移动配置：控制器先暂时停止原守护，以 Shell 确认下线 → Rust login → Shell 独立确认同账号 / 服务在线 → Rust logout → Shell 确认离线，最后用原 Shell 恢复原连接和后台。凭据只经本机管道进入 Rust 进程内存，脱敏报告保留明确的前后状态；失败时先核对实际状态，不盲目重放密码。

Windows 先运行同 commit 的原生 exe 做无凭据 status，取得真实 portal_navigation / redirect 等固定诊断，不需要打开 GUI，也不为复现导航问题主动下线 Windows。只有实际取得现场输入与结果，才能判定历史 Win11 错误是否已修复。

本工具不包含原生 Worker 的队列、跨进程运行锁、配置持久化、托盘或 IPC；外层控制器负责停止其他写入者、串行测试和收尾。独立认证库使用自己的 Cargo.lock，桌面整体依赖图、启动初始化、WebView 与系统集成仍须产品验收，不能由同源认证逻辑通过直接推定 GUI 全部通过。取舍见[决策](../.agents/notes/implemented/desktop/2026-10-28-headless-auth-probe.md)。

账号池的 Shell 直接 / 守护持锁换号已另有[21 实测](account-pool-21-review-2026-10-28.md)。Rust 账号池编排在 Worker 层，其阶段、错误分类及提交门闩回归需原 Tauri CI 执行；本探针只验证 AuthClient 的认证链。用户随后已授权构建发布，实际新 Rust 验证进度与结果归[0.2.3 发布记录](desktop-release-0.2.3.md)。
