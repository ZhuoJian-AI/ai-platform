"""为「敏睿钢铁」组织创建并填充 9 个 RAG 集合（1 组织级 + 7 部门级 + 1 团队级）。

覆盖 9 个 demo 场景中需要 RAG 检索的 8 个场景（FIN-01 无 RAG）：
  - department 级 7 个：排产与炼钢规则库(production) / 设备故障案例库(equipment) /
    质量缺陷案例库(quality) / 供应商资质与行情库(supply) / 客户画像与行情库(sales) /
    能源调度规则库(energy) / 安全法规与隐患案例库(safety)
  - team 级 1 个：岗位JD库(hr-recruiting，HR-01 招聘子任务)
  - organization 级 1 个：员工综合知识库(org，HR-01 培训制度 + 全员问答)

embedding=text-embedding-v4，chunk_size=512，chunk_overlap=64。
幂等：集合按 (org, scope, name) 去重；文档按 (collection, source) 去重。
embedding 失败单文档置 failed 不阻断其余；重跑因 source 去重跳过已成功。

用法:
    docker cp demo/agilesteel/scripts/seed_agilesteel_rag.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_agilesteel_rag.py
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

ORG_SLUG = "agilesteel"
ORG_NAME_FALLBACK = "敏睿钢铁"


# ───────────────────────── RAG 集合定义 ─────────────────────────

COLLECTIONS: list[dict] = [
    # ── 1. 排产与炼钢规则库（dept production，MFG-01） ──
    {
        "name": "排产与炼钢规则库",
        "scope_type": "department",
        "dept_slug": "production", "team_slug": None,
        "description": "炼钢-连铸-轧钢一体化排产优先级 + 转炉终点碳温命中率判定 + 热装热送约束，供 MFG-01 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "排产优先级与冶炼规则.md",
                "title": "一体化排产 5 条优先级 + 转炉终点碳温命中率规则",
                "content": """# 炼钢-连铸-轧钢一体化排产规则

## 排产 5 条优先级（按序）
1. 合同交期最紧的订单优先（按 due_date 升序，逾期优先）
2. 优特钢（P-ST-40Cr / P-ST-42CrMo）单炉配炼，避免与普材混炉
3. 连铸-轧钢热装热送优先（连铸坯温度≥800℃ 直送轧制，省能耗）
4. 设备状态约束：EQ-CV-2（fault）、EQ-RM-3（maintenance）排除/降速
5. 钢种批量经济批量：普材（P-ST-Q235B / P-ST-20MnSi）≥800t/炉组批

## 转炉终点碳温命中率判定
- 终点碳温双命中：endpoint_carbon_actual 与 endpoint_temp_actual 同时命中目标（偏差碳≤0.02%、温度≤15℃）
- 达标线：近期炉次 hit_carbon_temp 双命中率 ≥92%
- 喷溅/返干判定：炉次 actual_tonnage < plan_tonnage*0.95 视为喷溅降产
- 磷命中：phosphorus_actual ≤ phosphorus_target（0.025%）为合格

## 一体化约束
- 连铸拉速与轧制节奏匹配：连铸拉速 0.8-1.2 m/min 对应轧制节奏
- 热装温度门槛：≥800℃ 热装，<800℃ 入冷坯炉（标温降与能耗代价）
- 炉次 steel_grade 回挂 PLM 钢种主数据 P-ST-，按 heat_no 关联 ERP 炉次成本 PC-AS-
- 废钢配料 charging_scrap（M-SCR-HMS1 等）按钢种适用范围选料
""",
            },
        ],
    },

    # ── 2. 设备故障案例库（dept equipment，EQP-01） ──
    {
        "name": "设备故障案例库",
        "scope_type": "department",
        "dept_slug": "equipment", "team_slug": None,
        "description": "高炉/转炉/连铸/轧机关键设备历史故障 5W2H + 排查步骤 + 配件清单，供 EQP-01 预测性维护 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "关键设备故障案例库.md",
                "title": "钢铁关键设备故障 5W2H 根因 + 排查 + 配件",
                "content": """# 钢铁关键设备故障案例库

## 转炉氧枪漏水（EQ-CV-2 典型）
- 根因：氧枪枪头冷却水泄漏烧穿（高温铁水冲刷+热应力）
- 排查步骤：(1) 检查氧枪进出水流量差 (2) 振动趋势 listSensorReadings 振动↑温度↑ (3) 确认枪头烧穿位置
- 配件：SP-CV-TUYERE 氧枪枪头（互换件 SP-CV-LANCE 氧枪本体）
- 验证标准：更换后水流量差≤0.5m³/h，振动≤2.0mm/s
- 预防周期：枪头使用≥120 炉次更换

