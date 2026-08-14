"""从 ClawHub (https://clawhub.ai) 拉取技能整包并导入到指定组织的技能文件夹。

一个 ClawHub 技能 = 一个文件夹（SKILL.md + 支撑文件）。本平台技能模型与之同构：
SkillFolder（节点作用域）+ SkillFile（path + 文本 content）。本脚本把整包文件逐个写入
目标组织下的 SkillFolder，幂等（按 org+scope+slug 去重，已存在则复用并 upsert 文件）。

格式兼容性说明：ClawHub 的 SKILL.md 采用 YAML frontmatter（OpenClaw 格式）；本平台
runtime（app/agents/graph/nodes.py:_build_tools）查找 ``skill.md`` 并解析其中的
```skill JSON 块来注册 function-tool。因此导入时把 SKILL.md 落到平台约定的 manifest
路径 ``skill.md``，使其在「技能」页可被发现；但由于缺少 ```skill 块，agent runtime
会跳过它（不报错）——导入后作为技能文件库可见，需另附 manifest 块才能注册为可调用工具。

用法:
    cd llm_router/backend
    python scripts/import_clawhub_skill.py --slug docx-cn --org 敏睿制造
    # 可选: --scope-type organization --scope-id <dept/team/user id> --version 1.0.1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from uuid import UUID

# 确保能把 `app` 包导入（脚本从 backend/ 目录运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.organization import Organization
from app.models.skill import SkillFolder
from app.schemas.skill import SkillFileCreate, SkillFolderCreate
from app.services.skill_store_service import create_folder, list_folders, upsert_file

# 抑制 SQLAlchemy echo 噪声
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = structlog.get_logger()

CLAWHUB_BASE = "https://clawhub.ai"
# ClawHub canonical manifest → 本平台 runtime 约定的 manifest 路径
MANIFEST_RENAME = {"SKILL.md": "skill.md", "skills.md": "skill.md"}


def _curl(url: str, binary: bool = False, timeout: int = 60) -> bytes | dict:
    """用 curl 取数（本机 Python urllib SSL 校验失败，curl 正常）。"""
    proc = subprocess.run(
        ["curl", "-sS", "-L", "--fail", "-m", str(timeout), "-A", "Mozilla/5.0", url],
        capture_output=True, timeout=timeout + 10,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed ({proc.returncode}) for {url}: {proc.stderr.decode()[:200]}")
    data = proc.stdout
    return data if binary else json.loads(data.decode("utf-8"))


def _http_json(url: str) -> dict:
    return _curl(url, binary=False, timeout=30)  # type: ignore[return-value]


def _resolve_version(slug: str, version: str | None) -> tuple[str, dict, str | None, str]:
    """返回 (选中版本号, 版本详情, owner handle, display name)。version=None 取 latest。"""
    info = _http_json(f"{CLAWHUB_BASE}/api/v1/skills/{slug}")
    owner = (info.get("owner") or {}).get("handle")
    display_name = (info.get("skill") or info).get("displayName") or slug
    selected = version or (info.get("latestVersion") or {}).get("version")
    if not selected:
        raise RuntimeError(f"ClawHub skill '{slug}' 无可用版本")
    detail = _http_json(f"{CLAWHUB_BASE}/api/v1/skills/{slug}/versions/{selected}")
    return selected, detail, owner, display_name


async def _get_or_create_folder(
    db: AsyncSession, org_id: UUID, slug: str, name: str,
    scope_type: str, scope_id: str | None,
) -> SkillFolder:
    existing = await list_folders(db, org_id, scope_type, scope_id)
    for f in existing:
        if f.slug == slug:
            logger.info("skill_folder_reuse", slug=slug, folder_id=str(f.id))
            return f
    return await create_folder(db, org_id, SkillFolderCreate(
        name=name, slug=slug, scope_type=scope_type, scope_id=scope_id,
    ))


async def import_skill(
    slug: str, org_name: str, scope_type: str, scope_id: str | None,
    version: str | None, dry_run: bool,
) -> None:
    selected_version, detail, owner, display_name = _resolve_version(slug, version)
    skill = detail.get("skill", {})
    files = detail.get("version", {}).get("files", []) or []
    logger.info("clawhub_resolved", slug=slug, version=selected_version,
                files=len(files), owner=owner, display_name=display_name)

    if dry_run:
        for f in files:
            print(f"  [dry-run] {f['path']}  ({f.get('size')} B)")
        return

    # 下载整包 ZIP 并解包（比逐文件 /file 拉取更省、更稳）
    import io, zipfile
    url = f"{CLAWHUB_BASE}/api/v1/download?slug={slug}"
    if selected_version:
        url += f"&version={selected_version}"
    zf = zipfile.ZipFile(io.BytesIO(_curl(url, binary=True)))  # type: ignore[arg-type]
    bundle = {n: zf.read(n) for n in zf.namelist()}

    async with async_session_factory() as db:
        # 定位组织（按名称，回退 slug）
        r = await db.execute(select(Organization).where(Organization.deleted_at.is_(None)))
        org = next((o for o in r.scalars().all() if o.name == org_name or o.slug == org_name), None)
        if org is None:
            raise RuntimeError(f"组织 '{org_name}' 不存在")
        org_id = org.id

        folder = await _get_or_create_folder(
            db, org_id, slug=slug, name=f"{display_name}（ClawHub:{slug}）",
            scope_type=scope_type, scope_id=scope_id,
        )

        provenance = {
            "clawhub_slug": slug, "clawhub_version": selected_version,
            "clawhub_owner": owner, "source": f"{CLAWHUB_BASE}/{owner}/skills/{slug}",
        }
        written = 0
        for entry in files:
            path = entry["path"]
            data = bundle.get(path)
            if data is None:
                logger.warning("file_missing_in_zip", path=path)
                continue
            # 文本化（平台 SkillFile.content 为 TEXT 列；本技能所有文件均为文本）
            content = data.decode("utf-8", errors="replace")
            store_path = MANIFEST_RENAME.get(path, path)
            meta = {**provenance, "original_path": path, "sha256": entry.get("sha256")}
            await upsert_file(db, folder, SkillFileCreate(
                path=store_path, content=content, metadata=meta,
            ))
            written += 1
            logger.info("skill_file_upserted", path=store_path, size=len(content))

        await db.commit()
        print(f"\n✅ 导入完成：组织「{org.name}」 / 技能文件夹 slug={slug} "
              f"（version {selected_version}，{written} 文件）")
        print(f"   folder_id = {folder.id}")
        print(f"   作用域: scope_type={scope_type}, scope_id={scope_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description="从 ClawHub 导入技能到组织")
    ap.add_argument("--slug", required=True, help="ClawHub 技能 slug，如 docx-cn")
    ap.add_argument("--org", required=True, help="目标组织名称或 slug，如 敏睿制造")
    ap.add_argument("--scope-type", default="organization",
                    choices=["organization", "department", "team", "user"])
    ap.add_argument("--scope-id", default=None, help="部门/团队/用户 id（organization 作用域留空）")
    ap.add_argument("--version", default=None, help="指定版本；缺省取 latest")
    ap.add_argument("--dry-run", action="store_true", help="只解析不写入")
    args = ap.parse_args()
    asyncio.run(import_skill(
        slug=args.slug, org_name=args.org, scope_type=args.scope_type,
        scope_id=args.scope_id, version=args.version, dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
