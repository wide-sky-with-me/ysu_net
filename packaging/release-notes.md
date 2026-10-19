## YSU Net（下一版本草稿）

<!-- 打标签前把上面的标题改为 `## YSU Net vX.Y.Z`；发布任务只接受与标签一致的标题。 -->

桌面客户端改为 Tauri 2 + Rust，Windows、Linux、macOS 共用同一套界面与认证实现，不再依赖 Python、Node 或 Playwright。原 Qt 客户端（`v0.1.0` 附件、`ysu-gui`）停止维护。

### 主要变化

- 认证、自动重连、运营商切换与多账号热切换由 Rust 原生后台执行；登录、切换以独立状态查询确认，未知状态不自动登录。
- 可选零流量自动换号：门户连续报告零剩余流量时才尝试备用账号，缺失流量不猜测。
- 浏览器认证经私有管道驱动本机 Edge / Chrome，不开放本机调试端口。
- 界面改为参考 Linear 的中性风格，提供浅色 / 深色与六种主题色。

### 安装与升级

| 系统 | 文件 |
| --- | --- |
| Windows 10 / 11 x64 | NSIS 安装程序（当前用户安装，无需管理员）；安装前先卸载旧 Qt 版 |
| Ubuntu 22.04 及更新，x86_64 | `.deb`；与旧包同名，同版本替换用 `sudo apt install --reinstall` |
| macOS 13.5 及更新 | `.dmg`（Apple 芯片与 Intel 分别提供），拖入“应用程序” |
| Python / Linux 命令行 | wheel、源码包，或按 README 从源码安装 |

安装包未签名：Windows 可能提示未知发布者，macOS 首次打开可能需要在“系统设置 → 隐私与安全性”中允许。附件的 SHA-256 摘要见 `SHA256SUMS`。

### 验证范围

CI 在四个平台运行 Rust 与前端测试、真实 Chrome 认证夹具、原生窗口冒烟，并实际安装、启动、卸载安装包。发布前需补充校内真实认证结果；CI 检查不等于校园网全场景验证。

### 反馈

用法问答见 [Discussions](https://github.com/wide-sky-with-me/ysu_net/discussions)，可复现故障见 [Issues](https://github.com/wide-sky-with-me/ysu_net/issues/new/choose)。公开前移除账号、密码、会话、设备地址和本机路径。
