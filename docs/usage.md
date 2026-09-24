# 使用与配置

[返回首页](../README.md) · [更新与迁移](migration.md) · [开发说明](development.md)

命令均在安装后使用。用户级配置位于 `${XDG_CONFIG_HOME:-~/.config}/ysu-net/config.json`，
系统级配置位于 `/etc/ysu-net/config.json`，系统级管理命令需要 `sudo ysu ...`。

## 命令

| 命令 | 作用 |
| --- | --- |
| `ysu` / `ysu menu` | 交互菜单 |
| `ysu login` | 登录一次；已运行守护时先 `ysu stop` |
| `ysu on` / `ysuon` | 启动自动重连，认证结果查看状态或日志 |
| `ysu stop` | 停止自动重连，保留当前网络连接 |
| `ysu off` / `ysuoff` / `ysu logout` | 先停止自动重连，再发起下线并验证结果 |
| `ysu restart` | 重启自动重连并重新读取配置 |
| `ysu status [--raw]` | 查询在线状态，可输出 JSON |
| `ysu info [--raw]` | 查询在线信息和账户信息 |
| `ysu service [服务名]` | 查看或配置下次登录使用的服务，不立即断线 |
| `ysu switch <服务名>` | 立即切换并核验实际服务，失败时尝试恢复原连接 |
| `ysu backend [api\|browser]` | 查看或切换认证实现 |
| `ysu config account` | 设置账号密码 |
| `ysu config show` / `ysu config path` | 查看脱敏配置 / 配置路径 |
| `ysu config set <配置项> <值>` | 修改运行参数 |
| `ysu boot on\|off\|status` | 自启开关，与当前连接状态独立 |
| `ysu logs [-f] [-n 50]` | 查看 / 跟随 systemd 日志 |
| `ysu doctor [--network]` | 默认只检查本地；指定参数后查询校园网 |
| `ysu daemon [--once]` | 前台守护 / 单次检查，用 Ctrl+C 停止 |

`service` 只保存配置，不断开当前连接。立即切换请先停止守护，再运行 `ysu switch 中国移动`。
`switch` 会核对在线账号和实际服务，确认下线后登录目标服务，并用独立查询验证结果；只有成功才保存服务配置。
失败时最多尝试恢复原服务一次，保留原配置并返回非零退出码；未知状态或其他账号的连接不会被主动下线。
切换会短暂中断连接，远端 SSH 操作应另备恢复通道。配置写锁与守护运行锁分离，支持热更新且不会覆盖切换期间更新的密码。
普通 `login` 不隐式切换已在线连接；若实际服务不匹配，返回 3 并提示使用 `switch`。
没有 systemd 时，`ysu daemon` 直接向终端输出日志，先结束前台守护才能手动登录或下线。
`on/stop/boot/logs` 管理 systemd 服务，不提供脱离终端的脚本进程管理器。

## 账户、流量与诊断

```bash
ysu info                 # 账户、实际服务、在线设备、门户提供的流量和余额
ysu info --raw           # 保留原始 JSON，供脚本处理
ysu doctor               # 本地环境、配置权限、依赖、后台与自启诊断
ysu doctor --network     # 额外核对在线状态、实际服务及 DNS/TLS 故障
```

直接运行 `ysu`：菜单 **13** 查看账户与剩余流量，**7** 做本地诊断，**14** 做联网诊断。

账户信息兼容 `data.accountInfo` 与 `data.data.accountInfo`，数值 `0` 会正常显示，HTML 标签会转为纯文本。默认不展示会话标识或账户条目中的签名跳转链接；原始 JSON 可能包含账户及会话数据，分享前请脱敏。

流量、余额按门户原文展示，不推算额度、不猜测单位。字段缺失显示“门户未提供”，不代表流量为零或不限量。本次中国移动真实接口仅返回业务明细、我的运营商和在线设备，没有返回剩余流量与余额；可进一步到门户业务明细或运营商自助服务查询。

