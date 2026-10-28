# 开发与验证

[返回首页](../README.md) · [产品与架构](architecture.md) · [使用与配置](usage.md) · [更新与迁移](migration.md)

## 模块职责

Python 运行时代码位于 `src/ysu_net/`，通过安装包导入，不修改 `sys.path` 或依赖调用者的工作目录。三平台共用的 Svelte 前端与 Rust 原生壳位于仓库根 `desktop/`；整体边界见[项目架构](architecture.md)。下表的 Python 模块路径均相对 `src/ysu_net/`。
云端测试使用 uv 的可编辑安装；Linux 安装器仍直接引用项目 `.venv`，因此项目目录必须保留。

| 位置 | 职责 |
| --- | --- |
| `__main__.py` | 模块入口，与 `pyproject.toml` 声明的 `ysu` 命令调用同一个 CLI |
| `paths.py` | 定位可编辑安装的项目根目录，供安装器和认证进程使用 |
| `auth/api.py` | requests 实现的 Portal / CAS 认证、上线、下线和状态查询 |
| `auth/dns_fallback.py`、`auth/campus-addresses.json` | 默认 API 自有连接的 DNS 失败回退与跨语言共享地址数据；Rust resolver 编译时嵌入同一 JSON |
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
| `auth/node_runtime.py` | 浏览器认证所需 Node.js 的查找 |

`install.sh` 和 `uninstall.sh` 是保留在根目录的用户入口，业务逻辑不放入 shell 文件。
认证进程通过 `python -m ysu_net.auth.api` 或 `python -m ysu_net.auth.browser` 启动，
安装包装器通过 `.venv/bin/python -P -m ysu_net` 进入管理命令，避免调用目录中的同名旧模块或包遮蔽已安装程序；`-P` 不改工作目录，保留可编辑安装和显式 `PYTHONPATH`。systemd 使用项目解释器绝对路径执行 `.venv/bin/python -m ysu_net`，未指定工作目录；迁移时需移走用户主目录的同名旧模块，避免用户服务解析到它。

## 环境与命令

本页的依赖准备、构建和产品测试命令仅在 GitHub Actions runner 执行，不是本机操作清单。本机只下载、校验云端产物并安装或运行；纯文档修改只做静态核对，不编译、不运行产品测试，也不启动开发或预览服务。

```bash
# 仅在 GitHub Actions runner 执行：
uv sync --locked --extra browser
uv run ysu --help
uv run python -m ysu_net --help
uv run python -m ysu_net.auth.api --help
uv run --extra browser python -m ysu_net.auth.browser --help
```

