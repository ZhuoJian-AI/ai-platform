"""本体 validator — check entity/relation graph consistency.

校验：实体 id 唯一、关系的 src/dst 引用存在的实体 id。返回 (ok, errors)。
"""

from __future__ import annotations


def validate_ontology(entities: list, relations: list) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not isinstance(entities, list):
        errors.append("entities 必须为数组")
        entities = []
    if not isinstance(relations, list):
        errors.append("relations 必须为数组")
        relations = []

    ids: set[str] = set()
    for i, ent in enumerate(entities):
        if not isinstance(ent, dict):
            errors.append(f"entities[{i}] 必须为对象")
            continue
        eid = ent.get("id")
        if not eid:
            errors.append(f"entities[{i}] 缺少 id")
            continue
        if eid in ids:
            errors.append(f"实体 id 重复：{eid}")
            continue
        ids.add(str(eid))

    for i, rel in enumerate(relations):
        if not isinstance(rel, dict):
            errors.append(f"relations[{i}] 必须为对象")
            continue
        src, dst = rel.get("src"), rel.get("dst")
        if src is None or dst is None:
            errors.append(f"relations[{i}] 缺少 src/dst")
            continue
        if str(src) not in ids:
            errors.append(f"relations[{i}] src 引用不存在的实体：{src}")
        if str(dst) not in ids:
            errors.append(f"relations[{i}] dst 引用不存在的实体：{dst}")

    return (len(errors) == 0, errors)
