"""一键重置并重新导入「敏睿制造」POC 数据。

流程：
    1. 硬删除目标组织及其全部子表数据（临时关闭 FK 检查，按 organization_id 清空）；
    2. 删除组织本身；
    3. 恢复 FK 检查并提交；
    4. 调用 seed_minrui_manufacturing.seed() 重建全部 POC 数据。

目标组织 slug 默认取自 seed 模块的 ORG_DEF（即 minrui），可用 --slug 覆盖。
子表清单由 information_schema 动态发现，随 schema 演进自动覆盖新表，无需维护。
幂等：可重复执行，每次都把目标组织清空后重建；组织不存在时直接进入 seed。

⚠️ 破坏性操作：会永久删除目标组织下的全部数据，请确认 slug 后再执行。

用法:
    cd llm_router/backend
    python scripts/reset_and_seed.py                 # 重置 minrui 并重建（交互确认）
    python scripts/reset_and_seed.py --yes           # 跳过确认，适合 CI / 部署
    python scripts/reset_and_seed.py --slug minrui   # 指定组织
    python scripts/reset_and_seed.py --reset-only    # 只清空不重建
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

# 确保能把 `app` 包导入（脚本从 backend/ 目录运行）
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR.parent))

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.organization import Organization

logger = structlog.get_logger()


def _load_seed_module():
    """按文件路径加载 seed_minrui_manufacturing（scripts/ 不是包，用 importlib）。"""
    seed_path = SCRIPTS_DIR / "seed_minrui_manufacturing.py"
    spec = importlib.util.spec_from_file_location("seed_minrui_manufacturing", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # noqa: SLF001
    return mod


async def _discover_org_scoped_tables(db: AsyncSession) -> list[str]:
    """从 information_schema 动态发现所有含 organization_id 列的表。"""
    rows = await db.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE column_name = 'organization_id' AND table_schema = 'public' "
            "ORDER BY table_name"
        )
    )
    return [r[0] for r in rows.all()]


async def reset_org(slug: str) -> dict:
    """硬删除目标组织及其全部子表数据。返回 {reset: bool, deleted: {table: n}}。"""
    result = {"reset": False, "deleted": {}}
    async with async_session_factory() as db:
        org = (
            await db.execute(
                select(Organization).where(
                    Organization.slug == slug, Organization.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

        if org is None:
            logger.info("reset_org_missing", slug=slug)
            return result

        tables = await _discover_org_scoped_tables(db)
        logger.info("reset_org_start", slug=slug, org_id=str(org.id), child_tables=len(tables))

        # 临时关闭 FK 检查：子表含 RESTRICT 约束，关闭后可按 organization_id 任意顺序清理。
        # 表名来自 information_schema（DB 侧可信），非用户输入，可安全插值。
        # oid 转字符串：部分子表 organization_id 列为 text/varchar（如 audit_logs），
        # asyncpg 的 text 编解码器拒绝 UUID 对象；传 str 对 uuid 列与 text 列均兼容。
        oid = str(org.id)
        await db.execute(text("SET session_replication_role = replica"))
        for tbl in tables:
            deleted = await db.execute(
                text(f'DELETE FROM "{tbl}" WHERE organization_id = :oid'),
                {"oid": oid},
            )
            n = deleted.rowcount or 0
            if n:
                result["deleted"][tbl] = n
                logger.info("reset_table_deleted", table=tbl, rows=n)

        # 最后删除组织本身
        await db.execute(text("DELETE FROM organizations WHERE id = :oid"), {"oid": oid})
        await db.execute(text("SET session_replication_role = DEFAULT"))
        await db.commit()
        result["reset"] = True
        logger.info("reset_org_done", slug=slug)
    return result


async def main(argv: list[str] | None = None) -> int:
    seed_mod = _load_seed_module()
    default_slug = seed_mod.ORG_DEF["slug"]

    parser = argparse.ArgumentParser(description="一键重置并重建 POC 组织数据")
    parser.add_argument("--slug", default=default_slug, help=f"目标组织 slug（默认 {default_slug}）")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认，适合 CI / 部署")
    parser.add_argument("--reset-only", action="store_true", help="只清空不重建")
    args = parser.parse_args(argv)

    if not args.yes:
        confirm = input(
            f"⚠️  将永久删除组织 [{args.slug}] 下的全部数据并重建。确认？[y/N] "
        ).strip().lower()
        if confirm not in {"y", "yes"}:
            print("已取消。")
            return 0

    # 1) 重置
    reset = await reset_org(args.slug)
    if reset["reset"]:
        total = sum(reset["deleted"].values())
        print(f"\n已清空组织 [{args.slug}]：共删除 {total} 行子表数据。")
        for tbl, n in reset["deleted"].items():
            print(f"  {tbl:<20}: -{n}")
    else:
        print(f"\n组织 [{args.slug}] 不存在，跳过清理，直接进入 seed。")

    # 2) 重建
    if args.reset_only:
        print("\n--reset-only：跳过重建。")
        return 0

    print("\n开始重建 POC 数据 …")
    result = await seed_mod.seed()
    seed_mod._print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
