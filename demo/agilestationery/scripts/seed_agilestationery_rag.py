"""为「敏睿文具」组织创建并填充 9 个 RAG 集合（8 部门级 + 1 团队级）。

覆盖 9 个 demo 场景中需要 RAG 检索的场景：
  - department 级 8 个：经销商画像与渠道规则库(sales) / 渠道秩序与平台规则库(ecommerce) /
    竞品情报与营销物料库(marketing) / 报关合规与库存规则库(supply) /
    假货特征与产品标准库(product) / 售后政策与工单规则库(service) /
    财务合规与发票规则库(finance) / 合同条款与合规规则库(legal)
  - team 级 1 个：岗位JD与人事制度库(hr-recruiting，HR-01 招聘子任务)

embedding=text-embedding-v4，chunk_size=512，chunk_overlap=64。
幂等：集合按 (org, scope, name) 去重；文档按 (collection, source) 去重。
embedding 失败单文档置 failed 不阻断其余；重跑因 source 去重跳过已成功。
注：若前次入库残留 status=failed 的文档，按 source 去重会再次跳过（agilesteel A4 坑），
    需手动清理 RagDocument 后重跑，或先删除该 collection 再重建。

用法:
    docker cp demo/agilestationery/scripts/seed_agilestationery_rag.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agilestationery_rag.py
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.rag import RagCollection, RagDocument  # noqa: E402
from app.models.team import Team  # noqa: E402
from app.schemas.rag import RagCollectionCreate, RagDocumentCreate  # noqa: E402
from app.services.rag_service import (  # noqa: E402
    create_collection, get_collection, ingest_document, list_collections,
)

logger = structlog.get_logger()

ORG_SLUG = "agilestationery"
ORG_NAME_FALLBACK = "敏睿文具"


# ───────────────────────── RAG 集合定义 ─────────────────────────

COLLECTIONS: list[dict] = [
    # ── 1. 经销商画像与渠道规则库（dept sales，SAL-01） ──
    {
        "name": "经销商画像与渠道规则库",
        "scope_type": "department",
        "dept_slug": "sales", "team_slug": None,
        "description": "经销商分层与信用评分 + 销售预测与补货 + KA 大客户运营，供 SAL-01 销售 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "经销商分层与信用评分规则.md",
                "title": "经销商 A/B/C/D 评级维度 + 信用评分规则",
                "content": """# 经销商分层与信用评分规则

## 经销商 4 级分层（DLR- 客户码）
- A 级：进货频次≥2次/月、进货结构覆盖 3 大品类、回款准时率≥95%、无窜货记录、销量同比上行 → 战略经销商，返利上浮
- B 级：进货频次 1-2 次/月、回款准时率 85-95% → 核心经销商，正常返利
- C 级：进货频次<1 次/月、回款准时率 70-85% → 成长型，重点培育
- D 级：回款逾期>60 天、或窜货次数≥2、或销量同比下滑>30% → 预警/淘汰候选

## 评级 5 维度（加权）
- 进货频次 20%（月均下单次数，DLR-AS-* 客户码回挂 ERP 订单）
- 进货结构 20%（覆盖品类数：中性笔/圆珠笔/记号笔/笔记本/文件夹）
- 回款情况 30%（准时率 + 平均账期，REC-AS- 应收关联）
- 窜货记录 15%（跨区域乱价次数，MR- 商家码证据关联）
- 销量趋势 15%（同比/环比增长率）

## 信用额度动态调整
- A 级：信用额度 = 近 3 月均进货额 × 2.0
- B 级：× 1.5；C 级：× 0.8；D 级：冻结新增额度
- 回款逾期(REC days_overdue>30) → 降一级 + 冻结发货
""",
            },
            {
                "source": "销售预测与补货规则.md",
                "title": "分渠道分SKU分区域预测因子 + 断货风险与补货建议",
                "content": """# 销售预测与补货规则

## 分渠道分SKU分区域预测因子
- 渠道：线上电商（天猫/京东/拼多多）、线下经销商、政企集采、校园书店
- SKU：按 P-PRD-* 产品码分品类（中性笔/圆珠笔/记号笔/笔记本/文件夹）
- 区域：华东/华南/华北/西部，开学季区域差异化备货
- 预测因子：近期销售订单(ASSO) + 渠道库存 + 开学季系数(8-9 月×1.5) + 政企采购周期(Q1/Q3 招标季)

## 季节性周期
- 开学季（8-9 月）：学生用笔/笔记本需求×1.5-2.0，提前 45 天备货
- 政企采购季（Q1 年度计划、Q3 补库）：协议量为主
- 大促（618/双11/双12）：线上爆品备货×2.0
- 年终礼品季（11-12 月）：礼盒套装需求上行

## 断货风险与补货建议规则
- 渠道库存 available_qty < 近 7 天日均销量×补货周期(7 天) → 断货风险 P0
- 安全库存 = 历史日均销量×(采购周期+7 天)
- 补货建议：现货优先调拨（listInventory available_qty），缺货关联 SPO 补货单
- KA 协议量优先保供，非协议客户按评级 A→B→C 分配

## 交期答复
- 现货 available_qty≥订单量 → 3-5 天发货
- 需补货：关联 SPO + 采购周期，答复 15-25 天
""",
            },
            {
                "source": "KA大客户运营规则.md",
                "title": "KA 大客户交叉销售 + 品类扩容 + 流失预警",
                "content": """# KA 大客户运营规则

