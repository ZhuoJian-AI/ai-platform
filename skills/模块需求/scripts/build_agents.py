#!/usr/bin/env python3
"""把 SKILL.md + references/ 拼成给 Codex 用的单份 AGENTS.md。

为什么要这个脚本：
Claude Code 支持 SKILL.md + references/ 的按需加载，Codex 不支持 —— 在 Codex 里
分文件写等于白写。所以维护单一主体（SKILL.md + references/），用这个脚本生成 Codex 版，
不手工维护两份（两份必然漂移）。

改了 SKILL.md 或任何 reference 之后，重跑一次：
    python scripts/build_agents.py
"""

from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFS = [
    ("01_开场.md", "第一部分 · 开场"),
    ("02_逼问需求.md", "第二部分 · 逼问需求"),
    ("03_做成什么样.md", "第三部分 · 做成什么样"),
    ("04_需求成型.md", "第四部分 · 需求成型"),
]


def read(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def strip_frontmatter(text: str) -> tuple[str, str]:
    """返回 (frontmatter 里的 description, 去掉 frontmatter 的正文)"""
    if not text.startswith("---"):
        return "", text
    end = text.index("\n---", 3) + 4
    fm, body = text[:end], text[end:]
    m = re.search(r"^description:\s*(.+)$", fm, flags=re.M)
    return (m.group(1).strip() if m else ""), body.lstrip("\n")


def demote_headings(text: str) -> str:
    """整份下沉一级，避免和 AGENTS.md 的章节标题打架"""
    return re.sub(r"^(#{1,5}) ", r"#\1 ", text, flags=re.M)


def main() -> int:
    desc, skill_body = strip_frontmatter(read(ROOT / "SKILL.md"))

    # 正文里的 references 指路改成本文内部指路
    for filename, section in REFS:
        skill_body = skill_body.replace(f"`references/{filename}`", f"**{section}**")
    skill_body = skill_body.replace("`templates/需求文档模板.html`", "随包的 `需求文档模板.html`")
    # 「按需读取」那张表在单份文件里没有意义
    skill_body = re.sub(r"\n## 按需读取\n.*?(?=\n## |\Z)", "\n", skill_body, flags=re.S)

    parts = [
        "# 模块需求（Codex 单份版）",
        "",
        "> 本文件由 `scripts/build_agents.py` 从 `SKILL.md` + `references/` 自动生成。",
        "> **不要直接改这个文件** —— 改了下次生成就没了。要改去改 `SKILL.md` 或对应的 reference。",
        "",
        f"> **这个 skill 干什么**：{desc}",
        "",
        "---",
        "",
        skill_body.rstrip(),
        "",
    ]

    for filename, section in REFS:
        body = read(ROOT / "references" / filename)
        # 去掉每份自己的一级标题（下面统一用 section 名）
        body = re.sub(r"^# .*\n", "", body, count=1)
        parts += ["", "---", "", f"# {section}", "", demote_headings(body).strip(), ""]

    out = "\n".join(parts).rstrip() + "\n"
    target = ROOT / "AGENTS.md"
    io.open(target, "w", encoding="utf-8", newline="\n").write(out)
    print(f"已生成 {target}（{len(out)} 字符，{out.count(chr(10)) + 1} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
