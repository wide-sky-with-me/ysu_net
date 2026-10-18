# 桌面细节修正验收

日期：2026-10-16。范围：FlClash 排版后的局部精修；不换布局或色板，不修改认证、账号持久化和原生托盘逻辑。历史[排版验收](flclash-layout-validation.md)保持原貌，不作为本轮结果。

## 修正与复现

- 紧凑自动化卡片：说明从图标旁的窄列移到整行，统一使用 11px 字号；标题、图标和开关居中对齐。700×560 仍完整显示关键操作。
- 账号选择：文本明确以省略号截断，悬停展示完整名称、用户名和状态；未命名账号不再重复显示用户名。仅改变展示，不修改选项值、禁用规则和切换流程。
- 账号列表：长名称换行时，“当前”标记保持在首行；保留完整名称，不做强制单行截断。

新增[针对性回归](../desktop/tests/detail_desktop_preview.py)，同一脚本在修改前记录 **13/31 通过、18 项失败**，修改后 **31/31 通过**。`--baseline` 仅用于收集完整失败证据，报告仍标记 `ok:false`。覆盖浅深主题、1000/700/390/320px、空账号、长名称和未命名账号；未放宽既有断言。

修正前后截图：[紧凑修正前](../dist/desktop-detail-validation/before/connection-light-700.png)、[紧凑修正后](../dist/desktop-detail-validation/after/connection-light-700.png)、[长名称修正前](../dist/desktop-detail-validation/before/long-account-light.png)、[长名称修正后](../dist/desktop-detail-validation/after/long-account-light.png)、[深色桌面](../dist/desktop-detail-validation/after/connection-dark-1000.png)。

## 本轮检查

| 检查 | 实际结果 |
| --- | --- |
| `npm --prefix desktop run check` | 0 错误、0 警告 |
| 前端单测 / 构建入口测试 | 42/42、5/5 |
| 生产前端构建 | 通过 |
| 新增细节回归 | 31/31 |
| FlClash 网格与可访问性 | 10 布局、18 实际表面对比、5 紧凑状态通过；含 Tab 顺序、强制色和降低透明度 |
| 既有排版回归 | 74 布局、12 对比检查通过 |
| 逐页评审回归 | 27/27 |
| 多账号回归 | 9 组交互、10 布局通过 |
| 桌面交互回归 | 8 组交互、19 布局通过 |
| 普通网页 / 离线模拟冒烟 | 通过；无外部请求、页面错误或网页存储 |
| Linux 原生离线构建 / 冒烟 | 通过；原生渲染、连接/切换、账号/轮换、关闭后托盘操作、重建和退出清理通过 |

[前端构建日志](../dist/desktop-detail-validation/frontend-build.log)、[浏览器回归日志](../dist/desktop-detail-validation/browser-regression.log)与各脚本报告位于[本轮证据目录](../dist/desktop-detail-validation/)。浏览器使用 Chrome 154.0.8037.97。所有认证数据均来自隔离离线模拟。

## 原生与证据边界

SDK 容器内离线 `--no-bundle` 构建通过，耗时 1m37s；[二进制元数据](../dist/desktop-detail-validation/binary.json)记录本轮大小和 SHA256。[原生验收报告](../dist/desktop-detail-validation/native/acceptance.json)确认 Rust/WebView 渲染、连接与运营商切换、账号管理及热切换、自动重连/轮换、关闭后的托盘操作、窗口重建和进程清理通过。没有运行认证旁车。原生构建位于浏览器回归之后，[前端哈希](../dist/desktop-detail-validation/web-tested-sha256.json)比对确认两者使用相同前端。

原生验证使用受控 D-Bus/Xvfb 显示，不代替真实系统面板与鼠标悬停；Linux 报告 `tooltip_supported:false`。已看图核对[实际原生菜单与已连接界面](../dist/desktop-detail-validation/native/native-tray-menu.png)。最初的[可见阶段截图](../dist/desktop-detail-validation/native/native-visible.png)仍为白屏，原样保留并排除为视觉成功证据；之后的原生渲染断言和菜单截图证明页面已绘制。原生截图是默认 1000×720 窗口，紧凑和窄屏由浏览器验证。

[展示层差异](../dist/desktop-detail-validation/presentation.diff)只涉及样式和模板；[业务不变核对](../dist/desktop-detail-validation/unchanged-business.json)确认 App 脚本与 AccountBook 组件保持逐字一致。前一轮归档中列入清单的 25 个证据文件保持原哈希，见[归档检查](../dist/desktop-detail-validation/archive-check.json)。

预览助手退出后留下了子进程；已核对命令及所有权并终止，1423 端口确认关闭，见[清理记录](../dist/desktop-detail-validation/preview-cleanup.json)。未安装、提交、推送或发布；未运行真实校园网认证。Windows/macOS 原生窗口、系统面板与悬停、打包签名、完整 Rust/Python 回归和长稳测试未执行。

## 复跑

先运行 `npm --prefix desktop run build`，再启动 `node desktop/node_modules/vite/bin/vite.js preview desktop --host 127.0.0.1 --strictPort --port 1423`。运行以下检查后终止自己启动的预览进程并确认端口关闭：

```sh
.venv/bin/python desktop/tests/detail_desktop_preview.py --output dist/desktop-detail-replay
.venv/bin/python desktop/tests/flclash_desktop_preview.py --output dist/desktop-detail-replay/grid
.venv/bin/python desktop/tests/ui_review_preview.py --output dist/desktop-detail-replay/review
```

原生构建命令为 `YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs --no-bundle`；原生自检沿用[桌面开发文档](tauri-desktop.md#验证命令)，结果输出到新的目录，不覆盖本轮或历史档案。