## KA 客户识别
- 政企集采大客户 DLR-AS-KA-*：年采购额≥500 万、协议量稳定
- 连锁文具店 DLR-AS-CHAIN：门店≥20 家、月均进货≥50 万
- 校园供应商 DLR-AS-EDU：覆盖高校/中小学渠道

## 交叉销售规则
- 历史采购以中性笔为主 → 推荐圆珠笔/记号笔同品类扩容
- 礼盒套装组合推荐（年终礼品季）
- 关联推荐：笔记本+文件夹+笔具组合套装

## 品类扩容规则
- 客户当前 SKU 数<5 → 品类扩容机会高
- 推荐未覆盖品类的明星 SKU（销量 Top 10）
- 试用装支持：首次扩容 SKU 提供 5% 试单折扣

## 流失预警
- 连续 2 月进货额环比下滑>30% → 流失预警 P1
- 协议量完成率<70% → 主动拜访 + 协议续约谈判
- 竞品替代风险：竞品同品类低价倾销 → 渠道政策加固
- 应收逾期(ASINV days_overdue>30) → 信用风险，影响 KA 资格复审
""",
            },
        ],
    },

    # ── 2. 渠道秩序与平台规则库（dept ecommerce，ECM-01） ──
    {
        "name": "渠道秩序与平台规则库",
        "scope_type": "department",
        "dept_slug": "ecommerce", "team_slug": None,
        "description": "线上渠道秩序 + 渠道效能分析 + 智能投放优化，供 ECM-01 电商运营 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "线上渠道秩序规则.md",
                "title": "低价倾销/窜货/非授权店铺判定 + MR- 商家码",
                "content": """# 线上渠道秩序规则

## 低价倾销判定
- 判定阈值：线上成交价 < 指导价×85% → 低价倾销
- 指导价：按 SKU 产品码 P-PRD-* 在 PLM 维护的 msrp_price
- 连续 7 天低价 → 判定违规，冻结该商家 MR-AS-* 授权
- 促销豁免：官方大促（618/双11）期间白名单商家可短期破价≤10%

## 窜货识别规则
- 发货地与授权区域不匹配 → 窜货嫌疑
- 跨区域订单占比>30% → 启动窜货调查
- 关联证据：MR-AS-* 商家码 + 物流发货地 + 收货地 + DLR-AS-* 经销商归属区域
- 窜货次数≥2 → D 级降级 + 返利扣减

## 非授权店铺判定
- 平台店铺未在 MR-AS-* 授权白名单 → 非授权
- 商品图盗用官方素材 + 价格异常低 → 假货嫌疑，转 CTF- 假货样本流程
- 处置：平台投诉下架 + 法律取证 EV-AS-

## 渠道秩序指标
- 授权店铺覆盖率：授权数/应有授权数≥90%
- 低价违规率：违规订单数/总订单数<3%
- 窜货订单率：<2%
""",
            },
            {
                "source": "渠道效能分析与投放优化规则.md",
                "title": "GMV/投放/转化/ROI 指标 + 智能投放优化",
                "content": """# 渠道效能分析与智能投放优化规则

## 渠道效能 5 维指标口径
- GMV：成交金额（含退款前），口径 GMV-AS-* 维度按渠道/SKU/区域
- 投放费用：直通车/引力魔方/京东快车等 CPC+CPM 总费用
- 转化率：成交订单数/访客数，按 SKU 分品
- 退货率：退货订单数/成交订单数，>8% 低效预警
- ROI：GMV/投放费用，<2.0 低效投放

## 低效识别规则
- SKU 退货率>10% + ROI<1.5 → 低效 SKU 下架或优化
- 渠道 ROI<2.0 连续 14 天 → 预算砍半 + 策略复盘
- 关键词低效：CPC>行业均值 1.5× 且转化率<1% → 否词

## 智能投放优化规则
- 出价策略：ROI≥3.0 的关键词加价 20%，ROI<1.0 降价 30%
- 人群标签：高复购人群（历史购买≥3 次）溢价 50%
- 预算动态分配：按 SKU 毛利率×ROI 分配，高毛利高 ROI 加预算
- 大促拆解：预热期(7 天)预算占 30%、爆发期(3 天)50%、返场期(2 天)20%
- 分时折扣：低峰时段(0-6 点)出价-50%，高峰时段(20-23 点)出价+30%

## 投放复盘
- 每日 GMV/费用/ROI/转化率看板
- 每周 SKU 级投放效能排名 + 优化建议
- 每月渠道效能复盘 + 预算重分配
""",
            },
        ],
    },

    # ── 3. 竞品情报与营销物料库（dept marketing，MKT-01） ──
    {
        "name": "竞品情报与营销物料库",
        "scope_type": "department",
        "dept_slug": "marketing", "team_slug": None,
        "description": "竞品监测框架 + B 端营销物料规范 + 渠道市场洞察，供 MKT-01 营销 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "竞品监测框架.md",
                "title": "竞品 4 维监测 + CMP- 竞品码 + 周报模板",
                "content": """# 竞品监测框架

## 竞品 4 维监测
- 渠道政策：授权体系/返利结构/区域保护政策
- 新品动态：新品发布节奏/SKU 扩展/技术卖点（如可擦笔/速干墨水）
- 价格策略：主流 SKU 指导价/促销节奏/区域定价差异
- KA 策略：大客户协议量/排他条款/品类组合

