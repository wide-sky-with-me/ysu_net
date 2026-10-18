# Tauri 原生 Rust 桌面版

[返回首页](../README.md) · [两个产品与架构](architecture.md) · [Rust 迁移决策](../.agents/notes/proposals/desktop/2026-10-14-rust-desktop.md) · [Qt 兼容版](desktop.md)

当前在 `feat/rust-desktop` 开发，尚未发布。图形版采用 Tauri 2 + Svelte + 全 Rust 认证和后台，Windows / Linux / macOS 共用源码。Python CLI、systemd、Qt 兼容入口及旧旁车源码保留，但新桌面不启动或打包 Python、Node、Playwright 认证运行时。

## 运行语义

[认证库](../desktop/crates/ysu-auth/src/lib.rs)实现 Portal/CAS、加密、状态、登录、下线、运营商切换及账户解析；[原生运行器](../desktop/src-tauri/src/runtime.rs)调度有界串行任务、重连、取消与快照。前端只提交类型化命令，排队确认不是认证成功。

连接与实际运营商以独立状态查询为准；查询失败保持未知，不触发自动登录。显式切换失败尝试有界恢复，只在确认目标服务后保存服务字段。用户认证操作及一次自动重连的查询、变更与核验共享配置的总超时；超时后提示重新查询实际状态。账户读取失败或超时只清理账户数据，不改连接状态；缺项、原文和零值按门户数据展示，不补造余额、额度或单位。

配置字段与 Python CLI 兼容；密码仅在本机配置保存，快照无密码字段，空密码保存保留原值。设置更新在独立短写锁下合并最新配置并原子替换，认证/守护使用兼容运行锁。环境变量 `YSU_USER`、`YSU_PASS`、`YSU_SERVICE` 保留原覆盖语义；修改磁盘值不覆盖仍生效的环境变量。

[多账号与流量换号](accounts.md)提供独立账号簿、确认后热切换与默认关闭的零流量轮换。前端不负责轮换调度；原生后台以同账号/服务绑定的独立查询为依据。关闭自动重连或下线同时关闭轮换，状态未知、额度缺失及业务失败不触发换号。

关闭窗口只有在系统托盘实际可用且启用驻留时保留后台；否则退出。主窗口销毁后可重建，认证和重连不依赖 WebView 存活。关闭自动重连不下线，忙碌时仍可关闭重连或退出；显式下线同时停止重连；退出取消本客户端任务并释放锁，不主动下线已建立的连接。`--minimized` 在无托盘环境显示窗口，避免应用隐身。

托盘与主窗口共用核心快照与串行任务入口。菜单展示连接状态、账号/运营商、IP、上次查询的额度和最近结果；可打开主窗口、连接/断开、刷新状态与账户、控制自动重连/换号或退出。状态未知时只查询，不从托盘猜测登录；缺少凭据时引导打开窗口设置。额度缺失或账号/运营商不匹配时显示待核验。

Windows/macOS 使用系统原生悬停提示；Windows 摘要按 UTF-16 长度限制收敛，完整信息保留在菜单。Linux 的 Tauri 托盘悬停提示和图标鼠标事件不受支持，以系统托盘菜单提供等价状态与操作，保留“打开主窗口”项。Linux 后台每十秒检查托盘宿主：宿主退出时恢复主窗口，防止后台失去入口；窗口聚焦时重新读取桌面能力。并发更新与平台选择见[托盘决策](../.agents/notes/implemented/desktop/2026-10-15-tray-control.md)。

