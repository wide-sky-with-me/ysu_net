# 排障与已知问题

[返回导航](Home.md) · [命令行入口](CLI-Reference.md) · [隐私与反馈](Privacy-and-Reporting.md)

先记下工具版本、使用方式、系统版本、认证方式与运营商，再一次改变一个条件。不要为排障公开真实账号或原始网络材料。

| 现象 | 最小检查与处理 |
| --- | --- |
| `ysu: command not found` | 检查 PATH 是否含 `~/.local/bin`；可直接执行 `~/.local/bin/ysu --help` |
| 默认分支找不到 `ysu-gui` | `main` 没有桌面入口，使用桌面测试版附件或对应标签，见 [桌面版](Desktop-Client.md) |
| `systemctl --user` 连接用户总线失败 | 登录用户会话，或使用无服务安装与前台守护；不要把此故障当成账号错误 |
| 开启自动重连但尚未联网 | 服务启动不等于认证成功；单独查询状态并查看最少必要日志 |
| 状态未知、查询超时或 DNS/TLS 错误 | 先确认接入校园网；命令行先本地 `ysu doctor`，再按需 `ysu doctor --network` |
| 提示已有守护进程或后台服务管理 | 同一配置只运行一个重连器；先按说明停止 systemd 服务或前台守护 |
| 账号错误、验证码或认证暂停 | 暂停重连，本机核对配置或通过门户处理；不要连续重复提交密码 |
| 剩余流量/余额显示“门户未提供” | 门户没有返回字段，去门户或运营商查询；不是流量为零或无限量 |
| 桌面自动重连后仍显示未连接 | 先手动刷新；已有 [Issue #1](https://github.com/wide-sky-with-me/ysu_net/issues/1)，尚未确认修复 |
| 运营商切换失败或在线设备超限 | 先核对独立状态与原服务是否恢复，按门户提示处理已有在线设备；工具不自动踢其他设备 |

命令行的具体故障表与退出码见 [使用说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md#常见问题)。桌面浏览器认证依赖与限制见 [对应标签文档](https://github.com/wide-sky-with-me/ysu_net/blob/v0.1.0-beta.1/docs/desktop.md#限制)。不要把关闭 TLS 校验当作默认修复方式；先核对证书与可信 CA 配置。

## 形成可处理的反馈

用法疑问到 [Q&A](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a)，可复现程序故障到 [Issue 表单](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=bug_report.yml)。已有同一问题时补充原帖，提供版本、复现顺序、预期/实际结果与人工脱敏的最少提示；无须上传账号、IP/MAC、完整日志、配置或 HAR。

没有真正执行的步骤标为“未测试”；历史验收不覆盖当前设备或所有运营商。改进想法可在 [Ideas](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/ideas) 讨论，不在排障贴中预先承诺修复排期。