## 竞品编码
- CMP-AS-* 竞品码：按品牌+品类建立（如 CMP-AS-MUNDANE-中性笔）
- 关联：MR-AS-* 商家（竞品授权店铺）+ EV-AS- 取证（价格截图/政策文件）

## 周报模板
1. 本周竞品新品发布清单（品牌/SKU/卖点/价位段）
2. 价格异动（涨/跌幅>5% 的 SKU）
3. 渠道政策变化（返利/授权/排他）
4. KA 动态（竞品签约大客户/流失大客户）
5. 本周建议（定价调整/新品对标/渠道反制）

## 监测渠道
- 线上：天猫/京东/拼多多店铺数据爬取
- 线下：经销商反馈 + 区域市场走访
- 行业：文具展会/行业报告/媒体披露
""",
            },
            {
                "source": "B端营销物料规范.md",
                "title": "订货会/渠道政策/陈列/大客户推广文案结构 + 品牌合规初审",
                "content": """# B 端文本营销物料规范

## 物料 4 类结构
1. 订货会宣讲文案：开场(品牌实力) → 品类卖点(按 SKU P-PRD-*) → 政策激励(返利/账期) → 逼单(限时限量)
2. 渠道政策通知：政策标题 → 适用对象(DLR-AS-* 分级) → 政策条款(返利比例/账期/区域) → 生效日期 → 申诉渠道
3. 陈列规范文本：货架层数 → 品类分区(笔具/笔记本/文件夹) → 爆品位(黄金位) → 价格标签规范
4. 大客户推广方案：客户痛点 → 产品组合(套装 SKU) → 量化收益(成本节约/效率提升) → 案例 → 报价

## 品牌合规初审规则
- 极限词禁用清单："最/第一/顶级/国家级/最佳/极品/独家/全网最低/绝对"
- 虚假宣传禁用："治愈/疗效/100% 保证/永不褪色/永久不干"
- 数据引用必须有出处："销量第一（数据来源：XX 报告 YYYY 年）"
- 比较广告合规：不得直接贬低竞品（CMP-AS-* 不得在物料中点名贬低）
- 礼盒套装须标注：内含 SKU 清单 + 数量 + 总价

## 物料审核流程
1. 市场部撰写 → 2. 法务初审（极限词/虚假宣传） → 3. 品牌经理终审 → 4. 发布
- 审核不通过打回 + 标注违规点
""",
            },
            {
                "source": "渠道市场洞察方法.md",
                "title": "品类/功能/包装趋势 + 区域渠道偏好差异",
                "content": """# 渠道市场洞察方法

## 品类趋势识别
- 中性笔：0.5mm 细尖需求上升（学生+办公），速干墨水成主流
- 记号笔：可擦写+环保墨水趋势
- 笔记本：活页/康奈尔/方格内页细分，礼盒化
- 文件夹：A4 容量+分类索引+环保材质

## 功能趋势识别
- 环保：再生塑料/可降解包装，欧盟客户强制
- 速干：考试场景刚需（3 秒内不晕染）
- 可擦：热敏可擦笔学生市场增长
- 防伪：二维码防伪溯源成标配

## 包装趋势识别
- 礼盒化：年终礼品/开学礼盒套装增长
- 环保：减少塑料包装，FSC 认证纸
- 单品小包装：便携笔袋+替换芯设计

## 区域渠道偏好差异
- 华东：品牌敏感+环保诉求高，高端品占比高
- 华南：外贸出口集散，OEM/定制需求
- 华北：政企集采占比高，协议量稳定
- 西部：价格敏感，性价比 SKU 占比高
- 校园渠道：开学季爆量，性价比+套装为主
""",
            },
        ],
    },

    # ── 4. 报关合规与库存规则库（dept supply，SCM-01） ──
    {
        "name": "报关合规与库存规则库",
        "scope_type": "department",
        "dept_slug": "supply", "team_slug": None,
        "description": "报关单证规则 + 智能库存与补货 + 汇率预警，供 SCM-01 供应链 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "报关与单证规则.md",
                "title": "HS 归类标准 + 单证关联 + 合规校验",
                "content": """# 报关与单证规则

## HS 归类标准（文具品类）
- 中性笔（墨水笔，按笔尖分类）：9608.20
- 圆珠笔（油墨笔）：9608.10
- 笔芯（替换芯）：9608.60
- 记号笔（马克笔，按墨水笔归类）：9608.20
- 塑料包装/笔盒：3926.10
- 纸质笔记本：4820.10

## 单证识别要素
- 报关单 CD-AS-*：合同号/发票号/HS 编码/数量/单价/原产国/目的国
- 商业发票 INV-AS-*：与报关单数量/单价一致
- 凭证 BV-AS-*：报关单/发票/装箱单/提单关联验真

## 合规校验 4 维
1. 归类合规：HS 编码与实际商品一致（如中性笔不得归 9608.10 圆珠笔）
2. 单证合规：报关单/发票/装箱单/合同四单一致
3. 价格合规：申报价与发票价一致，转让定价合规
4. 发票一致性：INV-AS-* 与 CD-AS-* 金额/数量/品名一致

## 常见违规
- HS 归类错误（高税率归低税率）→ 海关稽查 + 罚款
- 单证不符 → 退单/延误
- 低价申报 → 反倾销调查风险

## 关联编码
- CD-AS-* 报关单 → INV-AS-* 发票 → BV-AS-* 凭证 → REC-AS-* 应收
- 关联缺失 → 报关合规预警 P0
""",
            },
            {
                "source": "智能库存与补货规则.md",
                "title": "安全库存/滞销/临期识别 + 仓配调度",
                "content": """# 智能库存与补货规则

