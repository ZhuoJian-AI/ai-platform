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

不引入 pyyaml 依赖：manifest 用 JSON 表达（``json`` 标准库即可解析）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SKILL_BLOCK_RE = re.compile(r"```skill\s*\n(.*?)```", re.DOTALL)


@dataclass
class SkillManifest:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    bound_endpoint_ids: list[str] = field(default_factory=list)


def parse_skill_manifest(content: str | None) -> SkillManifest | None:
    """从 skill.md 内容解析 manifest；缺失或非法返回 None。"""
    if not content:
        return None
    m = SKILL_BLOCK_RE.search(content)
    raw = m.group(1).strip() if m else ""
    if not raw:
        # 退化为整段 JSON（允许 skill.md 仅写 JSON）
        raw = content.strip()
        if not raw.startswith("{"):
            return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
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
    return SkillManifest(name=name, description=description, parameters=parameters, bound_endpoint_ids=bound)
