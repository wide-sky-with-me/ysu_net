# 0.2.4 构建与发布记录

日期：2026-10-28。状态：正式 v0.2.4 已公开并成为 Latest，发布时间 08:52:57 UTC；公开下载复核通过。本机未安装或操作校园网连接。

## 源码与范围

标签 `v0.2.4` 对应 `d2439f00d34e10d61e7dc18532f3e3f7e2071f2a`。产品基于[已验证的链路调试源码](debug-recording-2026-10-28.md)，同步 CLI、前端、Tauri 和认证库版本及各锁文件中的项目版本，不更改第三方依赖。调试默认关闭，操作前开始记录，断网后可取出文件；当前合同见[指南](debug-recording.md)。此发布提供取证能力，不证明此前 Windows network 故障已经定位或修复。

后续 CI 分层优化不包含在本标签内。发布继续使用既有完整四平台 / 浏览器 / 安装 / 原公钥验签门禁，不将新 CI 策略的静态合同冒充正式标签实跑。

## 云端验证

| 运行 | 结果 |
| --- | --- |
| [Native / Release 40658458384](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40658458384) | 四平台构建、认证 / Runtime、真实 Chromium、完整浏览器、原生 / 安装检查及正式发布均成功 |
| [Mock 40658458429](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40658458429) | Python 回归、分发构建和包内地址数据检查成功 |
| [Community 40658458320](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40658458320) | 社区文档检查成功 |

新增功能在此前开发提交已有四平台认证探针验证；本标签没有独立 Headless 运行，不把旧源码的探针成绩改记成标签成绩。全部产品构建、格式与测试由 Actions 执行，本机只做静态核对及公开产物下载 / SHA256 比对。

## 公开资产与签名

[正式 Release](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.2.4)有 13 个资产：四个安装包、三个完整更新载荷及其三份签名、Python wheel / 源码包、latest.json 和 SHA256SUMS（Windows 安装包与更新载荷是同一文件，计数按实际附件去重）。`deltas` 为空，没有差分附件、生产补丁签名或还原收益成绩。

云端使用原客户端公钥与受签名版本验证三个真实完整载荷，并取得可信 0.2.3 公开基线；最终补丁未达发布条件，保留完整包。更新公钥字符串的 SHA256 保持 `57de1a2962b7535c52a720912ad2b3d8c3823908e766a085481c8f6ef14ce3c9`，不更换信任锚。

[认证清单 artifact](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40658458384/artifacts/12802534532)的 ZIP SHA256 为 `780b16b09340c190669ceaacd490ca713afe1f5e12fb3ca49dfdfa9e19cd02a4`。其 sourceCommit、版本、原公钥摘要与 fullAndDeltaVerificationCompleted 均核对；随后逐个下载所有 13 个公开附件，大小与 SHA256 全部等于该已验签清单。固定 Latest 下载别名的 latest.json 与标签附件逐字节一致，版本为 0.2.4。本机未重新执行 Minisign，不把摘要比较说成本机独立验签。

## 使用与剩余范围

Windows / macOS 可从“关于”主动检查更新，Linux 使用对应 deb；配置和账号簿保持兼容。更新包签名不替代 Windows 发布者签名或 Apple 签名 / 公证。

本轮未运行本机 GUI、新登录 / 下线、实际断网、账号池轮换、跨版本软件内升级或失败回滚。这些场景不能由公开包验证或云端演示替代；需要用户先开启记录再复现，继续定位原机器的网络失败。

忽略目录 `build/release-0.2.4-20261028/` 保存发布源码身份、认证清单、公开附件与复核收据；没有真实账号、密钥或原始认证材料进入本轮提交。