## 安全库存规则
- 安全库存 = 历史日均销量×(采购周期+7 天)
- 中性笔主力 SKU：采购周期 15 天 → 安全库存=日均×22
- 进口品（日系/欧系笔芯）：采购周期 45 天 → 安全库存=日均×52

## 滞销识别
- 库存周转天数>90 天 → 滞销预警 P1
- 库存周转天数>180 天 → 滞销清理（促销/退货/调拨）
- 按 SKU P-PRD-* 维度计算周转

## 临期识别
- 墨水类（中性笔/圆珠笔/记号笔）：保质期 24 个月
- 临期阈值：距保质期<6 个月 → 临期预警，优先出货
- 过期处置：报废 + 财务核销 INV-AS-*

## 开学季备货
- 8-9 月开学季：主力 SKU 备货量×1.5-2.0
- 提前 45 天下单补货，避免断货
- 区域仓配：华东/华南主仓 + 区域前置仓

## 仓配调度规则
- 多仓库存调拨：现货 available_qty 优先调拨
- 跨仓调拨成本 vs 紧急补货成本权衡
- KA 协议量优先保供
""",
            },
            {
                "source": "汇率预警规则.md",
                "title": "JPY/CNY 波动对采购付款时点决策",
                "content": """# 汇率预警规则

## 汇率监测币种
- JPY/CNY：日系笔芯/笔头进口采购
- EUR/CNY：欧系文具进口
- USD/CNY：通用进口结算

## 波动预警阈值
- 单日波动>1% → 关注
- 单周波动>3% → 预警 P1
- 单月波动>5% → 采购决策复盘

## 采购付款时点决策
- JPY 贬值趋势 → 延迟付款（按账期 60 天尾款时点）
- JPY 升值趋势 → 提前付款/锁汇
- 锁汇工具：远期结售汇（3-6 个月远期）

## 关联
- 应付 AP-AS-* 供应商应付 → 汇率影响实际付款额
- 采购订单 SPO-AS-* 锁定币种 + 汇率
- 财务对账 REC-AS-* 实际汇率差异入汇兑损益
""",
            },
        ],
    },

    # ── 5. 假货特征与产品标准库（dept product，PRD-01） ──
    {
        "name": "假货特征与产品标准库",
        "scope_type": "department",
        "dept_slug": "product", "team_slug": None,
        "description": "假货识别标准 + 产品品类规划 + 全渠道反馈分析，供 PRD-01 产品 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "渠道假货识别标准.md",
                "title": "笔身/包装/防伪标识比对要点 + CTF- 假货样本",
                "content": """# 渠道假货识别标准

## 笔身比对要点
- 笔夹激光雕刻：正品笔夹有激光雕刻 logo，假货为丝印/贴标，边缘模糊
- 笔身丝印：正品丝印清晰锐利，假货丝印边缘毛糙/易刮落
- 笔尖工艺：正品笔尖球珠为碳化钨/不锈钢，假货为普通钢，书写顺滑度差异
- 配重：正品配重均衡，假货常头重脚轻

## 包装比对要点
- 包装盒材质：正品用 FSC 认证纸+UV 印刷，假货纸薄/色彩偏差
- 条形码：正品 EAN-13 可扫且与 SKU P-PRD-* 一致，假货常条码错乱/重复
- 内页说明书：正品多语言说明书，假货常缺失/简陋

## 防伪标识比对
- 防伪二维码：正品每支笔独立二维码，扫码进入官方溯源页（关联 P-PRD-* 批次）
- hologram 标（全息防伪标）：正品有全息变色效果，假货为普通镭射贴
- 激光防伪线：正品笔身有激光刻线，假货无/仿制粗糙

## 假货样本编码
- CTF-AS-* 假货样本码：按品类+渠道建立
- CTF.evidence_code → EV-AS- 取证（购买记录/截图/物流单）
- EV-AS- → MR-AS-* 商家（非授权/可疑店铺）关联
- CTF → 法务维权批量投诉流程

## 处置规则
- 单个 CTF 样本 → 平台投诉下架
- 同商家 CTF≥3 → 批量维权 + 法律诉讼
- 假货率>5% 的渠道 → 暂停该渠道授权
""",
            },
            {
                "source": "产品品类规划与生命周期规则.md",
                "title": "SKU-ZB- 产品码 + 上架/下架 + 生命周期",
                "content": """# 产品品类规划与生命周期规则

## 产品编码
- SKU-ZB-* 产品码：按品类+型号+规格建立（如 SKU-ZB-GELPEN-0.5-BLACK）
- PLM 主数据：含 msrp_price/成本/保质期/渠道分配

## 生命周期 4 阶段
1. 导入期（0-3 月）：新品上市，铺货+试用，广告投入高，销量爬坡
2. 成长期（3-12 月）：销量快速增长，渠道扩容，毛利稳定
3. 成熟期（1-3 年）：销量稳定，毛利优化，渠道维护，防竞品替代
4. 衰退期（>3 年或销量同比下滑>20%）：清库存/换包装升级/下市

## 上架/下架规则
- 上架：PLM 维护完成 + 渠道分配（线上/线下/KA）+ 首批备货到位
- 渠道分配：线上爆品优先电商渠道，高毛利礼盒优先 KA/校园
- 下架：销量连续 3 月下滑>30% + 库存周转>180 天 → 下架清理
- 下架前 30 天通知经销商清库

