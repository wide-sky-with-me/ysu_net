# 浅彩玻璃桌面验收

日期：2026-10-15（Asia/Shanghai）。用户提供 BeaconTower 截图，明确要求浅青/淡紫弥散背景、半透明白色面板与悬浮圆角侧栏；参考图附件 SHA256 为 `a7ee8b8d89b0a6f0e7cd04f452800e0583bbf0d4533ee72a92b4866576eeb91f`。本轮替代[上一轮无框白底方向](clean-desktop-validation.md)，旧截图、报告和安装包不作为当前成绩，也不覆盖重写。

## 实现范围

只重做三平台共用的[桌面样式](../desktop/src/app.css)，连接、账号、设置与日志统一使用浅彩玻璃层级；设计取舍由[当前设计说明](rust-desktop-design.md#当前方案与自检)唯一维护。没有增加参考图中的监控曲线、服务器指标或角色装饰，没有修改 Svelte 业务脚本、认证、持久化、账号切换与轮换。Shell/Python 和旧 Qt 保持原样，无新增依赖。

背景静态绘制，只有侧栏、顶栏使用背景模糊；其余面板通过透明叠色表达材质，不使用持续动画。降低透明度偏好下切换到实色表面，强制颜色模式使用系统颜色。相关媒体特性的本轮验证基于 Chrome 模拟，不外推为 Windows/macOS 原生系统偏好验收。

## 验证结果

| 检查 | 本轮结果 |
| --- | --- |
| Svelte / TypeScript | 0 错误、0 警告 |
| 前端单元回归 | 42 项通过 |
| 构建入口契约 | 5 项通过 |
| Vite 生产构建 | 通过，本地字体，无新增依赖 |
| 新玻璃视觉检查 | 54 组源背景色与透明面板复合采样通过，最低对比度 5.25；主按钮渐变 42 个采样点通过 |
| 可访问媒体特性 | 浅深主题下的降低透明度与强制颜色检查通过 |
| 既有布局检查 | 74 个样本、12 组基础文本颜色检查通过 |
| 原有交互 | 8 组交互、19 个布局样本通过 |
| 多账号交互 | 9 组交互、10 个布局样本通过 |
| Linux 原生程序 | 离线构建与真实 WebView 验收通过；账号管理/切换、自动化、后台存活和窗口重建通过 |

原生验收在禁网 Ubuntu 22.04 SDK、独立 D-Bus/Xvfb 中完成，检查实际 Linux WebKitGTK 渲染、离线核心 IPC、账号与流量轮换、窗口关闭后后台存活、重建及退出清理。已查看[原生窗口截图](../dist/glass-desktop-validation/native/native-visible.png)；其外部黑色是 Xvfb 桌面，不属于程序背景。`native/acceptance.json` 记录进程树清理与无认证旁车；其中短时资源采样不代表稳态或真实认证性能，也不用于宣称玻璃效果更省内存。

[新增玻璃检查](../desktop/tests/glass_desktop_preview.py)同时核对弥散背景、面板透明度与圆角、选中导航悬停保持、按钮渐变及媒体降级。复合色采样检查是本轮有限样本，不宣称全像素或所有系统的可访问性认证。[既有布局检查](../desktop/tests/clean_desktop_preview.py)、[设计交互](../desktop/tests/rust_desktop_preview.py)和[多账号交互](../desktop/tests/multi_account_preview.py)保留原有断言，继续覆盖确认、Esc/焦点恢复、密码清空、换号失败、未知状态、环境锁定、繁忙时停止自动化与退出等行为。

窗口覆盖 1000×720、1280×900、860×640、700×560、520×720、390×844、320×720，包含浅深主题及账号编辑。默认窗口直接看到两个自动化开关；窄窗口正常纵向滚动，没有横向溢出或控件标签重叠。Chrome 为本机 154.0.8037.97，演示只使用合成数据，没有真实校园网认证。

## 看图与修正

实际查看了[浅色连接](../dist/glass-desktop-validation/glass/connection-light.png)、[浅色设置](../dist/glass-desktop-validation/glass/settings-light.png)、[深色连接](../dist/glass-desktop-validation/glass/connection-dark.png)、[窄窗口](../dist/glass-desktop-validation/layout/connection-light-320.png)，以及媒体降级截图。看图发现鼠标悬停会让基础 hover 覆盖白色选中导航，已修正选择器优先级并补充回归；运营商和主题选中控件同步保持其选中样式，随后重新生产构建并复测。

高对比模式截图还暴露了浏览器给文字绘制白色背板的问题，导致主按钮白字被遮盖。主按钮及已明确指定系统色的控件改为保留系统 Highlight / HighlightText，同时停用该区域的自动二次改色；页签仅选中项保留强调下划线。补充了相关样式回归并重新看图，最终结果以重建后的报告为准。

本轮首次直接启动 Vite 时未指定 `desktop` 根目录，返回 HTTP 404，浏览器按实际响应退出。按本机 CLI 帮助核对 `vite preview [root]` 后修正命令；失败日志保留为 `preview-root-before.log`，没有删除或放宽浏览器断言。临时服务使用 `exec node` 和严格端口绑定，避免 npm/嵌套 shell 子进程遗留以及端口自动漂移。

收尾的 TCP 连通探测遇到 SYN 等待；进程和内核监听表确认没有预览服务。已停止这次无超时探测，最终清理核验改用带超时的 `ss` 查询，不把网络等待误报为产品故障。

## 复现与边界

```sh
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
npm --prefix desktop run build
.venv/bin/python /home/yhr/.dsh/skills/webapp-testing/scripts/with_server.py \
  --server 'exec node desktop/node_modules/vite/bin/vite.js preview desktop --host 127.0.0.1 --strictPort --port 1423' \
  --port 1423 -- .venv/bin/python desktop/tests/glass_desktop_preview.py
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true \
  node desktop/scripts/desktop.mjs --no-bundle
mkdir -p dist/glass-desktop-validation/native
cp desktop/src-tauri/target/release/ysu-net dist/glass-desktop-validation/native/ysu-net
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh dbus-run-session -- \
  xvfb-run -a -s '-screen 0 1280x900x24' \
  env LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  build/tauri-venv/bin/python packaging/tauri_smoke.py \
  --binary dist/glass-desktop-validation/native/ysu-net \
  --output dist/glass-desktop-validation/native --capture-desktop
```

本地证据位于 `dist/glass-desktop-validation/`，与上一轮分开。`glass/glass-report.json` 保存新增材质检查，`layout/`、`interaction/`、`accounts/` 保存既有浏览器结果。未实测真实校园网、Windows/macOS 原生构建及各系统托盘/自启和安装升级，未重跑未变更的 Python/Rust 业务单元测试；没有安装、提交、推送或发布。原生程序按 `--no-bundle` 构建，不替换既有安装包。
