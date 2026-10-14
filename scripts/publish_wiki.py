#!/usr/bin/env python3
"""Export reviewed Wiki sources into an initialized local Wiki clone."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "wide-sky-with-me/ysu_net"
WIKI_URL = f"https://github.com/{REPO}/wiki"
ALLOWED_REMOTES = {
    f"https://github.com/{REPO}.wiki.git",
    f"git@github.com:{REPO}.wiki.git",
    f"ssh://git@github.com/{REPO}.wiki.git",
}


def main():
    parser = argparse.ArgumentParser(description="导出已审查 Wiki 页到初始化后的本地 Wiki 克隆，不自动提交或推送")
    parser.add_argument("clone", type=Path, help="独立 Wiki Git 仓库目录")
    args = parser.parse_args()
    target = args.clone.resolve()
    if target == ROOT or target.is_relative_to(ROOT):
        parser.error("Wiki 克隆必须位于源码仓库之外")
    if not (target / ".git").exists():
        parser.error("目标不是已初始化的 Wiki 克隆；先在 GitHub 保存 Home 页并克隆")
    remote = subprocess.check_output(["git", "-C", str(target), "remote", "get-url", "origin"], text=True).strip()
    if remote.rstrip("/") not in ALLOWED_REMOTES:
        parser.error("目标 origin 与项目 Wiki 不一致")
    status = subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"], text=True)
    if status:
        parser.error("Wiki 克隆已有未提交改动；先处理已有改动，导出不会覆盖它们")
    subprocess.run(["python3", str(ROOT / "scripts/check_community.py")], check=True)
    pages = sorted((ROOT / "docs/wiki").glob("*.md"))
    names = {page.name for page in pages}
    pattern = re.compile(r"(\[[^\]]*\]\()([A-Za-z0-9_-]+\.md)(#[^\s)]*)?(\))")
    exports = []
    for page in pages:
        text = page.read_text(encoding="utf-8")

        def replace(match):
            filename = match.group(2)
            if filename not in names:
                raise ValueError("Wiki 页链接未指向受审查源文件")
            return f"{match.group(1)}{WIKI_URL}/{Path(filename).stem}{match.group(3) or ''}{match.group(4)}"

        content = pattern.sub(replace, text)
        destination = target / page.name
        if destination.is_symlink():
            parser.error("Wiki 目标含符号链接，请人工检查")
        exports.append((destination, content))
    for destination, content in exports:
        destination.write_text(content, encoding="utf-8")
    print(f"已导出 {len(pages)} 个 Wiki 文件；保留其他已有页面，不自动提交或推送。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
