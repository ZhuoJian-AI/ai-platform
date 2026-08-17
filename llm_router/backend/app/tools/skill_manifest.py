"""Skill manifest parser — 从 skill.md 解析 function-tool 定义。

约定：技能文件夹根目录的 ``skill.md`` 内含一个 ```skill 代码块，块内为 JSON：

    ```skill
    {
      "name": "get_order",
      "description": "按订单号查询订单",
      "parameters": {<JSON Schema>},
      "bound_endpoint_ids": ["<endpoint uuid>", "..."]
    }
    ```
    ````
    代码块之后可写任意 Markdown 文档（不影响解析）。

同时兼容标准 YAML frontmatter。可执行包额外声明 runtime/entrypoint。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

SKILL_BLOCK_RE = re.compile(r"```skill\s*\n(.*?)```", re.DOTALL)


@dataclass
class SkillManifest:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    bound_endpoint_ids: list[str] = field(default_factory=list)
    runtime: str = "prompt"
    entrypoint: str | None = None
    command: str | None = None
    user_invocable: bool = True


def parse_skill_manifest_dict(content: str | None) -> dict | None:
    """Return normalized raw manifest from fenced JSON, JSON-only, or YAML frontmatter."""
    if not content:
        return None
    m = SKILL_BLOCK_RE.search(content)
    if m:
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
    stripped = content.lstrip("\ufeff\r\n ")
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
    # Standard frontmatter starts with ---. Also accept the frequently used
    # compact form ``name: ...\n...\n---`` for backwards compatibility.
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        raw = parts[1] if len(parts) >= 3 else ""
    else:
        raw = stripped.split("---", 1)[0] if "---" in stripped else ""
    if not raw.strip():
        return None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def parse_skill_manifest(content: str | None) -> SkillManifest | None:
    """从 skill.md 内容解析 manifest；缺失或非法返回 None。"""
    data = parse_skill_manifest_dict(content)
    if not isinstance(data, dict) or not data.get("name"):
        return None
    name = str(data["name"])
    description = str(data.get("description") or "")
    parameters = data.get("parameters") or {}
    if not isinstance(parameters, dict):
        parameters = {}
    bound = data.get("bound_endpoint_ids") or []
    if not isinstance(bound, list):
        bound = []
    bound = [str(x) for x in bound]
    runtime = str(data.get("runtime") or "prompt").lower()
    if runtime not in {"prompt", "python", "node"}:
        runtime = "prompt"
    entrypoint = str(data.get("entrypoint")) if data.get("entrypoint") else None
    command = str(data.get("command")) if data.get("command") else None
    return SkillManifest(
        name=name,
        description=description,
        parameters=parameters,
        bound_endpoint_ids=bound,
        runtime=runtime,
        entrypoint=entrypoint,
        command=command,
        user_invocable=bool(data.get("user_invocable", True)),
    )
