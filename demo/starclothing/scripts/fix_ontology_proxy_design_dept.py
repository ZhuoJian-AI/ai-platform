"""补 SCM 本体 proxy 到 设计部（PD-2 用）"""
import asyncio
from app.database import async_session_factory
from sqlalchemy import text

ORG_ID = '54f5f892-cf08-4a75-88b2-b649fea392a4'
DESIGN_DEPT = '1aa0ff87-010f-49b5-98e6-e86bbc16d82d'  # 设计部
SUPPLY_DEPT = '4dfa88d7-0258-40d0-b4c0-e869decb7412'   # 供应链部 (SCM 原 scope)

async def main():
    async with async_session_factory() as db:
        # 拿供应链部 SCM 本体（已 scope 化的）
        r = await db.execute(text("""
            select path, content, metadata::text from ontology_files
            where organization_id=:oid and path like 'SCM/%' and scope_type='department' and scope_id=:sid and deleted_at is null
        """), {'oid': ORG_ID, 'sid': SUPPLY_DEPT})
        rows = r.fetchall()
        print(f"source SCM ontology_files in 供应链部: {len(rows)}")
        for (path, content, metadata) in rows:
            await db.execute(text("""
                insert into ontology_files (id, organization_id, scope_type, scope_id, path, size, content_hash, content, metadata)
                values (gen_random_uuid(), :oid, 'department', :sid, :path, length(:content), '', :content, CAST(:meta AS jsonb))
            """), {
                'oid': ORG_ID, 'sid': DESIGN_DEPT, 'path': path,
                'content': content, 'meta': metadata,
            })
        # ontology_folder
        await db.execute(text("""
            insert into ontology_folders (id, organization_id, scope_type, scope_id, path)
            values (gen_random_uuid(), :oid, 'department', :sid, 'SCM')
            on conflict do nothing
        """), {'oid': ORG_ID, 'sid': DESIGN_DEPT})
        await db.commit()
        print(f"proxied {len(rows)} SCM ontology_files + 1 folder -> 设计部")

asyncio.run(main())
