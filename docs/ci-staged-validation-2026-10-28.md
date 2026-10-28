# 桌面 CI 分层：基线与验证

日期：2026-10-28。状态：已完成云端 checks 与 Windows 单平台打包验证。当前操作归[开发说明](development.md#tauri-ci-并行门禁)，原因归[分层决策](../.agents/notes/implemented/ci/2026-10-28-staged-desktop-validation.md)。

## 已观察的旧流程

源码 `6f27ff8eed90a9ab6e04d0d52d4faa69fe02b183` 的[开发分支运行 40654179654](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40654179654)全部成功；各 job 的完成减开始时间如下，不含未报告的排队：

| job | 总秒数 | Rust 测试步骤 | 普通编译 / 打包步骤 |
| --- | --- | --- | --- |
| Linux x64 | 287 | 42 | 101 |
| Windows x64 | 405 | 94 | 166 |
| macOS arm64 | 293 | 52 | 130 |
| macOS Intel | 572 | 111 | 245 |
| 独立浏览器 | 335 | — | 完整浏览器步骤 300 秒 |

Intel 日志中的 Cargo release 为 220 秒，245 秒步骤还包含其他工作，不能统称为编译。相同提交推至 main 后的[重复运行 40655751510](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40655751510)也成功，Intel 总计 740 秒，缓存步骤 116 秒、编译 / 打包 343 秒。这说明完整矩阵重复触发和平台波动都影响反馈，不由缓存步骤时长推断冷 / 暖命中。

此前调试功能开发还经历格式修正和异步栈占用回归，另见[原记录](debug-recording-2026-10-28.md)；多轮等待不等于单次 Rust 编译耗时。历史失败与旧通过均保留。

## 本轮范围

增加 SDK 准备前的格式 / 前端 preflight；普通推送保留四平台回归但不打包，以最小浏览器冒烟反馈。请求安装包时执行原完整浏览器验收，并只制作 / 安装验证所选平台；PR 和 v 标签始终完整四平台。Cargo、缓存、依赖、签名与原测试断言不降级，完整十脚本内容保留。

## 云端结果

首轮 checks [40660729384](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40660729384) 的 preflight 为 12 秒，浏览器最小冒烟 job 为 58 秒，Linux / ARM 检查分别 164 / 159 秒，未执行安装包步骤。Windows 在既有 `successful_switch_merges_concurrent_account_changes` 回归失败：20ms / 80ms 定时假设没有保证操作先取得旧配置。保留全部原断言，改用测试后端 Notify 门闩和已进入操作的条件进行确定同步；相关字段与等待仅在 cfg(test) 下编译，不更改已发布产品逻辑。该首轮运行不作为完整通过成绩。

修正后的源码 `59ea9a84f22ca415aa099a6ba7eb05720c87372d` 在 [checks 40662010888](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40662010888) 首次运行全部通过；各平台保留原回归且打包步骤均跳过：

| job | 总秒数 | 范围 |
| --- | --- | --- |
| preflight | 40 | 格式、前端类型 / 单元 / 构建入口 |
| Linux x64 | 172 | 四平台各自的原生与认证回归 |
| Windows x64 | 198 | 同上 |
| macOS arm64 | 142 | 同上 |
| macOS Intel | 296 | 同上 |
| 独立浏览器 | 59 | 最小浏览器冒烟 |

前置 40 秒与最慢原生 job 296 秒合计约 5.6 分钟，未包含 job 间调度间隔；旧样本最慢 job 为 9.5 分钟，且包含安装包和完整验收。该比较反映省去开发反馈路径中的打包工作，源码、范围和运行环境有差异，不能视为受控编译基准或固定提速比例。此次 [Mock CI 40662010849](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40662010849) 与 [Community 40662010846](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40662010846) 均通过，涵盖新增策略及门禁合同。

同一提交手动选择 `windows-x64` 的 [40662975594](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40662975594) 最终通过：Windows job 394 秒并完成安装包、原生冒烟与安装验收；完整浏览器 job 325 秒且快速冒烟跳过；其他平台执行原回归并跳过安装包。实际只产生 Windows 安装包 artifact 与 Linux 浏览器预览 artifact。

该次首次运行的 macOS ARM `chromium_cdp_full_cas_login_and_logout_fixture` 返回“Chromium 调试操作失败”，随后仅重跑同一 SHA 的失败 job，138 秒通过。错误根因尚未确定，原失败保留，没有改认证库、断言或超时；该次重试结果不用于计算干净的整体耗时。Windows 与完整浏览器均在首次运行通过。

正式 [v0.2.4 发布](desktop-release-0.2.4.md) 使用此次调整之前已验证的发布工作流；新 CI 的标签强制完整策略由合同检查，不将该次旧工作流发布冒充新流程实跑。本机只做源码、链接和格式等静态核对，软件测试、编译与安装验收全部由云端执行。
