#!/usr/bin/env python3
"""Export reviewed Wiki sources into an initialized local Wiki clone."""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "wide-sky-with-me/ysu_net"
WIKI_URL = f"https://github.com/{REPO}/wiki"
ALLOWED_REMOTES = {
    f"https://github.com/{REPO}.wiki.git",
    f"git@github.com:{REPO}.wiki.git",
    f"ssh://git@github.com/{REPO}.wiki.git",
}

def prepare_exports(source: Path, target: Path):
    """Render and preflight every reviewed destination before replacing any page."""
    pages = sorted(source.glob("*.md"))
    names = {page.name for page in pages}
    if not pages or not {"Home.md", "_Sidebar.md"}.issubset(names):
        raise ValueError("Wiki 源页为空或缺少 Home / _Sidebar，停止导出")
    pattern = re.compile(r"(\[[^\]]*\]\()([A-Za-z0-9_-]+\.md)(#[^\s)]*)?(\))")
    exports = []
    for page in pages:
        if page.is_symlink() or not page.is_file():
            raise ValueError("Wiki 受审查源页必须是普通文件")
        text = page.read_text(encoding="utf-8")

        def replace(match):
            filename = match.group(2)
            if filename not in names:
                raise ValueError("Wiki 页链接未指向受审查源文件")
            return f"{match.group(1)}{WIKI_URL}/{Path(filename).stem}{match.group(3) or ''}{match.group(4)}"

        content = pattern.sub(replace, text)
        destination = target / page.name
        if destination.is_symlink():
            raise ValueError("Wiki 目标含符号链接，请人工检查")
        if destination.exists() and not destination.is_file():
            raise ValueError("Wiki 页目标不是普通文件，请人工检查")
        exports.append((destination, content))
    return exports


def replace_page(destination: Path, content: str) -> None:
    """Replace the directory entry, never truncate a possibly hard-linked inode.

    Atomicity is per page, NOT a whole-export transaction or protection against
    every same-UID race. Cleanup addresses only this invocation's temporary name.
    """
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".ysu-wiki-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Close before replacing: Windows also requires the temporary handle closed.
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    subprocess.run([sys.executable, str(ROOT / "scripts/check_community.py")], check=True)
    try:
        exports = prepare_exports(ROOT / "docs/wiki", target)
    except ValueError as error:
        parser.error(str(error))
    try:
        for destination, content in exports:
            replace_page(destination, content)
    except OSError:
        parser.exit(1, "Wiki 导出失败；此前页面可能已替换，请人工复核，不会自动提交或推送。\n")
    print(f"已导出 {len(exports)} 个 Wiki 文件；保留其他已有页面，不自动提交或推送。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
