# Tauri 离线验收：2026-10-14

[开发与构建说明](tauri-desktop.md) · [迁移决策](../.agents/notes/proposals/desktop/2026-10-14-tauri-migration.md)

本记录只覆盖本次工作区的 Linux 构建及离线行为，不代表发布或校园网验收。未提交、推送或更新任何 GitHub 发布附件。

## 环境和产物

宿主为 WSL2 Linux x86_64；在 Ubuntu 22.04 容器中以非 root 用户构建及运行，Python 3.12.15、Rust 1.99.0、Node 24.21.0、Tauri 2.12.3、Svelte 5 / Vite 8。原生运行使用独立 D-Bus 与 Xvfb，软件渲染，并关闭容器网络。没有安装或覆盖宿主桌面程序。

- Linux Debian 包：`desktop/src-tauri/target/release/bundle/deb/YSU Net_0.1.0_amd64.deb`，约 23.72 MiB。
- SHA-256：`4253aded76ae2600f88dca0c7909de2af530f896f8785b06d5dbe1fd5baf9aa2`。
- Qt-free 冻结旁车约 21.34 MiB。检查真实 CArchive 以及嵌入 PYZ 的模块目录，未包含 Qt / shiboken 或 Playwright Node 二进制；包含可选浏览器认证 JS。

最终包用 `dpkg-deb -x` 提取至 `build/tauri-installed/`，原生验收运行提取后的 `usr/bin/ysu-net`，不是仅运行源码或构建目录的替代程序。包内 Rust 程序与旁车邻接布局通过实际启动验证；未执行宿主系统安装升级。

## 已执行检查

| 检查 | 结果与边界 |
| --- | --- |
| 完整 Python 回归 | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q`，246 项通过，包含保留的 Qt 测试 |
| 无 Qt 后台与平台相关回归 | `PYTHONPATH=tests .venv/bin/python -m unittest test_desktop_core test_node_runtime test_system_browser -q`，63 项通过 |
| 前端类型与静态检查 | `npm --prefix desktop run check`，零错误、零警告 |
| 前端单元测试 | `npm --prefix desktop test`，22 项通过 |
| 前端发布构建 | Vite 构建通过；JS 约 86.62 kB，gzip 32.51 kB；不把此大小当作运行内存 |
| Rust 编译和协议测试 | `cargo check --locked`、`cargo test --locked`，4 项通过；最终源码 `cargo fmt --check` 通过 |
| 包构建和冻结自检 | `packaging/tauri_build.py --bundles deb` 通过，包括 UTF-8 认证帮助、冻结旁车 JSONL、临时演示配置、退出与版本检查 |
| 浏览器离线交互 | `packaging/tauri_web_smoke.py` 通过，未发起外部请求，零页面异常 |
| 原生包集成 | `packaging/tauri_smoke.py` 通过，实际冻结旁车、WebView DOM、后台和窗口生命周期均验证 |
| Linux 实际窗口事件 | `packaging/tauri_linux_lifecycle.py` 通过，无托盘下 `--minimized` 显示窗口、重复启动复用原核心、真实 `WM_DELETE_WINDOW` 退出并清理进程 |
| 新工作流静态校验 | `uvx --from actionlint-py actionlint .github/workflows/tauri.yml` 通过；未运行远端 Actions |

浏览器测试覆盖切换确认与取消、断开重连、账户、密码离开设置后清空、下载显式确认、诊断脱敏、浅深主题、日志筛选和复制、状态未知 / 外部管理 / 空配置 / 忙碌样本、紧凑窗口、不使用 Web Storage、普通浏览器不冒充原生连接。

原生集成覆盖登录、切换移动、账户查询、自动重连、界面渲染、销毁 WebView 后核心与连接继续存在、重建窗口恢复最新状态、下线关闭自动重连、退出后观察到的子进程全部结束。演示使用模拟认证；不证明校园网接口在此版本已真实验收。

开发期修正了演示模式显式配置路径未完全隔离的问题，保留测试验证真实配置字节不变、不生成真实偏好文件、不输出其账号密码。macOS 的本机浏览器发现、Node 双架构归档选择和校验通过 mock 测试，不等同于 macOS 实机结果。

## 内存结论

`dist/tauri-smoke/acceptance.json` 保存最终包的完整进程树样本；包含 Rust/GTK、Python 冻结启动器及核心、WebKit 网络与渲染进程。关闭窗口后确认渲染进程退出，但 GTK 壳、核心和 WebKit 网络进程仍保留。

最终一次软件渲染样本的可见 PSS 为 251.32 MiB、后台为 153.48 MiB；对应短时单核 CPU 样本为 3.07% / 0%。每段采样约 0.65 秒，精度与覆盖有限，不作为稳态性能指标或认证峰值。RSS 求和包含共享页重复计数。

这组数据没有证明比此前 Qt 样本更省内存；历史 Qt 使用不同的 offscreen 渲染和采样方式，也不是严格同条件对照。当前收益是现代界面、较小的独立包及可回收 WebView，而不是已达成更低常驻内存。真实桌面渲染、长时空闲、反复开关窗口与浏览器认证峰值仍待测量。

Tauri 锁定版本在 Linux 有意保留默认 WebContext 以复用 WebKit 网络进程；不通过反复创建私有上下文规避它，以免引入上下文和网络进程累积风险。此为依赖源码解释，不替代反复开关窗口的压力验收。

## 失败与修正

初次 Rust 编译暴露自启插件动态参数的所有权 / 生命周期错误，改用持有参数的 Builder 后编译及原生验收通过。浏览器测试曾把“空配置”错误预期为在线，按实际离线语义修正断言后通过，未更改产品行为来迁就测试。

初次容器原生运行因 UID 无用户数据库条目导致 D-Bus 启动失败，属于测试 SDK 配置；补充非 root 用户元数据后复测通过，Dockerfile 同步支持构建用户 UID/GID。工作流静态检查发现未使用的就绪循环变量，补充最后一次失败输出及明确退出后通过。

完整 Python 回归退出阶段出现一次 GC `ResourceWarning`（一个不可回收对象），未定位；保留原始事实，不声称旧 Qt 的对象清理或内存问题已经解决。

## 待验收

Windows、macOS 双架构只有构建适配、CI 定义和相关 mock 测试，没有本次实机或远端 CI 成绩。真实校园网认证、运营商实际切换与恢复、浏览器认证、系统登录自启、不同桌面托盘、安装升级和签名公证均需独立验证。

演示不改系统自启或真实账号；未为测试登录校园网、下载完整浏览器或触发真实下线。旧 CLI / Qt 源码与发布流程保留。

## 本地产物

- `dist/tauri-smoke/acceptance.json`、`native-report.json`、`linux-lifecycle.json`：原生行为、进程采样与清理结果。
- `dist/tauri-smoke/native-visible.png`：从最终包运行时捕获的原生窗口，数据为明确标注的离线模拟。
- `dist/tauri-preview/browser-report.json` 及浅深色截图：浏览器交互证据，不冒充原生进程测试。

产物目录按项目规则忽略，不提交原始运行日志或安装包。重复执行会替换这些本地证据，本文记录的包哈希与命令用于区分本次结果。
