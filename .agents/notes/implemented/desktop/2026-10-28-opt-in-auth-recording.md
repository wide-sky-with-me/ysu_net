# 显式开启的本地认证链路记录

日期：2026-10-28。状态：源码已实施，四平台云端检查通过，尚未正式发行。
范围：三平台原生桌面、共用 Rust AuthClient、API 与 Browser；Python CLI 保留原日志语义。

## 背景

用户提供 Windows 正式版在 HTTPS 门户 redirect 转 HTTP captive 时的 network 错误。现有闭集诊断可区分导航拒绝与网络失败，却不能区分请求发送、响应读取或底层 I/O 类别；内存日志会在退出后丢失。用户愿意本机复现，但复现可能断网，因此需要事先开启且可离线保留的证据。

## 选择

- 调试默认关闭，只在原生日志页显式开始 / 停止。启动记录不访问校园网，不启动认证、取消现有任务或改变自动重连 / 配置；重启与更新后台重建不自动恢复记录。
- Rust 库提供可选 Trace sink。每次 AuthClient 操作在 task-local scope 内生成独立 ID，Operation 显式携带该上下文；普通调用与无界面探针不启用时无文件副作用。浏览器事件沿已有 Operation 关联，不向子进程注入日志参数或秘密。
- 认证操作 Future 由非 async 入口装箱后交给追踪 scope，避免原生账号切换的嵌套 Future 放大栈占用。首轮云端原有账号池回归暴露栈溢出，保留原断言与默认栈，不以调整 RUST_MIN_STACK 绕过。
- 文件只接受 typed enums / bool / numbers 与编译期版本、平台、时间。原 URL、host、query 值、设备身份、凭据、头、正文和任意异常文本没有字段入口。网络错误遍历有界 source 链，只取固定类别及数字 OS 码；保留原 AuthError 和公开错误分类接口。
- 每次记录持有独立 writer / sink；停止或到限关闭该 writer，已绑定的认证请求不转投后来的文件。桌面新产生的固定状态通知按发生时刻写入当前窗口，完整复现须在任务开始前启用记录。取消通过 Drop 写终止事件；用户主动停止时可能存在未完成任务，结束标记据实说明。
- 文件按行写入 / flush，开始确认和正常停止执行 sync_data，断网不影响本地写入；不承诺进程强制终止或断电下最后一条完整。I/O 失败只停止记录并暴露状态，不绕过认证规则或扩大超时。
- 配置旁目录每份最多 8 MiB，保留五份本模块名称的记录；到限写结束标记。新建时仅清理最旧且可取得锁的旧文件，拒绝链接目录 / 文件。Unix 新目录 / 文件为 0700 / 0600，Windows 继承父目录权限。
- 文件锁使用 sidecar，避免 Windows 的数据文件排他锁阻止用户读取进行中的 JSONL；维护锁及 writer 锁显式解锁。正常文件句柄不向浏览器授权继承。打开目录命令不接受路径、URL 或程序参数，只能打开该配置派生的目录。

## 替代方案与后果

直接持久化所有普通日志或打开底层 HTTP debug 容易带入完整 URL、Cookie、正文和个人信息，未采用。仅在错误后复制内存日志无法保留失败前链路，也不能区分网络阶段。抓取 HAR / 明文报文不是本功能范围。

全局可切换 sink 会把开启前或旧会话任务混进新文件，故在创建认证客户端时取得本次记录代际。CDP 层只记录主文档元数据与现有认证阶段；其受控认证请求仍由共用 Rust transport 记录，不声称获得 Chromium 内部的完整 TCP / TLS 证据。同步本地写入有 I/O 成本，原认证预算不因此放宽。

## 验证与所属说明

实现：[库事件](../../../../desktop/crates/ysu-auth/src/trace.rs)、[文件生命周期](../../../../desktop/src-tauri/src/debug_recording.rs)、[界面](../../../../desktop/src/components/DebugRecording.svelte)。回归：[网络阶段与脱敏](../../../../desktop/crates/ysu-auth/src/trace_tests.rs)、[文件及代际](../../../../desktop/src-tauri/src/debug_recording_tests.rs)。当前运行合同归[调试指南](../../../../docs/debug-recording.md)。编译、格式化和产品测试仅由 GitHub Actions 执行，本轮通过与前期失败归[验收记录](../../../../docs/debug-recording-2026-10-28.md)；真实 Windows 校园网故障仍需用户复现采样，功能实现不等于该故障已修复。
