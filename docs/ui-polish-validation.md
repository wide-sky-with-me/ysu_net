# 界面细节修订验收

日期：2026-10-17。范围：共用 Svelte 桌面界面的几何、控件与信息层级，不改业务行为、文案语义、认证、账号持久化或原生托盘。当前布局见[设计说明](rust-desktop-design.md)；[品牌字标验收](brand-wordmark-validation.md)与更早记录保留原貌。

## 实际存在的问题

改动前逐页放大核对，确认的缺陷都是可量化的，不是主观喜好：

- 内容宽度不一致：标题与模式提示是 964px，正文容器 960px，滚动条占位再吃掉 15px，卡片左边界与标题差 4px、右边界比提示窄 15px。
- 圆角有 10、11、12、14、15、16、18、20、22、24px 十档，同层级卡片互不相等；按钮是 999px 胶囊，与 10px 圆角输入框不是同一族。
- 设置页四个页签均分整宽，每段约 190px，与下方内容左边界错位。
- 数字输入仍显示浏览器微调箭头。
- 两列表单（门户地址/CAS 地址）每列各自画分隔线，列间隙处断成两段。
- 日志级别是浅色底块，与时间、正文并排显得堆叠。
- 账号列表与诊断表的最后一行仍带分隔线，末端多一条无意义横线。
- 分组标题 13px/650 与正文 13px 几乎同权，"认证""检查与重试"难以一眼分开。

## 改动

[公共样式](../desktop/src/app.css)是唯一产品改动。几何体系收为三档：`--radius-lg: 20px` 用于卡片与大面，`--radius-md: 14px` 用于内层面板与提示，`--radius-sm: 10px` 用于按钮、输入框与下拉。按钮从胶囊改为 10px 圆角，与输入框同族；只有开关保留胶囊形态。内容宽度统一到 964px 并去掉 `main` 的左右内缩，标题、提示、卡片共享同一左边界。

分组标题提到 14px/700。表单改为 `132px` 固定标签列加自适应控件，两列表单只在容器底部保留一条连续分隔线。日志级别改为色点加文字，去掉底块。账号列表与环境清单的末行不再画线。数字输入的 `::-webkit-inner-spin-button` 增加 `display: none`。模式提示去掉边框、字号提到 11px，降低横条的存在感。

未改动：DOM 结构、组件划分、点击与键盘行为、状态语义、文案、配色变量、阴影、字体栈、响应式断点。

## 范围与复现

[范围核对](../dist/ui-polish-validation/scope-check.json)确认产品侧只修改了 `app.css`：`App.svelte` 及其他 27 个受保护文件哈希与本轮初始值一致。

本轮有一个证据缺口需要明确：[基线说明](../dist/ui-polish-validation/baseline-note.json)记录，`app.css` 的“改动前副本”在改动完成后才复制，内容等于改动后版本，已删除该误导副本。因此本轮**没有**可直接逐行对比的 `app.css` 基线文件，只有 brand 轮留下的改前哈希 `d13e6f3f…` 作为指纹。判据改为：[差异](../dist/ui-polish-validation/changes.diff)中的文档改动、声明的规则变更清单（只改值、新增 3 条伪元素与末行规则、未删除任何选择器），以及全部回归通过。这是代理清单而非文件对比证据；下次同类改动应在开工前先保存副本。

复现：用项目既有 `with_server.py` 托管 `vite preview desktop --host 127.0.0.1 --strictPort --port 1423`，再运行 `desktop/tests/` 下各回归脚本，退出时服务器关闭。

## 结果

`npm --prefix desktop run check` 零错误零警告；`run test` 82/82，`run test:build` 5/5，`run build` 成功，见[构建日志](../dist/ui-polish-validation/frontend-build.log)。

- 逐页回归 32/32，含紧凑窗口外观页的退出按钮可见性，见[报告](../dist/ui-polish-validation/check-ui_review_preview/review-report.json)。
- 任务网格 10 个布局、18 对对比、五种紧凑状态与键盘顺序通过，见[报告](../dist/ui-polish-validation/check-flclash_desktop_preview/flclash-report.json)。
- 页面矩阵 74 个布局、12 对文字对比通过，见[报告](../dist/ui-polish-validation/check-clean_desktop_preview/clean-desktop-report.json)。
- 主题选择 186/186，见[报告](../dist/ui-polish-validation/check-accent_themes_preview/accent-ui-report.json)。
- 侧栏底部 118/118、品牌字标 166/166、流量状态 110/110、细节回归 31/31，见同级各报告。

改动过程中出现过一次真实回归：模式提示字号提高后，700×560 的连接页 `main` 溢出，布局回归报 `external` 场景失败。处理方式是把提示的上下内边距收回 5px、行高收到 1.5，未删除或放宽任何断言；复测通过。

## 直接看图

- [浅色连接页](../dist/ui-polish-validation/v2-connection.png)：按钮与标题同行，刷新与电源图标为新版。
- [Windows 字体下的深色连接页](../dist/windows-render-validation/dark-1000x720-connection.png)与[Windows 最小窗口 700×560](../dist/windows-render-validation/light-700x560-connection.png)。
- [设置-认证与重试](../dist/ui-polish-validation/v3-auth-light.png)，可见单条分隔线与固定标签列；[环境诊断](../dist/ui-polish-validation/v3-diagnostics-light.png)。
- [设置-外观与启动](../dist/ui-polish-validation/v2-appearance.png)：分段与主题选中态统一为强调色。
- [设置-校园网账号](../dist/ui-polish-validation/v2-account-settings.png)，末行不再多一条线。
- [日志列表](../dist/ui-polish-validation/v2-logs.png)：搜索框用放大镜，级别为色点加文字。
- [账户摘要](../dist/ui-polish-validation/zoom-summary.png)、[数字输入](../dist/ui-polish-validation/zoom-number-input.png)（无微调箭头）。

