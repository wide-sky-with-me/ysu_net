# 参与贡献

[返回导航](Home.md) · [隐私与反馈](Privacy-and-Reporting.md)

贡献流程、分支选择、验证命令和 PR 要求唯一维护在 [CONTRIBUTING.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/CONTRIBUTING.md)。模块职责与 mock 测试见 [开发说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/development.md)。

## 从可验证的小改进开始

使用文档的错误、缺少的排障说明、脱敏复现与对应回归测试，都可以帮助项目发展。先搜索已有 Issue / Discussion，说明目标版本和预期行为，再提交聚焦一个问题的改动。

`main` 当前是命令行主线；桌面改动需说明针对 `feat/desktop-gui` 或发布标签的版本，避免把缺少 GUI 的基线当作桌面开发环境。不要把历史测试数量、CI 安装成功或他人的实测替代为本次验证结果。

## 文档与 Wiki

Wiki 的审查源在 [docs/wiki](https://github.com/wide-sky-with-me/ysu_net/tree/main/docs/wiki)，详细命令继续维护在对应使用文档。建议通过 PR 修改源文件，维护者检查脱敏与链接后同步至 Wiki；具体步骤见 [社区维护说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/community-maintenance.md)。

公开示例仅使用占位数据。遵循 [社区行为约定](https://github.com/wide-sky-with-me/ysu_net/blob/main/CODE_OF_CONDUCT.md)，不要求他人发送真实凭据，也不承诺尚未验证的能力或固定维护排期。
