"""为「星途热熔胶」组织创建并填充 9 个 RAG 集合（均为部门级）。

覆盖 9 个 demo 场景中需要 RAG 检索的场景：
  - 研发中心(rd) 2 个：配方研发知识库(starhma-rd-formula-kb) /
    实验分析知识库(starhma-rd-experiment-kb)
  - 营销销售中心(sales) 1 个：销售知识库(starhma-sales-kb)
  - 生产制造部(mfg) 2 个：排产知识库(starhma-mfg-schedule-kb) /
    设备维护知识库(starhma-eqp-maintenance-kb)
  - 供应链部(scm) 1 个：库存供应链知识库(starhma-scm-inventory-kb)
  - 品质与技术服务部(qas) 1 个：售后故障知识库(starhma-qas-aftersales-kb)
  - 综合管理部(admin) 2 个：经营分析知识库(starhma-admin-bi-kb) /
    文档处理知识库(starhma-admin-doc-kb)

embedding=text-embedding-v4，chunk_size=512，chunk_overlap=64。
幂等：集合按 (org, scope, name) 去重；文档按 (collection, source) 去重。
embedding 失败单文档置 failed 不阻断其余；重跑因 source 去重跳过已成功。
注：首次入库依赖 agileac 真 embedding key（README §3 SQL 同步后从 agileac
    复制 aliyun-embedding-openai + aliyun-all-openai provider/key）。
    若前次入库残留 status=failed 的文档，按 source 去重会再次跳过（A4 坑），
    需手动清理 RagDocument 后重跑，或先删除该 collection 再重建。

用法:
    docker cp demo/starhma/scripts/seed_starhma_rag.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starhma_rag.py
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
from app.schemas.rag import RagCollectionCreate, RagDocumentCreate  # noqa: E402
from app.services.rag_service import (  # noqa: E402
    create_collection, get_collection, ingest_document, list_collections,
)

logger = structlog.get_logger()

ORG_SLUG = "starhma"
ORG_NAME_FALLBACK = "星途热熔胶"


# ───────────────────────── RAG 集合定义 ─────────────────────────

COLLECTIONS: list[dict] = [
    # ── 1. 配方研发知识库（dept rd） ──
    {
        "name": "starhma-rd-formula-kb",
        "scope_type": "department",
        "dept_slug": "rd", "team_slug": None,
        "description": "配方设计规则、原料组分功能、配方智能推荐与性能预测流程、失效案例，供配方研发 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "配方设计规则与命名约定.md",
                "title": "配方编号规则、标准品/定制配方与跨系统关联",
                "content": """# 配方设计规则与命名约定

## 配方编号（FORM-）
- 标准品 FORM-STD-001/002/003：面向七大下游的通用热熔胶/热熔压敏胶
  - FORM-STD-001：EVA 基高速包装热熔胶（软化点 95℃、粘度 8500mPa·s、开放时间 4s）
  - FORM-STD-002：APAO 基高温热熔胶（软化点 145℃、耐温 120℃）
  - FORM-STD-003：SIS 基热熔压敏胶（剥离力 18N、初粘 12#）
- 定制配方 FORM-CUS-001/002/003：按客户工况定制
  - FORM-CUS-001：鞋材箱包低温热熔胶（耐 -10℃、开放时间 7s）
  - FORM-CUS-002：医疗用品低温热熔胶（施胶 130℃、剥离 14N、FDA + ISO-10993）
  - FORM-CUS-003：物流快递袋压敏胶（初粘 15#、低温持粘）

## 跨系统关联（no-guessing，勿互传编号）
- 标准品 FORM-STD-001 → ERP 成品胶 M-FG-001（按 product_code 关联，FORM- 当 M-FG- 传 ERP）
- 定制配方 FORM-CUS-001 → MES 批次 BAT-2026-0703（按 formula_no 关联，BAT- 当 FORM- 传 FRM）
- 工艺参数 PP- 挂 formula_no=FORM-；检测报告 QR-FG- 挂 formula_no=FORM-
- 配方保密：FORM- 的组分明细为机密，仅 rd 部门可见；外发前须脱敏隐藏组分比例
""",
            },
            {
                "source": "原料组分功能与代码体系.md",
                "title": "ING- 组分编码、功能分类与 ERP 物料 prefix 转换",
                "content": """# 原料组分功能与代码体系

## 组分编码（ING-）
- ING-RES- 树脂：ING-RES-001 EVA（VA% 28%）、ING-RES-002 APAO、ING-RES-003 SIS
- ING-TK- 增粘剂：ING-TK-001 松香改性树脂、ING-TK-002 C5 石油树脂、ING-TK-003 萜烯树脂
- ING-WAX- 蜡：ING-WAX-001 石蜡（熔点 58℃）、ING-WAX-002 微晶蜡、ING-WAX-003 费托蜡
- ING-AO- 抗氧剂：ING-AO-001 BHT、ING-AO-002 1010、ING-AO-003 168

## 组分功能规则
- 树脂决定基体软化点与初粘力：EVA 通用、APAO 耐高温、SIS 压敏
- 增粘剂调节初粘与剥离：松香改性初粘高、C5 石油树脂耐老化
- 蜡调节粘度与开放时间：费托蜡降粘明显、微晶蜡增韧
- 抗氧剂用量 0.3-0.8%，防黄变与热氧老化

## 跨系统 prefix 转换（关键 no-guessing）
- 组分 ING-RES-001 → ERP 采购物料 M-RES-001（prefix 转换 ING-RES-→M-RES-）
- 组分 ING-TK-002 → ERP M-TK-002；ING-WAX-001 → M-WAX-001；ING-AO-001 → M-AO-001
- 调 ERP listMaterials(material_code='M-RES-001') 查物料单价/库存，勿把 ING- 当 M- 传 ERP
""",
            },
            {
                "source": "配方智能推荐流程.md",
                "title": "recommendFormula 入参语义、历史相似配方匹配与配比输出",
                "content": """# 配方智能推荐流程

## recommendFormula 入参（FRM 端点）
- industry：下游行业（医疗/食品日化包装/物流快递袋/鞋材箱包/汽车内饰/粘扣带/家居）
- substrate：客户基材（无纺布/PE 膜/铝箔/纸张/皮革/EVA 泡棉）
- temp：施胶温度（℃），低温 130℃ 以下优先 SIS/APAO
- open_time：开放时间（s），高速自动包装 3-5s、手工 6-10s
- peel：目标剥离力（N/25mm）
- env_std：环保标准（FDA/REACH/SGS/ISO-10993）
- cost：成本上限（元/kg）

## 推荐流程
- 输入工况 → 检索历史相似配方（按 industry + substrate + env_std 命中）
- 输出推荐配方 FORM-CUS- 或 FORM-STD- + 初始配比（ING-RES-/ING-TK-/ING-WAX-/ING-AO- 组分百分比）
- 例：医疗无纺布/PE 膜、130℃、开放 6s、剥离 14N、FDA+ISO-10993、成本 40 元/kg
  → 推荐 FORM-CUS-002 + ING-RES-001/ING-TK-002/ING-WAX-001/ING-AO-001 配比
- 勿杜撰配比；配方组分比例受成本上限与性能目标约束，超出范围须提示风险
""",
            },
            {
                "source": "性能预测规则.md",
                "title": "predictPerformance 性能指标预测与达标判定",
                "content": """# 性能预测规则

## predictPerformance 入参与输出
- 输入 formula_no（FORM-）+ 组分配比，输出软化点/粘度/剥离力/耐温/初粘预测值
- 性能指标（PERF-）：
  - 软化点（环球法 ℃）：EVA 基 80-110、APAO 基 130-160、SIS 基 70-95
  - 粘度（mPa·s/180℃）：高速包装 5000-10000、压敏 3000-8000
  - 剥离力（N/25mm）：包装 4-8、压敏 12-20
  - 耐温（℃）：常温 60、低温 -10、高温 120
  - 初粘（#）：压敏 10-18

## 达标判定
- 按客户工况对照达标：医疗低温 FORM-CUS-002 须耐 -10℃ + 剥离 14N + FDA
- 偏差预警：预测偏离目标值 ±15% 须提示调整组分（增粘剂±5% 调剥离、蜡±3% 调粘度）
- 性能预测结果挂 PERF- 编号，关联 formula_no；勿把 PERF- 当 FORM- 传 FRM
- 复杂工况（多基材/极端温）须提示客户送样验证，勿给死结论
""",
            },
            {
                "source": "配方失效记录与案例库.md",
                "title": "FR- 失效记录、根因与配方调整建议",
                "content": """# 配方失效记录与案例库

## 失效记录（FR-）
- FR-2025-021：FORM-CUS-002 医疗配方初粘不足，根因 ING-TK-002 用量偏低 +5%，调整后达标
- FR-2025-035：FORM-CUS-001 低温 -15℃ 脆断，根因 ING-WAX-001 石蜡过量，改 ING-WAX-002 微晶蜡
- FR-2025-048：FORM-STD-002 高温 130℃ 软化点不足，根因 ING-RES-002 APAO 批次波动
- 每条失效记录关联 formula_no + batch_no(BAT-) + 实验号(EXP-) + 检测报告(QR-FG-)

## 根因分析与配方调整
- 失效类别：初粘不足/剥离偏低/耐温不足/黄变/拉丝/开放时间偏短
- 调整规则：初粘不足→增粘剂+3-5%；剥离偏低→树脂+2-4%；黄变→抗氧剂+0.2%
- 失效闭环：FR- → 配方版本升级（FORM-CUS-002 v2）→ 重测 EXP- → 重出 QR-FG-
- 调 listFailureRecords(formula_no='FORM-CUS-002') 查历史失效，勿杜撰失效原因
""",
            },
            {
                "source": "配方保密与版本管理.md",
                "title": "配方组分机密、版本升级与外发脱敏",
                "content": """# 配方保密与版本管理

## 配方机密等级
- 组分明细（ING-RES- 百分比）为核心机密，仅 rd/formula-team 可见
- 外发配方卡仅公开性能指标（软化点/粘度/剥离/耐温）+ 环保认证，隐藏组分比例

