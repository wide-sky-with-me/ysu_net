# 桌面 v0.2.9 发布

日期：2026-11-10。状态：正式发布并成为 Latest；四个桌面平台构建、原生安装验收与独立浏览器验收通过，Python 分发包与摘要随附。本页只记录该标签的源码、产物与门禁，不把后续主分支提交算进本版本。

当前行为归[桌面语义](tauri-desktop.md)，发布内容原文见[发布说明](../packaging/release-notes.md)，历史版本导航见[桌面验收](desktop-acceptance.md)。

## 源码与产物

标签 `v0.2.9` 指向对应发布提交，版本号在 `pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/Cargo.toml`、`desktop/crates/ysu-auth/Cargo.toml` 与 `tauri.conf.json` 中一致。发布作业先通过四个平台构建、原生安装验收、独立浏览器验收与 Python 回归，再由 `release` 作业汇总附件。

| 附件 | 说明 |
| --- | --- |
| `YSU-Net_0.2.9_windows-x64-setup.exe` | 当前用户 NSIS 安装包，附 `.sig` |
| `YSU-Net_0.2.9_linux-x64.deb` | Debian / Ubuntu 系统包 |
| `YSU-Net_0.2.9_macos-arm64.dmg` / `macos-x64.dmg` | 两个 macOS 架构的磁盘映像 |
| `YSU-Net_0.2.9_macos-arm64.app.tar.gz` / `macos-x64.app.tar.gz` | 软件内更新载荷，各附 `.sig` |
| `ysu_net_login-0.2.9-py3-none-any.whl` / `.tar.gz` | 独立 Python CLI 分发 |
| `latest.json`、`SHA256SUMS` | 更新清单与摘要 |

沿用 0.2.1 的正式更新公钥，不更换信任锚；本版本共发布 13 个完整资产，Windows / macOS 的软件内更新使用完整包。

## 本版内容

### 自助服务 OAuth2 会话预热与回调修复

- **修复真实校园网下 `stage=cas_callback reason=redirect_blocked`**：0.2.8 在 Windows 实机读取“设备”页时，因未先访问 `GET /self/index` 初始化 `SESSION@/`（含 Spring Security `SavedRequest=/self/index` 与 OAuth2 `state`）及 `SESSION@/cas-sso/`，直接调用 `/cas-sso/clientredirect?service=.../login/oauth2/code/custom-self` 导致 CAS 登录回调缺少 OAuth2 `code`、丢失 `SavedRequest` 并在最终回跳 `/` → `/eportal/redirect.jsp` 时产生明文 `http://auth1.ysu.edu.cn/portal/portal-main?sessionId=...` 重定向而被阻断。
- **双端预热与导航升级**：Rust（`ysu-auth`）与 Python（`ysu_net.auth.selfservice`）统一先访问 `GET /self/index`，若已落在 `/self/*` 则直接复用会话，否则提取同源 OAuth2 `callbackAuthorize` 的 `service` 参数传给 `/cas-sso/clientredirect`，5 步纯 HTTPS 跳转直达 `/self/index`；同时将 `Stage::CasCallback` 的重定向跟随升级为 `navigation_get`（Python `cas_login` 同步升级 `/eportal/redirect.jsp` 的同源 HTTP 跳转为 HTTPS）。

### 桌面端日志与界面优化

- **错误文案与日志对齐**：修复桌面运行器在 `self_service` 与 `self_kick` 失败时向“日志”页写入连接查询通用文案（`查询未确认连接状态...`）的问题，统一使用自助服务与设备下线专属错误说明。
- **设备页与账户页交互细节**：“设备”页在多台设备在线时提供“全部下线”入口（二次确认后执行批量下线）；将空状态与内联错误中的结构化诊断后缀（`[action=...]`）与主标题分离展示，并为“设备”页补齐页面切换入场动效。

## 门禁结果

| 检查 | 结果 |
| --- | --- |
| 本机真实校园网 Shell 核验（Python `selfservice.snapshot`） | `--fresh` 首次完整登录与第二次会话缓存复用均通过（`online=1`、套餐与流量项完整返回） |
| 云端 `cargo test`（`ysu-auth` + `ysu-net`） | 通过，含 `/self/index` OAuth2 `service` 预热、会话复用及运行器自助服务错误日志测试 |
| 云端 `npm run check`（svelte-check + tsc） | 0 错误 0 警告 |
| 云端 `npm test` | 全部通过 |
| 云端 `browser-acceptance` | 10 套件全部通过 |
| 云端四平台原生构建与安装冒烟 | Linux x64、Windows x64、macOS arm64、macOS x64 全部通过 |
| 云端 Python 回归（`Mock tests`）与社区检查（`Community documents`） | 全部通过 |

## 验证范围

- 已在真实校园网环境下通过本机 Shell 验证 `GET /self/index` OAuth2 预热后的委托 CAS 登录、四个只读接口读取与会话缓存复用；桌面端共用相同协议流程并通过云端四平台构建与原生冒烟。
- 桌面端安装包的实机点击复核与非本机设备下线仍按现场使用情况记录。