## 轧机轧辊剥落（EQ-RM-3 典型）
- 根因：轧辊疲劳裂纹扩展导致表层剥落（轧制力长期超载+冷却不均）
- 排查：振动劣化趋势 + 轧材表面周期性印痕
- 配件：SP-RM-ROLL 轧辊（库存低于安全 4 件需补货）
- 预防：轧辊使用达 2000t 后孔型检查 + 磨削

## 高炉冷却壁烧穿（EQ-BF-1）
- 根因：冷却壁长期热负荷过高局部烧穿
- 配件：SP-BF-COOLING 冷却壁
- 预防：冷却壁温度场监测，局部偏高安排状态检测

## 连铸结晶器漏钢（EQ-CCM-1）
- 根因：结晶器铜板磨损 + 液面波动漏钢
- 配件：SP-CCM-MOLD 结晶器
- 预防：铜板磨损量达限更换

## 健康分判定（scoreMaintenancePriority 依据）
- 健康分<60 或 trend=下降 为重点关注
- 故障概率 fault_probability_7d≥0.6 立即安排预测性维护
- 优先级 = 风险(100-健康分) × 产能影响(A级设备1.0) × 备件现货 +20
""",
            },
        ],
    },

    # ── 3. 质量缺陷案例库（dept quality，QAL-01） ──
    {
        "name": "质量缺陷案例库",
        "scope_type": "department",
        "dept_slug": "quality", "team_slug": None,
        "description": "8 类钢材表面缺陷历史 5W2H 根因 + 纠正 + 预防，供 QAL-01 质量追溯 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "钢材表面缺陷案例库.md",
                "title": "8 类钢材表面缺陷根因 + 纠正 + 预防",
                "content": """# 钢材表面缺陷案例库（8 类）

## 表面裂纹 D-CRACK
- 根因：连铸坯温应力导致裂纹扩展（二冷配水不当/拉速不稳）
- 纠正：优化二冷配水制度，提高连铸拉速稳定性
- 预防：同钢种开炉前校核二冷制度；连铸电磁搅拌 EMS

## 表面划伤 D-SCRATCH
- 根因：轧制导卫/输送辊道擦伤
- 纠正：检查导卫磨损，辊道润滑
- 预防：导卫达 2000t 后检查

## 非金属夹杂 D-INCL
- 根因：精炼洁净度不足 / 连铸保护渣卷入
- 纠正：提升 RH 真空脱气时间≥15min，优化中间包挡墙
- 预防：洁净钢种（45#/40Cr/42CrMo）延长精炼时间

## 成分偏析 D-SEG
- 根因：连铸凝固组织不均 / 浇温控制偏差
- 纠正：调整连铸电磁搅拌参数 + 浇温控制
- 预防：合金钢种启用 EMS

## 尺寸超差 D-DIM
- 根因：轧制孔型磨损 / 张力控制失稳
- 纠正：更换轧辊 SP-RM-ROLL，调整张力
- 预防：批量达 2000t 后检查孔型

## 氧化铁皮 D-SCALE
- 根因：加热炉氧化严重 / 除鳞不净
- 纠正：提高除鳞水压，缩短加热时间
- 预防：定期校核除鳞压力

## 折叠 D-LAP
- 根因：轧件表面缺陷被压入折叠
- 纠正：检查轧件表面，修磨
- 预防：轧前表面检查

## 力学性能不达标 D-MECH
- 根因：成分微调 / 终轧温度 / 冷却制度偏差
- 纠正：优化控冷工艺，调整终轧温度
- 预防：高性能钢种（42CrMo）按控冷曲线执行

## 追溯链路
缺陷 DF（MES 裸码）→ 工单 SWO → 炉次 HT → 钢种 P-ST- → PLM 历史案例 DF-AS-（带 AS 段，不同码空间勿直传 DF）
""",
            },
        ],
    },

    # ── 4. 供应商资质与行情库（dept supply，SCM-01） ──
    {
        "name": "供应商资质与行情库",
        "scope_type": "department",
        "dept_slug": "supply", "team_slug": None,
        "description": "供应商评级 + 大宗原料行情 + 废钢判级标准，供 SCM-01 采购风控 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "供应商评级与行情库.md",
                "title": "大宗原料供应商评级 + 行情 + 废钢判级",
                "content": """# 供应商资质与行情库

