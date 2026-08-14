"""DLP Rule Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DlpRuleCreate(BaseModel):
    """从规则库添加规则：选一条库规则（library_name），配置 6 项可调字段。

    name/rule_type/pattern/description 由后端按 library_name 从规则库拷入，不可在此指定。
    """
    library_name: str = Field(..., max_length=255)
    severity: str = Field(..., pattern=r"^(low|medium|high|critical)$")
    action: str = Field(..., pattern=r"^(block|redact|warn|log)$")
    direction: str = Field(..., pattern=r"^(request|response|both)$")
    scope_type: str = Field(..., pattern=r"^(organization|department|team)$")
    scope_id: UUID | None = None
    is_active: bool = True
    priority: int = 0


class DlpRuleUpdate(BaseModel):
    """配置规则：仅可改 6 项（severity/action/direction/scope/priority/is_active）。

    name/rule_type/pattern/description 不可改（来自规则库）。
    范围编辑：scope_type 与 scope_id 配合；organization_id 用于维持规则归属到
    当前组织——切换为组织/部门/团队范围时归属到当前组织，不允许提升为全局。
    """
    severity: str | None = Field(None, pattern=r"^(low|medium|high|critical)$")
    action: str | None = Field(None, pattern=r"^(block|redact|warn|log)$")
    direction: str | None = Field(None, pattern=r"^(request|response|both)$")
    is_active: bool | None = None
    priority: int | None = None
    scope_type: str | None = Field(None, pattern=r"^(organization|department|team)$")
    scope_id: UUID | None = None
    organization_id: UUID | None = None


class DlpRuleLibraryEntry(BaseModel):
    """规则库条目（只读，代码内置）。"""
    name: str
    rule_type: str
    pattern: str
    severity: str
    action: str
    direction: str
    description: str


class DlpRuleRead(BaseModel):
    id: UUID
    organization_id: UUID | None
    name: str
    description: str | None
    rule_type: str
    severity: str
    action: str
    direction: str
    pattern: str
    scope_type: str
    scope_id: UUID | None
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DlpRuleTestRequest(BaseModel):
    """测试 DLP 规则是否匹配给定文本。"""
    text: str
    direction: str = Field(default="request", pattern=r"^(request|response)$")


class DlpRuleTestResponse(BaseModel):
    matched: bool
    violations: list[dict]  # [{rule_id, rule_name, severity, matched_text_redacted}]
    redacted_text: str | None = None
