# 参与贡献

[返回导航](Home.md) · [隐私与反馈](Privacy-and-Reporting.md)

贡献流程、分支选择、验证命令和 PR 要求唯一维护在 [CONTRIBUTING.md](https://github.com/wide-sky-with-me/ysu_net/blob/main/CONTRIBUTING.md)。模块职责与 mock 测试见 [开发说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/development.md)。

## 从可验证的小改进开始

使用文档的错误、缺少的排障说明、脱敏复现与对应回归测试，都可以帮助项目发展。先搜索已有 Issue / Discussion，说明目标版本和预期行为，再提交聚焦一个问题的改动。

从 `main` 创建聚焦问题的开发分支，说明目标正式版或开发构建；同样显示 0.2.1 不等于相同源码。桌面是 Tauri / Rust，CLI 的 Python 环境独立维护，不存在 Python `gui` 可选依赖。构建、依赖解析、产品测试与打包只在独立构建分支的 GitHub Actions 执行，不在本机运行 Cargo/Rust、前端生产构建或产品测试；云端失败继续修云端，不回退本机。前提和产物核验见[云端构建说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/tauri-desktop.md#构建前提)。

## 文档与 Wiki

Wiki 的审查源在 [docs/wiki](https://github.com/wide-sky-with-me/ysu_net/tree/main/docs/wiki)，只维护简短入门与导航；命令 / 参数、更新信任和运行语义分别链接各自唯一文档。通过 PR 修改源文件，纯文档修改只做静态链接、锚点与脱敏检查；维护者复核后再同步 Wiki，步骤见[社区维护说明](https://github.com/wide-sky-with-me/ysu_net/blob/main/docs/community-maintenance.md)。源码合入、Wiki 同步与正式 Release 是不同操作，不因合入主分支宣称发布。

公开示例仅使用占位数据。遵循 [社区行为约定](https://github.com/wide-sky-with-me/ysu_net/blob/main/CODE_OF_CONDUCT.md)，不要求真实凭据，不承诺尚未验证的能力或维护排期。交付时分别列明静态检查、云端 CI、安装运行及真实校园网验收；旧报告、Mock、公开签名夹具与普通安装都不能替代真实原位升级成绩。