## 供应商评级（A/B/C）
- A 级：履约率≥95%、质量合格率≥99%、信用无逾期 → 优先采购
- B 级：履约 85-95% → 备选，限量
- C 级：履约<85% 或应付逾期 → 预警，淘汰候选
- 铁矿石：S-STEEL-ORE-01（BHP，A）、S-STEEL-ORE-02（淡水河谷，A）
- 焦炭：S-STEEL-COKE-01（山西焦煤，A）
- 废钢：S-STEEL-SCR-01（长三角，B）、S-STEEL-SCR-02（华中，B）
- 合金：S-STEEL-ALY-01（中信合金，A）

## 大宗原料行情因子
- 铁矿石 62% 粉矿：国际普氏指数 + 港口库存 + 钢厂开工率
- 焦炭：焦煤价格 + 环保限产
- 废钢：成材需求 + 电炉开工
- 价格预测：近期报价(ASQ)均值 + 行情趋势因子

## 废钢判级标准（SCR-）
- SCR-HMS1 重废1型：厚度≥6mm，密度 1.2 t/m³，杂质≤1.0%，牌价 2680
- SCR-HMS2 重废2型：厚度≥4mm，密度 1.0 t/m³，杂质≤1.5%，牌价 2520
- SCR-BROKEN 破碎料：密度 0.9，杂质≤2.0%
- SCR-TURNINGS 车屑：密度 0.7，杂质≤3.0%，限量使用（仅 Q235B 限量）
- 判级不达标（如重废2型含破碎料超标）→ 降级扣价

## 采购决策规则
- 库存低于安全线 + 下月排产增量 → 紧急补货（urgency 高）
- 多家比价按 单价/交期/账期/评级 综合排序（compareQuotations）
- 应付逾期(days_overdue>0) → 供应商信用风险预警
""",
            },
        ],
    },

    # ── 5. 客户画像与行情库（dept sales，SAL-01） ──
    {
        "name": "客户画像与行情库",
        "scope_type": "department",
        "dept_slug": "sales", "team_slug": None,
        "description": "客户 360 画像 + 分区域分品种量价预测 + 订单评审规则，供 SAL-01 销售 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "客户画像与行情库.md",
                "title": "客户分层 + 量价预测 + 订单评审规则",
                "content": """# 客户画像与行情库

## 客户 4 类分层
- 工程项目 C-AS-PROJ（桥梁/建筑）：单笔大、账期 90 天、信用 A，按单排产
- 钢贸经销商 C-AS-TRADE：批量中、账期 30-45 天，备货为主
- 直供终端 C-AS-OEM（机械/汽车/能源）：协议量、稳定，账期 60 天
- 海外出口 C-AS-EXP：FOB 报价、船期约束，USD 结算

## 分区域分品种量价预测
- 建筑用钢（P-ST-Q345B/20MnSi/Q235B）：下游基建景气 + 区域固投
- 优特钢（P-ST-45#/40Cr/42CrMo）：机械/汽车/能源景气 + 替代进口
- 量价预测：近期销售订单(ASSO) + 商机 + 下游景气因子

## 订单评审规则
- 产能占用：按生产订单 SPO + 炉次 HT 排产余量
- 库存可承诺：钢材成品 M-ST-*-Bar 的 available_qty
- 交期窗口：现货优先（listInventory available_qty），需排产关联 SPO
- 评审结论：可接（产能+库存充足）/ 有条件（缓排/部分现货）/ 缓排
- 应收逾期(ASINV days_overdue>0) → 信用风险，影响接单

## 交期答复秒级
- 现货：available_qty≥订单量 → 答复 3-5 天发货
- 需排产：关联 SPO + 炉次 HT 周期，答复 15-30 天
""",
            },
        ],
    },

    # ── 6. 能源调度规则库（dept energy，ENE-01） ──
    {
        "name": "能源调度规则库",
        "scope_type": "department",
        "dept_slug": "energy", "team_slug": None,
        "description": "煤气/蒸汽/电力平衡规则 + 燃烧优化 + 排放阈值 + 碳足迹，供 ENE-01 能源调度 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "能源调度与排放规则.md",
                "title": "介质平衡 + 燃烧优化 + 排放阈值 + 碳足迹",
                "content": """# 能源调度与排放规则

## 介质平衡规则
- 转炉煤气回收：吨钢回收量≥85m³/t，回收至 8 万 m³ 储气柜供轧材加热炉（EDP 调度方案）
- 余热蒸汽并网：余热锅炉 120t/h 蒸汽并网，补轧材缺口（gap<0 优先并网）
- 煤气放散率目标：≤3%，超放散预警
- 高炉煤气压力<8kPa 接近放散阈值 → 提产储气柜回收

## 燃烧优化
- 高炉热风炉/加热炉/锅炉：空燃比优化（过剩空气系数 1.05-1.15）
- 送风参数：根据炉况实时调整，降低煤气消耗

