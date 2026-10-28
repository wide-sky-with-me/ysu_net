# 2026-10-27 123 受控认证链采样

状态：真实离线 / CAS / 服务拒绝已采样；开发源码修正已写入，云端待验，未发行或部署。**123 当前仍离线**，测试账号未能恢复校园网连接，已请用户恢复原连接或指定有效的既有配置来源。SSH 仍可连接。

## 目标与边界

用户指定 123，随后要求从 Windows SSH 配置取得连接信息并配置 WSL 免密；实际目标确认后，追加现有 WSL 公钥并验证 BatchMode 登录，保留其他密钥和配置，没有转移私钥。

用户另行明确允许短暂下线 123，沿用 111 保存的配置测试并恢复连接。111 仅作为配置读取来源，没有下线、重连或修改配置；凭据只经加密 SSH 管道进入进程内存，不写 argv、磁盘或日志。123 没有安装正式客户端、改网络配置或编译产品；使用此前已校验的云端 Python 运行时 / wheel 与受限采样 worker。

安全收据与独立采样脚本存于本地忽略目录 `build/portal-live-review-20261027/`，不是公开仓库或 CI artifact。只保留角色、固定枚举、bool、状态码、计数和采样器摘要，不保存原页面、URL 查询值、SID、票据、Cookie、账户或密码。计数是应用请求尝试，不是完整抓包。

## 实测证据

| 阶段 | 实际观察 | 结论 |
| --- | --- | --- |
| 初始 DNS | 系统上游 8.8.8.8，门户与 CAS 均解析暂时失败 | 旧采样阻塞仍存在；仅进程内使用实时校内 DNS，不改系统解析器 |
| 初始只读链 | UTC 15:13:22，7 次 GET；门户确认 online，CAS 返回所需表单和加密盐 | 在线普通链符合已有规则；不能据此代表离线登录 |
| 受控下线 | 初查在线；准备与 offline 返回成功，随后同会话读到明确 offline | 下线发生；原在线身份与测试配置不同，不声称可恢复原身份 |
| 新会话离线查询 | HTTPS redirect 302 指向固定 HTTP captive 根 | 原只允许 HTTPS 的 Rust 策略在此确定拒绝 |
| history 对照 | 精确 history 入口仍转 captive，并带 history query | 改入口参数不能解决；此变体不纳入本次例外 |
| captive 对照 | 同 IP 的 HTTPS curl 证书校验失败；一次匿名 HTTP 根 GET 200，静态导航指向 HTTPS index | 保留 TLS 校验，采用专用匿名引导解析 |
| 完整离线引导 | UTC 15:21:39，6 次 GET；index → redirect → captive → HTTPS index → HTTPS main → state | 门户独立确认 offline，未使用密码 |
| CAS 表单补证 | 5 个 form；其他方式与密码方式复用 captchaDiv，密码容器明确隐藏 | Python 属性顺序及全页判断均会误判；Rust API 全页 any 也受影响 |
| 限定密码表单后的认证 | 验证码接口明确不需要；唯一一次 CAS 密码 POST 返回 302，流程变成 serviceSelection | 本轮 CAS / CBC 链真实成功，无证据改成其他 SSO 加密分支 |
| 服务选择 | HTTP 200、外层 code=200，data.authResult=fail，authMessage 属认证失败 | 必须在此停止；旧 worker 实际继续发了 userOnline |
| 旧上线与最终核验 | userOnline 返回 online=false / 认证失败，独立新会话仍 offline | 未恢复网络；不重试密码或私自更换运营商、账号 |

独立进程在原 SSH 返回后完成只读 dry-run，验证收尾进程可存活。准备期间参数名与就绪文件权限校验失败发生在认证变更之前，修正后才下线。旧 Python worker 对验证码的两次停止均发生在密码 POST 之前，保留原收据；修正范围后合计仅一次实际密码 POST。所有阶段都没有触发第二次下线。

## 源码修正与覆盖

