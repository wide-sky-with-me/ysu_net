# 文档导航

[项目首页](../README.md) · [新用户 Wiki](wiki/Home.md) · [支持与反馈](../SUPPORT.md)

## 安装与使用

| 目标 | 入口 |
| --- | --- |
| 选择桌面版或命令行版、下载安装 | [首页快速开始](../README.md#快速开始)、[Wiki 入门](wiki/Quick-Start.md) |
| 桌面连接、账户查询与托盘 | [桌面使用指南](wiki/Desktop-Client.md) |
| 命令、配置、systemd 与退出码 | [CLI 使用说明](usage.md) |
| 保存账号、手动切换与自动换号 | [多账号管理](accounts.md) |
| 软件内更新、完整包与差分条件 | [签名更新](updates.md) |
| 升级、旧 Qt / 候选包迁移及卸载 | [迁移指南](migration.md) |
| DNS、门户跳转、状态或认证异常 | [排障](wiki/Troubleshooting.md) |
| 断网前开启链路记录、离线保存调试证据 | [桌面调试记录](debug-recording.md)（开发源码，0.2.3 未提供） |
| 界面预览及截图来源 | [截图说明](screenshots/README.md)、[界面设计](rust-desktop-design.md) |

当前正式版本与开发源码的区别统一见[首页发行状态](../README.md#发行与候选状态)。使用旧版本时，以对应标签文档为准；本目录中的带日期记录保留当时结论，不作为当前能力清单。

## 实现与维护

| 主题 | 入口 |
| --- | --- |
| 产品、代码与配置边界 | [架构](architecture.md) |
| Rust 认证、状态观察、DNS 与云端构建 | [桌面运行语义](tauri-desktop.md) |
| Python 模块、回归与 CI 门禁 | [开发验证](development.md) |
| 共用 Rust 认证库的无界面验证 | [认证探针](rust-auth-probe.md) |
| 贡献流程、文档与 Wiki 同步 | [贡献指南](../CONTRIBUTING.md)、[社区维护](community-maintenance.md) |
| 脱敏、公开反馈与安全报告 | [资料规则](security.md)、[安全报告入口](../SECURITY.md) |

编译、打包和产品测试只在 GitHub Actions 执行；本机文档维护使用静态检查，具体要求见[贡献指南](../CONTRIBUTING.md#开发验证)。

## 验证记录

[桌面验收导航](desktop-acceptance.md)按阶段串联正式发布、界面、安装和更新证据；每份记录注明源码、环境与未覆盖范围。

- [0.2.3 发布与真实认证验证](desktop-release-0.2.3.md)：四平台产物、签名及公开下载，21 的 Rust 登录 / 退出与 Windows 原生只读查询。
- [21 Shell 链路对照](portal-21-review-2026-10-28.md)与[账号池实测](account-pool-21-review-2026-10-28.md)：保留当次 Python CLI 和守护切换证据。
- [DNS / TLS 只读核验](portal-ip-fallback-2026-10-28.md)与[123 服务登录对照](portal-123-review-2026-10-27.md)：分别记录连接地址验证及 CAS 后服务拒绝。

认证库通过不代表 GUI、Worker 账号池或软件内升级全部通过；剩余场景见[验收边界](desktop-acceptance.md#尚未证明的范围)。
