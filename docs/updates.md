# 签名在线更新

[桌面说明](tauri-desktop.md) · [更新实现](../desktop/src-tauri/src/updater.rs) · [生命周期决策](../.agents/notes/implemented/desktop/2026-10-22-diagnostics-and-update-lifecycle.md)

## 使用与版本边界

当前开发界面将“软件更新”集中到侧栏“关于”。已发布 0.2.1 的入口仍在“设置 → 外观与启动”底部；0.2.0 不含入口，须手动安装一次含入口的新版本，只有后续版本可从软件内更新。当前是签名整包在线覆盖升级，不是二进制差分增量。本页说明实现与信任边界，实际正式发行和 CI 状态统一见[首页发行状态](../README.md#发行与候选状态)，不从界面或普通安装验收推断远端原位升级已经通过。

仅用户点击“检查更新”才访问版本源。发现新版后展示版本与纯文本说明，用户确认后下载、验签并安装；没有启动时自动下载或静默强制升级。Demo / 普通网页不检查或安装真实更新。说明和下载元数据不接收网页传入的地址或公钥。

- Windows x64：复用当前用户 NSIS 安装器，安装前暂停本客户端任务，安装器可能直接退出旧进程。
- macOS arm64 / x64：使用对应架构 `.app.tar.gz` 更新包；安装后按界面提示重启。当前构建仍未提供 Apple 发布者签名 / 公证，更新签名不替代它们。
- 当前 Linux `.deb` 产品：提供固定 Releases 下载入口，继续按系统包方式升级；本轮未启用原位安装。Python CLI 的安装 / 升级方式不变。

“前往发布页”在原生客户端通过无参数 `updater_open_releases` 命令调用官方 opener 的 Rust API，只能打开内置的固定 Releases 地址；不向网页开放任意 URL、应用程序选择或插件 guest 权限。普通网页仍使用正常链接，Demo 不显示或调用真实打开入口。Linux deb 声明 `xdg-utils` 运行依赖，默认浏览器须由系统正确配置；成功分派不代表网页已加载。系统打开失败显示固定错误及可手动复制的公共地址，不输出本机路径或底层异常。

检查或签名失败不会停止认证后台。下载验签后若已有认证工作正在执行，安装被阻止，稍后重试；安装前同时拦住新任务、排队任务、启动首查和自动重连。暂停不发 Portal 下线请求，不改变账号、自动重连偏好或系统自启。仅暂停 / 安装 / 后台重建的临界段暂缓普通退出，避免半替换；下载阶段仍可退出。Windows 官方安装器成功后自行退出，不用其提前执行的回调不可逆地丢弃恢复上下文。安装失败先恢复同配置后台；恢复失败保持锁定，只能显式重试恢复或退出重开，不在半停机状态自动认证。重启参数使用启动时已解析的绝对配置路径，避免安装器或 LaunchServices 改变工作目录后读错配置。

更新源未发布 `latest.json` 时显示“更新源尚未就绪”，不是“已经是最新版”。网络、清单、签名、安装和后台恢复分别提供固定错误，不输出包含下载令牌的底层错误。

## 信任与发布

使用[官方 Tauri updater](https://v2.tauri.app/plugin/updater/)，不自实现密码学验证。公钥内嵌于 [Tauri 配置](../desktop/src-tauri/tauri.conf.json)，私钥保存在仓库外受保护目录，不进入客户端、源码、日志或构建附件。`requireSignedVersion=true` 同时绑定已签载荷和公告版本，禁止用更高公告版本重放旧签名载荷。0.2.1 首次正式更新发行按[信任锚决策](../.agents/notes/implemented/desktop/2026-10-24-first-signed-release-trust-anchor.md)建立签名基线，旧 0.2.1 候选包需[手动安装正式版](migration.md#桌面-v021-及旧候选包)。正式发行后必须维护本密钥；未来更换公钥须另行设计迁移，不能让已安装客户端直接信任新的任意公钥。

静态源固定为 `https://github.com/wide-sky-with-me/ysu_net/releases/latest/download/latest.json`。下载只接受本仓库的 HTTPS Release 附件，再由官方插件验证签名与版本；客户端不会根据前端参数改源或关闭验证。清单内联 `.sig` 内容，分别声明 Windows x64、macOS x64 / arm64 目标；当前 Linux deb 不伪造自动更新目标。

普通开发 / fork 构建不要求签名密钥。发布构建在进程环境提供 `TAURI_SIGNING_PRIVATE_KEY`（私钥路径或内容）及可选的 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`，执行 `npm --prefix desktop run native:build -- --signed-update`。参数只开启官方 `createUpdaterArtifacts`，不接收任意构建配置；CLI 自动把应用版本写入受签名保护的备注。私钥不应粘贴到聊天或提交进仓库。

正式 tag 的 Windows / macOS 构建从 GitHub Actions Secrets 读取同名密钥，缺失即失败；四平台验收通过后才能发布。签名安装包 / app archive、对应 `.sig` 和 `latest.json` 都需上传，摘要同时覆盖这些公开附件。发布作业安装维护中的 Minisign，使用客户端配置内的原公钥严格验证三个载荷及签名保护的版本，并核对清单 URL / 内联签名与实际文件一致；结构或 SHA 校验不能替代该验签，验证工具缺失也阻止发布。[Tauri CLI 2.12.2 的密钥不匹配检查](https://github.com/tauri-apps/tauri/blob/tauri-cli-v2.12.2/crates/tauri-cli/src/bundle.rs)允许只告警后继续签名，因此不能用构建成功代替此门槛。不从待发布附件下载新的公钥替换信任锚。普通开发分支的安装包与测试附件不因此成为正式发行或公开更新源；实际状态见[首页](../README.md#发行与候选状态)。

## 验证范围

单元测试包含状态机、认证门闩、失败恢复和独立测试公钥的官方 `Update::verify`；有效签名、损坏载荷、伪造版本和坏签名各自断言。固定测试包是不可执行纯文本，私钥不入仓库，测试不联网或安装更新。发布页测试经过真实 Tauri IPC 路由验证固定地址、Demo 禁止和固定错误；Linux 另由清空环境的独立子进程调用官方 opener，并仅把请求交给隔离的记录脚本，不启动真实浏览器或联网。这不证明 Windows / macOS 的系统浏览器配置或页面加载成功。网页 Mock 交互只验证按钮 / 确认与 IPC，不代表真实升级。真实 feed、Windows / macOS 原位升级与失败回滚需在隔离测试机器逐项验收；当次候选成绩和缺口另列验收记录。