## 产品组合策略
- 引流款：低价中性笔，低毛利高销量
- 利润款：礼盒/套装，高毛利
- 形象款：高端笔/限定款，品牌建设
- 防御款：对标竞品 CMP-AS-* 的价格带产品
""",
            },
            {
                "source": "全渠道反馈分析规则.md",
                "title": "质量/功能/包装/体验四维分类 + 高频问题定位",
                "content": """# 全渠道反馈分析规则

## 反馈 4 维分类
- 质量：漏墨/断墨/笔尖脱落/部件松动
- 功能：书写不流畅/速干不达预期/可擦残留
- 包装：包装破损/错发/少发/条码扫不出
- 体验：手感差/外观差/性价比不满

## 反馈编码
- FB-AS-* 反馈码：按渠道+SKU 建立
- 关联：SKU-ZB-* 产品码 + DLR-AS-* 经销商 + CASE-AS-* 售后工单
- 高频问题：同 SKU 反馈数>月销×2% → P0 立项改进

## 高频问题定位规则
- 漏墨高频 → 笔尖工艺/密封结构改进（关联 CTF- 假货排查，排除假货因素）
- 断墨高频 → 墨水配方/笔尖供墨系统改进
- 包装破损高频 → 包装材质/物流包装改进
- 条码扫不出高频 → 印刷工艺/条码标准复核

## 反馈闭环
- 收集：线上评价/客服工单/经销商反馈/校园渠道回访
- 分类：按 4 维自动分类 + 人工复核
- 立项：高频问题 → 产品改进 SPO + 质量改进 DF-AS-
- 闭环：改进后反馈率下降验证
""",
            },
        ],
    },

    # ── 6. 售后政策与工单规则库（dept service，SVC-01） ──
    {
        "name": "售后政策与工单规则库",
        "scope_type": "department",
        "dept_slug": "service", "team_slug": None,
        "description": "售后工单处理 + B 端客服辅助 + 服务质量分析，供 SVC-01 售后 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "售后工单处理规则.md",
                "title": "退换货/破损补发资质校验 + 工单分派与超时升级",
                "content": """# 售后工单处理规则

## 工单编码
- CASE-AS-* 工单码：按渠道+订单+问题类型建立
- 关联：订单 SPO-AS-* + SKU-ZB-* 产品 + DLR-AS-* 经销商

## 资质校验
- 退换货资质：订单未超 7 天（线上）/30 天（线下 KA），商品未使用/不影响二次销售
- 破损补发资质：物流破损凭照片+物流单，30 天内可补发
- 质量问题退货：凭 FB-AS-* 反馈 + 质量缺陷证据，不受 7 天限制

## 分派规则（按 3 维）
1. 订单等级：KA 协议客户优先级 P0，普通订单 P1
2. 问题类型：质量问题（漏墨/断墨）→ 产品组，物流破损 → 供应链，咨询类 → 客服
3. 客户优先级：A 级经销商 P0，D 级 P2

## 常规合规自动流转结案
- 7 天无理由退货 + 资质校验通过 → 自动批准退货
- 破损补发 + 物流凭证齐全 → 自动补发
- 咨询类（政策/进度）→ 自动回复话术 + 结案

## 超时升级
- 工单超 24h 未响应 → P0 升级主管
- 超 48h 未结案 → 升级部门总监
- 超 72h 未闭环 → 升级总经理 + 月度复盘

## 状态枚举
- 待受理 → 处理中 → 待客户确认 → 已结案 / 已升级 / 已驳回
""",
            },
            {
                "source": "B端客服辅助与服务质量规则.md",
                "title": "话术推荐/政策查询/历史上下文 + 服务质量指标",
                "content": """# B 端客服辅助与服务质量规则

## 话术推荐规则
- 退货咨询 → 退货政策话术（7 天无理由/30 天质量）
- 物流查询 → 调 ERP 物流单 + 答复预计到达
- 产品咨询 → 调 PLM 产品 P-PRD-* 参数 + 卖点话术
- 投诉 → 安抚话术 + 升级分派

## 政策查询
- 退货政策：7 天无理由（线上）/30 天质量（全渠道）
- 保价政策：价格保护 15 天，降价差价退还
- 发票政策：凭 INV-AS-* 开票，电子发票 24h 内开具
- 运费政策：质量问题商家承担，无理由买家承担

## 历史订单上下文
- 查询客户历史订单 SPO-AS-* + 反馈 FB-AS-* + 工单 CASE-AS-*
- 复购客户（≥3 次）→ VIP 话术 + 优先处理
- 历史投诉≥2 次 → 升级专家客服

## 复杂问题分派
- 涉及质量问题（批量）→ 产品组 + 质量改进 DF-AS-
- 涉及假货嫌疑 → 转假货识别流程 CTF-AS-
- 涉及发票纠纷 → 财务 INV-AS-
- 涉及法律威胁 → 法务 LEG-AS-

## 服务质量 4 维指标
- 投诉率：投诉工单数/总订单数，>2% 预警
- 咨询响应：首次响应<30s，平均响应<2min
- 处理时效：常规工单 24h 结案率≥90%
- 满意度：CSAT≥4.5/5，低于 4.0 触发复盘
""",
            },
        ],
    },

    # ── 7. 财务合规与发票规则库（dept finance，FIN-01） ──
    {
        "name": "财务合规与发票规则库",
        "scope_type": "department",
        "dept_slug": "finance", "team_slug": None,
        "description": "发票识别与费用审核 + 应收与风险 + 财务合规，供 FIN-01 财务 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "发票识别与费用审核规则.md",
                "title": "专票/普票/海关票识别 + 凭证验真 + 报销合规",
                "content": """# 发票识别与费用审核规则

