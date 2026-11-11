# 参与贡献

[返回导航](Home.md) · [隐私与反馈](Privacy-and-Reporting.md)

欢迎参与改进文档、反馈问题、补充回归测试或提交代码功能。完整的开发流程、测试命令与提交规范见 [CONTRIBUTING.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/CONTRIBUTING.md) 与 [开发说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/development.md)。

## 贡献方式

1. **反馈与改进建议**：先搜索已有 Issue 或 Discussion，说明使用版本、系统环境与复现步骤。
2. **代码与测试开发**：从 `main` 创建分支，保持改动聚焦单一主题，并补充对应的离线单元测试；跨平台编译与安装包验收通过 GitHub Actions 执行。
3. **文档与 Wiki 维护**：Wiki 页面源文件统一维护在仓库的 [docs/wiki/](https://github.com/wide-sky-with-me/ysu_net/tree/main/docs/wiki) 目录中。修改文档后可运行 `python3 scripts/check_community.py` 检查链接与脱敏规则，合入后再按 [社区维护说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/community-maintenance.md) 同步至 GitHub Wiki。
