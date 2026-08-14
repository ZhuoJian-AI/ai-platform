"""一次性维护脚本：对服装缺陷知识库 RAG 的所有 NULL embedding chunks 回填向量。

背景：seed_starclothing_defect_rag.py 跑的时候若 embedding provider 未配好、或
`_EMBED_BATCH`（rag_service.py）超过上游批次上限（Aliyun text-embedding-v4 为 10），
所有 chunks 的 embedding 列会留 NULL，retrieve() 退化为 keyword_fallback。

本脚本：
1. 拉取 collection 下所有 embedding IS NULL 的 RagChunk；
2. 按 BATCH 分批调 llm_client.embed() 拿向量；
3. UPDATE 对应 chunk 的 embedding 列。
幂等：只更新 embedding IS NULL 的 chunk；已嵌入的跳过。

用法（容器内）：
    docker cp demo/starclothing/scripts/reembed_defect_rag.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/reembed_defect_rag.py
"""
import asyncio
import sys
from pathlib import Path
from uuid import UUID

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/starclothing/scripts/ → backend=repo/llm_router/backend
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
if not (_BACKEND / "app" / "database.py").exists():
    _BACKEND = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND.parent.parent / "mock"))

from sqlalchemy import select, update  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models.rag import RagChunk, RagCollection  # noqa: E402
from app.agents import llm_client  # noqa: E402

COLLECTION_ID = UUID("874eb1e9-f470-4228-8258-49b386ee5279")
ORG_ID = UUID("54f5f892-cf08-4a75-88b2-b649fea392a4")
BATCH = 8


async def main():
    async with async_session_factory() as db:
        coll = await db.get(RagCollection, COLLECTION_ID)
        if coll is None:
            print(f"collection {COLLECTION_ID} not found")
            return
        print(f"collection: {coll.name} | embed_model={coll.embedding_model} | chunk={coll.chunk_size}/{coll.chunk_overlap}")

        rows = (await db.execute(
            select(RagChunk.id, RagChunk.content).where(
                RagChunk.collection_id == COLLECTION_ID,
                RagChunk.embedding.is_(None),
            ).order_by(RagChunk.created_at)
        )).all()
        print(f"chunks to embed: {len(rows)}")
        if not rows:
            print("nothing to do")
            return

        done = 0
        fail = 0
        for start in range(0, len(rows), BATCH):
            batch = rows[start:start + BATCH]
            texts = [r.content for r in batch]
            try:
                vecs = await llm_client.embed(db, ORG_ID, coll.embedding_model, texts)
            except Exception as exc:  # noqa: BLE001
                print(f"  batch {start} embed failed: {exc}")
                fail += len(batch)
                continue
            if not vecs or len(vecs) != len(batch):
                print(f"  batch {start} embed returned {len(vecs) if vecs else 0} vecs, expected {len(batch)}")
                fail += len(batch)
                continue
            for r, v in zip(batch, vecs, strict=False):
                await db.execute(update(RagChunk).where(RagChunk.id == r.id).values(embedding=v))
            await db.commit()
            done += len(batch)
            print(f"  batch {start}+{len(batch)}: embedded, committed (total {done}/{len(rows)})")

        print(f"\n=== done: embedded={done}, failed={fail}, total={len(rows)} ===")
        rs = (await db.execute(
            select(RagChunk.id).where(RagChunk.collection_id == COLLECTION_ID, RagChunk.embedding.is_not(None))
        )).all()
        print(f"verify: chunks with embedding now = {len(rs)}")


if __name__ == "__main__":
    asyncio.run(main())
