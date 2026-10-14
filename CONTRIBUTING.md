# 参与贡献

欢迎改进使用文档、提交脱敏反馈、补充测试或贡献代码。先阅读 [使用说明](docs/usage.md)、[支持与反馈](SUPPORT.md) 和 [敏感信息规则](docs/security.md)。

## 选择入口

- 可复现故障：使用 [问题反馈表单](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=bug_report.yml)，先搜索已有 Issue，补充同一问题而不是重复开帖。
- 使用问答：到 [Q&A](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a)，解决后可将有效回复标为答案。
- 尚在讨论的想法：到 [Ideas](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/ideas)；明确需求后再使用功能建议表单。
- 凭据泄漏或安全缺陷：通过 [私密漏洞报告](https://github.com/wide-sky-with-me/ysu_net/security/advisories/new) 联系维护者，见 [SECURITY.md](SECURITY.md)。

## 版本与分支

`main` 提供 Linux 命令行工具。桌面客户端当前为 [v0.1.0-beta.1 测试版](https://github.com/wide-sky-with-me/ysu_net/releases/tag/v0.1.0-beta.1)，源码位于 `feat/desktop-gui`，尚未合并至 `main`。改动命令行或社区文档时以 `main` 为基线；涉及桌面客户端时先说明对应版本和目标分支，避免把桌面改动提交到缺少 GUI 的基线。

## 本地开发

项目使用 Python 3.12 及以上、uv、标准库 unittest。命令行开发环境：

```bash
uv sync --locked --extra browser
uv run ysu --help
uv run --extra browser python -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
git diff --check
```

连接相关测试使用 mock，不需要真实账号或校园网。默认诊断和查看帮助保持无联网副作用。新增行为补对应回归测试；涉及真实网络的验证独立记录已测范围与未测范围，使用“测试账号”等泛化称呼。更多模块与验证约定见 [开发说明](docs/development.md)。

社区文件和 Wiki 源文档可单独检查，无需执行登录、下线或启动服务：

```bash
python3 scripts/check_community.py
git diff --check
```

## 提交与审查

每个 PR 聚焦一个问题，说明改了什么、为什么、验证命令与结果，以及尚未验证的场景。使用 `docs:`、`fix:`、`feat:` 等提交前缀；纯文档改动不宣称通过真实校园网回归。行为变更同步更新其所属文档，不重复维护同一份完整命令表。

真实账号、密码、Cookie、Token、会话标识、HAR、原始认证页面和配置文件均留在本机。日志与截图分享前按 [脱敏清单](docs/security.md#公开反馈的脱敏清单) 人工检查；测试数据只能使用虚构占位值。不要把个人联系方式、真实设备地址或本机绝对路径写入提交、Issue 或 PR。

## Wiki 维护

Wiki 页面的受审查源文件位于 [docs/wiki](docs/wiki/Home.md)。修改源文件、通过社区检查后，由维护者同步到独立的 Wiki Git 仓库；不要在两边分别修改同一事实。发布步骤和首次初始化要求见 [社区维护说明](docs/community-maintenance.md)。

参与讨论与审查时遵循 [社区行为约定](CODE_OF_CONDUCT.md)。维护者按可复现性和影响范围处理反馈，不承诺固定回复时间。
