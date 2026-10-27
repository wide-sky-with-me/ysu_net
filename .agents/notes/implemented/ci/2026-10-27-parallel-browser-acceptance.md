# 完整浏览器验收与原生矩阵并行

日期：2026-10-27<br>
状态：已通过新 Mock、四平台 Native 与完整浏览器验收；SDK 取消 / 定向复跑使本轮不构成稳定提速基准；无新标签或正式发行<br>
范围：Tauri CI 排程及其合同，不改 Cargo / profile / cache / target、产品行为或验收门槛

## 背景与局部替代

[基线记录](../../../../docs/ci-parallel-acceptance-2026-10-27.md)显示旧 Linux job 的 594 秒中有 300 秒是完整前端浏览器验收；这不是 594 秒纯 Rust 编译。先前只有构建慢的调查建议，没有已实施的提速成绩。

选择先缩短串行关键路径，不削测试、不延长超时或改为 debug。局部替代旧“先 UI 验收再原生打包”的排程：UI 失败可能不再提前阻止其他原生工作消耗算力，但正式交付仍须全部门槛通过。

## 选择与代价

- 单独的 Linux `browser-acceptance` 与四目标 `build` 并行，彼此无 needs。完整十脚本 run 块逐字搬迁，顺序、参数、输出、回环限制、严格端口、有界等待与 trap 清理不变；不是删除或抽样验收。
- 新 job 自备 Node / uv、锁定依赖、前端 build、字体与 ffmpeg，并检查可执行 Chrome；失败仍 always 保留独立证据。原生各平台的前端 / Rust / Chromium、Native、安装、签名和公共工具门槛保留，新 job 不接触签名 Secret。
- 正式 release 同时依赖 build 与 browser-acceptance，任一失败或取消都不能发布，不用 always / continue-on-error 绕过；format-only 同时跳过两条产品 job，仅保留原格式化路径，原 45 分钟产品 job 上限不减。

额外 job 会重复 Node / uv / 前端 build 和字体 / ffmpeg 准备；并行失败可能比串行更耗 runner，排队与 runner 波动也可能抵消收益。理想模型只是 `max(412 秒, 新 browser job 含准备的耗时)`，不是承诺节省 300 秒或固定百分比，也不表示 Rust 编译本身变快。

Cargo dev-fast / profile、cache key 和共享 target 曾被考虑，但本阶段暂缓；避免同时引入缓存失效、路径及验收配置新变量。基线只有 metadata，无法据此判冷 / 暖缓存；不把构建打包步骤全部归因于 Rust。

## 实现、合同与验证

[工作流](../../../../.github/workflows/tauri.yml)是排程实现；[完整搬迁与门禁合同](../../../../tests/test_ci_performance.py)固定完整 run 块、并行关系、format-only、双发布依赖、证据与未削减项；[既有工具合同](../../../../tests/test_ci_tools.py)保留工具 / 验签要求并同步双依赖。

当前 CI 语义唯一归[开发说明](../../../../docs/development.md#tauri-ci-并行门禁)，基线与实际结果归[本轮记录](../../../../docs/ci-parallel-acceptance-2026-10-27.md)。新候选 `7c876513` 通过 Mock 和全部五条验收门禁，未复用旧 `2bb` 成绩；Linux 首轮 SDK 慢下载取消后只复跑该目标，成功结果来自同 SHA 两次 attempt，不把整体耗时当干净性能基准。本机仅静态文档与现成 metadata 核对，未运行合同测试、产品、浏览器、格式化或构建，正式 tag / 发布路径未实跑。
