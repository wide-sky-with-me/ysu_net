# 桌面 v0.2.7 发布

日期：2026-11-10。状态：标签已推送，云端门禁运行中；四平台构建、安装验收、浏览器验收与 Python 分发结果待本次运行回填。本页只记录该标签的源码、产物与门禁，不把后续主分支提交算进本版本。

当前行为归[桌面语义](tauri-desktop.md)，发布内容原文见[发布说明](../packaging/release-notes.md)，历史版本导航见[桌面验收](desktop-acceptance.md)。

## 源码与产物

标签 `v0.2.7` 的版本号在 `pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/Cargo.toml`、`desktop/crates/ysu-auth/Cargo.toml` 与 `tauri.conf.json` 中一致。发布作业先通过四个平台构建、原生安装验收、独立浏览器验收与 Python 回归，再由 `release` 作业汇总附件。

| 附件 | 说明 |
| --- | --- |
| `YSU-Net_0.2.7_windows-x64-setup.exe` | 当前用户 NSIS 安装包，附 `.sig` |
| `YSU-Net_0.2.7_linux-x64.deb` | Debian / Ubuntu 系统包 |
| `YSU-Net_0.2.7_macos-arm64.dmg` / `macos-x64.dmg` | 两个 macOS 架构的磁盘映像 |
| `YSU-Net_0.2.7_macos-arm64.app.tar.gz` / `macos-x64.app.tar.gz` | 软件内更新载荷，各附 `.sig` |
| `ysu_net_login-0.2.7-py3-none-any.whl` / `.tar.gz` | 独立 Python CLI 分发 |
| `latest.json`、`SHA256SUMS` | 更新清单与摘要 |

沿用 0.2.1 的正式更新公钥，不更换信任锚；本版本没有差分附件，Windows / macOS 的软件内更新使用完整包。

## 本版内容

### 设备自助服务

门户自助服务（`auth1.ysu.edu.cn/self`）不是独立域名，而是认证门户下的一条路径，走独立的 OAuth2 客户端 `custom-self`。两端都通过 `/cas-sso/clientredirect?client_name=sidadapter&service=…/login/oauth2/code/custom-self` 委托回同一套经典 CAS 表单，因此登录、验证码与密码加密全部复用现有实现，只更换 `service`。

- 桌面端：新增侧栏“设备”页，读取在线设备、套餐、剩余流量与记住的上网选择，支持下线指定设备并核对结果。
- 命令行：新增 `ysu self [--raw]` 与 `ysu self kick <编号|all> [--yes]`。
- 会话复用：CLI 缓存登录状态到 `$XDG_CACHE_HOME/ysu-net/self-session.json`（`0600`、绑定账号与门户地址、默认 30 分钟，`--fresh` 强制重登）；桌面端用进程内缓存，退出登录即丢弃。

### 未实现

解绑 MAC、关闭无感知认证与绑定 PPSK 未实现：本校当前 `enableSelfUnbind=false`，且设备响应中没有 `macBindInfoUuid` 等可操作标识。

## 门禁结果

| 运行 | 实际结果 |
| --- | --- |
| [Tauri CI](https://github.com/wide-sky-with-me/ysu_net/actions/workflows/tauri.yml) | 待本次标签运行回填 |
| [Mock](https://github.com/wide-sky-with-me/ysu_net/actions/workflows/test.yml) | 待本次标签运行回填 |
| [Community](https://github.com/wide-sky-with-me/ysu_net/actions/workflows/community.yml) | 待本次标签运行回填 |

## 验证范围

标签构建前在本机完成的检查：

| 检查 | 结果 |
| --- | --- |
| `cargo test`（`ysu-auth`） | 144 项通过，含新增的 8 项设备选择与解析测试 |
| `npm run check`（svelte-check + tsc） | 0 错误 0 警告 |
| `npm test` | 14 个文件 286 项通过 |
| Python 回归 | 全量通过（排除 4 项既有的 `test_layout` 环境失败） |
| `rustfmt --check` | 7 个 Rust 文件通过 |
| 真实账号只读查询 | 通过；设备、套餐、流量、记住的上网选择均与门户一致 |
| 真实设备下线 | **部分**：手机已确认下线（在线 2 → 1 台），但那次核验逻辑有缺陷（立即重读误报失败），修正后未再对真实设备复核 |
| 桌面端真实登录 | **未执行**：本机为 WSL，图形界面的真实登录与下线留给使用者手动验证 |

设备下线在真实设备上的完整复核、桌面端“设备”页的人工验收，以及窄视口下的列表布局，都还没记录。