`doctor` 默认不联网；`--network` 只查询，不登录、不下线、不切换运营商。后台异常、已开启自启但未开启 linger、实际服务与配置不一致时，会提示对应处理方式并返回 2。明确离线但门户可达不视为查询故障，会提示登录方法。未安装或主动停止后台服务仍可使用一次性命令。

## 常见使用场景

**日常查看与维护：**

```bash
ysu status              # 查询校园网在线状态
ysu info                # 查看账户信息
ysu logs -f             # 持续查看重连日志，Ctrl+C 仅退出日志查看
ysu stop                # 暂停自动重连，保留当前网络连接
ysu on                  # 恢复自动重连
ysu off                 # 停止自动重连，并退出校园网
```

**切换运营商（保持同一账号）：**

```bash
ysu stop
ysu switch 中国移动     # 成功后才保存服务；失败尝试恢复原连接
# 只改下次登录配置可使用：ysu service 中国移动
ysu on                  # 验证成功后恢复自动重连
```

修改账号时，先使用旧配置 `ysu off` 下线，再 `ysu config account`、`ysu login`，确认成功后恢复守护。
遇到运营商“同时在线数量已达上限”，先在其他终端正常下线或通过门户核对在线设备，再重试；工具不自动踢其他设备。

**无 systemd 或用户总线不可用：**

```bash
bash install.sh --no-service
export PATH="$HOME/.local/bin:$PATH"
ysu config account
ysu daemon              # 保持终端打开；Ctrl+C 停止守护
```

前台守护退出后才可执行 `ysu login` 或 `ysu logout`；不支持用 `ysu stop` 结束前台守护。
如需指定独立配置，使用 `ysu --config /绝对路径/config.json config account`，
再运行 `ysu --config /绝对路径/config.json daemon`。全局参数放在子命令之前。

## 配置与重试行为

使用 `ysu config show` 查看当前配置，或通过下列字段修改；所有间隔和超时均以秒为单位。

| 配置项 | 默认值 | 用途 |
| --- | --- | --- |
| `service` | `校园网` | 选择校园网或运营商，也可用 `ysu service` |
| `backend` | `api` | `api` 或 `browser`，浏览器方式需安装可选依赖 |
| `check_interval` | `15` | 正常在线时的检查间隔 |
| `retry_interval` | `30` | 失败后的首次重试间隔 |
| `max_retry_interval` | `900` | 重试间隔上限，不得小于 `retry_interval` |
| `operation_timeout` | `180` | 单次认证子进程的总时限 |
| `verify_tls` | `true` | 是否校验 HTTPS 证书 |
| `base` | `https://auth1.ysu.edu.cn` | Portal 入口 |
| `cas_host` | `https://cer.ysu.edu.cn` | CAS 统一认证入口 |

账号和密码通过 `ysu config account` 输入，不接受 `config set password ...`。

```bash
ysu config set check_interval 15
ysu config set retry_interval 30
ysu config set max_retry_interval 900
ysu config set operation_timeout 180
ysu config set verify_tls true
ysu service 中国移动
```

配置使用 JSON，原子写入并设置 `0600` 权限；密码中的空格、引号和特殊字符会原样保留。
配置查看不输出账号密码。`YSU_USER`、`YSU_PASS`、`YSU_SERVICE` 可临时覆盖当前进程的配置；
systemd 不会自动继承交互终端导出的环境变量，后台使用持久化配置。
账号密码仅传给认证子进程的环境变量，不拼入命令行或 systemd 单元。

后台每轮读取配置，默认 15 秒检查一次。失败按 30、60、120…秒退避，带少量随机延迟，最多 900 秒：

- **在线**：保持检查，不重复登录。
- **明确离线**：发起登录并再次验证在线状态。
- **查询失败 / 响应异常**：状态记为未知，仅重试查询，不盲目提交密码。
- **API 认证被拒绝 / 需要验证码，或浏览器识别到 IP 冻结**：暂停自动登录；修改账号配置、手动登录成功或重启守护后可恢复。浏览器其他错误按普通失败退避。

