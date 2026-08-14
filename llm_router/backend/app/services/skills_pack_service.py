"""Skills 包打包服务 —— 为归口用户即时生成可被第三方智能体终端安装的 skills 包。

每个 skills 包 = 一个 zip，含：
- ``.mcp.json``：MCP server 端点 + **内嵌 Bearer（即时签发的 scoped API key）**，
  第三方终端（Claude Code / Codex / WorkBuddy）解压到项目根即可识别，无需再输凭证。
- ``README.md``：安装说明 + composer 示例（L4）。
- ``.claude/skills/<agent-slug>/SKILL.md``：每个归口用户 scope 内的 Agent 模板 → 一个
  Claude Code skill；body = Agent.system_prompt（L3 模板），顶部加 L1 调用约束。
- ``ontology/*.md``：归口用户 scope 内本体文件（L2 identifiers）原样导出，参考用。

鉴权即时轮换：每次导出撤销该用户上一份 skills-pack key、即时签发新 key，明文仅此一次
返回给用户（嵌入 zip 的 .mcp.json），库内只存加密件。
"""

from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import CurrentUser
from app.models.agent import Agent
from app.models.api_key import ApiKey
from app.models.organization import Organization
from app.schemas.api_key import ApiKeyCreate
from app.services import api_key_service, scope_service

# skills-pack key 命名前缀（按用户隔离，导出时撤销同 user 旧 key）
SKILLS_PACK_KEY_PREFIX = "skills-pack:"


# L1 调用约束（runtime 输出协议 + 工具调用策略的对外版本，写进每个 SKILL.md 顶部）
_L1_PREAMBLE = """<!-- L1 调用约束（runtime 输出协议 + 工具调用策略）-->
## 调用约束（必须遵守）

1. **不要臆造数据**：所有对象 ID / 标识符必须来自 `query_ontology` 或接口返回值，不得自行编造。
2. **最少端点集**：先 `list_skills` / `list_data_interfaces` 规划，再 `call_skill` 调用必要的最少端点；不要盲目全调。
3. **先文本后 Word**：分析过程先在文本里流式输出完整内容（评审参与者需实时看到推理），分析完成后再产出 Word 文档供归档分发；不要直接跳到文档生成而让屏幕只显示一句「现在生成报告」。
   - **本 skills 包未暴露 `generate_docx` 工具**（仅暴露 query_ontology / list_skills / call_skill / list_data_interfaces / search_rag / read_memory / write_memory / list_agents / get_agent_config）。
   - 若下方 L3 模板（system_prompt）提到「调 `generate_docx`」「生成 .docx 附件」等，**改由你自行产出 Word**：用第三方终端本机能力直接写 `.docx` 文件（如 python-docx、pandoc），或先输出完整结构化 markdown 再用本机工具转成 .docx。**不要尝试调用 `generate_docx`**（会 tool not found）。
4. **检索 cue**：涉及知识库时，提示词须含相关知识库名称字样以稳定触发 `search_rag`。

---

<!-- L3 模板（Agent.system_prompt：persona + policy + RAG cue + 闭环 + 输出骨架）-->
"""


async def _revoke_prior_pack_keys(db: AsyncSession, cu: CurrentUser) -> None:
    """撤销该用户上一份 skills-pack key（每次导出即时轮换）。"""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_name.like(f"{SKILLS_PACK_KEY_PREFIX}{cu.id}%"),
            ApiKey.is_active.is_(True),
            ApiKey.revoked_at.is_(None),
        )
    )
    for key in result.scalars().all():
        await api_key_service.revoke_api_key(db, key)


async def _mint_pack_key(db: AsyncSession, cu: CurrentUser) -> str:
    """为当前归口用户即时签发一张 scoped API key，返回明文（仅此一次）。

    scope 取用户最细粒度：team > department > organization。与 demo 已 seed 的
    per-system org key 同模式（ApiKey 模型已有 dept/team/scope_type 字段，无需扩）。
    """
    if cu.team_id:
        scope_type, dept_id, team_id = "team", UUID(cu.department_id) if cu.department_id else None, UUID(cu.team_id)
    elif cu.department_id:
        scope_type, dept_id, team_id = "department", UUID(cu.department_id), None
    else:
        scope_type, dept_id, team_id = "organization", None, None

    data = ApiKeyCreate(
        key_name=f"{SKILLS_PACK_KEY_PREFIX}{cu.id}",
        scope_type=scope_type,
        allowed_models=[],  # 全部模型
    )
    _, full_key = await api_key_service.create_api_key(
        db, UUID(str(cu.organization_id)), data, dept_id=dept_id, team_id=team_id,
    )
    return full_key


