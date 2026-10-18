# 侧栏底部验收

日期：2026-10-17。范围：共用 Svelte 桌面界面的左下角，不涉及认证、账号、原生托盘、偏好存储或 CLI/Qt 功能修改。当前布局见[设计说明](rust-desktop-design.md)；[上一轮配色验收](theme-refinement-validation.md)保留原貌，不计入本轮通过成绩。

## 实现与复现

产品修改仅涉及[应用组件](../desktop/src/App.svelte)和[公共样式](../desktop/src/app.css)。[底栏检查脚本](../desktop/tests/sidebar_footer_preview.py)验证状态含义、视觉排布、操作与焦点；[范围核对](../dist/sidebar-footer-validation/scope-check.json)逐字比较底栏外的应用与样式，另外核对 21 个文件保持本轮初始哈希。[修改前源码](../dist/sidebar-footer-validation/source-before/)、[差异](../dist/sidebar-footer-validation/changes.diff)与[修改前哈希](../dist/sidebar-footer-validation/source-before-sha256.json)保留本轮基线。

基线使用修改前已验收的构建，先核对对应源码哈希，再运行新布局目标：34/86 满足。[原始基线报告](../dist/sidebar-footer-validation/before/sidebar-footer-report.json)与[当时的检查脚本](../dist/sidebar-footer-validation/before/sidebar_footer_preview.py)冻结保存；未满足项表示旧排布尚未实现新目标，不表示原有业务故障。

预览统一通过项目既有 `with_server.py` 托管 `vite preview desktop --host 127.0.0.1 --strictPort --port 1423`，退出时关闭服务器。底栏复现命令为 `.venv/bin/python desktop/tests/sidebar_footer_preview.py --url http://127.0.0.1:1423/ --output dist/sidebar-footer-validation/after`；此前附加 `--baseline` 只捕获旧布局，不执行交互。

## 本轮浏览器结果

`npm --prefix desktop run check` 零错误、零警告；`run test` 82/82，`run test:build` 5/5，`run build` 成功，见[构建日志](../dist/sidebar-footer-validation/frontend-build.log)。

- 底栏专项 118/118：浅深主题，1000、881、880、700、521px 宽度及 700×480 短窗口。文字最小 12px，实际最低对比度 5.193:1。状态与诊断可达、无溢出，普通宽度同排、窄侧栏纵排。在线/离线/未知/未连接核心分支、忙碌锁定、外部管理下允许诊断、Tab/Enter、结果焦点、强制色焦点、版本仍可查均通过；520、390、320px 顶部导航仍通过设置页访问诊断。无网页存储、页面/控制台错误或外部请求。见[专项报告](../dist/sidebar-footer-validation/after/sidebar-footer-report.json)。
- 逐页回归 32/32，包含紧凑外观页的退出按钮可达性，见[逐页报告](../dist/sidebar-footer-validation/review/review-report.json)。
- 任务网格 10 个布局、18 对对比、紧凑状态及键盘顺序通过，见[网格报告](../dist/sidebar-footer-validation/layout/flclash-report.json)。
- 页面矩阵 74 个布局、12 对文字对比通过，见[页面报告](../dist/sidebar-footer-validation/pages/clean-desktop-report.json)。
- 主题选择 186/186，保留原有断言，见[主题报告](../dist/sidebar-footer-validation/accents/accent-ui-report.json)。

完整日志见[浏览器回归](../dist/sidebar-footer-validation/browser-validation.log)。

## 直接看图

- [浅色常规窗口](../dist/sidebar-footer-validation/after/light-1000-720.png)，[修改前同尺寸](../dist/sidebar-footer-validation/before/light-1000-720.png)。
- [深色紧凑窗口](../dist/sidebar-footer-validation/after/dark-700-560.png)，[修改前同尺寸](../dist/sidebar-footer-validation/before/dark-700-560.png)。
- [短窗口](../dist/sidebar-footer-validation/after/light-700-480.png)与[高对比键盘焦点](../dist/sidebar-footer-validation/after/dark-forced-colors.png)。

## 原生与边界

浏览器 smoke 通过：`packaging/tauri_web_smoke.py --url http://127.0.0.1:1423/ --browser /usr/bin/google-chrome --output dist/sidebar-footer-validation/web`，见[报告](../dist/sidebar-footer-validation/web/browser-report.json)。对话框、操作、密码清理、明暗模式与紧凑窗口等标志均通过，无页面错误、控制台错误和外部请求。

Linux release 构建成功：`YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs --no-bundle`，见[构建日志](../dist/sidebar-footer-validation/native-build.log)。将 release 二进制复制为[本轮验收程序](../dist/sidebar-footer-validation/bin/ysu-net)，在无网络 SDK 的 `dbus-run-session` / `xvfb-run` 下执行 `packaging/tauri_smoke.py --binary dist/sidebar-footer-validation/bin/ysu-net --output dist/sidebar-footer-validation/native --capture-desktop`，退出码 0。[原生验收](../dist/sidebar-footer-validation/native/acceptance.json)确认 IPC、账号与自动化、偏好保存/重读/恢复、关闭驻留、窗口重建、托盘后台操作及宿主丢失恢复通过；`processes_cleaned:true`、`no_auth_sidecar:true`。完整日志见[原生自检](../dist/sidebar-footer-validation/native-validation.log)。

浏览器验收与原生构建使用的前端产物哈希一致，记录于[一致性核对](../dist/sidebar-footer-validation/native-assets-check.json)。完整视觉矩阵来自 Chrome；Linux 原生自检不代表真实桌面面板、系统辅助功能或每种主题/窗口组合已逐一看图验收。

Windows/Linux/macOS 共用此次组件和样式；Windows/macOS 原生窗口、系统辅助功能与真实桌面鼠标/托盘体验未测，浏览器截图不替代对应平台实机验收。无真实校园认证、安装、发布、提交或推送。CLI/Python/Qt 和 Rust 业务源码未作功能修改，未重复其独立业务单元测试。

收尾时，无超时 TCP 端口探测发生长时间等待，终止该检查后使用 `ss -ltn 'sport = :1423'` 确认无监听。只调整收尾核对命令，未改变产品或重跑已通过的应用回归。
