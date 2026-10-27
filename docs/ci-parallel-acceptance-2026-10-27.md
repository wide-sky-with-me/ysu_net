# 2026-10-27 CI 浏览器验收并行：基线与验收结果

状态：CI-only 候选已通过 Mock、四平台 Native 与独立浏览器验收；Linux SDK 慢下载经取消、同 SHA 定向复跑后通过，本轮不是干净的整体提速基准。无新标签或 Release。当前行为归[开发说明](development.md#tauri-ci-并行门禁)，原因归[并行决策](../.agents/notes/implemented/ci/2026-10-27-parallel-browser-acceptance.md)。

## 问题与证据来源

本轮针对小功能迭代的构建反馈慢；此前只有调查建议，未实施这些排程优化。基线产品源码为 `2bb9589e8526f681ab4616124d8f1f10bf2ab97c`，[Native 运行 40457529662](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40457529662)的成功只属于旧排程，不能沿用作本轮通过。

安全 CI metadata 留存在本地 `build/portal-trace-20261027-111/candidate-workflows.json`，不是 fresh checkout 必须可用的附件；以下摘要与公开 run 身份为持久证据，不链接私有会话或复制长日志。耗时按 metadata 中各 job / step 的完成减开始时间计算，不含未报告的排队时间。

## 旧基线：不是纯 Rust 编译计时

| 目标 | job 总秒数 | 前端浏览器验收 | Rust 测试步骤 | 构建 / 打包步骤 | cache 步骤 |
| --- | --- | --- | --- | --- | --- |
| Linux x64 | 594 | 300 | 35 | 100 | 33 |
| Windows x64 | 382 | 跳过 | 85 | 129 | 43 |
| macOS ARM64 | 309 | 跳过 | 53 | 136 | 30 |
| macOS Intel | 412 | 跳过 | 70 | 164 | 67 |

“构建 / 打包”对应旧普通原生 bundle 命令步骤，包含混合工作，不能全算 Rust 编译；Rust 测试步骤本身也不是独立编译器基准。cache 步骤时长不证明命中率或冷 / 暖缓存，未用这些 metadata 推导其状态。

## 本轮改动与静态核对

[工作流](../.github/workflows/tauri.yml)将原 Linux 完整浏览器验收 run 块搬至独立 `browser-acceptance`，与四平台 `build` 并行，不互设 needs。十脚本的顺序、参数、输出、回环限制、strictPort、启动等待及 trap 未削减；新 job 仍准备 Node / uv、锁定依赖、前端 build、字体 / ffmpeg 和可执行 Chrome，并 always 上传独立验收证据。

四平台 Chrome 认证夹具、Native / 安装验收、原生签名、公共差分工具、locked 检查和包证据保留。新 web job 无签名 Secret；正式 release 仍限定 v 标签，且须 build 与 browser-acceptance 都成功，失败 / 取消不能绕过。format-only 跳过两条产品 job，原格式化路径保留；产品 job 的 45 分钟上限不减。

[新增排程合同](../tests/test_ci_performance.py)固定完整 run 字节、并行 / format-only / 双依赖、证据及保留门槛；[工具合同](../tests/test_ci_tools.py)同步双依赖但不删除原工具与验签要求。文档整理阶段仅阅读源码及静态核对，未在本机运行这些合同测试；云端状态单列于下表，不等同正式标签发布路径已通过。

## 收益模型与暂缓项

移出旧 Linux 的 300 秒后，旧矩阵其余最长目标为 Intel 的 412 秒；理想关键路径模型为 `max(412 秒, 新 browser job 含准备的耗时)`。新 job 额外的 Node / uv / build / 字体 / ffmpeg 准备、排队及 runner 差异均需实测，不能承诺节省 300 秒或固定百分比，也不宣称 Rust 编译时间已变快。

并行意味着 UI 失败时其他原生工作可能已消耗算力，换取较短的成功关键路径而非更少验收。Cargo dev-fast / profile、cache key / 共享 target 仅考虑后暂缓，本阶段没有实施或完成这些优化。

## 新候选 after：跨 attempt 的同源验收

| 项目 | 当前证据 |
| --- | --- |
| CI-only 候选 SHA | `7c876513bdcace8a0dbf2b8925412cf15481a506`，仅三 CI 路径 |
| Mock | [40497389880](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40497389880) success，包含新增排程合同 |
| Native 四平台 build 与新 browser job | [40497389816](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40497389816) attempt 2 success；只重跑 Linux，其余四条成功 job 保留首轮证据 |
| 整体关键路径提速结论 | 不据本轮计算提升比例：SDK 下载、取消与复跑污染了整体耗时对照 |
| 正式 tag / 双依赖发布路径 | 仅静态核对，本轮未发新 tag / Release |

成功 job 的实际时长如下；来自两个 attempt，仅描述验收，不能合并冒充同条件性能基准：

| 成功 job | 总秒数 | 补充 |
| --- | --- | --- |
| Linux x64 | 1009 | 复跑 SDK 746 秒、Rust 测试 39 秒、构建 / 打包 108 秒 |
| Windows x64 | 415 | 首轮成功 |
| macOS ARM64 | 349 | 首轮成功 |
| macOS Intel | 655 | 首轮成功 |
| 独立浏览器验收 | 384 | 其中原完整验收步骤 326 秒；与 Windows / macOS job 实际重叠 |

首轮 Linux 在编译前的 SDK 准备持续 1106 秒仍未完成，取消取日志后发现 Ubuntu 镜像包下载缓慢：13.7 MB 包至下一次获取记录约隔 303 秒，随后仍在下载 61.2 MB 字体。没有更改 45 分钟上限、包清单、源码或门槛；同 SHA 仅复跑该目标并通过。复跑 SDK 仍远高于基线 35 秒，因此不能把结果表述为稳定提速，也不能归因于 Rust 编译变慢；首轮取消记录保留。

所有编译、格式化、产品、单元及浏览器验收只在 GitHub Actions；独立静态复核未发现确定门禁弱化。正式 tag / 私钥签名 / 发布未实跑，既有验收、导航采样和发行结论不改写。

## 另项受控认证采样延期

用户选择保持 111 现有连接，本轮仅 8 GET 只读预检；没有下线、登录、换号或改配置，受控认证 cycle 延期，未采集离线登录或完整认证链，不能记成网络已重登或认证验收完成。
