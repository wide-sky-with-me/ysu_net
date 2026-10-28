# 2026-10-28 v0.2.3 构建与发布记录

[返回验收导航](desktop-acceptance.md) · [当前发行状态](../README.md#发行与候选状态) · [升级指南](migration.md#桌面-v023-升级)

状态：[正式 v0.2.3](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.3) 已于 `2026-10-28T04:33:07Z` 发布，为 stable、非草稿并成为 Latest。标签源码为 `96e3a4beb662182a610b7cfa0611fd76f47b0735`，13 个公开附件及固定更新地址已复核；本机没有安装新 GUI。

## 范围与来源

本版将 Python CLI、Tauri、前端与共用 Rust 认证库同步至 0.2.3，并更新各自锁文件中的项目版本，不更新第三方依赖。保留 v0.2.2 正式更新信任锚。包括独立状态观察、账户来源绑定、门户 HTTP / HTML 导航、DNS 回退、验证码及动作信封、账号池诊断与回归，以及独立认证探针和云端门禁。

运行语义分别归[桌面说明](tauri-desktop.md)、[账号池](accounts.md)与[探针操作指南](rust-auth-probe.md)；本页记录当次验证和发行事实。

| 已有实测 | 证据与限制 |
| --- | --- |
| 21 旧客户端和正式 v0.2.2 Shell 的离线登录 / 在线退出 | [同机对照](portal-21-review-2026-10-28.md)，已恢复原连接 / 后台；不是新 Rust 结果 |
| Shell 账号池直接 / 守护双向换号 | [账号池记录](account-pool-21-review-2026-10-28.md)，四次真实切换；未测试真实零流量触发或服务拒绝恢复 |
| 离线 / 在线两条导航链 | [跳转对照](portal-redirect-parity-2026-10-28.md)，21 脱敏轨迹结合 123 精确地址样本；原 Windows 故障一跳仍未采样 |
| 123 DNS 与服务拒绝 | [123 记录](portal-123-review-2026-10-27.md)；CAS 成功后服务拒绝不能靠放宽导航或 TLS 消除 |

## 云端与正式发行

独立构建分支上的最终产品候选 `42282a624969c5ef010033ef1a2f1bdfd1c0ea8c` 已通过 [Native 40630691590](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40630691590) 的四平台构建、原生 / 安装及独立浏览器门禁，[Mock 40630691566](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40630691566) 453 项与 [Community 40630691595](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40630691595) 也通过。后续 `96e3a4b` 仅更新文档及链接，产品源码逐字节未变，随后快进并推送 main、创建正式标签。

正式源码的 [Headless 40631817211](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40631817211) 四目标认证库 / 探针回归、release 构建及实际二进制输入验收全部成功；[标签 Native 40631875553](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40631875553) 的四平台原生、Chromium、安装门禁、独立界面验收与 release job 全部成功，[标签 Mock 40631875476](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40631875476) 及 [Community 40631875493](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40631875493) 同样成功。发布前由云端 Minisign 按原公钥和受保护版本验证真实完整载荷。

同提交重复的 [main Native 40631817243](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40631817243) 为释放 macOS 并发名额主动取消；候选与正式标签的完整门禁均保留并通过，不将取消记作通过。本机只做静态核对、云端产物下载 / 摘要验证及明确记录的运行验收，没有执行 Cargo、rustfmt、前端构建或读取生产签名私钥。

## 公开资产与签名

本次实际发布 13 项：四个系统安装包、两个 macOS 更新 archive、三个完整载荷 `.sig`、Python wheel / 源码包、`latest.json` 与 `SHA256SUMS`。三个更新平台为 Windows x64、macOS arm64 / x64，Linux 继续 `.deb` 手动升级。原更新公钥字符串 SHA256 仍为 `57de1a2962b7535c52a720912ad2b3d8c3823908e766a085481c8f6ef14ce3c9`，未换信任锚。

云端取得可信 0.2.2 基线，但生成的补丁候选没有通过大小 / 收益门槛；公开 `deltas` 为空，差分附件为零，没有实际生产补丁签名或补丁还原可供宣称。本次 0.2.2 → 0.2.3 下载完整更新包；支持条件差分不代表每次都会发布补丁。

发布后重新下载全部 13 个公开附件，逐项核对大小、SHA256、签名字段和完整清单，全部与云端已验签的 `release-verification-v0.2.3` 清单一致；`SHA256SUMS` 全部通过。Release / Latest API 为 v0.2.3，固定 `releases/latest/download/latest.json` 的实际字节也与本次清单一致。本地没有重复运行 Minisign，签名认证证据来自成功的云端验证，公开下载字节与其摘要一致。

脱敏公开复核收据、云端清单与下载资产保留在本地忽略目录 `build/release-0.2.3-20261028/`。更新包签名不等于 Windows 发布者签名或 Apple 签名 / 公证；发布后的文档补记不改变发行标签或已上传资产。

## 首轮验证与修正

首轮候选 `6b80a80b04d8b852790470a95c45e7a22da409af` 的 [Mock 40629197054](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40629197054) 453 项通过；此前首轮失败发现 DNS 模块相对导入破坏脚本入口，已改为绝对包导入，保留原退出码断言。[Native 40629197046](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40629197046) 四平台构建 / 原生 / 安装作业全部通过，但独立 browser-acceptance 因随包日志缺少原有信任锚不变的明确措辞而失败；发布仍被阻止，说明已补，需新候选重跑。

UTC 03:56:46–03:56:54，在 21 运行同提交 Linux 云端 Rust 探针：在线 status=0；Shell 下线后 Rust status=1，证明离线门户引导可完成；Rust login=4，在 CAS 回调要求交互，Shell 独立确认仍离线。随后原 Shell login=0 恢复移动服务，身份匹配、守护 active，原配置和源码逐字节不变。本轮没有成功 Rust 登录或退出，不算认证闭环通过。

随后只读分类证明正常门户 / 回调页脚本引用 noSupport，旧 Rust 整页扫描将其误作风控；新增文档文本判断及正反合同。原因与替代方案归[决策](../.agents/notes/implemented/desktop/2026-10-28-cas-callback-risk-text.md)。

## 修复后的真实验证

候选 `153f24c4ffc09fc07b64983f41ad331d94d1f182` 的 [Headless 40630120452](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40630120452) Linux / Windows 云端产物已核对 manifest 源码及 SHA256。Linux 二进制摘要为 `c27c811c2d94ca09374079bea82c80ed44c373885e1a6fc6fb4efc7972e66c0e`，Windows 为 `745fd3792e4015136c3b5ea2dc82d15a3b2d14958f60fe17e20b3c304db7040b`。

UTC 04:06:41–04:06:44，21 原后台停止后由 Shell 下线并独立确认 offline；Rust status=1，Rust login=0 且新 Transport 后查确认同账号 / 移动服务在线，Shell 独立 status=0 配对一致；Rust logout=0，Rust 与 Shell 均确认 offline。最后原 Shell login=0 恢复原移动连接，守护恢复 active，持久配置与原安装源码逐字节一致。凭据仅在 21 内存及 Rust stdin 管道中使用，未更换原安装或导出配置。

Windows 同提交 exe 使用默认门户 / CAS、API 后端、TLS 校验及 20 秒总预算，不传账号密码、不开 GUI、不修改配置，status=0，读取到 online / unicom；owner_matches_config=false 是无账号输入的预期，不能据此认领在线身份。临时 Windows 文件已删除。该结果证明本次环境的 Rust 导航可完成，不代表原 Windows GUI 故障已逐项复现或 Windows 离线登录 / 退出通过。

上述探针直接使用产品 AuthClient，没有复制 Python 协议；它不包含原生 Worker、账号池、锁、托盘或界面。Shell 账号池已有单独实测，Rust Worker 仍以相应云端回归为证据。脱敏收据与控制器保存于本地忽略的 `build/release-0.2.3-20261028/`，不上传原页面、账号或会话。

## 后续门禁修正

[Native 40630120663](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40630120663) 的 macOS arm64 在首次下载后立即重新打开缓存时遇到 WouldBlock，当时停止发布。随后补齐 Cache 所有者析构时显式解锁，并新增共享文件描述符仍存在时的排他 / 释放回归；原断言保留，取舍与尚未直接观察的 fork 解释见[决策](../.agents/notes/implemented/desktop/2026-10-28-cache-lock-lifetime.md)。

修复后的候选与正式标签现已分别通过上述四平台 Native 门禁；这项修正没有改变已在 21 / Windows 实测的认证库、验证入口或共享地址表，已用 Git 对照确认与 `153f24c` 的相应源码完全一致。

## 未覆盖范围

真实 Windows GUI 门户故障、软件内跨版本原位升级与失败回滚、物理断网、真实零额度自动换号及长稳运行仍需独立实机验收。当前已保存的 Shell 成绩和历史已通过的观察器候选仅代表各自源码与环境。