def _sanitize_name(raw: str) -> str:
    """把任意串清洗为 Claude Code 合法且**导出确定性**的 skill/server 名。

    合法名：小写字母/数字/连字符，字母数字开头，≤64 字。纯函数（不含 key/时间戳），
    故同一归口用户每次导出得到**完全相同**的名——第三方终端多次安装时覆盖原 skill，
    不堆叠为多个。frontmatter ``name`` 与目录名必须一致，故两者都用本函数同一产出。
    """
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", raw or "").strip("-").lower()
    if not s or not s[0].isalnum():
        s = f"skill-{s}" if s else "skill"
    return s[:64]


def _skill_md(agent: Agent) -> tuple[str, str]:
    """一个 Agent → (相对路径, SKILL.md 内容)。

    Claude Code skill 标准：目录下放 SKILL.md，frontmatter 含 name/description，body 是指令。
    frontmatter ``name`` 与目录名都用 ``_sanitize_name(agent.slug)`` —— 导出确定性，重装覆盖。
    """
    name = _sanitize_name(agent.slug or agent.name)
    description = (agent.description or agent.system_prompt[:80] or agent.name).strip()
    # frontmatter description 不能含换行；截断
    description = description.replace("\n", " ").replace("\r", " ")[:200]
    body = f"""---
name: {name}
description: {description}
---

{_L1_PREAMBLE}
{agent.system_prompt or ""}
"""
    rel_path = f".claude/skills/{name}/SKILL.md"
    return rel_path, body


def _root_skill_md(agents: list[Agent], pack_name: str, user_label: str) -> str:
    """zip 根 SKILL.md —— WorkBuddy 等要求「zip 根含 SKILL.md（YAML name+description）」的终端用。

    - 单 agent：根 SKILL.md 即该 agent 的（name=agent slug，与 .claude/skills/<slug>/ 一致）。
    - 多 agent：合并成一份索引型（name=包级稳定名，body 按 agent 分节，含 L1 调用约束），
      调用时用 ``get_agent_config(slug)`` 取具体 system_prompt。
    """
    if len(agents) == 1:
        a = agents[0]
        name = _sanitize_name(a.slug or a.name)
        desc = (a.description or a.system_prompt[:80] or a.name).strip().replace("\n", " ").replace("\r", " ")[:200]
        return f"""---
name: {name}
description: {desc}
---

{_L1_PREAMBLE}
{a.system_prompt or ""}
"""
    # 多 agent：合并索引
    slugs = ", ".join(_sanitize_name(a.slug or a.name) for a in agents)
    sections = "\n\n".join(
        f"## {_sanitize_name(a.slug or a.name)}\n\n{a.system_prompt or ''}".rstrip()
        for a in agents
    )
    return f"""---
name: {pack_name}
description: 归口用户 {user_label} 的 skills 包，含 {len(agents)} 个智能体模板（{slugs}）。调用前先 list_agents / get_agent_config 取具体 system_prompt 当指令，再用 call_skill / search_rag / query_ontology / read_memory 自主完成。
---

{_L1_PREAMBLE}
# 含的智能体模板（按需取用，调用前可 get_agent_config 取最新配置）

{sections}
"""


def _mcp_json(base_url: str, raw_key: str, server_name: str) -> str:
    """生成 .mcp.json（Claude Code 项目级 MCP 配置），内嵌 Bearer。"""
    mcp_url = base_url.rstrip("/") + "/mcp/"
    config = {
        "mcpServers": {
            server_name: {
                "type": "http",
                "url": mcp_url,
                "headers": {"Authorization": f"Bearer {raw_key}"},
            }
        }
    }
    return json.dumps(config, ensure_ascii=False, indent=2)