`uv run ysu` 用于 runner 中的源码检查，不会自动安装 systemd 服务。项目采用 `src` 布局，可编辑安装用于云端测试；修改入口声明或依赖后在 runner 重新 `uv sync`。Linux CLI 的既有安装方式与目录保留要求见[首页](../README.md#快速开始)，不在本机用源码重建代替云端产物。

## 测试

以下产品测试仅在 GitHub Actions runner 执行。全量 `tests/` 包含真实差分 CLI 验签集成，Linux runner 除 uv 环境外还须准备 qbsdiff/qbspatch 与 Minisign；统一由[公共差分工具 action](../.github/actions/setup-delta-tools/action.yml)固定版本、来源与摘要，缺失仍硬失败，不通过跳过测试掩盖依赖问题。

```bash
# 仅在 GitHub Actions runner 执行：
uv run --extra browser python -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
uv lock --check
```

- `tests/test_protocol.py`：API 和浏览器认证、CAS 跳转、在线状态、退出码及资源清理。
- `tests/test_dns_fallback.py` 与 Rust `dns_tests.rs`：DNS 成功优先、精确域名、失败 / 超时回退和原 Host / URL / 端口；Python 另用临时自签证书及回环 TLS 服务验证 SNI、Cookie、Origin、单次 POST 与错误域名证书拒绝。此文件的 TLS 类仅连接回环，不继承禁止一切 socket 的基类；其他类仍禁止联网。Mock runner 必须提供 OpenSSL，构建后检查 wheel 内共享 JSON 与源码逐字节一致。本轮新增测试尚未云端运行。
- `tests/test_manager.py`：配置、重连、进程、CLI、安装卸载、systemd 单元及命令包装器。
- `tests/test_switching.py`：服务一致性、切换失败恢复、配置并发更新和脱敏错误分类。
- `tests/test_account_info.py`：共享账户实现、嵌套响应、缺失值与零值、原始 JSON 兼容及诊断。
- `tests/test_menu_help.py`：说明页入口、选项覆盖、返回菜单以及无操作副作用。
- `tests/test_repository.py`：在临时 Git 仓库验证敏感文件忽略规则，不修改项目索引。
- `tests/test_layout.py`：包入口、项目外调用，以及 user/system 三个包装命令对同名模块和包的启动隔离。
- `tests/fixtures/online-service.json`：Python/Rust 共用服务字段兼容样本，覆盖缺失、`null`、未知值、类型异常、冲突及账号证据的严格校验。
- `tests/fixtures/cas-login-methods.json` 与 `portal-action-results.json`：123 采样后重建的合成表单 / 业务拒绝合同；Python `test_live_contracts.py` 与 Rust `live_contract_tests.rs` 共用，验证其他登录方式的验证码不误判、服务拒绝后不激活。源码已补，云端待验，真实边界见[123 记录](portal-123-review-2026-10-27.md)。
- [`tests/fixtures/portal-navigation.json`](../tests/fixtures/portal-navigation.json)：旧门户引导的 Python/Rust 共享样本；Rust 在专用 GET 引导中规范化可信旧地址，不发送 HTTP，也不放宽通用 API/CAS/POST 边界。精确条件和负例见 [`transport.rs::portal_navigation_target`](../desktop/crates/ysu-auth/src/transport.rs) 与认证库回归。
- Rust `captive_tests.rs`、`regression_tests.rs` 与 `browser.rs` 内部导航回归：共用 Location / HTML 解析、匿名 captive 单次限制，以及交给 Chromium 的受控 HTTPS 重定向和上下文负例；新增测试待云端执行，依据及真实采样限制见[Shell 跳转对照](portal-redirect-parity-2026-10-28.md)。
- `tests/test_system_browser.py`：系统浏览器查找、Snap 排除与启动回退。
- `tests/test_node_runtime.py`：Node.js 运行时查找顺序与缺失时的报错。
- `tests/helpers.py`：公共响应样本、临时目录和禁止联网的测试基类。

[Mock tests](../.github/workflows/test.yml)负责完整 Python 回归与分发构建，[Tauri CI](../.github/workflows/tauri.yml)负责四平台原生矩阵与独立浏览器验收，[差分预检](../.github/workflows/updater-delta-preflight.yml)解析依赖锁并生成或检查公开夹具；涉及差分的三个入口复用相同公共工具准备。社区文档另由[社区检查](../.github/workflows/community.yml)验证。不能仅凭一条工作流成功宣称全部 CI 通过。

开发源码另有[无界面 Rust 认证入口及独立 CI](rust-auth-probe.md)：直接调用共用 AuthClient，在四目标 runner 运行认证库、example 单元测试和实际二进制输入拒绝验收后保留带摘要的开发产物。无需 Tauri / WebView 即可在真实机器定位导航与动作，但本轮工作流和新源码尚未运行；它不替代 Tauri 的 Chromium、原生安装或界面门禁。

[21 账号池实测](account-pool-21-review-2026-10-28.md)验证 Shell 直接与守护热切换。Rust 对应的 `account_runtime_tests.rs` 直接运行 Worker / Store，用测试后端事件及查询门闩核对跨服务顺序、核验前配置未提交、失败恢复和固定诊断保留；这些新回归尚未执行，归 Tauri CI，不归只调用 AuthClient 的独立探针。

Svelte、Rust 与原生集成的命令见[Tauri 开发说明](tauri-desktop.md#验证命令)，按不同栈分别报告覆盖范围。Python 两个后端的账户展示统一在 `auth/account.py` 修改；Rust 对应实现位于 `desktop/crates/ysu-auth/`，协议或展示语义变更需同时补相应回归。

连接相关测试 mock Portal、CAS、Playwright 和认证子进程；测试基类禁止 socket 连接与 DNS 查询。上列 DNS 回退的 TLS 集成类显式例外，仅允许回环地址并拦截外部域名解析，不连接校园网。
服务管理命令使用 mock，安装卸载在临时目录验证；可用时调用 `systemd-analyze verify`
做静态检查。测试不会注册或启动本机服务，不需要校园网、真实账号或浏览器运行时。

**默认 API 后端的校园网认证闭环已通过真实校内网络验收。** 覆盖 CAS 登录、独立在线查询、账户查询、下线、自动重连及单轮守护入口，详见[真实网络验收记录](live-test.md)。离线识别以实测协议中的
`portalOnlineUserInfo.message == "dx.failed.user.offline"` 为准，未知响应仍按查询失败处理。
中国移动已由增强版 `switch` 真实切换成功，独立查询服务与外网 HTTPS 均通过；用户级 systemd 安装、真实重连、崩溃恢复及重装保留配置也已[实测验收](deployment-test.md)。此前会话上限错误及新版切换失败恢复由分离的真实记录与模拟测试说明。可选浏览器后端、验证码/风控、其他运营商、服务器重启及长稳运行仍未实测。
独立历史验收另见 [2026-10-20 Shell 真实复测](shell-live-2026-10-20.md)与 [2026-10-21 Windows 原生只读修复及复装验收](windows-readonly-fix-2026-10-21.md)；较新的桌面本地与远端结果集中见[桌面验收记录](tauri-desktop.md#验收记录)。历史运营商上线成绩不代表当前账号的可用会话。
2026-10-28 的[21 同机 Shell 对照](portal-21-review-2026-10-28.md)补齐现有客户端及正式 v0.2.2 云端包的移动服务离线登录 / 在线退出；它没有覆盖新 Rust 或 DNS 回退源码，也未复现 123 的相同配置条件。
`manager/switching.py` 不持久化凭据；CLI 在成功后通过独立写锁合并服务字段。配置写锁与守护运行锁分开，避免破坏热更新或覆盖并发修改。

### Tauri CI 并行门禁

当前工作流源码将四目标 `build` 与独立 Linux `browser-acceptance` 并行，彼此无 needs；后者完整承接原十脚本浏览器验收，顺序、参数、输出、回环 / strictPort、有界启动与退出清理不变。新 job 自备 Node / uv、锁定依赖、前端 build、字体 / ffmpeg 和可执行 Chrome，不注入签名 Secret；独立 `rust-desktop-preview-linux-x64` artifact 以 always 保留预览证据与启动日志。

原生矩阵仍执行前端 / Rust、四平台 Chrome 认证夹具、Native / 安装、签名及工具硬失败门槛。正式 `release` 仍限定 v 标签且同时 needs `[build, browser-acceptance]`，任一失败或取消都不能发布；不以 always / continue-on-error 绕过。`format_only=true` 跳过两条产品 job，只走原 `format-source`；产品 job 的 45 分钟上限不减。

本阶段只改排程，没有修改 Cargo / profile / cache / target 或削减测试；新候选 `7c876513` 已通过云端 Mock、四平台 Native 与独立浏览器验收。Linux SDK 下载异常后的定向复跑污染了整体耗时对照，不据此宣称稳定提速；基线、代价与实际结果见[本轮记录](ci-parallel-acceptance-2026-10-27.md)，为何先拆关键路径见[并行决策](../.agents/notes/implemented/ci/2026-10-27-parallel-browser-acceptance.md)。

## 构建与依赖

以下打包与依赖准备仅在 GitHub Actions runner 执行：

```bash
# 仅在 GitHub Actions runner 执行：
uv build                       # 生成 dist/ 下的 wheel 和源码包
uv sync --locked               # 仅安装 API 依赖
uv sync --locked --extra browser
```

Python 分发使用 Hatchling，`pyproject.toml` 声明 Python 依赖和 `ysu` 命令；`uv.lock` 锁定应用依赖，`[build-system]` 声明 Python 构建依赖。Mock CI 在回归、构建和共享数据检查成功后将 wheel / 源码包保留为 `ysu-net-python-dev` artifact（7 天），供下载校验与运行验收，不发布 Release。前端依赖与原生配置分别属于 `desktop/package.json` 和 `desktop/src-tauri/`，不是 Python 命令声明的一部分。
不再维护重复的 `requirements.txt`。`.venv/`、`dist/`、`build/` 和真实账号配置均不提交。
包可构建用于分发，Linux 服务安装当前仍以源码目录的可编辑安装为支持方式。

### 桌面构建

Windows / Linux / macOS 桌面共用 Tauri + Rust 原生构建入口，不再冻结 Python 认证旁车；平台 SDK、安装包和无 Python 构建命令均面向 GitHub Actions runner，见[Tauri 开发说明](tauri-desktop.md#构建前提)。本机不需要为下载、安装或运行云端产物准备构建 SDK，也不启动 Vite preview。`desktop-test` 依赖组仅供云端外部浏览器/进程验收，不是 GUI 构建或运行依赖。推送 `v*` 标签时，Tauri 工作流通过[上述双门禁](#tauri-ci-并行门禁)后，连同 runner 上 `uv build` 生成的 wheel 与源码包一起发布，并生成 `SHA256SUMS`；开发构建使用独立分支，不打版本标签、不发布正式 Release，发行边界见[项目架构](architecture.md#构建与发行边界)。

### 本地构建产物清理

以下仅说明历史目录的保护边界，不要求清理或恢复本地构建。可重建输出包括 Cargo 的 `desktop/src-tauri/target/`、`desktop/crates/ysu-auth/target/` 和自定义 `CARGO_TARGET_DIR`（历史路径可为 `build/tauri-target/`），Vite 输出 `desktop/dist/`，以及依赖目录内的 `.vite/`、`.vitest-cache/` 和 `.vite-temp/`。清理须另行授权，并逐项核对实际绝对路径、无符号链接、Git 忽略且不含跟踪文件，确认没有进程使用它们。

先保留安装包、校验和、原始 JSON 与关键验收截图，再清理编译中间产物；本地历史证据和交付物不因被 Git 忽略就自动视为垃圾。不要整目录删除 `build/` 或 `dist/`，也不要使用无差别的 `git clean -fdX`：忽略规则同时覆盖配置、环境文件、私钥、Cookie 和运行环境。

保留项目 `.venv/`、`desktop/node_modules/` 的依赖主体、既有 SDK / 编译工具链及各依赖锁文件；已安装的 Linux CLI / 服务仍引用项目目录与 `.venv`，这不构成本机编译许可。若需补回前端或原生产物，应重新下载并校验云端产物，不在本机重建；清理不等于卸载系统中的客户端或服务。

敏感资料与发布前检查流程见[敏感信息与发布检查](security.md)。忽略规则只防止误提交，不能替代内容检查；云端构建后还要在 runner 检查 wheel 和源码包的文件清单与内容。

新增认证实现时，将协议实现放入 `auth/`，扩展配置允许的后端和 `manager/backend.py` 调用，
同时补充网络 mock 测试；不要让菜单、安装或默认诊断隐式访问校园网。
