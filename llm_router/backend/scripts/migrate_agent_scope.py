"""一次性迁移：把已落库的 demo Agent 从 org 级搬到部门级 scope。

背景：0032_agent_scope 迁移给 agents 加了 scope_type/scope_id（server_default 'organization'），
存量 demo Agent 全落在 org 级。新环境重跑 seed_*_agents.py 会直接落在部门级，无需本脚本；
仅对「已 seed 过旧版（org 级 agent）」的存量环境补一刀。

幂等：已是 department scope 的跳过；找不到 org/dept/agent 的告警不中断。

用法（容器内）:
    docker cp llm_router/backend/scripts/migrate_agent_scope.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/migrate_agent_scope.py
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.database import async_session_factory
from app.models.agent import Agent
from app.models.department import Department
from app.models.organization import Organization

# org slug → { agent slug → 归口部门 slug }（与各 seed_*_agents.py 的 SLUG_TO_DEPT 一致）
MAPPING: dict[str, dict[str, str]] = {
    "starclothing": {
        "starclothing-pd1-product-monitor": "dev",
        "starclothing-pd2-fabric-library": "design",
        "starclothing-pd3-defect-closure": "quality",
        "starclothing-sc1-material-validation": "supply",
        "starclothing-sc2-factory-scheduling": "production",
        "starclothing-sc3-reconciliation": "finance",
        "starclothing-sc4-price-comparison": "merch",
    },
    "agileac": {
        "agileac-rnd-01-translation": "rnd",
        "agileac-prd-01-product-params": "product",
        "agileac-mfg-01-production-report": "production",
        "agileac-qal-01-quality-report": "quality",
        "agileac-scm-01-procurement-logistics": "supply",
        "agileac-sal-01-sales-ecommerce": "sales",
        "agileac-svc-01-after-sales-diagnosis": "after-sales",
        "agileac-mkt-01-marketing-content": "marketing",
        "agileac-fin-01-reconciliation-receivable": "finance",
        "agileac-hr-01-hr-ops": "hr",
        "agileac-sal-02-reimbursement-status": "sales",
    },
}


async def run() -> None:
    async with async_session_factory() as db:
        for org_slug, slug_to_dept in MAPPING.items():
            org = (await db.execute(
                select(Organization).where(
                    Organization.slug == org_slug, Organization.deleted_at.is_(None)
                )
            )).scalar_one_or_none()
            if org is None:
                print(f"[skip] org '{org_slug}' 不存在，跳过")
                continue

            # 预取该 org 全部部门 slug→id
            dept_rows = (await db.execute(
                select(Department.id, Department.slug).where(
                    Department.organization_id == org.id, Department.deleted_at.is_(None)
                )
            )).all()
            dept_slug_to_id = {r[1]: str(r[0]) for r in dept_rows}

            moved = skipped = missing = 0
            for agent_slug, dept_slug in slug_to_dept.items():
                dept_id = dept_slug_to_id.get(dept_slug)
                if dept_id is None:
                    print(f"  [warn] dept '{dept_slug}' 不存在（org={org_slug}），跳过 agent '{agent_slug}'")
                    missing += 1
                    continue
                agent = (await db.execute(
                    select(Agent).where(
                        Agent.organization_id == org.id,
                        Agent.slug == agent_slug,
                        Agent.deleted_at.is_(None),
                    )
                )).scalar_one_or_none()
                if agent is None:
                    print(f"  [warn] agent '{agent_slug}' 不存在（org={org_slug}），跳过")
                    missing += 1
                    continue
                if agent.scope_type == "department" and agent.scope_id == dept_id:
                    skipped += 1
                    continue
                agent.scope_type = "department"
                agent.scope_id = dept_id
                moved += 1
                print(f"  [move] {agent_slug}: {agent.scope_type}/{agent.scope_id} → department/{dept_id}")
            await db.commit()
            print(f"[{org_slug}] moved={moved} skipped={skipped} missing={missing}")


if __name__ == "__main__":
    asyncio.run(run())
    sys.exit(0)
