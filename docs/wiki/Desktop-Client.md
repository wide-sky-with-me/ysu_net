# Windows / Ubuntu 桌面测试版

[返回导航](Home.md) · [排障](Troubleshooting.md) · [隐私与反馈](Privacy-and-Reporting.md)

## 下载与版本

当前发布是 [v0.1.0-beta.1](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.1.0-beta.1)，尚处于测试阶段。桌面代码未合并回 `main`。安装、配置位置、托盘与浏览器依赖以 [该标签的桌面说明](https://github.com/wide-sky-with-me/ysu_net/blob/v0.1.0-beta.1/docs/desktop.md) 为准。

| 环境 | 发布附件 |
| --- | --- |
| Windows 10 / 11 x64 | `YSU-Net-0.1.0-windows-setup.exe` 或 `YSU-Net-0.1.0-windows-portable.zip` |
| Ubuntu 22.04 及更新，x86_64 | `ysu-net_0.1.0_amd64.deb` 或 `YSU-Net-0.1.0-linux-x86_64.tar.gz` |

附件文件名中的 `0.1.0` 不代表稳定版；发行标签仍为 `v0.1.0-beta.1`。仅从本仓库的对应发布页下载。Windows 安装包尚未签名，先核对下载来源；Ubuntu `.deb` 可按版本文档安装。

## 第一次连接

在“设置”中本机输入并保存账号密码，选择服务与默认 API 认证。进入“概览”点击连接，分别观察界面状态和实际网络连通性。需要自动重连时再打开开关；重连、断开、运营商切换均会影响当前连接。流量与余额按门户原文展示，缺失字段不是零。

同一配置一次只由一个重连进程管理。Linux 的命令行后台服务已运行时，先按使用说明停止守护，再交给桌面客户端；不要同时启动两套自动重连。

## 源码体验

```bash
git clone --branch v0.1.0-beta.1 https://github.com/wide-sky-with-me/ysu_net.git ysu-net-desktop
cd ysu-net-desktop
uv sync --locked --extra gui
uv run ysu-gui
```

此处检出发布标签，用于复现对应测试版，不适合直接在分离的 HEAD 上开发提交。贡献桌面代码时见 [贡献指南](https://github.com/wide-sky-with-me/ysu_net/blob/main/CONTRIBUTING.md)。

## 已知问题与验证边界

[Issue #1](https://github.com/wide-sky-with-me/ysu_net/issues/1) 报告自动重连后实际联网、界面仍显示未连接；手动刷新后状态更新。此项尚未确认修复，可先刷新并在原帖补充脱敏复现信息。

CI 中的安装、启动与截图不等于所有校园网认证场景已验证。Windows 校内认证、浏览器认证、其他运营商和长稳情况应按真实反馈逐项确认；提交体验时写明已测与未测范围，不把测试版描述为全场景已验收。
