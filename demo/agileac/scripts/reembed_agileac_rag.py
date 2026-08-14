"""对敏睿空调 RAG 集合中所有 embedding IS NULL 的 chunks 回填向量。

参数化 collection：按集合名称（默认全部 agileac 集合）回填。

前置条件：组织级需配置一个 OpenAI 兼容的 embedding provider（如阿里云通义
text-embedding-v4 或 OpenAI text-embedding-3-small）。否则 `llm_client.embed`
会抛异常，本脚本打印失败计数。

幂等：只更新 embedding IS NULL 的 chunk；已嵌入的跳过。

用法（容器内）：
    docker cp demo/agileac/scripts/reembed_agileac_rag.py ai_infra_backend:/app/scripts/
    # 全部 agileac 集合回填：
    docker exec ai_infra_backend python scripts/reembed_agileac_rag.py
    # 单个集合（按名称）：
    docker exec ai_infra_backend python scripts/reembed_agileac_rag.py 售后故障与维修知识库
"""
import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
if not (_BACKEND / "app" / "database.py").exists():
    _BACKEND = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND.parent.parent / "mock"))

from sqlalchemy import select, update  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.rag import RagChunk, RagCollection  # noqa: E402
from app.agents import llm_client  # noqa: E402

ORG_SLUG = "agileac"
BATCH = 8  # 受 Aliyun text-embedding-v4 单批 10 上限制约


async def _get_org_id(db) -> str:
    org = (await db.execute(
        select(Organization).where(Organization.slug == ORG_SLUG, Organization.deleted_at.is_(None))
    )).scalar_one_or_none()
    if org is None:
        raise RuntimeError(f"组织 slug='{ORG_SLUG}' 不存在，请先运行 seed_agileac_org.py。")
    return org.id


async def _embed_collection(db, coll: RagCollection, org_id: str) -> tuple[int, int]:
    rows = (await db.execute(
        select(RagChunk.id, RagChunk.content).where(
            RagChunk.collection_id == coll.id,
            RagChunk.embedding.is_(None),
        ).order_by(RagChunk.created_at)
    )).all()
    if not rows:
        print(f"  [{coll.name}] nothing to do (all chunks embedded)")
        return 0, 0

    done = fail = 0
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        texts = [r.content for r in batch]
        try:
            vecs = await llm_client.embed(db, org_id, coll.embedding_model, texts)
        except Exception as exc:  # noqa: BLE001 — 嵌入失败不阻断，下批继续
            print(f"  [{coll.name}] batch {start}+{len(batch)} embed failed: {exc}")
            fail += len(batch)
            continue
        if not vecs or len(vecs) != len(batch):
            print(f"  [{coll.name}] batch {start}+{len(batch)} returned {len(vecs) if vecs else 0} vecs, expected {len(batch)}")
            fail += len(batch)
            continue
        for r, v in zip(batch, vecs, strict=False):
            await db.execute(update(RagChunk).where(RagChunk.id == r.id).values(embedding=v))
        await db.commit()
        done += len(batch)
        print(f"  [{coll.name}] batch {start}+{len(batch)}: embedded (total {done}/{len(rows)})")

    return done, fail


async def main(collection_name: str | None = None) -> None:
    async with async_session_factory() as db:
        org_id = await _get_org_id(db)
        print(f"org: {ORG_SLUG} ({org_id})")

        # 拉取目标集合
        if collection_name:
            colls = (await db.execute(
                select(RagCollection).where(RagCollection.name == collection_name)
            )).scalars().all()
        else:
            # 拉取所有 agileac 集合（同组织下 scope_type 不同的所有集合）
            # 通过 collection_id IN (RagCollection under org via scope) — RagCollection 无 org_id 列直接关联，
            # 但 scope_id 为 org 下的 dept/team/id；用 join Department + Team + scope_type='organization' 三路
            from app.models.department import Department
            from app.models.team import Team
            org_colls = (await db.execute(
                select(RagCollection).where(
                    RagCollection.scope_type == "organization",
                    RagCollection.scope_id.is_(None),
                )
            )).scalars().all()
            dept_ids = [d.id for d in (await db.execute(
                select(Department).where(Department.organization_id == org_id, Department.deleted_at.is_(None))
            )).scalars().all()]
            team_ids = []
            if dept_ids:
                team_rows = (await db.execute(
                    select(Team).where(Team.department_id.in_(dept_ids), Team.deleted_at.is_(None))
                )).scalars().all()
                team_ids = [t.id for t in team_rows]
            dept_str_ids = [str(d) for d in dept_ids]
            team_str_ids = [str(t) for t in team_ids]
            dept_colls = (await db.execute(
                select(RagCollection).where(
                    RagCollection.scope_type == "department",
                    RagCollection.scope_id.in_(dept_str_ids),
                )
            )).scalars().all() if dept_str_ids else []
            team_colls = (await db.execute(
                select(RagCollection).where(
                    RagCollection.scope_type == "team",
                    RagCollection.scope_id.in_(team_str_ids),
                )
            )).scalars().all() if team_str_ids else []
            colls = list(org_colls) + list(dept_colls) + list(team_colls)

        if not colls:
            print(f"no collections found for org={ORG_SLUG}" + (f" name={collection_name}" if collection_name else ""))
            return

        print(f"target collections: {len(colls)}")
        total_done = total_fail = 0
        for coll in colls:
            print(f"\n=== {coll.name} (scope={coll.scope_type}, embed={coll.embedding_model}, chunk={coll.chunk_size}/{coll.chunk_overlap}) ===")
            done, fail = await _embed_collection(db, coll, org_id)
            total_done += done
            total_fail += fail
            # 验证
            cnt = (await db.execute(
                select(RagChunk.id).where(RagChunk.collection_id == coll.id, RagChunk.embedding.is_not(None))
            )).all()
            print(f"  verify: chunks with embedding now = {len(cnt)}")

        print(f"\n=== done: embedded={total_done}, failed={total_fail} ===")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(name))
