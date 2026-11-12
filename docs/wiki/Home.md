# YSU Net 使用指南

欢迎使用 **YSU Net** 燕山大学校园网连接与管理工具。本 Wiki 提供快速上手、桌面端与命令行操作指南及常见问题排障。

## 选择你的使用方式

- **Windows / Linux / macOS 桌面客户端（最新正式版 `v0.3.2`）**：采用圆润卡片、状态柔光与弹性微交互界面（支持浅色/深色与 6 套主题强调色），内置系统托盘驻留、开机自启与软件内签名更新（Windows / macOS），直接前往 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载对应安装包即可使用，无需配置 Python 环境。
- **Linux 命令行与后台守护 (`ysu`)**：适合 Linux 桌面、服务器、WSL 与 SSH 终端，通过 `bash install.sh` 安装，支持 `systemd` 后台自动重连与无感认证自动续约。

> 同一台设备上请只开启桌面端或命令行其中一套后台自动重连，避免两个程序同时竞争登录。

## 核心功能导航

- **[快速开始](Quick-Start.md)**：3 分钟完成桌面客户端或 Linux 命令行的首次安装与校园网连接。
- **[桌面客户端指南](Desktop-Client.md)**：连接控制、套餐流量查询、在线设备管理、**7 天无感认证与到期自动续约**、多账号池切换及外观设置。
- **[命令行速查](CLI-Reference.md)**：`ysu` 日常连接、`ysu self` 无感认证与自动续约、`ysu account` 多账号池等高频终端命令速查（完整手册见 [docs/usage.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)）。
- **[常见问题排障](Troubleshooting.md)**：登录失败、已连接却无法上网、无感认证换号冲突、验证码挑战与服务异常的排查方法。
- **[隐私与反馈](Privacy-and-Reporting.md)**：提交 Issue / Discussion 前的脱敏注意事项与反馈入口。
- **[参与贡献](Contributing.md)**：参与文档完善、问题复现与代码贡献的协作说明。