## 版本升级
- FORM-CUS-002 v1 → v2：调整 ING-TK-002 用量修复初粘不足（关联 FR-2025-021）
- 版本号挂在 formula_no 字段，MES 批次 BAT- 按 formula_no+v 版本关联
- 旧版本批次保留可追溯，勿删除；新批次投产须用最新版本

## 外发脱敏
- 调 desensitizeFormula(formula_no='FORM-CUS-002') 产出脱敏配方卡
- 脱敏方式：隐藏组分比例精度（仅公开 ±5% 范围）、隐藏具体 ING- 编号
- 脱敏后配方卡供 sales-rep 报价用；勿把完整组分发给客户
""",
            },
            {
                "source": "配方跨系统闭环与编号互传规则.md",
                "title": "FORM→M-FG-/BAT- 关联、ING→M- prefix 转换",
                "content": """# 配方跨系统闭环与编号互传规则

## 闭环 1：配方 → 成品胶
- FORM-STD-001（FRM 配方）→ M-FG-001（ERP 成品胶），按 product_code 关联
- 调 ERP listMaterials(material_code='M-FG-001') 查成品库存/单价
- 标准品配方与成品胶 1:1 对应，FORM-STD-002 → M-FG-002，FORM-STD-003 → M-FG-003

## 闭环 2：定制配方 → 生产批次
- FORM-CUS-001（FRM 定制配方）→ BAT-2026-0703（MES 批次），按 formula_no 关联
- 定制配方转产后，MES 扥次 BAT- 承载 formula_no；调 MES getWorkOrder(work_order_no) 追溯
- 勿把 BAT- 当 FORM- 传 FRM、勿把 FORM- 当 M-FG- 传 ERP

## 闭环 3：组分 → 采购物料
- ING-RES-001 → M-RES-001（prefix 转换），勿把 ING-RES- 当 M-RES- 传 ERP
- 采购补货按 M-RES-001 下采购单 POHMA，勿用 ING-RES- 下单
""",
            },
        ],
    },
    # ── 2. 实验分析知识库（dept rd） ──
    {
        "name": "starhma-rd-experiment-kb",
        "scope_type": "department",
        "dept_slug": "rd", "team_slug": None,
        "description": "流变/拉力/持粘测试方法、实验数据分析与报告生成流程、测试方案模板，供实验分析 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "流变测试方法.md",
                "title": "EXP-RHE- 流变仪测试规程与数据解读",
                "content": """# 流变测试方法

## 流变实验（EXP-RHE-）
- EXP-RHE-001：FORM-CUS-002 医疗配方流变测试，180℃ 粘度曲线 + 剪切速率扫描
- EXP-RHE-002：FORM-STD-001 EVA 包装胶流变测试，软化点附近粘度突变
- 仪器：旋转流变仪，平板 25mm，间隙 1mm，剪切速率 0.1-1000 s⁻¹
- 测试条件：180℃ 恒温，扫描 10 个剪切速率点

## 数据解读
- 粘度曲线呈剪切变稀行为；偏离标准曲线 ±20% 为异常
- 软化点附近粘度突变点即环球法软化点参考值
- 异常识别：低剪切粘度异常高（疑似交联/凝胶）、高剪切粘度异常低（疑似降解）
- 数据挂 EXP-RHE- 编号 + formula_no + batch_no(BAT-)；勿把 EXP- 当 FORM- 传 FRM
""",
            },
            {
                "source": "拉力测试方法.md",
                "title": "EXP-TEN- 拉力机剥离/拉伸测试规程",
                "content": """# 拉力测试方法

## 拉力实验（EXP-TEN-）
- EXP-TEN-001：FORM-CUS-002 医疗配方 180° 剥离测试（无纺布/PE 膜基材）
- EXP-TEN-002：FORM-CUS-001 鞋材配方拉伸剪切强度测试
- 仪器：万能拉力机，载荷 500N，速度 300mm/min
- 样品制备：250mm × 25mm，施胶量 30g/m²，压合 24h 后测试

## 测试规程
- 180° 剥离：基材→胶层→基材，剥离速度 300mm/min，取 5 个样品均值
- 拉伸剪切：搭接 25mm × 25mm，速度 50mm/min
- 数据取均值 ± 标准差；剥离力低于目标值 80% 为异常

## 异常识别
- 剥离力离散度大（CV>15%）：疑似施胶不均或基材表面处理不一致
- 剥离面观察：内聚破坏（胶层断）正常、粘附破坏（界面断）异常须调整配方
- 数据挂 EXP-TEN- + formula_no + 样品号 SMP-；勿把 SMP- 当 EXP- 传
""",
            },
            {
                "source": "持粘与初粘测试方法.md",
                "title": "EXP-ADH- 持粘/初粘测试与达标判定",
                "content": """# 持粘与初粘测试方法

## 持粘实验（EXP-ADH-）
- EXP-ADH-001：FORM-STD-003 压敏胶持粘测试，40℃ 1kg 载荷下位移 ≤2mm
- EXP-ADH-002：FORM-CUS-003 物流袋配方低温持粘，-10℃ 载荷 500g
- 仪器：持粘性测试仪，测试板 25mm × 25mm，砝码 1kg/500g

## 初粘测试
- 初粘（钢球法 #）：钢球 1-30#，斜面 30°，记录最大粘住钢球号
- 压敏胶初粘 ≥10# 为达标；物流袋低温初粘 ≥8#

## 达标判定
- 持粘位移 >2mm 为异常；低温持粘须在 -10℃ 环境箱内测试 30min
- 异常根因：增粘剂过量（持粘不足）、蜡过量（初粘偏低）、树脂过量（脆断）
- 数据挂 EXP-ADH- + formula_no + 测试方案号 TS-；勿把 TS- 当 EXP- 传
""",
            },
            {
                "source": "实验数据分析流程.md",
                "title": "analyzeExperimentData 异常识别与关联失效",
                "content": """# 实验数据分析流程

## analyzeExperimentData 入参与输出
- 输入 experiment_no（EXP-RHE-/EXP-TEN-/EXP-ADH-），输出 anomaly_flags + statistics + recommendations
- 异常识别维度：
  - 数值异常：偏离标准曲线 ±20%、超出目标值 80-120% 区间
  - 离散度异常：CV>15%、5 个样品极差 >30%
  - 趋势异常：连续批次性能下滑（关联历史 EXP-）

## 关联失效记录
- 异常数据须关联失效记录 FR-：例 EXP-TEN-001 剥离偏低 → 关联 FR-2025-021
- 关联字段：formula_no + batch_no(BAT-) + failure_record_no(FR-)
- 异常根因建议：组分调整（ING-TK-±5%）或工艺调整（PP-REACT- 温度±5℃）

## 输出规范
- 返 anomaly_flags 列表（含指标/异常类型/偏离幅度）、statistics（均值/标准差/CV）、recommendations
- 勿杜撰异常原因；未命中标准库的异常须提示送样复测
- 数据挂 experiment_no；勿把 EXP- 当 FR- 传 FRM listFailureRecords
""",
            },
            {
                "source": "实验报告生成流程.md",
                "title": "generateExperimentReport 报告结构与签发",
                "content": """# 实验报告生成流程

## generateExperimentReport 入参与输出
- 输入 experiment_no（EXP-）或 formula_no + batch_no，输出标准化实验报告
- 报告结构：
  1. 实验信息：experiment_no/formula_no/batch_no/样品号 SMP-/测试方案 TS-
  2. 测试方法：引用 EXP-RHE-/EXP-TEN-/EXP-ADH- 测试规程
  3. 数据汇总：均值±标准差、CV、达标判定
  4. 异常与根因：anomaly_flags + 关联 FR- 失效记录
  5. 结论与建议：达标/不达标、配方调整建议（ING- 组分±%）

## 报告签发
- 报告号 EXP-RPT-，关联 experiment_no + formula_no
- 签发流程：实验员 rd-analyst 生成 → rd-formulator 复核 → 主管签发
- 报告归档到 FRM；售后 QAS-01 诊断时可调历史报告追溯配方性能
- 勿杜撰数据；不达标报告须明确标红 + 调整建议，勿给虚假达标结论
""",
            },
            {
                "source": "测试方案模板.md",
                "title": "TS- 测试方案模板与样品管理",
                "content": """# 测试方案模板与样品管理

## 测试方案（TS-）
- TS-2026-001：医疗配方 FORM-CUS-002 全性能测试方案（流变+拉力+持粘+初粘+FDA 验证）
- TS-2026-002：物流袋配方 FORM-CUS-003 低温性能测试方案
- 方案字段：方案号 TS- / 适用 formula_no / 测试项清单 / 样品数 / 测试条件 / 判定标准

## 测试项清单
- 流变 EXP-RHE- / 拉力 EXP-TEN- / 持粘 EXP-ADH-，每项至少 5 个样品
- 环保验证：FDA/REACH/SGS/ISO-10993（医疗+食品包装配方须做）
- 测试条件：温度/湿度/老化时间（70℃ × 7d 热老化、-10℃ × 24h 低温）

## 样品管理（SMP-）
- SMP-2026-002：FORM-CUS-002 医疗配方样品，关联 formula_no + batch_no
- 样品号 SMP- 与实验号 EXP- 不同码空间：SMP- 是样品实体、EXP- 是测试过程
- 调 listTestSchemes(formula_no='FORM-CUS-002') 查测试方案，勿把 SMP- 当 TS- 传
""",
            },
        ],
    },
    # ── 3. 销售知识库（dept sales） ──
    {
        "name": "starhma-sales-kb",
        "scope_type": "department",
        "dept_slug": "sales", "team_slug": None,
        "description": "各系列热熔胶参数、适用行业/基材、智能询盘、报价与样品流程、竞品对比、环保认证，供销售 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "各系列热熔胶参数.md",
                "title": "FORM-STD- 与 FORM-CUS- 系列参数对照",
                "content": """# 各系列热熔胶参数

## 标准品系列（FORM-STD-）
- FORM-STD-001：EVA 基高速包装热熔胶
  - 软化点 95℃、粘度 8500mPa·s、开放时间 4s、剥离 6N、耐温 80℃
  - 用途：食品日化包装自动装箱、纸盒封箱