## 排放阈值（mg/m³，超标预警）
- SO2：烧结机头 200、焦炉 100
- NOx：转炉 300
- 颗粒物：轧材 30、烧结 40
- CO2：吨钢≤1.85 t
- 超标风险：value/limit≥0.95 高风险(P0)，≥0.85 中风险(P1)

## 碳足迹核算
- 分工序能耗标杆(listEnergyConsumption)：焦化 105、烧结 48、炼铁 385、炼钢 -8(回收)、轧材 58-65 kgce/t
- 吨钢 CO2 = Σ 工序能耗 × 排放因子
- 支撑低碳产品认证与碳资产管理

## 预警处置
- 介质缺口(predictMediaShortfall gap<0)：余热蒸汽并网 + 回收转炉煤气
- 排放超标(scoreEmissionRisk)：提高脱硫出力 / 清灰提压
""",
            },
        ],
    },

    # ── 7. 安全法规与隐患案例库（dept safety，SAF-01） ──
    {
        "name": "安全法规与隐患案例库",
        "scope_type": "department",
        "dept_slug": "safety", "team_slug": None,
        "description": "安全规程条款 + 整改标准 + 隐患历史案例，供 SAF-01 违章识别与隐患闭环 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "安全法规与隐患案例库.md",
                "title": "安全规程条款 + 整改标准 + 隐患案例",
                "content": """# 安全法规与隐患案例库

## 违章类型 → 规程条款 + 整改建议
- 未戴安全帽：《安全生产责任制》§3.2 进入生产区须佩戴安全帽 → 立即补戴+班组教育+扣分
- 高处作业未系带：《高处作业安全管理规定》§4.1 2m 以上作业须系安全带 → 停工补系+复训
- 违规动火：《动火作业管理规定》§2.1 煤气区域严禁动火吸烟 → 清离现场+煤气检测+复训
- 未执行LOTO：《检修挂牌上锁规定》§3.1 检修须执行 LOTO → 补办挂牌+联锁验证+复训
- 未佩报警器：《煤气安全管理规定》§5.2 煤气区域须佩戴报警器 → 补发报警器+煤气专项培训
- 未穿防护服：《劳动防护用品管理规定》§3.3 炉前作业须穿高温防护服 → 补穿+劳保盘点

## 风险点分级（红橙黄蓝）
- 红色：转炉主控室（高温液渣喷溅）、1#高炉炉台（煤气泄漏）→ 立即闭环+联动应急
- 橙色：连铸二冷室（受限空间）、轧机检修（误启动）、天车（冲顶）
- 黄色：轧制线（检修 LOTO）
- 蓝色：原料场（扬尘）、化验室（试剂）

## 隐患闭环规则
- 优先级 scoreHazardPriority = 风险等级权重(红1.0/橙0.7/黄0.4/蓝0.2)×100 + 暴露人数×2 + 紧急度×5
- P0-立即（score≥100）、P1-本周（≥60）、P2-两周
- 红色隐患必须 24h 内闭环 + 应急联动
- 隐患 equipment_code 关联 EQ- 设备，闭环到设备预测性维护

## 应急处置
- 煤气泄漏：疏散+警戒+通风+检测+堵漏
- 液渣喷溅：撤离至安全距离+挡渣墙
""",
            },
        ],
    },

    # ── 8. 岗位JD库（team hr-recruiting，HR-01 招聘子任务） ──
    {
        "name": "岗位JD库",
        "scope_type": "team",
        "dept_slug": "hr", "team_slug": "hr-recruiting",
        "description": "钢铁典型岗位 JD + 胜任力模型 + 5 维度简历评估规则 + 面试题库，供 HR-01 招聘子任务 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "钢铁岗位JD与评估规则.md",
                "title": "钢铁典型岗位 JD + 胜任力 + 5 维度评估 + 面试题",
                "content": """# 钢铁典型岗位 JD 与简历评估规则

## 典型岗位 JD
- 炼钢工程师 P-MELT：硕士/冶金工程，5-9 年，懂转炉炼钢/终点碳温控制/钢种优化，KPI 炉次产量+一次合格率
- 轧钢工程师 P-ROLL：本科/材料成型，8 年，懂热轧工艺/板形控制/轧辊管理
- 特钢工艺工程师 P-SPECIAL：硕士/材料科学，6 年，懂特钢深加工/非调质钢/切削性能
- 设备工程师 P-EQP：本科/机械工程，6-12 年，懂预测性维护/振动诊断/高炉转炉设备
- 能源调度员 P-ENE：硕士/热能工程，4 年，懂能源调度/煤气平衡/碳足迹
- 安全员 P-SAF：本科/安全工程，5 年，懂隐患排查/煤气作业/应急
- IT 工程师 P-IT：硕士/计算机，4-5 年，懂 Python/工业大数据/预测模型

