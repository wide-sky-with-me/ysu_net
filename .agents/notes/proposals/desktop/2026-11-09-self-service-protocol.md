# 自助服务（/self）接入方案与协议探测结论

日期：2026-11-09。状态：只读部分已实施并实测（`ysu self`）；**下线写操作已实施但未实测**（`ysu self kick`），解绑与无感知仍未实现。范围：auth1 `https://auth1.ysu.edu.cn/self` 的设备自助服务（我的设备、无感知认证、记住的上网选择、流量明细）是否以及如何进入 ysu_net 的 CLI 与桌面端。当次实测证据归[自助服务协议探测记录](../../../../docs/self-service-probe-2026-11-09.md)。

## 背景

上一轮已确认新版自助服务不在独立域名，而是收进认证门户的 `/self` 路径，走一套独立的 OAuth2 客户端 `custom-self`。本轮要求「好好试试协议级接入」，因此先做协议可行性探测，再决定实现边界。

探测期间本机没有任何可用凭据（`~/.config/ysu-net/config.json` 的 `username` 与 `password` 均为空，无 `/etc/ysu-net/`，环境无 `YSU_USER` / `YSU_PASS`），所以全部结论来自「入口链 + 错误凭据 + SPA 源码」，**登录成功分支一次都没跑过**。

## 探测结论（决定方案的四个事实）

1. **两条登录路，成本差一个数量级**。SPA 直连 `/cas-sso/login` 需要复刻 `croypto`（24 B Base64 → 16 B AES key）+ `login-page-flowkey`（11 KB，双层 Base64 的 HS512 JWT）+ AES-128-ECB 密码加密；委托路 `/cas-sso/clientredirect?client_name=sidadapter&service=<callback>` 落到 `cer.ysu.edu.cn/authserver/login` 的**经典 CAS 表单**，而这套表单正是 `src/ysu_net/auth/api.py:cas_login()` 已经在驱动的东西，唯一变化是 `service` 参数。
2. **AES 契约已被差分证明**：正确 AES → `401 用户不存在或者密码错误!`；明文或 Base64 明文 → `401` 且**无**错误文案；伪造 flowkey → `500`。说明服务端确实用 `croypto` 解密，而不是忽略该字段。
3. **登录墙后的接口全部来自 SPA 源码，没有任何真实响应体**。`/sam/api/userself/*` 在匿名下全部 `500` + 空 body，而**不存在的路径也是 `500`**，所以这个状态码无法区分「未登录」与「不存在」，端点存活与鉴权方式都未被证明。
4. **写操作密集**。设备页涉及 `devices/kick-offline/batch`、`devices/unbind/batch`、`nosense/unbind/batch`、`ppsk/self/bindMac` 四个写接口，直接对应「踢设备下线」「关无感知」「绑 MAC」。`/self` 的「我的设备」本质是一个写控制台，不是只读面板。

## 选择

分三档，按成本与风险递增，**本轮不实现任何一档的产品代码**：

- **A（推荐先做）只读代理，且只做已验证部分**：不做 SPA 登录，只把 `/sam/api/userself/protected/aggregate/init` 这类匿名可达、只读、无用户数据的配置接口纳入诊断，用于回答「本校自助服务开了哪些功能项」。这与 `api.py:96` 现有的 `sam_enable_info` 属同一类，风险为零。
- **B 委托 CAS 登录后读**：复刻 `sidadapter` 委托路拿到 `/self` 会话，再调 `devices` 只读列表。可行，但必须先用真实账号证明登录成功分支，否则 `devices` 契约全是猜的。
- **C SPA 直连**：只在 B 被证明不可行（例如委托路拿到的会话没有 `devices` 权限）时才考虑。`croypto` + 11 KB flowkey + 请求体 PBKDF2 加密三层叠加，且 flowkey 每次 GET 都变、与外层会话绑定关系不明，跟进成本高。

**写操作一律不进客户端**，包括踢下线、解绑、关无感知、绑 MAC。理由与现有写操作纪律一致：项目现有写操作只有 login / offline / serviceLogin / switch，每一个都附独立核验与失败恢复。`devices/kick-offline/batch` 这类批量写没有幂等证据、没有失败语义证据，「关无感知」还会直接释放实名认证终端名额——把这种能力做成客户端按钮，等于在没有核验原语的前提下提供破坏性操作。

## 放弃的方案