- FORM-STD-002：APAO 基高温热熔胶
  - 软化点 145℃、粘度 12000mPa·s、耐温 120℃、剥离 8N
  - 用途：汽车内饰件粘接、空气滤芯、家居封边
- FORM-STD-003：SIS 基热熔压敏胶
  - 软化点 85℃、粘度 6000mPa·s、初粘 12#、剥离 18N
  - 用途：粘扣带、快递袋封口、家居卫材

## 定制配方系列（FORM-CUS-）
- FORM-CUS-001：鞋材箱包低温热熔胶（耐 -10℃、开放 7s、剥离 10N）
- FORM-CUS-002：医疗用品低温热熔胶（施胶 130℃、剥离 14N、FDA+ISO-10993）
- FORM-CUS-003：物流快递袋压敏胶（初粘 15#、低温持粘）
- 调 FRM listFormulas 系列参数对照；勿把 FORM- 当 M-FG- 传 ERP
""",
            },
            {
                "source": "适用行业与基材对照.md",
                "title": "七大下游行业、基材与推荐配方",
                "content": """# 适用行业与基材对照

## 行业 → 推荐配方
- 汽车内饰：FORM-STD-002（APAO 耐温 120℃），基材 EVA 泡棉/皮革
- 医疗用品：FORM-CUS-002（FDA+ISO-10993），基材无纺布/PE 膜
- 食品日化包装：FORM-STD-001（FDA 食品级），基材纸盒/铝箔
- 物流快递袋：FORM-CUS-003 + FORM-STD-003（低温压敏），基材 PE/PP 膜
- 鞋材箱包：FORM-CUS-001（耐低温），基材皮革/EVA 泡棉
- 粘扣带：FORM-STD-003（压敏初粘 12#），基材尼龙/涤纶
- 家居卫材：FORM-STD-002 + FORM-STD-003，基材无纺布/棉布

## 基材 → 配方选择规则
- 极性基材（PE 膜/铝箔）：EVA/APAO 基（FORM-STD-001/002）
- 非极性基材（PP 膜）：SIS 压敏（FORM-STD-003）
- 多孔基材（无纺布/纸）：开放时间 4-7s 适中，避免渗透
- 勿杜撰适用行业；复杂工况须提交 INQ- 询盘由 FRM recommendFormula 定制
""",
            },
            {
                "source": "智能询盘流程.md",
                "title": "INQ- 询盘解析、工况匹配与配方推荐",
                "content": """# 智能询盘流程

## 询盘（INQ-）
- INQ-002：医疗用品客户询盘，基材无纺布/PE 膜、施胶 130℃、开放 6s、剥离 14N、FDA+ISO-10993、成本 40 元/kg
- 询盘字段：询盘号 INQ- / 客户 CLI- / 行业 / 基材 / 工况（温度/开放时间/剥离力）/ 环保标准 / 成本上限

## 智能询盘流程
- 解析询盘工况 → 匹配历史配方（FORM-STD- / FORM-CUS-）
- 例：INQ-002 匹配 FORM-CUS-002（医疗低温 + FDA+ISO-10993）
- 调 FRM recommendFormula(industry='医疗', substrate='无纺布/PE 膜', temp=130,
  open_time=6, peel=14, env_std='FDA+ISO-10993', cost=40) 重算推荐
- 输出：推荐配方 FORM-CUS-002 + 初始配比 + 预估性能 + 报价 + 样品 SMP-2026-002

## no-guessing
- INQ- 是询盘、HMAQT- 是报价、SMP- 是样品、CLI- 是客户，不同码空间勿互传
- 客户未明确工况字段时勿杜撰，须反问客户补全
- 调 CRM listOpportunities(opportunity_no='INQ-002') 查询盘，勿把 INQ- 当 CLI- 传
""",
            },
            {
                "source": "报价与样品流程.md",
                "title": "HMAQT- 报价、SMP- 样品与合同转单",
                "content": """# 报价与样品流程

## 报价（HMAQT-）
- HMAQT-2026-002：FORM-CUS-002 医疗配方报价，单价 38 元/kg，最小起订 500kg
- 报价字段：报价号 HMAQT- / 询盘号 INQ- / 客户 CLI- / 配方 FORM- / 单价 / 起订量 / 交期 / 付款条件
- 报价规则：标准品按市场价 ±10%；定制配方按成本+毛利 25-35%
- 环保认证加价：FDA+ISO-10993 +5 元/kg、REACH+SGS +3 元/kg

## 样品（SMP-）
- SMP-2026-002：FORM-CUS-002 医疗配方样品 2kg，关联 formula_no + 询盘 INQ-
- 样品流程：客户询盘 → 寄样 SMP- → 客户验证 → 转正式订单
- 样品批次与正式批次均挂 BAT-，可追溯

## 合同转单
- 客户确认样品后转合同 CT-HMA-（CRM 合同），按 invoice_no 关联回款 INV-
- 勿把 HMAQT- 当 CT-HMA- 传 CRM、勿把 SMP- 当 M-FG- 传 ERP
- 调 CRM listQuotations(quotation_no='HMAQT-2026-002') 查报价
""",
            },
            {
                "source": "竞品对比.md",
                "title": "国产/进口竞品参数与差异化卖点",
                "content": """# 竞品对比

## 竞品格局
- 进口：汉高 Technomelt（包装胶龙头）、富乐 Hysol（医疗胶）、3M（压敏胶）
- 国产：嘉宝长兴、上海天洋、东莞成铭

## 参数对比（医疗低温热熔胶）
- 星途 FORM-CUS-002：施胶 130℃、剥离 14N、FDA+ISO-10993、成本 38 元/kg
- 汉高 Technomelt 6205：施胶 140℃、剥离 13N、FDA、成本 52 元/kg
- 富乐 Hysol 7255：施胶 135℃、剥离 15N、FDA+ISO-10993、成本 55 元/kg

## 差异化卖点
- 星途：低温施胶（节能 15%）、成本较进口低 25-30%、本地化交付快
- 风险点：进口品牌在医疗资质历史更久，复杂工况客户仍倾向进口
- 销售话术：先打物流/包装标准品切入，再做医疗定制升级；勿贬低竞品资质
""",
            },
            {
                "source": "环保认证与法规.md",
                "title": "FDA/REACH/SGS/ISO-10993 认证要求",
                "content": """# 环保认证与法规

## 认证体系
- FDA 21 CFR 175.105：食品级粘合剂（间接接触），FORM-STD-001/FORM-CUS-002 食品+医疗配方须做
- REACH SVHC：欧盟高度关注物质，出口欧盟客户必查（FORM-STD-002/003 已通过）
- SGS RoHS：电子电器有害物质限值，汽车内饰配方须做
- ISO-10993：医疗器械生物相容性（细胞毒性/致敏/刺激），医疗配方 FORM-CUS-002 必做

## 认证与配方绑定
- FORM-CUS-002 医疗配方：FDA + ISO-10993 + REACH 三证齐全
- FORM-STD-001 食品包装胶：FDA 21 CFR 175.105
- FORM-STD-002 汽车内饰胶：SGS RoHS
- 环保证书号挂配方 formula_no；客户询盘 env_std 字段须对照达标

## 销售规则
- 客户要求环保标准未在配方卡列出时，勿杜撰达标，须走样品复测流程
- 环保认证有效期 3 年，临期须复检；过期认证不得对外宣传
- 调 FRM getFormula(formula_no='FORM-CUS-002') 查认证清单，勿凭记忆答复
""",
            },
            {
                "source": "销售跨系统数据获取规则.md",
                "title": "CRM 询盘/报价/订单 + FRM 配方 + ERP 物料 联动",
                "content": """# 销售跨系统数据获取规则

## 技能 starhma-sales-crm-frm-erp-query 联动
- CRM：listCustomers/getCustomer/listOpportunities/getOpportunity/listQuotations/
  getQuotation/listSalesOrders/listFollowUps（客户/询盘/报价/订单/跟进）
- FRM：recommendFormula/getFormula/listFormulas（配方推荐/查询）
- ERP：listMaterials（成品胶 M-FG- 单价/库存）

## 关键 no-guessing
- CRM 客户 CLI-、询盘 INQ-、报价 HMAQT-、合同 CT-HMA-、回款 HMAAR-、发票 INV- 各自独立编号
- FRM 配方 FORM-、组分 ING-；ERP 成品 M-FG-、物料 M-RES- 等；prefix 不可互传
- 跨系统关联：合同 CT-HMA-001 关联客户 CLI-001；发票 INV202607001 关联 ERP 凭证 BV-HMA-2026-0701

## 销售流程闭环
- 询盘 INQ-002 → 报价 HMAQT-2026-002 → 样品 SMP-2026-002 → 合同 CT-HMA-002 → 回款 HMAAR-
- 勿把询盘号当合同号传 CRM；调 listOpportunities 查询盘、listSalesOrders 查合同
""",
            },
        ],
    },
    # ── 4. 排产知识库（dept mfg） ──
    {
        "name": "starhma-mfg-schedule-kb",
        "scope_type": "department",
        "dept_slug": "mfg", "team_slug": None,
        "description": "多品种柔性排产规则、产线产能、订单冲突识别、工艺参数区间、换线成本，供排产 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "多品种柔性排产规则.md",
                "title": "optimizeProductionSchedule 入参与排产建议输出",
                "content": """# 多品种柔性排产规则

## optimizeProductionSchedule 入参
- 工单清单（WO + 交期 + 批次 BAT- + 配方 FORM-）
- 产线负荷（LINE-AUTO-01/02 + LINE-03 当前排程）
- 换线成本（换配方/换颜色/换基材）

## 排产规则
- 优先级：紧急订单（CRM 合同 CT-HMA- 交期 <7d）> 标准品（FORM-STD-）> 定制（FORM-CUS-）
- 同配方/同颜色组批：减少换线次数
- 产能匹配：标准品 8t/d 全自动线、定制 4.5t/d 半自动线
- 换线规则：EVA→APAO 须清洗反应釜（2h）、APAO→SIS 须清洗造粒机（1.5h）

