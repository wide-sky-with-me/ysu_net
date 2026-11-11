# 参与贡献

欢迎参与改进 **YSU Net** 的文档、反馈问题、补充测试或贡献代码功能。开始前建议先浏览 [文档导航](docs/README.md)、[开发与测试说明](docs/development.md) 和 [隐私与脱敏规则](docs/security.md)。

---

## 反馈与讨论入口

- **程序故障报告**：使用 [问题反馈表单](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=bug_report.yml)，提交前请先搜索已有 Issue。
- **使用问题咨询**：前往 [Discussions / Q&A](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/q-a)。
- **新功能想法**：先在 [Discussions / Ideas](https://github.com/wide-sky-with-me/ysu_net/discussions/categories/ideas) 交流，或提交 [功能建议表单](https://github.com/wide-sky-with-me/ysu_net/issues/new?template=feature_request.yml)。
- **安全与凭据漏洞**：请通过 [私密漏洞报告](https://github.com/wide-sky-with-me/ysu_net/security/advisories/new) 联系维护者（详见 [SECURITY.md](SECURITY.md)）。

---

## 开发与验证约定

1. **双端同步评估**：新增、优化或修复功能时，请同步评估并更新所有受影响的终端（Rust 桌面客户端与 Python CLI），保持功能行为与状态语义一致。
2. **构建与测试**：
   - 本地可运行 Python 单元测试、前端 Vitest 单元测试与社区文档检查：
     ```bash
     PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests
     npm --prefix desktop run check
     npm --prefix desktop test
     python3 scripts/check_community.py
     git diff --check
     ```
   - Rust 编译与四平台桌面打包统一通过 GitHub Actions 云端工作流执行（详见 [Tauri 桌面版说明](docs/tauri-desktop.md#构建前提与持续集成)）。
3. **提交与脱敏**：
   - 每个 PR 聚焦一个明确主题，使用 `feat:`、`fix:`、`docs:` 等清晰提交前缀。
   - 公开提交的代码、测试夹具、日志与截图请遵循 [公开反馈的脱敏清单](docs/security.md#公开反馈的脱敏清单)，只使用虚构占位数据。

参与讨论与代码审查时请遵守 [社区行为准则](CODE_OF_CONDUCT.md)。
