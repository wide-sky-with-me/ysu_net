# 0.2.1 验收与正式发布（2026-10-24）

本记录分别说明验收修复、本地公开签名夹具和开发分支 CI 的实际成绩，不将其中任何一项代作生产签名或软件内真实升级成绩。[旧 CI 失败记录](desktop-ci-2026-10-24.md)与[前次本地验收](desktop-candidate-2026-10-23.md)保持原貌；实际发行统一见[首页](../README.md#发行与候选状态)。

## 失败复现与修复

在 `4b03e4e` 构建后的本地预览中，兼容浏览器验收复现了旧脚本第 39 行找不到独立“离线模拟”横幅的问题。修复提交为 `a58d3be421c2437dce163feda450582d96018b47`，未恢复无意义横幅，也未删除 Demo 安全检查。

[兼容验收](../packaging/tauri_web_smoke.py)改为核对演示日志、禁用的更新操作、模拟自启状态刷新后重置以及普通网页的禁用控件；请求在发送前限制到预览服务的同一回环源，非回环预览参数提前拒绝。保留密码清空、无 Web Storage、断线 / 未知等场景、确认弹窗、紧凑布局及不下载认证运行时的原有断言。[桥接测试](../desktop/src/lib/bridge.test.ts)另核对 Demo 认证 / 系统设置只改内存，普通网页入口拒绝操作，两者均不调用原生 IPC。

## 本地实际验证

- `npm --prefix desktop run check`：零错误、零警告；`npm --prefix desktop test`：145 项通过；`npm --prefix desktop run test:build`：8 项通过。
- 同一构建预览依次执行 `packaging/tauri_web_smoke.py`、`desktop/tests/rust_desktop_preview.py`、`desktop/tests/multi_account_preview.py`、`desktop/tests/rounded_desktop_preview.py`：全部通过，无外部请求、页面或控制台错误。临时预览服务结束后关闭，原始报告保留于本地 `dist/release-0.2.1-20261024/`。
- Python 总回归：367 项，360 项通过、7 项因主机未安装 Minisign 明确跳过；后者随后在独立工具环境中全部实跑，不以跳过作为发布通过。
- Ubuntu 24.04 临时容器安装发行版 Minisign 0.11 后，`python3 -m unittest tests.test_update_manifest tests.test_update_signature -v`：19 项全部通过、无跳过，包含三个目标逐项损坏、错误公钥、伪造签名、改写受保护备注、旧签名重标版本及 CLI 验签失败不得报告成功。

签名夹具来自已销毁私钥的独立公开文本样本，与生产密钥无关；测试不执行安装器或真实认证。旧 Ubuntu 22.04 SDK 的发行源未提供 Minisign 包，因此验签工具验证改在 Ubuntu 24.04 进行，未更换原生 Linux 构建基线。

## 已结束的远端开发 CI

[运行 40040905354](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40040905354)对应 `a58d3be`，最终整体成功：Linux x64、Windows x64、macOS arm64、macOS x64 全部构建、原生及对应安装验收成功。Linux 已通过先前失败的完整浏览器验收链。

这是非标签的开发分支运行，签名构建和 Release 作业按条件跳过；其安装器不能冒充正式签名更新包。后续发布提交还须由标签运行完整门槛，不能只复用本页的成功描述。

## 首次信任锚与后续失败复核

用户已批准为尚未正式发行的 0.2.1 建立新签名基线，公钥和仓库 Secret 已配套配置；私钥在仓库外按所有者权限保存，不进入报告。官方工具签署不可执行预检文本后，隔离 Minisign 已用配置公钥验证载荷及版本 0.2.1；这只证明配对可用，不代替三个最终更新包的真实验证。旧 0.2.1 候选包需手动安装正式版，见[迁移说明](migration.md#桌面-v021-及旧候选包)与[信任锚决策](../.agents/notes/implemented/desktop/2026-10-24-first-signed-release-trust-anchor.md)。后续标签必须针对含新公钥的最终源码重新通过四平台与实际载荷验签，不能使用旧候选安装器替代。

`91233ef` 的[运行 40042116339](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40042116339)中，Linux、Windows、macOS arm64 通过；macOS x64 初次在真实 Chromium 的 DOM 验证码 / 风控夹具返回 code 2 而非预期 4，约耗尽该测试的 10 秒预算。同一源码仅重跑失败作业后，7 项 Chromium 夹具全部通过，随后在 `bundle_dmg.sh` 返回通用打包错误；该日志不足以确定 DMG 子命令的具体原因，不能记为最终通过。

真实 Chromium 夹具预算随后与相邻的完整 CAS / 验证码场景统一为 20 秒，保留 code 4 和禁止提交凭据的全部断言；业务默认值、短时限专门测试不变，失败时仅补充固定诊断枚举。普通 Mac 构建额外启用 Tauri 详细输出，签名密钥所在步骤不启用该诊断；不跳过 DMG 或安装门槛。

## 正式发布与公开下载复核

最终源码 `467a0764381a179add8bc1d295b843eab03c4a02` 的[开发 CI 40048061662](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40048061662)四平台全部成功后创建 `v0.2.1` 标签；[签名标签运行 40048904776](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40048904776)再次完成四平台构建、原生与安装验收，三个更新包签名及统一发布前门槛全部通过。Linux SDK 配置较慢，未跳过该平台或用旧包替代。

[正式 v0.2.1 Release](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.1)于 **2026-10-24 09:50:57（Asia/Shanghai）**公开，非草稿、非预发行，已成为 Latest。公开复核实际下载全部 13 个附件：`SHA256SUMS` 的 12 项覆盖与摘要全部匹配；三个真实更新载荷由维护中的 Minisign 使用标签客户端的固定公钥验证通过，受保护版本均为 0.2.1，清单内联签名与独立 `.sig` 一致。

另外不携带凭据访问固定 `releases/latest/download/latest.json`，得到与该正式版相同的清单；清单中三个下载 URL 均可匿名获得与正式附件摘要相同的字节。独立复核只用公钥，不启动安装器、解压安装或执行真实升级；Python wheel / sdist 的 233 个成员完成路径与密钥容器文件名检查，不把该检查冒充内容级全面秘密扫描。原始公开附件与 JSON 证据保留于本地 `dist/release-0.2.1-20261024/` 与 `build/release-0.2.1-ci/`，不含私钥。

## 发布门槛与未覆盖范围

[发布流程](../.github/workflows/tauri.yml)要求四平台成功后，使用客户端原公钥和维护中的 Minisign 验证实际三个更新载荷及受保护版本，并核对公开清单与摘要，通过后才发布；签名、密钥不匹配或工具缺失都须阻止发布。实现及限制归属[软件更新说明](updates.md)，不从待发布附件取公钥建立自证信任，也不把独立夹具通过当作生产密钥匹配。

真实校园网新登录 / 下线 / 换号 / 物理断网 / 长稳，以及 Windows / macOS 软件内原位升级和失败回滚仍未完成实机验收。更新签名不等于 Windows Authenticode 或 Apple 签名 / 公证；0.2.0 首次升级仍需手动安装。