## 排产建议输出
- 输出 PSCH- 排产建议：工单排序 + 产线分配 + 开工/完工时间 + 换线次数
- 冲突订单列表：交期无法满足的工单，须与销售协商调整交期
- 调 PCM optimizeProductionSchedule(work_order_list=[...]) 返 schedule + conflicts
- 勿杜撰产能；超出负荷的订单须进冲突列表，勿给虚假满足交期结论
""",
            },
            {
                "source": "产线产能与设备配置.md",
                "title": "LINE-AUTO-01/02 全自动 + LINE-03/04 半自动产能",
                "content": """# 产线产能与设备配置

## 产线（LINE-）
- LINE-AUTO-01：全自动 EVA/APAO 产线，产能 8t/d，配反应釜 EQ-RX-01 + 造粒机 EQ-GRN-01
- LINE-AUTO-02：全自动 SIS 压敏胶产线，产能 8t/d，配反应釜 EQ-RX-02 + 造粒机 EQ-GRN-02
- LINE-03：半自动 EVA/APAO 产线，产能 4.5t/d，配反应釜 EQ-RX-03
- LINE-04：半自动小批量定制产线，产能 3t/d，用于 FORM-CUS- 定制配方

## 产能配置规则
- 全自动线优先排标准品（FORM-STD-001/002/003），大批量订单
- 半自动线优先排定制配方（FORM-CUS-001/002/003），小批量多品种
- 设备 EQ-RX- 反应釜产能瓶颈 8t/d（1000L × 8 批 × 1t/批）
- 调 PCM listEquipment(line='LINE-AUTO-01') 查产线设备；勿把 LINE- 当 EQ- 传

## MES 关联
- MES 工单 WO 关联产线 LINE- 与批次 BAT-；PCM 排产建议 PSCH- → MES WO 排程
- LINE- 与 EQ- 不同码空间：LINE-AUTO-01 是产线、EQ-RX-01 是设备，勿互传
""",
            },
            {
                "source": "订单冲突识别.md",
                "title": "交期冲突、产能超载与换线冲突识别",
                "content": """# 订单冲突识别

## 冲突类别
- 交期冲突：CRM 合同 CT-HMA- 交期 < 当前排程最早可开工日
- 产能超载：当日排程工单总量 > 产线产能（8t/d 或 4.5t/d）
- 换线冲突：相邻工单配方/颜色/基材不同，换线时间挤占产能

## 识别规则
- optimizeProductionSchedule 返 conflicts 列表，每条含 conflict_type + work_order_no + reason
- 交期冲突：建议与销售协商改交期（关联 CRM 合同 CT-HMA-）
- 产能超载：建议转半自动线 LINE-03/04 或外协
- 换线冲突：建议重排顺序，同配方组批

## 示例
- WO202607001..005 五张工单交期均在 7/10-7/15
- LINE-AUTO-01/02 负荷 16t vs 排程 20t → 4t 超载
- WO202607001 (FORM-CUS-002 医疗) 与 WO202607002 (FORM-CUS-001 鞋材) 换线须 2h
- 输出冲突：4t 转半自动线 LINE-03；WO202607001/002 重新组批减少换线
""",
            },
            {
                "source": "工艺参数区间.md",
                "title": "PP-STIR-/PP-REACT-/PP-COOL- 工艺参数区间与达标",
                "content": """# 工艺参数区间

## 工艺参数（PP-）
- PP-STIR- 搅拌段：PP-STIR-001 搅拌速度 60-120 rpm、PP-STIR-002 搅拌时间 30-90 min
- PP-REACT- 反应段：PP-REACT-001 反应温度 160-180℃、PP-REACT-002 反应时间 2-4h
- PP-COOL- 冷却段：PP-COOL-001 冷却温度 80-100℃、PP-COOL-002 冷却速率 1-3℃/min

## 工艺参数区间
- EVA 基（FORM-STD-001/CUS-002）：反应 170℃ × 2.5h，搅拌 90 rpm × 60 min
- APAO 基（FORM-STD-002）：反应 180℃ × 3h，搅拌 80 rpm × 75 min
- SIS 基（FORM-STD-003/CUS-003）：反应 160℃ × 2h，搅拌 100 rpm × 45 min

## 关联规则
- PP- 挂 formula_no=FORM- + line=LINE- + equipment_no=EQ-RX-
- 调 PCM recommendProcessParams(formula_no='FORM-CUS-002', line='LINE-AUTO-01')
  返 recommended_params + safety_range
- 偏离区间 ±5℃/±10 rpm 须预警；勿把 PP- 当 FORM- 传 FRM
""",
            },
            {
                "source": "换线成本与组批策略.md",
                "title": "换线时间/清洗成本与组批规则",
                "content": """# 换线成本与组批策略

## 换线时间
- 同配方换色：30 min（清洗造粒机 + 模头）
- EVA ↔ APAO 换基体：2h（清洗反应釜 EQ-RX- + 管路）
- APAO ↔ SIS 换基体：1.5h（清洗造粒机 EQ-GRN-）
- 同基体换配方（FORM-STD-001 → FORM-STD-003）：1h

## 清洗成本
- 反应釜清洗：原料 50kg × 35 元/kg = 1750 元 + 人工 2h × 80 元/h = 160 元
- 造粒机清洗：原料 30kg × 35 元/kg = 1050 元 + 人工 1.5h × 80 元/h = 120 元

## 组批策略
- 同基体同颜色组批：减少换线次数
- 紧急订单穿插：紧急 FORM-CUS-002 医疗订单可插入排程，但须计换线成本
- 排产优化目标：min Σ 换线成本 + max Σ 准时交付率
- 调 PCM optimizeProductionSchedule 自动组批，勿手动杜撰组批方案
""",
            },
            {
                "source": "排产跨系统闭环.md",
                "title": "PCM 排产 PSCH- ↔ MES 工单 WO ↔ ERP 成本 PC-HMA-",
                "content": """# 排产跨系统闭环

## 闭环：PCM 排产 → MES 工单
- PCM 排产建议 PSCH- → MES 工单 WO（按 work_order_no 关联）
- 排产建议字段：psch_no + work_order_list + line_assignment + start/end_time
- 调 MES listWorkOrders(work_order_no='WO202607001') 查工单状态

## 闭环：MES 批次 → ERP 成本
- MES 批次 BAT-2026-0702（工单 WO202607002）→ ERP 生产成本 PC-HMA-202607002
- PC-HMA-.heat_no 承载 BAT- 批次号；PC-HMA-.work_order_no 承载 CRM 合同 CT-HMA-
- 调 ERP listProductionCosts(heat_no='BAT-2026-0702') 查批次成本

## no-guessing
- PSCH-（PCM 排产建议）、WO（MES 工单）、BAT-（MES 批次）、PC-HMA-（ERP 成本）各自独立编号
- CT-HMA-（CRM 合同）→ PC-HMA-.work_order_no 关联，勿把 CT-HMA- 当 WO 传 MES
- LINE-（产线）、EQ-（设备）不同码空间勿互传
""",
            },
        ],
    },
    # ── 5. 设备维护知识库（dept mfg） ──
    {
        "name": "starhma-eqp-maintenance-kb",
        "scope_type": "department",
        "dept_slug": "mfg", "team_slug": None,
        "description": "反应釜/电机/造粒机预测性维护规则、保养周期、故障案例，供设备运维 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "反应釜维护规则.md",
                "title": "EQ-RX- 反应釜预测性维护与保养",
                "content": """# 反应釜维护规则

## 反应釜（EQ-RX-）
- EQ-RX-01：LINE-AUTO-01 全自动线反应釜 1000L
- EQ-RX-02：LINE-AUTO-02 全自动线反应釜 1000L
- EQ-RX-03：LINE-03 半自动线反应釜 500L
- 监控指标：搅拌电流（电机 EQ-MTR-）、夹套温度、釜内温度、振动

## 预测性维护
- 调 PCM predictEquipmentFault(equipment_no='EQ-RX-01') 返 health_score + risk_level + recommended_action
- 健康分维度：振动 0-10、温升 0-10、电流稳定性 0-10、密封性 0-10
- 健康分 <7 黄牌预警、<5 红牌停机
- 故障预测号 PM-，关联 equipment_no + line=LINE-

## 保养周期
- 日常：班前班后点检（搅拌电流、油位、密封）
- 月度：减速机换油、轴封检查
- 年度：釜体内壁测厚、搅拌桨动平衡
- 保养记录挂 PM- 编号；勿把 PM- 当 EQ- 传
""",
            },
            {
                "source": "电机维护规则.md",
                "title": "EQ-MTR- 电机振动/温升监控与健康分",
                "content": """# 电机维护规则

## 电机（EQ-MTR-）
- EQ-MTR-01：EQ-RX-01 反应釜搅拌电机 22kW
- EQ-MTR-02：EQ-RX-02 反应釜搅拌电机 22kW（EQP-01 场景示例设备）
- EQ-MTR-03：EQ-GRN-01 造粒机主电机 15kW
- 监控指标：振动（mm/s）、温升（℃）、电流（A）、转速（rpm）

## 振动/温升规则
- 振动标准：<2.8 mm/s 正常、2.8-4.5 预警、>4.5 停机
- 温升标准：<60K 正常、60-80K 预警、>80K 停机
- 电流稳定性：偏差 ±5% 正常、>±10% 预警（疑似过载/缺相）

## 健康分算法
- health_score = 0.4×振动分 + 0.3×温升分 + 0.3×电流分
- EQ-MTR-02 健康分 6.2（振动 3.2 偏高）→ 黄牌预警，建议保养
- 关联产线 LINE-AUTO-02 与工艺参数 PP-REACT-002，停机前先转产
- 调 PCM getEquipmentRunData(equipment_no='EQ-MTR-02') 查运行数据
""",
            },
            {
                "source": "造粒机维护规则.md",
                "title": "EQ-GRN- 造粒机模头/刀具保养",
                "content": """# 造粒机维护规则

## 造粒机（EQ-GRN-）
- EQ-GRN-01：LINE-AUTO-01 全自动线造粒机
- EQ-GRN-02：LINE-AUTO-02 全自动线造粒机
- 监控指标：模头温度、刀具磨损、切粒速度、颗粒均匀度

