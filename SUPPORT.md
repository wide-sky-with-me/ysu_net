# 支持与反馈

本项目是社区维护的燕山大学校园网工具，不是学校或运营商的官方支持渠道。账号状态、套餐、计费和门户服务异常请向对应服务方查询；工具故障与使用问题可在本仓库反馈。

## 先确认版本

- Linux 命令行版：从 `main` 安装，见 [README](README.md) 和 [使用说明](docs/usage.md)。反馈时提供安装来源及提交短哈希。
- Windows / Ubuntu 桌面版：从 [Releases](https://github.com/wide-sky-with-me/ysu_net/releases) 选择明确版本；`v0.1.0` 包含自动重连状态刷新修复，见 [对应版本的桌面说明](https://github.com/wide-sky-with-me/ysu_net/blob/v0.1.0/docs/desktop.md)。
- Wiki 提供 [入门导航](docs/wiki/Home.md)；命令与参数以使用版本对应的文档为准。`main` 已包含 `ysu-gui` 入口，源码运行需安装 `gui` 可选依赖。

## 选择反馈渠道

| 事项 | 入口 |
| --- | --- |
| 安装、配置或用法问答 | [Discussions / Q&A](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a) |
| 可复现的程序故障 | [Issue 问题反馈](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=bug_report.yml) |
| 明确的功能需求 | [Issue 功能建议](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=feature_request.yml) |
| 待讨论的方案 | [Discussions / Ideas](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/ideas) |
| 版本公告和社区规则 | [Discussions / Announcements](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/announcements) |
| 凭据泄漏或安全缺陷 | [私密漏洞报告](https://github.com/wide-sky-with-me/ysu_net/security/advisories/new)，见 [SECURITY.md](SECURITY.md) |

## 一份有效的反馈

说明操作系统版本、工具版本或提交号、命令行/桌面版、API/浏览器认证、运营商、是否接入校园网、复现步骤、预期和实际结果。不要提供账号、密码、IP、MAC、姓名、宿舍/设备位置或联系方式。可附人工脱敏后的最少错误片段；不要上传完整配置、原始响应、HAR 或认证截图。

命令行排障先运行 `ysu doctor`，它只检查本地；在校园网内确需查询时再运行 `ysu doctor --network`。两个命令均不登录、不下线、不切换运营商。即使普通展示隐藏了部分字段，完整输出仍须人工复核，见 [脱敏清单](docs/security.md#公开反馈的脱敏清单)。

桌面自动重连后仍显示未连接的 [Issue #1](https://github.com/wide-sky-with-me/ysu_net/issues/1) 已在 `v0.1.0` 修复：登录成功后立即独立查询并同步界面状态。旧测试版用户可先手动刷新，再升级；修复有离线引擎与 Qt 窗口回归证据，校内网络实测需按当前设备另行确认。若新版仍出现此现象，请在原 Issue 补充脱敏版本和复现信息。

不要仅以“有网/没网”判断认证成功：操作返回、独立状态查询、界面显示和外网连通性应分别描述。维护者可能先请求补充信息，再确认复现；Issue 关闭原因会按实际验证说明，固定响应期限不作承诺。
