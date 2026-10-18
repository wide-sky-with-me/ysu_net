# 桌面主题色验收

日期：2026-10-17。范围为共用 Svelte 前端与 Rust 桌面偏好链路；Windows、Linux、macOS 使用相同实现。功能与视觉规则分别维护在[桌面指南](tauri-desktop.md)和[设计说明](rust-desktop-design.md)，本页只保存本轮证据。

## 前端与存储

- `npm --prefix desktop run check`：零错误、零警告；`test`：82 项；`test:build`：5 项；生产构建通过。[日志](../dist/accent-themes-validation/frontend-build.log)。最终样式构建另见[最终构建日志](../dist/accent-themes-validation/frontend-final-build.log)。
- 独立 Rust 子任务完成 `cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check` 与 `cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked --offline`：85 项通过，无失败或忽略。通过 `YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true` 执行；主会话复核了存储、请求校验、快照和自检改动。六色逐项保存/新 Store 与 Runtime 重读、旧字段缺失、异常类型、未来值、只读回退、非法写入无变化、忙碌/外部状态及重连意图均有回归。
- 选色浏览器回归 [150/150](../dist/accent-themes-validation/ui-accepted/accent-ui-report.json)：六色实效、唯一选中、名称与勾选、hover、语义色保留、色样边界、明暗/系统联动、键盘、强制色、保存失败及无网页存储；窗口宽度覆盖 1000、700、390、320px。
- 六套色板各 64/64，共 384 项：[松石青](../dist/accent-themes-validation/palettes-accepted/teal/color-palette-report.json)、[海蓝](../dist/accent-themes-validation/palettes-accepted/blue/color-palette-report.json)、[靛蓝](../dist/accent-themes-validation/palettes-accepted/indigo/color-palette-report.json)、[紫罗兰](../dist/accent-themes-validation/palettes-accepted/violet/color-palette-report.json)、[玫瑰](../dist/accent-themes-validation/palettes-accepted/rose/color-palette-report.json)、[琥珀](../dist/accent-themes-validation/palettes-accepted/amber/color-palette-report.json)。保留既有文本 4.5:1、控件/焦点/图标 3:1 门槛，增加实际主题色标识检查。最终最小文本对比度 4.641:1、非文本 3.093:1。
- 既有回归：[页面](../dist/accent-themes-validation/pages-accepted/clean-desktop-report.json) 74 布局与 12 对文本对比；[网格](../dist/accent-themes-validation/grid-accepted/flclash-report.json) 10 布局、18 对对比、5 个紧凑状态及键盘/辅助媒体；[流量状态](../dist/accent-themes-validation/quota-accepted/quota-status-report.json) 110/110；[浏览器 smoke](../dist/accent-themes-validation/web-accepted/browser-report.json) 通过。各脚本报告无页面错误或外部请求。

## 本轮失败与修正

1. 首次选色回归 149/150：鼠标导航后直接调用 `focus()` 未进入键盘焦点态。测试补上真实 Tab 路径，强制色下的选色焦点另明确使用 `CanvasText`，原焦点宽度断言保留。见[首次记录](../dist/accent-themes-validation/browser-initial.log)和[首次报告](../dist/accent-themes-validation/ui/accent-ui-report.json)。
2. 既有布局脚本在 520px 将纵向主题色行报为碰撞。保留水平设置行约定，最窄屏仅将选项改为双列，未删除或放宽碰撞断言；最终 74 布局及选色窄屏检查通过。见[中间记录](../dist/accent-themes-validation/browser-final.log)。新色板中接近阈值的边界色也增加了对比余量，默认色未动。
3. 流量脚本临时转译样例只包含原来的两个模块，新增 `accents` 导致导入失败。同步适配流量与旧 UI-review 两处样例模块图，不改业务断言；两者独立生成相同快照，见[构建检查](../dist/accent-themes-validation/fixture-builders.json)。旧 UI-review 的其余界面断言本轮未运行。

[最终浏览器前段日志](../dist/accent-themes-validation/browser-accepted.log)记录选色、页面、色板和网格通过，随后因上述样例导入错误返回非零；修复仅涉及测试构建，续跑流量与浏览器 smoke 均通过，见[后段日志](../dist/accent-themes-validation/browser-tail.log)。不将中间失败写成整条命令成功。

## Linux 原生

`YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs --no-bundle` 通过，release 编译 1 分 29 秒；[构建日志](../dist/accent-themes-validation/native-build.log)。原生构建内嵌的六个前端文件与浏览器验收版本逐项哈希相同，见[一致性记录](../dist/accent-themes-validation/native-assets-check.json)和[本轮二进制](../dist/accent-themes-validation/bin/ysu-net)。

通过 `dbus-run-session`、`xvfb-run` 与现有 `packaging/tauri_smoke.py --capture-desktop` 执行离线原生自检，[原生报告](../dist/accent-themes-validation/native/native-report.json)为 `ok:true`。新增 `accent_preferences` 的保存、独立磁盘重读、非法值无变化和恢复初值全部为真；既有 IPC、账号管理/切换、流量、重连/轮换、关闭后驻留、托盘操作、窗口重建与退出清理通过，未观察到认证旁车。

[早期原生截图](../dist/accent-themes-validation/native/native-visible.png)仅有白色窗口，排除视觉通过声明；[托盘菜单截图](../dist/accent-themes-validation/native/native-tray-menu.png)确实渲染默认配色，但有菜单遮挡，不代表六色原生视觉遍历。[原生日志](../dist/accent-themes-validation/native/native-stderr.log)保留缺少 AT-SPI bus 的环境警告，未声称原生辅助功能实机验收。短时资源样本不作为性能比较。

## 截图与边界

- [海蓝浅色](../dist/accent-themes-validation/ui-accepted/settings-blue-light.png)、[玫瑰深色](../dist/accent-themes-validation/ui-accepted/settings-rose-dark.png)、[320px 深色](../dist/accent-themes-validation/ui-accepted/settings-dark-320.png)、[系统强制色](../dist/accent-themes-validation/ui-accepted/high-contrast.png)均为本轮构建的离线浏览器预览。
- 默认松石青的实际色值与上一轮逐项相同；相关备份在本轮 `source-before`，范围与冻结文件检查见[范围检查](../dist/accent-themes-validation/scope-check.json)。历史验收、截图和报告保留原貌，不用其成绩替代本轮验证。
- 未执行 Windows/macOS 原生窗口、托盘、自启或安装包实机验收；未执行真实校园认证、长时间重连与性能比较。命令行/旧 Qt 产品代码未变更，本轮没有为它们重跑回归；旧 Qt 的偏好互操作限制见[桌面指南](tauri-desktop.md)。未安装、发布、提交或推送。