## 预测性维护
- 刀具磨损：>0.3mm 须更换（影响颗粒均匀度）
- 模头温度稳定性：偏差 ±3℃ 正常、>±5℃ 预警
- 颗粒均匀度：CV<5% 正常、>10% 预警（影响下游熔融均匀性）

## 保养周期
- 日常：刀具目视检查、模头温度记录
- 周度：刀具磨损测量、模头清理
- 月度：刀具更换、模头抛光
- 故障案例：EQ-GRN-01 刀具磨损 0.4mm 导致颗粒不均，影响下游 FORM-STD-001 熔融
- 关联设备 EQ-GRN-01 + line=LINE-AUTO-01 + 工艺 PP-COOL-001
""",
            },
            {
                "source": "预测性维护流程.md",
                "title": "predictEquipmentFault 风险等级与保养提醒",
                "content": """# 预测性维护流程

## predictEquipmentFault 入参与输出
- 输入 equipment_no（EQ-RX-/EQ-MTR-/EQ-GRN-）
- 输出 health_score + risk_level（高/中/低）+ predicted_fault + recommended_action + lead_time

## 风险等级
- 高：health_score <5，须立即停机保养
- 中：health_score 5-7，建议 7 天内保养
- 低：health_score >7，按周期保养

## 保养提醒
- risk_level=高 → 工单立即生成，停机转产
- risk_level=中 → 工单 7 天内执行，提前备件
- risk_level=低 → 按月度/年度周期保养

## EQP-01 场景示例
- EQ-MTR-02 振动 3.2mm/s（预警）、温升 65K、电流稳定
- health_score 6.2 → risk_level=中，建议 7 天内保养轴承
- 关联产线 LINE-AUTO-02 + 工艺参数 PP-REACT-002（反应温度 175℃）
- 调 PCM predictEquipmentFault(equipment_no='EQ-MTR-02') 复算，勿凭经验判断
""",
            },
            {
                "source": "保养周期与工单.md",
                "title": "日常/月度/年度保养周期与工单闭环",
                "content": """# 保养周期与工单

## 保养周期
- 反应釜 EQ-RX-：日点检/月换油/年测厚
- 电机 EQ-MTR-：日点检/季振动/年大修
- 造粒机 EQ-GRN-：日检查/周刀具/月更换

## 保养工单（PM-）
- PM-2026-031：EQ-MTR-02 电机轴承保养工单
- 工单字段：工单号 PM- / equipment_no EQ- / 保养类型 / 计划时间 / 执行人 / 状态
- 保养闭环：计划 → 执行 → 验收 → 健康分复测

## 关联与追溯
- 保养工单 PM- 关联 equipment_no + line=LINE-
- 故障停机须关联 PM- 与 PCM 故障预测记录
- 调 PCM listEquipment(line='LINE-AUTO-02') 查产线设备清单
- 勿把 PM- 当 EQ- 传 PCM；PM- 是工单、EQ- 是设备实体
""",
            },
            {
                "source": "故障案例库.md",
                "title": "设备故障案例与根因复盘",
                "content": """# 故障案例库

## 反应釜故障
- EQ-RX-03 釜壁结焦：反应温度超 180℃ 持续 4h → 清釜 8h，批次 BAT-2026-0704 报废
- EQ-RX-01 搅拌轴封泄漏：密封圈老化 → 换密封 4h，影响 LINE-AUTO-01 产线 8t 产能

## 电机故障
- EQ-MTR-02 轴承磨损：振动 3.2mm/s 持续 15 天 → 停机换轴承 6h
- EQ-MTR-03 缺相过载：电流偏差 12% → 急停换接触器 1h

## 造粒机故障
- EQ-GRN-01 刀具磨损：颗粒 CV 12% → 换刀具 2h，影响 FORM-STD-001 熔融均匀性
- EQ-GRN-02 模头堵塞：模头温度波动 ±7℃ → 拆模头清理 3h

## 根因复盘规则
- 故障须关联 equipment_no + line + 工艺参数 PP- + 关联批次 BAT-
- 健康分历史趋势复盘：定位劣化拐点，优化保养周期
- 调 PCM getEquipment(equipment_no='EQ-MTR-02') 查设备档案，勿杜撰故障历史
""",
            },
        ],
    },
    # ── 6. 库存供应链知识库（dept scm） ──
    {
        "name": "starhma-scm-inventory-kb",
        "scope_type": "department",
        "dept_slug": "scm", "team_slug": None,
        "description": "原料/成品安全库存、低库存预警、采购补货、原料价格行情、呆滞物料，供供应链 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "原料安全库存规则.md",
                "title": "M-RES-/M-TK-/M-WAX-/M-AO- 安全库存与预警",
                "content": """# 原料安全库存规则

## 原料物料（M-）
- M-RES-001 EVA 树脂：安全库存 20t，日均消耗 2t，备货周期 7d
- M-RES-002 APAO 树脂：安全库存 15t，日均消耗 1.5t
- M-RES-003 SIS 树脂：安全库存 12t，日均消耗 1.2t
- M-TK-002 C5 石油树脂：安全库存 10t，日均消耗 1t
- M-WAX-001 石蜡：安全库存 5t，日均消耗 0.5t
- M-AO-001 BHT 抗氧剂：安全库存 0.5t，日均消耗 0.05t

## 安全库存算法
- 安全库存 = 日均消耗 × 备货周期 × 安全系数 1.5
- 低库存预警：< 安全库存 1.2 倍 → 黄色预警
- 紧急预警：< 安全库存 0.8 倍 → 红色，须立即补货

## no-guessing
- 原料 M-RES-/M-TK-/M-WAX-/M-AO- 与组分 ING-RES-/ING-TK-/ING-WAX-/ING-AO- 不同码空间
- 调 ERP listMaterials(material_code='M-RES-001') 查物料库存/单价，勿用 ING- 查 ERP
- 安全库存按物料码 M- 维护，勿按组分 ING- 维护
""",
            },
            {
                "source": "成品安全库存规则.md",
                "title": "M-FG- 成品胶安全库存与产销平衡",
                "content": """# 成品安全库存规则

## 成品胶（M-FG-）
- M-FG-001 EVA 包装胶（FORM-STD-001）：安全库存 8t
- M-FG-002 APAO 高温胶（FORM-STD-002）：安全库存 6t
- M-FG-003 SIS 压敏胶（FORM-STD-003）：安全库存 5t

## 产销平衡
- 安全库存 = 月销量 × 备货周期 0.3 月 × 安全系数 1.2
- 库存预警联动销售预测：CRM listSalesOrders 查未来 30d 订单
- 成品库存 > 安全库存 2 倍 → 库存积压预警（呆滞风险）

## 关联
- M-FG- 关联标准品 FORM-STD-（按 product_code 1:1）
- 定制配方 FORM-CUS- 不建立成品库存（按订单生产，零库存）
- 调 ERP listInventory(material_code='M-FG-002') 查成品库存
- 勿把 M-FG- 当 FORM- 传 FRM、勿把 FORM-STD-001 当 M-FG-001 传 ERP
""",
            },
            {
                "source": "低库存预警流程.md",
                "title": "库存预警、补货触发与联动销售预测",
                "content": """# 低库存预警流程

## 预警规则
- 黄色预警：库存 < 安全库存 × 1.2，建议补货
- 红色预警：库存 < 安全库存 × 0.8，立即补货
- 库存差异：ERP listInventory 实时库存 vs 安全库存阈值

## 预警示例（SCM-01 场景）
- M-RES-001 库存 16t < 安全 20t × 0.8 = 16t → 红色，立即补货
- M-TK-002 库存 11t < 安全 10t × 1.2 = 12t → 黄色，建议补货
- M-AO-001 库存 0.4t < 安全 0.5t × 0.8 = 0.4t → 红色，立即补货
- M-FG-002 成品库存 4t < 安全 6t × 0.8 = 4.8t → 红色，建议转产

## 联动销售预测
- 调 CRM listSalesOrders 查未来 30d 订单，预估成品消耗
- 调 ERP listStockMovements 查近期出库趋势
- 输出：预警清单 + 补货建议数量 + 优先级
- 勿杜撰补货数量；须按日均消耗 × 备货周期计算
""",
            },
            {
                "source": "采购补货流程.md",
                "title": "POHMA 采购单生成与供应商选择",
                "content": """# 采购补货流程

## 采购单（POHMA）
- POHMA：ERP 采购单编号前缀（HMA = 热熔胶 hot-melt-adhesive）
- 字段：采购单号 POHMA / 供应商 S-HMA- / 物料 M- / 数量 / 单价 / 交期 / 付款条件

## 补货流程
- 库存红色预警 → 生成采购申请 → 选供应商 → 生成采购单 POHMA
- 供应商选择：优先历史供应商（S-HMA-001 价格优、S-HMA-002 质量稳）
- 补货数量 = 安全库存 × 2 − 当前库存（补到安全库存 2 倍）

## 关联
- 采购单 POHMA 关联物料 M-RES- / M-TK- 等，勿关联组分 ING-
- 采购入库 → ERP listStockMovements 记录入库流水
- 应付 HMAAP 关联采购单 POHMA（按 purchase_order_no）
- 调 ERP listPurchaseOrders 查采购单，勿把 POHMA 当 HMAAP 传
""",
            },
            {
                "source": "原料价格行情.md",
                "title": "M- 原料价格波动与采购策略",
                "content": """# 原料价格行情

## 价格波动
- M-RES-001 EVA 树脂：12-18 元/kg，受油价影响波动 ±20%
- M-RES-002 APAO 树脂：18-25 元/kg
- M-RES-003 SIS 树脂：20-28 元/kg
- M-TK-002 C5 石油树脂：9-14 元/kg
- M-WAX-001 石蜡：7-10 元/kg
- M-AO-001 BHT：35-45 元/kg

## 采购策略
- 价格低位 + 库存 < 安全库存 1.5 倍：批量补货到安全库存 2 倍
- 价格高位 + 库存充足：按需补货，不批量囤货
- 季节性波动：油价上涨前（Q4）批量囤 EVA/APAO 树脂

