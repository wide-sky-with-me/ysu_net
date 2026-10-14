#!/usr/bin/env python3
"""Check community documents and JSON-compatible YAML forms offline."""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOTS = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SUPPORT.md",
    ROOT / "SECURITY.md",
    ROOT / "CODE_OF_CONDUCT.md",
    ROOT / "docs/security.md",
    ROOT / "docs/community-maintenance.md",
    ROOT / "docs/wiki",
    ROOT / ".github/ISSUE_TEMPLATE",
    ROOT / ".github/DISCUSSION_TEMPLATE",
    ROOT / ".github/PULL_REQUEST_TEMPLATE.md",
]
LINK = re.compile(r"\[[^\]]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "access-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "credential-url": re.compile(r"https?://[^\s/@:]+:[^\s/@]+@"),
    "personal-home": re.compile(r"(?:/home/|/Users/)[A-Za-z0-9_.-]+/|[A-Za-z]:\\Users\\[^\\\s]+\\"),
    "device-address": re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b|\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "session-value": re.compile(r"(?i)(?:authorization|cookie|userindex|access_token)\s*[:=]\s*['\"]?[A-Za-z0-9/+_.=-]{16,}"),
}


def public_files():
    files = []
    for path in PUBLIC_ROOTS:
        if path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file())
        else:
            files.append(path)
    return sorted(files)


def headings(text):
    result = set()
    seen = {}
    for line in re.sub(r"```.*?```", "", text, flags=re.S).splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", line)
        if not match:
            continue
        title = re.sub(r"<[^>]+>", "", match.group(1)).lower()
        title = re.sub(r"[^\w\-\s]", "", title)
        anchor = re.sub(r"\s", "-", title)
        count = seen.get(anchor, 0)
        seen[anchor] = count + 1
        result.add(f"{anchor}-{count}" if count else anchor)
    return result


def check_links(path, text, errors):
    content = re.sub(r"```.*?```", lambda match: "\n" * match.group(0).count("\n"), text, flags=re.S)
    for match in LINK.finditer(content):
        line = content.count("\n", 0, match.start()) + 1
        source = f"{path.relative_to(ROOT)}:{line}"
        target = unquote(match.group(1).strip("<>"))
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        dest = (path.parent / parsed.path).resolve() if parsed.path else path
        if not dest.is_relative_to(ROOT) or not dest.exists():
            errors.append(f"{source}: 文档链接目标不存在")
        elif parsed.fragment and dest.suffix.lower() == ".md":
            if parsed.fragment not in headings(dest.read_text(encoding="utf-8")):
                errors.append(f"{source}: 文档锚点不存在")


def check_form(path, data, errors):
    label = str(path.relative_to(ROOT))
    is_issue = path.parent.name == "ISSUE_TEMPLATE"
    if path.name == "config.yml":
        if set(data) != {"blank_issues_enabled", "contact_links"}:
            errors.append(f"{label}: 反馈入口配置字段错误")
        if not isinstance(data.get("blank_issues_enabled"), bool):
            errors.append(f"{label}: blank_issues_enabled 应为布尔值")
        for item in data.get("contact_links", []):
            if not all(isinstance(item.get(key), str) and item[key] for key in ("name", "url", "about")):
                errors.append(f"{label}: contact_links 缺少必要字段")
        return
    allowed = {"name", "description", "title", "labels", "body"} if is_issue else {"title", "labels", "body"}
    if set(data) - allowed or not isinstance(data.get("body"), list):
        errors.append(f"{label}: 表单顶层字段错误")
        return
    if is_issue and not all(isinstance(data.get(key), str) and data[key] for key in ("name", "description")):
        errors.append(f"{label}: 问题表单缺少名称或说明")
    if not is_issue and path.stem not in {"q-a", "ideas", "show-and-tell"}:
        errors.append(f"{label}: 讨论分类 slug 未核对")
    ids = set()
    editable = False
    privacy = False
    for field in data["body"]:
        kind = field.get("type")
        attrs = field.get("attributes", {})
        field_id = field.get("id")
        if kind not in {"markdown", "input", "textarea", "dropdown", "checkboxes"}:
            errors.append(f"{label}: 未支持的表单字段")
        if field_id:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", field_id) or field_id in ids:
                errors.append(f"{label}: 字段 id 非法或重复")
            ids.add(field_id)
        if kind == "markdown":
            if not attrs.get("value"):
                errors.append(f"{label}: Markdown 提示为空")
            continue
        editable = True
        if not attrs.get("label") or not field_id:
            errors.append(f"{label}: 输入字段缺少标签或 id")
        if kind == "dropdown" and (not attrs.get("options") or len(set(attrs["options"])) != len(attrs["options"])):
            errors.append(f"{label}: 下拉选项为空或重复")
        if kind == "checkboxes" and field_id == "privacy":
            privacy = any(option.get("required") is True and "信息" in option.get("label", "") for option in attrs.get("options", []))
    if not editable or not privacy:
        errors.append(f"{label}: 缺少输入字段或必填脱敏确认")


def main():
    errors = []
    paths = public_files()
    forms = 0
    for path in paths:
        if not path.is_file():
            errors.append(f"{path.relative_to(ROOT)}: 必要社区文件缺失")
            continue
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            for rule, regex in RULES.items():
                if regex.search(line):
                    errors.append(f"{path.relative_to(ROOT)}:{number}: 敏感字段规则 {rule} 命中，需人工复核")
        if path.suffix == ".md":
            check_links(path, text, errors)
        elif path.suffix == ".yml":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.relative_to(ROOT)}:{exc.lineno}: 表单须使用 JSON 兼容的 YAML")
                continue
            if not isinstance(data, dict):
                errors.append(f"{path.relative_to(ROOT)}: 表单应为对象")
                continue
            check_form(path, data, errors)
            forms += 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"社区检查通过：{len(paths)} 个文件，{forms} 个表单/入口配置；本地链接和锚点有效，敏感字段规则无命中。")
    print("规则扫描不替代人工脱敏；外部链接、平台表单渲染和真实校园网行为需分别核对。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
