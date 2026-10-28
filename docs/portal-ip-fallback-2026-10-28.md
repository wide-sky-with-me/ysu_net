# 123 备用 IP 与 TLS 只读核验

日期：2026-10-28。状态：指定连接地址的真实网络检查完成；新增产品源码尚未云端验收、部署或发行。

用户在[此前 123 采样](portal-123-review-2026-10-27.md)后确认域名解析问题，并提出使用 IP。本轮保持服务器系统 DNS、路由、代理、服务和配置不变，没有登录、下线或凭据 POST。

## 实际命令与结果

2026-10-28 02:01:55 UTC，在 123 执行：

```bash
# 两个目标分别设置 host、address、entry；仅为公共入口，无票据或账号。
dig @202.206.240.12 "$host" A +short
curl --noproxy '*' --resolve "$host:443:$address" \
  --connect-timeout 4 --max-time 8 --silent --output /dev/null \
  --write-out '%{http_code} %{ssl_verify_result}' "https://$host/$entry"
```

| 目标 | 入口路径 | DNS 结果 | curl 退出码 | HTTP | SSL verify result |
| --- | --- | --- | --- | --- | --- |
| 门户 `auth1.ysu.edu.cn` | `eportal/index.jsp` | 与本轮[地址表](../src/ysu_net/auth/campus-addresses.json)一致 | 0 | 200 | 0 |
| CAS `cer.ysu.edu.cn` | `authserver/login` | 与同一地址表一致 | 0 | 200 | 0 |

`--resolve` 仅指定连接 IP，URL 保留原域名，未使用 `--insecure`。此次没有请求认证后的业务接口，不构成登录恢复。IP 返回 200 也不保证长期地址稳定、不同网络可达或服务策略允许登录。

## 源码范围与待执行项

Rust Transport 与 Python 默认 API 的备用连接逻辑、回归和 wheel 数据检查已补；当前规则见[网络语义](tauri-desktop.md#dns-失败时的备用-ip开发源码云端待验)，原因见[决策](../.agents/notes/implemented/desktop/2026-10-28-campus-ip-fallback.md)。Python 可选 Browser 未接入。正式 v0.2.2 CLI / 桌面尚无该能力。

本机仅做源码 / JSON / 文档静态检查，不运行 Cargo、产品测试或打包。待授权将已审查的修改提交、推送至独立开发构建分支后，执行 GitHub Actions 格式、Mock 与四平台 Native 验证，再下载校验云端产物，并在 123 的原系统 DNS 条件下只读核验。之前已通过的候选成绩不能作为本轮新增代码的通过证据。

此前 serviceLogin 拒绝独立存在；本轮没有再次提交相同凭据，不能宣称已经纠正其根因或恢复在线。
