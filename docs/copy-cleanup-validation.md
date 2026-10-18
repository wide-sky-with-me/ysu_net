# 界面文案精简验收

日期：2026-10-17。范围：Windows/Linux/macOS 共用的 Svelte 界面；当前取舍见[设计说明](rust-desktop-design.md)。未改 Shell、旧 Qt、认证、账号存储或 Rust 后台。

## 改动

删除正常托盘的操作介绍、按钮旁重复的退出说明、浏览器可用时的介绍，以及账号/账号簿、本地诊断旁的重复说明。日志底部只保留条数，清空范围移至按钮提示。退出影响仍在确认框，缺浏览器、无托盘、密码留空、用户名固定、未保存修改、证书和门户缺项等必要提示保留。

保存、诊断和退出操作继续右对齐；高度不超过 620px 的桌面外观页缩小纵向留白，不缩字号与按钮，不改变窄屏正常滚动。

## 检查与证据

文案改动后执行 `npm --prefix desktop run check`、`test`、`test:build`、`build`：零错误、零警告，82 项单元测试和 5 项构建入口测试通过，生产构建通过，见[首轮日志](../dist/copy-cleanup-validation/frontend-build.log)。随后只调整短窗口样式及对应页面类名，再执行 `check` 与 `build`，见[最终构建日志](../dist/copy-cleanup-validation/frontend-final-build.log)。

最终生产预览通过：[界面回归](../dist/copy-cleanup-validation/review-accepted/review-report.json) 32/32（原有 27 组加新增 5 组）；[页面布局](../dist/copy-cleanup-validation/pages-accepted/clean-desktop-report.json) 74 布局与 12 对对比；[选色回归](../dist/copy-cleanup-validation/accents-accepted/accent-ui-report.json) 150/150；[浏览器 smoke](../dist/copy-cleanup-validation/web-accepted/browser-report.json) 通过。四个脚本由 `with_server.py` 在 1423 端口的生产预览中串行执行，见[最终浏览器日志](../dist/copy-cleanup-validation/browser-accepted.log)。

已看图复核[常规外观页](../dist/copy-cleanup-validation/review-accepted/concise-appearance-1000.png)、[短窗口修正结果](../dist/copy-cleanup-validation/review-accepted/appearance-density.png)和[窄屏](../dist/copy-cleanup-validation/review-accepted/concise-appearance-320.png)。

Linux release 构建通过：`YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs --no-bundle`，见[构建日志](../dist/copy-cleanup-validation/native-build.log)。在隔离 SDK 的 `dbus-run-session`/`xvfb-run` 中对[本轮二进制](../dist/copy-cleanup-validation/bin/ysu-net)执行 `packaging/tauri_smoke.py --capture-desktop`，退出码 0；[原生验收](../dist/copy-cleanup-validation/native/acceptance.json)为 `ok:true`，IPC、账号、主题色落盘/重读、托盘后台操作、窗口重建与进程清理通过。完整文案/辅助媒体矩阵来自 Chrome，不据此声称原生全状态视觉或辅助功能实机验收；短时资源数据不作为性能比较。

## 失败与复测

首轮完整界面回归 31/32。新增的五个精简文案/必要引导场景通过，但原有 700×560 外观密度检查发现退出按钮底部约 594px，超出首屏；见[首轮日志](../dist/copy-cleanup-validation/browser-regression.log)与[失败截图](../dist/copy-cleanup-validation/review/appearance-density.png)。保留原来的可见性断言，仅收紧短窗口外观页的标题、设置行和分组间距。

[界面回归](../desktop/tests/ui_review_preview.py)只追加场景，不删除原有检查；新增宽/窄屏重复小字消失、退出确认语义、密码清理、诊断焦点、日志条数/按钮提示，以及缺浏览器、缺组件、无托盘时的引导。[浏览器 smoke](../packaging/tauri_web_smoke.py)将被删除的介绍文案检查替换为“系统浏览器可用”和无介绍段落，原“无下载组件按钮”及其余行为断言保留。

## 范围与边界

原生内嵌与最终浏览器构建的六个前端文件哈希相同，见[一致性记录](../dist/copy-cleanup-validation/native-assets-check.json)。组件脚本、基础色板与原有界面断言保持不变，见[源码差异](../dist/copy-cleanup-validation/source-changes.diff)、[本轮源码哈希](../dist/copy-cleanup-validation/source-after-sha256.json)和[范围检查](../dist/copy-cleanup-validation/scope-check.json)。辅助核对首次将上轮已适配的测试脚本与更早源码清单比较而失败；现以最近主题色源码清单核对未改文件，更早清单只用于其冻结产物。收尾的进程清理字段应读取外层 `acceptance.json`，辅助核对曾误读内部 IPC 报告并已修正。旧验收报告、截图和哈希清单保持原貌，不作为本轮通过证据。

未执行真实校园认证、Windows/macOS 原生实机、系统自启实机、长时稳定性或性能比较。Shell/Qt 与 Rust 逻辑未变，未重复运行它们的单元回归；本轮不安装、发布、提交或推送。