## 发票 3 类识别要素
1. 增值税专票：发票代码/号码/开票日期/税额/购买方/销售方/货物劳务名称
2. 增值税普票：同专票但不可抵扣
3. 海关票：海关进口增值税专用缴款书，含报关单号 CD-AS-*

## 凭证关联验真
- INV-AS-* 发票码 → BV-AS-* 凭证码关联
- 验真 4 维：发票真伪（税务平台验真）+ 金额一致 + 购买方一致 + 货物品名一致
- 三单一致：发票/合同/收货单一致

## 报销合规
- 报销类型：差旅/办公/招待/市场/采购
- 预算额度：按部门年度预算 + 月度额度，超预算预警
- 票据合规：必须有 INV-AS-* 发票，收据/白条不合规
- 审批流：直属经理 → 部门总监 → 财务复核 → 打款

## 银行流水对账
- 银行流水 vs 应收 REC-AS-* / 应付 AP-AS-* 对账
- 差异>1% → 对账预警 P1
- 未匹配流水 → 待处理 + 人工核对

## 关联编码
- INV-AS-* 发票 → BV-AS-* 凭证 → REC-AS-* 应收 / AP-AS-* 应付
- INV → CD-AS-* 报关单（进口票）
- 报销凭证 BV-AS-* status 枚举：申请中/经理审批/总监联签/财务复核/已打款/已闭环
""",
            },
            {
                "source": "应收与财务合规规则.md",
                "title": "应收账龄分析 + 分级催收 + 异常财务指标 + 税务风险",
                "content": """# 应收与财务合规规则

## 应收账龄分析（REC-AS-*）
- 0-30 天：正常期
- 31-60 天：关注期，提示催收
- 61-90 天：预警期，正式催收函
- 91-180 天：逾期期，冻结发货 + 法务介入
- >180 天：坏账候选，计提坏账准备

## 分级催收清单
- A 级经销商：柔性催收（电话/微信），优先保关系
- B 级：标准催收（函件+电话）
- C 级：强力催收（律师函）
- D 级：法务诉讼 + 坏账核销

## 逾期预警
- 单笔逾期>30 天 → P1 预警
- 累计逾期>经销商信用额度 50% → 冻结发货
- 应收周转天数>60 天 → 月度复盘

## 异常财务指标
- 毛利率下滑：同比下滑>5% → 预警，查成本/定价
- 费用超支：费用/预算>110% → 预警
- 回款逾期：回款率<90% → 催收加强
- 库存积压：库存周转>90 天 → 清库存

## 税务风险扫描
- 进项票异常：进项税额增幅>销项 20% → 稽查风险
- 发票开具异常：作废率/红冲率>5% → 预警
- 转让定价：进口价格偏离行业均值>20% → 反避税风险
- 报关与发票不一致 → 海关/税务双重风险
""",
            },
        ],
    },

    # ── 8. 合同条款与合规规则库（dept legal，LEG-01） ──
    {
        "name": "合同条款与合规规则库",
        "scope_type": "department",
        "dept_slug": "legal", "team_slug": None,
        "description": "合同智能审核 + 知识产权与渠道维权 + 合规风险，供 LEG-01 法务 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "合同智能审核规则.md",
                "title": "经销商/采购/服务合同风险条款识别 + 模板匹配",
                "content": """# 合同智能审核规则

## 合同 3 类
1. 经销商合同：授权区域/返利结构/账期/排他/违约
2. 采购合同：供应商资质/交期/质量/付款/违约
3. 服务合同：服务范围/SLA/付款/知识产权归属

## 风险条款识别（6 类）
- 账期条款：账期>90 天 → 资金风险预警，建议 60 天内
- 违约条款：违约金过高（>合同额 30%）或过低（<5%）→ 风险
- 排他条款：排他区域过宽（>全省）或期限过长（>3 年）→ 反垄断风险
- 返利条款：返利比例不透明/计算复杂 → 争议风险
- 知识产权条款：未明确知识产权归属 → 侵权风险
- 争议解决条款：未约定管辖法院/仲裁 → 诉讼成本风险

## 合同模板匹配
- 标准模板库：经销商合同/采购合同/服务合同 3 大类
- 匹配度<80% → 高风险条款审查
- 匹配度<60% → 人工逐条审查
- 偏离条款标注 + 风险等级（高/中/低）

## 审核流程
1. 业务上传合同 → 2. 系统模板匹配 + 风险条款识别 → 3. 法务复核 → 4. 风险高→总监审批 → 5. 签约
- 审核记录归档 LEG-AS-*
""",
            },
            {
                "source": "知识产权与合规风险规则.md",
                "title": "非授权/侵权/假冒监测 + 批量维权 + 宣传合规",
                "content": """# 知识产权与渠道维权规则

## 非授权商家监测
- 线上店铺未在 MR-AS-* 授权白名单 → 非授权
- 盗用官方素材/商标 → 侵权取证 EV-AS-
- 处置：平台投诉 + 函件警告 + 诉讼

## 商标/专利侵权监测
- 商标侵权：同品类同字号/近似商标 → 行政投诉 + 民事诉讼
- 专利侵权（笔尖工艺/墨水配方/笔身结构）：专利号比对 → 诉讼/许可谈判
- 关联：CTF-AS-* 假货样本 + EV-AS- 取证 + MR-AS-* 商家

