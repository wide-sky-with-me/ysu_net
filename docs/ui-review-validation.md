# 逐页设计评审验收

日期：2026-10-15，Asia/Shanghai。范围：Windows、Linux、macOS 共用的 Svelte 桌面界面；不涉及 Shell、旧 Qt 界面、认证算法或持久化格式。本轮未安装、提交、推送或发布，未认证真实校园网账号。

## 评审与参考

七个独立只读 agent 分别审查连接、账户、账号设置、外观与启动、认证与重试、环境诊断、日志及共享组件。主会话汇总源码、实测尺寸和截图，统一实施并复测，成员结论未直接视为验收通过。

主会话实际读取 [BeaconTower 经典 Sky Glass 源码](https://github.com/Yoahoug/BeaconTower/tree/8ead780b932e6ff5939705acbc9d0704c1a3bda2/web)，核对 token、布局、表单、组件与概览截图。采用紧凑网格、胶囊按钮、输入框比例和淡彩玻璃层次，不采用 `web-toy` 主题，不补造监控指标。当前视觉规则统一维护在[桌面设计](rust-desktop-design.md)。

修改前的独立评审证据在 [before](../dist/ui-review-validation/before/)，产品源码字节备份在 [source-before](../dist/ui-review-validation/source-before/)。上一轮[玻璃风格验收](glass-desktop-validation.md)保持原貌。

## 质询点与落地修正

| 子界面 | 已核实的问题 | 实施修正 |
| --- | --- | --- |
| 连接 | 960px 提前换列，未知状态暗示离线；外部接管原因重复且远离锁定控件；已知额度重复说明来源 | 控制与自动化网格按实际宽度换列；区分未知与明确离线；接管提示移到控制前并去重；直接显示核心提供的额度原文 |
| 账户 | 所有字段都放大，默认摘要空出一格；缺项说明永久占据卡片；窄屏缺项字体被放大 | 自适应摘要条，只突出真实数字；描述与缺项分别降级；说明仅在缺项时显示，缺项保持 13px |
| 账户数据标题 | 合成的“套餐与余额”与已有套餐字段混淆 | 仅将缺失余额的后备标题改为“账户余额”；门户实际提供的组合标题、零值、空白和单位原样保留并补回归断言 |
| 账号设置 | 当前账号表单和编辑器过长；新账号空密码说明矛盾；保存、删除错误滚出视口；外部锁定缺少局部原因 | 当前账号、账号簿明确区分；自适应双列编辑器；密码规则由各输入状态表达；错误放回编辑器或对应条目并聚焦；账号簿显示接管原因 |
| 外观与启动 | 最小原生窗口的退出操作被裁切；读取失败被误当作无托盘；原生离线模式展示实际无效的自启开关 | 收紧设置行使退出完整可见；未知、明确不支持和普通网页分别提示；仅原生离线模式禁用自启，浏览器模拟交互保留 |
| 认证与重试 | 地址和参数行过长；关闭证书校验后的提示与真实确认条件不符；改回原值仍提示脏状态；控件名称不明确 | 地址与时间参数网格化；区分待关闭与已保存关闭；展示净差异但保留草稿同步保护；认证选择器补明确可访问名称 |
| 环境诊断 | 概览与原文重复铺开；缺少持续完成反馈；固定页签透出下方文字 | 收紧概览，原有完整诊断文本默认折叠；完成时间、状态和焦点明确；固定页签使用实色遮挡层 |
| 日志及共享控件 | 工具栏过早换行；键盘焦点边缘被裁；高对比选择态不明显；长账号名撑破确认框 | 日志搜索按实际宽度收缩，仅窄屏分行；焦点环向内；系统高对比选中色明确；确认标题允许任意位置换行；统一按钮与选择器细节 |

业务约束继续保留：账号切换串行化与独立确认、当前账号删除保护、密码清理、未知额度语义、轮换主动开启、证书从开启到关闭时确认、忙碌期间停用自动化及退出、Esc 与键盘焦点恢复。

## 当前验证

| 检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| Svelte / TypeScript | 0 错误、0 警告 | `npm --prefix desktop run check` |
| 前端单元测试 | 42 项通过，包含组合标题及门户原文保留断言 | `npm --prefix desktop test` |
| 构建入口测试 | 5 项通过 | `npm --prefix desktop run test:build` |
| 生产构建 | 通过，无新增依赖 | `npm --prefix desktop run build` |
| 新增设计回归 | 22/22 通过 | [最终报告](../dist/ui-review-validation/final/review-report.json) |
| 玻璃样式 | 54 个合成对比度样本及渐变、悬停、辅助显示偏好通过 | [样式报告](../dist/ui-review-validation/final-glass/glass-report.json) |
| 布局与文字 | 74 个布局样本、12 组文字对比度通过 | [布局报告](../dist/ui-review-validation/final-layout/clean-desktop-report.json) |
| 原有桌面交互 | 8 组行为、19 个布局样本通过 | [交互报告](../dist/ui-review-validation/final-interactions/frontend-design-report.json) |
| 多账号交互 | 9 组行为、10 个布局样本通过 | [账号报告](../dist/ui-review-validation/final-accounts/multi-account-report.json) |
| 兼容验收 | 通过，验证诊断默认收起、聚焦和主动展开 | [兼容报告](../dist/ui-review-validation/compatibility-final/browser-report.json) |
| Linux 原生 | 最终代码离线构建、WebView 渲染、IPC、账号管理与切换、后台驻留、窗口销毁及重建通过，进程已清理 | [原生报告](../dist/ui-review-validation/native/native-report.json)、[原生截图](../dist/ui-review-validation/native/native-visible.png) |

浏览器为 Linux Chrome 154.0.8037.97，访问本轮生产构建，不是开发页面；各报告无页面异常、控制台错误或外部请求。700×560 是原生最小窗口，320/390px 是补充响应式样本，不是新增原生窗口规格。原生验收使用隔离离线数据与无网络 SDK，浏览器 IPC 注入夹具不冒充原生验证。原生短时资源采样未用作性能改善声明。

[基线回归](../dist/ui-review-validation/before-regression/review-report.json)、[中间复测](../dist/ui-review-validation/after/review-report.json)及失败日志均保留。复测中补明确认证控件名称；日志焦点测试改为真实 Tab 路径，而非鼠标模态下直接调用 focus。旧用例不再查已去重的徽章或过期长文案，转为检查可见的接管说明、禁用状态、本机浏览器及无需下载语义。没有删除业务断言或放宽溢出标准。

## 重放

前提：仓库既有桌面依赖、Python 测试环境、Chrome 和 Linux Tauri SDK 已存在。本轮未新增依赖。

```sh
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
npm --prefix desktop run build
node desktop/node_modules/vite/bin/vite.js preview desktop --host 127.0.0.1 --strictPort --port 1423
```

预览运行时，在另一终端执行；新增回归默认从当前源码生成临时离线夹具，也可通过 `--fixture` 指定已冻结 JSON：

```sh
.venv/bin/python desktop/tests/ui_review_preview.py --url http://127.0.0.1:1423/ --output dist/ui-review-replay/design
.venv/bin/python desktop/tests/glass_desktop_preview.py --url http://127.0.0.1:1423/ --output dist/ui-review-replay/glass
.venv/bin/python desktop/tests/clean_desktop_preview.py --url http://127.0.0.1:1423/ --output dist/ui-review-replay/layout
.venv/bin/python desktop/tests/rust_desktop_preview.py --url http://127.0.0.1:1423/ --output dist/ui-review-replay/interactions
.venv/bin/python desktop/tests/multi_account_preview.py --url http://127.0.0.1:1423/ --output dist/ui-review-replay/accounts
.venv/bin/python packaging/tauri_web_smoke.py --url http://127.0.0.1:1423/ --browser /usr/bin/google-chrome --output dist/ui-review-replay/compatibility
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh env CARGO_NET_OFFLINE=true node desktop/scripts/desktop.mjs --no-bundle
mkdir -p dist/ui-review-replay/native
cp desktop/src-tauri/target/release/ysu-net dist/ui-review-replay/native/ysu-net
YSU_SDK_NETWORK=none bash build/tauri-sdk.sh dbus-run-session -- xvfb-run -a -s '-screen 0 1280x900x24' env LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 build/tauri-venv/bin/python packaging/tauri_smoke.py --binary dist/ui-review-replay/native/ysu-net --output dist/ui-review-replay/native --capture-desktop
```

本轮自建预览服务在验证结束后关闭。实际最终源码、网页入口和原生程序指纹见 [SHA-256](../dist/ui-review-validation/final-sha256.txt)。验收产物位于被忽略的 `dist`，属于本机验证证据，不作为发行包。

## 当前截图与覆盖边界

主会话实际看图核对了账户、认证、账号编辑、最小窗口外观与诊断、连接窄窗以及 Linux 原生窗口；最终页面另有自动截图留存。

- [账户摘要](../dist/ui-review-validation/final/account-density.png)
- [认证参数](../dist/ui-review-validation/final/authentication-density.png)
- [账号编辑](../dist/ui-review-validation/final/account-settings-density.png)
- [最小窗口外观](../dist/ui-review-validation/final/appearance-density.png)
- [诊断反馈](../dist/ui-review-validation/final/diagnostic-feedback.png)
- [连接最小窗口](../dist/ui-review-validation/final-layout/connection-light-700.png)

三平台使用同一前端，平台特有开关按实际能力呈现。Windows/macOS 实机窗口、托盘、自启及真实校园网认证尚未验证；Linux 虚拟显示的离线通过不等同于这些环境的通过。
