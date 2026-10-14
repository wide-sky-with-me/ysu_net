## YSU Net v0.1.0

命令行工具与 Windows / Ubuntu 桌面客户端整合到 `main`，原 `feat/desktop-gui` 与 `docs/community-20261014` 分支继续保留。

### 修复

- 修复 [Issue #1](https://github.com/wide-sky-with-me/ysu_net/issues/1)：自动重连完成后，概览与托盘仍显示未连接，需要手动刷新。
- 登录成功后立即独立查询并同步连接状态、运营商、连接按钮与托盘；仅确认在线后报告重连成功。
- 查询失败或异常响应保持状态未知并退避重试；已经在线时不重复登录，登录失败不额外发起确认查询。

### 功能与社区

- 桌面客户端支持浅色 / 深色外观、系统托盘、运营商切换、自动重连与登录系统后自启。
- 默认 API 认证无需浏览器组件；可选浏览器认证使用本机 Edge / Chrome，所需运行时按需下载并校验。
- 合并社区文档、Wiki 审查源、贡献 / 支持入口与脱敏反馈表单，更新主线和版本选择说明。

### 下载与升级

| 系统 | 文件 |
| --- | --- |
| Windows 10 / 11 x64 | `YSU-Net-0.1.0-windows-setup.exe`，或 `YSU-Net-0.1.0-windows-portable.zip` |
| Ubuntu 22.04 及更新，x86_64 | `ysu-net_0.1.0_amd64.deb`，或 `YSU-Net-0.1.0-linux-x86_64.tar.gz` |
| Python / Linux 命令行 | wheel、源码包，或按 README 从源码安装 |

旧测试版附件文件名也含 `0.1.0`，请从本次 **v0.1.0** 发布页下载修复后的包，而不是 `v0.1.0-beta.1`。

Windows 安装无需管理员权限；安装包未签名，系统可能显示未知发布者。Ubuntu 使用 `sudo apt install ./ysu-net_0.1.0_amd64.deb`。升级前退出旧桌面程序，既有账户配置与界面偏好仍保存在用户配置目录。

### 验证范围

新增回归先在旧实现上复现，再在修复后通过；合并后的本地离线回归共 189 项，含 Qt 窗口状态同步测试。社区链接 / 表单检查、锁文件检查、shell 语法和 Python 分发包构建按发布前流程执行。桌面安装包由 GitHub Actions 分别在 Windows / Ubuntu 构建并执行安装、启动与截图检查。

本次未新增真实校园网、所有运营商、验证码或长稳验收。历史 API / 校园网、中国移动与 systemd 验收的范围见项目文档，CI 检查不等于当前校内环境的全场景验证。

### 反馈

用法问答见 [Discussions](https://github.com/wide-sky-with-me/ysu_net/discussions)，可复现故障见 [Issues](https://github.com/wide-sky-with-me/ysu_net/issues/new/choose)。只提供版本、环境、复现步骤与最少必要提示；公开前移除账号、密码、会话、设备地址和本机路径，不上传完整配置、原始日志或认证截图。
