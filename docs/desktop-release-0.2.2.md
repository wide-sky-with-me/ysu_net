# 2026-10-26 v0.2.2 正式发布验收

[返回验收导航](desktop-acceptance.md) · [当前发行状态](../README.md#发行与候选状态) · [更新语义](updates.md) · [升级指南](migration.md#桌面-v022-升级)

## 发行与源码

[正式 v0.2.2](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.2) 于 `2026-10-26T15:31:38Z`（上海时间 23:31:38）发布，为 stable、非草稿并已成为 Latest；发行标签源码为 `925569a3beb8aec635256a42ceb6df9fced62911`。本页只记录该发行，不回写 0.2.1 或此前冻结记录。

## 云端流水线

- 预发布 [Native 40343277913](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40343277913)、[Mock 40343277847](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40343277847)、[Community 40343277679](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40343277679) 均成功。
- 发行源码的 main 与 tag 共六条流水线均成功；[标签 Native 40347003244](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40347003244) 包括成功的 release job，[main Native 40347003375](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40347003375) 亦通过。
- Native 覆盖 Linux x64、Windows x64、macOS arm64 / x64 构建、原生与安装验收；这些是 runner 环境成绩，不是本机部署或校园网登录证明。

## 真实整包签名与本次资产

三个真实完整更新载荷（Windows NSIS、两种 macOS app archive）及版本 `0.2.2` 已在云端使用 Minisign 与客户端原公钥验证。客户端配置中公钥字符串的 SHA256 为 `57de1a2962b7535c52a720912ad2b3d8c3823908e766a085481c8f6ef14ce3c9`，沿用 0.2.1 正式信任锚，没有换钥。

可信公开旧基线为 0.2.1，但本次最终只有原 13 项资产：四个安装包、两个额外 macOS 更新 archive、三个 `.sig`、Python wheel / 源码包、`latest.json` 与 `SHA256SUMS`。`deltaTargets` 为空、差分附件为零，**没有执行生产补丁签名，也没有本次真实差分传输或省流量成绩**。客户端具备条件差分能力，不等于每次发布都有补丁。

## 匿名公开下载复核

- 13 个公开附件已全部匿名下载；每项实际大小与 SHA256 均与云端已验签 inventory 及 GitHub API 资产摘要一致。`SHA256SUMS` 的 12 条记录完整覆盖其余附件，三个平台的内联签名均与各自独立 `.sig` 相同。
- 固定 `releases/latest/download/latest.json` 的实际字节与 v0.2.2 清单完全相同，版本为 `0.2.2`，原三个平台键完整。清单 SHA256 为 `a6d6d684d85bf6c96508ced6fc8de7898dc4376e9edfe2b3900c49a747f69287`。
- 核对报告保留在本地证据目录 `build/release-0.2.2-20261026/public-byte-verification.json`；公开来源为上述 Release 和云端运行。这里的下载复核是与已验签云端字节一致，不声称本机重新执行 Minisign、安装器或产品测试。

## 图标证据

安装图标 SVG 与界面品牌统一为默认蓝色底图及三节点 / U 形连线。四目标的 PNG / ICO / ICNS 生成与头部检查通过；Windows 应用与安装器 PE 图标像素和生成 ICO 相同。已人工查看云端 32px / 128px PNG，不据此宣称所有尺寸、所有系统安装器或桌面托盘外观都经过实机验收。

## 本机与未覆盖范围

本轮未在本机编译、运行产品测试、安装新客户端或更改账号、配置、自启、认证状态；公开附件只下载与核对，没有执行。发布前只读核对的本机安装版为 0.2.1，不据此推断用户之后是否自行升级，也不冒充本轮已部署 0.2.2。

真实签名安装载荷的软件内跨版本原位升级、Windows / macOS 安装失败回滚、系统登录自启、本轮校园网新登录 / 下线 / 换号、物理断网与长稳仍未执行。Mock trace、纯文本差分夹具和普通安装不能代替这些场景。无可信缓存首更仍直接下载整包；Linux `.deb` 继续手动更新。

旧版若检查更新即退出，可从正式 Release 手工升级；不要禁用 TLS 校验、验签或替换公钥。安装、缓存及失败恢复规则以[更新说明](updates.md)为准，本页不复制运行协议。
