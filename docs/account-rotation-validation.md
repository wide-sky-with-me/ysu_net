# 多账号离线验收

日期：2026-10-14。范围：`feat/rust-desktop` 未提交工作树；只使用合成账号、回环 HTTP/CDP、隔离配置和演示后台。没有操作真实账号、安装应用、提交、推送或发布。使用方式见[多账号说明](accounts.md)，选择理由见[决策](../.agents/notes/proposals/accounts/2026-10-14-account-rotation.md)。

## 实现与覆盖

Rust 桌面新增[账号存储](../desktop/src-tauri/src/accounts.rs)、[串行切换及轮换](../desktop/src-tauri/src/account_runtime.rs)和[账号管理组件](../desktop/src/components/AccountBook.svelte)。Python CLI/守护使用[同一 JSON 契约](../src/ysu_net/manager/accounts.py)与[独立调度](../src/ysu_net/manager/account_switching.py)，旧 Qt 引擎接入所有者控制通道，不新增账号簿视觉界面；Rust 不消费 Python 文件通道。

| 检查 | 本次结果 | 证据 |
| --- | --- | --- |
| Python 完整离线回归 | 393 通过，0 跳过 | [日志](../dist/account-rotation-validation/python-tests.log) |
| Rust 桌面运行时 | 67 通过 | [日志](../dist/account-rotation-validation/rust-runtime-tests.log) |
| Rust 认证库 | 65 通过；7 项浏览器测试单独运行 | [日志](../dist/account-rotation-validation/rust-auth-tests.log) |
| 系统 Chrome / Rust CDP | 7 通过，回环服务 | [日志](../dist/account-rotation-validation/rust-browser-tests.log) |
| Svelte / TypeScript | 0 错误、0 警告 | `npm --prefix desktop run check` |
| 前端协议与交互单元 | 42 通过 | `npm --prefix desktop test` |
| 原生构建契约 | 5 通过 | `npm --prefix desktop run test:build` |
| 新多账号浏览器交互 | 9 组交互、10 个布局截图；无页面/控制台/外部请求错误 | [报告](../dist/account-rotation-validation/browser-accounts/multi-account-report.json) |
| 原有设计与旧预览回归 | 保持通过 | [设计报告](../dist/account-rotation-validation/browser-design/frontend-design-report.json)、[旧预览报告](../dist/account-rotation-validation/browser-legacy/browser-report.json) |
| CLI 卸载兼容 | 后续修改后定向重跑 9 项通过；保留/清除账号簿及持锁保护 | [日志](../dist/account-rotation-validation/installer-tests.log) |
| 依赖与工作流 | `uv lock --check --offline`、`actionlint` 通过 | 仅静态检查，不代表三平台 CI 已执行 |

Python 完整测试退出时仍有一条 GC `ResourceWarning`，没有将其宣称已消除。上述计数包含既有测试，不等同全部是本功能新增测试。浏览器脚本使用前端演示适配器；原生和 CLI 的真实调度分别由对应集成与状态机测试覆盖。

## 审查与回归

[定向 Python 回归](../tests/test_multi_accounts_review.py)、[原生账号回归](../desktop/src-tauri/src/account_runtime_tests.rs)与[认证预检回归](../desktop/crates/ysu-auth/src/tests.rs)补齐以下反例：

- 外层业务失败、未知原始服务、显式外部 `userId` 即使同时带匹配显示名称，也不成为零流量证据。
- 最后核验与 prepare 之间源账号从 A 变 C 时，旧 A 证据不重新绑定到 C；在短写锁内比对预期身份，先于写簿、下线和登录停止。
- 下线前的首次及再次状态预检突然出现外层失败，均没有发出 OFFLINE 请求。
- 密码恰好等于用户名时，公开用户名仍唯一且可回传；公开配置及账号条目没有密码字段，自由文本继续脱敏。原生 WebView 自检使用两个这类合成账号。
- Python 保存的标签、用户名与密码边界对齐 Rust 校验；非法输入保留原文件。活动配置缺失密码时，Rust 在 overlay 后再次校验活动条目，不把无效覆盖写回原本有效的账号簿；[修复前反例](../dist/account-rotation-validation/rust-overlay-before.log)和存储回归保留。
- 候选新意图阻止旧恢复；过期、停用与重新开启打断零值链。
- 快速关闭再开启可能合并 watch 通知；运行中任务按控制代次取消，而非只读最终布尔值。[修复前失败日志](../dist/account-rotation-validation/rust-coalesced-before.log)与最终运行时回归保留断言。