## 假冒监测与批量维权
- 假货样本 CTF-AS-* 收集 + 取证 EV-AS-
- 同商家 CTF≥3 → 批量维权流程：
  1. 平台投诉下架 2. 律师函 3. 行政投诉（市场监管局）4. 民事诉讼
- 假货率>5% 的渠道 → 暂停授权 + 专项维权

## 合规风险规则
- 宣传文案极限词审查："最/第一/顶级/国家级" → 禁用，违规罚则
- 虚假宣传审查："治愈/100%保证/永不褪色" → 禁用
- 比较广告合规：不得直接贬低竞品 CMP-AS-*

## 进出口贸易合规
- 海关合规：HS 归类准确 + 单证一致（CD-AS-* / INV-AS-*）
- 外汇合规：收付汇与报关单/发票一致
- 商检合规：法定检验商品（部分文具类）须商检
- 反倾销：出口目的国反倾销调查风险监测
""",
            },
        ],
    },

    # ── 9. 岗位JD与人事制度库（team hr-recruiting，HR-01 招聘子任务） ──
    {
        "name": "岗位JD与人事制度库",
        "scope_type": "team",
        "dept_slug": "hr", "team_slug": "hr-recruiting",
        "description": "文具贸易典型岗位 JD + 胜任力模型 + 5 维度简历评估 + 面试题库 + 人事制度，供 HR-01 招聘子任务 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "文具贸易岗位JD与评估规则.md",
                "title": "典型岗位 JD + 胜任力 + 5 维度评估 + 面试题 + 人事制度",
                "content": """# 文具贸易典型岗位 JD 与简历评估规则

## 典型岗位 JD
- 电商运营专员 P-EC：本科/电子商务或市场营销，3-5 年，懂天猫/京东运营/直通车/ROI 优化，KPI GMV+ROI
- 产品管理专员 P-PRD：本科/产品设计或工业设计，3-5 年，懂文具品类规划/生命周期/SKU 管理，KPI 新品成功率+毛利
- 报关与单证专员 P-CUS：本科/国际贸易或物流，2-4 年，懂 HS 归类/报关单证/海关合规，KPI 报关差错率
- 法务专员 P-LEG：本科/法学，3-5 年，懂合同审核/知识产权/贸易合规，KPI 合同审核时效+维权闭环
- IT 工程师 P-IT：本科/计算机，3-5 年，懂 Python/SQL/AI 应用/RAG 开发，KPI 系统可用性+AI 落地
- 渠道销售专员 P-SAL：本科/市场营销，3-5 年，懂经销商管理/渠道政策/KA 运营，KPI 经销商活跃度+回款
- 供应链专员 P-SCM：本科/供应链或物流，3-5 年，懂库存管理/补货/报关协同，KPI 库存周转+断货率

## 胜任力模型（3 维度）
- 专业能力（电商运营/产品规划/报关单证/法务/IT，按岗位）
- 问题解决（渠道决策/库存优化/合规判定/根因分析）
- 协同（跨部门/渠道-供应链-法务协同）

## 5 维度简历评估规则（加权）
- 学历 15%（本科优先，岗位要求硕士优先硕士）
- 工作经验 25%（年限 + 文具/快消/贸易行业）
- 行业匹配 25%（文具/快消/电商/贸易相关）
- 技能匹配 25%（JD 关键技能 tags 命中）
- 软技能 10%（沟通/抗压/执行）
- 综合：A+(≥90) 优先推荐、A(80-89) 推荐、B+(70-79) 备选、B/C(<70) 不推荐

## 面试题库
- 3 通用：自我介绍/职业规划/为何离开上家
- 5 JD 关键技能：按岗位（如电商运营：直通车优化/大促拆解/退货率压降/人群标签/ROI 提升）
- 2 案例：渠道冲突处置案例/库存优化案例

## 人事制度问答
- 考勤：标准工时/弹性制，迟到/早退/缺勤/加班
- 薪资：基本工资+岗位津贴+绩效奖金+加班补贴-扣减=实发，period YYYY-MM
- 福利：五险一金+补充医疗+节日福利+年度体检
- 入转调离流程：入职(合同/工牌/系统开通)→转正(3 月考核)→调岗(部门+HR 审批)→离职(交接+离职证明)

