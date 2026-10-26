# 排障与已知问题

[返回导航](Home.md) · [命令行入口](CLI-Reference.md) · [隐私与反馈](Privacy-and-Reporting.md)

先记下系统 / 架构、正式 Release 或开发构建来源、版本号、认证方式与运营商，再一次改变一个条件。版本号相同不代表同一构建；[正式版与当前源码](https://github.com/wide-sky-with-me/ysu_net/blob/main/README.md#发行与候选状态)应分别判断，本页不另维护 Latest 版本号。不要为排障公开真实账号、配置或原始网络材料。

| 现象 | 最小检查与处理 |
| --- | --- |
| 找不到“关于”或界面与当前截图不同 | 0.2.1 正式版的更新入口在“设置 → 外观与启动”底部；0.2.2 目标版本改到“关于”。按实际安装来源与对应版本说明核对，不凭当前源码截图或相同版本号推断目标版本已发布。 |
| 状态未知、查询失败或超时 | 先确认接入校园网，再刷新状态；未知不等于离线。固定 `code=2` 只表示查询类失败，不足以判定账号、DNS 或 TLS 根因。本地诊断不执行登录。 |
| 账户信息读取失败 | 使用账户页的只读重试，无需先下线或换号；连接状态由独立查询核验，账户缺项不能作为离线证据。 |
| 剩余流量显示“门户未提供” | 到门户或运营商查询；缺失不是零或不限量，也不据此自动换号。 |
| 开启重连却尚未联网 | 启动后台不等于认证成功；单独查询状态并查看最少必要日志。遇验证码或风控时暂停重连，在本机或门户处理。 |
| 已有后台服务管理或账号切换被阻止 | 同一配置只运行一个重连器；由桌面或 CLI 的当前所有者操作，不删除锁文件来抢占。 |
| 运营商切换失败或在线设备超限 | 核对独立状态与原服务恢复情况，按门户提示处理已有设备；工具不自动踢其他设备。 |
| 更新提示“更新源尚未就绪” | 不等于“已经是最新版”；稍后重试或走固定正式发布页，不修改源或关闭验签。 |
| 更新仍下载整包，没有差分 | 0.2.1 正式客户端本来是整包方式；0.2.2 目标实现无匹配缓存、无合适补丁或差分失败时也使用整包，无基线首更不保证省流量。版本行为与条件见[更新说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/updates.md)，不据此推断当前已发行版本。 |
| 安装失败或后台恢复失败 | 按明确提示恢复后台或退出后重开；恢复未完成时不要假定自动认证已经恢复，也不要删除账号配置。安装失败不触发差分二次安装。 |
| `ysu: command not found` | 检查 PATH 是否含 `~/.local/bin`；可直接执行 `~/.local/bin/ysu --help`。 |
| `systemctl --user` 连接用户总线失败 | 登录用户会话，或采用无服务安装与前台守护；这不是账号错误。 |
| 找不到 `ysu-gui` | 旧 Qt 客户端已移除，改用 [Tauri 桌面版](Desktop-Client.md)；旧 Qt 问题和报告不作为当前版本故障结论。 |

CLI 的完整故障表 / 退出码见[使用说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md#常见问题)，桌面平台与浏览器限制见[桌面说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md)。不要把关闭 TLS 校验当默认修复方式。需要开发构建时只走[云端路线](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提)，不为排障在本机编译或跑产品测试。

## 形成可处理的反馈

用法疑问到 [Q&A](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a)，可复现故障到 [Issue 表单](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=bug_report.yml)。先阅读已有问题及最新回复。历史 Qt [Issue #1](https://github.com/wide-sky-with-me/ysu_net/issues/1) 已关闭，不应继续标为“未确认修复”；其处理记录只属于当时版本，不是当前 Tauri 或所有平台的通用故障结论。

提供操作顺序、预期 / 实际结果及人工脱敏的最少固定错误片段；不上传账号、IP/MAC、完整日志、配置或 HAR。未经验证的步骤写“未测试”，云端 CI / 离线演示不代替真实校园网或原位升级验收。更多规则见[隐私与反馈](Privacy-and-Reporting.md)。
