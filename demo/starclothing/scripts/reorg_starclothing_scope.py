"""一次性迁移：fabric-buyer → fabric-dev + 部门级重新实现数据接口/技能/本体/RAG + agents 绑定部门 workspace + skill_ids 更新"""
import asyncio
import json
from app.database import async_session_factory
from sqlalchemy import text
from app.auth.security import hash_password

ORG_ID = '54f5f892-cf08-4a75-88b2-b649fea392a4'  # starclothing

# 部门 id 映射
DEPT = {
    'executive':  '9411dd4b-84a2-405e-9817-af8f9a2f6a15',  # 总经办
    'design':     '1aa0ff87-010f-49b5-98e6-e86bbc16d82d',  # 设计部
    'dev':        '6cb5dc48-ac06-4351-b1fc-309148bc55e6',  # 开发部
    'merch':      '610abe2f-4559-4a96-bf71-9afb56411434',  # 商品部
    'supply':     '4dfa88d7-0258-40d0-b4c0-e869decb7412',  # 供应链部
    'quality':    '3e196391-2507-4711-995b-13417ffb5a40',  # 品控部
    'production': '9d794d30-2a48-4e0d-940d-398234ee9b8c',  # 生产部
    'finance':    'eeeb22f6-076c-4ed9-b7a9-a01e8c0eceac',  # 财务部
    'hr':         '42ca84d3-fbd0-4576-a285-aea0c1586f9d',  # 人力资源部
    'it':         '26256df3-370e-4c28-9c3d-bb2d5054c273',  # 信息技术部
}

# 团队 id
TEAM = {
    'fabric-dev-team': '01411b98-1308-4aa1-8998-8003eff60f8c',  # 设计部·面料开发组
}

# 每个 (部门, mock系统) 对应的 skill slug + data_system name + connector slug
# connector slug 是 org 级 tool_connector 的 slug，5 个 mock 系统已存在
SYSTEM_MAP = {
    'plm': {'name': 'PLM 产品生命周期系统（服装）（星途）', 'slug': 'starclothing-plm-query', 'desc': '星途 PLM 查询技能'},
    'scm': {'name': 'SCM 供应链协同系统（服装）（星途）', 'slug': 'starclothing-scm-query', 'desc': '星途 SCM 查询技能'},
    'mes': {'name': 'MES 制造执行系统（星途）', 'slug': 'starclothing-mes-query', 'desc': '星途 MES 查询技能'},
    'erp': {'name': 'ERP 资源计划系统（星途）', 'slug': 'starclothing-erp-query', 'desc': '星途 ERP 查询技能'},
    'crm': {'name': 'CRM 工业销售系统（星途）', 'slug': 'starclothing-crm-query', 'desc': '星途 CRM 查询技能'},
}

# 每个场景的归口部门 + 需要的 mock 系统
SCENARIO_DEPTS = {
    'PD-1': {'dept': 'dev',        'systems': ['plm']},
    'PD-2': {'dept': 'design',     'systems': ['scm']},
    'PD-3': {'dept': 'quality',    'systems': ['plm']},  # + defect RAG (own)
    'SC-1': {'dept': 'supply',     'systems': ['scm', 'mes']},
    'SC-2': {'dept': 'production', 'systems': ['mes', 'scm']},
    'SC-3': {'dept': 'finance',    'systems': ['erp', 'mes', 'crm']},
    'SC-4': {'dept': 'merch',      'systems': ['crm', 'scm', 'erp']},
}

# agent slug → 场景
AGENT_SCENARIO = {
    'starclothing-pd1-product-monitor':    'PD-1',
    'starclothing-pd2-fabric-library':     'PD-2',
    'starclothing-pd3-defect-closure':     'PD-3',
    'starclothing-sc1-material-validation':'SC-1',
    'starclothing-sc2-factory-scheduling': 'SC-2',
    'starclothing-sc3-reconciliation':     'SC-3',
    'starclothing-sc4-price-comparison':   'SC-4',
}

