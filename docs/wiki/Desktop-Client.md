# 桌面客户端（Windows / Linux / macOS）

[返回导航](Home.md) · [排障](Troubleshooting.md) · [隐私与反馈](Privacy-and-Reporting.md)

## 安装与版本选择

桌面采用 Tauri 2 + Svelte + Rust，三平台共用界面和认证后台，不需要 Python、Node 或 Playwright 认证运行时；Linux Python CLI 是独立产品。正式 **v0.2.1** 从 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载对应系统、架构的附件并核对 `SHA256SUMS`。

当前开发源码仍标识 0.2.1，包含正式包之后的“关于”、差分、连接光环和反馈浮层；同版本不等于同构建，合入主分支也不是发布新版。来源与实际成绩分别见[发行状态](https://github.com/wide-sky-with-me/ysu_net/blob/main/README.md#发行与候选状态)和[桌面验收导航](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/desktop-acceptance.md)。开发版编译、打包与产品测试只在[独立构建分支的 GitHub Actions](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提)进行，不回退本机编译。

| 系统 | 选择与限制 |
| --- | --- |
| Windows 10 / 11 x64 | 当前用户 NSIS 安装，使用系统 WebView2；旧 Qt Inno 版不会被自动替换，先关闭旧自启、退出并卸载旧版。 |
| Ubuntu 22.04 及更新，x86_64 | 使用 `.deb`，包名 `ysu-net`；按系统包方式升级，不使用软件内原位安装或差分。 |
| macOS 13.5 及更新 | Apple 芯片与 Intel 分别选择 arm64 / x64 `.dmg`，不是通用二进制；先退出程序再替换应用。 |

更新包签名不等于 Windows Authenticode 发布者签名或 Apple 签名 / 公证；当前系统发布者签名限制见[迁移说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md)。0.2.0 和旧 0.2.1 候选需[手动安装正式版](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md#桌面-v021-及旧候选包)，不要等待同版本自动升级或关闭验签。旧 Qt 标签与附件只保留历史。

## 连接与日常使用

在“设置 → 校园网账号”保存账号密码，默认 API 认证；回到“连接”页发起连接，再独立查看状态。未知不等于离线，账户查询不要求先重登；缺失流量不是零或不限量，也不补造余额。多账号、热切换与可选零流量换号见[账号说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/accounts.md)，不要同时运行桌面和 CLI 两套重连器。

托盘可打开窗口、查询、连接 / 断开和停止自动化；无可用托盘时关闭窗口会退出。退出停止本客户端重连，不主动下线已建立连接。平台托盘差异与完整行为见[运行语义](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#运行语义)。桌面可选浏览器模式使用本机 Edge / Chrome，不需要 CLI 的 Python 浏览器依赖。

开发树的光环只是核心已确认在线的装饰，不表示网速、认证成功回执或正在查询；减少动效会暂停相关装饰。浮层不改变业务结果与忙碌准入，具体交互见[设计说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/rust-desktop-design.md)。

## 检查更新

正式 0.2.1 的入口在“设置 → 外观与启动”底部；开发树移到侧栏“关于”，同时离线展示随包日志与公开项目资料。打开页面本身不检查或下载更新，须主动点击并确认；Demo / 普通网页不执行真实更新。

正式 0.2.1 采用签名整包覆盖升级；开发树在有平台、版本和摘要精确匹配的缓存时才可差分，首次无基线仍下载整包。差分只还原完整安装包，不直接修补已安装目录，后续仍走原安装器覆盖流程。补丁与还原整包都沿用原公钥及受签名版本验签；差分失败仅下载阶段最多回退一次整包，不因安装失败再装一遍。缓存、信任和失败处理只在[软件更新说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/updates.md)维护。

云端四平台、离线夹具和普通安装的成绩不等于真实校园网登录、跨版本原位升级或失败回滚通过；只按[对应验收记录](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/desktop-acceptance.md)判断范围。遇到问题先看[排障](Troubleshooting.md)，公开反馈前人工脱敏。
