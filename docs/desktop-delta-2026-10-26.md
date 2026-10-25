# 2026-10-26 签名差分更新云端验收

[运行语义](updates.md) · [设计决策](../.agents/notes/implemented/desktop/2026-10-25-signed-delta-download.md) · [验收导航](desktop-acceptance.md) · [构建物清理](build-cleanup-2026-10-26.md)

## 结论与源码身份

真正 BSDIFF40 差分传输、补丁先验签/还原完整包再验签、受限缓存及下载阶段一次整包回退已实现；发布工作流保留原完整资产并接通可选差分生成和最终复验。代码不是正式新发行，也没有替换本机正在使用的程序。

[GitHub Actions 40217060581](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40217060581) 在独立开发构建分支 `build/signed-delta-20261025-163838` 的源码提交 `0107585dfbeb7cf98a4dad85cdc3bb278b085b1b` 完整通过。Windows x64 NSIS、Linux x64 deb、macOS arm64 和 x64 app/dmg 四项均 success；正式 release 与仅格式化 job 为 skipped，没有标签或 Release。

四平台执行现有前端检查/回归、应用 `--locked` 编译/测试、真实 Chromium 认证夹具、浏览器验收、开发包构建及各平台包验收。本轮桌面 Rust 测试分别为 Windows **159通过**、Linux **165通过**、两个 macOS 各 **164通过**，无失败或忽略；认证 crate 的7项默认忽略外部浏览器夹具另有明确步骤实际执行并通过，不将默认忽略当成通过。

## 差分证据及其边界

- 四平台真实调用官方 `Update::verify` 验独立测试密钥的补丁与重建完整载荷，并断言篡改补丁即使重算不可信 SHA 仍失败、旧完整包签名与伪造公告版本不能重放。数据是已签纯文本，不执行真正安装器；`mock-install` 只核对后台 pause/finish 次序。
- 缓存、平台/包型/精确基线、恶意 BSDIFF40 控制、无缓存首次整包、无效扩展、单次回退、原子失败、symlink/reparse、占用与 no-clobber 等测试实际执行。Windows官方NT绑定和Unix rustix目录句柄路径均通过云端临时目录用例；不把它们视为针对所有同UID恶意进程或所有文件系统的完整安全审计。
- Linux 的真实 qbsdiff/qbspatch 1.4.4 与 Minisign 0.12 发布集成4项通过：保留原完整包、重建重验、重写摘要也不能伪造补丁、受签名版本和坏基线拒绝。注入 signer 仅在生成补丁逐字节等于已签公开夹具后复制公开签名；未执行生产默认 signer、读取生产私钥或真正发布附件。其他平台明确 skip 此Linux专属CLI集成，不伪称执行。
- 网络错误回退使用注入网络层；URL/重定向规则及实际读取上限有策略/缓冲测试。不将配置超时、合作式解码 deadline 或 Mock 网络失败宣传为真实慢速 HTTPS/CDN 故障注入或可强杀阻塞CPU线程。

[公开夹具目录](../desktop/src-tauri/fixtures/delta/fixture.json)由云端独立临时密钥生成，私钥仅在 runner 临时目录后销毁；仓库只有公开数据。预检 [40210713525](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40210713525) 的公开夹具与依赖锁产物已按服务端 ZIP 摘要核验；[40211763690](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40211763690) 再解析显式 rustix/windows-sys 依赖，原包版本未改变。项目锁文件、格式化及所有编译/产品检查均在云端完成，本机没有 Cargo、Rust、前端生产构建或回退编译。

## 故障与修正没有被覆盖

保留未通过运行 [40213156786](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40213156786)、[40214249160](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40214249160)、[40215573102](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40215573102) 与日志身份。本轮依次修正 SDK 测试构造缺固定 endpoints、Ubuntu22未提供Minisign包、Windows检出改变已签文本换行、WindowsPath大小写不敏感排序与精确库存不一致；没有删断言、放宽签名/库存门槛或从云端失败回退本机测试。

签名夹具使用局部[.gitattributes](../desktop/src-tauri/fixtures/delta/.gitattributes)固定原字节，四平台都有提前SHA完整性检查。清单输出统一按精确文件名排序及LF，保留显式反例。Ubuntu22使用官方0.12静态归档并固定 SHA256 `9a599b48ba6eb7b1e80f12f36b94ceca7c00b7a5173c95c3efc88d9822957e73`；本机只下载/核验归档，没有执行它。qbsdiff1.4.4上游工具锁存在dev自依赖1.4.3冲突，因此仅独立CLI安装未用其损坏的 `--locked`，版本仍精确检查，应用原 `--locked` 门槛不变。

## 仍未覆盖

没有新正式版本、真实新旧签名安装载荷的省流量实测、软件内真实跨版本升级、Windows/macOS原位安装失败回滚、校园网新登录/下线/换号、物理断网或长稳。压缩整包差分不保证划算；只有补丁严格小于完整包80%才发布，无精确缓存时仍直接整包，不先拉旧包。首次正式启用和生产默认 signer/公开基线下载还需在明确授权的发布验收中验证。

当前Windows安装程序身份仍为此前云端验收包 `0CF4CE3B426430082411B3BD4EA559367027844130F407F4C110E2B6519C91A7`，本次最终只读复核相同；未停止客户端、读取真实配置或安装替换。源码提交收口仅补此证据、决策归档/注释链接及当前文档，不改变已验收运行逻辑，也不重复启动构建。

机器回执保留在 `build/maintenance-20261025/delta-preflight/`、`delta-candidate/` 与 `final-installed-preservation.json`；本报告保留可长期访问的源码/run身份，不能用本机缓存永久存在作假设。
