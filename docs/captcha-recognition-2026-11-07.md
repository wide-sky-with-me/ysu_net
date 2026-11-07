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

## 模型托管与桌面入口

模型发布为同一仓库的固定资产 `captcha-model-v1`（54088400 字节，SHA256 与 `MODEL_SHA256` 一致），标签不是产品版本，`--latest=false`，因此不改变 Latest、不触发 `v*` 发布流程。实测该资产可匿名下载，下载结果的摘要与仓库锚点一致。桌面端新增 `captcha_status` / `captcha_download` 两个命令：前者只读磁盘，后者在用户点击时下载、校验、原子替换，并用一个进程内标记拒绝并发重复下载；离线模拟与普通网页不解锁下载。对应界面在“设置 → 认证 → 验证码识别”，尚未在任何真实环境截取验收截图。

## 取样节奏

为取得连续识别率，新增 `packaging/captcha_accuracy.py`：`collect` 按节奏抓取验证码并记录模型输出，`score` 按人工填写的标签统计完全一致与忽略大小写的命中率。2026-11-07 夜间实测该接口对密集请求敏感：20 秒内连续取图 20 次后，后续请求返回空正文，直到约十分钟后仍为空。因此脚本把节奏下限设为 20 秒、默认 30 秒，并在空正文时停止并提示限流；本轮未能完成十轮取样，识别率仍以仓库内三张样本为准。

## 未覆盖项

| 项目 | 现状 |
| --- | --- |
| 真实登录闭环 | 没有在校园网未认证状态下用自动识别完成一次完整登录并独立核验在线的记录；现有证据只到「样本能识别」和「识别结果被填入提交」 |
| 连续准确率 | 取样脚本与节奏限制已就绪，但本轮取样被接口限流打断，仍无十轮以上的连续统计 |
| 大小写 | 模型输出全小写，三张样本目视为混合大小写；门户是否区分大小写未实测，若区分则识别会失败 |
| 模型托管 | 已固定为 `captcha-model-v1` 资产并校验摘要；换模型需同步更新锚点与字符集 |
| 桌面入口 | 设置页已提供状态与下载按钮，但界面本身还没有真实环境截图或人工点击验收记录 |
| Browser 模式 | 未接入，验证码仍返回需人工处理 |
| CI 覆盖 | ddddocr 样本用例已纳入 Mock 作业的独立步骤，真实执行；桌面推理用例需要模型文件，云端仍跳过 |
