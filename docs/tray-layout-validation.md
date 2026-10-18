# 内容排布与托盘验收

日期：2026-10-15（Asia/Shanghai）。范围为未发布的 Tauri 桌面版，不替换 Qt 兼容发行物。旧验收记录与截图保留原貌；本轮产物独立保存于 [tray-layout-validation](../dist/tray-layout-validation/)。

## 改动

连接页将状态、运营商、账号、IP 和证书/认证方式放入同一上下文，取消分散的信息卡片；账号与运营商操作并排，自动化为紧凑状态行。保留未知、外部管理、错误及零额度复核提示，移除重复的通用轮换解释。700×560 的常规在线、离线和未知状态均检查完整控件边界与主区域滚动高度，不只检查 DOM 可见性。

账户页增加直达管理入口。编辑账号时在原位置替换列表，避免长列表把编辑器推至末尾；关闭或保存时恢复列表焦点与滚动位置。校验失败、保存失败、取消、Escape、切页和切设置分区的密码清空仍受回归保护。

托盘增加账号/运营商、IP、上次查询额度及最近结果，提供打开、连接/断开、刷新、自动重连、自动换号和退出。图标增加状态角标，Windows/macOS 使用原生摘要，Linux 使用菜单。完整运行语义见[当前文档](tauri-desktop.md)，并发与平台选择见[决策](../.agents/notes/implemented/desktop/2026-10-15-tray-control.md)。

## 前端与构建

执行：`npm --prefix desktop run check`、`test`、`test:build`、`build`。类型与 Svelte 检查无错误/警告，前端单元测试 42 项、构建入口测试 5 项通过。

对最终构建启动 `node desktop/node_modules/vite/bin/vite.js preview desktop --host 127.0.0.1 --strictPort --port 1423`，使用本机 Chrome 154.0.8037.97、离线模拟与注入的只读快照执行以下脚本；输出均在本轮目录，未请求校园网或外部资源。

- [ui_review_preview.py](../desktop/tests/ui_review_preview.py)：27 项通过，含 700×560 全控件完整可见、32 条账号的编辑/返回焦点、未知 IP、错误局部提示与强制颜色。
- [clean_desktop_preview.py](../desktop/tests/clean_desktop_preview.py)：74 个布局与 12 组文本对比通过。
- [glass_desktop_preview.py](../desktop/tests/glass_desktop_preview.py)：54 个合成背景对比样本、主按钮渐变、悬停选中态及辅助媒体检查通过。
- [multi_account_preview.py](../desktop/tests/multi_account_preview.py)：9 组业务交互、10 个布局通过，保留确认、独立核验、当前账号保护、失败不改账号簿、忙碌时停止及密码清空断言。
- [rust_desktop_preview.py](../desktop/tests/rust_desktop_preview.py)：8 组交互、19 个布局通过。
- [tauri_web_smoke.py](../packaging/tauri_web_smoke.py)：完整离线交互通过，普通网页不伪装原生核心，未使用 Web Storage 保存凭据。

最终前端截图：[最小窗口](../dist/tray-layout-validation/layout-final/connection-light-700.png)、[标准窗口](../dist/tray-layout-validation/layout-final/connection-light.png)。

## 原生验证

使用既有 Ubuntu 22.04 SDK 容器、Rust 1.99.0、锁定的 Tauri 2.12.3；`YSU_SDK_NETWORK=none` 与 `CARGO_NET_OFFLINE=true`。未安装到宿主系统，未发起真实认证，未提交、推送或发布。

原生单元测试 79 项通过，其中托盘纯模型 12 项，覆盖未知/离线/外部管理、忙碌停止、轮换资格、额度与身份失配、摘要长度、角标、快照顺序/重试及调度槽释放。格式检查、最终原生 release 构建和 Linux 离线桌面集成通过。验证命令使用实际项目入口：

