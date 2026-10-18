# 素洁桌面重设计验收

日期：2026-10-14（Asia/Shanghai）。范围：`feat/rust-desktop` 中三平台共用的 Svelte 界面，仅调整视觉布局与静态文案，不修改认证、配置、账号切换或轮换执行逻辑；Shell 与旧 Qt 保持原样。当前视觉定义见[设计说明](rust-desktop-design.md#当前方案与自检)。

## 结果

| 检查 | 本轮结果 |
| --- | --- |
| Svelte / TypeScript | 0 错误、0 警告 |
| 前端单元回归 | 42 项通过 |
| 原生构建入口契约 | 5 项通过 |
| 生产构建 | Vite 构建通过，本地字体，无新增依赖 |
| 新增视觉回归 | 74 个布局样本通过；12 组文本颜色对比度通过，最低 4.90 |
| 既有设计交互 | 8 组通过，19 个布局样本无溢出或标签重叠 |
| 多账号交互 | 9 组通过，10 个布局样本通过 |
| Linux 原生程序 | 在已有 Ubuntu 22.04 SDK 内离线构建，真实 WebKit WebView 演示验收通过 |

布局样本覆盖浅深主题，以及 1000×720、1280×900、860×640、700×560、520×720、390×844、320×720 窗口。默认桌面窗口的连接页不需要滚动即可看到两个自动化开关；窄窗口正常堆叠。设置各任务页签、账户及日志共用新的无框画布。实际实现：[布局](../desktop/src/App.svelte)、[样式](../desktop/src/app.css)。

## 交互与原生边界

[新增视觉回归](../desktop/tests/clean_desktop_preview.py)检查实际生产构建的布局、控件裁切、文字对比度与默认窗口可见性。保留[原有设计交互](../desktop/tests/rust_desktop_preview.py)及[多账号交互](../desktop/tests/multi_account_preview.py)断言，继续覆盖运营商/账号切换确认、Esc 与焦点恢复、密码清理、忙碌时停止自动化、未知/离线/外部管理状态、轮换前提、系统主题、日志筛选等。浏览器为本机 Chrome 154.0.8037.97；页面错误、控制台错误、外部请求均为零，浏览器存储为空。

Linux 使用关闭网络的独立 D-Bus/Xvfb 会话和软件渲染，运行本轮新编译的 Rust 原生程序；WebView 中验证账号管理与热切换、登录/下线、自动重连、轮换开关、额度报告、窗口销毁/重建与后台存活。应用完整进程树仅包含 Rust/WebKit，无 Python/Node 认证旁车，退出后自有进程已清理。监督工具的 Python 不属于应用进程树。D-Bus 的未知子进程提示保留在日志中，实际命令退出码为 0。

本轮使用 `--no-bundle` 构建原生程序，未重打安装包、安装、操作真实账号、提交、推送或发布。Windows/macOS 原生窗口与字体、托盘与自启、真实校园认证和升级仍待实机验证；共用样式通过浏览器验证不等于这些平台的原生验收。未修改业务核心，未重跑 Python 或 Rust 业务单元测试，也未把此前成绩计入本轮。

## 发现与修正

首次新增视觉检查遇到 CSS 压缩将 `#ffffff` 缩为 `#fff`，测试颜色解析器只支持六位写法而失败；修正解析器支持三位格式，保留断言。随后测得侧栏辅助文字的对比度为 4.48，低于本轮 4.5 的检查门槛；实际加深辅助文字颜色后，侧栏达到 4.90，未放宽标准。失败日志分别保留在本地 `browser-tests-first.log`、`browser-contrast-before.log`。修正后重新构建浏览器及最终原生程序，没有以修正前的二进制验收。

实际看图复核：[浅色连接](../dist/clean-desktop-validation/visual/connection-light.png)、[深色连接](../dist/clean-desktop-validation/visual/connection-dark.png)、[浅色设置](../dist/clean-desktop-validation/visual/page-设置-light.png)、[窄窗口](../dist/clean-desktop-validation/visual/connection-light-390.png)、[原生 WebView](../dist/clean-desktop-validation/native/native-visible.png)。截图均为离线合成数据，不是校园在线会话。

## 复现与证据

```sh
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
npm --prefix desktop run build
.venv/bin/python /home/yhr/.dsh/skills/webapp-testing/scripts/with_server.py \
  --server 'npm --prefix desktop run preview -- --port 1423' --port 1423 -- \
  .venv/bin/python desktop/tests/clean_desktop_preview.py --url http://127.0.0.1:1423/
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true \
  node desktop/scripts/desktop.mjs --no-bundle
```

其他浏览器脚本使用同一个预览地址，结果另存本轮目录。预览通过 helper 启动；结束检查发现其有遗留的 Vite 监听子进程，核对命令行与本轮启动记录后清理，并再次确认端口关闭，不仅依赖 helper 的停止提示。原生验收入口为[现有监督脚本](../packaging/tauri_smoke.py)，在 SDK 内使用 `build/tauri-venv/bin/python`、独立 `dbus-run-session` / `xvfb-run` 及 `--capture-desktop`。监督脚本在项目 `.venv` 下曾因缺少 psutil 退出，本轮沿用已有 SDK 验收环境，没有添加应用依赖。

本地证据保存在 `dist/clean-desktop-validation/`：浏览器报告位于 `visual/clean-desktop-report.json`、`interaction/frontend-design-report.json`、`accounts/multi-account-report.json`，原生结果为 `native/native-report.json` 与 `native/acceptance.json`；构建日志和 `build-manifest.json` 记录当时源码与二进制哈希。原生程序 SHA256：`af43f448a3ff32e2b1d3dfdd57ea63006a8459d0b8d4fa075ce3e2ad29010bb7`。短时间软件渲染采样不作为性能改进结论；历史安装包及验收文档保持不变。