- **直接按 SPA 契约实现登录**：需要同时维护 `croypto`、`flowkey`（每次刷新都变）、请求体 PBKDF2 加密三套易变契约，而委托路能以现有 `cas_login()` 达成同一目的。除非委托路被证伪，否则不付这份维护成本。
- **复用 `cas_encrypt_password()` 直接打 `/cas-sso/login`**：两者的加密算法不同（CER 是 AES-CBC + 随机 64 字符前缀，cas-sso 是 AES-ECB 纯密码）。混用会表现为「永远 401 且无错误文案」，是最难排查的一类故障。
- **把 `/self` 当纯外链交付**：上一轮评估的 A 方案仍然成立且更便宜，但用户本轮明确要协议级接入，因此把它降级为「若 B 受阻就退回外链」的兜底，不再作为默认建议。

## 后果与限制

- 本提案成立的前提是「委托路能拿到有 `devices` 权限的会话」。这一步**没有验证过**，一旦被证伪，B 档整体作废，只能退回 C 或外链。
- `enableSelfUnbind=false`、`enableResetPwd=false`、`enableForgotPassword=false` 已在匿名 `init` 中读到，说明本校关闭了自助解绑与自助改密；即使登录成功，这些功能也不会出现。反过来，「我的设备」是否可用仍未知。
- 请求体加密已按 SPA 契约复刻（PBKDF2-SHA256 / 15536 轮 / salt `yujhygtfredswcvf`），但用假 token 提交仍返回 500，无法判断是 token 无效还是契约有偏差。
- 验证码形态与上一轮判断相反：当前 `recaptchaVendor=system`，走 160×70 图片码，**不是**极验；极验分支只在 `recaptchaVendor=geetest` 时加载。现有 `captcha.py` 的 80×30 模型不能复用。
- 探测全程只读 + 错误凭据，未修改任何远端状态，未触发「记住的上网选择」或设备解绑。

## 实施结果（2026-11-09 晚补充）

真实账号验证推翻了本提案的两条成本估计，也证实了第三条：

- 委托路可行：`cas_login(service=…/login/oauth2/code/custom-self)` 直接登录成功，无需复刻 SPA 的 `croypto` / `flowkey` / 请求体加密。**B 档成立，C 档作废。**
- 登录后 API 不需要 `Authorization: Bearer`，也不要求请求体加密——SPA 的 `metadata.encrypt` 缺省即不加密，服务端同样接受明文 `{}`。这去掉了本提案预估的主要工作量。
- 「我的设备本质是写控制台」成立且更重要了：只读接口一次都没有触发风控，而**错误密码重试触发了「IP 被冻结 1 小时」**。写操作的风险判断不变。

已实施范围（只读）：[selfservice.py](../../../../src/ysu_net/auth/selfservice.py) 与 `ysu self` 子命令，覆盖 devices / package / flow / rememberService 四个接口；[17 项单元测试](../../../../tests/test_selfservice.py)全绿，夹具为合成数据。`api.cas_login()` 增加可选 `service` 参数，默认值保持原门户链不变，其余认证语义零改动。

写操作（kick-offline / unbind / nosense-unbind / bindMac）**仍未实现**，本轮也未调用任何一个。

## 写操作的范围调整（2026-11-09 晚）

用户明确要求「账号设备的登录和下线管理」，因此把**下线**从「不做」改为「做」，其余三项维持不做：

| 动作 | 端点 | 决定 |
| --- | --- | --- |
| 下线设备 | `devices/kick-offline/batch` | 已实现，待实测 |
| 解绑 MAC | `devices/unbind/batch` | 不实现：本校 `enableSelfUnbind=false`，且设备响应里没有 `macBindInfoUuid` |
| 关闭无感知 | `nosense/unbind/batch` | 不实现：当前账号所有设备 `noSenseUuid` 均为 null，没有可操作对象 |
| 绑 PPSK MAC | `auth-broker/.../bindMac` | 不实现：本校未开放 PPSK |

选择「只做下线」的依据：它是用户唯一明确提出的需求；其余三项在本校当前配置下要么关闭、要么没有可操作对象，实现了也没有可验证路径。

下线本身的核验语义：写入前后各读一次设备列表，目标 UUID 仍在 `onlineDevices` 中就抛 `KickVerifyError`，不报告成功。SSO 标志按门户自己的规则推导（本机保留、他机登出），不自行发明。

## 下一步（需要用户决定）

1. 提供一个可用账号，跑一次真实的 `/self` 登录，验证 B 档前提。这是唯一能解锁后续工作的动作，且必须由用户明确授权。
2. 若授权，先在 `build/` 里跑通「委托登录 → `devices` 只读列表 → 与门户网页核对」，再谈是否进产品代码。
3. 无论结果如何，写操作都不在本次范围；若要纳入，需要单独一份决策，定义批量写操作的核验语义与失败恢复。
