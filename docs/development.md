# 开发与验证

[返回首页](../README.md) · [产品与架构](architecture.md) · [使用与配置](usage.md) · [更新与迁移](migration.md)

## 模块职责

Python 运行时代码位于 `src/ysu_net/`，通过安装包导入，不修改 `sys.path` 或依赖调用者的工作目录。三平台共用的 Svelte 前端与 Rust 原生壳位于仓库根 `desktop/`；整体边界见[项目架构](architecture.md)。下表的 Python 模块路径均相对 `src/ysu_net/`。
开发使用 uv 的可编辑安装；Linux 安装器仍直接引用项目 `.venv`，因此项目目录必须保留。

| 位置 | 职责 |
| --- | --- |
| `__main__.py` | 模块入口，与 `pyproject.toml` 声明的 `ysu` 命令调用同一个 CLI |
| `paths.py` | 定位可编辑安装的项目根目录，供安装器和认证进程使用 |
| `auth/api.py` | requests 实现的 Portal / CAS 认证、上线、下线和状态查询 |
| `auth/browser.py` | Playwright 认证及 UI 兜底 |
| `auth/common.py` | 协议状态判断、异常退出码、资源清理 |
| `auth/account.py` | 两个后端共用的账户解析、纯文本展示、缺失额度与零值处理 |
| `manager/cli.py` | 命令分发和交互菜单 |
| `manager/ui.py` | 终端颜色、状态提示、纯文本兼容和只读菜单说明 |
| `manager/switching.py` | 显式运营商切换、独立核验及有限失败恢复 |
| `manager/config.py` | 配置验证、环境变量覆盖、权限和原子保存 |
| `manager/backend.py` | 调用认证模块、进程组清理和总超时 |
| `manager/daemon.py` | 在线检查、退避重试和人工认证暂停 |
| `manager/locking.py` | 同一配置下的进程互斥 |
| `manager/service.py` | systemd 单元生成和服务管理 |
| `manager/install.py` | 安装 / 卸载命令包装器与服务 |
| `auth/system_browser.py` | 查找本机 Edge / Chrome，供浏览器认证在缺少 Playwright Chromium 时使用 |
| `auth/node_runtime.py` | 浏览器认证所需 Node.js 的查找与按需下载（固定版本、SHA-256 校验） |
| `auth/worker.py` | 打包后的程序以 `--ysu-auth` 重新进入自身，运行认证模块 |
| `gui/engine.py` | 旧 Qt 与保留 JSONL 原型使用的无 Qt 后台线程；新 Rust 桌面不调用 |
| `gui/window.py` | 旧 Qt 主窗口、各页面与系统托盘 |
| `gui/widgets.py`、`gui/theme.py`、`gui/icons.py` | 旧 Qt 控件、样式与图标 |
| `gui/prefs.py` | Qt / JSONL 原型的偏好读写及 Qt 自启适配；Rust 配置层保持格式兼容 |
| `gui/app.py` | Qt 兼容命令 `ysu-gui`、单实例和字体设置 |
| `desktop/app.py`、`desktop/__main__.py` | JSONL 旁车启动与关闭，不是图形窗口入口 |
| `desktop/core.py`、`desktop/protocol.py` | 无 Qt 桌面状态、快照、命令校验与协议 |
| `desktop/demo.py` | 隔离的离线演示后端 |

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
- `tests/test_switching.py`：服务一致性、切换失败恢复、配置并发更新和脱敏错误分类。
- `tests/test_account_info.py`：共享账户实现、嵌套响应、缺失值与零值、原始 JSON 兼容及诊断。
- `tests/test_menu_help.py`：说明页入口、选项覆盖、返回菜单以及无操作副作用。
- `tests/test_repository.py`：在临时 Git 仓库验证敏感文件忽略规则，不修改项目索引。
- `tests/test_layout.py`：包入口、项目外调用和模块启动路径。
- `tests/test_gui.py`：图形界面引擎、锁冲突、偏好与自启、打包入口，以及可选的离屏窗口冒烟测试（未安装 PySide6 时跳过）。
- `tests/test_system_browser.py`：系统浏览器查找、Snap 排除与启动回退。
- `tests/test_node_runtime.py`：Node.js 运行时查找顺序、镜像回退、校验失败与取消下载。
- `tests/test_desktop_core.py`：无 Qt 旁车协议、演示隔离、并发状态、凭据脱敏与退出清理。
- `tests/helpers.py`：公共响应样本、临时目录和禁止联网的测试基类。

