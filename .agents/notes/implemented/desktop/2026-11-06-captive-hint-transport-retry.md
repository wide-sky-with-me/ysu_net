# 匿名 captive 提示改用受限原始读取

日期：2026-11-06。状态：源码修改完成，本地 crate 测试通过；Windows 产品构建与实机复核进行中。

范围：桌面 Rust 认证核心的匿名 captive 引导请求（`desktop/crates/ysu-auth/src/transport.rs`）。
来源、目标、方法、一次性语义、大小与时限约束不变；API / Browser 共用解析器的接线不变。

## 背景与真实证据

`天选_唯一`（Windows 11 24H2）直连测试机上，WiFi 接入 iYanDa 且未认证时，GUI 0.2.3 与 0.2.4、
API 与浏览器两种认证方式四个组合全部以 `stage=portal_navigation reason=network` 失败；同一时刻
同一账号用 Python CLI 0.2.4 (`ysu login`) 登录成功并完成真实联网，随后 GUI 立即正确显示已连接。

现场链路（该机 curl）：

```
https://auth1.ysu.edu.cn/                      302 -> /eportal/redirect.jsp
https://auth1.ysu.edu.cn/eportal/redirect.jsp  302 -> Location: http://124.124.124.124
http://124.124.124.124/                        200  单行脚本，跳转 HTTPS index.jsp?wlanuserip=...
```

第一轮只调整了 reqwest 客户端的压缩与协议协商并加一次重试；云端构建后的实机复测仍然
`reason=network`，因此该方向被证伪并保留在历史里。

第二轮在同一台机器上做对照（交叉编译到 `x86_64-pc-windows-gnu` 的最小程序）：

```
tokio TcpStream 连接 124.124.124.124:80        ok, 91 ms
原始 HTTP/1.1 GET（5 种头组合）                 全部 200，601 字节，含完整 500 字节正文
reqwest 0.12（与产品相同的构建参数）            连续 3 次
  error sending request ... client error (SendRequest)
  ... connection closed before message completed
```

同一地址、同一进程外条件，裸 TCP 稳定成功而 hyper 稳定判为响应不完整；实测声明长度与实际正文
都是 500 字节，不存在截断，具体触发条件未再隔离。

## 选择与替代方案

- 这条匿名提示改由 `captive_get()` 用 `tokio::net::TcpStream` 完成：一次 `GET`、读至对端关闭、
  按 `\r\n\r\n` 切分、只取状态码与正文，不跟随重定向、不携带 Cookie/凭据、沿用 `RESPONSE_LIMIT`。
- 传输失败仍只重试一次，且仅限匿名 GET；`captive_read` 的一次性语义不变。
- 放弃的方案：继续在 reqwest 上关压缩 / 换 TLS 后端 / 调 UA（实测都不改变 hyper 的判定）；
  放宽 `is_captive_bootstrap` 来源条件（诊断显示它已命中，放宽是无证据的扩张）；
  提高观察预算（整链 250 ms，预算不是瓶颈）。

## 后果与验证

代价是这一段不再复用 reqwest 的连接池、代理与 TLS 配置，需要自己处理读取边界；收益是把
"服务端关闭与声明长度不符"这类差异挡在认证核心之外。

已执行：`cargo test --lib`（ysu-auth）133 passed / 0 failed / 7 ignored，含
`observed_iyanda_hint_resolves_to_the_fresh_https_index`（真实页面夹具）、
`anonymous_hint_read_tolerates_a_body_shorter_than_its_declared_length`（本地声明长度大于正文）。

未执行：Windows 产品构建与实机复核。若实机仍失败，下一步在该机用 `pktmon` 抓取这段
明文请求的双向报文，确认服务端在哪一步关闭连接。
