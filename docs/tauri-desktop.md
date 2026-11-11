# Tauri 原生桌面版说明

[返回首页](../README.md) · [文档导航](README.md) · [桌面使用指南](wiki/Desktop-Client.md) · [产品与架构](architecture.md) · [界面设计规范](rust-desktop-design.md)

桌面客户端基于 **Tauri 2 + Svelte 5 + Rust** 构建，覆盖 Windows 10/11 x64、Ubuntu 22.04+ x64 与 macOS 13.5+（Apple Silicon / Intel）。所有网络认证、后台重连、多账号轮换与无感认证续约均由纯 Rust 原生模块执行，无需本机安装 Python、Node 或 Playwright。

---

## 核心运行机制

### 1. 门户认证与状态监测

- **认证核心（`ysu-auth`）**：封装校园网 Portal（`auth1.ysu.edu.cn`）与统一身份认证 CAS（`cer.ysu.edu.cn`）的登录、下线、运营商切换、套餐查询及设备自助服务（`/self`）。
- **串行任务调度（`src-tauri`）**：原生后台 Worker 串行处理手动操作、断线自动重连、零流量换号与无感自动续约，通过文件锁避免多进程并发冲突，并向前端推送状态快照。
- **后台只读状态观察**：即使未开启自动重连，后台也会以 30 秒周期轻量检测在线状态；窗口恢复可见或系统网络变化时自动触发刷新，实时同步连接状态与当前运营商。
- **独立结果核验**：登录、下线、切换运营商与切换账号均以操作后的独立状态查询为准，只有确认目标账号与运营商实际生效后才报告成功。

### 2. 设备自助服务与 7 天无感认证

侧栏「设备」页对接校园网自助服务（`auth1.ysu.edu.cn/self`）：

- **会话管理**：自助服务作为独立的 OAuth2 客户端（`custom-self`）委托统一身份认证登录；桌面端在进程内按账号隔离缓存已认证会话（30 分钟有效），避免短时间内重复触发 CAS 登录。
- **在线设备与远程下线**：读取在线设备列表（名称、类型、MAC、IP、在线时长、接入方式）、计费套餐与剩余流量；支持下线单台或全部设备，并在下线后轮询复核列表确认生效。
- **7 天无感认证控制**：支持查看账号下全部 7 天无感认证记录（MAC、设备名、到期时间），一键为本机或在线设备开启 7 天无感认证（`/self/setting/noSense`）、取消无感绑定（`/self/mac/unbind`）及修改默认上网服务（`/self/setting/net`）。
- **到期前自动续约與多账号协同**：
  - 自动续约规则保存在主配置同目录的 `config.nosense.json` 中，支持按账号独立配置。
  - 原生后台每 60 秒检查一次所有开启了自动续约的账号（单账号网络查询间隔 30 分钟）；当检测到目标 MAC 的无感认证距离到期不足 24 小时或已过期时，自动执行「解绑 → 重新绑定 7 天」。
  - 手动切换账号或触发零流量自动换号时，后台在下线旧账号前自动解绑旧账号上的本机 MAC 无感认证，并在新账号上线后自动为新账号绑定本机无感认证及迁移续约规则。

### 3. 验证码自动识别与 DNS 容错

- **离线验证码识别**：当 CAS 要求输入四位图形验证码时，若本地已下载 `common.onnx` 模型（可在「设置 → 认证与重试 → 验证码识别」一键下载并自动校验 SHA256），客户端直接通过内置 `tract-onnx` 引擎本地识别填充；验证码不匹配时最多自动换图重试 3 次，密码错误则立即停止。
- **DNS 备用 IP 回退**：当校园网 DNS 解析缓慢（超过 500ms）或失败时，自动对 `auth1.ysu.edu.cn` 与 `cer.ysu.edu.cn` 使用内置备用 IP 建立 TCP 连接，同时完整保留原域名的 HTTP Host、TLS SNI 与 HTTPS 证书校验。
- **可选浏览器模式**：默认使用纯 Rust HTTP API；若切换为「浏览器」模式，Rust 通过私有匿名管道（`--remote-debugging-pipe`）调用本机 Edge 或 Chrome，不开放任何本地调试端口。

### 4. 系统托盘與开机自启

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
