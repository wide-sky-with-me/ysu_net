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

自 **v0.2.0** 起，桌面采用 Tauri，独立 Python CLI 同步版本。下载[对应版本 Release](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.0)的附件；发布流程要求四平台构建、原生和安装验收全部成功，实际结果以对应 CI 运行为准。`v0.1.0` 的 Qt 附件和旧测试标签保留历史，不覆盖，也不作为新版下载入口。源码复现以对应标签为准，新开发以 `main` 为基线。

安装和本地诊断可在校外完成，登录与校园网状态查询需要接入校园网。API 是默认认证方式，浏览器方式是可选能力。缺少流量字段时显示“门户未提供”，不代表额度为零或不限量。

## 社区入口

[使用问答](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a) · [改进想法](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/ideas) · [版本公告](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/announcements) · [故障反馈](https://github.com/wide-sky-with-me/ysu_net/issues/new/choose)

公开资料只保留复现所需信息。真实账号、密码、会话、Cookie、Token、IP/MAC、个人资料、配置、HAR 与原始认证材料留在本机；分享前先看 [隐私与反馈](Privacy-and-Reporting.md)。

本导航的审查源位于 [docs/wiki](https://github.com/wide-sky-with-me/ysu_net/tree/main/docs/wiki)，详细说明位于 [docs](https://github.com/wide-sky-with-me/ysu_net/tree/main/docs)。
