#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project-memory skill 的记忆管理脚本

支持的命令：
    init / add / search / list / remove / summarize / export / cleanup

存储布局：
    {workspace}/.project-memory/
        ├── index.json          # 索引（标题、分类、标签、时间）
        ├── code-map.md
        ├── architecture.md
        ├── solutions.md
        ├── decisions.md
        ├── work-log.md
        └── glossary.md

工作区参数支持：
    - 绝对路径：例如 /root/PythonCodeHub
    - "--global" 或 "~"：写入到 ~/.project-memory/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

CATEGORIES = [
    "code-map",
    "architecture",
    "solutions",
    "decisions",
    "work-log",
    "glossary",
]

ENTRY_SEPARATOR = "\n---\n"
ENTRY_RE = re.compile(
    r"^###\s+(?P<title>.+?)\n"
    r"-\s+\*\*Date\*\*:\s*(?P<date>.+?)\n"
    r"-\s+\*\*Tags\*\*:\s*(?P<tags>.*?)\n"
    r"\n(?P<content>.*?)$",
    re.DOTALL | re.MULTILINE,
)

# cleanup 时默认豁免的分类（设计决策长期有效）
CLEANUP_EXEMPT_CATEGORIES = {"decisions", "glossary"}

# 用于识别 pin 钉住条目的 tag
PIN_TAG = "pinned"

