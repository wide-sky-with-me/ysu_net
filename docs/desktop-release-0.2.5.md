# 桌面 v0.2.5 发布

日期：2026-11-06。状态：正式发布并成为 Latest；四个桌面平台与独立浏览器验收通过，Python 分发包与摘要随附。本页只记录该标签的源码、产物与门禁，不把开发分支上的后续功能算进本版本。

当前行为归[桌面语义](tauri-desktop.md)，发布内容原文见[发布说明](../packaging/release-notes.md)，历史版本导航见[桌面验收](desktop-acceptance.md)。

## 源码与产物

标签 `v0.2.5` 指向提交 `b145a7dbf5120284c55fe93b10a6fc604ef1689b`，版本号在 `pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/Cargo.toml`、`desktop/crates/ysu-auth/Cargo.toml` 与 `tauri.conf.json` 中一致。发布作业先通过四个平台构建、原生安装验收、独立浏览器验收与 Python 回归，再由 `release` 作业汇总附件。

| 附件 | 说明 |
| --- | --- |
| `YSU-Net_0.2.5_windows-x64-setup.exe` | 当前用户 NSIS 安装包，附 `.sig` |
| `YSU-Net_0.2.5_linux-x64.deb` | Debian / Ubuntu 系统包 |
| `YSU-Net_0.2.5_macos-arm64.dmg` / `macos-x64.dmg` | 两个 macOS 架构的磁盘映像 |
| `YSU-Net_0.2.5_macos-arm64.app.tar.gz` / `macos-x64.app.tar.gz` | 软件内更新载荷，各附 `.sig` |
| `ysu_net_login-0.2.5-py3-none-any.whl` / `.tar.gz` | 独立 Python CLI 分发 |
| `latest.json`、`SHA256SUMS` | 更新清单与摘要；清单平台为 `windows-x86_64`、`darwin-aarch64`、`darwin-x86_64` |

沿用 0.2.1 的正式更新公钥，不更换信任锚；本版本没有差分附件，Windows / macOS 的软件内更新使用完整包。

## 门禁结果

| 运行 | 实际结果 |
| --- | --- |
| [Tauri 42201403535](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42201403535) | preflight、四个平台构建与安装验收、`browser-acceptance`、`release` 全部成功 |
| [Mock 42201403529](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42201403529) | Python 回归、分发构建与 wheel 数据检查成功 |
| [Community 42201403637](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42201403637) | 社区文档、链接与表单检查成功 |

同标签的前一个运行 [42198454162](https://github.com/wide-sky-with-me/ysu_net/actions/runs/42198454162) 不是通过成绩：`browser-acceptance` 断言关于页缺少「不更换 0.2.1 正式更新信任锚」一句失败，补回该句后删除并重推标签。最终运行的 Linux 作业曾停在原生 SDK 安装步骤，取消后重跑失败作业完成，取消与重跑不改变产物来源。

## 内容与边界

修复未认证校园网下桌面端无法完成离线门户引导的问题：读取匿名提示页改为一次受限字节交换，只取状态码与正文，失败后不重放凭据。CLI 同步版本号，配置与账号簿保持兼容。

该修复来自单台 Windows 测试机、单一校园网络的现场对照，修复后桌面端登录成功并可重复；其他网络条件与设备未验证。本版本不包含验证码识别——它在标签之后才合入 main，见[验证码核验](captcha-recognition-2026-11-07.md)。更新包签名不替代 Windows 发布者签名或 Apple 签名 / 公证。
