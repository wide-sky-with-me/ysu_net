# 桌面 v0.2.7 发布

日期：2026-11-10。状态：已由 [0.2.8](desktop-release-0.2.8.md) 接替；四个桌面平台构建、原生安装验收与独立浏览器验收通过，Python 分发包与摘要随附。本页只记录该标签的源码、产物与门禁，不把后续主分支提交算进本版本。

当前行为归[桌面语义](tauri-desktop.md)，发布内容原文见[发布说明](../packaging/release-notes.md)，历史版本导航见[桌面验收](desktop-acceptance.md)。

## 源码与产物

标签 `v0.2.7` 指向提交 `b1bcb44`，版本号在 `pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/Cargo.toml`、`desktop/crates/ysu-auth/Cargo.toml` 与 `tauri.conf.json` 中一致。发布作业先通过四个平台构建、原生安装验收、独立浏览器验收与 Python 回归，再由 `release` 作业汇总附件。

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
| [Tauri 42752804815](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42752804815) | preflight、四个平台构建与安装验收、`browser-acceptance`、`release` 全部成功；13 个公开附件 |
| [Mock 42752805056](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42752805056) | Python 回归、分发构建与 wheel 数据检查成功 |
| [Community 42752804818](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42752804818) | 社区文档、链接与表单检查成功 |

同标签的前三次运行不是通过成绩，保留作为修正依据：

| 运行 | 失败点 | 修正 |
| --- | --- | --- |
| [42748937221](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42748937221) | `uv sync --locked` 报 lockfile 需要更新 | `pyproject.toml` 改版本后未重新生成 `uv.lock`，已补 `uv lock` |
| [42750030258](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42750030258) | `rust_desktop_preview.py` 等不到设置页 tablist | 新增“设备”导航项使 Ctrl+数字 按数组下标漂移，改为每个页面固定 `key` |
| [42751744507](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42751744507) | `multi_account_preview.py` 在 320px 报 `document_overflow` | 六项导航在窄视口放不下，≤420px 只保留图标 |
| [42752804815](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42752804815) 的首轮提交前 | 同上，`get_by_role(button, name="设置")` 超时 | 用 `display: none` 隐藏文字会剥离可访问名称，改为 1px 视觉隐藏 |

这些失败经定位修正后重推标签，最终在云端门禁一次通过。

## 验证范围

云端门禁与本机实测覆盖的检查：

| 检查 | 结果 |
| --- | --- |
| 云端 `cargo test`（`ysu-auth`） | 通过，含新增的设备选择与解析测试 |
| 云端 `npm run check`（svelte-check + tsc） | 0 错误 0 警告 |
| 云端 `npm test` | 14 个文件 286 项通过 |
| 云端 Python 回归 | `Mock 42752805056` 全量通过 |
| 云端 `rustfmt --check` | 通过 |
| CLI 真实账号只读查询 | 通过；设备、套餐、流量、记住的上网选择均与门户一致 |
| 窄视口布局（320 / 390 / 700 px） | 通过：无横向溢出，六个导航项均可用可访问名定位，见 `browser-acceptance` |
| 真实设备下线 | **部分**：手机已确认下线（在线 2 → 1 台），但那次核验逻辑有缺陷（立即重读误报失败），修正后未再对真实设备复核 |
| 桌面端真实登录与“设备”页 | **`v0.2.7` 标签存在前端解析缺陷**：`v0.2.7`（`b1bcb44`）中 `parseSnapshot` 遗漏 `self_service` / `self_error` / `self_notice` 字段，导致桌面端“设备”页读取后无法展示数据或错误提示；后续已在主分支修复并补齐浏览器与原生冒烟断言 |

设备下线在真实设备上的完整复核与修复后桌面端“设备”页的真实网络验收仍待记录。