## 价格行情来源
- ERP listMaterials 查物料 price 字段（最近采购单价）
- 供应商报价：S-HMA-001/002 历史报价趋势
- 勿杜撰价格预测；价格行情须标注采集时间与来源
- 影响成品报价：M-RES- 价格上涨 → FORM-STD- 报价上调
""",
            },
            {
                "source": "呆滞物料管理.md",
                "title": "呆滞物料识别、降价处理与报废",
                "content": """# 呆滞物料管理

## 呆滞识别
- 库存 > 安全库存 × 3 且 90 天未动 → 呆滞物料
- 原料保质期：EVA/APAO 6 个月、SIS 12 个月、抗氧剂 24 个月
- 临期识别：保质期剩 1 个月 → 黄色，剩 15 天 → 红色

## 处理规则
- 呆滞原料：降价转售给低端客户、或报废
- 临期原料：优先消耗（FIFO），调整排产用临期批次
- 呆滞成品 M-FG-：降价促销（关联 sales-rep）

## 案例
- M-RES-003 SIS 库存 36t（安全 12t × 3）且 95 天未动 → 呆滞
- 处理：降价转售给低端粘扣带客户，回收 60% 成本
- 呆滞记录挂物料 M- + 库存仓 WH-HMA- + 入库批次
- 调 ERP listInventory + listStockMovements 识别呆滞，勿凭经验判断
""",
            },
            {
                "source": "库存跨系统闭环.md",
                "title": "ERP 库存 ↔ CRM 销售订单 ↔ MES 工单 联动",
                "content": """# 库存跨系统闭环

## 技能 starhma-scm-erp-crm-query 联动
- ERP：listInventory/listMaterials/listPurchaseOrders/listStockMovements/listWarehouses/listSuppliers
- CRM：listSalesOrders（销售订单驱动补货）

## 闭环：销售订单 → 库存消耗 → 采购补货
- CRM 销售订单 CT-HMA- → ERP 成品 M-FG- 库存出库 → 库存预警 → 采购 POHMA
- 成品 M-FG- 出库挂销售订单号；原料 M- 入库挂采购单号 POHMA

## 仓库管理
- WH-HMA-01 原料仓（M-RES-/M-TK-/M-WAX-/M-AO-）
- WH-HMA-02 成品仓（M-FG-001/002/003）
- WH-HMA-03 呆滞仓（隔离呆滞物料）

## no-guessing
- 仓 WH-HMA-、物料 M-、采购单 POHMA、应付 HMAAP、销售订单 CT-HMA- 各自独立编号
- 调 ERP listWarehouses 查仓库、listInventory 查库存，勿把 WH- 当 M- 传
- 物料 M-RES- 与组分 ING-RES- 不同码空间，prefix 转换勿互传
""",
            },
        ],
    },
    # ── 7. 售后故障知识库（dept qas） ──
    {
        "name": "starhma-qas-aftersales-kb",
        "scope_type": "department",
        "dept_slug": "qas", "team_slug": None,
        "description": "开胶/拉丝/堵枪/低温失效故障案例、诊断流程、根因分析、检测报告，供售后诊断 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "开胶故障案例库.md",
                "title": "开胶故障 FC- 案例、根因与排查方案",
                "content": """# 开胶故障案例库

## 开胶故障（FC-）
- FC-2025-008：FORM-CUS-001 鞋材配方开胶，根因 ING-WAX-001 石蜡过量 + 低温 -5℃ 脆化
- FC-2025-012：FORM-STD-001 包装胶封箱开胶，根因施胶温度偏低 140℃（应 170℃）
- FC-2025-019：FORM-CUS-002 医疗配方无纺布开胶，根因基材表面张力低未处理

## 故障字段
- 案例号 FC- / 客诉号 CC- / 客户 CLI- / 配方 FORM- / 批次 BAT- / 故障现象 / 根因 / 解决方案

## 排查方案
- 现场采样 → 检测剥离力 EXP-TEN- → 对比留样性能
- 基材表面张力测试（必做，<38 dyn/cm 须电晕处理）
- 配方组分复检（关联失效记录 FR-）
- 勿杜撰根因；未命中案例库的故障须送样实验室复测
- 调 QAS listFailureCases 查案例，勿把 FC- 当 CC- 传
""",
            },
            {
                "source": "拉丝故障案例库.md",
                "title": "拉丝故障根因与配方/工艺调整",
                "content": """# 拉丝故障案例库

## 拉丝故障
- FC-2025-024：FORM-STD-001 高速包装拉丝，根因施胶温度过高 185℃（应 170℃）致粘度过低
- FC-2025-029：FORM-STD-003 压敏胶拉丝，根因 ING-WAX-001 用量偏低 + 开放时间过长

## 根因
- 温度过高：粘度过低 → 拉丝（降温度 5-10℃）
- 蜡用量偏低：粘度偏高、开放时间过长 → 拉丝（增蜡 1-2%）
- 拉伸速度过快：设备速度与胶断裂不匹配

## 调整方案
- 工艺调整：调 PP-REACT-002 反应温度 +5℃ 提高软化点
- 配方调整：ING-WAX-001 +1.5% 提升断裂伸长
- 客户端调整：喷枪温度回调、气压调整

## 关联
- 故障挂 FC- + CC- + FORM- + BAT- + 工艺 PP-
- 调 QAS diagnoseAfterSalesFault 现象='拉丝' 匹配案例，勿凭经验下结论
""",
            },
            {
                "source": "堵枪故障案例库.md",
                "title": "堵枪故障根因与设备/工艺排查",
                "content": """# 堵枪故障案例库

## 堵枪故障
- FC-2025-031：FORM-STD-001 包装胶堵枪，根因胶中杂质（颗粒不均）+ 喷枪滤网未清
- FC-2025-036：FORM-STD-002 高温胶堵枪，根因保温段温度不足致胶凝固

## 根因
- 颗粒不均：造粒机 EQ-GRN- 刀具磨损（关联 EQP-01 维护）
- 保温不足：喷枪保温段温度 < 软化点（FORM-STD-002 须保温 >145℃）
- 杂质：滤网失效、原料杂质（关联来料检测 QR-IN-）

## 排查
- 拆枪检查：滤网、模头、保温段温度
- 颗粒复检：CV >10% 异常（关联造粒机 EQ-GRN- 维护）
- 来料复检：QR-IN- 来料检测报告
- 调整：换滤网、提保温段温度 5-10℃、清枪

## 关联
- 故障挂 FC- + CC- + FORM- + BAT- + 设备 EQ-GRN- + 来料 QR-IN-
- 勿把 QR-IN- 当 QR-FG- 传；来料/成品检测不同码空间
""",
            },
            {
                "source": "低温失效案例库.md",
                "title": "低温脆断/剥离失效根因与配方调整",
                "content": """# 低温失效案例库

## 低温失效故障
- FC-2025-042：FORM-CUS-001 鞋材配方 -15℃ 脆断，根因 ING-WAX-001 石蜡过量
- FC-2025-045：FORM-CUS-002 医疗配方 -10℃ 剥离 8N（应 14N），根因 ING-RES-003 SIS 用量偏低

## 根因
- 石蜡过量：低温脆化（换 ING-WAX-002 微晶蜡增韧）
- SIS 用量偏低：压敏性不足（增 ING-RES-003 +3%）
- 树脂选型不当：EVA 低温性差（医疗低温须 SIS/APAO）

## 调整方案
- 配方升级：FORM-CUS-002 v2，ING-RES-003 +3%、ING-WAX-001 → ING-WAX-002
- 复测：EXP-ADH-002 低温持粘 + EXP-TEN-001 低温剥离
- 失效闭环：FR-2025-048 → 配方升级 → 重出 QR-FG- 检测报告

## 关联
- 故障挂 FC- + CC- + FORM- + BAT- + 失效记录 FR- + 实验 EXP-ADH-
- 调 QAS diagnoseAfterSalesFault 现象='低温剥离失效' 匹配案例
""",
            },
            {
                "source": "诊断流程.md",
                "title": "diagnoseAfterSalesFault 现象匹配与方案输出",
                "content": """# 诊断流程

## diagnoseAfterSalesFault 入参与输出
- 输入 complaint_no（CC-）+ 故障现象 + 基材 + 工况
- 输出 matched_cases（FC-）+ root_cause + troubleshooting_steps + formula_adjustment

## 诊断流程
- 现象分类：开胶/拉丝/堵枪/低温失效四类
- 基材/工况匹配：按基材（无纺布/PE 膜/铝箔）+ 工况（温度/湿度）命中历史案例
- 配方关联：故障客户用的配方 FORM- + 批次 BAT-，调 FRM getFormula 追溯组分

## QAS-01 场景示例
- CC-2026-001 开胶故障：医疗客户 CLI-001、FORM-CUS-001 鞋材配方、-5℃ 工况
- 匹配 FC-2025-008（FORM-CUS-001 开胶 + 低温脆化）
- 根因：ING-WAX-001 石蜡过量 + 低温脆化
- 方案：配方升级 ING-WAX-001 → ING-WAX-002，关联 FR-2025-035

## no-guessing
- CC- 客诉、FC- 故障案例、FR- 失效记录各自独立编号
- 调 QAS listCustomerComplaints 查客诉、listFailureCases 查案例
- 勿把 CC- 当 FC- 传、勿把 FC- 当 FR- 传
""",
            },
            {
                "source": "根因分析流程.md",
                "title": "analyzeRootCause 关联配方/批次/工艺三维根因",
                "content": """# 根因分析流程

## analyzeRootCase 入参与输出
- 输入 complaint_no（CC-）或 failure_case_no（FC-）
- 输出 root_cause_analysis + related_formula + related_batch + related_process + recommendations

## 三维根因
- 配方维度：FORM- 组分比例（ING-RES-/ING-TK-/ING-WAX-/ING-AO-）
  - 关联失效记录 FR-（FRM listFailureRecords）
- 批次维度：BAT- 生产批次（MES getWorkOrder）
  - 关联检测报告 QR-FG-（QAS getQualityReport）
- 工艺维度：PP-STIR-/PP-REACT-/PP-COOL- 工艺参数
  - 关联设备运行数据 EQ- + 工艺 PP-

