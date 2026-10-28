# 直接调用共享 Rust 认证库的无界面验证入口

日期：2026-10-28。状态：验证工具、回归及云端工作流源码已实施；云端编译、格式、执行与远端 Rust 验收待进行。

范围：开发用独立探针及四目标认证 CI，不改产品 Config、IPC、原生运行器或认证算法。当前合同唯一维护在[验证说明](../../../../docs/rust-auth-probe.md)。

## 背景与选择

用户指出 Windows Rust 图形版曾在门户连接 / 跳转失败，要求复现认证逻辑，不因缺图形界面停在 Shell 成绩。[21](../../../../docs/portal-21-review-2026-10-28.md)已证明正式 0.2.2 Shell 在相应输入下能离线登录、在线退出，并观察到离线 captive 与在线旧门户跳转；这些结果不能证明 Rust 通过。

认证已独立为 `ysu-auth` 库，桌面与探针可调用同一 AuthClient。选择新增 example 二进制，使用真实 status / login / logout 和新的独立前后查询。探针只实现验证前后条件与输出脱敏，不重写导航、SSO、加密、Cookie 或业务状态机；未来库修正无需同步第二套算法。

验证入口不把已在线 / 已离线的幂等返回算成新的登录 / 退出通过，也不只凭动作返回成功。前后查询及动作共享外层总预算，仍需外部监督核对超时后的真实状态。接受 api / browser 的原 Config，但要求 TLS 校验开启，不增加 fixture / HTTP 运行参数。

配置只经有界 stdin 管道进入进程；不增加命令行密码、配置落盘或任意服务器消息输出。新增工具使用闭集 phase / outcome 与原固定 AuthDiagnostic，让入口前查、动作本身和后查的错误可以区分。开发者产物由 manifest、源码 commit 和摘要关联，独立 CI 不依赖 GUI 构建，但保留原产品门禁。

## 实际考虑的替代方案

- 用 Python 复制 Rust 协议：容易与生产代码分叉，复制正确不等于 Rust 正确，未采用。
- 只运行只读 probe：已有 readonly_probe 能定位导航，但不足以验证 fresh CAS / 服务上线 / 实际退出，保留它并新增严格动作验证。
- 通过 Tauri GUI 的测试开关连接真实网络：会把 WebView / 显示会话前提混入认证定位，现有本地演示 / fixture 开关也不能当作真实网络入口，未扩展。
- 把探针做成新的正式 CLI / 安装组件：会引入运行锁、服务、升级与兼容责任；本次仅提供有界开发工具，外层恢复原连接与守护。

## 后果、实现与验证

独立库和桌面整体使用不同 Cargo.lock / 依赖图，探针没有 Worker、IPC、共享运行锁或系统集成，因此同源逻辑通过仍不等于完整 GUI 验收。browser 仍需平台 Chrome / Edge；独立 CI 不替代原四平台 Chromium 测试。输入缓冲清零不代表第三方库和 Config 字符串的全部内存副本已清零。

实现：[auth_probe.rs](../../../../desktop/crates/ysu-auth/examples/auth_probe.rs)；回归：[入口合同](../../../../desktop/crates/ysu-auth/examples/support/auth_probe_tests.rs)、[观察信封整链](../../../../desktop/crates/ysu-auth/src/live_contract_tests.rs)与[测试服务](../../../../desktop/crates/ysu-auth/src/tests.rs)。云端：[独立工作流](../../../../.github/workflows/rust-auth.yml)、[实际二进制输入验收与标识](../../../../packaging/auth_probe_smoke.py)；原格式作业新增收集 examples。

本机只做源码、Python AST、YAML、diff 与文档静态核对；不运行 Cargo、rustfmt 或产品测试。编译和真实 Rust 结果尚未取得，不能以此前 Shell 实测或旧候选 CI 记录代替。后续按独立分支的确切 commit 下载 Linux / Windows 产物，在 21 做完整动作对照、Windows 做只读导航复现，再分别记录实际结果。
