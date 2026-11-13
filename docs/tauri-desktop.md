# Tauri 原生桌面版说明

[返回首页](../README.md) · [文档导航](README.md) · [桌面使用指南](wiki/Desktop-Client.md) · [产品与架构](architecture.md) · [界面设计规范](rust-desktop-design.md)

桌面客户端基于 **Tauri 2 + Svelte 5 + Rust** 构建，覆盖 Windows 10/11 x64、Ubuntu 22.04+ x64 与 macOS 13.5+（Apple Silicon / Intel）。所有网络认证、后台重连、多账号轮换与无感认证续约均由纯 Rust 原生模块执行，无需本机安装 Python、Node 或 Playwright。

---

## 核心运行机制

### 1. 门户认证与状态监测

- **认证核心（`ysu-auth`）**：封装校园网 Portal（`auth1.ysu.edu.cn`）与统一身份认证 CAS（`cer.ysu.edu.cn`）的登录、下线、运营商切换、套餐查询及设备自助服务（`/self`）。
- **串行任务调度与防风控熔断（`src-tauri`）**：原生后台 Worker 按主轮询周期（默认 15 秒）串行调度手动操作、断线自动重连（默认 `30 秒 ~ 900 秒` 指数退避）、零流量换号与无感自动续约，通过文件锁避免多进程并发冲突，并向前端推送状态快照；当自动重连**连续登录失败达 3 次**，或触发密码错误、需人工介入的验证码与风控拦截页（退出码 `4`）时自动暂停重连，避免反复尝试导致校园网 IP 冻结。
- **低内存与连接池复用设计**：
  - `ysu-auth` 按 TLS 校验策略复用全局 HTTPS 客户端连接池（`reqwest::Client`，独立按实例注入 Cookie 请求头，避免 15 秒轮询重复加载根证书）；
  - `src-tauri` 限制 Tokio 工作线程池与阻塞池规模（`2` 工作线程 / `8` 阻塞线程），以紧凑结构体存储内存运行日志，在窗口销毁驻留托盘期间跳过无接收端的 `core-event` 快照序列化广播，并在窗口转入托盘或最小化后主动触发 Windows 工作集修剪（`SetProcessWorkingSetSize`）。
- **后台只读状态观察**：即使未开启自动重连，后台也会以 30 秒周期轻量检测在线状态（网络异常时退避至最高 300 秒）；窗口恢复可见或系统网络变化时自动触发刷新，实时同步连接状态与当前运营商。
- **门户会话边界与安全导航**：
  - 独立维护 4 组会话上下文：`cer.ysu.edu.cn/authserver`（`CASTGC`、`XSRF-TOKEN`、`JSESSIONID`）、`auth1.ysu.edu.cn/eportal`（`JSESSIONID`）、`auth1.ysu.edu.cn/sam`（`JSESSIONID`，下线前预热）及 `/self` 与 OAuth2 根路径（`SESSION`）；`/portal/portal-main` 不依赖 Cookie，凭 URL `sessionId` / `flowSessionId` 驱动 `authenticate → serviceSelection → finish` 工作流节点。
  - 仅在受限白名单内跟随门户跳转；针对 `/eportal/redirect.jsp` 下发的旧式 `http://auth1.ysu.edu.cn/portal/portal-main?...` 地址在发包前本地改写为 `https://`，防止触发服务端 `308` 重定向丢失 `customPageId`、`userIp`、`ssid`、`nasIp` 等参数或明文传输 `sessionId`；离线探测 `http://124.124.124.124/` 仅作无 Cookie 单次明文引导提示。
  - CAS 多登录表单页面仅围绕选中的密码表单提取 `#pwdEncryptSalt`（按 16/24/32 字节盐值分别执行 AES-128/192/256-CBC 加密）并判定 `#captchaDiv` 可见性，同时剥离 `<script>`/`<style>` 等非正文标签后检测风控拦截页（`IP被冻结`、`访问被拒绝`、`安全验证`、`风险验证`、`访问频繁`、`noSupport`）。
- **独立结果核验**：登录、下线、切换运营商与切换账号均以操作后的无 Cookie 独立状态查询为准，只有确认目标账号与运营商实际生效后才报告成功。

### 2. 设备自助服务与 7 天无感认证

侧栏「设备」页对接校园网自助服务（`auth1.ysu.edu.cn/self`）：