执行旧 Qt 窗口测试需安装 gui extra 并设置 `QT_QPA_PLATFORM=offscreen`；未安装时相关测试跳过。Svelte、Rust 与原生集成的命令见[Tauri 开发说明](tauri-desktop.md#验证命令)，按不同栈分别报告覆盖范围。Python 两个后端的账户展示统一在 `auth/account.py` 修改；Rust 对应实现位于 `desktop/crates/ysu-auth/`，协议或展示语义变更需同时补相应回归。

连接相关测试 mock Portal、CAS、Playwright 和认证子进程；测试基类禁止 socket 连接与 DNS 查询。
服务管理命令使用 mock，安装卸载在临时目录验证；可用时调用 `systemd-analyze verify`
做静态检查。测试不会注册或启动本机服务，不需要校园网、真实账号或浏览器运行时。

**默认 API 后端的校园网认证闭环已通过真实校内网络验收。** 覆盖 CAS 登录、独立在线查询、账户查询、下线、自动重连及单轮守护入口，详见[真实网络验收记录](live-test.md)。离线识别以实测协议中的
`portalOnlineUserInfo.message == "dx.failed.user.offline"` 为准，未知响应仍按查询失败处理。
中国移动已由增强版 `switch` 真实切换成功，独立查询服务与外网 HTTPS 均通过；用户级 systemd 安装、真实重连、崩溃恢复及重装保留配置也已[实测验收](deployment-test.md)。此前会话上限错误及新版切换失败恢复由分离的真实记录与模拟测试说明。可选浏览器后端、验证码/风控、其他运营商、服务器重启及长稳运行仍未实测。
`manager/switching.py` 不持久化凭据；CLI 在成功后通过独立写锁合并服务字段。配置写锁与守护运行锁分开，避免破坏热更新或覆盖并发修改。

## 构建与依赖

```bash
uv build                       # 生成 dist/ 下的 wheel 和源码包
uv sync --locked               # 仅安装 API 依赖
uv sync --locked --extra browser
```

Python 分发使用 Hatchling，`pyproject.toml` 声明 Python 依赖和 `ysu` / Qt 兼容命令；`uv.lock` 锁定应用依赖，`[build-system]` 声明 Python 构建依赖。前端依赖与原生配置分别属于 `desktop/package.json` 和 `desktop/src-tauri/`，不是 Python 命令声明的一部分。
不再维护重复的 `requirements.txt`。`.venv/`、`dist/`、`build/` 和真实账号配置均不提交。
包可构建用于分发，Linux 服务安装当前仍以源码目录的可编辑安装为支持方式。

### 桌面构建

Windows / Linux / macOS 桌面共用 Tauri + Rust 原生构建入口，不再冻结 Python 认证旁车；平台 SDK、安装包和无 Python 构建命令见[Tauri 开发说明](tauri-desktop.md#构建前提)。`desktop-test` 依赖组仅供外部浏览器/进程验收，不是 GUI 构建或运行依赖。本节以下仅说明保留的 Qt 兼容构建；发行边界见[项目架构](architecture.md#构建与发行边界)。

### Qt 兼容版安装包

```bash
uv sync --locked --extra gui --group build
uv run python packaging/build.py --installer
```

`packaging/build.py` 用 PyInstaller 生成单目录程序，并先检查打包后的认证入口能输出 UTF-8 中文，
然后在 Windows 上生成便携 zip 和 Inno Setup 安装程序（`packaging/ysu-net.iss`），在 Ubuntu 上生成 tar.gz 和 `.deb`。
打包后会删除 Playwright 自带的 Node.js（改为按需下载），在 Linux 上还会删除 Ubuntu 已自带的系统库和 GTK 主题插件，
`.deb` 的依赖由 `ldd` 与 `dpkg -S` 自动生成；随后以隔离的配置目录做冒烟测试：认证入口、`--smoke` 界面启动，
以及（设置 `YSU_BROWSER_CHECK=1` 时）“未安装提示 → 下载组件 → 调用系统浏览器”的完整流程。
PyInstaller 不支持跨平台构建，两个系统的安装包由 `.github/workflows/desktop.yml` 分别在对应 runner 上构建。
标签构建的发布任务还会执行 `uv build`，生成 Python wheel 与源码包，并为所有桌面和 Python 附件生成 `SHA256SUMS`；仅在两个平台构建与安装验证成功后创建 Release。
Ubuntu 包在 22.04 上构建，以兼容较旧的 glibc。

敏感资料与发布前检查流程见[敏感信息与发布检查](security.md)。忽略规则只防止误提交，不能替代内容检查；构建后还要检查 wheel 和源码包的文件清单与内容。

新增认证实现时，将协议实现放入 `auth/`，扩展配置允许的后端和 `manager/backend.py` 调用，
同时补充网络 mock 测试；不要让菜单、安装或默认诊断隐式访问校园网。
