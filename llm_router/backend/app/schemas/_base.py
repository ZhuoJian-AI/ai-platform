"""Shared Pydantic base mixins.

SQLAlchemy DeclarativeBase 占用了 ``metadata`` 类属性，故 ORM 中 JSONB 元数据列的 Python
属性命名为 ``metadata_``（映射到 DB 列 ``metadata``）。为让 Read schema 仍对外暴露 ``metadata``
键，``MetaReadModel`` 用 before-validator 把 ORM 实例的 ``metadata_`` 提取为 ``metadata``。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrmModel(BaseModel):
    """带 from_attributes 的基类，便于从 ORM 实例构造。"""

    model_config = ConfigDict(from_attributes=True)


class MetaReadModel(OrmModel):
    """含 ``metadata`` 字段的 Read 基类：从 ORM ``metadata_`` 属性提取。"""

    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_metadata(cls, data):
        # ORM 实例：把 metadata_ 字段提为 metadata；dict 输入原样返回。
        if not isinstance(data, dict) and hasattr(data, "metadata_"):
            d = dict(data.__dict__)
            d["metadata"] = d.pop("metadata_", {})
            return d
        return data