# 部门 workspace slug 映射
DEPT_WS_SLUG = {
    'executive': 'executive', 'design': 'design', 'dev': 'dev', 'merch': 'merch',
    'supply': 'supply', 'quality': 'quality', 'production': 'production',
    'finance': 'finance', 'hr': 'hr', 'it': 'it',
}


async def fetch_existing_org_skill_folder(db, slug):
    """拿 org 级原 skill_folder id（要被删的） + 它的 skill.md manifest 内容 + bound_endpoint_ids"""
    r = await db.execute(text("""
        select id from skill_folders
        where organization_id=:oid and slug=:slug and scope_type='organization' and deleted_at is null
    """), {'oid': ORG_ID, 'slug': slug})
    row = r.first()
    return str(row[0]) if row else None


async def fetch_skill_files(db, folder_id):
    """拿 skill_folder 下所有文件（path + content）"""
    r = await db.execute(text("""
        select path, content from skill_files
        where skill_folder_id=:fid and deleted_at is null
    """), {'fid': folder_id})
    return [(row[0], row[1]) for row in r.fetchall()]


async def fetch_data_system_id(db, name):
    r = await db.execute(text("""
        select id from data_systems
        where organization_id=:oid and name=:name and scope_type='organization' and deleted_at is null
    """), {'oid': ORG_ID, 'name': name})
    row = r.first()
    return str(row[0]) if row else None


async def fetch_data_interfaces(db, system_id):
    r = await db.execute(text("""
        select name, method, path, description, params_schema::text, response_schema::text, is_active
        from data_interfaces
        where data_system_id=:sid and deleted_at is null
    """), {'sid': system_id})
    return [(row[0], row[1], row[2], row[3], row[4], row[5], row[6]) for row in r.fetchall()]


async def fetch_tool_endpoints_for_system(db, system_key):
    """mock system key (plm/scm/mes/erp/crm) -> tool_endpoints for that system (by connector slug)"""
    connector_slug = f"starclothing-{system_key}"  # 原 connector slug
    r = await db.execute(text("""
        select te.id, te.name, te.method, te.path, te.description, te.params_schema, te.response_schema, te.is_active
        from tool_endpoints te
        join tool_connectors tc on tc.id=te.connector_id
        where tc.organization_id=:oid and tc.slug=:slug and tc.deleted_at is null and te.deleted_at is null
    """), {'oid': ORG_ID, 'slug': connector_slug})
    return [(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]) for row in r.fetchall()]


async def fetch_workspace_id(db, slug):
    r = await db.execute(text("""
        select id from workspaces
        where organization_id=:oid and slug=:slug and deleted_at is null
    """), {'oid': ORG_ID, 'slug': slug})
    row = r.first()
    return str(row[0]) if row else None


async def fetch_defect_rag_id(db):
    r = await db.execute(text("""
        select id from rag_collections
        where organization_id=:oid and slug='kb-5f1da53fcd25' and deleted_at is null
    """), {'oid': ORG_ID})
    row = r.first()
    return str(row[0]) if row else None