[共享额度样本](../tests/fixtures/account-quota.json)含 84 个合成场景，两种语言使用同一原始输入及期望。自动换号的零值、冷却、候选选择与恢复使用确定性状态机测试；这不是实际校园网流量耗尽实测。`zero_reported` 只代表门户显示零，可能包含舍入。

## Linux 原生包

本机缺少 WebKitGTK 4.1，直接运行产物以动态库缺失退出 127；随后按既有方案在已准备的 Ubuntu 22.04 SDK 内、关闭网络的独立 D-Bus/Xvfb 会话验收，没有安装宿主动态库。验收监督脚本需要 psutil，项目 `.venv` 未含此依赖，使用既有 SDK 验收虚拟环境。

最终包、ELF 与源码哈希见[包元数据](../dist/account-rotation-validation/package.json)，内容见[包清单](../dist/account-rotation-validation/package-contents.txt)。当前包仍为开发用 `0.1.0`，不表示可与旧包并装或已处理升级、签名。此前 Rust 基线 deb 已保留到 `build/tauri-history/`，原[历史报告](rust-desktop-validation.md)结论不变；其同名可变产物路径不代表本次包。

构建目录与包内 ELF 的哈希分别保存；实际比较仅有 Tauri 包类型标记 `UNK` → `DEB` 的三个字节不同，按这个确切标记归一化后完全一致，不忽略其他差异。

[原生报告](../dist/account-rotation-validation/native/native-report.json)、[完整进程树验收](../dist/account-rotation-validation/native/acceptance.json)覆盖账号增改删、当前删除保护、核验后热切换、额度报告、轮换开关、下线同时停用、真实 WebView 快照解析、窗口销毁/重建与后台存活。[生命周期报告](../dist/account-rotation-validation/native/linux-lifecycle.json)另外覆盖无托盘最小化回退、单实例与原生关闭。

真实 WebView 使用正剩余额度演示，不把它当作零流量自动换号验收。进程树只含 Rust 主程序与 WebKit 子进程，没有 Python/Node/Chromium 认证旁车；监督脚本在应用进程树之外。软件渲染的短采样不作为稳态性能或版本比较。D-Bus 的未知子进程提示与各测试退出码分别核对。

## 复现入口

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -B -m unittest discover -s tests -v
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh cargo test --locked --offline --manifest-path desktop/src-tauri/Cargo.toml
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_TARGET_DIR=/workspace/build/rust-auth-target cargo test --locked --offline --manifest-path desktop/crates/ysu-auth/Cargo.toml
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs
```

原生检查从最终 deb 解包的程序启动：

```sh
dpkg-deb --extract 'desktop/src-tauri/target/release/bundle/deb/YSU Net_0.1.0_amd64.deb' dist/account-rotation-validation/package
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh dbus-run-session -- xvfb-run -a -s '-screen 0 1280x900x24' env LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 build/tauri-venv/bin/python packaging/tauri_smoke.py --binary dist/account-rotation-validation/package/usr/bin/ysu-net --output dist/account-rotation-validation/native --capture-desktop
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh dbus-run-session -- xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 build/tauri-venv/bin/python packaging/tauri_linux_lifecycle.py --binary dist/account-rotation-validation/package/usr/bin/ysu-net --output dist/account-rotation-validation/native
```

前端交互入口为[多账号预览](../desktop/tests/multi_account_preview.py)、[设计预览](../desktop/tests/rust_desktop_preview.py)、[旧预览](../packaging/tauri_web_smoke.py)。复现前按脚本帮助启动已构建前端的回环 preview，并提供系统 Chrome，不下载浏览器。

## 未覆盖

Windows/macOS 的实际构建、文件权限、持锁控制、窗口和自启；Rust MSRV 1.90 与 Clippy；真实托盘、安装/升级/签名；真实校园网、多终端并发、真实运营商交互、流量单位/精度和无限量文案。SDK 使用 Rust 1.99.0，宿主 Chrome 与 Node 24.21.0；这些结果不外推到未运行的平台或生产门户。
