"""DLP 诊断脚本 —— 对任意文本跑一遍当前数据库里启用的 DLP 规则，打印命中详情。

用法:
    # 从文件读取待测文本
    python -m scripts.dlp_debug path/to/payload.txt

    # 从 stdin 读取（便于粘贴 workbuddy 实际发送的 system prompt / 消息）
    cat payload.txt | python -m scripts.dlp_debug -

    # 可选：只针对某个组织加载规则（默认加载所有启用规则）
    python -m scripts.dlp_debug payload.txt --org <organization_id>

需在 backend/ 目录下运行（确保 app 包可导入）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.database import async_session_factory, engine
from app.dlp.engine import DLPEngine
from app.models.dlp_rule import DlpRule

# 关闭 SQL echo，避免诊断输出被 SQL 日志淹没
engine.echo = False


async def load_rules(org_id: str | None) -> list[DlpRule]:
    async with async_session_factory() as db:
        stmt = select(DlpRule).where(
            DlpRule.is_active.is_(True),
            DlpRule.deleted_at.is_(None),
        )
        if org_id:
            stmt = stmt.where(DlpRule.organization_id == org_id)
        result = await db.execute(stmt.order_by(DlpRule.priority.desc()))
        return list(result.scalars().all())


async def main() -> int:
    parser = argparse.ArgumentParser(description="DLP 规则诊断")
    parser.add_argument(
        "input",
        help="待测文本文件路径，或 '-' 表示从 stdin 读取",
    )
    parser.add_argument("--org", default=None, help="可选：限定 organization_id")
    parser.add_argument(
        "--direction", default="request",
        choices=["request", "response", "both"],
        help="扫描方向（默认 request，与代理请求扫描一致）",
    )
    args = parser.parse_args()

    # 读取文本
    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding="utf-8")

    print(f"待测文本长度: {len(text)} 字符")
    print(f"扫描方向: {args.direction}")
    print("-" * 60)

    rules = await load_rules(args.org)
    print(f"加载启用规则: {len(rules)} 条")
    for r in rules:
        print(f"  - [{r.action:6}] {r.name}  (priority={r.priority}, dir={r.direction})")
    print("-" * 60)

    engine = DLPEngine(rules=rules)
    result = await engine.scan(text, direction=args.direction)

    print(f"blocked : {result.blocked}")
    print(f"violations (block+redact): {len(result.violations)}")
    print(f"warnings : {len(result.warnings)}")
    print(f"logged   : {len(result.logged)}")
    print("=" * 60)

    def dump(label: str, matches) -> None:
        if not matches:
            return
        print(f"\n【{label}】")
        for i, m in enumerate(matches, 1):
            print(f"  {i}. 规则: {m.rule_name}  (severity={m.severity}, action={m.action})")
            print(f"     位置: [{m.start}, {m.end})")
            print(f"     命中(脱敏): {m.matched_text_redacted}")
            # 命中文本前后各展示最多 40 字符上下文
            ctx_start = max(0, m.start - 40)
            ctx_end = min(len(text), m.end + 40)
            print(f"     上下文: ...{text[ctx_start:ctx_end]!r}...")

    dump("BLOCK / REDACT", result.violations)
    dump("WARN", result.warnings)
    dump("LOG", result.logged)

    return 0 if not result.blocked else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
