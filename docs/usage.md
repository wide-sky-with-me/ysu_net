# 命令与配置完整手册

[返回首页](../README.md) · [文档导航](README.md) · [多账号与无感联动](accounts.md) · [更新与卸载](migration.md)

本页介绍 Linux 命令行工具 `ysu` 的安装方式、命令用法、设备自助服务与 7 天无感认证管理，以及配置文件与环境变量说明。若使用图形界面，请参阅 [桌面客户端指南](wiki/Desktop-Client.md)。

---

## 安装方式

```bash
git clone https://github.com/wide-sky-with-me/ysu_net.git
cd ysu_net
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
```

`install.sh` 支持以下安装选项：

| 选项 | 适用场景 | 说明 |
| --- | --- | --- |
| 默认（无参数） | 个人 Linux 桌面 / WSL | 安装用户级命令 `~/.local/bin/ysu` 与用户级服务 `systemctl --user` |
| `--system` | 服务器 / 多用户主机 | 安装系统级命令 `/usr/local/bin/ysu`、配置 `/etc/ysu-net/config.json` 与系统级 `ysu-net.service`（开机即可联网） |
| `--no-service` | 容器 / 无 systemd 环境 | 仅安装 `ysu` 命令，需要后台重连时手动运行 `ysu daemon` |
| `--captcha` | 自动处理 CAS 验证码 | 额外安装 `ddddocr` 离线验证码识别依赖 |
| `--browser` | 需要浏览器认证模式 | 额外安装 Playwright 并下载 Chromium 浏览器 |

---

## 日常连接与状态管理

首次安装后，先设置账号与运营商，再启动连接：

```bash
ysu config account       # 交互输入学号/工号与密码
ysu service              # 选择运营商：校园网 / 中国移动 / 中国联通 / 中国电信
ysu on                   # 立即登录并开启后台自动重连
```

### 核心命令一览

| 命令 | 作用 |
| --- | --- |
| `ysu` | 在交互式终端打开文本菜单；非交互环境输出状态摘要 |
| `ysu on` | 立即登录校园网，并启动、启用后台自动重连服务 |
| `ysu off` | 停止、禁用后台自动重连服务，并主动下线当前校园网连接 |
| `ysu login` | 仅执行一次登录（不修改后台服务开关） |
| `ysu logout` | 仅执行一次下线（若后台自动重连仍在运行，建议先 `ysu stop` 或直接用 `ysu off`） |
| `ysu status [--json]` | 查询校园网实际在线状态（学号、运营商、IP）及后台守护状态 |
| `ysu info [--raw] [--json]` | 查询当前账号套餐、计费周期、剩余流量与连接详情 |
| `ysu service [运营商]` | 查看或切换运营商（`校园网`、`中国移动`、`中国联通`、`中国电信`）；若当前已在线会先下线再按新运营商重连 |
| `ysu start` / `ysu stop` / `ysu restart` | 启动 / 停止 / 重启后台自动重连服务（`stop` 不会断开已建立的校园网连接） |
| `ysu enable` / `ysu disable` | 开启 / 关闭开机自启 |
| `ysu logs [-n 行数] [-f]` | 查看后台守护日志（`-f` 持续跟随输出） |
| `ysu doctor [--network] [--json]` | 检查本地配置、锁文件与依赖；加 `--network` 可额外测试门户连通性 |

---

## 设备自助服务与 7 天无感认证（`ysu self`）

`ysu self` 直连校园网自助服务系统（`https://auth1.ysu.edu.cn/self`），用于管理在线设备、7 天 MAC 无感认证、默认上网服务与到期前自动续约。

所有 `ysu self` 子命令均支持 `--account <标识>` 参数，用于指定操作[账号池](accounts.md)中的某个已保存账号；不指定时默认操作当前活动主账号。

### 1. 查看在线设备与无感状态

```bash
ysu self                      # 查看当前账号的在线设备、套餐流量、无感认证记录与自动续约状态
ysu self list --json          # 以 JSON 格式输出完整快照
ysu self list --account backup # 查看账号池中指定账号的自助服务状态
```

输出内容包括：
- **套餐与剩余流量**：计费周期、套餐名称、剩余流量、默认上网服务（运营商）。
- **在线设备列表**：每台设备的序号、本机标记、设备名称、类型、MAC、IP、在线时长、接入方式与无感状态。
- **7 天无感认证记录**：当前账号下所有已开启无感认证的设备 MAC、设备名称与到期时间。
- **自动续约状态**：当前账号是否开启到期自动续约、目标 MAC、默认服务以及最近一次续约时间。

### 2. 开启与取消 7 天无感认证

开启 7 天无感认证后，对应 MAC 地址的设备在有效期内接入校园网时将由门户直接放行，无需再次发起认证。

```bash
# 为本机开启 7 天无感认证（优先匹配本机在线设备，若当前账号无在线设备则自动探测本机物理网卡 MAC）
ysu self nosense current

# 开启无感认证的同时指定默认上网服务，并一并开启到期前自动续约
ysu self nosense current --service 中国联通 --auto-renew

# 为指定序号或指定 MAC 的设备开启无感认证
ysu self nosense 1 --name "我的笔记本"
ysu self nosense AA-BB-CC-DD-EE-FF --name "路由器" --service 中国移动

# 取消本机、指定序号、指定 MAC 或全部无感认证记录
ysu self unbind current
ysu self unbind 1
ysu self unbind AA-BB-CC-DD-EE-FF
ysu self unbind all -y
```