## 根因闭环
- 根因号 RCA-，关联 CC- + FC- + FR- + BAT- + PP-
- 根因 → 配方升级 FORM- v2 → 重产 BAT- → 重测 QR-FG- → 客户复测
- 勿杜撰根因；多维未命中须送样实验室复测，标注 RCA- pending

## 关联
- 调 QAS analyzeRootCase(complaint_no='CC-2026-001')，勿把 CC- 当 RCA- 传
- 根因 RCA- 与故障案例 FC- 不同码空间：RCA- 是分析结论、FC- 是案例实体
""",
            },
            {
                "source": "检测报告管理.md",
                "title": "QR-IN- 来料检测 + QR-FG- 成品检测",
                "content": """# 检测报告管理

## 来料检测（QR-IN-）
- QR-IN-2026-001：M-RES-001 EVA 树脂来料检测，VA% 28%、酸值 0.5mgKOH/g、含水 0.1%
- 字段：报告号 QR-IN- / 物料 M- / 供应商 S-HMA- / 批次 / 检测项 / 结果 / 判定
- 不合格来料须退货，关联采购单 POHMA

## 成品检测（QR-FG-）
- QR-FG-2026-002：BAT-2026-0702 批次 FORM-STD-001 成品检测，软化点 95℃、剥离 6N、FDA 达标
- 字段：报告号 QR-FG- / 批次 BAT- / 配方 FORM- / 检测项 / 结果 / 判定

## 关联与追溯
- QR-FG- 挂 batch_no(BAT-) + formula_no(FORM-)
- 售后故障诊断时调 QR-FG- 复查批次留样性能，追溯配方/工艺根因
- 不良品 NG-2026-001 关联批次 BAT-2026-0702 + 检测 QR-FG-

## no-guessing
- QR-IN- 来料、QR-FG- 成品不同码空间，勿互传
- 调 QAS getQualityReport(quality_report_no='QR-FG-2026-002')，勿把 QR- 当 BAT- 传 MES
""",
            },
        ],
    },
    # ── 8. 经营分析知识库（dept admin） ──
    {
        "name": "starhma-admin-bi-kb",
        "scope_type": "department",
        "dept_slug": "admin", "team_slug": None,
        "description": "跨系统数据汇总规则、应收应付对账、经营简报模板，供经营分析 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "跨系统数据汇总规则.md",
                "title": "ERP/CRM/MES 三系统数据汇总口径",
                "content": """# 跨系统数据汇总规则

## 数据来源
- ERP：营收（销售出库）/采购（POHMA）/库存（M-）/成本（PC-HMA-）/应付（HMAAP）/凭证（BV-HMA-）
- CRM：订单（CT-HMA-）/客户（CLI-）/回款（HMAAR-）/发票（INV-）/争议（DSP-HMA-）
- MES：产能（LINE-）/工单（WO）/批次（BAT-）/不良（DF）

## 汇总口径
- 营收 = CRM 销售订单 CT-HMA- 金额（按月汇总）vs ERP 销售出库 M-FG-（按月）
- 产能 = MES listShiftOutputs 按产线 LINE- + 月汇总（额定 8t/d × 30d = 240t/月）
- 工单 = MES listWorkOrders 按 status 汇总（已排产/生产中/已完工）
- 客户 = CRM listCustomers 按行业汇总（医疗/包装/物流等七大下游）

## no-guessing
- 营收来自 CRM 订单 + ERP 出库双口径，须对账差异
- 产能来自 MES、销售来自 CRM、成本来自 ERP，勿跨系统直传编号
- 调 ERP/CRM/MES 各自 list 接口取数，勿用单系统数据代表全局
""",
            },
            {
                "source": "应收应付对账规则.md",
                "title": "INV↔BV-HMA- 发票凭证对账 + 回款/应付闭环",
                "content": """# 应收应付对账规则

## 应收对账（CRM ↔ ERP）
- CRM 发票 INV- ↔ ERP 凭证 BV-HMA- 按 invoice_no 关联
- INV202607001 ↔ BV-HMA-2026-0701（按 invoice_no 一一对应）
- 应收 = CRM 回款 HMAAR- vs 发票 INV- 金额，差异闭环

## 应付对账（ERP）
- 采购单 POHMA → 应付 HMAAP（按 purchase_order_no 关联）
- 应付 HMAAP vs 凭证 BV-HMA- 付款金额，差异闭环

## 对账差异处理
- 凭证金额(BV-HMA-) vs 回款金额(HMAAR-) vs 应付金额(HMAAP)
- 差异类型：金额不一致（汇率/折扣）/时间差（跨月）/状态不一致（已开票未回款）
- days_overdue >30 → 逾期预警，关联争议 DSP-HMA-

## no-guessing
- INV-（CRM 发票）、BV-HMA-（ERP 凭证）、HMAAR-（CRM 回款）、HMAAP（ERP 应付）各自独立编号
- 调 ERP listVouchers + CRM listReceivables 对账，勿把 INV- 当 BV-HMA- 传
- 对账按 invoice_no 关联，勿用客户号 CLI- 直接对账
""",
            },
            {
                "source": "经营简报模板.md",
                "title": "月度经营简报结构与指标体系",
                "content": """# 经营简报模板

## 简报结构
1. 营收与利润：本月营收（CRM 订单 + ERP 出库）、毛利率（售价 − 成本 PC-HMA-）
2. 产能与工单：MES 产能利用率（实际/额定）、工单完成率、不良率 DF
3. 订单与客户：CRM 新增订单 CT-HMA- 数 + 新增客户 CLI- 数 + 七大下游分布
4. 库存与采购：ERP 原料/成品库存、采购 POHMA 金额、呆滞预警
5. 应收应付：应收 HMAAR- 账龄、应付 HMAAP 账龄、对账差异 INV↔BV-HMA-
6. 风险预警：客户回款逾期、库存呆滞、设备故障、配方失效

## 指标体系
- 营收 YoY/MoM、毛利率、产能利用率、订单交付率、库存周转率、应收账龄、不良率
- 数据口径标注来源系统（ERP/CRM/MES），勿混用

## 示例
- 2026 年 7 月简报：营收 1850 万（CRM 订单 1920 万 + 差异 70 万跨月）、毛利率 28%、产能利用率 87%
- 红色预警：M-RES-001 库存红色、EQ-MTR-02 健康分 6.2、CC-2026-001 开胶客诉
- 勿杜撰数据；每项指标须可追溯到源系统接口
""",
            },
            {
                "source": "营收与成本分析.md",
                "title": "营收口径、生产成本归集与毛利分析",
                "content": """# 营收与成本分析

## 营收口径
- CRM 销售订单 CT-HMA- 金额（含税/不含税口径须一致）
- ERP 销售出库 M-FG- × 单价（出库时点确认营收）
- 双口径差异：订单金额 vs 出库金额（折扣/退货/跨月）

## 生产成本归集
- ERP 生产成本 PC-HMA-：原料 M-RES-/M-TK-/M-WAX-/M-AO- + 人工 + 制造费用
- PC-HMA-.heat_no 承载批次 BAT-，PC-HMA-.work_order_no 承载合同 CT-HMA-
- 成本中心 CC-HMA- 归集部门成本（CC-HMA-PROD 生产 / CC-HMA-ADM 行政）

## 毛利分析
- 毛利 = 营收 − 生产成本 PC-HMA- − 销售费用
- 毛利率 = 毛利 / 营收，标准品毛利 25-30%、定制 30-40%
- 低毛利预警：定制配方成本上涨（M-RES- 涨价）须上调报价 HMAQT-

## no-guessing
- PC-HMA-（ERP 成本）、CT-HMA-（CRM 合同）、BAT-（MES 批次）跨系统关联勿互传
- 调 ERP listProductionCosts + listCostCenters 归集成本
- 营收来自 CRM/ERP 双口径，勿用单口径代表全局
""",
            },
            {
                "source": "产能与工单分析.md",
                "title": "MES 产能利用率、工单完成率与不良率",
                "content": """# 产能与工单分析

## 产能利用率
- MES listShiftOutputs 按产线 LINE-AUTO-01/02 + LINE-03/04 月汇总
- 额定产能：全自动线 8t/d × 30d = 240t/月，半自动 4.5t/d × 30d = 135t/月
- 利用率 = 实际产量 / 额定产能，<80% 黄色、<60% 红色

## 工单完成率
- MES listWorkOrders 按 status 汇总（已排产/生产中/已完工/异常）
- 完成率 = 已完工 / 总工单数，按月统计
- 异常工单关联：设备故障 EQ- / 工艺偏离 PP- / 来料不良 QR-IN-

## 不良率
- MES listDefects 按缺陷类型汇总（颗粒不均/粘度偏差/外观不良）
- 不良率 = 不良数 DF / 总产量，<1% 正常、>3% 红色
- 不良 NG- 关联批次 BAT- + 检测 QR-FG- + 根因 RCA-

## no-guessing
- LINE-（产线）、EQ-（设备）、WO（工单）、BAT-（批次）、DF（不良）各自独立编号
- 调 MES listShiftOutputs/listWorkOrders/listDefects 取数，勿跨系统直传编号
- 产能来自 MES，勿用 ERP 出库代表产能
""",
            },
            {
                "source": "经营风险预警.md",
                "title": "客户回款/库存呆滞/设备故障/配方失效四维预警",
                "content": """# 经营风险预警

## 客户回款风险
- CRM 回款 HMAAR- 账龄 >30 天 → 黄色、>60 天 → 红色
- 关联争议 DSP-HMA-（进度款/质量争议），调 CRM listComplaints
- 应收占比 >40% 须重点催收

## 库存呆滞风险
- ERP 原料 M- 库存 > 安全库存 × 3 且 90 天未动 → 呆滞
- 成品 M-FG- 库存 > 安全库存 × 2 → 积压
- 调 ERP listInventory 识别呆滞，联动 sales-rep 促销

## 设备故障风险
- PCM 设备健康分 <5 → 红色停机，影响产能
- 调 PCM predictEquipmentFault，关联 EQ- + LINE-

## 配方失效风险
- FRM 失效记录 FR- 近 30 天 >5 条 → 配方稳定性预警
- 关联客诉 CC- + 检测 QR-FG-，调 FRM listFailureRecords

