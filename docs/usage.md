# 使用与配置

[返回首页](../README.md) · [更新与迁移](migration.md) · [多账号热切换](accounts.md) · [开发说明](development.md)

命令均在安装后使用。请在持久目录（如 `~/ysu_net` 或系统级 `/opt/ysu_net`，勿使用 `/tmp`）克隆并运行 `bash install.sh`，安装后保留源码与 `.venv`（移动目录后需重新运行 `bash install.sh`）：
- **用户级（默认）**：命令位于 `~/.local/bin/{ysu,ysuon,ysuoff}`，配置位于 `${XDG_CONFIG_HOME:-~/.config}/ysu-net/config.json`，服务位于 `${XDG_CONFIG_HOME:-~/.config}/systemd/user/ysu-net.service`。
- **系统级（`--system`）**：命令位于 `/usr/local/bin/{ysu,ysuon,ysuoff}`，配置位于 `/etc/ysu-net/config.json`，服务位于 `/etc/systemd/system/ysu-net.service`，管理命令需 `sudo ysu ...`。

## 命令

| 命令 | 作用 |
| --- | --- |
| `ysu` / `ysu menu` | 交互主菜单，16 进入多账号管理，17 查看我的设备与自助服务 |
| `ysu accounts` / `ysu accounts menu` | 多账号交互菜单；管理账号、热切换与自动换号 |
| `ysu accounts list [--raw]` | 查看账号簿与流量换号开关，可输出 JSON |
| `ysu accounts save <ID> [--name 备注] [--user 账号] [--service 服务] [--backend api\|browser]` | 新增或更新账号条目并交互录入密码 |
| `ysu accounts switch <ID>` | 核验在线身份后热切换到指定账号，失败时尝试恢复原连接 |
| `ysu accounts delete <ID>` | 删除备用账号（当前活动账号不可直接删除） |
| `ysu accounts rotation on\|off` | 开启或关闭零流量自动换号 |
| `ysu login` | 登录一次；已运行守护时先 `ysu stop` |
| `ysu on` / `ysuon` / `ysu start` | 启动自动重连，认证结果查看状态或日志 |
| `ysu stop` | 停止自动重连，保留当前网络连接 |
| `ysu off` / `ysuoff` / `ysu logout` | 先停止自动重连，再发起下线并验证结果 |
| `ysu restart` | 重启自动重连并重新读取配置 |
| `ysu status [--raw]` | 查询在线状态，可输出 JSON |
| `ysu info [--raw]` | 查询在线信息和账户信息 |
| `ysu self [--raw]` | 自助服务：我的设备、套餐、剩余流量与记住的上网选择 |
| `ysu self kick <编号\|all> [--yes]` | 下线指定设备（会中断该设备的网络连接） |
| `ysu service [服务名]` | 查看或配置下次登录使用的服务，不立即断线 |
| `ysu switch <服务名>` | 立即切换并核验实际服务，失败时尝试恢复原连接 |
| `ysu backend [api\|browser]` | 查看或切换认证实现 |
| `ysu config account` | 设置账号密码 |
| `ysu config show [--raw]` / `ysu config path` | 查看脱敏配置（支持 JSON） / 配置路径 |
| `ysu config set <配置项> <值>` | 修改运行参数 |
| `ysu boot on\|off\|status` | 自启开关，与当前连接状态独立 |
| `ysu logs` / `ysu log [-f] [-n 50]` | 查看 / 跟随 systemd 日志 |
| `ysu doctor [--network]` | 默认只检查本地；指定参数后查询校园网 |
| `ysu daemon [--once]` | 前台守护 / 单次检查，用 Ctrl+C 停止 |

全局选项放在子命令之前：`--scope user|system` 选择用户级或系统级范围，`--config <路径>` 指定独立配置文件；环境变量 `NO_COLOR=1` 禁用终端彩色输出。安装与卸载脚本位于项目根目录：`bash install.sh [--system] [--no-service] [--browser] [--captcha] [--offline]`、`bash uninstall.sh [--system] [--purge]`（`--purge` 同时清理配置与账号簿）。

`service` 只保存配置，不断开当前连接。立即切换请先停止守护，再运行 `ysu switch 中国移动`。
`switch` 会核对在线账号和实际服务，确认下线后登录目标服务，并用独立查询验证结果；只有成功才保存服务配置。
失败时最多尝试恢复原服务一次，保留原配置并返回非零退出码；未知状态或其他账号的连接不会被主动下线。
切换会短暂中断连接，远端 SSH 操作应另备恢复通道。配置写锁与守护运行锁分离，支持热更新且不会覆盖切换期间更新的密码。
普通 `login` 不隐式切换已在线连接；若实际服务不匹配，返回 3 并提示使用 `switch`。
实际服务核验允许 `realServiceName` 缺失或为 JSON `null` 时使用有效的 `service`；其他未知原始服务名、空字符串、类型异常或有效服务冲突仍按查询失败处理。多账号切换和流量轮换还要求所有非 `null` 原始服务字段与已核验服务一致，不使用不明标签作为账号证据。
没有 systemd 时，`ysu daemon` 直接向终端输出日志，先结束前台守护才能手动登录或下线。
`on/stop/boot/logs` 管理 systemd 服务，不提供脱离终端的脚本进程管理器。