# 敏感信息检测（OWASP 常见高危项）
SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("password", re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+")),
    ("api_key", re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?key)\s*[:=]\s*\S+")),
    ("secret", re.compile(r"(?i)\b(secret|token)\s*[:=]\s*\S+")),
    ("aksk", re.compile(r"\b(AKID|AKIA)[A-Z0-9]{8,}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
]


def _detect_sensitive(text: str) -> list[str]:
    """返回命中的敏感信息类别列表，未命中返回空列表"""
    hits: list[str] = []
    for label, pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def _resolve_store_dir(workspace: str) -> Path:
    """根据 workspace 参数返回记忆存储目录"""
    if workspace in ("--global", "~", ""):
        base = Path.home() / ".project-memory"
    else:
        base = Path(workspace).expanduser().resolve() / ".project-memory"
    return base


def _ensure_store(store_dir: Path) -> None:
    """确保存储目录与各分类文件存在"""
    store_dir.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        f = store_dir / f"{cat}.md"
        if not f.exists():
            f.write_text(f"# {cat}\n\n", encoding="utf-8")
    index = store_dir / "index.json"
    if not index.exists():
        index.write_text(
            json.dumps({"updated_at": _now_str(), "entries": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_index(store_dir: Path) -> dict[str, Any]:
    path = store_dir / "index.json"
    if not path.exists():
        return {"updated_at": _now_str(), "entries": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"updated_at": _now_str(), "entries": []}


def _save_index(store_dir: Path, index: dict[str, Any]) -> None:
    index["updated_at"] = _now_str()
    (store_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_entries(text: str) -> list[dict[str, str]]:
    """从分类文件文本中解析出所有条目"""
    entries: list[dict[str, str]] = []
    blocks = re.split(r"\n---\n", text)
    for block in blocks:
        block = block.strip("\n")
        if not block.startswith("### "):
            continue
        m = ENTRY_RE.match(block + "\n")
        if not m:
            continue
        entries.append({
            "title": m.group("title").strip(),
            "date": m.group("date").strip(),
            "tags": m.group("tags").strip(),
            "content": m.group("content").rstrip(),
        })
    return entries


def _render_entry(title: str, content: str, tags: str = "") -> str:
    return (
        f"### {title}\n"
        f"- **Date**: {_now_str()}\n"
        f"- **Tags**: {tags}\n\n"
        f"{content.strip()}\n"
    )


def _category_file(store_dir: Path, category: str) -> Path:
    if category not in CATEGORIES:
        raise SystemExit(f"未知分类: {category}，可选值: {', '.join(CATEGORIES)}")
    return store_dir / f"{category}.md"


# ---------- 命令实现 ----------

def cmd_init(workspace: str) -> None:
    store_dir = _resolve_store_dir(workspace)
    _ensure_store(store_dir)
    print(f"[project-memory] 初始化完成: {store_dir}")


def cmd_add(
    workspace: str,
    category: str,
    title: str,
    content: str,
    tags: str = "",
    force: bool = False,
) -> None:
    """添加或更新一条记忆条目

    参数:
        workspace: 工作区路径或 --global / ~
        category: 分类名，必须在 CATEGORIES 中
        title: 条目标题（同分类同标题视为更新）
        content: 条目正文
        tags: 逗号分隔的标签字符串，留空则从标题自动抽取
        force: 是否忽略敏感信息检测

    返回值: None

    执行步骤：
    1. 确保存储目录与分类文件存在
    2. 检测敏感信息，命中则拒绝写入（force=True 可绕过）
    3. 若同分类下已存在同标题条目，则覆盖更新
    4. 否则追加到分类文件末尾
    5. 同步更新 index.json
    """
    store_dir = _resolve_store_dir(workspace)
    _ensure_store(store_dir)
    file_path = _category_file(store_dir, category)

    # 敏感信息拦截
    sensitive_hits = _detect_sensitive(f"{title}\n{content}")
    if sensitive_hits and not force:
        print(
            f"[project-memory] 拒绝写入：检测到疑似敏感信息（{', '.join(sensitive_hits)}）。"
            f"如确认安全可加 --force 绕过"
        )
        raise SystemExit(2)

    # 自动从内容中抽取关键词作为补充标签（仅当未指定 tags 时）
    if not tags:
        tags = _auto_tags(title, content)

    entries = _parse_entries(file_path.read_text(encoding="utf-8"))
    updated = False
    new_entries: list[dict[str, str]] = []
    for e in entries:
        if e["title"] == title:
            new_entries.append({
                "title": title,
                "date": _now_str(),
                "tags": tags,
                "content": content.strip(),
            })
            updated = True
        else:
            new_entries.append(e)
    if not updated:
        new_entries.append({
            "title": title,
            "date": _now_str(),
            "tags": tags,
            "content": content.strip(),
        })

    _write_category(file_path, category, new_entries)

    # 同步索引
    index = _load_index(store_dir)
    index["entries"] = [
        x for x in index["entries"]
        if not (x.get("category") == category and x.get("title") == title)
    ]
    index["entries"].append({
        "category": category,
        "title": title,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "date": _now_str(),
    })
    _save_index(store_dir, index)

    action = "更新" if updated else "添加"
    print(f"[project-memory] 已{action} [{category}] {title}")


def _write_category(file_path: Path, category: str, entries: list[dict[str, str]]) -> None:
    """将条目列表回写到分类文件"""
    parts = [f"# {category}\n"]
    for e in entries:
        parts.append(
            f"### {e['title']}\n"
            f"- **Date**: {e['date']}\n"
            f"- **Tags**: {e['tags']}\n\n"
            f"{e['content']}\n"
        )
    file_path.write_text(ENTRY_SEPARATOR.join(parts), encoding="utf-8")


def _auto_tags(title: str, content: str) -> str:
    """简单关键词抽取：从标题中拆词"""
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", title)
    seen: list[str] = []
    for w in words:
        if w.lower() not in [s.lower() for s in seen]:
            seen.append(w)
        if len(seen) >= 5:
            break
    return ", ".join(seen)


def cmd_search(workspace: str, keywords: str, as_json: bool = False) -> None:
    store_dir = _resolve_store_dir(workspace)
    if not store_dir.exists():
        msg = "[project-memory] 记忆存储不存在，请先运行 init"
        print(json.dumps({"error": msg, "hits": []}, ensure_ascii=False) if as_json else msg)
        return

    kw_list = [k.strip().lower() for k in re.split(r"[\s,;]+", keywords) if k.strip()]
    hits: list[tuple[str, dict[str, str]]] = []

    for cat in CATEGORIES:
        file_path = store_dir / f"{cat}.md"
        if not file_path.exists():
            continue
        for entry in _parse_entries(file_path.read_text(encoding="utf-8")):
            haystack = (entry["title"] + " " + entry["tags"] + " " + entry["content"]).lower()
            if all(k in haystack for k in kw_list):
                hits.append((cat, entry))

    if as_json:
        payload = [
            {
                "category": cat,
                "title": e["title"],
                "date": e["date"],
                "tags": e["tags"],
                "content": e["content"],
            }
            for cat, e in hits
        ]
        print(json.dumps({"hits": payload}, ensure_ascii=False, indent=2))
        return

    if not hits:
        print(f"[project-memory] 未找到与 '{keywords}' 相关的记忆")
        return

    print(f"[project-memory] 找到 {len(hits)} 条相关记忆:\n")
    for cat, e in hits:
        print(f"## [{cat}] {e['title']}")
        print(f"- Date: {e['date']}")
        print(f"- Tags: {e['tags']}")
        print()
        print(e["content"])
        print("\n---\n")


def cmd_list(workspace: str, category: str | None = None, as_json: bool = False) -> None:
    store_dir = _resolve_store_dir(workspace)
    if not store_dir.exists():
        msg = "[project-memory] 记忆存储不存在"
        print(json.dumps({"error": msg, "items": []}, ensure_ascii=False) if as_json else msg)
        return
    cats = [category] if category else CATEGORIES
    items: list[dict[str, str]] = []
    for cat in cats:
        file_path = store_dir / f"{cat}.md"
        if not file_path.exists():
            continue
        entries = _parse_entries(file_path.read_text(encoding="utf-8"))
        for e in entries:
            items.append({
                "category": cat,
                "title": e["title"],
                "date": e["date"],
                "tags": e["tags"],
            })

    if as_json:
        print(json.dumps({"items": items}, ensure_ascii=False, indent=2))
        return

    grouped: dict[str, list[dict[str, str]]] = {}
    for it in items:
        grouped.setdefault(it["category"], []).append(it)
    for cat in cats:
        if cat not in grouped:
            continue
        print(f"## {cat} ({len(grouped[cat])} 条)")
        for e in grouped[cat]:
            print(f"  - [{e['date']}] {e['title']}  (tags: {e['tags']})")
        print()


def cmd_remove(workspace: str, category: str, title: str) -> None:
    store_dir = _resolve_store_dir(workspace)
    file_path = _category_file(store_dir, category)
    if not file_path.exists():
        print(f"[project-memory] {category} 不存在")
        return
    entries = _parse_entries(file_path.read_text(encoding="utf-8"))
    remained = [e for e in entries if e["title"] != title]
    if len(remained) == len(entries):
        print(f"[project-memory] 未找到条目: {title}")
        return

    _write_category(file_path, category, remained)

    # 同步索引
    index = _load_index(store_dir)
    index["entries"] = [
        x for x in index["entries"]
        if not (x.get("category") == category and x.get("title") == title)
    ]
    _save_index(store_dir, index)
    print(f"[project-memory] 已删除 [{category}] {title}")


def cmd_pin(workspace: str, category: str, title: str, unpin: bool = False) -> None:
    """为条目打上 pinned 标签，cleanup 将永不删除

    参数:
        workspace: 工作区路径
        category: 分类名
        title: 条目标题
        unpin: True 表示取消钉住
    """
    store_dir = _resolve_store_dir(workspace)
    file_path = _category_file(store_dir, category)
    if not file_path.exists():
        print(f"[project-memory] {category} 不存在")
        return
    entries = _parse_entries(file_path.read_text(encoding="utf-8"))
    found = False
    for e in entries:
        if e["title"] != title:
            continue
        found = True
        tag_list = [t.strip() for t in e["tags"].split(",") if t.strip()]
        has_pin = PIN_TAG in tag_list
        if unpin and has_pin:
            tag_list = [t for t in tag_list if t != PIN_TAG]
        elif not unpin and not has_pin:
            tag_list.append(PIN_TAG)
        e["tags"] = ", ".join(tag_list)
    if not found:
        print(f"[project-memory] 未找到条目: {title}")
        return
    _write_category(file_path, category, entries)

    # 同步索引中的 tags
    index = _load_index(store_dir)
    for x in index["entries"]:
        if x.get("category") == category and x.get("title") == title:
            tags = list(x.get("tags") or [])
            if unpin and PIN_TAG in tags:
                tags = [t for t in tags if t != PIN_TAG]
            elif not unpin and PIN_TAG not in tags:
                tags.append(PIN_TAG)
            x["tags"] = tags
    _save_index(store_dir, index)
    print(f"[project-memory] {'已取消钉住' if unpin else '已钉住'} [{category}] {title}")


def cmd_summarize(workspace: str, summary: str) -> None:
    """将会话摘要写入 work-log"""
    title = f"Session Summary {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    cmd_add(workspace, "work-log", title, summary, tags="session, summary")


def cmd_export(workspace: str) -> None:
    store_dir = _resolve_store_dir(workspace)
    if not store_dir.exists():
        print("[project-memory] 记忆存储不存在")
        return
    print(f"# Project Memory Export ({store_dir})\n")
    for cat in CATEGORIES:
        file_path = store_dir / f"{cat}.md"
        if not file_path.exists():
            continue
        text = file_path.read_text(encoding="utf-8").strip()
        if text and text != f"# {cat}":
            print(text)
            print()


def cmd_cleanup(workspace: str, days: int) -> None:
    """清理超过 N 天的旧条目

    参数:
        workspace: 工作区路径
        days: 保留天数，正整数

    豁免规则：
    1. decisions / glossary 分类整体豁免（长期有效的设计决策与术语）
    2. 任何带 `pinned` 标签的条目都不会被清理
    """
    if days <= 0:
        raise SystemExit("days 必须为正整数")
    store_dir = _resolve_store_dir(workspace)
    if not store_dir.exists():
        print("[project-memory] 记忆存储不存在")
        return
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    removed_keys: set[tuple[str, str]] = set()
    for cat in CATEGORIES:
        if cat in CLEANUP_EXEMPT_CATEGORIES:
            continue
        file_path = store_dir / f"{cat}.md"
        if not file_path.exists():
            continue
        entries = _parse_entries(file_path.read_text(encoding="utf-8"))
        kept: list[dict[str, str]] = []
        for e in entries:
            tags = [t.strip() for t in e["tags"].split(",") if t.strip()]
            if PIN_TAG in tags:
                kept.append(e)
                continue
            try:
                d = datetime.strptime(e["date"], "%Y-%m-%d %H:%M")
            except ValueError:
                kept.append(e)
                continue
            if d >= cutoff:
                kept.append(e)
            else:
                removed += 1
                removed_keys.add((cat, e["title"]))
        if len(kept) != len(entries):
            _write_category(file_path, cat, kept)

    # 同步索引：仅移除真正被清理的条目，避免误删豁免分类
    index = _load_index(store_dir)
    index["entries"] = [
        x for x in index["entries"]
        if (x.get("category"), x.get("title")) not in removed_keys
    ]
    _save_index(store_dir, index)

    print(f"[project-memory] 已清理 {removed} 条超过 {days} 天的记忆")


# ---------- 入口 ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memory_manager.py", description="project-memory 记忆管理工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init"); sp.add_argument("workspace")
    sp = sub.add_parser("add")
    sp.add_argument("workspace"); sp.add_argument("category")
    sp.add_argument("title"); sp.add_argument("content")
    sp.add_argument("--tags", default="")
    sp.add_argument("--force", action="store_true", help="忽略敏感信息检测，强制写入")

    sp = sub.add_parser("search")
    sp.add_argument("workspace"); sp.add_argument("keywords")
    sp.add_argument("--json", dest="as_json", action="store_true")

    sp = sub.add_parser("list")
    sp.add_argument("workspace"); sp.add_argument("category", nargs="?")
    sp.add_argument("--json", dest="as_json", action="store_true")

    sp = sub.add_parser("remove")
    sp.add_argument("workspace"); sp.add_argument("category"); sp.add_argument("title")

    sp = sub.add_parser("pin")
    sp.add_argument("workspace"); sp.add_argument("category"); sp.add_argument("title")
    sp.add_argument("--unpin", action="store_true", help="取消钉住")

    sp = sub.add_parser("summarize"); sp.add_argument("workspace"); sp.add_argument("summary")
    sp = sub.add_parser("export"); sp.add_argument("workspace")
    sp = sub.add_parser("cleanup"); sp.add_argument("workspace"); sp.add_argument("days", type=int)
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        cmd_init(args.workspace)
    elif args.cmd == "add":
        cmd_add(args.workspace, args.category, args.title, args.content, args.tags, args.force)
    elif args.cmd == "search":
        cmd_search(args.workspace, args.keywords, args.as_json)
    elif args.cmd == "list":
        cmd_list(args.workspace, args.category, args.as_json)
    elif args.cmd == "remove":
        cmd_remove(args.workspace, args.category, args.title)
    elif args.cmd == "pin":
        cmd_pin(args.workspace, args.category, args.title, args.unpin)
    elif args.cmd == "summarize":
        cmd_summarize(args.workspace, args.summary)
    elif args.cmd == "export":
        cmd_export(args.workspace)
    elif args.cmd == "cleanup":
        cmd_cleanup(args.workspace, args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