## 注意
- 岗位码 P-EC/P-PRD/P-CUS/P-LEG/P-IT/P-SAL/P-SCM ≠ 产品码 SKU-ZB-* / P-PRD-*（产品码），按上下文区分
- RC-AS-* 招聘需求 → P- 岗位关联
""",
            },
        ],
    },
]


# ───────────────────────── 主流程 ─────────────────────────

async def _get_org(db, slug: str) -> Organization | None:
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    org = (await db.execute(stmt.where(Organization.slug == slug))).scalar_one_or_none()
    if org is None:
        org = (await db.execute(stmt.where(Organization.name == ORG_NAME_FALLBACK))).scalar_one_or_none()
    return org


async def _get_dept_by_slug(db, org_id, slug: str) -> Department | None:
    return (await db.execute(
        select(Department).where(
            Department.organization_id == org_id, Department.slug == slug,
            Department.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def _get_team_by_slug(db, dept_id, slug: str) -> Team | None:
    return (await db.execute(
        select(Team).where(
            Team.department_id == dept_id, Team.slug == slug,
            Team.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def _resolve_scope_id(db, org_id, spec: dict) -> str | None:
    if spec["scope_type"] == "organization":
        return None
    if spec["scope_type"] == "department":
        dept = await _get_dept_by_slug(db, org_id, spec["dept_slug"])
        if dept is None:
            raise RuntimeError(f"部门 slug='{spec['dept_slug']}' 不存在，请先运行 seed_agilestationery_org.py。")
        return str(dept.id)
    if spec["scope_type"] == "team":
        dept = await _get_dept_by_slug(db, org_id, spec["dept_slug"])
        if dept is None:
            raise RuntimeError(f"部门 slug='{spec['dept_slug']}' 不存在。")
        team = await _get_team_by_slug(db, dept.id, spec["team_slug"])
        if team is None:
            raise RuntimeError(f"团队 slug='{spec['team_slug']}（部门 {spec['dept_slug']}）不存在。")
        return str(team.id)
    raise ValueError(f"未知 scope_type: {spec['scope_type']}")


async def main() -> None:
    overall = {"added": 0, "skipped": 0, "failed": 0, "collections": []}
    async with async_session_factory() as db:
        org = await _get_org(db, ORG_SLUG)
        if org is None:
            logger.error("org_not_found", slug=ORG_SLUG)
            sys.exit(1)
        logger.info("org_resolved", id=str(org.id), name=org.name, slug=org.slug)

        for spec in COLLECTIONS:
            scope_id = await _resolve_scope_id(db, org.id, spec)
            scope_label = f"{spec['scope_type']}:{spec['dept_slug'] or 'org'}/{spec['team_slug'] or '-'}"

            colls = await list_collections(db, org.id, scope_type=spec["scope_type"])
            coll = next((c for c in colls if c.name == spec["name"]
                         and (str(c.scope_id) if c.scope_id else None) == (str(scope_id) if scope_id else None)), None)
            if not coll:
                coll = await create_collection(db, org.id, RagCollectionCreate(
                    name=spec["name"], description=spec["description"],
                    embedding_model="text-embedding-v4",
                    chunk_size=spec["chunk_size"], chunk_overlap=spec["chunk_overlap"],
                    scope_type=spec["scope_type"], scope_id=scope_id,
                ))
                await db.commit()
                logger.info("collection_created", id=str(coll.id), name=coll.name, scope=scope_label)
            else:
                coll = await get_collection(db, coll.id)
                logger.info("collection_resolved", id=str(coll.id), name=coll.name,
                            embedding=coll.embedding_model, chunk=f"{coll.chunk_size}/{coll.chunk_overlap}",
                            scope=scope_label)

            existing = {row[0] for row in (await db.execute(
                select(RagDocument.source).where(
                    RagDocument.collection_id == coll.id, RagDocument.deleted_at.is_(None)
                )
            )).all()}

            added = skipped = failed = 0
            failed_sources: list[str] = []
            for d in spec["docs"]:
                if d["source"] in existing:
                    logger.info("skip_exists", source=d["source"], collection=spec["name"])
                    skipped += 1
                    continue
                try:
                    doc = await ingest_document(db, coll, org.id, RagDocumentCreate(
                        source=d["source"], title=d["title"], content=d["content"], folder_path="",
                    ))
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    try:
                        await db.commit()
                    except Exception:  # noqa: BLE001
                        await db.rollback()
                    logger.error("ingest_failed", source=d["source"], collection=spec["name"], error=str(exc))
                    failed += 1
                    failed_sources.append(d["source"])
                    continue
                logger.info("ingested", source=doc.source, title=doc.title, doc_id=str(doc.id),
                            collection=spec["name"])
                added += 1

            overall["added"] += added
            overall["skipped"] += skipped
            overall["failed"] += failed
            overall["collections"].append({
                "name": spec["name"], "scope": scope_label,
                "added": added, "skipped": skipped, "failed": failed, "total": len(spec["docs"]),
                "failed_sources": failed_sources,
            })

    print("\n" + "=" * 72)
    print("敏睿文具 RAG 集合导入完成（覆盖式幂等，可安全重复执行）")
    print("-" * 72)
    print(f"{'集合':<28}{'scope':<32}{'新增':>6}{'跳过':>6}{'失败':>6}{'合计':>6}")
    for c in overall["collections"]:
        print(f"{c['name']:<28}{c['scope']:<32}{c['added']:>6}{c['skipped']:>6}{c['failed']:>6}{c['total']:>6}")
        for src in c.get("failed_sources", []):
            print(f"    ✗ failed: {src}")
    print("-" * 72)
    print(f"合计：新增 {overall['added']} ｜ 跳过 {overall['skipped']} ｜ 失败 {overall['failed']} 个文档")
    if overall["failed"]:
        print(f"⚠️ {overall['failed']} 个文档入库失败（多为 embedding 不可用）：请检查组织级 embedding "
              "供应商配置后重跑（重跑因 source 去重会跳过已成功、重试失败的）")
        print("  注：若前次残留 status=failed 的文档（agilesteel A4 坑），按 source 去重会再次跳过，"
              "需手动清理 RagDocument 后重跑。")
    else:
        print("✓ 无失败：embedding 通道已生效，所有 chunk 均已嵌入向量")
    print("embedding NULL 的历史 chunk 可跑 reembed_agilestationery_rag.py 回填（参数化 collection 名称）")
    print("位置：管理端「敏睿文具」组织 → RAG 知识库 → 各集合（按 scope 分级可见）")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
