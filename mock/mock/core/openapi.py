"""OpenAPI 快照导出——把各子应用 spec 落盘为 JSON，供 seed 脚本离线回退与审阅。

用法：``python -m mock openapi`` 写入 ``mock/openapi/<key>.json``。
"""

from __future__ import annotations

import json
from pathlib import Path

from mock.core.registry import MOCK_SYSTEMS, SystemDef


def snapshot(sysdef: SystemDef) -> dict:
    """取子应用 OpenAPI spec（路径相对，不含挂载前缀）。"""
    app = sysdef.load_app()
    return app.openapi()


def export(sysdef: SystemDef, base_dir: Path) -> Path:
    spec = snapshot(sysdef)
    out_dir = base_dir / "openapi"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{sysdef.key}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_all(base_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for s in MOCK_SYSTEMS:
        paths.append(export(s, base_dir))
    return paths
