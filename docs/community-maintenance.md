# 社区入口与 Wiki 维护

[返回首页](../README.md) · [贡献指南](../CONTRIBUTING.md) · [隐私规则](security.md)

## 各入口的职责

`README` 负责版本选择与入门；`docs/usage.md` 负责完整命令与配置；对应发布标签的桌面文档负责桌面版本行为。Wiki 是面向新用户的导航、简短入门和排障入口，源文件在 `docs/wiki/`，不复制维护另一套完整参数表。

Issue 收集可复现故障和明确需求；Discussion 中 `Q&A` 用于问答、`Ideas` 用于开放方案、`Announcements` 用于公告、`Show and tell` 用于脱敏体验分享。不要承诺未验证的能力或固定响应时间。私密漏洞报告用于凭据泄漏与安全缺陷，流程见 [SECURITY.md](../SECURITY.md)。

## 表单与检查

GitHub 的 Issue 与 Discussion 表单必须存在于默认分支才会启用；Discussion 文件名按分类 slug 对应 `q-a.yml`、`ideas.yml`、`show-and-tell.yml`。表单使用 JSON 写法，这是 YAML 的兼容子集，可直接使用 Python 标准库验证，无新增依赖；修改时保留这种写法。

```bash
python3 scripts/check_community.py
python3 -m unittest discover -s tests -p test_community.py -v
git diff --check
```

检查涵盖必要社区文件、表单关键字段、必填脱敏确认、本地 Markdown 链接/锚点和常见敏感内容规则。报告只显示规则、路径与行号，不回显匹配值。外部 URL、GitHub 实际表单渲染与语义仍须单独核对；规则扫描不代替人工复核。

`.github/workflows/community.yml` 在相关文档和表单改动时执行上述离线检查，只申请 `contents: read`。它不自动访问校园网、提交凭据、修改 Wiki 或发布内容。

## Wiki 首次初始化

GitHub 的 `has_wiki=true` 仅开启功能；首次建立独立 Wiki Git 仓库需要在 [Wiki 新建页](https://github.com/wide-sky-with-me/ysu_net/wiki/_new) 保存一次 `Home`。初始化前 `git clone ...wiki.git` 会返回仓库不存在。GitHub API 的仓库内容接口不是 Wiki 页面接口，见 [官方 Wiki 文档](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages#cloning-wikis-to-your-computer)。

初始化时只填公开简介或项目链接，无需提交真实配置、日志或凭据。编辑权限保持仅协作者；更广泛贡献通过源文档 PR 审查。

## 同步已审查页面

在源码仓库根目录执行，Wiki 克隆放在源码目录之外；以下操作保留额外已有页面，不删除远端内容：

```bash
wiki_dir="$(mktemp -d)/ysu-net-wiki"
git clone https://github.com/wide-sky-with-me/ysu_net.wiki.git "$wiki_dir"
python3 scripts/publish_wiki.py "$wiki_dir"
git -C "$wiki_dir" diff --check
git -C "$wiki_dir" diff --stat
```

`publish_wiki.py` 先检查源文档与 origin，再导出 Markdown 并将页间 `.md` 链接转为公开 Wiki URL；已有未提交改动时会停止。人工复核生成的 diff 和脱敏后，再只暂存本次源页面并提交、推送 Wiki 的默认分支。提交身份使用维护者公开的 GitHub noreply 地址，避免暴露个人邮箱；不要在 remote URL、命令行或脚本中嵌入访问令牌。

同步后逐项核对首页、侧栏、页脚、安装/排障跳转和版本标签链接；比较源文件与导出页面。后续修改先更新审查源，再同步 Wiki，避免两边漂移。

## 发布前人工核对

自 `v0.2.0` 起桌面采用 Tauri，Python CLI 仍独立发布；`v0.1.0` 的 Qt 附件和旧测试标签保留，不覆盖。核对源码版本、Release notes 标题、下载与迁移链接，以及四平台构建、原生和安装验收全部成功这一发布门槛；未取得对应结果前不写成本轮 CI 通过或已经发布。核对已有 Issue 的实时处理状态，区分离线回归、CI 安装检查和校内实测。正文、表单、讨论和 Wiki 都不加入真实账号、会话、设备地址、个人路径或截图；历史验收保持原貌，当前检查单独说明实际范围。
