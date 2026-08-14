"""OpenAPI / Swagger spec parser → ToolEndpoint + Skill definitions.

从连接器 spec（OpenAPI 3.x JSON）解析路径与方法，生成 ToolEndpoint 元数据与
OpenAI function-tool 风格的 Skill definition，供「导入 spec」按钮使用。
"""

from __future__ import annotations

import re
from typing import Any


def _param_to_schema(param: dict) -> tuple[str, dict, bool]:
    """OpenAPI parameter → (name, json-schema, required)。"""
    name = param.get("name", "param")
    p_schema = param.get("schema", {}) or {}
    required = bool(param.get("required", False))
    # 简化：直接采用 schema（已含 type）
    return name, p_schema, required


def parse_spec(spec: dict) -> list[dict]:
    """解析 OpenAPI spec，返回 endpoint 描述列表：

    [{"name","method","path","description","params_schema","response_schema"}]
    """
    paths: dict[str, Any] = spec.get("paths", {}) or {}
    endpoints: list[dict] = []
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            op = op or {}
            parameters = op.get("parameters", []) or []
            props: dict[str, Any] = {}
            required: list[str] = []
            for p in parameters:
                pname, pschema, preq = _param_to_schema(p)
                if pname:
                    props[pname] = pschema or {"type": "string"}
                    if preq:
                        required.append(pname)
            params_schema = {"type": "object", "properties": props, "required": required}

            # operationId 优先作 name
            name = op.get("operationId") or _slugify(f"{method} {path}")
            endpoints.append({
                "name": name,
                "method": method.upper(),
                "path": path,
                "description": op.get("summary") or op.get("description") or "",
                "params_schema": params_schema,
                "response_schema": op.get("responses", {}) or {},
            })
    return endpoints


def endpoint_to_skill_definition(ep: dict) -> dict:
    """把 endpoint 描述转为 OpenAI function-tool definition。"""
    return {
        "name": ep["name"],
        "description": ep.get("description") or f"{ep['method']} {ep['path']}",
        "parameters": ep.get("params_schema") or {"type": "object", "properties": {}},
    }


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s or "endpoint"
