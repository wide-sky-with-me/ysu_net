# Rust 桌面界面设计

[返回首页](../README.md) · [Tauri 桌面说明](tauri-desktop.md) · [产品与架构](architecture.md)

本页维护三平台共用 Svelte 界面的现行视觉规则。更新：2026-10-23。实现见 [app.css](../desktop/src/app.css)、[主题色](../desktop/src/accents.css)和[页面动效](../desktop/src/lib/motion.ts)。

## 设计方向与来源

本轮按用户要求，以 [FlClash](https://github.com/chen08209/FlClash) 的圆润、分层表面和响应式内容组织为参考，替换此前偏 Linear 的内嵌白纸面板。参考的是设计原则，不复制其 Flutter 实现、标识或代理软件功能，也不引入 Flutter、组件库或远程素材。

参考源码固定为官方 `8d4f9744948751f1273fe871e1d05276fac09b0e`：

- [表面层级](https://github.com/chen08209/FlClash/blob/8d4f9744948751f1273fe871e1d05276fac09b0e/.agents/surfaces.md)：用底色明度区分页面、卡片与内部控件，不给所有卡片描边或添加阴影。
- [形状](https://github.com/chen08209/FlClash/blob/8d4f9744948751f1273fe871e1d05276fac09b0e/lib/ui/shape.dart)及 [Dashboard 布局](https://github.com/chen08209/FlClash/blob/8d4f9744948751f1273fe871e1d05276fac09b0e/lib/views/dashboard/layout.dart)：区分主卡、次级块与胶囊控件的圆角和空间层级。
- [导航](https://github.com/chen08209/FlClash/blob/8d4f9744948751f1273fe871e1d05276fac09b0e/lib/ui/sidebar.dart)：中性选中底色配细强调色标记；交互反馈不改变命中范围或业务状态。
- [安卓连接图形](https://github.com/chen08209/FlClash/blob/8d4f9744948751f1273fe871e1d05276fac09b0e/lib/views/dashboard/widgets/current_outbound.dart#L683-L844)：状态改变时采用 450ms 形状/图标回弹，作为本项目状态反馈的节奏参考。该版本的[流量数字](https://github.com/chen08209/FlClash/blob/8d4f9744948751f1273fe871e1d05276fac09b0e/lib/views/dashboard/widgets/traffic.dart#L42-L73)本身为静态文本；这里的数字滑入是本项目新增实现，不声称复制上游计数动画。

本项目不声称复现上游全部动效；例如上游桌面一级导航并非移动端的淡入转场。这里按校园网工具的焦点、凭据清理和原生 WebView 约束独立实现短进入动画。

## 内容与布局

- 侧栏宽 196px；1100px 及以下为 184px，880px 及以下收为 80px 图标导航。520px 及以下品牌和导航位于顶部，文档自然滚动。
- 品牌保留“山形网络节点”标识、“燕大校园网”主标题与“YSU Net”副标题；标识跟随主题强调色，完整校名保留在无障碍名称中。系统应用与托盘底图未变，原生状态角标独立着色。
- 移除围住所有内容的大白色面板与密集细边框。页标题采用 24–26px 层级；内容最大宽 1056px，间距以 4px 为基准。
- 连接页按实际状态主卡、自动化操作、账号与运营商依次组织。主卡改为紧凑状态图形、清晰标题和横向胶囊操作，运营商、账号与 IP 用细线划分的数据行呈现，不再套三块同等重量的浅底卡片。移除常驻证书/API 说明；仅证书校验关闭时保留独立异常警告。不新增无数据依据的速率、延迟或流量图。
- 账户页突出真实套餐及用量，不再补造账户余额卡、演示金额或余额专属提示。已知正数流量卡用底部轻波纹增加可见动感，数值和单位仍保持完整原文；装饰不代表额度比例、实时速率或正在传输。“在线信息”使用账号身份主块与服务/地址详情组合，配合语义图标和层级字号，窄屏上下重排。原名称、值、重复字段及未知字段全部保留；缺少账号字段时不从当前配置补造身份。实现见 [OnlineDetails](../desktop/src/components/OnlineDetails.svelte) 与[分组逻辑](../desktop/src/lib/onlineDetails.ts)。设置按独立分区卡组织，设置 Tab 仍在主滚动区内吸顶。日志保留筛选工具条与独立滚动列表。
- DOM、阅读与 Tab 顺序一致；保留唯一 `main#main-content`、原生 dialog/select、设置 Tab 的关联和所有键盘入口。紧凑视图压缩留白，但不隐藏忙碌时仍可关闭的自动化开关或退出入口。
- 托盘右键菜单沿用原生控件：带 16px 状态图标的固定中文品牌标题兼作打开窗口入口，连接状态与账号/运营商合并为最多 32 字符摘要，IP 和最近结果（36 字符摘要）收进“连接详情”，快捷操作、自动化、退出分组。动态文字使用普通菜单项，规避 GTK 图标项组合标签不随文字 setter 刷新的问题。确认离线为红色，在线为绿色，处理中/未知为警告色；不添加悬浮 WebView，菜单背景、字体及圆角由操作系统决定。

## 色彩、字体与形状

| 用途 | 浅色 | 深色 |
| --- | --- | --- |
| 页面底色 | `#f3f5f9` | `#121824` |
| 卡片 | `#ffffff` | `#1c2534` |
| 内部控件底色 | `#f1f4f9` | `#263246` |
| 正文 | `#1b283b` | `#e5ebf6` |
| 次级文字 | `#6a778b` | `#a7b2c6` |
| 默认强调色 | `#3b6ed4` | `#9bbcff` |

- 默认采用雾蓝强调色与蓝灰白表面；松石青保留原绿色表面配色，作为可选主题。六种主题色继续与明暗模式独立。状态胶囊与连接图形统一采用在线绿、确认离线红、未知警告色，未连接核心保持中性，不随主题色改变。默认及已有偏好的兼容规则见 [Tauri 桌面说明](tauri-desktop.md#配置与演示)。
- 卡片通常 28px、连接主卡 28px、内部块 18–20px、输入控件 12px；按钮和分段选择采用胶囊。紧凑及窄屏按可用空间收敛圆角，不依赖浏览器专有形状能力。
- 普通分区卡无投影；连接主卡以细线分隔信息，真正浮起的确认框才使用独立阴影。浅色靠实色层级、深色逐级提亮，不铺满透明磨砂效果。
- 使用本地 Inter Variable 与系统中文字体，不联网下载字体。正文 14px，次级文字不小于 12px；数字使用等宽数字。连接状态 21–23px，用量数字 28–32px，缺失值不放大或补造。

## 交互动效与可访问性

- 页面/设置分区变化时，仅对现有内容表面执行 240ms 的透明度和 8px 纵向进入，多个同级表面最多错开 48ms。快照更新不反复播放；切页、卸载、焦点恢复和密码清理不等待退出动画。
- 状态胶囊与连接图形在首次确认及真实状态变化时，执行一次 450ms 回弹与淡出光环；不持续呼吸，不将提交确认或普通刷新当作连接成功。相同状态快照不重播。
- [数值组件](../desktop/src/components/AnimatedMetric.svelte)仅对真实完整数值执行一次 450ms 轻滑入；同值不重播、不拆开单位、不从零补造中间额度。持续的[流量波纹](../desktop/src/components/QuotaAmbient.svelte)只是一层无障碍隐藏的装饰：双层 SVG 平移，周期 7s / 11s，不增加数值、刻度或百分比。仅已知正数流量出现；缺项、零值与不限量不启动。
- 按钮采用 160ms 的背景与轻按压反馈，导航标记采用短缩放过渡；开关滑块使用 220ms 的位移反馈，其选中值仍只来自核心确认的快照。
- 原生确认框用 220ms 轻上移/缩放进入，背景 180ms 淡入；保持取消首焦点、Tab 循环与 Esc 立即关闭并还焦点，不添加延迟关闭。
- `prefers-reduced-motion: reduce` 禁用 CSS 动画与过渡；有限动效同时监听偏好变化，立即取消 Web Animations 及待执行帧。流量装饰在离屏、页面隐藏、减少动效时暂停，销毁时移除可见性监听并断开观察器，不新增轮询。数值始终直接展示完整正文。无全局平滑滚动，不与编辑器的显式滚动及焦点定位竞争。
- 强制颜色模式使用系统边界与强调色，键盘焦点有真实轮廓。所有页面保留未知、确认离线、读取失败与门户缺项的原有语义；无乐观在线状态，也不改变密码、配置、认证或更新协议。

## 验证

[原有页面回归](../desktop/tests/rust_desktop_preview.py)和[多账号回归](../desktop/tests/multi_account_preview.py)继续覆盖焦点、密码清理、状态、700×560 / 390×844 / 320×720 无横向溢出及设置吸顶。

[动效单元测试](../desktop/src/lib/motion.test.ts)检查帧调度、同值不重播、可见性暂停、减少动效和销毁；[圆润界面回归](../desktop/tests/rounded_desktop_preview.py)检查真实状态、绿红语义、流量原文与无障碍读取、持续波纹及离屏暂停、无伪造余额、原生弹窗焦点和六种主题色/明暗模式组合。它已加入 [Tauri CI](../.github/workflows/tauri.yml) 的构建后浏览器验收。

```bash
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run build
# 启动 Vite preview 后：
uv run --no-sync python desktop/tests/rounded_desktop_preview.py \
  --url http://127.0.0.1:1421/ --browser /usr/bin/google-chrome
```

浏览器演示数据不代表真实校园网；Linux 原生运行和三平台打包说明见 [Tauri 桌面说明](tauri-desktop.md)。三平台共用此次界面源码，不将本机 Linux/浏览器验证宣称为本轮 Windows、macOS 或真实认证验收。本轮实际构建、失败复测和未覆盖范围见 [2026-10-23 候选验收](desktop-candidate-2026-10-23.md)。
