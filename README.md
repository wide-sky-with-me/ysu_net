# ysu-net · 燕山大学校园网管理工具

通过 `ysu` 统一管理校园网登录、下线、自动重连、账号配置、开机自启和日志。
交互方式参考 [clash-for-linux](https://github.com/wnlen/clash-for-linux)，认证仍使用本项目的 Portal / CAS 实现。

支持 Linux + Python 3.12；后台服务使用 systemd。没有 systemd 的环境可使用前台守护。
默认采用轻量 API 认证，Playwright 浏览器认证按需安装。

当前验证范围为本地 mock 测试及 systemd 单元静态检查，尚未在校园网实测。
可以先在非校园网环境安装、配置和运行 `ysu doctor`；登录和真实状态查询需要接入校园网。

## 安装

先准备 Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后执行：

```bash
git clone https://github.com/wide-sky-with-me/ysu_net.git
cd ysu_net
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
```

安装会创建 `.venv`、按 `uv.lock` 安装依赖、注册用户级服务，并生成 `~/.local/bin/ysu`、`ysuon`、`ysuoff`。
请将 `~/.local/bin` 加入 PATH。安装依赖需要互联网；安装过程不访问校园网，不自动登录或启动服务。
**安装后请保留项目目录和 `.venv`，管理命令及服务直接引用这里的文件。**
上面的 PATH 设置只影响当前终端。需要长期生效时，将同一行加入 Bash 的 `~/.bashrc`
或 Zsh 的 `~/.zshrc`，然后重新打开终端。

```bash
ysu config account          # 交互输入账号密码（密码不回显）
ysu service                 # 选择校园网 / 移动 / 联通 / 电信
ysu doctor                  # 仅检查本地环境
ysu login                   # 在校园网内手动验证登录
ysu on                      # 开启后台自动重连
ysu boot on                 # 可选：启用自启
```

直接执行 `ysu` 打开交互菜单；非交互终端中显示帮助。
无需安装命令也可运行 `uv run python ysu.py <命令>`。

终端输出会用颜色区分成功、提示和失败；菜单显示当前服务及账号配置状态，进入菜单不会自动访问网络。
耗时操作会显示等待提示，诊断会汇总通过和待处理项。设置 `NO_COLOR=1` 或 `TERM=dumb` 可关闭颜色，
重定向或管道输出自动使用纯文本。`status/info --raw` 只输出原始 JSON，不附加标题或进度信息。
`ysu config show` 在终端中显示中文配置摘要，重定向时保留 JSON；也可用 `ysu config show --raw` 显式获取 JSON。

其他安装方式：

```bash
bash install.sh --browser       # 额外安装 Playwright 和 Chromium
bash install.sh --no-service    # 只安装命令，适合没有 systemd / 用户总线的环境
bash install.sh --offline       # 使用已有 uv、Python 和依赖缓存；不联网下载
sudo env PATH="$PATH" bash install.sh --system  # 系统级服务
```

系统级安装的命令位于 `/usr/local/bin`，配置位于 `/etc/ysu-net/config.json`；
使用 `sudo ysu ...` 管理。系统服务以 root 运行，应使用可信且受控的项目目录。
用户级配置位于 `${XDG_CONFIG_HOME:-~/.config}/ysu-net/config.json`。
同一台机器建议只启用一种安装范围，避免两个服务同时操作校园网。

用户服务随用户管理器启动。需要在未登录时也自动连接，可由管理员执行
`sudo loginctl enable-linger <用户名>`；安装器不会自动修改此系统设置。
如果 `systemctl --user` 无法连接用户总线，请登录本机用户会话，或使用 `--no-service`。

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
| `ysu service [服务名]` | 查看或切换运营商 |
| `ysu backend [api\|browser]` | 查看或切换认证实现 |
| `ysu config account` | 设置账号密码 |
| `ysu config show` / `ysu config path` | 查看脱敏配置 / 配置路径 |
| `ysu config set <配置项> <值>` | 修改运行参数 |
| `ysu boot on\|off\|status` | 自启开关，与当前连接状态独立 |
| `ysu logs [-f] [-n 50]` | 查看 / 跟随 systemd 日志 |
| `ysu doctor [--network]` | 默认只检查本地；指定参数后查询校园网 |
| `ysu daemon [--once]` | 前台守护 / 单次检查，用 Ctrl+C 停止 |

切换服务不会立即断开当前连接。需要切换已在线连接时：设置服务 → `ysu off` → `ysu on`。
没有 systemd 时，`ysu daemon` 直接向终端输出日志，先结束前台守护才能手动登录或下线。
`on/stop/boot/logs` 管理 systemd 服务，不提供脱离终端的脚本进程管理器。

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

**修改账号或运营商：**

```bash
ysu stop
ysu config account      # 修改账号密码；只切换运营商时可跳过
ysu service 中国移动    # 也可使用：校园网 / 中国联通 / 中国电信
ysu off                 # 下线旧连接
ysu login               # 验证新配置
ysu on                  # 验证成功后恢复自动重连
```

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
不要将真实账号配置提交到仓库。原始脚本的 `--debug` 输出可能含会话信息，分享前需脱敏；
管理命令后台日志只记录固定状态消息，不记录原始认证响应。

退出码：`0` 成功/在线，`1` 明确离线（status），`2` 连接/查询/配置错误，
`3` 操作失败或超时，`4` 认证需要人工处理，`130` 用户取消。
`daemon --once` 的返回码只表示检查循环是否正常执行；网络结果记录在日志，查询网络状态请用 `status`。

## 浏览器方式与原始脚本

```bash
uv sync --locked --extra browser
uv run --extra browser playwright install chromium
ysu backend browser
```

在部分 Linux 发行版上可能需要额外安装 Chromium 系统依赖；浏览器安装命令失败时按 Playwright 提示处理。
`--offline --browser` 不下载浏览器，请预先准备匹配版本的 Playwright 运行时。
`uv sync` 默认只安装 API 依赖；使用浏览器时保留 `--extra browser`。

原始脚本继续可用，通用参数放在子命令后：

```bash
export YSU_USER="你的账号"
export YSU_PASS="你的密码"
uv run python ysu_api.py login --service 校园网
uv run python ysu_api.py status --raw
uv run python ysu_api.py logout
uv run --extra browser python ysu_browser.py login --service 校园网
```

原始脚本还支持 `shell`、`--interactive`、`--debug`，以及 `YSU_BASE`、`YSU_CAS_HOST`、
`YSU_VERIFY_TLS`、`YSU_TIMEOUT`（API）、`YSU_PORTAL_UA`、`YSU_VERSION`、`YSU_SAVE_DEBUG_FILES`。
管理入口的认证地址和 TLS 以 JSON 配置为准，不从上述同名环境变量覆盖。
`requirements.txt` 保留给旧版 pip 安装使用，新环境请以 `pyproject.toml` 和 `uv.lock` 为准。

## 更新、卸载与旧版迁移

在原项目目录更新。先停止重连，让代码和依赖更新完再启动；`ysu stop` 不会主动下线。

```bash
ysu stop
git pull --ff-only
bash install.sh                # 浏览器用户使用 bash install.sh --browser
ysu doctor
ysu on
```

系统级安装对应使用 `sudo ysu stop`、`sudo env PATH="$PATH" bash install.sh --system`
和 `sudo ysu on`，浏览器用户同样追加 `--browser`。前台模式先按 Ctrl+C 停止守护，
更新时保留 `--no-service`，最后重新运行 `ysu daemon`。
重新安装保留账号配置；如果 `git pull --ff-only` 提示存在本地修改或分支分歧，请先处理本地修改。

卸载命令：

```bash
bash uninstall.sh                  # 移除用户级服务和命令，保留账号配置
bash uninstall.sh --purge          # 同时删除配置
sudo env PATH="$PATH" bash uninstall.sh --system  # 系统级卸载
```

卸载会先停止服务，保留当前校园网连接、源码和 `.venv`；想下线先执行 `ysu off`。
重新安装保留现有账号配置，不覆盖其他软件的同名命令。

曾使用旧版 `ysu-net-auth-install.sh` 的用户，先运行
`bash ysu-net-auth-uninstall.sh` 停止旧服务，再用新安装器安装并重新配置账号。
旧版 `/etc/ysu-net-auth.env` 保留，不自动执行或导入到新配置；旧脚本仅保留兼容。

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

## 开发与 mock 验证

```bash
uv sync --locked --extra browser
uv run --extra browser python -m unittest discover -s tests -v
```

测试通过 mock 模拟 Portal 响应、CAS 认证、Playwright、systemd 和认证子进程，
安装卸载使用临时目录。测试基类禁止真实 socket 连接及 DNS 查询；不需要校园网、真实账号或浏览器运行时。
CI 同样只运行 mock 测试和 shell 语法检查。

**尚未在校园网实测。** 当前离线识别以现有协议中的
`portalOnlineUserInfo.message == "dx.failed.user.offline"` 为准；未知响应一律作为查询失败。
真实 CAS 页面、学校风控、网关延迟和各运营商返回格式仍需校园网环境验证。
不要根据 mock 测试通过推断真实网络已经可用。

认证流程仍为：Portal 获取 sessionId → CAS 统一认证 → 选择服务 → 上线并轮询确认；
下线时调用 Portal offline 接口并轮询，浏览器方式保留 UI 下线兜底。
