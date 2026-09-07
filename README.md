# ysu-net · 燕山大学校园网管理工具

通过 `ysu` 统一管理校园网登录、下线、自动重连、账号配置、开机自启和日志。
交互方式参考 [clash-for-linux](https://github.com/wnlen/clash-for-linux)，认证仍使用本项目的 Portal / CAS 实现。

支持 Linux + Python 3.12；后台服务使用 systemd。没有 systemd 的环境可使用前台守护。
默认采用轻量 API 认证，Playwright 浏览器认证按需安装。

当前验证范围为本地 mock 测试及 systemd 单元静态检查，尚未在校园网实测。
可以先在非校园网环境安装、配置和运行 `ysu doctor`；登录和真实状态查询需要接入校园网。

## 快速开始

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
只安装 Python 环境而不注册服务：`uv sync --locked`，然后运行 `uv run ysu <命令>`。
也支持 `uv run python -m ysu_net <命令>`；安装注册后的 `ysu` 可从任意目录运行。

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

## 项目结构

```text
ysu_net/
├── src/ysu_net/          # Python 包
│   ├── __main__.py      # python -m ysu_net 入口
│   ├── paths.py         # 项目路径
│   ├── auth/            # API / 浏览器认证及协议工具
│   └── manager/         # CLI、配置、守护、安装、systemd、终端展示
├── tests/               # mock 测试与本地入口检查
├── docs/                # 使用、迁移、开发文档
├── .github/workflows/   # CI 检查
├── install.sh           # 用户安装入口
├── uninstall.sh         # 用户卸载入口
├── pyproject.toml       # 包配置、依赖及 ysu 命令声明
├── uv.lock              # 锁定依赖
├── .python-version      # Python 版本
├── README.md
└── LICENSE
```

账号配置、锁文件位于用户或系统配置目录，`.venv` 和构建产物不提交到仓库。
旧版根目录认证脚本、守护脚本及 `requirements.txt` 已移除，迁移方式见下文链接。

## 文档导航

- [使用与配置](docs/usage.md)：完整命令表、日常操作、配置参数、浏览器方式和故障排查。
- [更新、卸载与旧版迁移](docs/migration.md)：升级后的命令重装、旧服务清理和入口变更。
- [开发与验证](docs/development.md)：模块职责、mock 测试、打包及新增认证实现。

## 本地验证

```bash
uv sync --locked --extra browser
uv run --extra browser python -m unittest discover -s tests -v
```

连接相关测试使用 mock，不需要校园网、真实账号或浏览器运行时。实际 CAS 页面、风控及运营商返回格式仍需校园网实测。
