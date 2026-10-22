# Windows 原生只读查询修复与复装验收（2026-10-21）

## 结论与范围

已修复原生查询、重新构建并覆盖安装当前用户版客户端，完成安装后真实 WebView2 界面的只读验收。当前门户会话在线，实际服务为“中国联通”；账户页成功取得 5 项在线字段与 3 条门户业务条目。门户没有提供剩余流量和账户余额，页面明确显示“门户未提供”，没有把缺失值当成零或不限量。

实机阶段未登录、下线、切换账号或服务，未启用自动重连/轮换，未改机器网络配置。使用空凭据、API 后端、自动操作关闭的隔离测试配置，不覆盖用户正常配置。前后当前身份、服务和 IP 的私有 HMAC 一致，正常配置/账号簿/GUI JSON 与系统自启项保持原样。正常启动快捷方式没有测试参数。

这是未提交开发快照的本机修复验收，不是正式发布，也不表示登录、下线、物理断网重连或账号池已作新一轮实机验收。

## 根因和改动

真实 Python 请求链显示：HTTPS 入口跳转页返回同门户主机的旧 HTTP 页面地址；该 HTTP 页面只作 308 升级回同路径、同查询的 HTTPS。旧 Rust 在第一跳检查协议时返回错误码 2、认证跳转协议不支持。本次实际链没有经过历史探针提到的捕获页，也不是 JavaScript 分支误取。

Rust 仅在专用、无请求体的 GET 引导里，将精确可信入口产生的同主机默认 HTTP 端口、指定门户页面、唯一有效会话标识的旧地址规范为 HTTPS，再发送请求。URL 用户信息段、片段、其他来源/路径/端口、重复标识等负例保持原行为；通用 API、CAS、POST 和 HTTPS 允许边界没有放宽，TLS 校验仍开启。Python 实现原已工作，保持不变，新增共享样本验证协议结果。

账户页区分未知、确认离线、未读取和读取失败；新增向后兼容的公共信息错误字段，失败直接显示错误与只读重试，成功后清错。信息失败不伪造连接离线/在线；在线状态新确认后作废旧离线账户结果。既有用户 CSS 和预览脚本等改动按基线哈希保留。

实现与回归：[传输边界](../desktop/crates/ysu-auth/src/transport.rs)、[共享门户样本](../tests/fixtures/portal-navigation.json)、[原生只读探针](../desktop/crates/ysu-auth/examples/readonly_probe.rs)、[运行时](../desktop/src-tauri/src/runtime.rs)、[账户界面](../desktop/src/App.svelte)。当前使用语义见[使用说明](usage.md#账户流量与诊断)。

## 验证

| 验证层 | 本轮结果 |
| --- | --- |
| WSL Python 离线回归 | 345 通过；协议子集 33 通过 |
| WSL Rust 认证回归 | 75 通过、7 个浏览器专用 fixture 忽略；新增断言先红后绿 |
| WSL Rust 真实只读查询 | status → info → status 成功，前后仍为中国联通在线 |
| Windows 前端与构建包装 | 类型检查 0 错误/警告，89 项前端测试、5 项包装脚本测试通过 |
| Windows MSVC 认证库 | 70 通过、7 个浏览器专用 fixture 忽略；平台条件造成与 Linux 数量不同 |
| Windows MSVC 运行时 | 86 通过 |
| Windows 原生协议 | 新构建的 Rust 探针 status/info 均成功，不读取保存密码 |
| 安装 | 当前用户 NSIS 返回 0；安装 EXE 精确匹配构建包载荷，包括包类型标记；负例验证通过 |
| 安装后真实界面 | 非 Demo 的原生 WebView2：状态中国联通在线、账户字段和业务条目存在、刷新 busy/禁用/恢复均观察到 |
| 原生异常界面 | 独立测试配置指向未监听的本机 HTTPS 端口；未知不显示为确认离线，错误 alert 与只读重试有效；没有切断机器网络 |
| 退出与资源 | 两个最终验收实例均正常退出码 0，私有进程树为空，调试端口关闭 |

原生页面经本机 CDP 驱动，不是 Vite 预览或 Demo 数据。截图在捕获前遮盖身份、地址和个人条目，模型实际检查后确认可读、相互不同，布局与按钮正常。截图中的“已脱敏”来自取证遮盖，不是产品字段。仅检查常规视口，不声称已覆盖所有 DPI/多屏/最小窗口。

取证脚本此前的准备器识别与“成功必须新增日志”假设失败已保留，不当作产品失败或通过证据；最终改用真实 busy 生命周期和原生快照验收。调用包装器没有捕获完整动作序列，其空列表不作为完整网络审计；操作白名单、空凭据、自动控制关闭、源代码检查与前后会话签名共同限定本轮范围。在线前后采样一致不等于连续网络抓包证明。

## 安装与清理

安装版本仍为开发版 0.1.0；新的已安装 EXE SHA256：`BCABA6640C32C3A27BB288A88D3C72E785322729D4535D7E3898937691CC7700`。

已删除本轮 Windows 源码副本、依赖、编译目标、临时测试环境/配置/浏览器缓存和新建 NSIS 缓存，共 **5,782,839,654 逻辑字节**。保留安装客户端、用户正常数据和此前保留的开发工具。截图、安装包和脱敏证据留在 Linux 忽略目录，不重新创建 Windows 构建缓存。

清理后安装文件哈希保持一致，正常配置与 GUI 文件仍在，Rust/Cargo 1.99.1 保留，Windows 本机不经系统代理的外网 HTTPS 返回成功。验收程序现已退出，用户可正常从开始菜单打开；没有禁用客户端或改变原自启设置。

证据入口：[根因](../build/windows-query-fix-20261021/protocol-root-cause.json)、[回归及 Linux 复测](../build/windows-query-fix-20261021/protocol-verification.json)、[安装校验](../build/windows-query-fix-20261021/installed-verification.json)、[真实 UI](../build/windows-query-fix-20261021/evidence-live/native-ui.json)、[异常 UI](../build/windows-query-fix-20261021/evidence-failure/native-ui.json)、[前后保护校验](../build/windows-query-fix-20261021/baseline-after.json)、[清理回执](../build/windows-query-fix-20261021/cleanup.json)。这些 build 证据是本机文件，不随源码提交。

![真实原生连接页，已脱敏](../build/windows-query-fix-20261021/evidence-live/connection-redacted.png)

![真实原生账户页，已脱敏；缺失余量与余额如实显示](../build/windows-query-fix-20261021/evidence-live/account-redacted.png)
