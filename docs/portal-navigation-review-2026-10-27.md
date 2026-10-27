# 2026-10-27 门户入口只读观察与精确来源变体

状态：111 独立只读采样与新导航源码云端回归完成；未新发行、未部署、未确认 Win11 现场。现行行为归[运行说明](tauri-desktop.md#门户导航与诊断开发源码)，取舍归[导航变体决策](../.agents/notes/implemented/desktop/2026-10-27-portal-entry-variants.md)。

## 既有交付与本轮范围

已交付文档 / 源码阶段为 `63920be6ccbf7cf93b89872ccbec69180e435837`，其产品候选是 `1a81aac9c20cb660a6b31993ba7245bea03cc1d0`；该轮云端成绩与认证链对照保留在[既有记录](auth-flow-review-2026-10-27.md)，不回写。它没有本轮新增的精确 history 来源、Browser bootstrap Location 接线和导航分类诊断，不能沿用旧通过作新候选验证。版本字符串仍为 0.2.2，正式安装包不含这些开发改进。

用户本轮另行授权在已配置的 `111` 上观察只读门户链。采样经已知主机校验和 batch 模式连接，只执行独立 Requests 观察器，没有执行 Rust / CLI 产品、读取账号配置、发送账号密码、下线或重连服务器；不运行页面 JS，不发明文 HTTP，不写远端文件。

## 安全证据与请求账本

仅留存角色分类收据；原始 URL、SID 和正文只在远端内存处理，没有保存或导出。安全证据位于本地 `build/portal-trace-20261027-111/`；下列收据名用于定位，不承诺公开仓库或 CI 检出包含这些本地文件。

| 收据 | UTC 采样时间 | 实际请求 |
| --- | --- | --- |
| `navigation-receipt.json` | 05:05:56 | 两组各 8 GET，共 16 |
| `history-receipt.json` | 05:08:03 | 两组各 3 GET，共 6 |
| `parser-receipt.json` | 05:16:15 | 两组各 1 GET，共 2 |

合计 24 GET，明文 HTTP / POST / 认证变更 / 下线均为 0。两组分别为 Shell 默认和 Native 默认 UA / header 的子集，均直连且保持 TLS 校验；不是实际 Shell 或 Rust 网络栈的同机 A/B。

收据中的 probe SHA256 只标识独立采样器，不是 Rust 产品身份或原始响应摘要：
- 普通入口：`f196e2d04ce4c5829403ef2410452e33810b632bea3e1b31d68d1ecf197c0f13`。
- history：`bc3f5cbba15b02c17d1c661360696730e57a455f1d908ea61558f5b1ae68a8ae`。
- parser：`ae692a695d7bd5cc41ffb6bacdd3afff3bd2e8c2979d51871b7b8062d724a4c5`。

## 普通链：旧 API 规则已有覆盖

- 两组 index 均为 HTTPS 200，没有 SID 或可跟随的静态候选；不能把“未选到候选”当认证失败或更换凭据的理由。
- 无 query 的 redirect 来源返回 302，目标是同门户、默认 HTTP 端口的固定 `portal_main`，含唯一有效 SID。观察器不访问该 HTTP 地址，只请求已知同门户 HTTPS 等价目标，得到 200，再只读确认 online 和唯一识别服务。
- root 经 HTTPS redirect 再走同链；普通链收据的旧 `current_legacy_rewrite_shape` 为 true。因此普通入口组合本来就在旧 API 窄规范化范围内，不是新发现的未覆盖 bug，也不证明本机 Rust 已执行成功。

## history 链：实证新增一个完整来源

两组均实际观察到唯一公开 `mode=history` query 的 HTTPS redirect 来源，随后也是上述同门户旧 HTTP 目标；只请求 HTTPS 等价后得到 200，状态查询确认 online。旧完整来源比较只接受无 query 入口，所以两份 history 收据均标记旧 rewrite shape 为 false。

这次有“实际来源 query + 实际 Location 目标”的组合证据，不再只是从外部工具默认入口推断。永久对照采用本文的角色形状与[本轮合成夹具](../tests/fixtures/portal-entry-variants.json)：使用公开配置 endpoint 和合成 SID 重建两来源，不包含采样中的原 URL / SID。修正只增加第二个完整来源值，不移除任意 query、不扩大域名 / 路径 / 端口或 HTTP 许可；细节以[唯一运行说明](tauri-desktop.md#门户导航与诊断开发源码)为准。

## index parser 补证与限制

补采两组 index 均为 200、完整 631 字节；按 UTF-8 损失替换解码、2 MiB 上限及 Rust regex 的相同优先顺序选择首候选，结果均为 None，未截断，没有跟随候选。没有证据要求改变 parser、入口顺序或增加盲目 failover。

HTML meta 部分使用 Python HTMLParser，不是 Rust scraper；相同 regex 顺序和完整样本大小不能证明两种 HTML 解析器全等，也不能据此覆盖未执行的 JS 导航、动态 DOM、真实 Chromium 或其他门户响应。

## 新候选与未覆盖

新产品候选 `2bb9589e8526f681ab4616124d8f1f10bf2ab97c` 增加精确来源、共享导航检查、受限 Browser HTTP Location 接线及闭集诊断；[四目标 Native 构建与回归](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40457529662)、[Mock](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40457529602)及[Community](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40457529590)均成功。[独立云端格式化](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40456935394)仅计格式化来源，不计产品成绩；旧 `1a81` 的通过未代替本轮。文档状态收尾单独检查，不改上述已验产品源码。

本轮新增 Browser 导航回归覆盖生产纯决策与 Header 序列化，未真正驱动完整 `Browser::fulfill` / CDP 发送或系统 Chrome 校园端到端；实际调用接线只经静态核对，不能把两者合并为完整端到端成绩。

本次 111 已在线，未制造网页下线 / 离线，未执行 Rust 产品、同机 CLI / Rust A/B、凭据登录或会话变更；它不是用户 Win11 网页下线后 `redirect_blocked` 的现场复现。既有诊断定位和真实响应变体是不同证据，不能据此宣称 Win11 已修复或新包已部署。

所有编译、格式化、产品 / 单元与浏览器回归只走 GitHub Actions；本文只做安全收据阅读与文档静态核对，不新增 SSH、校园网络、配置凭据、Git 或发布操作。