## 账户、流量与诊断

```bash
ysu info                 # 账户、实际服务、在线设备、门户提供的套餐与流量
ysu info --raw           # 保留原始 JSON，供脚本处理
ysu doctor               # 本地环境、配置权限、依赖、后台与自启诊断
ysu doctor --network     # 额外核对在线状态、实际服务及 DNS/TLS 故障
```

直接运行 `ysu`：首次使用可先输入 **15**（也支持 **h** 或 **?**）查看“选项说明”，逐项了解用途、是否联网、是否改配置，以及是否影响当前连接或后台服务。说明页只显示帮助，按 Enter 返回菜单，输入 0 退出。

菜单 **13** 查看账户与剩余流量，**7** 做本地诊断，**14** 做联网诊断。特别注意：**4 会下线断网，9 只停守护保留连接，0 只退出菜单；10/11 只改自启，不改变当前服务运行状态。**

状态和账户查询读取当前网络会话，不要求先在本客户端重新登录。桌面的“连接状态未知”表示查询尚未确认，不等于门户已确认离线；账户读取失败会显示错误，并提供只读重试。无需为查询而下线、换号或重登。

账户信息兼容 `data.accountInfo` 与 `data.data.accountInfo`，数值 `0` 会正常显示，HTML 标签会转为纯文本。默认不展示会话标识或账户条目中的签名跳转链接；原始 JSON 可能包含账户及会话数据，分享前请脱敏。

流量与其他账户条目按门户原文展示，不推算额度、不猜测单位，也不补造账户余额项目。剩余流量缺失显示“门户未提供”，不代表流量为零或不限量；可进一步到门户业务明细或运营商自助服务查询。

### 自助服务（ysu self）

`ysu self` 登录自助服务（`auth1.ysu.edu.cn/self`）读取账户与设备数据。它与门户共用同一套统一身份认证，但走独立的 OAuth2 客户端，因此会自己完成一次 CAS 登录；登录结果不写入配置，也不改变当前连接。门户设备页另有解绑 MAC 与关闭无感知认证等操作，本工具未实现——本校当前关闭了自助解绑（`enableSelfUnbind=false`）。

```bash
ysu self                    # 我的设备、套餐、剩余流量、记住的上网选择
ysu self --raw              # 同一份数据的 JSON
ysu self kick 2             # 下线列表里的第 2 台设备（需确认）
ysu self kick all --yes     # 下线全部在线设备（非交互环境必须带 --yes）
```

`kick` 的编号来自 `ysu self` 列表的顺序（从 1 开始），只接受当前在线且带门户标识的设备。下线后工具会重新读取一次设备列表核对结果，设备仍在在线就报错而不是报告成功。

选择下线**本机**时会保留统一身份认证登录（只断 Portal，可重新上网）；下线**其他设备**会连同它的统一认证会话一起登出——这与门户网页的行为一致。任何一次下线都会中断目标设备当前的连接，它需要重新登录才能上网。

输出的每个值都按门户原文展示，不做单位换算；门户未提供的项目显式标注，不补零。

`ysu self` 默认复用已保存的登录状态：首次运行完整登录一次，之后 **30 分钟**内（`SESSION_TTL`）再次运行只做一次轻量校验，不再走密码登录。缓存保存在 `$XDG_CACHE_HOME/ysu-net/self-session.json`（默认 `~/.cache`），文件权限 `0600`，且绑定当前账号与门户地址——换账号或换 `base` 会直接失效，不会串用。

```bash
ysu self --fresh    # 忽略缓存，强制重新登录
```

输出第一行会写明会话来源（「复用已登录状态（未重新登录，缓存剩余 N 分钟）」或「本次新登录」），`--raw` 里是 `session.cached` / `session.expires_in`。

缓存失效、过期、或校验不通过时会自动清除并重新登录一次。即便如此，失败后仍**不要循环重试**：连续失败会触发统一认证的 **IP 冻结（约 1 小时）**，正确密码的重复登录同样计入风控。

`doctor` 默认不联网；`--network` 只查询，不登录、不下线、不切换运营商。API 方式下会一并显示`验证码识别`状态（`已就绪` / `按需人工处理`），未安装可选识别依赖不改变退出码。后台异常、已开启自启但未开启 linger、实际服务与配置不一致时，会提示对应处理方式并返回 2。明确离线但门户可达不视为查询故障，会提示登录方法。未安装或主动停止后台服务仍可使用一次性命令。

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

