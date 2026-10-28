# 校园域名解析失败时仅替换连接地址

日期：2026-10-28。状态：开发源码已实施，云端编译 / 格式 / 回归待执行；未部署、未发行。

范围：三平台 Rust API / CDP 共用网络层、Python CLI 默认 API。运行语义与后端覆盖唯一维护在[桌面网络说明](../../../../docs/tauri-desktop.md#dns-失败时的备用-ip)。

## 背景

123 使用的系统 DNS 查询门户与 CAS 超时；校园 DNS 可返回地址。用户提出直接使用 IP。[真实只读验证](../../../../docs/portal-ip-fallback-2026-10-28.md)表明：保留原域名并指定连接 IP、开启 TLS 校验，可取得两个入口的 HTTP 200。此前手动覆盖 DNS 后仍存在 serviceLogin 业务拒绝，因此 DNS 修复不能代表认证成功。

## 选择

保留配置 URL，只在已知精确域名解析失败时换用核验过的地址，正常 DNS 优先。域名与 IP 的唯一数据源放在 Python 包内 JSON，Rust 用 include_str! 嵌入，避免两端手抄地址漂移；云端 wheel 检查保证分发带入原始字节。地址有时效性，未实现在线更新或自动可信发现。

Rust 使用 reqwest resolver 扩展，仅替换返回的 SocketAddr；零端口交给原 URL 决定端口。已知域名的系统 lookup 最多等待 500 毫秒，在既有总 deadline 内留出 TLS / 请求时间，兼顾两秒被动观察；未知域名维持原解析等待。底层系统解析可能在 future 取消后继续占用工作线程，不能将其描述为 DNS 系统调用已强制终止。fallback 不接触 HTTP 请求体，也不以 TCP、TLS 或业务错误触发重发。

Python 使用自有 adapter / pool / connection；仅 NewConnectionError 异常链中的 gaierror 触发回退。在 _new_conn 内临时替换 urllib3 的 _dns_host，建立 socket 后立即恢复，TLS 及 HTTP 仍看到原域名。它依赖 urllib3 内部字段，因此保留真实回环 TLS 的证书正反例，验证 Host、SNI、Origin 和 Cookie。复制 PoolManager 的类映射，避免影响不相关 Session；原代理管理器不改。Python 等待原系统 DNS 错误后回退，不加入后台解析线程或全局超时补丁，CLI 原子进程总时限继续适用。

Python 可选 Playwright 同时有 Chromium 与 Node APIRequestContext 请求；单加 Chromium host resolver flag 不能覆盖后者。此次明确保留系统 DNS 要求，不引入本地代理或跨执行器 Cookie 桥接；Rust Browser 全部已拦截流量经 Transport，因此能共享该能力。该差异须在使用说明中明确，不宣传所有 Python 后端已覆盖。

## 实际考虑的替代方案

- 把配置 URL 换成 IP 或关闭证书校验：前者改变 SNI、证书域名、同源及 Cookie，后者降低原有信任边界，均未采用。
- 无条件固定地址：会压过未来正确的系统 DNS 更新；选择仅失败回退。
- 修改 hosts / 系统 DNS：仍是可行的系统修复，但影响其他应用且通常需要管理权限，不作为产品默认副作用。
- 增加 DNS 客户端依赖：本次只需两个已知地址的连接回退，现有 reqwest / Requests 扩展即可，不引入额外解析协议及服务器策略。
- 全局替换 socket.getaddrinfo 或仅添加 Chromium flag：分别有跨 Session 副作用和覆盖缺口，未采用。

## 实现与验证

[Rust resolver](../../../../desktop/crates/ysu-auth/src/dns.rs)、[Transport 接入](../../../../desktop/crates/ysu-auth/src/transport.rs)、[Python adapter](../../../../src/ysu_net/auth/dns_fallback.py)、[API Session 接入](../../../../src/ysu_net/auth/api.py)。[共享地址表](../../../../src/ysu_net/auth/campus-addresses.json)不含账号、会话或密钥。

[Rust 回归](../../../../desktop/crates/ysu-auth/src/dns_tests.rs)包含正常多地址、失败 / 空 / 挂起解析、未知域名和两秒 HTTP 集成预算；[Python 回归](../../../../tests/test_dns_fallback.py)包含拒绝 / 超时不重连及真实回环 TLS 正反例。[Mock CI](../../../../.github/workflows/test.yml)要求 OpenSSL 并验证 wheel 资源。新回归尚未执行，真实服务器证据仅证明 curl 指定 IP 的网络与 TLS 可达性，不能代替 Rust / Python 产品验收。
