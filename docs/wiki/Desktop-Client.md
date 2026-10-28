# 桌面客户端（Windows / Linux / macOS）

[返回导航](Home.md) · [排障](Troubleshooting.md) · [隐私与反馈](Privacy-and-Reporting.md)

## 安装与版本选择

桌面采用 Tauri 2 + Svelte + Rust，三平台共用界面和认证后台，不需要 Python、Node 或 Playwright 认证运行时；Linux Python CLI 是独立产品。正式附件从 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 选择对应系统、架构的安装包并核对 `SHA256SUMS`。

当前正式版本、源码与候选的区别只在[发行状态](https://github.com/wide-sky-with-me/ysu_net/blob/main/README.md#发行与候选状态)维护，本页不另标 Latest；同版本不等于同构建，合入主分支也不是发布新版。实际成绩见[桌面验收导航](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/desktop-acceptance.md)。开发版编译、打包与产品测试只在[独立构建分支的 GitHub Actions](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提)进行，不回退本机编译。

| 系统 | 选择与限制 |
| --- | --- |
| Windows 10 / 11 x64 | 当前用户 NSIS 安装，使用系统 WebView2；旧 Qt Inno 版不会被自动替换，先关闭旧自启、退出并卸载旧版。 |
| Ubuntu 22.04 及更新，x86_64 | 使用 `.deb`，包名 `ysu-net`；按系统包方式升级，不使用软件内原位安装或差分。 |
| macOS 13.5 及更新 | Apple 芯片与 Intel 分别选择 arm64 / x64 `.dmg`，不是通用二进制；先退出程序再替换应用。 |

更新包签名不等于 Windows Authenticode 发布者签名或 Apple 签名 / 公证；当前系统发布者签名限制见[迁移说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md)。0.2.0 和旧 0.2.1 候选需[手动安装正式版](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md#桌面-v021-及旧候选包)，不要等待同版本自动升级或关闭验签。旧 Qt 标签与附件只保留历史。

## 连接与日常使用

![浅色主题的连接页](https://raw.githubusercontent.com/wide-sky-with-me/ysu_net/main/docs/screenshots/desktop-connection-light.png)

截图来自 v0.2.3 云端浏览器验收，使用合成数据；来源与摘要见[截图说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/screenshots/README.md)，不作为真实登录证据。

1. 在“设置 → 校园网账号”保存账号密码和对应服务，默认使用 API 认证。
2. 回到“连接”页发起连接，待操作结束后查看独立查询的状态与实际服务。
3. 需要后台重连时再开启“自动重连”；仅查询状态或账户信息无需先断开连接。

未知不等于离线；缺失流量不是零或不限量，也不补造余额。多账号、热切换与可选零流量换号见[账号说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/accounts.md)，不要同时运行桌面和 CLI 两套重连器。

托盘可打开窗口、查询、连接 / 断开和停止自动化；无可用托盘时关闭窗口会退出。退出停止本客户端重连，不主动下线已建立连接。平台托盘差异与完整行为见[运行语义](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#运行语义)。桌面可选浏览器模式使用本机 Edge / Chrome，不需要 CLI 的 Python 浏览器依赖。

连接光环呈现核心已确认的在线状态，不表示网速、认证成功回执或正在查询；减少动效会暂停相关装饰。反馈浮层不改变业务结果与忙碌准入，具体交互见[设计说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/rust-desktop-design.md)。

## 检查更新

自 0.2.2 起，更新入口在侧栏“关于”，该页还离线展示随包日志与公开项目资料；0.2.1 的入口在“设置 → 外观与启动”底部。打开页面本身不检查或下载更新，须主动点击并确认；Demo / 普通网页不执行真实更新。

0.2.1 正式客户端只支持签名整包；自 0.2.2 起具备条件差分能力，仍须发布清单有合适补丁且本机缓存精确匹配，无基线首更下载整包。0.2.3 当次没有差分附件，下载整包是正常行为。旧 0.2.1 客户端不会因新清单有补丁就获得差分能力。差分只还原完整安装包，后续仍走原安装器覆盖流程；补丁与还原整包均按原公钥和受签名版本验证，失败仅下载阶段最多回退一次整包，不因安装失败再装一遍。缓存、信任和失败处理只在[软件更新说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/updates.md)维护。

共用 Rust 认证库已在 21 完成真实登录 / 退出，Windows 原生探针完成无凭据查询；它们不覆盖 Windows GUI 新登录、Worker 账号池或跨版本原位升级。实际范围见[验收导航](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/desktop-acceptance.md)，遇到问题先看[排障](Troubleshooting.md)，公开反馈前人工脱敏。
