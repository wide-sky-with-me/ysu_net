# 验证码识别改为可选本地推理

日期：2026-11-07。状态：源码已实施并合入 main，未随 v0.2.5 发布；当次证据与未覆盖项归[验证码验收记录](../../../../docs/captcha-recognition-2026-11-07.md)。范围：Python CLI 默认 API 与三平台共用 Rust 认证库的 CAS 验证码分支；Browser 模式与远端识别服务不在本次实现内。

## 证据与选择

门户验证码接口是 CAS 登录页的 `getCaptcha.htl`，实测返回 80x30 JPEG、四位字母数字、带一条对角干扰线。此前两个产品在 `captchaRequired` 为真时一律停在「需人工处理」：CLI 在非终端环境直接抛 `InteractionRequired`，桌面返回交互错误。守护与托盘场景没有终端，这类状态只能靠人工从门户登录一次再恢复。

选择随包引入 ddddocr 的 CRNN 模型（`common.onnx`，MIT）而不引入其 Python 运行时：桌面端用 `tract` 做纯 Rust 推理，不随安装包分发原生推理库，也不需要用户另装 Python。Python CLI 侧直接把 ddddocr 作为可选依赖（`[project.optional-dependencies] captcha`），因为它的模型和预处理已封装在包内，自行复刻只会多一份需要同步的字符集。

字符集必须用 ddddocr 的 `CHARSET_BETA`（8210 项，含空白类），共约 56 KiB，编译进 `ysu-auth`；换模型而不换字符集会让输出整体错位。推理路径为灰度 → 按高度 64 等比缩放 → `(x/255-0.5)/0.5` → CNN-LSTM → 贪心 CTC（`BLANK = 0`）。

未选择把模型放进安装包：模型约 52 MB，而这是一项可选项，会让所有用户为少数人的场景付下载与磁盘成本，也与「不装就不能用」的人工兜底冲突。未选择调用云端 OCR 服务：验证码图片属于认证资料，交给第三方既增加一个可用性依赖，也把认证图像移出本机。未选择 Tesseract：需要系统级二进制，字符白名单与扭曲字体的识别质量都不如专用模型。未选择在 Python 端自研推理：`onnxruntime` 会为每个平台引入原生依赖，收益只是少装一个可选包。

## 实现与验证

Python 入口是[captcha.py](../../../../src/ysu_net/auth/captcha.py)：`solve()` 按 `YSU_CAPTCHA_SOLVER`（`auto` / `remote` / `ddddocr` / `tesseract` / `manual`）依次尝试后端，结果必须恰好四位字母数字，否则视为未识别；`available()` 只回答「除人工输入外是否还有可用后端」，供调用方在非终端环境保持原合同——没有后端时仍不发起图片请求，直接要求人工介入。图片仍按原行为落盘到工作目录的 `captcha.png`，供人工核对或改用手工输入。接线在[api.py](../../../../src/ysu_net/auth/api.py)，只在 `captchaRequired` 为真时取图，不改变登录方式判定、加密与提交路径。

桌面入口是[captcha.rs](../../../../desktop/crates/ysu-auth/src/captcha.rs)：模型不入包，`ready_model()` 只在磁盘上已有模型时返回路径（`YSU_CAPTCHA_MODEL` 指定文件，或缓存目录 `YSU_CAPTCHA_DIR` 默认 `%LOCALAPPDATA%` / `XDG_CACHE_HOME` / `HOME` 下的 `ysu-net/captcha/common.onnx`）。`download_model()` 走显式请求、校验 `MODEL_SHA256` 后原子替换，登录路径从不调用它——一次登录绝不触发下载。协议侧[CAPTCHA_ATTEMPTS = 3](../../../../desktop/crates/ysu-auth/src/protocol.rs) 只对提交后正文出现「验证码」的拒绝换图重试，密码错误不进入该分支，避免把口令错误变成连续凭据尝试。

验证：仓库内保存三张真实抓取的验证码（`tests/fixtures/captcha/`），Python 合同测试覆盖自动 / 显式后端的顺序、长度与字符集拒绝、无终端时跳过人工输入、远端错误状态忽略；默认依赖下 ddddocr 用例跳过，带 `--extra captcha` 的作业执行真实识别。桌面端在带模型的环境下对同三张图大小写不敏感地得到一致结果；不带模型时该用例跳过，不进入常规回归。

## 后果与限制

默认不启用：模型既不在安装包内，也没有自动下载，桌面端「设置」也还没有下载入口——目前只有在磁盘上自行放置模型后才会自动识别。识别结果只当作一次候选提交，不做「识别成功即认证成功」的推断；认证仍以 CAS 重定向、回调同源和服务动作信封为准。

模型托管地址尚未固定，因此 `download_model()` 暂时没有默认 URL，只保留注入 URL 的接口；推理耗时、连续十轮识别的准确率、以及门户是否区分大小写（模型输出全小写）都还没有实测记录，见验收记录中的未覆盖项。
