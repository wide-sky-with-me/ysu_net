# auth1 /self 自助服务协议探测

日期：2026-11-09，标签 v0.2.7 于 2026-11-10 发布。状态：**登录成功分支、四个只读接口与设备下线均已用真实账号跑通**，CLI（`ysu self`）与桌面（侧栏“设备”页）同步实现；解绑 MAC、关闭无感知与 PPSK 绑定未实现。方案与取舍归[提案](../.agents/notes/proposals/desktop/2026-11-09-self-service-protocol.md)，发行结果归[0.2.7 发布记录](desktop-release-0.2.7.md)。

本轮不修改任何产品代码的认证语义，所有脚本与原始结果在本地忽略目录 `build/self-protocol-probe/`。真实账号凭据只经环境变量传入，不落盘、不进日志、不进本文。

## 入口链

```
GET /self
 -> 302 /oauth2/authorization/custom-self
 -> 302 /cas-sso/oauth2.0/authorize?response_type=code
        &client_id=CerVBeNwjL3nexy3yD5ZmyZ5b1l023O-ZlSMVZA3lfkyjNN3QQGQapCjIUOIFE8MM
        &scope=read+write&redirect_uri=…/login/oauth2/code/custom-self
 -> 302 /cas-sso/login?service=…/cas-sso/oauth2.0/callbackAuthorize?…
```

`client_id` 明文写在跳转里，`scope=read write`，无 PKCE。未登录时 `/self/*`（含 `/self/api/*`）一律 302 回 `oauth2/authorization/custom-self`；`/self/assets/` 是 403；但 **`/self/assets/*.js` 匿名可直取**（`index-BuQufmcH.js` 766 KB、`myDevices-FqRS9b8o.js` 45 KB 均 200）——登录墙只设在路由上，不设在静态资源上。

## 登录提交契约

`/cas-sso/login` 是 SPA 外壳，服务端只返回 `<p id=…>` 节点，**没有** `execution` / `pwdEncryptSalt` / `lt`。字段全部从 982 KB 的 `main.js` 逆出：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `type` | `<p id="current-login-type">` | 实测 `UsernamePassword` |
| `_eventId` | 常量 | `submit` |
| `execution` | `<p id="login-page-flowkey">` | 11 KB，`<uuid>_<Base64(Base64(JWT))>`，解两层后头为 `{"alg":"HS512"}` |
| `croypto` | `<p id="login-croypto">` | 24 B Base64 → 16 B，作 AES key |
| `password` | 计算 | `Base64(AES-128-ECB-PKCS7(明文, key=Base64Decode(croypto)))` |
| `captcha_code` | 可选 | 当前 `recaptchaVendor=system`，未见出码 |

差分验证（证明服务端确实用 `croypto` 解密，而非忽略该字段）：

| 提交 | 结果 |
| --- | --- |
| 正确 AES | `401 用户不存在或者密码错误!` |
| 明文密码 | `401`，**无**错误文案 |
| Base64 明文 | `401`，**无**错误文案 |
| 伪造 flowkey | `500` |

同 session 内两次 GET `/self` 拿到的 flowkey 不同；跨页复用旧 flowkey 仍返回 401（未到 500）。即服务端校验格式与 SPA 会话绑定，但不要求「必须是最新一次」。

## 委托路：现有 `cas_login()` 可直接复用

```
GET /cas-sso/clientredirect?client_name=sidadapter&service=…/login/oauth2/code/custom-self
 -> 302 https://cer.ysu.edu.cn/authserver/login?service=…/cas-sso/login?client_name=sidadapter
        &accept-language=zh-CN&delegatedclientid=TST-665818-…
```

落点是**经典 CAS 表单**（25 KB，`pwdFromId` / `execution` / `pwdEncryptSalt` / `lt` / `cllt` / `dllt`），正是 `src/ysu_net/auth/api.py:cas_login()` 已经在驱动的契约。把 `service` 从 `/portal/entry/pc/authenticate…` 换成 `…/login/oauth2/code/custom-self`，`delegatedclientid` 仍正常下发。差分：伪造 `execution` → 404；密码字段置空或改明文 → 200 但无 `Location`（表单被接受、认证未通过）。

因此协议级接入的登录成本不是「复刻 SPA」，而只是「多传一个 `service`」。

## 登录墙后的接口（源码推断，未验证）

`/self/assets/index-DYI5xHTd.js` 的设备 API 模块：