- **会话管理与委托登录**：门户认证通过 `/cas-sso/clientredirect?client_name=sidadapter` 委托 CAS，自助服务则经 `/oauth2/authorization/custom-self`（`CasOAuthClient`）委托登录。桌面端在进程内按账号隔离缓存 `/self` 已认证会话与 CAS `CASTGC` 票据（均为 30 分钟有效，其中 `CASTGC` 按配置与凭据精确索引并在遭拒或触发风控时立即清除），避免短时间内重复提交密码触发 CAS 风控。
- **账号归属与在线设备识别**：页面顶部固定展示当前「查询账号」（多账号池可直接切换并同步联动下方设备列表与无感续约表单；当校园网关当前在线学号与所查询账号不一致时给出状态提示）。设备列表同时依据门户 `currentDevice`（`本机`）与本机物理网卡 MAC（`localMac` → `本机网卡`，探测时自动过滤 `Tailscale`、`ZeroTier`、`WireGuard`、`Sing-box`、`Meta Tunnel`、`tun2socks` 等虚拟隧道适配器）标定当前主机；无 MAC 信息的有线设备行不展示无效的「开启无感」按钮，离线设备自动省略空占位字段。
- **在线设备与远程下线**：读取在线设备列表（名称、类型、MAC、IP、在线时长、接入方式）、计费套餐与剩余流量；支持下线单台或全部设备，并在下线后轮询复核列表确认生效。
- **7 天无感认证控制**：支持查看账号下全部 7 天无感认证记录（MAC、设备名、到期时间），一键为本机或在线设备开启 7 天无感认证（`/self/setting/noSense`）、取消无感绑定（`/self/mac/unbind`）及修改默认上网服务（`/self/setting/net`）。
- **到期前自动续约与多账号协同**：
  - 自动续约规则保存在主配置同目录的 `config.nosense.json` 中，支持按账号独立配置。
  - 原生后台随 15 秒主循环调度续约检查：单个账号查询成功后的常态网络巡检间隔为 **6 小时**，遇到瞬时网络或接口异常时 **30 分钟** 后重试，遇到密码错误、验证码或风控等需人工处理异常（退出码 `4`）时自动暂停该账号续约直至重新启用或手动续约；当检测到目标 MAC 的无感认证距离到期不足 24 小时或已过期时，自动执行「解绑 → 重新绑定 7 天」。
  - 手动切换账号或触发零流量自动换号时，后台在下线旧账号前自动解绑旧账号上的本机 MAC 无感认证，并在新账号上线后自动为新账号绑定本机无感认证及迁移续约规则。

### 3. 验证码自动识别与 DNS 容错

- **离线验证码识别**：当 CAS 要求输入四位图形验证码时，若本地已下载 `common.onnx` 模型（可在「设置 → 认证与重试 → 验证码识别」一键下载并自动校验 SHA256），客户端直接通过内置 `tract-onnx` 引擎本地识别填充；单次登录最多提交 **2 次**（首轮识别提交 1 次；仅当 CAS 明确返回验证码不匹配提示时刷新 `execution` 与 `pwdEncryptSalt` 换图重试 1 次），密码错误或触发风控页面时立即停止。
- **DNS 备用 IP 回退**：当校园网 DNS 解析缓慢（超过 500ms）或失败时，自动对 `auth1.ysu.edu.cn` 与 `cer.ysu.edu.cn` 使用内置备用 IP 建立 TCP 连接，同时完整保留原域名的 HTTP Host、TLS SNI 与 HTTPS 证书校验。
- **可选浏览器模式**：默认使用纯 Rust HTTP API；若切换为「浏览器」模式，Rust 通过私有匿名管道（`--remote-debugging-pipe`）调用本机 Edge 或 Chrome，不开放任何本地调试端口。

### 4. 系统托盘与开机自启

- **系统托盘**：支持关闭主窗口后驻留系统托盘，右键菜单直接展示当前连接状态摘要、流量、连接详情，并提供连接/断开、刷新、自动重连开关与退出操作。
- **开机自启**：基于系统原生登录自启机制，支持独立配置「开机自启」与「自启后最小化到托盘」。

---

## 配置与演示模式

- **配置文件位置**：
  - Windows：`%APPDATA%\ysu-net\config.json`
  - Linux / macOS：`${XDG_CONFIG_HOME:-~/.config}/ysu-net/config.json`
  - 同目录下存放 `gui.json`（外观与启动偏好）、`config.accounts.json`（多账号池）与 `config.nosense.json`（无感自动续约配置）。
- **演示模式**：启动时传入 `--demo`（或设置环境变量 `YSU_DESKTOP_DEMO=1`）可使用内存样例数据体验完整界面，不读写本机真实配置、不发起校园网请求。

---

## 构建前提与持续集成

桌面客户端的编译、打包与跨平台安装验收统一在 **GitHub Actions** 云端工作流（[`.github/workflows/tauri.yml`](../.github/workflows/tauri.yml)）中执行，覆盖四个平台目标：

- **Windows x64**：生成当前用户 NSIS 安装程序（`*-setup.exe`）及签名更新载荷。
- **Linux x64**：基于 Ubuntu 22.04 基线生成 `.deb` 安装包。
- **macOS arm64 / x64**：分别针对 Apple Silicon 与 Intel 架构构建 `.dmg` 镜像与 `.app.tar.gz` 签名更新载荷。

云端工作流常用检查命令：

```bash
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --check
cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml
```

推送 `v*` 版本标签时，工作流会在四平台构建、安装自检与浏览器界面验收全部通过后，校验更新包签名并自动发布至 GitHub Releases。
