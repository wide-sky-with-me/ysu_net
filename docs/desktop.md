# 图形界面客户端（Windows / Ubuntu）

[返回首页](../README.md) · [使用与配置](usage.md) · [开发与验证](development.md)

图形界面版与命令行版共用认证实现、运营商切换和自动重连逻辑，只是换了一种操作方式。
Linux 服务器或无桌面环境继续使用 `ysu` 命令行和 systemd 服务，两者互不替代。

| 版本 | 适用环境 | 获取方式 |
| --- | --- | --- |
| Windows 图形界面 | Windows 10 / 11（x64） | `YSU-Net-<版本>-windows-setup.exe` 安装程序，或 `-windows-portable.zip` 免安装版 |
| Ubuntu 图形界面 | Ubuntu 22.04 及更新（x86_64，GNOME） | `ysu-net_<版本>_amd64.deb`，或 `-linux-x86_64.tar.gz` |
| Linux 无界面版 | 任意 systemd Linux / 前台运行 | `bash install.sh`，见[首页](../README.md) |

安装包由 GitHub Actions 在对应系统上构建：推送 `v*` 标签后发布到 Releases，
手动运行 “Desktop builds” 工作流时可在运行记录的 Artifacts 下载。

## 安装

**Windows**：运行安装程序即可，不需要管理员权限，程序装在当前用户目录。首次运行时，
SmartScreen 可能提示“未知发布者”（安装包没有代码签名），点击“更多信息 → 仍要运行”。

**Ubuntu**：

```bash
sudo apt install ./ysu-net_0.1.0_amd64.deb
```

安装后可在应用列表中找到 “YSU Net”，也可以在终端执行 `ysu-gui` 启动。
卸载：`sudo apt remove ysu-net`。

**从源码运行**（两个系统通用，需要 uv）：

```bash
uv sync --locked --extra gui
uv run ysu-gui
```

## 功能

- **概览**：连接状态、IP、当前运营商；一键连接或断开。
- **运营商**：离线时，选择的服务用于下次登录；在线时选择其他运营商会立即切换，并独立确认结果，失败时尝试恢复原连接（与 `ysu switch` 相同）。
- **自动重连**：断线时自动登录，失败后按间隔退避重试；账号密码错误等需要人工处理的情况会暂停重试。
- **账户**：剩余流量、套餐与余额，按门户原文展示。
- **设置**：账号密码、认证参数、HTTPS 证书校验、开机自启、关闭窗口后驻留托盘、浅色 / 深色外观。
- **托盘**：图标颜色表示在线状态；右键菜单可以连接、断开或切换自动重连。
- **日志**：记录本次运行期间的操作结果，不含密码和服务器原始响应。

开启“登录系统后自动启动”和“自动重连”后，登录系统即可自动联网。
Windows 通过当前用户注册表的 `Run` 项自启，Ubuntu 通过 `~/.config/autostart/ysu-net.desktop` 自启；
两者都在用户登录桌面后才运行。需要在未登录时也保持在线的 Linux 机器，请改用 systemd 服务（`ysu on`）。

## 配置与数据

| 系统 | 配置目录 |
| --- | --- |
| Windows | `%APPDATA%\ysu-net\` |
| Ubuntu | `${XDG_CONFIG_HOME:-~/.config}/ysu-net/` |

`config.json` 与命令行版格式相同，同一台 Linux 机器上的 `ysu` 和图形界面读写的是同一份配置。
`gui.json` 只保存界面偏好（外观、托盘、上次是否开启自动重连）。
账号密码保存在本机配置文件中，与命令行版一样，不会上传。

同一份配置同一时间只能由一个自动重连进程管理：如果 `ysu on` 或 `ysu daemon` 已在运行，
界面中的自动重连开关会显示为由后台服务管理，登录和下线按钮也会提示先执行 `ysu stop`。

## 限制

- 浏览器认证直接调用本机已安装的 Microsoft Edge 或 Google Chrome（无窗口运行），不需要额外下载 Chromium。
  Windows 10 / 11 自带 Edge；Ubuntu 需要安装 Chrome 或 Edge 的 .deb 版本，Snap 版 Chromium 受沙箱限制无法使用，Firefox 不支持。
  也可以用环境变量 `YSU_BROWSER_PATH` 指定浏览器路径。
- Ubuntu 默认的 GNOME 桌面通过 AppIndicator 扩展显示托盘图标（Ubuntu 默认启用）。托盘不可用时，关闭窗口会直接退出程序。
- CI 会在 GitHub 的 Windows 和 Ubuntu 虚拟机上安装安装包、启动程序并截图，并用系统浏览器完成浏览器认证自检；
  虚拟机无法接入校园网，所以真实登录仍需在校内验收。Windows 版目前还没有在校园网环境里实际验收。

## 界面截图

`uv run python packaging/screenshots.py` 会用模拟数据渲染所有页面，不访问网络、不修改真实配置。
CI 的 `screenshots-*` 产物还包括在真实 Windows / Ubuntu 桌面上启动安装版程序后的整屏截图。