```
POST /sam/api/userself/devices                       # 设备列表
POST /sam/api/userself/devices/kick-offline/batch    # 批量踢下线（写）
POST /sam/api/userself/devices/unbind/batch          # 批量解绑（写）
POST /sam/api/userself/nosense/unbind/batch          # 关无感知（写）
POST /auth-broker/api/authsource/ppsk/self/bindMac   # 绑 PPSK MAC（写）
```

请求封装（`index-BuQufmcH.js` 拦截器）：`clientType: self`、`Authorization: Bearer <localStorage["v3-admin-vite-token-key"]>`；命中 `/api/*` 的 POST 且 `metadata.encrypt !== false` 时，body 变成

```
base64( 16B随机前缀 ‖ 16B IV ‖ AES-256-CBC( hex(JSON), PBKDF2(token, "yujhygtfredswcvf", 15536, SHA256) ) )
```

并加 `encrypted: true`。按此契约复刻后提交，仍是 `500` + 空 body。

**这个 500 无法判读**：不存在的路径（`/sam/api/userself/definitely-not-exist`）同样返回 `500` + 空 body。所以「端点存活」与「需要登录」两件事都没有被证明。

## 匿名可达（均 200，无用户数据）

| 端点 | 内容 |
| --- | --- |
| `/sam/api/userself/protected/aggregate/init` | 7242 B：`exploreTitle=自助服务`、`appType=self`、19 个功能项；`enableSelfUnbind/ResetPwd/ForgotPassword` 全为 `false`；用户字段全 `null` |
| `/sam/api/protected/guest/enableConfig/info` | 项目已在用（`api.py:96`） |
| `/sam/api/protected/samconfig/getOtherConfig` | 1268 B，含 `enableAntiProxyGlobal: true` |
| `/cas-sso/api/publicNoToken/captcha/generate/DEFAULT` | 160×70 PNG，6084 B（短信/找回密码用） |
| `/cas-sso/api/rememberedPwd/checkCredential`、`clear` | 200，返回固定结构，无用户数据 |

19 个功能项：充值、修改密码、我的套餐、运营商管理、历史明细、流量加油包、转账、账号中心、访客管理、申请专网、我的审批、我的申请、PPSK 管理、网络报修、FAQ 集锦、网络信息、个人哑终端管理、网络服务报修、取消记住的上网选择。

## 验证码：与上一轮判断相反

`main.js` 有 `case"geetest": … /sso-public/login-recapcha/gt4.js` 分支，但当前页面 `<p id="recaptchaVendor">` 是 `system`，页面不含 `gt4`，所以走**系统内置图片码**而非极验。尺寸 160×70，与现有 `captcha.py` 的 80×30 模型不能共用。连续多次错误凭据后 `captcha-url` 仍为空，**本轮没有触发到出码阈值**。

## 未覆盖

- 登录成功分支、`code` 交换、`Bearer` token 的签发与权限边界。
- `devices` 列表的真实结构、分页、字段含义。
- 四个写接口的幂等性、失败语义与风控。
- 委托路拿到的会话是否具备 `devices` 权限（本方案的唯一前提）。
- 真实账号下的验证码触发阈值与出码后表单变化。

## 复现

`build/self-protocol-probe/self_client.py`（入口链、提交契约、委托路、失败分类）与 `RESULTS.md`（逐条命令与输出）。两个文件都在 `.gitignore` 覆盖的 `build/` 下，不含凭据。

## 真实账号验证结果（推翻前文的三个判断）

用真实账号经浏览器完成一次 CAS 登录后，页面进入 `/self/index?ticket=ST-…`，首页显示「在线设备 2 台 / 我的设备 2 台」。随后用**纯 `requests`（无浏览器、无 Bearer、无请求体加密）**复现同一条链并取到全部只读响应：

| 前文判断 | 实际情况 |
| --- | --- |
| 需要 `Authorization: Bearer <v3-admin-vite-token-key>` | **不需要**。`localStorage` 里根本没有这个键，纯 cookie 即可 |
| 请求体要走 PBKDF2 + AES-256-CBC | **不需要**。`metadata.encrypt` 缺省时 SPA 不加密，服务端同样接受明文 `{}` |
| 未登录时 `500` 说明端点未知 | `500` 只是未登录的表现；登录后全部 `200`，不存在的路径仍是 `404` |

登录成功后 cookie 集合（`CASTGC` 在 `/authserver`，`SESSION` 在 `/`，`SOURCEID_TGC` 在 `/cas-sso/`）：