```bash
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true \
  cargo test --locked --offline --manifest-path desktop/src-tauri/Cargo.toml
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true \
  node desktop/scripts/desktop.mjs --no-bundle
```

原生二进制固定到本轮 `bin` 目录，`tauri_smoke.py` 与 `tauri_linux_lifecycle.py` 分别在独立 `dbus-run-session` / `xvfb-run` 下运行，使用软件渲染。前者创建受控 D-Bus watcher，读取真实原生菜单属性，调用同一托盘分发器，检查实际 CloseRequested 后 WebView 消失及后台动作、重建和宿主丢失恢复。仅 `--capture-desktop` 且存在 X11 测试显示时请求弹出原生菜单，截图后由测试显示的 libXtst 发送 Escape；普通无截图自检保持无交互，也不调用 libXtst。该工具仅属于验收环境，不进入桌面运行依赖。后者不创建托盘宿主，检查 `--minimized` 回退、单实例和真实 X11 WM_DELETE_WINDOW 关闭及进程清理。

最终集成 [acceptance.json](../dist/tray-layout-validation/native-final/acceptance.json) 为通过：真实 CloseRequested 后主 WebView 消失，核心仍在线；托盘分发器可停止重连/轮换、下线、重新连接、刷新和重新开启自动化；原生菜单属性与核心状态一致，重建窗口读取最新快照；受控宿主退出后主窗口恢复。完整进程树退出清理通过，未观察到 Python/Node 认证旁车或外部认证浏览器。GTK 原生菜单截图见[菜单](../dist/tray-layout-validation/native-final/native-tray-menu.png)，不是 HTML 仿制菜单。

[无截图自检](../dist/tray-layout-validation/native-no-capture/acceptance.json)与[无宿主生命周期](../dist/tray-layout-validation/lifecycle-final/linux-lifecycle.json)均通过。前者验证无交互路径，后者验证最小化启动回退、单实例、真实关闭及进程清理。构建和单元测试完整输出见[原生构建日志](../dist/tray-layout-validation/final-native-build.log)。这些结果仅代表上述 Linux 离线样本，不代表真实校园网或其他操作系统。

## 失败与修正

初次紧凑窗口断言发现主区域底部仍有少量溢出，进一步收敛容器间距和自动化行的隐式网格轨道后，保留完整边界与无滚动断言并通过。长列表样本起初越过真实账号簿容量，修正为 32 条有效账号，并保留编辑任务和焦点断言。

玻璃测试原先逐个检查已移除的独立卡片，现改为对应的实际父表面，仍执行相同透明度、圆角和合成对比标准。账号保存失败测试改为确认编辑器仍在、密码已清空，取消后再检查列表未新增条目，并新增焦点断言，没有删除失败不改状态的检查。

原生初次探测等待收起原生菜单后关闭窗口超时；验收脚本增加测试显示上的 Escape 与截图时序。随后菜单回读发现单次 UI 回调优化未释放下一次调度槽，已修正 Updates::take 并增加直接回归测试，防止菜单停在初始快照。失败产物保留在 [native-probe](../dist/tray-layout-validation/native-probe/) 与 [native](../dist/tray-layout-validation/native/)，与最终结果区分。

## 覆盖边界

Linux 受控 D-Bus 宿主、真实 GTK 菜单、真实 WebView 与核心状态不等于 GNOME/KDE 面板的实际鼠标点击。Xvfb 不提供真实桌面窗口管理器；最小化/恢复 API 验证不宣称覆盖真实任务栏最小化体验。Windows/macOS 共用实现与平台分支已同步，尚未在这两个系统进行原生运行、悬停和安装验收；签名、公证及真实校园网认证也未执行。

[source-sha256.json](../dist/tray-layout-validation/source-sha256.json) 记录本轮源码、前端入口和原生二进制校验值。普通测试不包含认证库被忽略的浏览器测试，也不引用旧轮成绩作为本轮通过证据。