async def main():
    async with async_session_factory() as db:
        # ── 阶段 0：改造 fabric-buyer → fabric-dev ──
        print("=== Phase 0: fabric-buyer → fabric-dev ===")
        hashed = hash_password('12345678')
        r = await db.execute(text("""
            update users set
              username='fabric-dev',
              display_name='面料开发员',
              department_id=:dept,
              team_id=:team,
              password_hash=:pw,
              must_change_password=false
            where username='fabric-buyer' and organization_id=:oid
        """), {
            'dept': DEPT['design'], 'team': TEAM['fabric-dev-team'],
            'pw': hashed, 'oid': ORG_ID,
        })
        print(f"  fabric-buyer -> fabric-dev: {r.rowcount} row")
        # 也把 fabric-buyer 的 user-scoped workspace 重命名
        r = await db.execute(text("""
            update workspaces set
              slug='fabric-dev',
              name='面料开发员',
              scope_id=(select id::text from users where username='fabric-dev' and organization_id=:oid)
            where slug='afdb611e-1feb-47a4-9aab-80fdd139773d' and organization_id=:oid
        """), {'oid': ORG_ID})
        print(f"  fabric-buyer workspace renamed: {r.rowcount} row")

        # ── 阶段 1：收集 org 级原资源数据（skill + data_system + data_interface + tool_endpoints） ──
        print("\n=== Phase 1: snapshot org-level resources ===")
        snapshots = {}  # system_key -> {skill_folder_id, skill_files, data_system_id, data_interfaces, tool_endpoints}
        for sys_key in ['plm', 'scm', 'mes', 'erp', 'crm']:
            info = SYSTEM_MAP[sys_key]
            sf_id = await fetch_existing_org_skill_folder(db, info['slug'])
            ds_id = await fetch_data_system_id(db, info['name'])
            sfiles = await fetch_skill_files(db, sf_id) if sf_id else []
            dis = await fetch_data_interfaces(db, ds_id) if ds_id else []
            tes = await fetch_tool_endpoints_for_system(db, sys_key)
            snapshots[sys_key] = {
                'skill_folder_id': sf_id, 'skill_files': sfiles,
                'data_system_id': ds_id, 'data_interfaces': dis,
                'tool_endpoints': tes,
            }
            print(f"  {sys_key}: skill_folder={sf_id} files={len(sfiles)} data_system={ds_id} di={len(dis)} tool_endpoints={len(tes)}")

        # ── 阶段 2：按场景归口部门创建 dept 级 data_system + data_interfaces + skill_folder + skill_files ──
        print("\n=== Phase 2: create dept-level data_systems + skill_folders ===")
        # 累积每个部门拥有的 skill IDs，最后回填 agent.skill_ids
        agent_skill_ids = {agent_slug: [] for agent_slug in AGENT_SCENARIO.keys()}

        # 遍历每个 (部门, mock系统) 对，创建 dept 级资源
        created_pairs = set()
        for scenario, info in SCENARIO_DEPTS.items():
            dept_key = info['dept']
            dept_id = DEPT[dept_key]
            for sys_key in info['systems']:
                pair = (dept_key, sys_key)
                if pair in created_pairs:
                    continue
                created_pairs.add(pair)
                snap = snapshots[sys_key]
                info_map = SYSTEM_MAP[sys_key]

                # 2.1 创建 dept 级 data_system
                r = await db.execute(text("""
                    insert into data_systems (id, organization_id, scope_type, scope_id, name, description, is_active)
                    values (gen_random_uuid(), :oid, 'department', :sid, :name, :desc, true)
                    returning id
                """), {
                    'oid': ORG_ID, 'sid': dept_id,
                    'name': info_map['name'], 'desc': f"{info_map['desc']}（{dept_key} 部门级）",
                })
                new_ds_id = str(r.first()[0])

                # 2.2 复制 data_interfaces 到新 data_system
                for (name, method, path, desc, ps, rs, is_active) in snap['data_interfaces']:
                    await db.execute(text("""
                        insert into data_interfaces (id, data_system_id, name, method, path, description, params_schema, response_schema, is_active)
                        values (gen_random_uuid(), :sid, :name, :method, :path, :desc, CAST(:ps AS jsonb), CAST(:rs AS jsonb), :ia)
                    """), {
                        'sid': new_ds_id, 'name': name, 'method': method, 'path': path,
                        'desc': desc, 'ps': ps, 'rs': rs, 'ia': is_active,
                    })
                print(f"  {scenario} ({dept_key}): data_system={info_map['name']} ({len(snap['data_interfaces'])} interfaces) created")

                # 2.3 创建 dept 级 skill_folder
                r = await db.execute(text("""
                    insert into skill_folders (id, organization_id, scope_type, scope_id, name, slug)
                    values (gen_random_uuid(), :oid, 'department', :sid, :name, :slug)
                    returning id
                """), {
                    'oid': ORG_ID, 'sid': dept_id,
                    'name': f"{info_map['desc']}（{dept_key}）",
                    'slug': info_map['slug'],
                })
                new_sf_id = str(r.first()[0])

                # 2.4 复制 skill_files (skill.md + 其他) 到新 skill_folder
                for (path, content) in snap['skill_files']:
                    await db.execute(text("""
                        insert into skill_files (id, skill_folder_id, path, content)
                        values (gen_random_uuid(), :fid, :path, :content)
                    """), {'fid': new_sf_id, 'path': path, 'content': content})
                print(f"  {scenario} ({dept_key}): skill_folder={info_map['slug']} ({len(snap['skill_files'])} files) created id={new_sf_id}")

                # 2.5 给 agent 累加 skill_id（按 scenario）
                agent_slug = next(a for a, s in AGENT_SCENARIO.items() if s == scenario)
                agent_skill_ids[agent_slug].append(new_sf_id)

        # ── 阶段 3：删除 org 级原 skill_folders + data_systems ──
        print("\n=== Phase 3: delete org-level originals ===")
        for sys_key in ['plm', 'scm', 'mes', 'erp', 'crm']:
            snap = snapshots[sys_key]
            # 删 org 级 skill_folder（级联删 skill_files，由 FK ON DELETE CASCADE 处理）
            if snap['skill_folder_id']:
                r = await db.execute(text("""
                    delete from skill_folders where id=:id and scope_type='organization'
                """), {'id': snap['skill_folder_id']})
                print(f"  {sys_key} org skill_folder deleted: {r.rowcount}")
            # 删 org 级 data_system
            if snap['data_system_id']:
                r = await db.execute(text("""
                    delete from data_systems where id=:id and scope_type='organization'
                """), {'id': snap['data_system_id']})
                print(f"  {sys_key} org data_system deleted: {r.rowcount}")

        # ── 阶段 4：拆分 ontology_files ──
        print("\n=== Phase 4: re-scope ontology files ===")
        # PLM/* → 开发部；SCM/* → 供应链部；Cross/* 保留 org
        r = await db.execute(text("""
            update ontology_files set scope_type='department', scope_id=:sid
            where organization_id=:oid and path like 'PLM/%' and scope_type='organization'
        """), {'oid': ORG_ID, 'sid': DEPT['dev']})
        print(f"  PLM/* ontology_files moved to 开发部: {r.rowcount}")
        r = await db.execute(text("""
            update ontology_files set scope_type='department', scope_id=:sid
            where organization_id=:oid and path like 'SCM/%' and scope_type='organization'
        """), {'oid': ORG_ID, 'sid': DEPT['supply']})
        print(f"  SCM/* ontology_files moved to 供应链部: {r.rowcount}")
        # ontology_folders 同步
        r = await db.execute(text("""
            update ontology_folders set scope_type='department', scope_id=:sid
            where organization_id=:oid and path='PLM' and scope_type='organization'
        """), {'oid': ORG_ID, 'sid': DEPT['dev']})
        print(f"  PLM ontology_folder moved: {r.rowcount}")
        r = await db.execute(text("""
            update ontology_folders set scope_type='department', scope_id=:sid
            where organization_id=:oid and path='SCM' and scope_type='organization'
        """), {'oid': ORG_ID, 'sid': DEPT['supply']})
        print(f"  SCM ontology_folder moved: {r.rowcount}")

        # 按需 proxy 复制本体到其他部门
        # PD-3 品控部需要 PLM 本体 → 复制
        # SC-2 生产部需要 SCM 本体 → 复制
        # SC-4 商品部需要 SCM 本体 → 复制
        # SC-1 供应链部已有 SCM 本体（own） → 不需要复制
        # SC-3 财务部需要 MES+CRM 本体 → 无 MES/CRM 本体，跳过
        proxy_targets = [
            ('PLM/*', DEPT['quality'], '品控部'),  # for PD-3
            ('SCM/*', DEPT['production'], '生产部'),  # for SC-2
            ('SCM/*', DEPT['merch'], '商品部'),  # for SC-4
        ]
        for src_pattern, target_dept_id, target_dept_name in proxy_targets:
            prefix = src_pattern.rstrip('/*')
            # 拿源部门最新本体（已 scope 化）
            r = await db.execute(text("""
                select path, content, metadata::text from ontology_files
                where organization_id=:oid and path like :pat and scope_type='department' and scope_id=:sid and deleted_at is null
            """), {'oid': ORG_ID, 'pat': f"{prefix}%", 'sid': DEPT['dev'] if prefix == 'PLM' else DEPT['supply']})
            for (path, content, metadata) in r.fetchall():
                # 复制到目标部门
                await db.execute(text("""
                    insert into ontology_files (id, organization_id, scope_type, scope_id, path, size, content_hash, content, metadata)
                    values (gen_random_uuid(), :oid, 'department', :sid, :path, length(:content), '', :content, CAST(:meta AS jsonb))
                """), {
                    'oid': ORG_ID, 'sid': target_dept_id, 'path': path,
                    'content': content, 'meta': metadata,
                })
            print(f"  proxy {prefix}/* -> {target_dept_name}: {r.rowcount} files")

        # ontology_folders 也 proxy 一份
        for src_path, target_dept_id, target_dept_name in [
            ('PLM', DEPT['quality'], '品控部'),
            ('SCM', DEPT['production'], '生产部'),
            ('SCM', DEPT['merch'], '商品部'),
        ]:
            src_dept_id = DEPT['dev'] if src_path == 'PLM' else DEPT['supply']
            await db.execute(text("""
                insert into ontology_folders (id, organization_id, scope_type, scope_id, path)
                values (gen_random_uuid(), :oid, 'department', :sid, :path)
                on conflict do nothing
            """), {'oid': ORG_ID, 'sid': target_dept_id, 'path': src_path})
            print(f"  proxy ontology_folder {src_path} -> {target_dept_name}")

        # ── 阶段 5：拆分 defect RAG → 品控部 ──
        print("\n=== Phase 5: re-scope defect RAG to 品控部 ===")
        rag_id = await fetch_defect_rag_id(db)
        if rag_id:
            r = await db.execute(text("""
                update rag_collections set scope_type='department', scope_id=:sid
                where id=:rid and scope_type='organization'
            """), {'rid': rag_id, 'sid': DEPT['quality']})
            print(f"  defect RAG moved to 品控部: {r.rowcount}")

        # ── 阶段 6：绑定 agents 到部门 workspace + 更新 skill_ids ──
        print("\n=== Phase 6: bind agents to dept workspaces + update skill_ids ===")
        for agent_slug, scenario in AGENT_SCENARIO.items():
            dept_key = SCENARIO_DEPTS[scenario]['dept']
            ws_slug = DEPT_WS_SLUG[dept_key]
            ws_id = await fetch_workspace_id(db, ws_slug)
            skills = agent_skill_ids[agent_slug]
            # PD-3 还要绑定 RAG
            extra = {}
            if scenario == 'PD-3' and rag_id:
                extra['rag_collection_id'] = rag_id
            if 'rag_collection_id' in extra:
                sql = """update agents set workspace_id=CAST(:ws_id AS uuid), skill_ids=CAST(:skill_ids_arr AS jsonb), rag_collection_id=CAST(:rag_collection_id AS uuid) where slug=:slug and organization_id=:oid"""
                params = {'ws_id': ws_id, 'skill_ids_arr': json.dumps(skills), 'rag_collection_id': extra['rag_collection_id'], 'slug': agent_slug, 'oid': ORG_ID}
            else:
                sql = """update agents set workspace_id=CAST(:ws_id AS uuid), skill_ids=CAST(:skill_ids_arr AS jsonb) where slug=:slug and organization_id=:oid"""
                params = {'ws_id': ws_id, 'skill_ids_arr': json.dumps(skills), 'slug': agent_slug, 'oid': ORG_ID}
            r = await db.execute(text(sql), params)
            print(f"  {agent_slug} ({scenario}) -> {dept_key} ws={ws_slug} skills={len(skills)}")

        await db.commit()
        print("\n=== DONE ===")


asyncio.run(main())