## 胜任力模型（3 维度）
- 专业能力（钢种工艺/设备诊断/能源调度，按岗位）
- 问题解决（根因分析/排产决策/应急处置）
- 协同（跨工序/跨部门）

## 5 维度简历评估规则（加权）
- 学历匹配 15%（硕士优先于本科）
- 工作经验 25%（年限 + 钢铁行业）
- 行业匹配 25%（钢铁/冶金/材料相关）
- 技能匹配 25%（JD 关键技能 tags 命中）
- 软技能 10%（沟通/抗压）
- 综合：A+(≥90)优先推荐、A(80-89)推荐、B+(70-79)备选、B/C(<70)不推荐

## 面试题库
- 3 通用：自我介绍/职业规划/为何离开上家
- 5 JD 关键技能：按岗位（如炼钢工程师：转炉终点控制/钢种微调/喷溅处置/精炼工艺/连铸拉速）
- 2 案例：故障处置案例/排产优化案例

## 注意
- 岗位码 P-MELT（炼钢工程师）≠ PLM 钢种 P-ST-Q345B，按第二段区分
- shortlistResumes 是 POST 不绑定，用 listResumesByPosition + LLM 评估替代
""",
            },
        ],
    },

    # ── 9. 员工综合知识库（org，HR-01 培训制度 + 全员问答） ──
    {
        "name": "员工综合知识库",
        "scope_type": "organization",
        "dept_slug": None, "team_slug": None,
        "description": "组织级员工综合知识库：差旅报销流程 + 状态枚举 + HR 制度摘要，对全员 auto-load。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "差旅报销流程与状态枚举.md",
                "title": "差旅报销 5 步流程 + 状态枚举",
                "content": """# 差旅报销流程与状态枚举

## 报销 5 步流程
1. 申请中：员工在 ERP 提交差旅报销申请（录入金额/事由/票据）
2. 直属经理审批中：直属经理审核事由与金额合理性
3. 部门总监联签中：超额度需部门总监联签
4. 财务复核中：财务核对票据合规性（凭证 BV-AS- 状态=财务复核中）
5. 已打款：财务打款（每周二、四集中打款）→ 已闭环

## 状态枚举
- 申请中 → 直属经理审批中 → 部门总监联签中 → 财务复核中 → 已打款 → 已闭环
- 凭证号 BV-AS-2026-XXXX，status 字段对应上述阶段
- period 字段：会计期间 YYYY-MM（如 2026-07）

## 查询口径
- 员工问"我的差旅报销走到哪一步"→ 调 ERP listVouchers(period="YYYY-MM")，按 summary 含"差旅费报销"定位，读 voucher_no/status/debit_total/entry_date
- 当前状态 + 第几步 + 金额 + 提交日期 + 预计下一步/打款日（每周二、四）

## HR 制度摘要
- 考勤：三班（早班/中班/晚班）+ 常白，迟到/早退/缺勤/加班
- 请假：年假/病假/事假/调休/婚假，待批/已批/已驳/已销
- 薪酬：基本工资+岗位津贴+绩效奖金+加班补贴-扣减=实发，period YYYY-MM
- 绩效：60-99 分，A(≥90)/B(80-89)/C(70-79)/D(<70)
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
            raise RuntimeError(f"部门 slug='{spec['dept_slug']}' 不存在，请先运行 seed_agilesteel_org.py。")
        return str(dept.id)
    if spec["scope_type"] == "team":
        dept = await _get_dept_by_slug(db, org_id, spec["dept_slug"])
        if dept is None:
            raise RuntimeError(f"部门 slug='{spec['dept_slug']}' 不存在。")
        team = await _get_team_by_slug(db, dept.id, spec["team_slug"])
        if team is None:
            raise RuntimeError(f"团队 slug='{spec['team_slug']}'（部门 {spec['dept_slug']}）不存在。")
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
    print("敏睿钢铁 RAG 集合导入完成（覆盖式幂等，可安全重复执行）")
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
    else:
        print("✓ 无失败：embedding 通道已生效，所有 chunk 均已嵌入向量")
    print("embedding NULL 的历史 chunk 可跑 reembed_agilesteel_rag.py 回填（参数化 collection 名称）")
    print("位置：管理端「敏睿钢铁」组织 → RAG 知识库 → 各集合（按 scope 分级可见）")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