## 原生与边界

Linux release 构建通过（`YSU_SDK_NETWORK=none`、`CARGO_NET_OFFLINE=true`），见[构建日志](../dist/ui-polish-validation/native-build.log)；在无网络 SDK 的 `dbus-run-session` / `xvfb-run` 下执行 `packaging/tauri_smoke.py --capture-desktop`，退出码 0。[原生验收](../dist/ui-polish-validation/native/acceptance.json)确认 IPC、账号、偏好保存与恢复、关闭驻留、窗口重建、托盘后台操作与宿主丢失恢复通过，`processes_cleaned`、`no_auth_sidecar` 为 true。原生构建与浏览器验收的 6 个前端文件哈希一致，见[一致性核对](../dist/ui-polish-validation/native-assets-check.json)。

视觉矩阵来自 Linux Chrome；Linux 原生自检只验证生命周期与渲染存在，不代表真实桌面面板、系统辅助功能已逐一看图。Windows 侧验证与边界见下节。无真实校园认证、安装、发布、提交或推送；CLI/Python/Qt 与 Rust 业务源码未改。

## 第二轮：图标与排版

由两个只读子代理先审查、再逐条核实后修改，采纳与驳回都记录理由。

图标的实质缺陷是几何不自洽：刷新图标两段弧圆心相差 12 单位、箭头方向反；`doctor`、`logs`、`browser` 三个都是矩形外框，16–18px 下难以区分；`info` 的点只有 0.1 单位，渲染成感叹号；断开连接与退出应用共用同一个“离开方框”符号；搜索框用的是日志文档图标。修正在[图标定义](../desktop/src/components/Icon.svelte)：刷新改为连续双弧循环，`doctor` 去掉外框改 ECG 波形，`logs` 改折角文档，`settings` 加圆柄，`info` 点改真圆；新增 `power`、`search`、`alert`，并让断开连接、搜索框、错误提示分别使用它们。删除零引用的 `arrow`、`download`；默认尺寸 20→18；调用处的 12/15/17/19 收敛到 14/16/18；`.icon-button` 从 34 改为 36，与输入框同高；删掉被 `display:none` 永久隐藏的 `service-indicator`。

排版采纳 6 条：连接卡操作按钮改为与标题同行右侧（原宽屏独占一行、窄屏又在右侧，行为反着）；分段控件选中态统一为强调色边框加浅底；禁用态透明度 .45→.6，并给“切换账号”补禁用原因提示；连接详情标签 10→11px；账户页分组标题与卡片内容对齐（5→20px）；“启动与退出”末行不再多一条分隔线（用 `:has(+ .quit-row)`）。

驳回 4 条并说明：手机宽度隐藏侧栏底部是有意设计，诊断入口在设置页，已有回归覆盖；520px 以下触控目标放大不适用于本机最小窗口 700×560 的桌面场景；账号下拉截断靠给切换按钮补 `title` 缓解，不拆 option 文案；连接页与账户页数值字号服务不同场景（信息行 vs 指标卡），不强行统一。

复测：Linux 逐页 32/32、网格 10 布局、页面 74 布局、主题 186/186、底栏 118/118、字标 166/166、流量 110/110、细节 31/31。Linux 原生重新构建与自检通过，见[构建日志](../dist/ui-polish-validation/v3-native-build.log)与[自检日志](../dist/ui-polish-validation/v3-native.log)。

## Windows 验证

运行环境是 WSL，Windows 侧有 Node、Python 与 Chrome 155，但没有 Rust 与 MSVC；Tauri 的 Windows 目标必须用 MSVC 工具链在本机编译，本机也没有 wine 或 Windows 交叉编译器，因此**本轮没有生成或运行过 Windows 原生程序**，也没有为了构建而向 Windows 安装 Rust/MSVC。

能真实执行的部分已经做了：通过 CDP 驱动 Windows 上的 Chrome，让页面在 WSL 构建、在 Windows 字体与渲染引擎下打开，覆盖浅深两套主题、1000/1280/700/520/390 五档视口、连接/账户/日志与设置四个页签，共 169 项检查全部通过，见[报告](../dist/windows-render-validation/windows-render-report.json)与 72 张截图。检查包含：页面无横向溢出、文案未被截断、最小窗口 700×560 首屏完整、页签单行、系统字体可用、无控制台错误与外部请求。

字体差异已量化：同一串中文在 Windows 雅黑下宽 124.14px，在 Linux 文泉驿下宽 124.49px，相差 0.3%，都不触发换行或溢出。这也是本轮不引入内嵌中文字体的依据。

仍未验证：Windows WebView2 与原生窗口、Windows 原生滚动条与高 DPI 缩放、系统托盘与开机自启。仓库已有 [Tauri CI](../.github/workflows/tauri.yml) 的 `windows-2022` 作业会在推送时构建 `ysu-net.exe` 并执行 `packaging/tauri_smoke.py`，但那需要推送才能触发，本轮未执行。Windows 实机复现命令：`python packaging/tauri_smoke.py --binary desktop/src-tauri/target/release/ysu-net.exe --output dist/tauri-smoke`。
