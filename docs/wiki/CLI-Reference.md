# 燕山大学校园网 Linux 命令行（ysu）速查

[返回导航](Home.md) · [快速开始](Quick-Start.md) · [桌面客户端](Desktop-Client.md) · [常见问题排障](Troubleshooting.md)

本页汇总燕山大学校园网 Linux 命令行工具 `ysu` 的高频指令，适用于课题组服务器、Ubuntu / Debian、WSL 与无桌面 SSH 环境的自动登录、`systemd` 断网重连、7 天无感认证自动续约及多账号池切换。完整参数、配置文件与环境变量说明见 [docs/usage.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)。

## 日常连接与守护

| 命令 | 说明 |
| --- | --- |
| `ysu` | 打开交互式终端菜单（非交互终端输出帮助说明） |
| `ysu on` | 启动后台自动重连服务（离线时自动登录） |
| `ysu off` | 停止后台自动重连服务，并下线当前连接 |
| `ysu login` / `ysu logout` | 单次登录 / 停止守护并下线 |
| `ysu status [--raw]` | 查看校园网在线状态与当前运营商 |
| `ysu info [--raw]` | 查看当前账号套餐、计费周期与剩余流量 |
| `ysu service [运营商]` | 查看或配置下次登录使用的运营商（`校园网` / `中国移动` / `中国联通` / `中国电信`） |
| `ysu switch <运营商>` | 立即核验切换当前在线运营商，失败时尝试恢复原连接（需先 `ysu stop`） |
| `ysu start` / `ysu stop` / `ysu restart` | 启动 / 停止 / 重启后台自动重连服务 |
| `ysu boot [on\|off\|status]` | 开启、关闭或查看开机自启状态 |
| `ysu night [on\|off\|status]` | 开启、关闭或查看宿舍夜间停网静默保护（支持 `--start 23:30 --end 06:00 --everyday`） |
| `ysu logs [-n 50] [-f]` | 查看或实时跟随后台守护日志 |
| `ysu doctor [--network]` | 检查本地配置与运行环境（加 `--network` 测试门户连通性） |

## 设备自助服务与 7 天无感认证 (`ysu self`)

支持追加 `--account <标识>` 操作账号池中的指定账号（用户名或账号 `id`）：

| 命令 | 说明 |
| --- | --- |
| `ysu self` / `ysu self list [--raw]` | 查看在线设备、套餐流量、7 天无感认证记录与自动续约状态 |
| `ysu self nosense current [--service 运营商]` | 为本机开启 7 天无感认证，可选同时设置默认上网服务 |
| `ysu self nosense <序号\|MAC> [--service 运营商]` | 为指定在线设备或 MAC（如 `AA-BB-CC-DD-EE-FF`）开启 7 天无感认证 |
| `ysu self unbind <current\|序号\|MAC\|all>` | 取消本机、指定设备或全部设备的 7 天无感认证 |
| `ysu self service <current\|序号\|MAC> --service <运营商>` | 修改设备无感认证的默认上网服务 |
| `ysu self renew on [--mac MAC] [--service 运营商]` | 开启无感认证到期前 24 小时后台自动续约 |
| `ysu self renew off` / `ysu self renew status [--raw]` | 关闭自动续约 / 查看自动续约配置 |
| `ysu self renew [--yes]` | 立即执行一次续约检查（`--yes` 强制立即解绑并重绑刷新 7 天有效期） |
| `ysu self kick <current\|序号\|MAC\|all> [--yes]` | 下线指定在线设备或全部设备 |

## 多账号池与自动换号 (`ysu accounts`)

完整说明见 [docs/accounts.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/accounts.md)：

| 命令 | 说明 |
| --- | --- |
| `ysu accounts` / `ysu accounts menu` | 打开多账号交互菜单（增删改、启停候选、热切换与自动换号开关） |
| `ysu accounts list [--raw]` | 输出账号池列表、启用状态、活动账号与自动换号配置（隐藏密码） |
| `ysu accounts save <学号> [--id ID] [--label 备注] [--service 运营商] [--backend api\|browser]` | 新增或更新账号（密码仅通过交互隐藏输入读取） |
| `ysu accounts save <学号> --id <ID> [--enabled\|--disabled]` | 启用或停用候选账号参与自动轮换 |
| `ysu accounts switch <id>` | 独立核验并热切换到指定账号（自动解绑旧账号本机无感认证并为新账号重绑） |
| `ysu accounts delete <id>` | 删除非活动账号 |
| `ysu accounts rotation <on\|off>` | 开启或关闭零流量自动换号 |

## 配置管理 (`ysu config`)

| 命令 | 说明 |
| --- | --- |
| `ysu config show [--raw]` / `ysu config path` | 查看当前配置（隐藏密码）/ 查看配置文件路径 |
| `ysu config account` | 交互修改主账号学号与密码 |
| `ysu service <运营商>` / `ysu backend <api\|browser>` | 修改默认运营商 / 切换认证方式（默认 `api`） |
| `ysu config set <配置项> <值>` | 修改检查间隔（`check_interval`）、重试间隔（`retry_interval`）或超时（`operation_timeout`） |