def _readme(org: Organization, agents: list[Agent], server_name: str) -> str:
    """生成 README：安装说明 + composer 示例（L4）。"""
    agent_lines = "\n".join(
        f"- `{a.slug}` — {a.description or a.name}" for a in agents
    ) or "- （当前用户 scope 内无 Agent 模板）"
    return f"""# {org.name} · 归口用户 Skills 包

## 是什么

本包让第三方智能体终端（Claude Code / Codex / WorkBuddy）以**当前归口用户权限**
调用平台五项能力：本体 / 技能 / 知识库(RAG) / 记忆 / 数据接口。鉴权已内嵌在
`.mcp.json`（即时签发的 scoped API key，每次导出轮换），**无需在终端再输凭证**。

## 安装

### Claude Code
1. 解压本 zip 到你的项目根目录（使 `.mcp.json` 与 `.claude/skills/` 落在项目根）。
2. 启动 Claude Code，`/mcp` 列出工具：
   - **配置类（只读，不运行智能体）**：`list_agents` / `get_agent_config` — 拉取平台
     已设定的智能体配置（`system_prompt` 即 L3 模板 persona/policy/输出骨架 + 绑定
     技能/RAG/模型）。**推荐先 `list_agents` → `get_agent_config(slug)` 取 system_prompt
     当自身指令**，再用下列工具自主完成。
   - **能力类**：`query_ontology` / `list_skills` / `call_skill` / `list_data_interfaces`
     / `search_rag` / `read_memory` / `write_memory`。
3. skills 在 `.claude/skills/<slug>/SKILL.md`（即导出时的 system_prompt 静态快照，
   配置后续变动以 `get_agent_config` 动态拉取为准），Claude Code 自动识别。

### Codex / WorkBuddy
将 `.mcp.json` 中 `mcpServers.{server_name}` 的 url + Authorization 头填入各自 MCP
客户端配置即可（同一端点、同一 key）。

## 可用 Agent 模板（已封装为 skills）

{agent_lines}

## composer 示例（L4 —— 在终端直接输入）

```
请基于历史缺陷知识库做本周新品评审风险预警，列出风险款号、评审必查项与闭环待办。
```

> composer 只写「目标 + 对象」，persona / 输出骨架由对应 SKILL.md 承载；
> 调用五项能力由 MCP tools 按需触发（先 list_skills / query_ontology 规划）。

## 安全提示

`.mcp.json` 内嵌的 API key 等同于你的归口用户权限，**请勿提交到公共仓库**。
下次导出会即时轮换（旧 key 自动失效）。
"""


async def build_skills_pack_zip(
    db: AsyncSession, cu: CurrentUser, request: Request,
) -> tuple[bytes, str]:
    """即时生成归口用户 skills 包 zip，返回 (zip 字节, 下载文件名)。"""
    # 1. 撤销旧 key + 即时签发新 key（鉴权即时轮换）
    await _revoke_prior_pack_keys(db, cu)
    raw_key = await _mint_pack_key(db, cu)

    # 2. 拉取用户 scope 内资源
    agents = await scope_service.list_agents_for_user(db, cu)
    ontologies = await scope_service.list_ontologies_for_user(db, cu)
    org = await db.get(Organization, UUID(str(cu.organization_id)))
    org_slug = (org.slug if org else cu.email) or "org"
    # MCP server 名导出确定性（同一归口用户每次导出同名）→ claude mcp add 重装覆盖、不堆叠。
    server_name = _sanitize_name(f"{org_slug}-{cu.id[:8]}")

    # 3. 打包
    base_url = str(request.base_url)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(".mcp.json", _mcp_json(base_url, raw_key, server_name))
        zf.writestr("README.md", _readme(org or type("_O", (), {"name": org_slug, "slug": org_slug})(), agents, server_name))
        # 根 SKILL.md：WorkBuddy 等「zip 根含 SKILL.md（YAML name+description）」终端用；
        # Claude Code 走 .claude/skills/<slug>/SKILL.md（下一段）。单 agent 同名覆盖一致。
        if agents:
            user_label = f"{org_slug}/{getattr(cu, 'email', cu.id[:8])}"
            zf.writestr("SKILL.md", _root_skill_md(agents, server_name, user_label))
        for agent in agents:
            rel, content = _skill_md(agent)
            zf.writestr(rel, content)
        for ont in ontologies:
            content = (ont.content or "").strip()
            if not content:
                continue
            # ontology/path → zip 内 ontology/<path>
            safe_path = ont.path or f"{ont.id}.md"
            zf.writestr(f"ontology/{safe_path}", content)

    filename = f"{org_slug}-{cu.id[:8]}-skills-pack.zip"
    return buf.getvalue(), filename
