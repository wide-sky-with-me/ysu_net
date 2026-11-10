# 桌面 v0.2.6 发布

日期：2026-11-09。状态：正式发布并成为 Latest；四个桌面平台与独立浏览器验收通过，Python 分发包与摘要随附。本页只记录该标签的源码、产物与门禁，不把后续主分支提交算进本版本。

当前行为归[桌面语义](tauri-desktop.md)，发布内容原文见[发布说明](../packaging/release-notes.md)，历史版本导航见[桌面验收](desktop-acceptance.md)。

## 源码与产物

标签 `v0.2.6` 指向提交 `260de5986bf038f55a235a0fb0ed2571bb2f642d`，版本号在 `pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/Cargo.toml`、`desktop/crates/ysu-auth/Cargo.toml` 与 `tauri.conf.json` 中一致。发布作业先通过四个平台构建、原生安装验收、独立浏览器验收与 Python 回归，再由 `release` 作业汇总附件。

| 附件 | 说明 |
| --- | --- |
| `YSU-Net_0.2.6_windows-x64-setup.exe` | 当前用户 NSIS 安装包，附 `.sig` |
| `YSU-Net_0.2.6_linux-x64.deb` | Debian / Ubuntu 系统包 |
| `YSU-Net_0.2.6_macos-arm64.dmg` / `macos-x64.dmg` | 两个 macOS 架构的磁盘映像 |
| `YSU-Net_0.2.6_macos-arm64.app.tar.gz` / `macos-x64.app.tar.gz` | 软件内更新载荷，各附 `.sig` |
| `ysu_net_login-0.2.6-py3-none-any.whl` / `.tar.gz` | 独立 Python CLI 分发 |
| `latest.json`、`SHA256SUMS` | 更新清单与摘要；清单平台为 `windows-x86_64`、`darwin-aarch64`、`darwin-x86_64` |

沿用 0.2.1 的正式更新公钥，不更换信任锚；本版本没有差分附件，Windows / macOS 的软件内更新使用完整包。

## 门禁结果

| 运行 | 实际结果 |
| --- | --- |
| [Tauri 42583161741](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42583161741) | preflight、四个平台构建与安装验收、`browser-acceptance`、`release` 全部成功 |
| [Mock 42583161813](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42583161813) | Python 回归、分发构建与 wheel 数据检查成功 |
| [Community 42583161778](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42583161778) | 社区文档、链接与表单检查成功 |

同标签的前一个运行 [42580873639](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42580873639) 不是通过成绩：`browser-acceptance` 在 `390x844` 窄视口下命中 `.captcha-setting` 折行重叠检查，修正窄视口横向布局后删除并重推标签。最终运行期间 `Install pinned public delta tools` 与 `setup-uv` 曾遇到 GitHub 下载 504，重跑失败作业后全部通过。

## 内容与边界

正式包含按需[验证码识别](captcha-recognition-2026-11-07.md)（桌面端在“设置 → 认证 → 验证码识别”独立分区按需下载模型，CLI 使用可选组 `captcha` 并由 `ysu doctor` 显示识别就绪状态），精简设置与链路调试面板布局、区分验证码状态读取与模型下载错误分类，并将链路调试轮询收敛为仅在录制开启且窗口可见时执行。

模型不随安装包分发，未下载模型或未装可选依赖时仍按原规则要求人工处理。更新包签名不替代 Windows 发布者签名或 Apple Developer ID 签名 / 公证；macOS 浏览器下载的 `.dmg` 若被 Gatekeeper 隔离提示“已损坏，无法打开”，需清除 `com.apple.quarantine` 扩展属性（见[迁移说明](migration.md#桌面-v020-升级)）。
