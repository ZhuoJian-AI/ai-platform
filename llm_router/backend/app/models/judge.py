"""JudgeTemplate ORM model — reusable LLM-as-judge scoring templates."""

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class JudgeTemplate(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """判官模板：可被多个智能体引用的评分维度与权重配置。"""

    __tablename__ = "judge_templates"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_judge_org_slug"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 评分维度：[{"dimension": "准确性", "weight": 0.5, "description": "..."}, ...]
    criteria: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 评分细则文本（0-100 分制说明）
    scoring_rubric: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
