# 桌面链路调试记录云端验收

日期：2026-10-28。状态：开发候选四平台检查通过，Windows 测试包已下载校验；尚未正式发行，也未取得出错 Windows 的新现场采样。

当前使用合同归[调试指南](debug-recording.md)，设计原因归[决策](../.agents/notes/implemented/desktop/2026-10-28-opt-in-auth-recording.md)。本页只记录本轮源码、产物与实际验证。

## 最终源码与门禁

最终代码提交为 `6f27ff8eed90a9ab6e04d0d52d4faa69fe02b183`，在独立分支 `build/debug-recording-fix-20261028` 构建，随后将相同提交快进至 main。当前包版本仍为 0.2.3，不能据版本号把开发包与正式标签产物混同。

| 运行 | 实际结果 |
| --- | --- |
| [Native 40654179654](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40654179654) | Windows x64、Linux x64、macOS arm64 / x64 构建、原生 / 安装验收及独立浏览器作业全部成功 |
| [Headless 40654179461](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40654179461) | 同提交四平台认证库、探针回归、输入验收与二进制构建全部成功 |
| [Mock 40654179454](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40654179454) | Python 回归与分发检查成功 |

Windows / Linux 的 Svelte 检查均为 0 error / 0 warning，前端 280 项通过。Windows 常规认证库 126 项通过，另有 7 项 Chromium 认证夹具单独执行通过，原生运行器 205 项通过；Linux 对应为 131 项、单独 7 项与 213 项。平台条件测试不同，不以某个平台的数量代表全部平台。

新增回归实际执行了发送 / 响应体读取失败区分、取消终止、错误原文不外泄、文件进行中可读、停止 / 新记录代际、8 MiB 限制、五份保留、写入失败与 Unix 权限 / 链接拒绝。演示模式拒绝创建调试文件，原 IPC 参数检查保留并覆盖新增空参数命令。

本机只执行文档链接、社区规则与 `git diff --check` 等静态核对，以及云端产物下载 / 摘要校验；未运行本机 Cargo、rustfmt、前端生产构建或产品测试。

## 首轮失败与修正

首次完整候选 `e017ca0413891854d5f42a10474cd7524c856f8a` 的 [Native 40653201250](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40653201250) 在 Linux / macOS ARM 的既有 `account_switch_preserves_typed_portal_failure_after_successful_recovery` 回归中出现栈溢出，随后取消剩余作业；该运行不是通过成绩。同源 [Headless 40653201377](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40653201377) 虽四平台通过，也不能替代原生 Worker 检查。

追踪包装增大了嵌套异步 Future 的栈占用，已由非 async 入口把操作 Future 装箱后再进入追踪 scope，保留原账号池断言和默认测试栈，没有修改 `RUST_MIN_STACK`、认证预算或工作流门槛。随后候选的 [Headless 40653871884](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40653871884) 因函数签名的 rustfmt 排版失败，按云端差异修正。最终上述完整门禁重新执行并通过，包括原来溢出的账号池回归。

## Windows 测试产物

来源为最终 Native 运行的 [rust-desktop-windows-x64 artifact](https://github.com/wide-sky-with-me/ysu_net/actions/runs/40654179654/artifacts/12801366263)。下载后核对 GitHub 返回的 ZIP 摘要，再提取唯一 NSIS 安装器和原生 exe；只重命名安装器便于区分，字节不变。

| 文件 | SHA256 |
| --- | --- |
| artifact ZIP | `7f4b08d3981d8a59ecf9e6c3311617dae56c73f248f07689039db7fd1db45195` |
| NSIS 安装器 | `d05e52e05619d6fb2cb2f440a3e8ac82cdb50df14b88b11737ff1c33dfae9567` |
| 原生 ysu-net.exe | `8c1ada50d1e0fe2afc8ea4287889a1a70891eef69b1738ae3088bb2c1c35e953` |

Windows 安装 / 卸载和从安装位置运行的冒烟在云端执行；本机未安装该包或启动 GUI。本次没有新标签、正式 Release、生产更新签名或差分附件。正式 0.2.3 的公开资产与签名仍归[原发布记录](desktop-release-0.2.3.md)。

## 剩余范围

需要用户在出错的 Windows 开启记录后，重新复现查询 / 登录 / 退出，才能继续判断原 HTTP captive 请求的连接、读取或解码失败。云端使用合成数据与隔离文件系统，不代表本机真实断网过程已验收；本功能提供证据，不把未知状态改判在线，也未据此修改密码、DNS、HTTP 跳转边界或 TLS 校验。

本轮忽略目录 `build/debug-recording-20261028/` 保存源码 / 格式化身份、云端摘要、测试摘录与校验后的 Windows 产物；认证原文和真实配置不在本轮提交中。
