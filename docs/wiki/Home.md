# ysu-net 使用导航

社区维护的燕山大学校园网管理工具，提供独立 Linux Python 命令行与 Windows / Linux / macOS Tauri 桌面客户端。本页是入门导航，详细行为以安装版本对应的文档为准；本项目不是学校或运营商的官方服务。

## 从这里开始

| 你的环境或目标 | 文档 |
| --- | --- |
| 第一次安装，选择版本 | [快速开始](Quick-Start.md) |
| Windows / Linux / macOS 桌面客户端 | [桌面客户端](Desktop-Client.md) |
| Linux、服务器、systemd 或前台守护 | [命令行入口](CLI-Reference.md) |
| 安装、连接、重连或状态异常 | [排障与已知问题](Troubleshooting.md) |
| 分享反馈、日志或截图 | [隐私与反馈](Privacy-and-Reporting.md) |
| 文档、测试或代码贡献 | [参与贡献](Contributing.md) |

## 先分清版本

正式 **v0.2.1** 已发布，下载以 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 为准；版本与来源的区别见[首页发行状态](https://github.com/wide-sky-with-me/ysu_net/blob/main/README.md#发行与候选状态)。当前 `main` / 开发源码仍可能标识为 0.2.1，但包含“关于”、差分下载、光环与反馈浮层等正式版之后的改进；合入主分支或 CI 成功不等于发布新版，也不保证已安装正式包包含这些变化。自 0.2.0 起桌面已由 Qt 迁移为 Tauri；旧 Qt 标签与附件仅保留历史，不作为当前下载入口。

安装和本地诊断可在校外完成，登录与校园网状态查询需要接入校园网。API 是默认认证方式；桌面可选本机 Edge / Chrome，CLI 的浏览器依赖独立安装。缺少流量时显示“门户未提供”，不代表零额度或不限量。编译、打包和产品测试只在 GitHub Actions 执行，本机不回退编译；需要开发版请先看[云端构建路线](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提)。

## 社区入口

[使用问答](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a) · [改进想法](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/ideas) · [版本公告](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/announcements) · [故障反馈](https://github.com/wide-sky-with-me/ysu_net/issues/new/choose)

公开资料只保留复现所需信息。真实账号、密码、会话、Cookie、Token、IP/MAC、个人资料、配置、HAR 与原始认证材料留在本机；分享前先看 [隐私与反馈](Privacy-and-Reporting.md)。

本导航的审查源位于 [docs/wiki](https://github.com/wide-sky-with-me/ysu_net/tree/main/docs/wiki)，详细说明位于 [docs](https://github.com/wide-sky-with-me/ysu_net/tree/main/docs)。
