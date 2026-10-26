# Linux 命令行入口

[返回导航](Home.md) · [快速开始](Quick-Start.md) · [排障](Troubleshooting.md)

Linux Python CLI 与 Tauri 桌面运行时独立；完整命令、参数、退出码和默认值只在[使用与配置](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)维护，本页只解释常用入口。CLI 源码安装沿用[快速开始](Quick-Start.md)，桌面差分更新不管理 CLI 代码或依赖。

| 目标 | 命令 | 影响 |
| --- | --- | --- |
| 一次性登录 | `ysu login` | 访问认证服务；先停止正在运行的守护 |
| 查看状态/账户 | `ysu status` / `ysu info` | 访问校园网查询；输出可能包含识别信息 |
| 本地排障 | `ysu doctor` | 默认不联网，不登录或下线 |
| 校园网排障 | `ysu doctor --network` | 只查询，不登录、下线或切换 |
| 开启自动重连 | `ysu on` | 启动 systemd 重连服务，认证结果需另查 |
| 只暂停重连 | `ysu stop` | 停止后台服务，保留当前连接 |
| 停止并下线 | `ysu off` | 停止自动重连并下线，影响当前网络 |
| 调整开机自启 | `ysu boot on/off/status` | 与当前服务运行和连接状态分别管理 |
| 查看菜单帮助 | `ysu` 后输入 `15`、`h` 或 `?` | 仅显示说明 |

`ysu service` 保存下次登录选择，不立即切断连接；`ysu switch <服务名>` 才会立即切换并独立核验，失败时尝试恢复原连接。远端使用前阅读 [切换说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md#常见使用场景)。

多账号从 `ysu accounts` 或主菜单 **16** 进入，热切换与流量换号的前提见[账号说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/accounts.md)，不另启动第二个守护。没有 systemd 时可用 `bash install.sh --no-service` 和 `ysu daemon` 前台运行；Ctrl+C 停止前台守护，`ysu stop` 不管理它。源码目录和 `.venv` 是包装入口引用的运行位置，请保留。

`--raw` 供脚本处理原始 JSON，不适合直接粘贴到公开反馈。普通 `info` 与诊断也不保证匿名；分享前按 [隐私规则](Privacy-and-Reporting.md) 检查。

升级和卸载见 [迁移说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md)，权限、账户配置和浏览器方式见 [使用说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)。
