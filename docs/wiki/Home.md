# YSU Net · 燕山大学校园网客户端使用指南

**YSU Net** 是面向**燕山大学（燕大 / Yanshan University）**有线校园网与 **`iYanDa`** 无线校园网的跨平台自动认证与连接管理工具，对接锐捷认证门户（`auth1.ysu.edu.cn`）、统一身份认证（`cer.ysu.edu.cn`）与自助服务（`auth1.ysu.edu.cn/self`），同时提供 **桌面客户端（GUI）** 与 **Linux Shell 命令行（`ysu`）** 双版本。

> [!IMPORTANT]
> 本项目为社区维护的非官方开源工具，与燕山大学、锐捷网络及各宽带运营商无隶属或官方授权关系。请仅对本人合法持有或获授权的账号与终端使用，并遵守学校网络安全管理规定。

## 选择你的使用版本

- **桌面客户端（Windows 10/11 / Ubuntu Linux / macOS）**：采用圆润卡片、状态柔光与弹性微交互界面（支持浅色/深色与 6 套主题强调色），内置系统托盘驻留、开机自启与软件内签名更新（Windows / macOS），直接前往 [GitHub Releases Latest](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载最新安装包即可使用，无需配置 Python 环境。
- **Shell 命令行版 (`ysu`，Linux 服务器 / Ubuntu / Debian / WSL / SSH)**：纯终端交互与无桌面脚本自动化，通过 `bash install.sh` 一键安装（文档命令已内置国内 GitHub 与清华源镜像加速），支持 `systemd` 后台断网自动重连与 7 天无感认证自动续约。

> 同一台设备上请只开启桌面端或命令行其中一套后台自动重连，避免两个程序同时竞争登录。

## 核心功能导航

- **[快速开始](Quick-Start.md)**：3 分钟完成桌面客户端或 Linux 命令行的首次安装与校园网连接。
- **[桌面客户端指南](Desktop-Client.md)**：连接控制、套餐流量查询、在线设备管理、**7 天无感认证与到期自动续约**、多账号池切换及外观设置。
- **[命令行速查](CLI-Reference.md)**：`ysu` 日常连接、`ysu self` 无感认证与自动续约、`ysu account` 多账号池等高频终端命令速查（完整手册见 [docs/usage.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)）。
- **[常见问题排障](Troubleshooting.md)**：登录失败、已连接却无法上网、无感认证换号冲突、验证码挑战与服务异常的排查方法。
- **[隐私与反馈](Privacy-and-Reporting.md)**：提交 Issue / Discussion 前的脱敏注意事项与反馈入口。
- **[参与贡献](Contributing.md)**：参与文档完善、问题复现与代码贡献的协作说明。