### 3. 修改无感默认上网服务

无感认证放行时，校园网会按你在自助服务中设置的「默认上网服务」计费和出口。你可以随时修改：

```bash
ysu self service current --service 中国联通
ysu self service AA-BB-CC-DD-EE-FF --service 校园网
```

### 4. 无感认证到期自动续约（`ysu self renew`）

校园网无感认证单次有效期为 **7 天**。开启自动续约后，`ysu daemon` 后台守护进程会定期检查该账号下的无感认证记录；当距离到期不足 **24 小时**（或已过期）时，自动执行「解绑旧记录 → 重新绑定 7 天」，实现长期免干预无感在线。

```bash
# 为当前主账号的本机开启自动续约
ysu self renew on --service 中国联通

# 为账号池中的指定账号与指定设备 MAC 开启独立自动续约
ysu self renew on --account backup --mac AA-BB-CC-DD-EE-FF --name "宿舍路由器" --service 中国移动

# 查看自动续约配置与上次续约结果
ysu self renew status

# 立即触发一次续约检查（加 --force 可忽略 24 小时窗口立即重绑刷新 7 天有效期）
ysu self renew now
ysu self renew now --force

# 关闭自动续约
ysu self renew off
```

> **提示**：自动续约由后台守护进程（`ysu-net.service` 或 `ysu daemon`）定期调度执行，开启 `ysu self renew on` 后请保持后台服务处于运行状态（`ysu start` 或 `ysu on`）。

### 5. 远程下线在线设备（`ysu self kick`）

```bash
ysu self kick 1               # 下线列表中的第 1 台设备（交互确认）
ysu self kick current -y      # 跳过确认，直接下线本机
ysu self kick all -y          # 下线该账号下的全部在线设备
```

---

## 配置文件与参数管理

### 交互与命令配置

```bash
ysu config show               # 查看当前生效配置（密码自动隐藏）
ysu config account            # 修改主账号学号与密码
ysu config service 中国移动    # 修改默认运营商
ysu config backend api        # 切换认证方式：api（默认）或 browser
ysu config timer --check-interval 15 --retry-interval 30 --max-retry-interval 900 --operation-timeout 180
ysu config path               # 查看配置文件所在路径
```

### 配置文件路径

| 安装模式 | 主配置文件 | 辅助状态与配置文件（同目录） |
| --- | --- | --- |
| 用户级（默认） | `${XDG_CONFIG_HOME:-~/.config}/ysu-net/config.json` | `config.accounts.json`（多账号池）<br>`config.nosense.json`（无感自动续约规则）<br>`self-session.json`（自助服务会话缓存） |
| 系统级（`--system`） | `/etc/ysu-net/config.json` | 同目录下的账号池、无感续约与会话文件 |

所有含凭据或会话的配置文件均以 `0600` 权限创建，仅文件所有者可读写。

### 配置字段说明（`config.json`）

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `username` / `password` | `""` | 校园网学号/工号与密码 |
| `service` | `"校园网"` | 目标网络服务：`校园网`、`中国移动`、`中国联通`、`中国电信` |
| `backend` | `"api"` | 认证方式：`api`（默认，纯 HTTP）或 `browser`（Playwright 浏览器） |
| `check_interval` | `15` | 在线时的状态轮询间隔（秒） |
| `retry_interval` | `30` | 断线后的初始重连间隔（秒），连续失败时按指数退避增长 |
| `max_retry_interval` | `900` | 退避重连的最大间隔上限（秒） |
| `operation_timeout` | `180` | 单次登录、下线或查询操作的总超时时间（秒） |
| `verify_tls` | `true` | 是否校验门户与统一身份认证的 HTTPS 证书 |
| `base` / `cas_host` | 燕大门户与 CAS 地址 | 门户地址 `https://auth1.ysu.edu.cn` 与认证地址 `https://cer.ysu.edu.cn` |

### 环境变量

临时调试或脚本调用时，可通过环境变量覆盖磁盘配置（优先级高于 `config.json`）：

- `YSU_USER` / `YSU_PASS` / `YSU_SERVICE`：临时指定账号、密码与运营商（开启环境变量覆盖期间，多账号热切换与自动换号会暂停，以免修改磁盘账号簿）。
- `YSU_CONFIG`：指定自定义 `config.json` 路径。
- `YSU_CAPTCHA_MODEL` / `YSU_CAPTCHA_DIR`：指定桌面端离线验证码识别模型路径或缓存目录。

---

## 认证脚本独立调用

除 `ysu` 管理器外，也可以直接调用底层单次认证模块：

```bash
# API 认证模块
uv run python -m ysu_net.auth.api status
uv run python -m ysu_net.auth.api info
uv run python -m ysu_net.auth.api login -u 学号 -p '密码' -s 中国联通
uv run python -m ysu_net.auth.api logout

# 浏览器认证模块（需安装 browser 依赖）
uv run --extra browser python -m ysu_net.auth.browser login -u 学号 -p '密码' -s 校园网
```

退出码约定：`0` 表示成功（或 `status` 确认在线），`1` 表示确认离线，`2` 表示网络或请求异常，`3` 表示操作后状态未确认，`4` 表示需要人工处理（如密码错误或未配置验证码识别时的验证码挑战）。
