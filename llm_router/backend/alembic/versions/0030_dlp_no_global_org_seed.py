"""DLP 去全局化 + 内置规则按组织回填

不再支持「全局规则」（scope_type='global'）。每个组织各自持有一份内置规则副本作为
组织级规则（scope_type='organization'），组织管理员可启停。新建组织由应用层
``organization_service.create_organization`` → ``seed_builtin_dlp_rules`` 自动播种；
本迁移负责一次性回填存量组织，并清理历史 global 规则行。

内置规则定义须与 ``app/dlp/patterns/__init__.py:ALL_BUILTIN_RULES`` 完全对齐
（4 条 PII + 1 条金融 + 4 条文件，共 9 条；凭证/SWIFT/IBAN/医疗已下线）。

Revision ID: 0030_dlp_no_global_org_seed
Revises: 0029_drop_model_aliases
Create Date: 2026-07-13
"""

import uuid

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0030_dlp_no_global_org_seed"
down_revision = "0029_drop_model_aliases"
branch_labels = None
depends_on = None


# 与 app/dlp/patterns/__init__.py:ALL_BUILTIN_RULES 对齐（顺序无关）。
# 规则内容硬编码于迁移以保证历史可复现——后续库内容变更不回灌已落库组织。
_BUILTIN_RULES = [
    # PII（app/dlp/patterns/pii.py）
    {
        "name": "中国身份证号",
        "rule_type": "regex",
        "pattern": r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
        "severity": "critical",
        "action": "block",
        "direction": "both",
    },
    {
        "name": "护照号码",
        "rule_type": "regex",
        "pattern": r"\b[A-PR-WY][A-Z0-9]\d{6,9}\b|\b[EK]\d{8,9}\b|\b[GECP]\d{8}\b",
        "severity": "high",
        "action": "redact",
        "direction": "both",
    },
    {
        "name": "手机号码",
        "rule_type": "regex",
        "pattern": r"(?:\+?86[-.\s]?)?1[3-9]\d{9}|\+?1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        "severity": "high",
        "action": "redact",
        "direction": "both",
    },
    {
        "name": "电子邮箱",
        "rule_type": "regex",
        "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "severity": "medium",
        "action": "redact",
        "direction": "both",
    },
    # 金融（app/dlp/patterns/financial.py）——仅保留关键财务指标
    {
        "name": "关键财务指标",
        "rule_type": "keyword",
        "pattern": (
            '["营业收入","营业总收入","营收","主营业务收入","营业成本","毛利","毛利率",'
            '"净利润","净亏损","归母净利润","扣非净利润","经营性现金流","现金流净额",'
            '"资产负债率","净资产收益率","ROE","ROA","EBITDA","EBIT","每股收益","EPS",'
            '"市盈率","PE","市净率","PB","利润总额","税前利润","营业利润","销售费用",'
            '"管理费用","研发费用","财务费用","存货周转率","应收账款周转率","总资产",'
            '"净资产","总营收","GMV","ARPU","LTV","CAC","净利率","同店销售额",'
            '"收入","利润","成本"]'
        ),
        "severity": "medium",
        "action": "warn",
        "direction": "both",
    },
    # 文件附件（app/dlp/patterns/files.py）
    {
        "name": "Excel附件",
        "rule_type": "regex",
        "pattern": r"\.xls[xmb]?\b|application/vnd\.(?:ms-excel|openxmlformats-officedocument\.spreadsheetml\.sheet)",
        "severity": "medium",
        "action": "warn",
        "direction": "request",
    },
    {
        "name": "Word附件",
        "rule_type": "regex",
        "pattern": r"\.doc[x]?\b|application/vnd\.(?:ms-word|openxmlformats-officedocument\.wordprocessingml\.document)",
        "severity": "medium",
        "action": "warn",
        "direction": "request",
    },
    {
        "name": "PPT附件",
        "rule_type": "regex",
        "pattern": r"\.ppt[x]?\b|application/vnd\.(?:ms-powerpoint|openxmlformats-officedocument\.presentationml\.presentation)",
        "severity": "medium",
        "action": "warn",
        "direction": "request",
    },
    {
        "name": "PDF附件",
        "rule_type": "regex",
        "pattern": r"\.pdf\b|application/pdf",
        "severity": "medium",
        "action": "warn",
        "direction": "request",
    },
]


_INSERT_SQL = sa.text(
    """
    INSERT INTO dlp_rules
      (id, organization_id, name, description, rule_type, pattern,
       severity, action, direction, scope_type, scope_id, is_active, priority,
       created_at, updated_at, deleted_at, created_by)
    SELECT
      -- :name 在 SELECT 输出位会被推断为 text，在 WHERE name=:name（varchar(255) 列）
      -- 会被推断为 varchar，asyncpg 对同一参数无法统一类型而报 AmbiguousParameterError，
      -- 故两侧显式 CAST 为 varchar。
      :rid, :org_id, CAST(:name AS varchar), :desc, :rule_type, :pattern,
      :severity, :action, :direction, 'organization', NULL, TRUE, 0,
      NOW(), NOW(), NULL, NULL
    WHERE NOT EXISTS (
      SELECT 1 FROM dlp_rules
       WHERE organization_id = :org_id
         AND name = CAST(:name AS varchar)
         AND scope_type = 'organization'
         AND deleted_at IS NULL
    )
    """
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 清理历史 global 规则行（含 0005 软删的 4 条与任何残留 active global 行）。
    #    二次软删，保留行以维持审计外键引用。
    bind.execute(
        sa.text(
            "UPDATE dlp_rules SET deleted_at = NOW() "
            "WHERE scope_type = 'global' AND deleted_at IS NULL"
        )
    )

    # 2) 为每个未软删组织回填内置规则（organization 级，幂等跳过已存在同名规则）。
    orgs = bind.execute(
        sa.text("SELECT id FROM organizations WHERE deleted_at IS NULL")
    ).fetchall()
    for (org_id,) in orgs:
        for r in _BUILTIN_RULES:
            bind.execute(
                _INSERT_SQL,
                {
                    "rid": str(uuid.uuid4()),
                    "org_id": str(org_id),
                    "name": r["name"],
                    "desc": f"内置规则 — {r['name']}",
                    "rule_type": r["rule_type"],
                    "pattern": r["pattern"],
                    "severity": r["severity"],
                    "action": r["action"],
                    "direction": r["direction"],
                },
            )


def downgrade() -> None:
    # 回滚：删除本迁移回填的 organization 级内置规则（按 name 匹配 9 条内置名）。
    # 不恢复 global 行（0005 已软删的不可逆，残留 active global 也不重建）。
    names = tuple(r["name"] for r in _BUILTIN_RULES)
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM dlp_rules "
            "WHERE scope_type = 'organization' "
            "  AND scope_id IS NULL "
            "  AND name = ANY(:names)"
        ),
        {"names": list(names)},
    )
