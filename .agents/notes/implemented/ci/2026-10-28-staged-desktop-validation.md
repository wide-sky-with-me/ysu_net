# 开发检查、按需安装包与完整发布分层

日期：2026-10-28。状态：源码已实施，云端验证待完成。范围：桌面 CI 调度，不更改产品、Cargo profile、缓存键、依赖、超时或签名信任。

## 背景与替代范围

[本轮证据](../../../../docs/ci-staged-validation-2026-10-28.md)中同源开发分支的 Intel job 为 572 秒，其中测试步骤 111 秒、编译 / 打包步骤 245 秒；后者的 Cargo release 日志为 220 秒。Windows job 为 405 秒。合入 main 后相同 SHA 又完整打包，Intel 再用 740 秒。它们是 CI 工作而非全部纯 Rust 编译；排队和此前失败修正另计。

此前[并行决策](2026-10-27-parallel-browser-acceptance.md)保留完整浏览器与原生矩阵并行，但每次推送仍制作全部安装器。此次局部替代其“每次推送都完整验收 / 打包”和“两个 job 无前置依赖”的范围；完整浏览器脚本、原生回归、安装 / 签名与发布约束保留。

## 选择

- 无 SDK 的 preflight 先检查两套 Rust 源码格式与前端类型 / 单元 / 构建入口，失败时不再启动四平台 SDK 准备。通过后原生矩阵与浏览器 job 并行，不互相等待。
- 普通分支推送为 checks：四平台认证库、原生 Runtime、真实 Chromium 管道与既有外部回归仍执行；浏览器用现有最小冒烟，不制作安装器。
- 手动 package_target 可选 all、checks 或单一平台。请求任何安装包时都执行原完整十脚本浏览器验收；只有所选平台制作安装器并运行对应原生 / 安装验收。手动默认 all，保留旧手动行为。
- v 标签和 PR 始终 all；事件策略不信任手动输入覆盖。所有包步骤与完整浏览器的 if 还直接包含 tag / PR 强制分支，不依赖 planner 输出放行。正式 release 仍只在 v 标签且 needs build 与 browser-acceptance 均成功后执行，原公钥验签、库存校验与签名 Secret 范围不改。
- 完整十脚本 run 块逐字保留，快速冒烟是另一个互斥入口。checks 不上传伪装为安装包的 artifact；记录范围在 preflight summary 中说明。format-only 仍只运行既有云端格式化任务。

## 替代方案与代价

只提高 CARGO_BUILD_JOBS 或增加缓存内容，可能增加内存、下载与缓存上传；未取得受控比较，未采用。开发改为 debug / 关闭 LTO 会改变产物 profile，本轮也未采用。删掉跨平台 Runtime 或 Chromium 回归会丢失 Windows 管道与文件锁差异覆盖，保留。

绿色完整构建增加一次轻量 preflight；换取失败更早反馈。快速检查不等于原生安装或完整视觉验收通过，必须在请求安装包、PR 或正式标签阶段完成相应门槛。新默认仍受最慢平台的检查影响，不承诺固定加速比例或 Rust 编译器本身变快。

## 实现与验证

[策略](../../../../packaging/ci_build_plan.py)、[工作流](../../../../.github/workflows/tauri.yml)、[策略与门禁合同](../../../../tests/test_ci_build_plan.py)、[保留完整验收合同](../../../../tests/test_ci_performance.py)。当前命令归[开发说明](../../../../docs/development.md#tauri-ci-并行门禁)，实际运行、失败复测与剩余范围归[验收](../../../../docs/ci-staged-validation-2026-10-28.md)。本机仅静态检查，全部测试、浏览器与编译由 GitHub Actions 执行。