自启使用 Tauri 原生插件，只在用户登录桌面后运行。Linux 无桌面运行继续使用 CLI/systemd；迁移时先关闭旧客户端自启，当前不自动删除旧启动项。新旧包身份与发行限制见[架构边界](architecture.md#构建与发行边界)。

## 浏览器模式

默认 API 模式直接使用 Rust HTTP、Cookie 和加密实现。可选浏览器模式由 Rust 通过 CDP 驱动本机 Edge / Chrome，使用专用临时目录，不复用个人浏览器资料，不下载 Node 或认证组件。需要系统已有可用 Chromium 系浏览器；验证码、风控或无法确定的页面状态返回需人工处理的结果，不伪造在线。

设置中的“刷新浏览器状态”和“运行本地诊断”仅检测环境，不发起登录。旧内部 `browser_install` 命令保留为刷新诊断的兼容入口，已无下载行为。CLI/Qt 的 Python 浏览器实现保持原流程，不将两种产品的运行依赖混为一谈。

## 构建前提

构建需要 Node 22.12 / 24 / 26 及更新受支持版本、Rust 和平台 SDK；以 [package.json](../desktop/package.json)、[Cargo.toml](../desktop/src-tauri/Cargo.toml)及锁文件为准。桌面构建本身不需要 Python、uv 或 PyInstaller；Python 仅用于 CLI 和外部验收脚本。

- Windows x64：Visual Studio C++ 桌面构建工具、Windows SDK；客户端使用系统 WebView2，安装器可按原配置引导安装。
- Linux x64：Ubuntu 22.04 / glibc 2.35 构建基线，依赖 WebKitGTK 4.1、GTK3、AppIndicator；SDK 清单见 [tauri.Dockerfile](../packaging/tauri.Dockerfile)。
- macOS：Apple Silicon / Intel 分别原生构建 `.app` / `.dmg`。本轮暂保留 13.5 的保守部署目标，不再以 Node 的运行要求作为理由；更早系统须独立验证后再调整。

跨系统安装包在对应系统构建。Windows/macOS、签名与公证是否通过，以实际验收记录为准，不依据框架支持推断。

```bash
npm ci --prefix desktop
npm --prefix desktop run native:build
# 指定本系统格式，例如 Linux：
npm --prefix desktop run native:build -- --bundles deb
# 开发应用 / 只准备图标 / 只编译程序：
npm --prefix desktop run native:dev
npm --prefix desktop run native:build -- --prepare-only
npm --prefix desktop run native:build -- --no-bundle
```

[构建入口](../desktop/scripts/desktop.mjs)核对桌面内部版本、生成图标，然后调用锁定依赖的 Tauri 构建。默认 Linux `deb`、Windows `nsis`、macOS `app,dmg`；产物位于 `desktop/src-tauri/target/release/bundle/`。图标、前端产物和目标目录是生成物。

[tauri_build.py](../packaging/tauri_build.py)仅为旧调用路径的转发兼容层，不再冻结旁车；优先使用以上原生入口。旧 `--api-only` 选项已停用，不应沿用 Python 驱动裁剪流程。直接运行 `tauri build` 前需先生成图标。

## 配置与演示

正常启动支持 `--config PATH` 或 `YSU_DESKTOP_CONFIG`。默认 Windows 使用 AppData/Roaming，Linux/macOS 沿用 `${XDG_CONFIG_HOME:-~/.config}/ysu-net/`。再次启动只聚焦同一实例，不改变既有配置或演示模式；更换模式前先退出。

`--demo` 或 `YSU_DESKTOP_DEMO=1` 使用临时样例配置，忽略传入真实路径及凭据环境变量。演示不认证、不启动系统浏览器、不下载组件、不修改系统自启；退出清理临时目录。演示账户、连接和浏览器可用状态为样例，不代表主机或校园网状态。

普通浏览器打开 Vite 地址只显示“等待桌面核心”，不模拟客户端。显式 `?demo=1` 才启用前端样例，可加 `theme=light|dark`、`accent=teal|blue|indigo|violet|rose|amber`、`scenario=offline|unknown|external|empty|busy`；`scenario=prefs-failure` 用于偏好保存失败回归。演示色仅在本页内存中生效，刷新重新按参数初始化，不写网页存储或真实设置。浏览器预览不代替原生运行器或 WebView 验收。

原生外观偏好沿用主配置相邻的 `gui.json` 与 `save_prefs`：可保存 `theme`、`accent`、`close_to_tray`，`auto_reconnect` 仍走专用操作。主题色参数严格白名单校验，非法请求不落盘；写入成功后快照更新选择。旧配置缺 `accent`、未知未来色或字段类型异常时，仅主题色回到默认 `teal`，保留其他有效偏好，读取不改原文件；下一次合法偏好保存会将回退值归一化落盘。命令行认证配置与账号簿不增加主题色字段。旧 Qt 回退界面忽略新增字段，其保存偏好会丢弃该字段，之后新桌面采用默认色；本轮不扩展历史回退界面的色板。三平台共用相同实现，视觉规则见[设计说明](rust-desktop-design.md)。

## 验证命令

```bash
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
npm --prefix desktop run build
cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --check
cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml
```

认证库普通测试使用本地回环 HTTP 样本、固定加密向量和协议状态，不访问校园网；另有需要系统 Chromium 的忽略测试，须显式运行 `cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml -- --ignored --test-threads=1`，普通测试通过不代表这些测试已执行。可用 `YSU_AUTH_CHROMIUM_PATH` 指定绝对可执行路径。原生测试覆盖运行器、配置、锁与演示；Python 回归按[开发说明](development.md#测试)单独执行，不合并技术栈成绩。

完整浏览器脚本为 [tauri_web_smoke.py](../packaging/tauri_web_smoke.py)，新设计与键盘回归为 [rust_desktop_preview.py](../desktop/tests/rust_desktop_preview.py)，多账号与忙碌控制为 [multi_account_preview.py](../desktop/tests/multi_account_preview.py)。启动已构建前端的 Vite preview 后传入 URL 与系统浏览器路径；覆盖确认、密码清空、账号增改删、异步快照、设置分区、无运行时下载、主题、日志、未知/外部状态和紧凑布局。

原生离线自检使用真实 Rust 主程序与 WebView，验证连接、切换、账户、重连、窗口关闭驻留/重建、托盘菜单原生属性回读、关闭窗口后的快捷操作、下线及退出清理。Linux 自检仅在没有实际宿主时创建受控 D-Bus watcher，验证关闭分支和宿主丢失恢复，不模拟真实桌面面板或鼠标悬停；另一个生命周期脚本在无宿主环境检查最小化启动回退、单实例和真实 X11 关闭请求。Linux 示例：

```bash
uv sync --locked --group desktop-test
dbus-run-session -- xvfb-run -a uv run --no-sync python packaging/tauri_smoke.py \
  --binary desktop/src-tauri/target/release/ysu-net --output dist/rust-desktop-smoke --capture-desktop
dbus-run-session -- xvfb-run -a uv run --no-sync python packaging/tauri_linux_lifecycle.py \
  --binary desktop/src-tauri/target/release/ysu-net --output dist/rust-desktop-smoke
```

截图只用于专用测试显示。Windows 传 `.exe`，macOS 传 `.app/Contents/MacOS/ysu-net`。脚本测量程序拥有的完整进程树，检查旧旁车及 Python/Node 认证进程缺席、退出清理。RSS 求和会重复共享页；PSS 可用时另记；短样本不作为稳态、认证峰值或跨机器性能比较。最小化 API 自检不代替带真实窗口管理器的桌面点击验证。当前界面、图标与原生证据见[界面细节修订验收](ui-polish-validation.md)，其中 Windows 侧用 CDP 驱动真实 Chrome 验证渲染与字体，Windows 原生二进制因本机无 Rust/MSVC 未构建。此前[品牌字标验收](brand-wordmark-validation.md)、[侧栏底部验收](sidebar-footer-validation.md)、[主题配色修订验收](theme-refinement-validation.md)、[文案精简验收](copy-cleanup-validation.md)、[主题色验收](accent-themes-validation.md)、[配色验收](color-palette-validation.md)、[流量状态标签验收](quota-status-validation.md)、[细节修正验收](desktop-detail-validation.md)、[FlClash 排版验收](flclash-layout-validation.md)与[托盘专项验收](tray-layout-validation.md)保留原貌。

[Tauri CI](../.github/workflows/tauri.yml)只上传构建和测试附件，不触发 Release。本次多账号、忙碌控制和原生包结果见[多账号验收](account-rotation-validation.md)，UI 来源与截图见[设计说明](rust-desktop-design.md)。此前 [Rust 迁移基线](rust-desktop-validation.md)、[Python 旁车验收](tauri-validation.md)及 [Clash 风格预览复核](tauri-verge-validation.md)均为历史证据，不作为当前包的本次成绩。
