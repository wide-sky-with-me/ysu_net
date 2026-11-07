# 验证码自动识别云端与样本核验

日期：2026-11-07。状态：源码已合入 main 并在四平台云端门禁通过；尚未正式发行，也没有一次「真实登录中完成验证码识别」的端到端记录。

当前行为归[桌面语义](tauri-desktop.md#验证码识别)与[CLI 使用](usage.md#验证码识别)，选择原因归[决策](../.agents/notes/implemented/desktop/2026-11-07-captcha-recognition.md)。本页只记录本轮源码、样本与门禁结果。

## 最终源码与门禁

最终代码为分支 `feat/captcha-desktop-20261107` 的 `461aa7fede52d4fbd9a7002f40fffb1c5d69d9e1`，以 `--no-ff` 合入 main（合并提交 `3b163b0`）。版本号仍为 0.2.5，正式 v0.2.5 产物不含本功能，不能据版本号把开发源码与已发布包混同。

| 运行 | 实际结果 |
| --- | --- |
| [Mock 42385981665](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42385981665) | Python 回归、分发与 wheel 数据检查成功；`test_captcha_solver` 7 项通过，ddddocr 样本用例跳过（默认依赖未装 `--extra captcha`） |
| [Native 42385981629](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42385981629) | Windows x64、Linux x64、macOS arm64 / x64 构建、安装验收与独立浏览器作业全部成功 |
| [Headless 42387637100](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42387637100) | 同提交四平台认证库回归与探针通过（手动触发，路径过滤不含锁文件改动） |

同一分支的前两次运行不是通过成绩，保留作为修正依据：[42224972810](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42224972810) 在 `rustfmt --check` 上失败（`captcha.rs` / `protocol.rs` 排版未提交），[42384770760](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42384770760) 在四平台 `cargo build --locked` 上失败（新增 `tract-onnx` / `image` / `sha2` 未写入 `desktop/src-tauri/Cargo.lock`）。两项分别由 `3539400`、`461aa7f` 修正。
合入 main 后，同一代码在 `618ce80f304fc0bee8e151a3ee04578c50e231df` 上重新全绿：[Mock 42388542302](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42388542302)、[Native 42388541982](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42388541982)、[Headless 42388541968](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42388541968) 与 [Community 42388542028](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42388542028)。其中 Mock 新增独立作业，用 `--extra captcha` 跑 `test_captcha_solver.py`：8 项全过，`test_recognizes_observed_portal_captchas` 不再跳过，三张真实样本均识别正确。
本机只执行文档链接、社区规则与 `git diff --check` 静态核对；未在本机运行 Cargo 构建、产品测试或前端生产构建。

## 样本与识别结果

三张真实抓取的验证码保存在 `tests/fixtures/captcha/`（`nB4f.jpg`、`TH3C.jpg`、`HTrL.jpg`），每张约 1.7 KB、80x30 JPEG、四位字母数字带对角干扰线，无账号、Cookie 或会话信息。

- Python ddddocr 后端对这三张全部命中，对照组为人工目视答案，比对时不区分大小写。
- 桌面 `tract` 推理对同三张给出与 ddddocr 一致的结果（同样按大小写不敏感比对）；该结论来自一次性本地核验，未写入常规回归——桌面用例需要 `YSU_CAPTCHA_MODEL` 指向模型文件，模型不入包，云端无该文件时用例跳过。
- 单张推理耗时只做过量级观察（十毫秒级），没有形成可复现的基准。

## 未覆盖项

| 项目 | 现状 |
| --- | --- |
| 真实登录闭环 | 没有在校园网未认证状态下用自动识别完成一次完整登录并独立核验在线的记录；现有证据只到「样本能识别」和「识别结果被填入提交」 |
| 连续准确率 | 未做十轮以上的连续登录统计，无法给出识别率 |
| 大小写 | 模型输出全小写，门户是否区分大小写未实测；若区分，需要额外的字重判定 |
| 模型托管 | `common.onnx` 没有稳定的公开下载地址，`download_model()` 只保留了注入 URL 的接口 |
| 桌面入口 | 设置页没有下载 / 启用开关，目前需要在缓存目录自行放置模型 |
| Browser 模式 | 未接入，验证码仍返回需人工处理 |
| CI 覆盖 | ddddocr 样本用例已纳入 Mock 作业的独立步骤，真实执行；桌面推理用例需要模型文件，云端仍跳过 |
