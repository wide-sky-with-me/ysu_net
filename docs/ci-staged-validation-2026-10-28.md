# 桌面 CI 分层：基线与验证

日期：2026-10-28。状态：策略与工作流已补，待云端验证。当前操作归[开发说明](development.md#tauri-ci-并行门禁)，原因归[分层决策](../.agents/notes/implemented/ci/2026-10-28-staged-desktop-validation.md)。

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

待独立构建分支的 checks 与手动 Windows 模式验证后补充。没有新成绩前不宣称已提速。正式 v0.2.4 使用此次调整之前已验证的发布工作流；新 CI 的标签强制完整策略由合同检查，不将该次旧工作流发布冒充新流程实跑。
