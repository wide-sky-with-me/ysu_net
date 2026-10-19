# Rust 桌面界面设计

更新：2026-10-19。范围：三平台共用的 Svelte 图形界面；产品仅 Shell 与图形版，平台不是独立产品。本页保存当前视觉取舍，逐次验证独立记录；Rust 实现、原生适配和构建由桌面开发文档说明。

## 已读取的设计来源

- [FlClash](https://github.com/chen08209/FlClash/tree/03f955382409a4a7ac1f3f92e46d9fcc6d39f106)：核对固定提交的官方浅深预览、`RowCardFrame` 与设置项组件。取一体导航、无框页标题、低对比细边表面和不等宽任务网格；保留 YSU Net 的青色、本地字体和校园网语义，不引入代理、TUN、速度曲线或装饰指标。官方预览存于[本轮参考目录](../dist/flclash-layout-validation/references/)。
- [Untitled UI 免费 Figma 文件](https://www.figma.com/community/file/1020079203222518115/untitled-ui-free-figma-ui-kit-and-design-system-v2-0)：请求返回 403，未读到 Figma 画布，不声明核对过画布节点。
- [作者免费文件页](https://www.untitledui.com/free-figma-ui-kit)及[文件资源页](https://www.untitledui.com/resources/figma-files)：实际读取正文；后者说明付费文件需登录，未据此取得付费文件。免费页面公开的[设置预览](../dist/rust-desktop-preview/references/untitled-settings.webp)已下载并实际看图。取其细线设置行与稳定标签/控件比例，不采用营销页排版与强调色。
- [Linear 设置设计文章](https://linear.app/now/settings-are-not-a-design-failure)：实际读取正文及 [Display/Theme 设置截图](../dist/rust-desktop-preview/references/linear-settings.png)。取其左标签右控件、分组间留白与静态开关。
- [Linear 新界面](https://linear.app/changelog/2024-03-20-new-linear-ui)：页面显示发布日期为 2024-03-27（URL 的日期不等于正文日期）；实际读取并查看[浅深主题截图](../dist/rust-desktop-preview/references/linear-themes.png)。取中性侧栏、纸白内容、克制的灰度层次。
- [Microsoft Fluent 2 布局](https://fluent2.microsoft.design/layout)与[层级](https://fluent2.microsoft.design/elevation)：2026-10-19 实际读取正文（对应 Figma 社区的桌面设计规范文档）。取其 4px 基准间距节奏、同组卡片等高与控件高度对齐、浅色轻量阴影/深色细线控层原则；不引入亚克力/云母模糊或 Windows 专属圆角。
- [Radix 官方资源](https://www.radix-ui.com/themes/docs/overview/resources)：正文明确列出 Victor Allegret 的非官方 Figma 库；其[社区文件](https://www.figma.com/community/file/1280428825266545105)也返回 403，未读取画布或凭摘要杜撰预览。
- [BeaconTower 经典 Sky Glass 源码](https://github.com/Yoahoug/BeaconTower/tree/8ead780b932e6ff5939705acbc9d0704c1a3bda2/web)：本地只读核对该提交的 token、布局、组件、设置表单及概览截图。借鉴紧凑的指标条、双列表单、胶囊按钮、10px 输入框与统一选择器；保留校园网内容和现有可读色。没有采用另一个 `web-toy` 主题，也没有引入监控图表。
- 2026-10-17 配色修订：实际读取 [Radix 色板组合](https://www.radix-ui.com/colors/docs/palette-composition/composing-a-palette)、[色阶用途](https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale)、[Linear 改版复盘](https://linear.app/now/how-we-redesigned-the-linear-ui)与 [shadcn 主题语义](https://ui.shadcn.com/docs/theming)。采用中性灰应用底色、独立的强调/状态色对与清晰的表面层次；没有引入其组件、字体或运行依赖。实际检查 Radix Colors 3.0.0 的 sRGB CSS，并校验官方包 SHA-512；[来源记录和色阶](../dist/theme-refinement-validation/references/)保存版本与许可证。青、蓝、琥珀的浅色强调按本项目 WCAG 比值要求微调，不宣称自定义值仍是原始 Radix 色阶。

公开设置预览原图：

- https://cdn.prod.website-files.com/6365d860c7b7a7191055eb8a/69aca86b5003514d64c0bc9b_original-50abdfeffa1414ae2fc8474b1917b48a%20Large.webp
- https://webassets.linear.app/images/ornj730p/production/6677830d892c9e68200e635f8ff3c47c73afcf96-4800x2860.png
- https://webassets.linear.app/images/ornj730p/production/8b5a3c1c0e0f8ff8a46886cd21fa6de136070d37-3312x1792.png

## 当前方案与自检

2026-10-15 修订：用户要求进一步结合 FlClash 改善排版，当前采用一体侧栏、无框标题与任务卡片网格。它替代上一轮独立悬浮侧栏、半透明顶栏及三条等权重玻璃容器。

2026-10-16 细化：沿用整体结构，紧凑状态文案使用 12px 字号。自动重连仅在异常、暂停等需要处理时显示消息和重试等待，移除常规说明；流量从自动换号卡片中拆出，作为自动化区的独立全宽状态标签，保留门户原文、未知额度和零值复核提示。账号选择以省略号明确截断，悬停可查看完整身份，未命名账号不重复学号；长名称的“当前”标记保持首行对齐。

当前色板（2026-10-17 修订）：浅色使用中性画布 `#f9f9f9`、侧栏 `#f0f0f0`、实白卡片、正文 `#202020` 与次级正文 `#646464`；深色使用画布 `#111111`、侧栏/输入区 `#191919`、卡片 `#222222`、抬升面 `#2a2a2a` 与正文 `#eeeeee`。取消工作区彩色光晕、带色正文/箭头/阴影，品牌图标采用平涂；控件边界仍比装饰分隔线更明确。默认松石青为浅色 `#007b6b`、深色 `#0bd8b6`。此前灰绿/彩色中性底和渐变不再是当前默认视觉。

主题色：在“设置 → 外观与启动 → 主题色”选择松石青、海蓝、靛蓝、紫罗兰、玫瑰或琥珀；明暗模式独立，跟随系统时保留已选色。各色共享稳定中性色，只改变强调文字、操作按钮、导航/控件选中底、焦点与品牌标记；深色强调更清晰，浅色强调保留深浅底上的文字对比。名称和预览色以[选项定义](../desktop/src/lib/accents.ts)为准，非默认色维护在[主题样式](../desktop/src/accents.css)。选择同时显示名称和勾选标记，支持键盘和系统强制色；以核心快照确认结果，保存失败保留旧选择。流量已提供/不限量跟随强调色，未知保持中性，零值警告、错误及成功语义色固定；认证、轮换判据与门户原文不变。偏好兼容见[桌面指南](tauri-desktop.md)。

本地 Manrope Variable 与中文回退保持不变。正文 14px、分组标题 15px、次要文字最小 12px（不再使用 10–11px）、页标题 23px（紧凑 21px）、连接状态 22–24px；细线、字重和留白承担层级。桌面侧栏 172–184px，内容向两侧留 24–30px。宽屏连接主卡与自动化侧卡并排，下方账号和运营商分别成卡；880px 及以下改为状态、自动化、连接控制的顺序，侧栏收为图标加文字。DOM 顺序跟随视觉阅读和 Tab 顺序，不用 CSS 重排制造焦点跳跃。700×560 保留首屏关键操作，520px 及以下使用正常纵向滚动和顶部导航。

几何体系（2026-10-17 修订）：圆角收为三档，大面/卡片 20px、内层面板与提示 14px、控件 10px；按钮从胶囊改为与输入框同族的 10px 圆角，仅开关保留胶囊。标题、模式提示、卡片共享同一内容宽度与左边界，去掉横条边框。表单改为固定 132px 标签列加自适应控件；两列表单的分隔线只留一条。数字输入隐藏微调箭头，日志级别改为色点加文字。

图标体系（同日第二轮）：[图标定义](../desktop/src/components/Icon.svelte)改为 1.8 笔画、默认 18px，尺寸只用 14/16/18 与 28/32；刷新为连续双弧循环，诊断用 ECG 波形而非外框，日志用折角文档，搜索、电源、错误各有独立图形，不再共用一个符号。分段控件与主题色的选中态统一为强调色边框加浅底。连接卡操作按钮在宽屏也与标题同行。Windows 字体下的渲染可用 [Windows 渲染脚本](../desktop/tests/windows_render_preview.py)验证。

品牌区改为字标组合：品牌色圆角块内是以笔画绘制的 Y（呼应 YSU），右侧为 `YSU Net` 双字重字标与 12px 的“燕山大学校园网”。Y 不依赖图标字体或位图，随强调色平涂，窄侧栏隐藏文字时仍可识别。

账户、设置和日志共享色板与表面规则。设置页签改为紧凑分段导航，滚动时保持实色遮挡；认证区收紧浏览器提示和保存区间距，保存按钮保持可见。侧栏底部只保留简短状态，并提供完整的可访问名称与悬停提示；无文字的诊断图标已移除，诊断与版本信息集中在“设置 → 环境诊断”，不再重复常驻侧栏；纯网页的“待核心”与网络离线区分。错误聚焦为末端留出滚动余量。降低透明度时使用实色，强制颜色模式保留系统选中态和焦点。

自检关注真实信息、阅读顺序与操作可达性。不新增遥测、图表、说明性副标题或依赖；保留未知状态、门户缺项、密码清理、确认/Esc/焦点恢复、证书关闭确认、外部管理锁定及忙碌时的停止/退出。不改认证、账号持久化或原生托盘实现。

文案精简（2026-10-17）：托盘和浏览器正常时只保留控件或状态，异常时仍提供处理办法；退出影响放在确认框，清空日志的范围放在按钮提示。移除本机存储、密码输入清理和本地诊断的重复说明，密码清理逻辑不变。去除说明后，保存、诊断和退出操作保持右对齐。

界面细节第三轮（2026-10-18）：确认框图标随操作语义传入（断开用电源、删除用垃圾桶、关闭证书校验用警告、切换账号用多人、退出用退出），不再对危险操作统一显示盾牌。连接图标底色随在线/离线/未知变化；自动重连、自动换号改用独立的循环与多人图标，不再与刷新按钮、账户导航共用。流量状态并入“自动换号”卡片说明行，自动化两卡与连接主卡等高。“切换账号”仅在选中非当前账号时出现，切换完成后焦点回到账号下拉框；880px 及以下运营商列略宽于账号列。账户页两个分组标题统一置于卡片外并左对齐。账号簿只用标签标出“已停用”“待设置密码”等异常，正常状态不再逐行写出。“环境诊断”页去掉与页签重名的分组标题。

界面细节第四轮（2026-10-19）：参考 Linear 设置页、Untitled UI 与 Fluent 2 布局/层级规范细化表面与控件细节。消除设置页纵向滚动时页签顶边与圆角处的表单透出；设置面板相邻分组间补齐细线分隔，双列账号编辑末行去掉单侧不对称底线，窄屏保留 84px 标签列避免“账号认证方式”断行，只读用户名悬停不再高亮边框。连接页运营商分段器压至与账号下拉同高（36px），统一 14px 卡片间距与双行说明行高；自动重连/自动换号开启时图标随强调色高亮，关闭 HTTPS 证书校验时连接底栏切换为警告图标与警示色。标准按钮启用浅色轻量控件阴影，空状态与日志工具栏补齐卡片层级，数值与计数统一等宽数字。CLI 终端选项列表同步补齐控制字符清理后再计算列宽。

控件边线（2026-10-19，参考 Linear）：输入框、下拉框、次级按钮与卡片改用低对比中性细线（浅色约 `#dedee2`、深色约 `#37373c`），悬停只加深中性色，不再出现强调色描边；输入框聚焦改为贴合边框的柔和强调色光圈，键盘焦点轮廓降低饱和但保持可见。分段控件与主题色的选中态改为中性抬升块（白/深灰底加细阴影），不再用强调色描边加浅底。强制颜色模式下聚焦仍显示系统高亮轮廓。

## 当前评审记录

2026-10-15：本轮以生产构建截图复核宽屏、紧凑及窄屏排版；既有布局、业务与溢出断言保持，不放宽。

## 先前验证记录

本轮网页复测：2026-10-14（Asia/Shanghai），在忙碌时关闭重连与退出交互修正后再次完整运行。保留全部原有行为断言；新增 [Rust 桌面预览回归](../desktop/tests/rust_desktop_preview.py)，并同时运行[既有浏览器验收](../packaging/tauri_web_smoke.py)。既有脚本针对 Rust 浏览器认证迁移更新预期，仍覆盖连接、账户、密码、确认、日志、未知/离线/外部管理与普通网页锁定。

实际命令（仓库根目录）：

```sh
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run build
python /home/yhr/.dsh/skills/webapp-testing/scripts/with_server.py \
  --server 'npm --prefix desktop run preview -- --port 1422' --port 1422 -- \
  python desktop/tests/rust_desktop_preview.py --url http://127.0.0.1:1422/
python /home/yhr/.dsh/skills/webapp-testing/scripts/with_server.py \
  --server 'npm --prefix desktop run preview -- --port 1422' --port 1422 -- \
  python packaging/tauri_web_smoke.py --url http://127.0.0.1:1422/ \
  --browser /usr/bin/google-chrome --output dist/rust-desktop-preview/compatibility
```

最终运行将两份浏览器脚本串联到同一个临时预览服务；上述拆分命令提供等价重放。服务在脚本完成后已由 helper 关闭。

- `check`：0 错误、0 警告；TypeScript 检查通过。
- `test`：23 项通过，未更改或删除原有行为断言。
- `build`：Vite 生产构建通过；Chrome 打开构建产物，不是开发服务器页面。
- 真实 Chrome：`/usr/bin/google-chrome`，版本 `154.0.8037.97`。新增回归 8 组关键行为通过；19 个布局样本无文档/主内容横向溢出，无标签与控件重叠。包含全部设置分区的 700×560 与 390×844 样本。
- 键盘与约束：Tab/Shift+Tab 确认弹窗循环、Esc 取消与触发器焦点恢复；页签方向键/Home/End 与单 Tab 停靠；密码保存、离开主页面和离开账号页签清空；下线关闭自动重连；切换确认；证书关闭二次确认；忙碌时仍可关闭重连或退出，连接及切换保持禁用；外部管理锁定；系统主题、日志搜索/级别/复制/清空均通过。
- 控制台错误、页面异常与外部请求均为 0；浏览器存储为空。仅使用离线模拟数据，未读取个人配置，未联网认证，未启动默认真实原生应用。

报告：[新增设计回归](../dist/rust-desktop-preview/frontend-design-report.json)、[既有验收回归](../dist/rust-desktop-preview/compatibility/browser-report.json)。

实际截图并看图审视：[浅色连接](../dist/rust-desktop-preview/connection-light.png)、[浅色账号设置](../dist/rust-desktop-preview/settings-light.png)、[浅色桌面设置](../dist/rust-desktop-preview/settings-desktop-light.png)、[浅色认证设置](../dist/rust-desktop-preview/settings-authentication-light.png)、[深色设置](../dist/rust-desktop-preview/settings-dark.png)、[紧凑设置](../dist/rust-desktop-preview/settings-compact.png)、[紧凑认证](../dist/rust-desktop-preview/settings-compact-authentication.png)、[紧凑重试与保存](../dist/rust-desktop-preview/settings-compact-parameters.png)。其余状态与账户/日志截图同目录保存。

## 先前审视与边界

真实 Chrome 曾暴露两个实际失败：原生 dialog 的末尾 Tab 让焦点离开弹窗，已在 [Confirm](../desktop/src/components/Confirm.svelte) 补双向循环；入口缺图标产生 favicon 404，由入口本地图标修复，零控制台错误断言保持。截图审视后修正选中页签悬停的弱化问题，长认证页固定页签，在 DOM 更新后重置滚动，紧凑窗口滚动到保存区时仍有任务上下文。没有用删除断言或忽略错误取得通过。

此前前端证据来自 Linux Chrome 构建预览，迁移时的 Linux 原生 WebView 与生命周期演示见 [Rust 迁移验收](rust-desktop-validation.md)，不作为当前前端成绩。当前浏览器回归以 CI 中的 [Rust 桌面预览回归](../desktop/tests/rust_desktop_preview.py)、[多账号回归](../desktop/tests/multi_account_preview.py)与[既有浏览器验收](../packaging/tauri_web_smoke.py)为准。缺少浏览器/浏览器模块与未就绪环境的说明分支保持；Windows/macOS 原生窗口、托盘、自启、系统浏览器发现及真实校园认证仍待对应实机验证。
