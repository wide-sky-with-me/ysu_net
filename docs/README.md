# 文档导航

[返回首页](../README.md) · [快速开始](wiki/Quick-Start.md) · [桌面客户端](wiki/Desktop-Client.md) · [命令与配置](usage.md) · [排障指南](wiki/Troubleshooting.md)

本目录汇总 **YSU Net** 的使用指南、功能说明与开发文档。

## 用户指南

| 文档 | 内容概览 |
| --- | --- |
| [Wiki 首页](wiki/Home.md) | 首次安装选择、核心流程与常用文档入口 |
| [快速开始](wiki/Quick-Start.md) | 桌面客户端与 Linux 命令行的三步安装与连接教程 |
| [桌面客户端指南](wiki/Desktop-Client.md) | 连接、账户、设备管理、7 天无感认证、自动续约、设置与托盘操作说明 |
| [命令与配置完整手册](usage.md) | `ysu` 全部子命令、无感认证与自助服务命令、配置文件字段、环境变量与 systemd 服务管理 |
| [CLI 速查表](wiki/CLI-Reference.md) | 终端高频命令、退出码与常用排障指令速查 |
| [多账号池、流量换号与无感联动](accounts.md) | 多账号管理、手动热切换、零剩余流量自动轮换，以及多账号下的无感认证交接与独立续约 |
| [常见问题排障](wiki/Troubleshooting.md) | 登录失败、假在线、无感认证冲突、DNS 异常、浏览器模式与 systemd 守护排查步骤 |
| [桌面链路调试记录](debug-recording.md) | 在桌面端「日志」页开启本地脱敏诊断记录并导出排查文件的方法 |
| [软件内签名更新](updates.md) | Windows / macOS 软件内更新检查、Minisign 签名校验与差分更新说明 |
| [更新、卸载与旧版迁移](migration.md) | 桌面版与命令行版升级步骤、卸载方法及早期版本迁移指南 |

## 架构与开发

| 文档 | 内容概览 |
| --- | --- |
| [产品形态与系统架构](architecture.md) | Rust 桌面端与 Python CLI 的模块划分、配置共享、认证流程与安全边界 |
| [Tauri 原生桌面版说明](tauri-desktop.md) | 桌面后台运行器、门户与自助服务协议、无感认证续约调度、构建环境与验证方法 |
| [桌面界面设计规范](rust-desktop-design.md) | 视觉层级、色彩主题、响应式布局、交互动效与无障碍设计规则 |
| [无界面认证验证探针](rust-auth-probe.md) | 使用 `ysu-auth-probe` 独立验证 Rust 认证核心的输入输出约定 |
| [开发与测试说明](development.md) | 代码目录结构、单元测试、代码规范与 GitHub Actions 持续集成流程 |
| [界面截图说明](screenshots/README.md) | 文档演示截图的生成来源与校验摘要 |

## 社区与隐私

| 文档 | 内容概览 |
| --- | --- |
| [隐私与脱敏规则](security.md) | 本地凭据保护方式与公开提交 Issue / Discussion 前的脱敏检查清单 |
| [隐私与反馈渠道](wiki/Privacy-and-Reporting.md) | 问题反馈、功能建议、问答与私密安全报告的渠道选择 |
| [参与贡献](wiki/Contributing.md) | 提交 Issue、PR 与改进文档的协作指引（完整约定见 [CONTRIBUTING.md](../CONTRIBUTING.md)） |
| [社区入口与 Wiki 维护](community-maintenance.md) | Issue 表单静态检查与 `docs/wiki/` 同步至 GitHub Wiki 的维护步骤 |
