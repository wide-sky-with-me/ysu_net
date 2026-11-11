# 命令行速查

[返回导航](Home.md) · [快速开始](Quick-Start.md) · [桌面客户端](Desktop-Client.md) · [常见问题排障](Troubleshooting.md)

本页汇总 Linux 命令行 `ysu` 的常用指令。完整参数、配置文件与环境变量说明见 [docs/usage.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/usage.md)。

## 日常连接与守护

| 命令 | 说明 |
| --- | --- |
| `ysu` | 打开交互式终端菜单（非交互终端输出状态摘要） |
| `ysu on` | 立即登录校园网，并启动、启用后台自动重连服务 |
| `ysu off` | 停止、禁用后台自动重连服务，并下线当前连接 |
| `ysu login` / `ysu logout` | 单次登录 / 单次下线（不更改后台服务启用状态） |
| `ysu status [--json]` | 查看校园网在线状态、当前运营商与后台服务状态 |
| `ysu info [--raw] [--json]` | 查看当前账号套餐、计费周期与剩余流量 |
| `ysu service [运营商]` | 查看或切换运营商（`校园网` / `中国移动` / `中国联通` / `中国电信`） |
| `ysu start` / `ysu stop` / `ysu restart` | 启动 / 停止 / 重启后台自动重连服务 |
| `ysu enable` / `ysu disable` | 开启 / 关闭开机自启 |
| `ysu logs [-n 50] [-f]` | 查看或实时跟随后台守护日志 |
| `ysu doctor [--network]` | 检查本地配置与运行环境（加 `--network` 测试门户连通性） |

## 设备自助服务与 7 天无感认证 (`ysu self`)

支持追加 `--account <标识>` 操作账号池中的指定账号：

| 命令 | 说明 |
| --- | --- |
| `ysu self` / `ysu self list [--json]` | 查看在线设备、套餐流量、7 天无感认证记录与自动续约状态 |
| `ysu self nosense current [--service 运营商] [--auto-renew]` | 为本机开启 7 天无感认证，可选同时设置默认上网服务并开启自动续约 |
| `ysu self nosense <序号\|MAC> [--name 名称]` | 为指定在线设备或 MAC（如 `AA-BB-CC-DD-EE-FF`）开启 7 天无感认证 |
| `ysu self unbind <current\|序号\|MAC\|all> [-y]` | 取消本机、指定设备或全部设备的 7 天无感认证 |
| `ysu self service current --service <运营商>` | 修改本机无感认证的默认上网服务 |
| `ysu self renew on [--mac MAC] [--service 运营商]` | 开启无感认证到期前 24 小时后台自动续约 |
| `ysu self renew off` / `ysu self renew status` | 关闭自动续约 / 查看自动续约状态 |
| `ysu self renew now [--force]` | 立即执行一次续约检查（`--force` 强制立即解绑并重绑刷新 7 天有效期） |
| `ysu self kick <current\|序号\|MAC\|IP\|all> [-y]` | 下线指定在线设备或全部设备 |

## 多账号池与自动换号 (`ysu account`)

完整说明见 [docs/accounts.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/accounts.md)：

| 命令 | 说明 |
| --- | --- |
| `ysu account list [--json]` | 查看账号池列表、优先级、活动账号与流量状态 |
| `ysu account add -u 学号 [-s 运营商] [--name 备注] [--priority 数字]` | 添加账号到账号池（不带 `-p` 时安全交互输入密码） |
| `ysu account edit <标识> [...]` | 修改已保存账号的名称、学号、密码、运营商或优先级 |
| `ysu account use <标识>` | 切换到指定账号（自动解绑旧账号本机无感认证并为新账号重绑） |
| `ysu account enable <标识>` / `disable <标识>` | 启用或停用候选账号参与零流量轮换 |
| `ysu account remove <标识>` | 删除非活动账号 |
| `ysu account auto [on\|off\|status]` | 开启、关闭或查看「零剩余流量自动换号」 |

## 配置管理 (`ysu config`)

| 命令 | 说明 |
| --- | --- |
| `ysu config show` / `ysu config path` | 查看当前配置（隐藏密码）/ 查看配置文件路径 |
| `ysu config account` | 交互修改主账号学号与密码 |
| `ysu config service <运营商>` | 修改默认运营商 |
| `ysu config backend <api\|browser>` | 切换认证方式（默认 `api`） |
| `ysu config timer [...]` | 修改检查间隔、重连间隔与操作超时 |
