# 2026-10-27 网络认证链路对照与开发候选验收

状态：源码对照与产品云端回归完成；未新发行、未做校园网现场复现。本文记录当次差异和证据，不替代[运行语义](tauri-desktop.md#独立只读状态观察)；最终文档检查另行记录。

## 样本与来源

- 本仓对照基线为 main `d2de907`，正式 `v0.2.2` 的产品源码仍为 `925569a`；开发候选版本字符串也为 0.2.2，但正式安装包不含本轮改进。当前产品候选为 `1a81aac9c20cb660a6b31993ba7245bea03cc1d0`，位于独立构建分支，未推送 main。
- 参考 Python 项目固定为 [YSUNetLoginv2 `ee265154`](https://github.com/KamijoToma/YSUNetLoginv2/tree/ee265154a000efbe9319fbf3406139d9cc54810f)；其独立 Go 子模块固定为 [YSUNetLoginV2-Go `102b6b49`](https://github.com/KamijoToma/YSUNetLoginV2-Go/tree/102b6b49f8e2167bf4ed211d3067955296d3e086)。不能把同名工具、旧 helper 和两个实际入口混为一个实现。
- 外部源码仅定向下载、校验 Git blob 并只读审查，未安装、执行或复制进产品。Python 元数据声明 MIT，但 README 称仅供学习研究，未见独立许可文本；Go README 又沿用 Python 许可。许可信息不一致，不据此推定移植授权。
- Win11 / API 后端已由用户确认；“最新版”不是精确构建证据，实际被拒跳转的来源、目标和表示形式仍未取得。本记录不包含账号、Cookie、真实会话地址或认证材料。

## Shell 版实际执行器

[安装器](../src/ysu_net/manager/install.py)生成的 Shell wrapper 执行项目 Python 的 `-P -m ysu_net`，再进入 [CLI](../src/ysu_net/manager/cli.py)；`ysu on` 启动的 systemd 服务进入[守护器](../src/ysu_net/manager/daemon.py)。手工命令和守护器都通过 [run_backend](../src/ysu_net/manager/backend.py)启动独立 API / Browser 子进程。仓库 Shell 安装脚本不是另一套认证算法。

桌面 [Runtime](../desktop/src-tauri/src/runtime.rs)直接调用 Rust [AuthClient](../desktop/crates/ysu-auth/src/lib.rs)，不是上述 Python 的旁车。本仓两端默认均为 API、相同 HTTPS Portal / CAS 和 TLS 校验，并非默认密码算法不同。因此 CLI 成绩、浏览器预览和桌面原生验收不能互相代替。

## 逐段对照

| 阶段 | 本仓 Shell / Python CLI | Rust 桌面当前候选 | 固定外部参照与判断 |
| --- | --- | --- | --- |
| 门户入口 | API 按 index.jsp → redirect.jsp → root；Requests 自动跟随 HTTP / HTTPS 及跨源跳转 | API 入口顺序相同，但逐跳验证 scheme / origin / method；HTML 按真实终端响应 URL 解析 | Py / Go 默认请求 redirect.jsp?mode=history；不能由默认入口推断实际最终响应仍带该参数 |
| SID 与会话 | 每次后端进程新 Session，同命令共享 Cookie；从重定向历史及最终 URL 提取 SID | 每次公有操作新 Transport / Jar，同操作共享；有界 HTTP / HTML 导航后取 SID | 两参照按最终 URL 含 portal-main 等方式判入口；不能用子串当信任证据，也不应导入用户个人浏览器 Cookie |
| 在线 / 离线 | 仅 result=success 确认在线，明确 dx.failed.user.offline 才离线；其他情况为查询失败 | 同样区分未知与离线，且在线服务识别更严格 | 参照主要按 redirectUrl 是否存在判断；Py 查询异常还会变为未在线。这种判法不能回抄为自动登录条件 |
| CAS | Portal seed → clientredirect → cer/authserver 表单 → AES-CBC | 同一代协议，并额外限制 CAS origin、form action、回跳及带 body 重定向 | **参照实际 Py / Go 已走 Portal 同源 direct CAS-SSO**：croypto / flowkey 与 AES-ECB，不是旧 ysu_login helper。本轮未新增该凭据投递分支 |
| 服务与上线 | 按流程节点 serviceLogin → userOnline → 查询实际服务 | 上述变更前再核实实际 owner，结束后以新会话独立查询实际账号 / 服务 | 两参照均在 userOnline 后才检查 authResult，不能当作“失败后绝不激活”的范例；userOnline 也不是只读查询 |
| 主动下线 | 有 terminalLoad / sam 预热、offline 和轮询；部分失败可 CAS / UI 兜底 | 受限准备、owner 核验、offline 与独立离线轮询，无隐式重新认证兜底 | 参照下线后的 userOnline POST 不构成可靠离线证明。第三方网页下线不会执行本工具的主动 logout 准备链 |
| 外部下线恢复 | daemon 仅明确 offline 才 login；查询失败退避。外部在线会清除认证暂停 | auto 也先独立查询，未知不登录；同配置的认证暂停保持，直到显式恢复 | 暂停政策不同是有意保守策略，不能解释已经执行的 portal_navigation / redirect_blocked |
| Info / 缓存 | 普通 Info 为状态与账户读取，没有新增来源双向配对；CLI 自身不保有长期 GUI 缓存 | 同会话读取前后核验 + typed 来源，Native 再独立 Status 配对；外部身份变化作废旧详情 | 参照无同等来源绑定；不以展示字段、配置用户名或已有任意在线状态代替实际来源 |
| 网络与预算 | 近浏览器 UA、可继承代理；单请求预算外另有父进程总时限 | Native UA、禁环境代理；操作绝对 deadline，观察单次另有短预算 | UA / 代理 / 慢网可能改变响应，但未在用户机器测量；不能据此关闭 TLS、延长为无限等待或猜换 UA |

本仓关键证据：[Python 导航](../src/ysu_net/auth/api.py#L683-L726)、[状态 / 动作语义](../src/ysu_net/auth/common.py)、[守护重连](../src/ysu_net/manager/daemon.py#L16-L43)、[Rust 协议](../desktop/crates/ysu-auth/src/protocol.rs)、[传输边界](../desktop/crates/ysu-auth/src/transport.rs)。外部关键证据：[Py 门户入口](https://github.com/KamijoToma/YSUNetLoginv2/blob/ee265154a000efbe9319fbf3406139d9cc54810f/src/ysu_net_login/ruijie_client.py#L96-L123)、[实际 direct SSO](https://github.com/KamijoToma/YSUNetLoginv2/blob/ee265154a000efbe9319fbf3406139d9cc54810f/src/ysu_net_login/ruijie_client.py#L152-L236)、[Py 服务顺序](https://github.com/KamijoToma/YSUNetLoginv2/blob/ee265154a000efbe9319fbf3406139d9cc54810f/src/ysu_net_login/ruijie_client.py#L483-L540)、[Go 实际链](https://github.com/KamijoToma/YSUNetLoginV2-Go/blob/102b6b49f8e2167bf4ed211d3067955296d3e086/internal/client/ruijie.go#L192-L271)。

## 当前日志能定位到哪里

`action=auto phase=online_state code=2 operation=status stage=portal_navigation reason=redirect_blocked` 表明自动任务已触发，但在门户会话导航的 URL 策略检查处失败，尚未得到明确离线证据；手工 login 也先经过该导航。它不能证明密码错误、验证码失败、CAS 加密代际错误、运营商选择失败或认证暂停。

Python 没有同等重定向白名单，因此对同一合成 HTTP captive / 跨源 / query-bearing source 输入可能继续，而 Rust 拒绝。这解释了**为何源码可能不同**，不是这台机器的实际响应证明。两端入口循环都没有 per-entry 异常 fallback；Python 只是未检查入口 404 / 500 响应时可能继续，而 Rust 提前 HttpRejected，这也不是本次 RedirectBlocked 的直接成因。

## 本轮已修与保留的边界

- 已补 [API HTML resolver](../desktop/crates/ysu-auth/src/protocol.rs)：原精确可信 GET 引导的 HTTP Location 已有 HTTPS 规范化，HTML / meta / JS 曾漏接；现复用同一规则，不发明文 HTTP，不增加 origin / 路由 / 参数例外。正负例复用[既有合成导航](../tests/fixtures/portal-navigation.json)和[组合回归](../desktop/crates/ysu-auth/src/regression_tests.rs)。
- 已补[原生只读观察](../desktop/src-tauri/src/runtime_observer.rs)与[前端提示合并](../desktop/src/lib/observation.ts)，不借刷新自动登录、下线、换号、启动浏览器或保存配置。被动失败仍为未知，auto 有自己的新查询和变更授权。
- 已补 [InfoObservation](../desktop/crates/ysu-auth/src/info_observation.rs)及 Native 提交配对：仅清旧缓存不足以防止 Info(A) 在最终 Status(B) 后晚写回；现在来源不匹配不提交，原 Info JSON 与外部账号无凭据读取保留。原因和取舍归[决策](../.agents/notes/implemented/desktop/2026-10-27-passive-state-observation.md)。
- **未盲加** mode=history 的 legacy HTTP 例外、direct SSO 新凭据用途、任意 entry failover 或 Browser 引导例外。参照默认参数不证明“该终端 URL + 该 HTTP 下一跳”的真实组合；direct SSO 差异发生在后续 CAS 阶段。Rust Browser 原有引导规范化接线缺口已静态识别，但本次 API 修正未包含它，不能建议换 Browser 作为已验证解法。
- `authResult / authMessage` 是另一个待评估的动作信封防御项：本仓两端目前均不提前识别它；参考本身也先发 userOnline 再判断。最终独立状态核验仍不可删，也不能把这个后续阶段研究项冒充当前导航现场根因。

## 验证分轮与限制

1. 首轮 `68f553a4` 的四平台 Native、Mock 与 Community 成功，但没有覆盖随后发现的 Info 晚写竞态，不能沿用作来源绑定交付证明。
2. 来源绑定候选 `6ebb08e4` 的 Mock / Community 成功；四平台 Auth 库均在同一旧配额正例失败：旧断言精确一次状态查询，实际新增读取后核验为两次。其他断言未删除。
3. 当前 `1a81aac9` 保留外部账号、无凭据、原 JSON、配额与严格轮换检查，将次数收紧为精确两次，并补离线只查一次且不读账户；[四目标 Native 回归与构建](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40447676375)及[Mock](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40447676170)均成功。最终文档单独检查；不将等待监控器的工作流数量假设错误当作产品失败。

新覆盖包括原生观察与来源晚写反例、库级纯组合 / 受控同会话整链、TS 合并清理及浏览器 IPC 夹具。所有编译、格式化、单元和产品验收仅在 GitHub Actions；本机只做静态检查与云端产物校验，未安装运行客户端、修改账号 / 自启或连接校园认证。Shell / 外部参照本次仅静态审读，未做同机同时间 CLI 与桌面的真实 A/B 认证。

缺字段仍按实际值比较，不回填配置身份；门户未报告的变化、A→B→A 和远端原子快照无法由这些查询完全保证。在途设置修改可让一次旧缓存配置短读完成；观察预算是异步时限，不是硬实时 CPU 隔离。在途读暂占门闩时安装会被拒，读完再试。

如需继续定位另一台机器，应由用户自行提供精确软件版本，以及去掉 query / fragment / path 内票据后的公共来源、目标、方法和响应类型；SID 只需是否存在 / 唯一，不提供值。不要完整 URL、HAR、Cookie、密码或配置。正式 0.2.2 仍是已发布包，本次开发改动未新发布、未现场确认。
