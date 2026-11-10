# 桌面 v0.2.8 发布

日期：2026-11-10。状态：正式发布并成为 Latest；四个桌面平台构建、原生安装验收与独立浏览器验收通过，Python 分发包与摘要随附。本页只记录该标签的源码、产物与门禁，不把后续主分支提交算进本版本。

当前行为归[桌面语义](tauri-desktop.md)，发布内容原文见[发布说明](../packaging/release-notes.md)，历史版本导航见[桌面验收](desktop-acceptance.md)。

## 源码与产物

标签 `v0.2.8` 的版本号在 `pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/Cargo.toml`、`desktop/crates/ysu-auth/Cargo.toml` 与 `tauri.conf.json` 中一致。发布作业先通过四个平台构建、原生安装验收、独立浏览器验收与 Python 回归，再由 `release` 作业汇总附件。

| 附件 | 说明 |
| --- | --- |
| `YSU-Net_0.2.8_windows-x64-setup.exe` | 当前用户 NSIS 安装包，附 `.sig` |
| `YSU-Net_0.2.8_linux-x64.deb` | Debian / Ubuntu 系统包 |
| `YSU-Net_0.2.8_macos-arm64.dmg` / `macos-x64.dmg` | 两个 macOS 架构的磁盘映像 |
| `YSU-Net_0.2.8_macos-arm64.app.tar.gz` / `macos-x64.app.tar.gz` | 软件内更新载荷，各附 `.sig` |
| `ysu_net_login-0.2.8-py3-none-any.whl` / `.tar.gz` | 独立 Python CLI 分发 |
| `latest.json`、`SHA256SUMS` | 更新清单与摘要 |

沿用 0.2.1 的正式更新公钥，不更换信任锚；Windows / macOS 的软件内更新支持完整包（及云端达到收益阈值时的签名差分补丁）。

## 本版内容

### 自助服务修复与协议补强

- **前端快照解析修复**：修复 0.2.7 中 `parseSnapshot` 遗漏 `self_service`、`self_error` 与 `self_notice` 字段导致桌面端“设备”页读取后无法展示数据或错误提示的问题，并补齐前端单元测试、Playwright 浏览器验收与四平台原生运行器冒烟断言。
- **进程级会话缓存与账号隔离**：桌面端 `ysu-auth` 的自助服务会话缓存改为进程级静态表，跨任务复用 30 分钟 TTL；在保存账号配置、热切换账号、保存或删除账号簿条目及退出登录时，主动清理对应会话缓存与页面快照。
- **委托 CAS 登录跳转链补强**：`selfservice.rs` 与 `selfservice.py` 同步支持跨 `auth1` / `cer` 的多步 HTTPS 重定向、已有 CAS 会话时的免表单直接回调、301/302/303/307/308 状态码及 `/self` 终点校验，严格限制 HTTPS 与 `{portal_host, cas_host}` 主机白名单。

### 界面与终端体验优化

- **桌面“设备”页**：空状态与错误状态移出内层分区卡片并独立居中，区分未配置账号引导与读取失败提示；每台设备同时展示类型与名称（如“电脑 · 我的设备”）、固定首行右侧“下线”按钮及 4 列元数据网格；新增独立“套餐与自助设置”摘要卡（遍历全部流量项与免登录有效期），补齐窄视口响应式列数与高对比度模式边框。
- **CLI `ysu self`**：去除重复的“自助服务”标题行，区分查询与下线进度提示，并在流量行补充显示门户流量项名称。

## 门禁结果

| 检查 | 结果 |
| --- | --- |
| 云端 `cargo test`（`ysu-auth` + `ysu-net`） | 通过，含跨站跳转、已登录 CAS 免表单回调、快照字段与会话缓存测试 |
| 云端 `npm run check`（svelte-check + tsc） | 0 错误 0 警告 |
| 云端 `npm test` | 14 个文件 288 项通过 |
| 云端 `browser-acceptance` | 10 套件全部通过，含设备页渲染截图 `devices-light.png` 与下线后列表核验 |
| 云端四平台原生构建与安装冒烟 | Linux x64、Windows x64、macOS arm64、macOS x64 全部通过 |
| 云端 Python 回归（`Mock tests`） | 51 项测试、wheel 构建与地址表校验全部通过 |
| 云端社区与链接检查（`Community documents`） | 通过 |

## 验证范围

- 云端门禁已覆盖“设备”页的数据解析、列表渲染、独立套餐摘要卡、下线确认与列表收缩（`2 台在线` → `1 台在线`），以及四平台原生运行器的 `self_service` / `self_kick` IPC 往返。
- 真实校园网环境下的桌面端“设备”页读取与非本机设备下线仍待在校园网现场记录。
