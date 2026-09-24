# 开发与验证

[返回首页](../README.md) · [使用与配置](usage.md) · [更新与迁移](migration.md)

## 模块职责

所有运行时代码位于 `src/ysu_net/`，通过安装包导入，不修改 `sys.path` 或依赖调用者的工作目录。
开发使用 uv 的可编辑安装；Linux 安装器仍直接引用项目 `.venv`，因此项目目录必须保留。

| 位置 | 职责 |
| --- | --- |
| `__main__.py` | 模块入口，与 `pyproject.toml` 声明的 `ysu` 命令调用同一个 CLI |
| `paths.py` | 定位可编辑安装的项目根目录，供安装器和认证进程使用 |
| `auth/api.py` | requests 实现的 Portal / CAS 认证、上线、下线和状态查询 |
| `auth/browser.py` | Playwright 认证及 UI 兜底 |
| `auth/common.py` | 协议状态判断、异常退出码、资源清理 |
| `manager/cli.py` | 命令分发和交互菜单 |
| `manager/ui.py` | 终端颜色、状态提示、纯文本兼容 |
| `manager/config.py` | 配置验证、环境变量覆盖、权限和原子保存 |
| `manager/backend.py` | 调用认证模块、进程组清理和总超时 |
| `manager/daemon.py` | 在线检查、退避重试和人工认证暂停 |
| `manager/locking.py` | 同一配置下的进程互斥 |
| `manager/service.py` | systemd 单元生成和服务管理 |
| `manager/install.py` | 安装 / 卸载命令包装器与服务 |

`install.sh` 和 `uninstall.sh` 是保留在根目录的用户入口，业务逻辑不放入 shell 文件。
认证进程通过 `python -m ysu_net.auth.api` 或 `python -m ysu_net.auth.browser` 启动，
安装包装器和 systemd 通过 `.venv/bin/python -m ysu_net` 进入管理命令。

## 环境与命令

```bash
uv sync --locked --extra browser
uv run ysu --help
uv run python -m ysu_net --help
uv run python -m ysu_net.auth.api --help
uv run --extra browser python -m ysu_net.auth.browser --help
```

`uv run ysu` 适用于项目开发；它不会自动安装 systemd 服务。
发布给本机日常使用时运行 `bash install.sh`；浏览器用户追加 `--browser`。
项目采用 `src` 布局，修改源码会立即反映到可编辑安装中；修改入口声明或依赖后重新 `uv sync`。

## 测试

```bash
uv run --extra browser python -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
uv lock --check
```

- `tests/test_protocol.py`：API 和浏览器认证、CAS 跳转、在线状态、退出码及资源清理。
- `tests/test_manager.py`：配置、重连、进程、CLI、安装卸载、systemd 单元及命令包装器。
- `tests/test_layout.py`：包入口、项目外调用和模块启动路径。
- `tests/helpers.py`：公共响应样本、临时目录和禁止联网的测试基类。

连接相关测试 mock Portal、CAS、Playwright 和认证子进程；测试基类禁止 socket 连接与 DNS 查询。
服务管理命令使用 mock，安装卸载在临时目录验证；可用时调用 `systemd-analyze verify`
做静态检查。测试不会注册或启动本机服务，不需要校园网、真实账号或浏览器运行时。

**默认 API 后端的校园网认证闭环已通过真实校内网络验收。** 覆盖 CAS 登录、独立在线查询、账户查询、下线、自动重连及单轮守护入口，详见[真实网络验收记录](live-test.md)。离线识别以实测协议中的
`portalOnlineUserInfo.message == "dx.failed.user.offline"` 为准，未知响应仍按查询失败处理。
中国移动已由增强版 `switch` 真实切换成功，独立查询服务与外网 HTTPS 均通过；此前会话上限错误及新版失败恢复由分离的真实记录与模拟测试说明。可选浏览器后端、验证码/风控、其他运营商及长稳运行仍未实测。
`manager/switching.py` 不持久化凭据；CLI 在成功后通过独立写锁合并服务字段。配置写锁与守护运行锁分开，避免破坏热更新或覆盖并发修改。

## 构建与依赖

```bash
uv build                       # 生成 dist/ 下的 wheel 和源码包
uv sync --locked               # 仅安装 API 依赖
uv sync --locked --extra browser
```

打包使用 Hatchling，`pyproject.toml` 是依赖和命令入口的唯一声明位置。
`uv.lock` 锁定应用依赖；构建依赖由 `[build-system]` 声明。
不再维护重复的 `requirements.txt`。`.venv/`、`dist/`、`build/` 和真实账号配置均不提交。
包可构建用于分发，Linux 服务安装当前仍以源码目录的可编辑安装为支持方式。

新增认证实现时，将协议实现放入 `auth/`，扩展配置允许的后端和 `manager/backend.py` 调用，
同时补充网络 mock 测试；不要让菜单、安装或默认诊断隐式访问校园网。
