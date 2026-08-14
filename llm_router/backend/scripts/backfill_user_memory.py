"""一次性回填：为所有非管理员终端用户合并/补齐唯一一条个人记忆，并清理管理员残留工作空间。

背景：
- 个人记忆（scope_type='user'）现改为「每用户一份」markdown 记录，分 `## 个人档案`（系统端
  同步，可覆写）与 `## 沉淀记忆`（智能体沉淀，逐条追加）。旧版每条事实单独成行、profile
  单独成行，存量用户存在多条，此处合并为一条并软删多余行；缺失记录的补齐。
- 组织管理员（role='admin'）非终端用户，不持有个人记忆与工作空间；历史残留的 user 工作空间
  此处一并软删。

幂等：
- 记忆合并按 (org, user) 汇聚到一条，重复执行无新增（多余行已软删）。
- 管理员工作空间软删仅作用于未软删的残留行，重复执行无新增。

用法:
    cd llm_router/backend
    python scripts/backfill_user_memory.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# 确保能把 `app` 包导入（脚本从 backend/ 目录运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.user_service import consolidate_user_profile_memory  # noqa: E402

logger = structlog.get_logger()


async def backfill() -> dict:
    stats = {
        "orgs": 0,
        "members": 0,
        "memory_consolidated": 0,
        "memory_removed": 0,
        "admins": 0,
        "admin_ws_removed": 0,
    }
    async with async_session_factory() as db:
        orgs = list(
            (
                await db.execute(
                    select(Organization).where(Organization.deleted_at.is_(None))
                )
            ).scalars().all()
        )
        stats["orgs"] = len(orgs)

        for org in orgs:
            users = list(
                (
                    await db.execute(
                        select(User).where(
                            User.organization_id == org.id,
                            User.deleted_at.is_(None),
                        )
                    )
                ).scalars().all()
            )
            for u in users:
                if u.role == "admin":
                    stats["admins"] += 1
                    # 清理管理员残留的 user 工作空间（未软删）
                    ws = (
                        await db.execute(
                            select(Workspace).where(
                                Workspace.organization_id == org.id,
                                Workspace.scope_type == "user",
                                Workspace.scope_id == str(u.id),
                                Workspace.deleted_at.is_(None),
                            )
                        )
                    ).scalars().first()
                    if ws is not None:
                        ws.deleted_at = datetime.now(UTC)
                        await db.flush()
                        stats["admin_ws_removed"] += 1
                        logger.info("backfill_admin_ws_removed", user_id=str(u.id), org_id=str(org.id))
                    continue

                stats["members"] += 1
                result = await consolidate_user_profile_memory(db, u)
                stats["memory_consolidated"] += 1
                stats["memory_removed"] += result.get("removed", 0)
                logger.info(
                    "backfill_memory_consolidated",
                    user_id=str(u.id), org_id=str(org.id),
                    removed=result.get("removed", 0),
                )

        await db.commit()
    return stats


def _print_report(stats: dict) -> None:
    print("\n" + "=" * 64)
    print("个人记忆合并回填 + 管理员工作空间清理完成")
    print("-" * 64)
    print(f"  组织数:           {stats['orgs']}")
    print(f"  非管理员用户:     {stats['members']}  → 合并/补齐个人记忆 {stats['memory_consolidated']} 条，软删多余 {stats['memory_removed']} 条")
    print(f"  管理员用户:       {stats['admins']}  → 清理残留工作空间 {stats['admin_ws_removed']} 个")
    print("=" * 64)


if __name__ == "__main__":
    _print_report(asyncio.run(backfill()))
