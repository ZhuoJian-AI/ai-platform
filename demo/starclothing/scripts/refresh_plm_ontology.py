"""幂等刷新：把 seed_starclothing_ontology 里 PLM 域重新渲染的本体文件
（含新增 identifiers.md）upsert 进「现有部门级 scope 的 PLM 副本」。

背景：seed_starclothing_ontology.py 默认写组织级 scope；但 reorg_starclothing_scope.py
已把 PLM/* 搬到部门级 scope（开发部 own + 品控部 proxy）。直接重跑 seed 会落到 org scope
的隐形副本，dev-lead / qc-lead 看不到。本脚本复用 seed 的结构化数据 + render 函数，
找到所有现有部门级 PLM 副本，逐个 upsert（按 (org, scope_type, scope_id, path) 幂等），
无需重跑 reorg 的迁移/ proxy 逻辑。

用法:
    docker cp demo/starclothing/scripts/refresh_plm_ontology.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/refresh_plm_ontology.py
"""
# ruff: noqa: E501
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_HERE.parent))  # 找到同目录的 seed_starclothing_ontology

import structlog  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.ontology import OntologyFile  # noqa: E402
from app.schemas.ontology import OntologyFileCreate  # noqa: E402
from app.services.ontology_store_service import upsert_file  # noqa: E402

import seed_starclothing_ontology as seed  # noqa: E402

logger = structlog.getLogger()

ORG_SLUG = "starclothing"


async def _get_org(db: AsyncSession) -> Organization:
    r = await db.execute(select(Organization).where(Organization.slug == ORG_SLUG, Organization.deleted_at.is_(None)))
    org = r.scalar_one_or_none()
    if org is None:
        r = await db.execute(select(Organization).where(Organization.name == "星途服装", Organization.deleted_at.is_(None)))
        org = r.scalar_one_or_none()
    if org is None:
        raise RuntimeError("组织 starclothing 不存在，先跑 seed_starclothing_apparel.py")
    return org


async def _find_dept_scopes_for_folder(db: AsyncSession, org_id: str, folder: str) -> list[tuple[str, str | None]]:
    """返回所有持有 {folder}/* 文件的 (scope_type, scope_id) 组合（含部门级 own + proxy 副本）。"""
    r = await db.execute(text("""
        select distinct scope_type, scope_id
        from ontology_files
        where organization_id=:oid and path like :pat and deleted_at is null
    """), {"oid": org_id, "pat": f"{folder}/%"})
    return [(row[0], row[1]) for row in r.fetchall()]


async def refresh() -> dict:
    # 遍历所有带 conventions 的系统（PLM/SCM/...），把重新渲染的文件（含 identifiers.md）
    # 幂等 upsert 到各自现有的部门级 scope 副本。
    systems = [s for s in seed.SYSTEMS if s.get("conventions")]
    updated = []
    async with async_session_factory() as db:
        org = await _get_org(db)
        for s in systems:
            folder = s["folder"]
            files = seed._files_for(
                folder, s["label"], s["object_types"], s["link_types"],
                s["action_types"], s["summary"],
                s.get("conventions"), s.get("code_mappings"),
            )
            scopes = await _find_dept_scopes_for_folder(db, str(org.id), folder)
            if not scopes:
                logger.warning("no_dept_scopes", folder=folder,
                               msg=f"未找到任何 {folder}/* 本体副本；先跑 seed_starclothing_ontology.py + reorg_starclothing_scope.py")
            for scope_type, scope_id in scopes:
                for path, content, meta in files:
                    await upsert_file(
                        db, org_id=org.id, scope_type=scope_type, scope_id=scope_id,
                        data=OntologyFileCreate(path=path, content=content, metadata=meta,
                                               scope_type=scope_type, scope_id=scope_id),
                    )
                    updated.append({"folder": folder, "scope": f"{scope_type}/{scope_id}", "path": path})
                logger.info("ontology_refreshed", folder=folder, scope_type=scope_type, scope_id=str(scope_id), files=len(files))
            await db.commit()
    return {"systems": len(systems), "updated": updated}


def _print_report(result: dict) -> None:
    print("\n" + "=" * 64)
    print("本体刷新完成（幂等 upsert 到现有部门级副本；含 identifiers.md）")
    print("-" * 64)
    by_scope: dict[str, list[str]] = {}
    for u in result["updated"]:
        by_scope.setdefault(u["scope"], []).append(u["path"])
    for scope, paths in by_scope.items():
        print(f"\n  [{scope}]")
        for p in paths:
            print(f"    - {p}")
    print("-" * 64)
    print("对应部门用户下次跑任务时即可看到新 identifiers.md。")
    print("=" * 64)


if __name__ == "__main__":
    res = asyncio.run(refresh())
    _print_report(res)
