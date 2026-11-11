# 无界面认证验证探针

[返回首页](../README.md) · [文档导航](README.md) · [Tauri 桌面说明](tauri-desktop.md) · [开发说明](development.md)

[`ysu-auth-probe`](../desktop/crates/ysu-auth/examples/auth_probe.rs) 是基于桌面端 `ysu_auth::AuthClient` 构建的无界面命令行验证工具，用于在无需启动 Tauri 窗口或 WebView 的环境下，直接验证 Rust 认证核心的在线查询、登录与下线流程。

---

## 支持的子命令

| 命令 | 作用 | 成功条件 |
| --- | --- | --- |
| `ysu-auth-probe status` | 查询当前校园网在线状态（可不提供账号密码） | 在线返回退出码 `0`，明确离线返回 `1` |
| `ysu-auth-probe login` | 从离线状态执行登录并核验 | 登录前确认离线，登录后以新会话独立查询确认在线且账号/运营商与配置一致 |
| `ysu-auth-probe logout` | 从在线状态执行下线并核验 | 下线前确认目标账号在线，下线后以新会话独立查询确认已离线 |

---

## 输入与输出约定

- **标准输入（`stdin`）**：从关闭后的标准输入管道读取一份 JSON 配置（上限 64 KiB），不通过命令行参数传递密码，也不会修改本机已保存的配置文件。
- **标准输出（`stdout`）**：输出单行脱敏 JSON（包含 `action`、`phase`、`outcome`、`code`、前后状态布尔证明与固定错误分类），不包含账号、密码、IP、Cookie 或门户原始文本。

### 调用示例

只读状态查询（Linux / macOS）：

```bash
printf '%s\n' '{"backend":"api","verify_tls":true,"operation_timeout":20}' | ./ysu-auth-probe status
```

Windows PowerShell：

```powershell
'{"backend":"api","verify_tls":true,"operation_timeout":20}' | .\ysu-auth-probe.exe status
```

---

## 云端工作流

独立的 [Headless Rust authentication](../.github/workflows/rust-auth.yml) 工作流会在 Linux x64、Windows x64、macOS arm64 与 macOS x64 四个平台上运行 `ysu-auth` 单元测试、`auth_probe` 示例测试与二进制冒烟校验，并生成跨平台探针产物。