[运行语义](tauri-desktop.md#离线-captive-与-cas-表单)维护当前精确行为；[决策](../.agents/notes/implemented/desktop/2026-10-27-offline-captive-bootstrap.md)解释新增匿名 HTTP 的范围、代价及局部替代关系。

三平台共用 Rust Transport，API 与 Browser 的主导航接入同一解析器，通用请求仍拒绝 HTTP。Rust API 限定验证码所属 form；Browser 保留实际布局可见性检查。Python CLI 修正属性解析与表单范围，两端同步检查服务的 authResult / authMessage，拒绝后不再上线。

新增 `cas-login-methods.json`、`portal-action-results.json` 均为重建的合成夹具，没有复制真实页面。对应 Rust / Python 合同覆盖隐藏属性顺序、重复 ID、独立可见挑战、业务拒绝、未知 authResult 及拒绝后零 userOnline；匿名客户端另覆盖无 Cookie / 认证头、禁止自动跳转与精确策略边界。

## 验证与未完成项

本地只做 Python AST、JSON、diff、链接及来源静态核对；未运行 Cargo、前端构建或产品测试。新源码尚未提交 / 推送，需用户授权独立构建分支后才能执行 GitHub Actions 格式、Rust / Python 回归与四目标构建。

本次不是 Rust 二进制或系统 Chromium 的校园网端到端运行，也没有 Win11 客户端安装 / 现场复验；Browser 新接线的真实 CDP 整链仍待验。服务账号被拒原因仅取得固定认证失败分类，没有足够证据归因为密码、额度或并发上限。123 尚未恢复在线，111 当前连接未被改动；系统 DNS 问题也没有在本次修复。

## 2026-10-28 正式 Python CLI 对照补证

用户确认本项目 Python CLI 曾在 123 从离线登录成功，并授权在 123 安装 CLI、采集正常入口轨迹。此前“测试配置被拒”仅描述当次请求结果，不能据此认定账号配置无效，也不能声称已经完成 Rust 与正常 Python 的同条件对照。

### 安装与来源

- 安装正式 v0.2.2 云端 wheel，SHA256 为 `b19e8665fdd213991ed951cf55275898ba3738d7d97b7a3b783d355a99122a1c`；25 个 Python 源文件与 v0.2.2 标签逐字节一致，运行后再次核验未改变。
- 用户目录 `~/.local/share/ysu-net/app/` 保留从云端 wheel 解包的源码、隔离依赖和云端 CPython 3.12.16；系统 Python / 包未改。运行时归档的 share 文档 / terminfo 子树含越界链接，安全过滤拒绝；只解包并核验其余运行时部分，没有放行越界链接或在服务器编译。
- 调用项目原安装器 `--no-service` 创建 ysu / ysuon / ysuoff；项目外执行 `ysu --help` 成功，没有注册、启动服务或开启自启。默认配置为 0600，账号密码留空，测试凭据继续只经内存与环境传入。

### 正常入口实测

本地收据为 `normal-cli-control-evidence.json`、`normal-cli-control-summary.json` 与 `formal-cli-install-receipt.json`，仍位于本文所述忽略目录。UTC 2026-10-27 16:05:52 至 16:05:56，即北京时间 2026-10-28 00:05，调用已安装的正常 `ysu status --raw → ysu login → ysu status --raw`，合计 29 次请求尝试、1 次 CAS 密码 POST、0 次下线。

请求头、Cookie、重定向、表单及验证码判断沿用正式 CLI 原逻辑。独立 sitecustomize 仅提供实时校内 DNS 的进程内解析提示和被动响应记录，并限制每个认证子进程最多一次密码 POST；没有修改应用源码或系统 DNS，没有环境代理。此过程仍有插桩及解析覆盖，不能称为完全无插桩网络 A/B。

| 验证点 | 正式 CLI 结果 |
| --- | --- |
| 独立初始状态 | code=1，明确 offline，才执行登录 |
| 输入与 CAS | 用户名无首尾空白，实际提交与配置一致；密码为密文，TLS 校验开启；CAS 返回 302 |
| 流程节点 | authenticate → serviceSelection |
| serviceLogin | HTTP 200 / 外层 code=200，data.authResult=fail，错误仅可分类为认证失败 |
| 原上线逻辑 | 正式旧版仍继续 userOnline，返回 online=false / 认证失败 |
| 命令与独立收尾 | login=3，final status=1，仍 offline；没有重复尝试或再次下线 |

这次正式 Python 与先前 worker 在相同 111 磁盘配置、同一 123 上重现同一服务拒绝，因此该失败不是已证实的 Rust 专属差异，也不能只归因于旧采样器的请求改动。门户消息未命中密码、用户不存在、绑定、禁用、过期、欠费或并发上限等明确类别，具体服务拒绝原因仍未知。

历史成功使用的配置与本次输入尚未确认相同。先前 123 在线响应的身份字符串与 111 保存用户名不等，但这本身不充分证明不同自然人，仍应考虑身份表示差异。此次保存用户名为数字、无首尾空白；不据此猜补身份映射或判定账号无效。用户的历史成功事实保留，下一步应对齐当时账号 / 服务 / 版本，再检查差异。

本次额外实际密码 POST 为 1，连同前轮合计 2；均通过 CAS，随后服务拒绝。当前连接仍未恢复，系统 DNS 仍不可用；正式 CLI 日常联网也受该 DNS 问题影响，本次解析覆盖没有被写进已安装产品。前轮源码修正尚未部署到该正式 CLI，Rust 产品云端验证及真实对照仍待完成。

## 2026-10-28 Clash 与透明代理核对

用户补充 123 曾安装 Clash，并提供管理员认证以读取受限防火墙规则。北京时间 09:41 至 09:49 分批只读检查，没有启停代理、修改 DNS / 路由 / 防火墙或重试校园网登录。管理员认证仅用于 sudo；认证材料未写入脚本、命令参数或报告。

| 检查 | 实际观察 |
| --- | --- |
| 安装痕迹 | 用户目录仍有 clash-for-linux-install，.bashrc 引用 clashctl；脚本包含导出 / 取消代理环境的定义 |
| 磁盘 YAML 样本 | 混合端口 7890、tun.enable=false、DNS fake-ip；这里只代表磁盘字段，未证明该文件曾作为运行配置加载 |
| 运行态 | 未发现 Clash / Mihomo 等进程、对应用户 / 系统 unit、代理命名容器或常见代理端口；桌面代理 mode=none |
| 测试环境 | SSH 进程及用户管理器无代理环境变量，Requests 对门户 / CAS 未选用环境代理；不代表所有历史交互终端都无代理 |
| 设备与路由 | 无 TUN / TAP、代理策略规则或 fake-IP 路由；门户、CAS 与 SSH 管理路由均走 enp4s0 / main |
| 管理员防火墙读取 | root helper 实际读取 nft -j list ruleset、iptables-save、ip6tables-save、iptables-legacy-save、ip6tables-legacy-save；均未发现代理命名、TPROXY、REDIRECT 或 fake-IP 标记，legacy 规则为空 |
| DNS | 53 端口为 systemd-resolved stub；配置上游为 8.8.8.8，系统 dig 查询门户 / CAS 均超时，校内 DNS 实时返回非 fake-IP 地址 |
| 当前连接复核 | UTC 01:49:13，6 次只读 GET，门户明确 offline；0 次密码 POST，0 次下线 |

安全收据为忽略目录中的 `proxy-runtime-receipt.json`、`proxy-residue-receipt.json`、`proxy-followup-receipt.json`、`proxy-privileged-receipt.json` 和 `proxy-review-status-receipt.json`。最初普通用户无权读取防火墙，提供管理员认证后的收据补齐这一缺口；未导出原始规则、订阅、节点或控制密钥。

结论仅覆盖这次分批观察：存在安装残留，未发现当前生效的 Clash / 透明代理，不能据此追溯此前运行状态。DNS 故障已复核，但前轮正式 CLI 采样已有进程内解析覆盖，因此它不能单独解释随后 serviceLogin 的业务拒绝。该拒绝的具体原因、历史成功条件对齐及 Rust 云端验证仍未完成；没有把排除代理当作已恢复连接或已修复认证的证明。

## 2026-10-28 Shell 登录与退出再测

用户明确要求在 123 试用 Shell 登录、退出。UTC 02:18:46 至 02:19:33（北京时间 10:18:46 至 10:19:33）实际调用已安装的正式 v0.2.2 `ysu`，继续使用此前授权的 111 配置作为输入；未改账号、运营商或服务器持久配置。25 个 Python 源文件运行前后均与已核验的正式 wheel / 标签一致，不包含本轮尚未云端构建的 DNS 回退或协议修正。

| 环境与命令 | 退出码 | 实际结果 |
| --- | --- | --- |
| 原系统 DNS：`ysu login` | 2 | 域名解析失败，未进入认证 |
| 原系统 DNS：`ysu logout` | 2 | 域名解析失败，未进入下线 |
| 仅测试进程指定解析：`ysu status --raw` | 1 | 独立确认 offline |
| 同上：`ysu login` | 3 | CAS 密码 POST 返回 302，节点从 authenticate 到 serviceSelection；serviceLogin 返回 HTTP 200 / code=200，但 data.authResult=fail，消息只命中认证失败类别 |
| 同上：`ysu status --raw` | 1 | 登录后仍明确 offline |
| 同上：`ysu logout` | 0 | 已离线分支返回成功；未发送 offline API 请求 |
| 同上：`ysu status --raw` | 1 | 退出后独立确认仍 offline |

两条原环境命令都明确被 DNS 阻断，才进行指定解析的对照；没有因业务失败更换输入或重复登录。对照使用校内 DNS 的本轮实时答案，仅改变进程解析，保留原 HTTPS URL 与证书校验，原请求头、Cookie、跳转、表单和业务逻辑不改；被动观察器每个认证子进程最多允许一次密码 POST。该对照不是完全无插桩产品测试，也不是新 DNS 回退实现的验收。

观察链记录 41 次请求尝试、1 次 CAS 密码 POST、0 次 offline API 请求；旧正式逻辑在 serviceLogin 拒绝后仍调用 userOnline，得到 online=false / 认证失败，与前轮结果一致。本轮后累计密码 POST 为 3 次，均通过 CAS 后遇到服务拒绝；具体原因仍未确认，不能据此判定密码错误或 Rust 独有故障。

此次实际执行了登录、退出命令，但没有登录成功，因此**尚未验证在线状态下的真实退出闭环**。退出码 0 只证明已离线时可成功返回，不能作为在线下线成功的证据。123 最终仍离线，SSH 可达；未修改系统 DNS、已安装源码或持久配置，未注册后台服务，凭据未落盘。确认控制进程退出后已删除本轮远端临时目录，保留已安装 CLI；本地忽略目录 `build/shell-cycle-20261028/` 保存脚本、脱敏收据及摘要。

## 2026-10-28 换机对照补证

随后按用户要求在 21 测试：现有客户端和同一个正式 v0.2.2 云端 wheel 均真实完成离线登录、在线退出，独立状态与身份 / 服务配对通过，已恢复原在线连接及后台。[21 的完整记录](portal-21-review-2026-10-28.md)保留来源、命令与收尾证据。

21 使用本机中国移动配置且 DNS 正常，与本记录中的 111 校园网配置 / 123 DNS 故障条件不同；该成功排除了正式 v0.2.2 Shell 在所有机器均无法登录的推断，不能单独定位 123 拒绝的根因，也不改变上述 123 仍离线及 Rust 尚未实测的结论。本次换机没有在 123 再次提交密码。