## 汇总
- 月度简报四维预警须可追溯源系统接口
- 勿杜撰风险等级；每项预警标注数据来源与采集时间
""",
            },
        ],
    },
    # ── 9. 文档处理知识库（dept admin） ──
    {
        "name": "starhma-admin-doc-kb",
        "scope_type": "department",
        "dept_slug": "admin", "team_slug": None,
        "description": "合同/招投标/资质文档检索与摘要、付款里程碑提取、文档分类，供文档处理 agent 检索。",
        "chunk_size": 512, "chunk_overlap": 64,
        "docs": [
            {
                "source": "合同检索与摘要规则.md",
                "title": "CT-HMA- 合同条款提取与摘要生成",
                "content": """# 合同检索与摘要规则

## 合同（CT-HMA-）
- CT-HMA-001：与 CLI-001 医疗客户合同，金额 280 万、交期 60 天、付款 30/60/10
- CT-HMA-002：与 CLI-002 包装客户合同，金额 450 万、交期 45 天、付款 40/50/10
- CT-HMA-003：与 CLI-003 物流客户合同，金额 180 万、交期 30 天、付款 50/50

## 合同字段
- 合同号 CT-HMA- / 客户 CLI- / 金额 / 交期 / 付款里程碑 / 质保期 / 保密条款 / 违约责任
- 关联生产成本 PC-HMA-.work_order_no（CT-HMA- → PC-HMA-202607001）
- 关联回款 INV202607001（发票）↔ ERP 凭证 BV-HMA-2026-0701

## 摘要生成
- 关键条款提取：金额/付款里程碑/交期/质保/保密/违约
- 风险点识别：付款偏紧/质保期争议/保密条款需强化
- 调 CRM listSalesOrders(so_no='CT-HMA-001') 查合同

## no-guessing
- CT-HMA-（CRM 合同）、PC-HMA-（ERP 成本）、INV-（CRM 发票）、BV-HMA-（ERP 凭证）各自独立编号
- 勿把 CT-HMA- 当 PC-HMA- 传 ERP；按 work_order_no 关联
- 勿把合同金额当生产成本，金额口径不同
""",
            },
            {
                "source": "招投标文档规则.md",
                "title": "招投标文件检索、资质核对与报价校验",
                "content": """# 招投标文档规则

## 招投标文件
- 招标方：医院/食品厂/物流公司/汽车厂等大客户
- 文档：招标书/技术规格书/资质要求/商务条款
- 关联询盘 INQ-（CRM 询盘号，招投标转询盘）

## 资质核对
- 投标须附环保认证：FDA/REACH/SGS/ISO-10993（按行业要求）
- 投标须附质量体系：ISO-9001 / IATF-16949（汽车）
- 资质有效期核对：临期 6 个月须续证，过期不得投标

## 报价校验
- 投标报价 HMAQT- vs 成本 PC-HMA- 毛利测算
- 报价低于成本 → 亏损预警；报价高于市场 → 落标风险
- 联动销售 sales-rep 与供应链 scm-manager 核价

## 关联
- 招投标文件号挂合同 CT-HMA-（中标后转合同）+ 客户 CLI-
- 未中标文件归档备查；勿把询盘 INQ- 当合同 CT-HMA- 传 CRM
- 调 CRM listOpportunities(opportunity_no='INQ-002') 查询盘/招投标
""",
            },
            {
                "source": "资质文档管理.md",
                "title": "环保/质量/体系资质有效期与续证",
                "content": """# 资质文档管理

## 资质清单
- 环保认证：FDA 21 CFR 175.105（FORM-STD-001/CUS-002）/ REACH / SGS RoHS / ISO-10993
- 质量体系：ISO-9001（公司级）/ IATF-16949（汽车供应链）
- 行业资质：医疗器械生产许可（FORM-CUS-002）/ 食品包装许可（FORM-STD-001）

## 有效期管理
- 资质有效期 3 年（ISO）/ 5 年（IATF）/ 2 年（FDA 食品级）
- 临期 6 个月 → 黄色预警，启动续证
- 过期资质不得对外宣传与投标

## 资质与配方绑定
- 资质证书号挂配方 formula_no（FORM-CUS-002 医疗配方 → ISO-10993 证书号）
- 调 FRM getFormula(formula_no='FORM-CUS-002') 查关联资质
- 资质文档分类：环保类/质量类/行业类，按 type 检索

## no-guessing
- 资质证书号与配方 FORM- 不同码空间，按 formula_no 关联勿互传
- 资质过期须明确标注，勿用过期资质对外答复客户
""",
            },
            {
                "source": "付款里程碑提取.md",
                "title": "合同付款节点提取与应收应付联动",
                "content": """# 付款里程碑提取

## 付款里程碑
- CT-HMA-001：30% 预付（合同签订）+ 60% 发货（交期 60 天）+ 10% 质保（质保期 12 个月）
- CT-HMA-002：40% 预付 + 50% 发货 + 10% 质保（质保期 6 个月）
- CT-HMA-003：50% 预付 + 50% 发货（无质保金）

## 提取规则
- 从合同 CT-HMA- 提取 payment_milestones 字段：节点 + 比例 + 触发条件 + 到期日
- 关联应收 HMAAR-（CRM 回款）+ 发票 INV- + 凭证 BV-HMA-（ERP）
- 节点到期未回款 → 逾期预警（days_overdue >30）

## 联动
- 付款里程碑 → 销售催收（sales-rep）→ 应收 HMAAR- → 凭证 BV-HMA-（对账 INV↔BV-HMA-）
- 质保金 10% 须质保期满释放，关联 QAS 售后故障记录（CC- 故障未结案不释放）

## no-guessing
- CT-HMA- 合同、HMAAR- 回款、INV- 发票、BV-HMA- 凭证、HMAAP 应付各自独立编号
- 按 invoice_no / contract_no 关联，勿跨系统直传编号
- 勿把付款里程碑当回款金额，二者口径不同（里程碑是计划、回款是实际）
""",
            },
            {
                "source": "采购单与凭证处理.md",
                "title": "POHMA 采购单 + BV-HMA- 凭证检索与摘要",
                "content": """# 采购单与凭证处理

## 采购单（POHMA）
- POHMA：ERP 采购单，关联供应商 S-HMA- + 物料 M- + 应付 HMAAP
- 检索：按 purchase_order_no / supplier / material / 交期 / 状态
- 摘要：采购金额 + 物料明细 + 付款条件 + 交期

## 凭证（BV-HMA-）
- BV-HMA-：ERP 财务凭证，关联发票 INV-（按 invoice_no）+ 应付 HMAAP + 采购 POHMA
- 检索：按 voucher_no / invoice_no / 金额 / 期间
- 摘要：借方/贷方科目 + 金额 + 关联业务单据

## 处理流程
- 采购入库 → 应付 HMAAP → 发票 INV- → 凭证 BV-HMA-（按 invoice_no 关联）
- 文档摘要提取：合同 CT-HMA- / 采购 POHMA / 凭证 BV-HMA- 关键条款
- 调 ERP listPurchaseOrders + listVouchers 检索，勿把 POHMA 当 BV-HMA- 传

## no-guessing
- POHMA（采购单）、HMAAP（应付）、BV-HMA-（凭证）、INV-（发票）各自独立编号
- 按 purchase_order_no / invoice_no / voucher_no 关联，勿跨系统直传
- 调 ERP listVouchers(voucher_no='BV-HMA-2026-0701') 查凭证
""",
            },
            {
                "source": "文档分类与归档规则.md",
                "title": "合同/招投标/资质/凭证分类与归档",
                "content": """# 文档分类与归档规则

## 文档分类
- 合同类：CT-HMA-001/002/003（销售合同）+ 采购合同（关联 POHMA）
- 招投标类：招标书/投标书/中标通知书（关联询盘 INQ-）
- 资质类：FDA/REACH/SGS/ISO-10993/ISO-9001/IATF-16949 证书
- 凭证类：BV-HMA- 财务凭证 + INV- 发票 + HMAAP 应付
- 技术类：配方卡（脱敏）+ 检测报告 QR-IN-/QR-FG- + 实验报告

## 归档规则
- 按客户 CLI- + 年度归档：CT-HMA-001 系列 + 资质 + 凭证
- 按配方 FORM- 归档：配方卡 + 检测报告 + 失效记录 FR-
- 保密分级：合同/配方为机密、资质/凭证为内部、招投标为秘密

## 检索
- 全文检索：按文档类型 + 客户 CLI- + 配方 FORM- + 期间
- 摘要生成：关键条款提取 + 付款里程碑 + 风险点
- 调 CRM listSalesOrders + ERP listPurchaseOrders/listVouchers 跨系统检索

## no-guessing
- 文档分类按业务实体（CLI-/FORM-/POHMA/BV-HMA-），勿混用编号
- 涉密文档（配方/合同）须脱敏后外发，勿直接转发完整内容
""",
            },
        ],
    },
]


# ───────────────────────── 辅助 ─────────────────────────

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


async def _resolve_scope_id(db, org_id, spec: dict) -> str | None:
    if spec["scope_type"] == "organization":
        return None
    if spec["scope_type"] == "department":
        dept = await _get_dept_by_slug(db, org_id, spec["dept_slug"])
        if dept is None:
            raise RuntimeError(f"部门 slug='{spec['dept_slug']}' 不存在，请先运行 seed_starhma_org.py。")
        return str(dept.id)
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
    print("星途热熔胶 RAG 集合导入完成（覆盖式幂等，可安全重复执行）")
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
        print("  注：首次入库依赖 agileac 真 embedding key（README §3 SQL 同步后从 agileac 复制 "
              "aliyun-embedding-openai + aliyun-all-openai provider/key）。")
        print("  注：若前次残留 status=failed 的文档（A4 坑），按 source 去重会再次跳过，"
              "需手动清理 RagDocument 后重跑。")
    else:
        print("✓ 无失败：embedding 通道已生效，所有 chunk 均已嵌入向量")
    print("位置：管理端「星途热熔胶」组织 → RAG 知识库 → 各集合（按 dept scope 分级可见）")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
