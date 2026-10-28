# 排障与已知问题

[返回导航](Home.md) · [命令行入口](CLI-Reference.md) · [隐私与反馈](Privacy-and-Reporting.md)

先记下系统 / 架构、安装来源与版本、认证方式和服务，再一次改变一个条件。版本号相同不代表同一构建；[正式版与当前源码](https://github.com/wide-sky-with-me/ysu_net/blob/main/README.md#发行与候选状态)应分别判断。不要为排障公开真实账号、配置或原始网络材料。

| 现象 | 最小检查与处理 |
| --- | --- |
| 找不到“关于”或界面与截图不同 | 自 0.2.2 起更新入口在“关于”；0.2.1 在“设置 → 外观与启动”底部。核对实际安装来源，旧版按[迁移指南](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/migration.md)升级。 |
| 状态未知、查询失败或超时 | 确认接入校园网后只读刷新，无需先下线；关闭自动重连也可查询。`code=2` 是查询类失败，不能单独定位账号、DNS 或 TLS 根因。 |
| 域名解析失败 | 0.2.3 的 Rust 传输和 Python 默认 API 支持精确校园域名的地址回退，仍保留域名与 TLS 校验；自定义域名、代理解析及 Python Browser 需单独核对 DNS。不要将配置地址改为 IP，详见[覆盖范围](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#dns-失败时的备用-ip)。 |
| 门户跳转失败 | 保存固定 `stage / reason / navigation` 分类，区分 HTTP 跳转、HTML 引导和 CAS 回调；0.2.3 已修复已采样链路，仍拒绝越界导航。不要用关闭 TLS 或任意重定向放行绕过，见[导航语义](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#门户导航与诊断)。 |
| CAS 回调报需人工处理 | 0.2.3 已修复把正常页面脚本中的风险词误判为正文的情况。真实验证码、风控或服务拒绝仍需处理；保留固定分类，HTTP 200、CAS 成功或表单提交都不足以证明服务已上线。 |
| Python 正常、Rust 失败 | 在同机、同网络、同账号 / 服务和后端下对照独立查询与失败阶段；不要从语言差异直接推定根因。已记录的对照与限制见[发布验证](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/desktop-release-0.2.3.md#修复后的真实验证)。 |
| 账户信息读取失败 | 使用账户页只读重试；连接状态由独立查询核验，账户缺项不能作为离线证据。 |
| 剩余流量显示“门户未提供” | 到门户或运营商查询；缺失不是零或不限量，也不据此自动换号。 |
| 开启重连却尚未联网 | 启动后台不等于认证成功；单独查询状态。遇验证码或风控时暂停重连，在本机或门户处理。 |
| 已有后台管理或账号切换被阻止 | 同一配置只运行一个重连器，由当前所有者执行切换，不删除锁文件抢占。Python 守护热切换与 Rust Worker 的边界见[账号说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/accounts.md)。 |
| 换号失败或在线设备超限 | 核对实际身份、服务和原连接恢复结果；只有旧账号确认下线、目标登录并独立核验后才提交配置。工具不自动踢其他设备。 |
| 更新提示“更新源尚未就绪” | 不等于“已经是最新版”；稍后重试或走固定发布页，不修改源或关闭验签。 |
| 更新仍下载整包 | 无合适补丁、无匹配缓存或差分失败都会使用整包；0.2.3 当次没有差分附件。完整条件见[更新说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/updates.md)。 |
| 安装失败或后台恢复失败 | 按提示恢复后台或退出后重开；未恢复时不要假定自动认证已运行，也不要删除账号配置。安装失败不触发差分二次安装。 |
| `ysu: command not found` | 检查 PATH 是否含 `~/.local/bin`，或运行 `~/.local/bin/ysu --help`。 |
| `systemctl --user` 无法连接总线 | 登录用户会话，或采用无服务安装与前台守护；这不是账号错误。 |
| 找不到 `ysu-gui` | 旧 Qt 客户端已移除，使用 [Tauri 桌面版](Desktop-Client.md)；历史 Qt 报告不作为当前版本故障结论。 |

CLI 的命令和退出码见[使用说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)，平台与浏览器限制见[桌面说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md)。需要开发构建时走[云端路线](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提)，不为排障在本机编译或跑产品测试。

需要保留断网前后的链路时，可使用 0.2.4 起提供的[桌面调试记录](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/debug-recording.md)。0.2.3 无该入口；先开启记录，再复现，断网后文件仍保留在本机。

## 形成可处理的反馈

用法疑问到 [Q&A](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a)，可复现故障到 [Issue 表单](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=bug_report.yml)。先阅读已有问题及最新回复，历史报告只对应当时版本与环境。

提供操作顺序、预期 / 实际结果及人工脱敏的最少固定错误片段；不上传账号、IP/MAC、完整日志、配置或 HAR。未经验证的步骤写“未测试”，云端 CI / 离线演示不代替真实校园网或原位升级验收。更多规则见[隐私与反馈](Privacy-and-Reporting.md)。