```
CASTGC@/authserver  JSESSIONID@/authserver  SESSION@/  SESSION@/cas-sso/
SOURCEID_TGC@/cas-sso/  happyVoyage@/  platformMultilingual@/
rg_objectid@/cas-sso  route@/authserver
```

关键实现细节：CAS 表单提交**必须带 `execution`**（值取自登录页 `<input id="execution">`，形如 `e2s1`）。漏掉它时服务端返回 200 + 登录页正文而非 302，表现为「登录失败但没有任何错误文案」。

## 只读接口实测（全部 200，需登录）

| 接口 | 内容 |
| --- | --- |
| `POST /sam/api/userself/devices` | `onlineDevices[]` / `offlineDevices[]`：`deviceName`、`deviceType`、`terminalType`(1 电脑/2 手机/3 平板/0 其他)、`userMac`、`userIpv4`、`onlineDuration`、`authType`、`currentDevice`、`unifiedAuthentication`、`noSense*` |
| `POST /sam/api/userself/package/overview` | 套餐名、计费周期、`usedFreeDesc`、`flowUsingPercentages`、余额 |
| `POST /sam/api/userself/package/flow` | `leftFreeValueDesc` / `totalFreeValueDesc` / `usingPercentages` |
| `POST /sam/api/userself/rememberService/current` | `{remembered, service, expirationDate}` |
| `POST /sam/api/userself/devices/defaultServicesList` | 可选默认服务（套餐默认 / 移动 / 电信 / 联通） |
| `POST /sam/api/userself/reset/operators/options` | 运营商绑定信息，含 `configSwitch.operatorsEnabled` |
| `POST /sam/api/protected/terminalType/listType` | 终端类型字典 |

`/self/myDevices` 是一个前端路由，直接 GET 会 404；设备页由 SPA 内部路由渲染，数据来自上表的 `devices` 接口。

## 已落地实现

只读模块 [selfservice.py](../src/ysu_net/auth/selfservice.py)，CLI 子命令 `ysu self`（后端 `api.py self`）：

```bash
ysu self          # 人文可读
ysu self --raw    # JSON
```

复用 `api.cas_login()`，唯一改动是给它加了 `service` 参数（默认值保持原门户链不变），自助服务传入 `/login/oauth2/code/custom-self`。这样 CAPTCHA、密码加密和错误处理都留在同一处。

实测输出（真实账号，2026-11-09）：

```
自助服务（门户原文）
在线设备：2 台 / 共 2 条
  - 我的设备（在线，本机）  类型=电脑 MAC=… IP=10.0.0.1 在线时长=0时52分57秒 接入方式=无线标准Portal接入
  - 我的设备（在线）  类型=手机 MAC=… IP=10.0.0.2 在线时长=0时39分36秒 接入方式=无线标准Portal接入
套餐：硕士研究生60G（0.00—60.00GB内免费）
计费周期：2026-11-01 至 2026-11-30
已用：国内下行流量:10 GB 47.10 MB /60 GB 0.00 MB
余额：0.00
剩余流量：49 GB 976.90 MB / 60 GB 0.00 MB（已用 16.7%）
记住的上网选择：未开启
```

## 写操作仍然不做

`devices/kick-offline/batch`、`devices/unbind/batch`、`nosense/unbind/batch`、`ppsk/self/bindMac` 四个写接口已从 SPA 分包中确认存在，但本轮**没有调用任何一个**，也没有为它们写代码。理由见提案：批量写没有幂等证据与失败语义证据，且「关无感知」会直接释放实名认证终端名额。

## 本轮遇到的真实现象

连续多次错误凭据 + 验证码失败后，CAS 返回「IP 被冻结，请 1 小时后重试」。这是**测试过程中真实触发的风控**，不是推测。触发后的表现是登录页正文变成冻结提示页（2973 B、无 `pwdEncryptSalt`），项目原有的错误文案「CAS 登录页未找到 pwdEncryptSalt」正好命中这个场景。

后续任何真实登录验证都应先用 `checkNeedCaptcha.htl` 确认是否已进入验证码期，并在失败后立即停止重试。

## 设备下线（写操作）接口契约

从 `/self/assets/myDevices-*.js` 反出的调用点（2026-11-09）：

