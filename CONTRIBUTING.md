# 参与贡献

欢迎改进使用文档、提交脱敏反馈、补充测试或贡献代码。先阅读 [文档导航](docs/README.md)、[使用说明](docs/usage.md)、[支持与反馈](SUPPORT.md) 和 [敏感信息规则](docs/security.md)。

## 选择入口

- 可复现故障：使用 [问题反馈表单](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=bug_report.yml)，先搜索已有 Issue，补充同一问题而不是重复开帖。
- 使用问答：到 [Q&A](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a)，解决后可将有效回复标为答案。
- 尚在讨论的想法：到 [Ideas](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/ideas)；明确需求后再使用功能建议表单。
- 凭据泄漏或安全缺陷：通过 [私密漏洞报告](https://github.com/wide-sky-with-me/ysu_net/security/advisories/new) 联系维护者，见 [SECURITY.md](SECURITY.md)。

## 版本与分支

自 **v0.2.0** 起，桌面采用 Tauri，覆盖 Windows / Linux / macOS；Linux Python CLI 独立维护。正式发行与当前同版本开发树的区别见[首页发行状态](README.md#发行与候选状态)，不因合并到 `main` 就宣布新版本。`v0.1.0` 的 Qt 附件与旧测试标签仅供历史复现，不覆盖。新改动以 `main` 为基线创建分支，注明目标版本和验证范围；正式发布仍要求四平台构建、原生和安装验收成功。

## 开发验证

编译、打包与产品测试仅在 GitHub Actions runner 执行，云端失败不回退本机编译。本机可阅读源码、编辑文件和执行文档/差异静态检查。以下 Python 3.12、uv 与 unittest 命令供 runner 使用：

```bash
uv sync --locked --extra browser
uv run ysu --help
uv run --extra browser python -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
git diff --check
```

连接相关测试使用 mock，不需要真实账号或校园网；DNS 回退的 TLS 集成类仅允许回环连接，用于核对证书身份，仍在云端运行。默认诊断和查看帮助保持无联网副作用。新增行为补对应回归测试；涉及真实网络的验证独立记录已测范围与未测范围，使用“测试账号”等泛化称呼。更多模块与验证约定见 [开发说明](docs/development.md)。

桌面开发使用 Node、Rust 和平台 SDK，命令以 [Tauri 构建与验证](docs/tauri-desktop.md#构建前提)为准；不存在 Python `gui` 可选依赖。Python 的 `browser` 是 CLI 浏览器认证依赖，`desktop-test` 仅供外部验收工具，不是桌面客户端运行时。

社区文件和 Wiki 源文档可单独检查，无需执行登录、下线或启动服务：

```bash
python3 scripts/check_community.py
git diff --check
```

## 提交与审查

每个 PR 聚焦一个问题，说明改了什么、为什么、验证命令与结果，以及尚未验证的场景。使用 `docs:`、`fix:`、`feat:` 等提交前缀；纯文档改动不宣称通过真实校园网回归。行为变更同步更新其所属文档，不重复维护同一份完整命令表。带日期的验收保留当时结论，新增事实写入新的记录并链接；界面截图使用合成数据，注明[来源与摘要](docs/screenshots/README.md)。

真实账号、密码、Cookie、Token、会话标识、HAR、原始认证页面和配置文件均留在本机。日志与截图分享前按 [脱敏清单](docs/security.md#公开反馈的脱敏清单) 人工检查；测试数据只能使用虚构占位值。不要把个人联系方式、真实设备地址或本机绝对路径写入提交、Issue 或 PR。

## Wiki 维护

Wiki 页面的受审查源文件位于 [docs/wiki](docs/wiki/Home.md)。修改源文件、通过社区检查后，由维护者同步到独立的 Wiki Git 仓库；不要在两边分别修改同一事实。发布步骤和首次初始化要求见 [社区维护说明](docs/community-maintenance.md)。

参与讨论与审查时遵循 [社区行为约定](CODE_OF_CONDUCT.md)。维护者按可复现性和影响范围处理反馈，不承诺固定回复时间。
