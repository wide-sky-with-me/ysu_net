# 社区入口与 Wiki 维护

[返回首页](../README.md) · [文档导航](README.md) · [贡献指南](../CONTRIBUTING.md) · [隐私与脱敏规则](security.md)

本页说明仓库社区文档、Issue/Discussion 表单以及 `docs/wiki/` 的维护与同步流程。

---

## 表单与文档静态检查

修改公开文档、Wiki 源文件或 `.github/` 下的表单模板后，可在本地运行静态检查脚本，自动核验内部 Markdown 链接、标题锚点、表单字段以及敏感信息脱敏规则：

```bash
python3 scripts/check_community.py
git diff --check
```

对应的 GitHub Actions 工作流 [`.github/workflows/community.yml`](../.github/workflows/community.yml) 也会在每次提交与 PR 时自动执行该检查。

---

## 同步 GitHub Wiki

项目 Wiki 的受审源文件统一保存在仓库 [`docs/wiki/`](wiki/Home.md) 目录中。更新 Wiki 时请先修改 `docs/wiki/*.md` 并通过检查，再使用 [`scripts/publish_wiki.py`](../scripts/publish_wiki.py) 导出到独立的 Wiki Git 仓库：

```bash
wiki_dir="$(mktemp -d)/ysu-net-wiki"
git clone https://github.com/wide-sky-with-me/ysu_net.wiki.git "$wiki_dir"
python3 scripts/publish_wiki.py "$wiki_dir"
git -C "$wiki_dir" diff --check
git -C "$wiki_dir" diff --stat
```

核对导出的差异无误后，在 `$wiki_dir` 中提交并推送至 Wiki 仓库默认分支。