```js
// 下线
await Ye({ onlineUserUuids: e, kickUnifiedAuthOffline: !au.value || tu.value })
//   Ye = POST /sam/api/userself/devices/kick-offline/batch

// 解绑 MAC（本项目未实现）
await $e({ macBindInfoUuids: e })
//   $e = POST /sam/api/userself/devices/unbind/batch

// 关闭无感知（本项目未实现）
await Ae({ noSenseUuids: e })
//   Ae = POST /sam/api/userself/nosense/unbind/batch
```

成功判定是 `code==200 && message=="OK"`，与只读接口一致。

`kickUnifiedAuthOffline` 的推导值得单独记：SPA 里

```js
au = ref(false); tu = ref(false)            // tu 是「无感知开关」以外的独立勾选项
su = (uuid, row) => { ...; row.unifiedAuthentication && row.currentDevice && (au.value = true) }
kickUnifiedAuthOffline = !au.value || tu.value
```

即：**下线本机**（`currentDevice && unifiedAuthentication`）时该值为 `false`，只断 Portal、保留 SSO，用户能重新上网；**下线其他设备**时为 `true`，连该设备的统一认证会话一起登出。本项目按同一规则实现（`kick_unified_flag`），不自行发明策略。

`devices/unbind/batch` 用的是 `macBindInfoUuid`，而 `/sam/api/userself/devices` 的响应里**没有**这个字段（只有 `onlineUserUuid`、`noSenseUuid`），说明解绑列表来自另一个接口；加上本校 `enableSelfUnbind=false`，本轮不实现。

## 已验证 / 未验证

- ✅ 契约来源：SPA 分包源码（`myDevices-FqRS9b8o.js` 45 KB），调用点、字段名、成功判定都直接读到。
- ✅ 实现：`ysu self kick <n|all>`，含下线前后两次读取的核验、本机/他机不同的 SSO 处理、非交互环境的 `--yes` 门槛。
- ✅ 离线测试：28 项，覆盖编号解析、`all` 过滤、越界与离线目标、SSO 标志推导、写后核验失败、写端点白名单。
- ❌ **没有对真实设备执行过一次下线**。验证过程中本机 IP 第二次被统一认证冻结（原因是短时间内反复完整登录，不是密码错误），所以真实写操作与核验链路都还没跑过。
- ❌ 没有验证 `kickUnifiedAuthOffline` 两种取值在服务端的实际差异（是否真的只断 Portal / 是否真的登出 SSO）。

解冻后应做的第一件事：用一台**不承担本次会话**的设备（例如手机）执行 `ysu self kick 2`，然后确认它真的断网、本机不受影响，再考虑是否可信。**不要在只有一台设备在线时试。**

## 会话缓存（2026-11-10 补）

前一轮的实现在 `open_session()` 里每次都新建一个 `requests.Session()`，所以**每次 `ysu self` 都完整跑一遍 CAS 密码登录**。验证过程中连续调用的代价是本机 IP 被冻结两次——这不是账号问题，是设计缺陷。

补上的做法：登录成功后把 cookie jar 写到 `$XDG_CACHE_HOME/ysu-net/self-session.json`（默认 `~/.cache`），下一次先用缓存。

- 文件 `0600`，目录 `0700`，原子替换；内容含 `CASTGC` / `SESSION` / `SOURCEID_TGC` 等会话 cookie。
- 绑定 `base` 与 `username`：两者任一不匹配直接返回 `None`，不会跨账号串用。
- TTL 600×3 = 1800 秒（`SESSION_TTL`）；过期、超 64 KiB、JSON 损坏、版本不符都按缓存未命中处理。
- 命中后仍做一次轻量校验（`GET /self/index`，不是登录），不通过就清掉缓存再登录。
- `--fresh` 跳过缓存；输出与 `--raw` 都会写明会话来源。

离线测试 11 项覆盖：往返保留 cookie 的 domain/path、文件权限、换账号/换源被拒、TTL 过期、损坏文件、失效后先清再登、命中时不调用 `cas_login`、`--fresh` 强制登录、渲染文案。

**未实测**：真实登录后写下的 cookie 能否让第二次调用免登录。验证时 IP 仍处于冻结期（第二次冻结约 1 小时），只能验证到离线层。

## 真实设备下线实测（2026-11-10 上午）

缓存与下线两条链路都已用真实账号跑通。

### 会话缓存