单次认证子进程总时限由 `operation_timeout` 控制（默认 180 秒），包括跳转、请求和轮询；
超时或停止守护时会清理整个认证进程组，包含 Playwright 子进程。
同一配置的守护进程和手动登录/下线通过文件锁互斥。

TLS 证书校验默认开启。确需兼容校园网证书问题时可显式设置
`ysu config set verify_tls false`，更推荐通过 `REQUESTS_CA_BUNDLE` 为 API 方式配置可信 CA。
不要将真实账号配置提交到仓库。认证模块的 `--debug` 输出可能含会话信息，分享前需脱敏；
管理命令后台日志只记录固定状态消息，不记录原始认证响应。

退出码：`0` 成功/在线，`1` 明确离线（status），`2` 连接/查询/配置错误，
`3` 操作失败或超时，`4` 认证需要人工处理，`130` 用户取消。
`daemon --once` 的返回码只表示检查循环是否正常执行；网络结果记录在日志，查询网络状态请用 `status`。

## 浏览器方式与认证模块

```bash
uv sync --locked --extra browser
uv run --extra browser playwright install chromium
ysu backend browser
```

在部分 Linux 发行版上可能需要额外安装 Chromium 系统依赖；浏览器安装命令失败时按 Playwright 提示处理。
`--offline --browser` 不下载浏览器，请预先准备匹配版本的 Playwright 运行时。
`uv sync` 默认只安装 API 依赖；使用浏览器时保留 `--extra browser`。

需要单独调试认证流程时可直接运行模块，通用参数放在子命令后：

```bash
export YSU_USER="你的账号"
export YSU_PASS="你的密码"
uv run python -m ysu_net.auth.api login --service 校园网
uv run python -m ysu_net.auth.api status --raw
uv run python -m ysu_net.auth.api logout
uv run --extra browser python -m ysu_net.auth.browser login --service 校园网
```

认证模块还支持 `shell`、`--interactive`、`--debug`，以及 `YSU_BASE`、`YSU_CAS_HOST`、
`YSU_VERIFY_TLS`、`YSU_TIMEOUT`（API）、`YSU_PORTAL_UA`、`YSU_VERSION`、`YSU_SAVE_DEBUG_FILES`。
管理入口的认证地址和 TLS 以 JSON 配置为准，不从上述同名环境变量覆盖。
依赖统一维护在 `pyproject.toml`，具体版本由 `uv.lock` 锁定；已移除旧的 `requirements.txt`。


## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| `ysu: command not found` | 检查 `~/.local/bin` 是否加入 PATH；也可直接运行 `~/.local/bin/ysu --help` |
| `systemctl --user` 无法连接总线 | 登录用户会话后重试，或使用 `bash install.sh --no-service` 和 `ysu daemon` |
| `ysu on` 提示完成，但还未联网 | 表示后台服务启动成功；认证结果用 `ysu status` 和 `ysu logs -f` 查询 |
| 查询失败、状态未知 | 先确认接入校园网，再运行 `ysu doctor`；需要实际网络诊断时用 `ysu doctor --network` |
| 提示已有守护进程运行 | 先 `ysu stop`；若运行的是前台守护，在对应终端按 Ctrl+C |
| 认证暂停、密码错误或要求验证码 | 停止守护，检查账号，使用 `ysu login` 手动处理，再 `ysu on` |
| 修改配置后未立即生效 | 守护在下一轮检查时读取配置，可用 `ysu restart` 立即重启 |
| 浏览器缺失 | 运行 `bash install.sh --browser`，再 `ysu backend browser` |
| `ysu doctor` 提示未配置账号 | 用 `ysu config account` 设置；单独导出的环境变量不会传入 systemd 服务 |