多个账号可从主菜单 **16** 或直接运行 `ysu accounts` 进入[账号簿与热切换菜单](accounts.md#shell-版交互菜单)，也支持独立子命令。守护运行时由锁所有者执行，不先停止后台。旧 `ysu config account` 仍是直接修改单账号配置；沿用此路径时，先用旧配置 `ysu off` 下线，再修改、登录并恢复守护。
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

自 0.2.3 起，默认 API 包含[DNS 失败时的备用 IP](tauri-desktop.md#dns-失败时的备用-ip)，云端回归与真实验证范围见[发布记录](desktop-release-0.2.3.md)。`base` / `cas_host` 保留 HTTPS 域名，`verify_tls` 保持开启；直接填写 IP 会改变证书校验和站点身份。可选 Python Browser 尚无此回退，仍需可用的系统 DNS。

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
- **API 认证被拒绝 / 需要验证码，或浏览器识别到 IP 冻结**：暂停自动登录；修改账号配置、手动登录成功或重启守护后可恢复。装了[验证码识别](#验证码识别)时先自动尝试，仍失败才进入该状态。浏览器其他错误按普通失败退避。

单次认证子进程总时限由 `operation_timeout` 控制（默认 180 秒），包括跳转、请求和轮询；
超时或停止守护时会清理整个认证进程组，包含 Playwright 子进程。
同一配置的守护进程和手动登录/下线通过文件锁互斥。

TLS 证书校验默认开启，排障时保持 `verify_tls=true`。API 方式如需额外可信 CA，可通过
`REQUESTS_CA_BUNDLE` 配置；DNS 或门户跳转失败不通过改 IP、关闭 TLS 校验处理。
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
## 验证码识别

CAS 要求验证码时不再一律停在人工处理。默认安装不含识别依赖，需要时显式安装可选组（后续运行 `install.sh` 升级时保留 `--captcha`）：

```bash
bash install.sh --captcha
# 或仅同步虚拟环境依赖：
uv sync --locked --extra captcha
```

后端由环境变量选择：`YSU_CAPTCHA_SOLVER` 取 `auto`（默认，依次尝试远端、ddddocr、tesseract、手工输入）、`remote`、`ddddocr`、`tesseract` 或 `manual`；远端后端需要 `YSU_CAPTCHA_REMOTE_URL`，只发送图片字节。识别结果按四位字母数字校验，失败即视为未识别。

无论是否装了识别依赖，图片都会先保存为工作目录的 `captcha.png`，便于核对；识别不到时命令以需人工介入结束并给出该路径。没有终端且没有可用后端时，仍按原规则在取图前停止，不会在后台反复提交。守护遇到这类状态时暂停自动登录，处理方式与[常见问题](#常见问题)一致。桌面端只在本地已有模型时自动识别，见[桌面语义](tauri-desktop.md#验证码识别)。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| `ysu: command not found` | 检查 `~/.local/bin` 是否加入 PATH；也可直接运行 `~/.local/bin/ysu --help` |
| `systemctl --user` 无法连接总线 | 登录用户会话后重试，或使用 `bash install.sh --no-service` 和 `ysu daemon` |
| `ysu on` 提示完成，但还未联网 | 表示后台服务启动成功；认证结果用 `ysu status` 和 `ysu logs -f` 查询 |
| 查询失败、状态未知 | 先确认接入校园网，再运行 `ysu doctor`；需要实际网络诊断时用 `ysu doctor --network` |
| 域名解析失败 | 0.2.3 默认 API 对包内精确校园域名提供回退；自定义域名、代理解析及 Python Browser 仍需单独检查 DNS，保留 HTTPS 域名和证书校验 |
| 门户跳转失败或 CAS 回调异常 | 核对版本、认证方式和固定错误阶段，按[排障指南](wiki/Troubleshooting.md)区分导航、CAS 与服务登录；HTTP 200 或表单提交成功不足以证明已上线 |
| 提示已有守护进程运行 | 先 `ysu stop`；若运行的是前台守护，在对应终端按 Ctrl+C |
| 认证暂停、密码错误或要求验证码 | 停止守护，检查账号，使用 `ysu login` 手动处理，再 `ysu on`；反复遇到验证码可先按[验证码识别](#验证码识别)安装可选依赖 |
| 修改配置后未立即生效 | 守护在下一轮检查时读取配置，可用 `ysu restart` 立即重启 |
| 浏览器缺失 | 运行 `bash install.sh --browser`，再 `ysu backend browser` |
| `ysu doctor` 提示未配置账号 | 用 `ysu config account` 设置；单独导出的环境变量不会传入 systemd 服务 |