| 次序 | 命令 | 实际输出 |
| --- | --- | --- |
| 1 | `ysu self` | 会话：本次新登录 → 写出 `~/.cache/ysu-net/self-session.json`（`0600`） |
| 2 | `ysu self` | 会话：复用已登录状态（未重新登录，缓存剩余 29 分钟） |
| 3 | `ysu self --fresh` | 会话：本次新登录 |
| 4 | `ysu self --raw` | `session.cached=true` `session.expires_in=1799` |

第 2 次与第 1 次的在线时长相差 6 秒（`10时4分32秒` → `10时4分38秒`），说明复用的是**会话**而不是响应缓存，数据仍实时读取。全程只发生两次密码登录（第 1、3 次）。

### 下线

`ysu self kick 2 --yes`（索引 2 = 手机，非本机）：

```
[失败] 下线请求已提交但设备仍显示在线，请用 ysu self 复核
```

紧接着 `ysu self` 复核：**在线设备 2 台 → 1 台，手机确实下线了**。

即：写操作成功，是**核验时机错了**——写完立刻重读，门户还没更新在线列表，于是误报失败。这是实现的缺陷，不是接口问题。

修正：核验改为最多等待 `KICK_VERIFY_SECONDS = 12` 秒、每 `KICK_VERIFY_INTERVAL = 3` 秒重读一次，目标 UUID 消失即成功，超时才报 `KickVerifyError`。离线测试用 mock 覆盖了等待路径。

修正后的真实复核尚未执行——需要一门设备重新上线（手机当时已下线，本机不能拿来自测，下线自己会中断当前会话）。

## 图形化版本（2026-11-10）

桌面端是独立的 Rust 执行器，不共享 CLI 的 Python 实现，因此同一功能在 `ysu-auth` 里重写了一遍。

| 层 | 改动 |
| --- | --- |
| `ysu-auth/src/selfservice.rs` | 新增：委托 CAS 登录、`/self` 只读快照、设备下线与写后核验 |
| `ysu-auth/src/protocol.rs` | `cas_login_url_with(service)` 抽出，`api_cas_login` 提为 `pub(crate)`——登录、验证码、表单逻辑全部复用 |
| `ysu-auth/src/lib.rs` | `AuthClient::self_snapshot()` / `self_kick(selector)` |
| `src-tauri/src/runtime.rs` | `Action::SelfService` / `Action::SelfKick`、后端 Native/Demo 双实现、快照字段 `self_service` / `self_error` / `self_notice` |
| `src/lib/protocol.ts` | `SelfService` / `SelfKick` / `SelfDevice` 类型与两个 action 名 |
| `src/App.svelte` | 侧栏“设备”页、下线确认对话框、F5 刷新接入 |
| `src/lib/demo.ts` | Demo 模式的动作与日志映射 |

与 CLI 的差异：桌面端用**进程内**会话缓存而不是落盘。`Transport` 内部全是 `Arc`，`clone` 共享同一个 cookie jar；缓存键是 `base|username|local`，TTL 同样 30 分钟，命中后仍做一次 `GET /self/index` 校验，失效就丢弃重登。退出登录（`logout`）会主动清掉该账号的缓存，避免留下已失效票据。

不落盘的理由：`cookie_store` 的 `save_json` 需要额外 feature，会改动 `Cargo.lock`，而按项目规则本机不运行 `cargo`。进程内缓存已经能消除「同一次运行里连点刷新反复登录」这个真正的风险，应用重启后重登一次可以接受。

下线核验沿用同一语义：最多 `VERIFY_ATTEMPTS = 4` 次、每次间隔 3 秒重读设备列表，目标 UUID 仍在在线集合中就返回 `interaction` 错误。

### 验证状态

- ✅ `npm run check`（svelte-check + tsc）：0 错误 0 警告
- ✅ `npm test`：14 个文件 286 项通过
- ✅ `rustfmt --check`：`selfservice.rs` / `selfservice_tests.rs` / `protocol.rs` / `lib.rs` / `runtime.rs` / `diagnostic.rs` 全部通过
- ⚠️ **Rust 编译与单元测试未在本机执行**：项目规定编译、打包与产品测试只在云端 GitHub Actions 进行。新增的 `selfservice_tests.rs`（8 项）也没有跑过。
- ⚠️ 桌面端**没有真实登录过**，也没有在真实设备上执行过下线。

本机只做了语法与格式的只读检查（`rustfmt --check` 能解析即说明语法成立），并据此修掉两个真实错误：`Stage::Response` / `Reason::Verification` 两个不存在的枚举值，以及 `demo.ip` 在非测试构建里不存在。
