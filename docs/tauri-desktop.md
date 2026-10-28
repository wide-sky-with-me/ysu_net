# Tauri 原生 Rust 桌面版

[文档导航](README.md) · [桌面使用指南](wiki/Desktop-Client.md) · [两个产品与架构](architecture.md) · [Rust 迁移决策](../.agents/notes/proposals/desktop/2026-10-14-rust-desktop.md)

自 **v0.2.0** 起，桌面采用 Tauri 2 + Svelte + 全 Rust 认证和后台，Windows / Linux / macOS 共用源码。Python CLI 与 systemd 独立保留，不是桌面运行时；源码版本与正式发行的区别统一见[首页发行状态](../README.md#发行与候选状态)。原 Qt 客户端与 Python 旁车源码已移除，新桌面不启动或打包 Python、Node、Playwright 认证运行时，也没有 Python `gui` 可选依赖。正式附件从 [GitHub Releases](https://github.com/wide-sky-with-me/ysu_net/releases/latest) 下载，发布仍要求四平台构建、原生 / 安装及独立浏览器验收成功，旧 `v0.1.0` Qt 附件保留历史。安装及旧自启迁移见[迁移说明](migration.md#桌面-v020-升级)。

## 运行语义

[认证库](../desktop/crates/ysu-auth/src/lib.rs)实现 Portal/CAS、加密、状态、登录、下线、运营商切换及账户解析；[原生运行器](../desktop/src-tauri/src/runtime.rs)调度有界串行任务、重连、取消与快照。前端只提交类型化命令，排队确认不是认证成功。

连接与实际运营商以独立状态查询为准；查询失败保持未知，不触发自动登录。显式切换失败尝试有界恢复，只在确认目标服务后保存服务字段。用户认证操作及一次自动重连的查询、变更与核验共享配置的总超时；超时后提示重新查询实际状态。自 0.2.1 起，账户刷新包含账户读取和随后独立状态核验，两段共用一次总预算；账户读取失败但状态核验在线时保留在线，状态核验失败或复合刷新超时则转未知，不从账户缺项推断离线。快照 `info_error` 提供固定公共错误，旧快照缺该字段按空串处理。页面区分未知、确认离线、未读取和失败，成功后清错；新在线观测会作废旧离线账户结果。缺项、原文和零值按门户数据展示；界面、CLI 和演示不补造账户余额，原始响应与任意真实条目不因此丢弃。

配置字段与 Python CLI 兼容；密码仅在本机配置保存，快照无密码字段，空密码保存保留原值。设置更新在独立短写锁下合并最新配置并原子替换，认证/守护使用兼容运行锁。环境变量 `YSU_USER`、`YSU_PASS`、`YSU_SERVICE` 保留原覆盖语义；修改磁盘值不覆盖仍生效的环境变量。

0.2.1 日志保留 `action / phase / code / operation / stage / reason` 固定分类，不传出底层任意错误、网址查询串、账号或 Cookie。`code=2` 是查询类失败，`3` 是操作未核验，`4` 是需要人工处理；分类不代表已经确认 DNS、TLS 或账号故障。设置中的本地环境诊断不是接口登录测试。错误后的重试先确认是连接页“刷新状态”还是账户页“刷新账户”；默认总时限 180 秒不含队列及配置读取，转圈期间仍可能显示旧观测。

[多账号与流量换号](accounts.md)提供独立账号簿、确认后热切换与默认关闭的零流量轮换。前端不负责轮换调度；原生后台以同账号/服务绑定的独立查询为依据。关闭自动重连或下线同时关闭轮换，状态未知、额度缺失及业务失败不触发换号。

### 独立只读状态观察

“日志”页的[链路调试记录](debug-recording.md)是开发源码新增的显式本地记录入口，正式 0.2.3 尚无此功能。它不发起认证、不改变跳转、TLS 或未知状态的处理；文件、范围与复现步骤以该指南为准。

只读观察、API HTML 导航规范化与 Info 来源配对纳入 0.2.3，共用源码的云端与真实验证见[0.2.3 发布记录](desktop-release-0.2.3.md)；早期开发候选的分轮证据仍归[历史对照](auth-flow-review-2026-10-27.md)。选择原因和限制见[只读观察决策](../.agents/notes/implemented/desktop/2026-10-27-passive-state-observation.md)。

原生 Worker 在自动重连关闭时也独立观察连接状态，托盘后台不依赖 WebView 定时器。健康周期为 30 秒；窗口获焦 / 恢复可见和 `online` / `offline` 事件只是查询提示，前端合并 300ms 内的突发事件，不从 `navigator` 或 IPC 接收确认推断在线 / 离线。界面只接受正常单调快照流中的原生结果。

观察使用缓存配置的临时 API 副本，单次 Status 预算为 `min(operation_timeout, 2秒)`；不启动浏览器、不读取私有 Info、不登录 / 下线、不保存账号或配置。即使保存的 backend 是 browser，被动读也不启动 Chromium；手动操作与自动认证仍尊重用户保存的 backend。API 不能确认时记未知，不据此自动认证，也不把本轮修正解释为应直接改用 browser。

原生成功采样后以 2 秒冷却合并提示，可复用手动 / auto 已取得的状态；失败后台按 60 / 120 / 240 / 300 秒退避。失败后的显式提示最早在该采样结束 30 秒后再查，不清失败计数，也不重置自动重连 / 轮换的计划或退避。手动队列优先且观察不占其容量；工作门闩拒绝时保留待处理提示，将观察准入至少后移 2 秒，避免过期计时器自旋。

被动读仍持有原认证门闩：在途短读会拒绝安装准入，应在短读结束后重试，不是更新强行中断它。空闲更新置 stop / updating 后不准入新观察；退出或 force-stop 取消在途 future，由 RAII 释放门闩，不发布迟到结果。观察不为每轮设置 busy、成功浮层或成功日志；错误用固定脱敏分类，观察错误日志最多每 60 秒一条。

状态身份按实际 user / service / IP 绑定；变化时旧 Info 及旧身份读取错误失效，不回写保存账号。未知清旧详情并保留最近已确认身份，供同身份恢复时保留仍有效的读取错误；确认离线清旧详情和旧读取错误。被动观察只更新状态，不自动补读账户详情。纯网页 / 前端 Demo 不发送原生观察，原生 Demo 只读内存；Windows / Linux / macOS 共用此 Rust 实现，CLI 没有桌面焦点事件，本轮不改变其后台行为。

显式账户读取另做来源绑定：认证库返回 `InfoObservation { status, info }`，在同一个 session / lock / operation deadline 内执行初始 snapshot → 账户只读 → 再 snapshot，按实际 online / user / service / IP 前后配对。空字段照实比较，不猜补或增加非空 / 配置 owner 门槛；实际 tuple 变动才报 `IdentityMismatch`，后查失败用固定 code 2 / Verification 文案并保留原网络、响应或超时 Reason，不伪称已换号；初查与账户读取失败的原分类优先语义不变。确认离线仍返回原 offline JSON，且不读账户；原 `info()` 继续只返回 `info` JSON，不把来源元数据混入展示字段，也不改轮换用 `verified_info()` 的严格语义。

Native 仍在账户读取后独立查询 Status；提交成功详情前再以 `matches_status` 配对该次实际状态，不匹配就拒绝旧详情写回并给出固定身份不一致错误，不把错配当作离线。独立确认离线仍优先，复查失败仍是未知；已有账户读取错误不被新增错配诊断覆盖。不解析中文 `fields` 或用保存账号当 owner 门槛，保存意图为 A 时仍可无凭据只读当前外部账号 B，不改账号、auto 或轮换设置。

在线读取比旧库多一次状态查询，新增核验与原步骤共享既有预算，不叠加新的整轮时限；无登录、下线或配置写。前后采样与本机串行提交不是远端原子事务；缺字段可能掩盖实际变化，也不能保证发现采样间 A→B→A 的 ABA 变化。来源晚写反例已在新候选独立回归，不把首轮观察器成绩代替来源绑定的验证。

### 门户导航与诊断

精确来源变体、Browser bootstrap Location 接线与分类诊断纳入 0.2.3，最新验证归[0.2.3 发布记录](desktop-release-0.2.3.md)。早期候选 `2bb9589e` 的四目标 Native、Mock 与 Community 成绩及 111 只读样本仍归[历史记录](portal-navigation-review-2026-10-27.md)，不将其作为新登录或 Win11 网页下线的证明；选择原因见[精确来源决策](../.agents/notes/implemented/desktop/2026-10-27-portal-entry-variants.md)。

来源只增加由配置 endpoint 派生的第二个完整 Url：原无 query 的精确 redirect 入口，以及唯一精确 `mode=history` 变体；不剥除任意 query，不通配额外 / 重复 / 编码参数、域名或路径。它们才可使用原受限 HTTP 目标规范化：无 body GET、HTTPS base 默认 443、同 host 的 HTTP 默认 80、配置 endpoint 派生的固定目标路径（`portal_main` 角色），目标无 userinfo / fragment，唯一 sessionId 的解码值非空、不超过 1024 字节且无控制符；先转换为 HTTPS 再做原 allowed 检查，不发明文 HTTP、不清改目标 query。

API 的 HTTP Location 和 HTML / meta / JS bootstrap 解析共用 checked 入口。Browser 只对明确 bootstrap 阶段、本主 CDP session 的主 frame Document、实际 GET 无 body 响应中的 HTTP Location 使用同一规则，来源取本次 request URL，不取旧 `last`；通过后将 HTTPS 目标真正写回 CDP 响应 Header。CAS、iframe、子资源、POST / HEAD 等不享受该例外；未证 Browser HTML / JS 来源不补，不能把切换 browser 当作已验证的现场解法。

拒绝导航可附可选 `NavigationDiagnostic`：只输出闭集 enum / bool 的来源 / 目标角色与形状，不保存或输出原 URL、host、path、query 值、Cookie、票据、账号或密码。`role` 按完整配置 origin 分类，独立 `host_role` 只按精确 host 分类：同门户 HTTP 可同时是 role=other、host_role=portal，两者都不授予导航许可。None 时旧 JSON / 日志不变，原 code / reason / stage / operation 保留，Native 仅在有该 metadata 时追加固定分类，不写进账户 Info；这些 token 不是具体目标或认证根因的证明。

上述 history 阶段未改 TLS、CAS / API / POST 通用边界、默认入口列表、超时 / 重试、加密或凭据用途。111 当时在线且仅跑独立 Requests 观察器，详细限制归[当次记录](portal-navigation-review-2026-10-27.md)；123 离线后新发现的 captive 引导另见下节。

### 离线 captive 与 CAS 表单

CAS 风险提示检查文档文本，排除脚本 / 样式 / 模板 / noscript 与属性引用，避免正常门户资源中的 noSupport 被当成拒绝；它不计算完整 CSS 可见性。回调仍要求门户同源、成功 HTTP 响应，并在后续流程节点及独立状态中确认身份 / 服务。来源异常与实际提示拒绝的诊断分开，原因见[回调风险文本决策](../.agents/notes/implemented/desktop/2026-10-28-cas-callback-risk-text.md)。本轮结果归[0.2.3 记录](desktop-release-0.2.3.md)。

123 的受控下线实测发现，无 query 的 HTTPS redirect 入口会返回固定 `http://124.124.124.124/`；该地址的 HTTPS 证书校验失败。当前新增专用匿名 GET 解析器：仅精确来源、精确根目标、GET 无 body，且每个 Transport 及其克隆合计一次。使用无 Cookie jar、无继承请求头、禁代理及禁自动重定向的独立客户端；复用现有响应大小和绝对 deadline，不运行页面 JS，不采用其中的 SID、Cookie 或 Location。

匿名页面只可提供配置门户同源、固定 index 路径的 HTTPS 导航提示，拒绝 userinfo、fragment 和 sessionId / flowSessionId / ticket；后续由 HTTPS 门户重新产生会话并查询状态。通用 allowed / API / CAS / POST 仍拒绝 HTTP；原有同门户旧地址 HTTPS 规范化继续有效。API 的 HTTP Location 与 HTML 导航共用同一异步解析入口；Browser 仅在 bootstrap、主 session / 主 frame Document、GET 无 body 的同等上下文接入 Location。对于 200 text/html 中已许可的静态 HTTP 跳转，Browser 生成受控 302 HTTPS Location 并清空 body，仍计入原重定向预算；Chromium 不加载或执行明文 captive 页面。普通 HTTPS HTML、CAS、iframe 和子资源保持原处理。接线取舍见[共用导航决策](../.agents/notes/implemented/desktop/2026-10-28-shared-bootstrap-navigation.md)，Shell 两条实际路径及证据限制见[对照记录](portal-redirect-parity-2026-10-28.md)。

CAS API 的 captchaDiv 检查仅接受所选密码表单与无所属 form 的独立挑战，忽略其他登录方式复用的 ID；验证码接口要求为 true 时仍停止。Browser 保留已有实际布局可见性检查。Python CLI 同步限定密码表单与独立挑战，并解析完整标签属性，避免 class / style 位于 id 前时误判；可见挑战不被接口 false 覆盖。

Rust 与 Python 的动作响应同时检查外层及 data 的 authResult / authMessage：authResult 存在时仅接受字符串 success，其他值停止；success=false 也停止。服务选择被拒后不再请求 userOnline，后续成功仍以实际账号与服务独立核验为准。固定错误分类不输出服务器原文。

本节能力纳入 0.2.3。Rust 共用 AuthClient 已在 21 完成真实离线登录、在线退出与 Shell 独立核验，Windows 原生探针也完成无凭据在线查询，证据及边界归[0.2.3 发布记录](desktop-release-0.2.3.md)。123 的 CAS 后服务拒绝曾在正式 v0.2.2 Python CLI 上以相同测试输入复现，不能作为 Rust 专属导航故障或配置无效的证明；原采样与当时状态见[123 记录](portal-123-review-2026-10-27.md#2026-10-28-正式-python-cli-对照补证)，协议选择见[决策](../.agents/notes/implemented/desktop/2026-10-27-offline-captive-bootstrap.md)。

同日[21 换机对照](portal-21-review-2026-10-28.md)已用现有客户端与相同正式 v0.2.2 wheel 完成真实离线登录及在线退出，并恢复原连接和后台。21 使用本机中国移动配置且 DNS 正常，和 123 的输入 / 网络条件不同；这是 Shell 正常链的补证，不是 Rust 或本节新源码验收。

### DNS 失败时的备用 IP

认证 URL 继续使用配置中的 HTTPS 域名。系统 DNS 能及时返回地址时优先采用；失败、无地址或等待超过 500 毫秒时，仅对[共享地址表](../src/ysu_net/auth/campus-addresses.json)中的两个精确校园域名使用备用 IP。只改变 TCP 连接地址，HTTP Host、TLS SNI、证书域名校验、Cookie、Origin 与跳转许可仍按原 URL 处理。自定义域名、后缀相似域名及其他站点没有此回退。

500 毫秒包含在操作原有的绝对 deadline 内，不延长单次任务，也为总预算 2 秒的被动观察保留网络时间；不能保证全部门户请求在剩余预算内完成。取消等待不保证立即终止底层系统 DNS 工作线程，但它不能继续发送 HTTP。TCP 失败、TLS 失败、HTTP 或业务拒绝不触发备用 IP 重试，不重放已提交的请求。

| 入口 | 接入范围 |
| --- | --- |
| Windows / Linux / macOS 原生桌面 API 与 Browser | 共用 Rust Transport 的 resolver；CDP 页面流量由 Rust 接管 |
| Python CLI 默认 API | 自有 Requests Session 的 HTTPS adapter；系统解析报 DNS 错误后回退，等待时长由系统解析器决定，仍受 CLI 子进程总时限约束 |
| Python 可选 Playwright Browser | 尚未接入；其浏览器及 Node APIRequestContext 仍依赖系统 DNS，需要先修复系统解析 |

地址表由 Python 包内 JSON 唯一维护，Rust 编译时嵌入；Python 分发必须携带同一文件。Python 不修改全局 socket、其他 Session 或代理管理器；使用环境代理时仍由原代理路径处理，不保证本机备用地址生效。原生客户端继续采用已有的直连策略。无需新增配置或把 `base` / `cas_host` 改为 IP。

备用地址的 DNS / TLS 可达性采样见[当次证据](portal-ip-fallback-2026-10-28.md)，来源和取舍见[决策](../.agents/notes/implemented/desktop/2026-10-28-campus-ip-fallback.md)。相关 resolver、Python 回环 TLS 和分发数据回归已纳入 0.2.3 云端检查，实际运行归[发布记录](desktop-release-0.2.3.md)。21 真实 Rust 对照及 Windows 查询使用各自网络条件，不是 123 DNS 故障下的新 Rust 登录证明。备用地址失效仍需更新，正常 DNS 返回不可达地址时不会改用备用 IP。

### 无界面认证验证

认证链也可脱离界面定位：[无界面 Rust 验证入口](rust-auth-probe.md)直接调用本桌面的 AuthClient，校验真正离线登录、在线退出与独立前后状态，并保留固定导航诊断。四目标认证工作流已通过，云端产物已用于 21 真实闭环及 Windows 无凭据查询；它不覆盖 Worker / WebView / 窗口集成，Shell 的成功记录也不替代 Rust 验收。

### 窗口与系统集成

关闭窗口只有在系统托盘实际可用且启用驻留时保留后台；否则退出。主窗口销毁后可重建，认证和重连不依赖 WebView 存活。关闭自动重连不下线，忙碌时仍可关闭重连或退出；显式下线同时停止重连；退出取消本客户端任务并释放锁，不主动下线已建立的连接。`--minimized` 在无托盘环境显示窗口，避免应用隐身。

托盘与主窗口共用核心快照与串行任务入口。固定中文品牌标题带状态角标，点击即打开主窗口；连接状态与账号/运营商共用紧凑摘要，上次流量独立展示，IP 与最近结果放入“连接详情”。连接/断开和刷新、自动化开关、退出分别分组。状态未知时只查询，不从托盘猜测登录；缺少凭据时引导打开窗口设置。额度缺失或账号/运营商不匹配时显示待核验。

菜单使用系统原生控件，背景、字体、圆角和高对比度行为由系统决定，不使用额外 WebView 模拟。Windows/macOS 保留原生悬停摘要；Windows 按 UTF-16 长度收敛，长账号与最近结果在菜单中省略，完整内容可到主窗口查看。Linux 不支持 Tauri 托盘 tooltip 和图标鼠标事件，通过菜单标题打开窗口并提供等价状态与操作。Linux 后台每十秒检查宿主，宿主退出时恢复窗口；聚焦窗口时重新读取能力。并发与平台选择见[托盘决策](../.agents/notes/implemented/desktop/2026-10-15-tray-control.md)。

自启使用 Tauri 原生插件，只在用户登录桌面后运行；“自启后进入托盘”默认开启，关闭后登录自启显示窗口，手动打开始终显示窗口。新自启项使用 `--autostart` 按偏好决定启动方式；旧 `--minimized` 保留强制托盘含义，无可用托盘或宿主时仍显示窗口，原生自检始终显示。更改启动方式只在原自启项已启用时先更新其参数、回读确认后保存偏好，不启用原已关闭的自启，不立即隐藏当前窗口；保存失败保留旧偏好，状态读取不修复或重写启动项。重复后台启动不抢焦点，手动再次打开仍唤起原实例、不更换配置。Linux 无桌面运行继续使用 CLI/systemd；迁移时先关闭旧客户端自启，当前不自动删除旧启动项。新旧包身份与发行限制见[架构边界](architecture.md#构建与发行边界)。

软件内更新的入口、整包 / 条件差分传输、平台差异与信任边界统一见[签名在线更新](updates.md)，不以合入主线或支持能力推断新正式发行、实际附件或真实安装已经通过。现行主题、字段对齐、“关于”、反馈浮层及连接光环规则归属[设计说明](rust-desktop-design.md)；历次构建与部署证据见[桌面验收导航](desktop-acceptance.md)。

“关于”同时展示离线更新日志、GitHub 地址和贡献者名单。日志只从唯一维护的 [release-notes.md](../packaging/release-notes.md) 派生转义文本，不读取可能落后的默认分支，也不把 feed 中的占位 notes 当完整日志。贡献者只使用[公开 API 核实快照](../desktop/src/lib/project-info.json)，显示快照日期，不推导邮箱、加载网络头像或在打开页面时抓取 GitHub；本地未发布改动不写进已发布日志。

项目外链由[原生固定目标命令](../desktop/src-tauri/src/project.rs)打开，只接受 repository / contributors 字符串枚举，拒绝 URL、程序和对象输入；发布页沿用原有无参数更新命令。Demo 在原生端先拒绝，页面也禁用外链；普通网页使用固定公共锚点。打开失败只显示固定错误及可复制公共地址，不泄露系统异常。打开“关于”仅读取更新状态，不触发检查、下载或安装。

## 浏览器模式

默认 API 模式直接使用 Rust HTTP、Cookie 和加密实现。可选浏览器模式由 Rust 通过 CDP 驱动本机 Edge / Chrome：CDP 只走私有匿名管道（`--remote-debugging-pipe`；POSIX 为 fd 3/4，Windows 为仅继承给该进程的两个句柄），不开放本机调试端口，其他本机进程无法连接或读取登录页与凭据。浏览器使用专用临时目录，不复用个人浏览器资料，不下载 Node 或认证组件。需要系统已有可用 Chromium 系浏览器；验证码、风控或无法确定的页面状态返回需人工处理的结果，不伪造在线。

设置中的“刷新浏览器状态”和“运行本地诊断”仅检测环境，不发起登录。旧内部 `browser_install` 命令保留为刷新诊断的兼容入口，已无下载行为。CLI 的 Python 浏览器实现保持原流程，不将两种产品的运行依赖混为一谈。

## 构建前提

**编译和打包只在 GitHub Actions 执行**；本机只下载、校验云端产物并做安装与运行验收，不运行 Cargo/Rust 编译或前端生产构建，云端失败也不回退本地编译。开发构建使用独立构建分支，不打版本标签、不发布正式 Release，保护当前工作树、开发分支和暂存区；约束见[项目规则](../AGENTS.md#构建执行位置)。

以下工具和 SDK 均为云端 runner 前提：Node 22.12 / 24 / 26 及更新受支持版本、Rust 和平台 SDK；以 [package.json](../desktop/package.json)、[Cargo.toml](../desktop/src-tauri/Cargo.toml)及锁文件为准，当前工作流使用 Node 24。桌面构建本身不需要 Python、uv 或 PyInstaller；Python 仅用于 CLI 和外部验收脚本。

- Windows x64：Visual Studio C++ 桌面构建工具、Windows SDK；客户端使用系统 WebView2，安装器可按原配置引导安装。
- Linux x64：Ubuntu 22.04 / glibc 2.35 构建基线，依赖 WebKitGTK 4.1、GTK3、AppIndicator；SDK 清单见 [tauri.Dockerfile](../packaging/tauri.Dockerfile)。
- macOS：Apple Silicon（arm64）/ Intel（x64）分别原生构建 `.app` / `.dmg`，不是通用二进制；最低系统为 13.5，更早系统须独立验证后再调整。

跨系统安装包在对应系统的 GitHub Actions runner 构建。Windows / macOS 的系统发布者签名限制与安装迁移见[迁移说明](migration.md#桌面-v020-升级)，更新签名另见[更新说明](updates.md)；下载核对 `SHA256SUMS` 或对应 Actions artifact 的摘要与来源身份。平台是否跑通以对应实际验收记录为准，不依据框架支持推断。

```bash
npm ci --prefix desktop
# 仅示意 GitHub Actions runner 的步骤，禁止本机执行：
npm --prefix desktop run native:build
# 按 runner 平台选择格式，例如 Linux：
npm --prefix desktop run native:build -- --bundles deb
# Windows / macOS 正式标签作业由受保护环境提供签名配置：
npm --prefix desktop run native:build -- --signed-update
```

[构建入口](../desktop/scripts/desktop.mjs)在 runner 上核对桌面内部版本、生成图标，然后调用锁定依赖的 Tauri 构建。默认 Linux `deb`、Windows `nsis`、macOS `app,dmg`；云端产物位于 `desktop/src-tauri/target/release/bundle/`，由工作流上传附件。图标、前端产物和目标目录是生成物；不要在本机直接运行 `tauri build` 或为验收补做本地编译。

## 配置与演示

正常启动支持 `--config PATH` 或 `YSU_DESKTOP_CONFIG`。默认 Windows 使用 AppData/Roaming，Linux/macOS 沿用 `${XDG_CONFIG_HOME:-~/.config}/ysu-net/`。再次启动只聚焦同一实例，不改变既有配置或演示模式；更换模式前先退出。

`--demo` 或 `YSU_DESKTOP_DEMO=1` 使用临时样例配置，忽略传入真实路径及凭据环境变量。演示不认证、不启动系统浏览器、不下载组件、不修改系统自启；退出清理临时目录。演示账户、连接和浏览器可用状态为样例，不代表主机或校园网状态。

普通浏览器打开已构建前端时显示“普通网页”，连接操作禁用，不模拟原生客户端。显式 `?demo=1` 才启用前端样例，可加 `theme=light|dark`、`accent=teal|blue|indigo|violet|rose|amber`、`scenario=offline|unknown|external|empty|busy`；`scenario=prefs-failure` 用于偏好保存失败回归。演示色仅在本页内存中生效，刷新重新按参数初始化，不写网页存储或真实设置。浏览器预览属于云端验收链路，不代替原生运行器或 WebView 验收。

原生外观偏好沿用主配置相邻的 `gui.json`，可保存 `theme`、`accent`、`close_to_tray`；`autostart_minimized` 默认 `true`、旧文件缺项按原自启进托盘行为读取，不改写原文件。启动方式由专用原生命令先处理已启用的自启项，再经 `save_prefs` 保存；`auto_reconnect` 仍走专用操作，两种设置不互相开启。偏好写入后必须返回含请求值的完整快照，自启开关必须原生回读一致，单纯排队或空确认不提示保存成功。主题色参数严格白名单校验，非法请求不落盘；默认使用中性灰白/灰黑表面与蓝色强调（`blue`）。旧配置缺 `accent`、未知未来色或字段类型异常时，仅主题色回到 `blue`，保留其他有效偏好，读取不改原文件；下一次合法偏好保存会将回退值归一化落盘。已明确保存的 `teal` 等合法主题值原样保留，不因默认色改变而覆盖用户选择；绿色强调仍可在外观设置中选择，但不再替换共用表面。命令行认证配置与账号簿不增加外观/启动字段。三平台共用相同实现，视觉规则见[设计说明](rust-desktop-design.md)。

## 验证命令

以下为 [Tauri CI](../.github/workflows/tauri.yml) 在 GitHub Actions runner 上执行的检查与产品测试入口，**不是本机执行清单**。纯文档整理只做文档静态检查，不启动预览、编译或产品测试。

```bash
# 仅在 GitHub Actions runner 执行：
npm --prefix desktop run check
npm --prefix desktop test
npm --prefix desktop run test:build
npm --prefix desktop run build
cargo fmt --manifest-path desktop/crates/ysu-auth/Cargo.toml --check
cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml
```

认证库普通测试使用本地回环 HTTP 样本、固定加密向量和协议状态，不访问校园网；另有需要系统 Chromium 的忽略测试，须显式运行 `cargo test --locked --manifest-path desktop/crates/ysu-auth/Cargo.toml -- --ignored --test-threads=1`，普通测试通过不代表这些测试已执行。可用 `YSU_AUTH_CHROMIUM_PATH` 指定绝对可执行路径。原生测试覆盖运行器、配置、锁与演示；Python 回归按[开发说明](development.md#测试)单独执行，不合并技术栈成绩。

完整浏览器脚本为 [tauri_web_smoke.py](../packaging/tauri_web_smoke.py)，新设计与键盘回归为 [rust_desktop_preview.py](../desktop/tests/rust_desktop_preview.py)，多账号与忙碌控制为 [multi_account_preview.py](../desktop/tests/multi_account_preview.py)。它们由云端工作流针对已构建前端启动临时预览后执行；主题、“关于”、反馈与光环脚本也在同一云端链路中运行，入口见[设计验证](rust-desktop-design.md#验证)与[验收导航](desktop-acceptance.md)。浏览器成绩不代替原生或真实认证。

原生离线自检使用已构建的 Rust 主程序与 WebView，验证连接、切换、账户、重连、窗口关闭驻留/重建、托盘菜单原生属性回读、关闭窗口后的快捷操作、下线及退出清理。Linux 自检仅在没有实际宿主时创建受控 D-Bus watcher，验证关闭分支和宿主丢失恢复，不模拟真实桌面面板或鼠标悬停；另一个生命周期脚本在无宿主环境检查最小化启动回退、单实例和真实 X11 关闭请求。以下仅为云端 Linux runner 的命令示例；本机如获另行授权，只使用已下载并校验的云端安装程序/二进制，不为自检编译：

```bash
uv sync --locked --group desktop-test
dbus-run-session -- xvfb-run -a uv run --no-sync python packaging/tauri_smoke.py \
  --binary desktop/src-tauri/target/release/ysu-net --output dist/rust-desktop-smoke --capture-desktop
dbus-run-session -- xvfb-run -a uv run --no-sync python packaging/tauri_linux_lifecycle.py \
  --binary desktop/src-tauri/target/release/ysu-net --output dist/rust-desktop-smoke
```

截图只用于专用测试显示。Windows 传 `.exe`，macOS 传 `.app/Contents/MacOS/ysu-net`。脚本测量程序拥有的完整进程树，检查旧旁车及 Python/Node 认证进程缺席、退出清理。RSS 求和会重复共享页；PSS 可用时另记；短样本不作为稳态、认证峰值或跨机器性能比较。最小化 API 自检不代替带真实窗口管理器的桌面点击验证。

[Tauri CI](../.github/workflows/tauri.yml)要求 Linux x64、Windows x64、macOS arm64 / x64 四个平台完成上述构建、原生与实际安装/卸载验收，上传构建和测试附件；推送 `v*` 标签时须全部平台及独立浏览器验收成功后才发布 Release。流程定义不是本轮通过声明，结果以对应标签的实际运行为准。

## 验收记录

[桌面验收导航](desktop-acceptance.md)串起正式发布、2026-10-24/25 的主题/字段对齐、“关于”、反馈浮层、连接动效和 Windows / 云端部署阶段，并标注旧备份后续清理及各阶段未覆盖范围。带日期的记录保留原貌、路径与当时结论；历史本地编译记录不是现行构建许可，源码阶段“尚未更新安装版”也不覆盖后续独立部署证据。正式版与开发工作树的区别统一见[首页发行状态](../README.md#发行与候选状态)。

更早的 [2026-10-23 候选本地验收](desktop-candidate-2026-10-23.md)、[2026-10-24 远端 CI 终结核对](desktop-ci-2026-10-24.md)和 [2026-10-21 Windows 本机只读验收](windows-readonly-fix-2026-10-21.md)均只代表各自提交、环境与样本，不以本地或旧版成绩覆盖远端失败、真实认证或当前原位升级缺口。
