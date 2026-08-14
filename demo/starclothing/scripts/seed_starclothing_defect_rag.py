"""为「星途服装」组织创建并填充「服装缺陷知识库」RAG 集合。

为 PD-3「新品生命周期数据闭环」agent 提供历史缺陷案例检索语料：覆盖漏水、
压胶脱落、起球、掉色、尺寸偏差、跳针断线、印花错位、整烫烫花 8 类典型
服装缺陷，每类按「缺陷描述 / 根因分析 / 纠正措施 / 预防规避 / 关联款号」
结构化条目组织，便于 agent 在新品开发评审时检索相似历史案例做风险预警。

幂等：集合存在则复用，文档按 (collection, source) 去重，可安全重复执行。

用法:
    # 容器内（docker cp 后）：
    docker cp demo/starclothing/scripts/seed_starclothing_defect_rag.py ai_infra_backend:/app/scripts/
    docker exec ai_infra_backend python scripts/seed_starclothing_defect_rag.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 兼容两种位置：容器内 /app/scripts/ → backend=/app；本地 demo/starclothing/scripts/ → backend=repo/llm_router/backend
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent
if not (_BACKEND_DIR / "app" / "database.py").exists():
    _BACKEND_DIR = _HERE.parents[3] / "llm_router" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import structlog
from sqlalchemy import select

from app.database import async_session_factory
from app.models.organization import Organization
from app.models.rag import RagCollection, RagDocument
from app.schemas.rag import RagCollectionCreate, RagDocumentCreate
from app.services.rag_service import (
    create_collection, get_collection, ingest_document, list_collections,
)

logger = structlog.get_logger()

ORG_NAME = "星途服装"
ORG_SLUG_FALLBACK = "starclothing"
COLL_NAME = "服装缺陷知识库"


# ───────────────────────── 缺陷知识库文档 ─────────────────────────
# 8 类典型服装缺陷，每类一份结构化 Markdown，便于 RAG 分块命中。
# 字段对齐 PLM mock 的 defect_history 表（defect_type / root_cause / corrective / avoidance）。

DOCS: list[dict] = [
    {
        "source": "缺陷-漏水.md",
        "title": "压胶冲锋衣·漏水缺陷分析",
        "content": """# 压胶冲锋衣·漏水缺陷分析

## 缺陷类型
漏水（ seam tape 渗漏 / 拉链位漏水）

## 常见发生部位
- 压胶冲锋衣主缝位（前片合肩、袖底、侧缝）
- 拉链部位压胶断点
- 帽檐与领口接缝

## 根因分析
1. **压胶温度不足**：热风机温度低于 120℃，胶条未充分熔融，无法渗入面料涂层。典型案例 DF20260001：压胶温度仅 105℃，水压测试 5kPa 即渗漏。
2. **胶条库存过期受潮**：胶条存放超过 6 个月或仓库湿度 >65%，热熔胶活化点漂移。典型案例 DF20260002。
3. **拉链位压胶断点**：拉链牙位压胶未连续，形成进水点。典型案例 DF20260012。
4. **压胶机硅胶轮老化**：硅胶轮表面硬化或磨损，压力不均。典型案例 DF20260018。
5. **面料涂层缺陷**：PU/DWR 涂层局部破损，水从面料本体渗入。

## 纠正措施
- 不合格品 100% 返工：拆开压胶条重新压胶，温度 130—140℃，压力 4bar，速度 2.5m/min。
- 拉链位改用预制压胶贴片，避免连续压胶中断。
- 胶条入库执行先进先出，库存超 3 个月重新做活化测试。

## 预防规避（新品开发评审必查）
- 设计阶段：明确压胶部位清单，拉链位必出防水贴片 BOM。
- 工艺阶段：试产首件必做水压测试（GB/T 4744），水压 ≥10kPa 合格，关键款 ≥15kPa。
- 物料阶段：胶条供应商需提供活化温度曲线，每批次附检测报告。
- 验证阶段：量产前抽 3 件做整衣水压 + 24h 雨淋测试。

## 关联历史款号
P-FW2026-002（压胶冲锋衣）、关联工单 XWO20260788、XWO20260800、XWO20260811。
""",
    },
    {
        "source": "缺陷-压胶脱落.md",
        "title": "压胶冲锋衣·压胶脱落缺陷分析",
        "content": """# 压胶冲锋衣·压胶脱落缺陷分析

## 缺陷类型
压胶脱落（胶条从面料上剥离，露出原缝位）

## 常见发生部位
- 压胶冲锋衣所有压胶缝位
- 胶条搭接点、起止点

## 根因分析
1. **胶条库存过期受潮**：热熔胶吸潮后粘力下降。典型案例 DF20260002：胶条库存 8 个月，仓库湿度 72%。
2. **压胶机硅胶轮老化**：压力不均，局部胶条未压实。典型案例 DF20260018。
3. **面料表面处理剂残留**：DWR 助剂未洗净，胶条与面料界面结合不良。
4. **压胶速度过快**：速度 >3.5m/min 时胶条活化时间不足。
5. **环境温度过低**：车间 <15℃，胶条冷却过快。

## 纠正措施
- 不合格品返工：拆胶条时使用专用剥胶机，避免损伤面料涂层；重新压胶参数同「漏水」缺陷。
- 胶条批次到货做剥离强度测试（≥8N/25mm）。
- 硅胶轮每月点检硬度，超过 Shore 60° 立即更换。

## 预防规避（新品开发评审必查）
- 工艺阶段：试产压胶部位 100% 做剥离强度抽测。
- 物料阶段：胶条供应商每批次附剥离强度报告，仓库存放温度 15—25℃、湿度 ≤55%。
- 设备阶段：压胶机每班点检温度/压力/速度三参数。
- 验证阶段：水洗 5 次后复测剥离强度，下降 ≤15% 为合格。

## 关联历史款号
P-FW2026-002（压胶冲锋衣）、关联工单 XWO20260788、XWO20260811。
""",
    },
    {
        "source": "缺陷-起球.md",
        "title": "双面呢大衣·面料起球缺陷分析",
        "content": """# 双面呢大衣·面料起球缺陷分析

## 缺陷类型
面料起球（面料表面毛球，影响外观与手感）

## 常见发生部位
- 羊毛/羊绒含量 ≥30% 的双面呢大衣
- 易摩擦部位：袖口、肘部、侧缝、腋下

## 根因分析
1. **羊毛纱线捻度偏低**：纱线结构松散，纤维易游离起毛。典型案例 DF20260003：捻度 380T/m，标准 450T/m。
2. **纱线毛羽偏长**：纺纱工序毛羽控制差，长毛羽易缠绕成球。典型案例 DF20260014。
3. **抗起球助剂缺失**：羊绒含量 ≥30% 必做抗起球处理，未执行。
4. **面料未预缩**：松弛回缩后纤维位移，加剧起球。
5. **整烫温度过高**：蒸汽烫伤面料表面，毛羽竖起。

## 纠正措施
- 不合格品：轻度起球用毛球修剪器处理，重度起球让步接收并降级销售。
- 调整纺纱捻度至 ≥450T/m；纱线供应商每批附捻度测试报告。
- 羊绒含量 ≥30% 的款必做抗起球助剂（如 CIBA 或 Gasogen 系列）。

## 预防规避（新品开发评审必查）
- 设计阶段：BOM 标注羊毛/羊绒含量、捻度要求、抗起球等级（≥3—4 级 GB/T 4802.1）。
- 物料阶段：纱线到货做捻度、毛羽、抗起球三项测试，羊绒 ≥30% 强制加抗起球助剂。
- 工艺阶段：试产首件做 5000 次马丁代尔摩擦测试。
- 验证阶段：成品做穿着模拟测试（30 次穿脱 + 摩擦），起球等级 ≥3 级。

## 关联历史款号
P-FW2026-001（双面呢大衣）、关联工单 XWO20260789、XWO20260799。
""",
    },
    {
        "source": "缺陷-掉色.md",
        "title": "纯棉T恤与牛仔裤·掉色缺陷分析",
        "content": """# 纯棉T恤与牛仔裤·掉色缺陷分析

## 缺陷类型
掉色（染料褪色、沾色、色迁移）

## 常见发生部位
- 纯棉 T 恤：领口、袖口、侧缝（与白色拼接处）
- 牛仔裤：臀部、膝盖、口袋边

## 根因分析
1. **活性染料固色不充分**：固色剂用量不足或固色温度未达 85℃。典型案例 DF20260004。
2. **水洗时间不足**：未充分洗去浮色，残留染料转移。典型案例 DF20260005。
3. **染料选择不当**：浅色系选了低色牢度染料。
4. **后整理未加固色**：固色剂或皂洗剂批次失效。
5. **烘干温度过高**：>120℃ 时染料升华，浅色面料尤其敏感。

## 纠正措施
- 不合格品：返工再固色（活性染料 85℃ × 20min，固色剂 2% o.w.f）+ 充分皂洗。
- 染料供应商每批次附色牢度报告（≥4 级 GB/T 3920）。
- 固色剂每批次做小样对比，失效立即停用。

## 预防规避（新品开发评审必查）
- 设计阶段：BOM 标注染料类型、色牢度要求（耐水洗 ≥4 级、耐摩擦 ≥3—4 级）。
- 物料阶段：面料到货做色牢度四项测试（水洗、摩擦、汗渍、日晒）。
- 工艺阶段：试产首件做水洗 5 次 + 摩擦 50 次复测色牢度。
- 验证阶段：浅深色拼接款必做沾色测试（≥4 级）。

## 关联历史款号
P-SS2026-010（纯棉T恤）、P-SS2026-020（牛仔裤）、关联工单 XWO20260802、XWO20260808。
""",
    },
    {
        "source": "缺陷-尺寸偏差.md",
        "title": "风衣与牛仔裤·尺寸偏差缺陷分析",
        "content": """# 风衣与牛仔裤·尺寸偏差缺陷分析

## 缺陷类型
尺寸偏差（成衣尺寸超出公差，影响合体度）

## 常见发生部位
- 风衣：胸围、衣长、袖长
- 牛仔裤：腰围、裤长、膝围
- 双面呢大衣：肩宽、胸围

## 根因分析
1. **裁剪样板未复核**：样板磨损或改版后未重新校对。典型案例 DF20260006。
2. **水洗缩率未预缩**：牛仔面料水洗缩率 5—8%，未做预缩导致成品偏小。典型案例 DF20260011。
3. **手缝吃势不均**：双面呢手工缝制吃势分配不均，尺寸偏差。典型案例 DF20260016。
4. **缝位吃势不当**：车缝时缝位未对齐，累计偏差。
5. **整烫变形**：整烫时拉伸过度，尺寸漂移。

## 纠正措施
- 不合格品：尺寸偏差超 1cm 返工改缝，超 2cm 降级销售。
- 牛仔面料到货必做缩率测试，样板放码时预加缩量。
- 双面呢手缝工序设制板复核岗，每款 100% 复核。

## 预防规避（新品开发评审必查）
- 设计阶段：BOM 标注面料缩率、成品公差（胸围 ±1.5cm、衣长 ±1cm）。
- 物料阶段：面料到货做缩率测试，缩率 >5% 强制预缩。
- 工艺阶段：试产首件 100% 量尺寸，关键尺寸（胸围、衣长、袖长、腰围）全检。
- 验证阶段：量产抽 10% 复测尺寸，超差批次 100% 返工。

## 关联历史款号
P-AP2026-030（风衣）、P-SS2026-020（牛仔裤）、P-FW2026-001（双面呢大衣）、关联工单 XWO20260810、XWO20260815、XWO20260789。
""",
    },
    {
        "source": "缺陷-跳针断线.md",
        "title": "多款·跳针断线缺陷分析",
        "content": """# 多款·跳针断线缺陷分析

## 缺陷类型
跳针断线（车缝线迹不连续、断线）

## 常见发生部位
- 纯棉 T 恤：领口双针、袖口
- 卫衣：帽口、口袋贴边
- 衬衫：门筒、领座
- 牛仔裤：裤襻、包缝位

## 根因分析
1. **机针偏细**：9# 机针用于厚料，针尖弯折跳针。典型案例 DF20260010：摇粒绒开衫用 9# 应改 11#。
2. **线迹密度过稀**：每 2cm 不到 8 针，受力点单针承力过大。典型案例 DF20260013。
3. **包缝线断裂**：包缝线张力不当或线品质差。典型案例 DF20260017。
4. **面料厚薄过渡**：薄到厚过渡时机针易偏。
5. **缝线老化**：缝线库存过久，强度下降。

## 纠正措施
- 不合格品：返工补缝，跳针段重缝，断线段接缝加固。
- 机针按面料厚度选型：薄料 9#、中厚 11#、厚料 14#。
- 缝线到货做强度测试，库存超 1 年淘汰。

## 预防规避（新品开发评审必查）
- 工艺阶段：试产首件按面料厚度选机针号，关键受力部位（裤襻、口袋贴边）用 14# 针。
- 工艺阶段：线迹密度每 2cm ≥8 针，关键部位 ≥10 针。
- 物料阶段：缝线强度 ≥3N，库存周期 ≤6 个月。
- 验证阶段：成品做拉力测试（拉链位、袋口位 ≥80N）。

## 关联历史款号
P-SS2026-010（纯棉T恤）、P-SS2026-011（摇粒绒开衫）、P-AP2026-031（衬衫）、P-SS2026-020（牛仔裤）、关联工单 XWO20260801、XWO20260809、XWO20260815。
""",
    },
    {
        "source": "缺陷-印花错位.md",
        "title": "印花T恤与卫衣·印花错位缺陷分析",
        "content": """# 印花T恤与卫衣·印花错位缺陷分析

## 缺陷类型
印花错位（印花图案偏移、倾斜、套色不准）

## 常见发生部位
- 纯棉 T 恤：胸前印花、后背印花
- 卫衣：胸前印花
- 风衣：背后 logo 印花

## 根因分析
1. **网版定位松动**：网版定位销磨损或定位胶失效。典型案例 DF20260007。
2. **布面张力不均**：布面绷紧不均，印花时布料位移。典型案例 DF20260008。
3. **套色对位不准**：多色套印时各色网版定位基准不一致。
4. **印花台板不平**：台板水平度差，印花受力不均。
5. **布料预缩不足**：印花后布料回缩，图案变形。

## 纠正措施
- 不合格品：让步接收或返工重印（仅限浅色覆盖印）。
- 网版每月校定位销，磨损超 0.5mm 立即更换。
- 印花台板每周校水平度，误差 ≤1mm。

## 预防规避（新品开发评审必查）
- 工艺阶段：试产首件做印花套色对位测试，误差 ≤1mm。
- 工艺阶段：多色套印必出定位十字线，每色复核。
- 物料阶段：印花布到货做张力测试，张力差异 ≤5%。
- 验证阶段：成品做水洗 5 次复测印花位置与色牢度。

## 关联历史款号
P-SS2026-010（纯棉T恤）、P-AP2026-032（卫衣）、关联工单 XWO20260803、XWO20260813。
""",
    },
    {
        "source": "缺陷-整烫烫花.md",
        "title": "双面呢与风衣·整烫烫花缺陷分析",
        "content": """# 双面呢与风衣·整烫烫花缺陷分析

## 缺陷类型
整烫烫花（熨烫温度过高或压力过大导致面料极光、烫痕）

## 常见发生部位
- 双面呢大衣：领面、门襟、袋口
- 风衣：覆肩、门襟
- 压胶冲锋衣：压胶位周边（非压胶部位）

## 根因分析
1. **熨斗温度过高**：熨斗温度 >170℃，羊毛化纤烫伤出极光。典型案例 DF20260009：180℃ 烫双面呢。
2. **蒸汽压力过大**：蒸汽直吹面料，局部变形。典型案例 DF20260015。
3. **熨烫未垫布**：熨斗直接接触面料，温度冲击大。
4. **整烫时间过长**：单点停留 >3s，热量累积烫伤。
5. **面料含化纤比例高**：化纤耐温低，更易烫花。

## 纠正措施
- 不合格品：轻度极光用蒸汽反复熏蒸复原；重度烫花让步接收或降级。
- 熨斗温度按面料分档：羊毛 130—140℃、化纤 110—120℃、棉 150—160℃。
- 整烫必垫烫布，单点停留 ≤2s。

## 预防规避（新品开发评审必查）
- 工艺阶段：试产首件按面料材质标熨烫温度档位，整烫工培训持证上岗。
- 工艺阶段：每工位挂熨烫温度对照表，关键部位（领面、门襟）必垫烫布。
- 设备阶段：熨斗每周校温度，误差 ≤5℃。
- 验证阶段：成品整烫后 100% 目视检查，关键款做极光仪检测。

## 关联历史款号
P-FW2026-001（双面呢大衣）、P-AP2026-030（风衣）、关联工单 XWO20260789、XWO20260810。
""",
    },
    {
        "source": "缺陷-闭环总览.md",
        "title": "新品开发缺陷风险预警·闭环机制",
        "content": """# 新品开发缺陷风险预警·闭环机制

## 闭环目标
将历史大货生产中的缺陷案例（PLM defect_history 表）沉淀为知识库，
在新品开发评审（Sampling / Bulk 阶段）由 PD-3 agent 检索相似历史
缺陷，输出风险预警与预防清单，避免同类缺陷在新款重复发生。

## 数据流
1. **缺陷录入**：大货生产出现缺陷 → MES 工单缺陷记录 → PLM 缺陷案例库（defect_history）。
2. **知识沉淀**：缺陷案例按 8 类缺陷类型结构化整理，沉淀至「服装缺陷知识库」RAG 集合。
3. **新品评审**：新品开发评审会 → PD-3 agent 接收款号/品类/工艺 → 检索知识库相似历史案例。
4. **风险预警**：agent 输出「历史缺陷 + 根因 + 预防措施 + 评审必查项」清单。
5. **闭环验证**：新款试产/量产验证预防措施落实，复测结果回写 PLM feasibility_log。

## 检索触发示例
- 款号 P-FW2026-002（压胶冲锋衣）→ 命中 漏水/压胶脱落 案例 → 必查压胶温度、胶条批次、拉链防水贴片。
- 款号 P-FW2026-001（双面呢大衣）→ 命中 起球/尺寸偏差/烫花 案例 → 必查纱线捻度、抗起球助剂、样板复核、整烫温度。
- 款号 P-SS2026-010（纯棉 T 恤）→ 命中 掉色/印花错位/起球/跳针 案例 → 必查染料色牢度、网版定位、抗起球助剂、机针选型。

## 关联系统
- PLM defect_history 表：18 条历史缺陷案例（DF20260001—DF20260018）。
- PLM feasibility_log 表：可行性评估日志，记录预防措施落实情况。
- MES 工单缺陷记录：实时缺陷数据源。
- 服装缺陷知识库 RAG：本知识库，PD-3 agent 检索语料。
""",
    },
]


async def _get_org(db) -> Organization:
    from sqlalchemy import or_
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    org = (await db.execute(stmt.where(Organization.name == ORG_NAME))).scalar_one_or_none()
    if org is None:
        org = (await db.execute(stmt.where(Organization.slug == ORG_SLUG_FALLBACK))).scalar_one_or_none()
    return org


async def main() -> None:
    async with async_session_factory() as db:
        org = await _get_org(db)
        if not org:
            logger.error("org_not_found", name=ORG_NAME)
            sys.exit(1)
        logger.info("org_resolved", id=str(org.id), name=org.name, slug=org.slug)

        # 定位或创建「服装缺陷知识库」集合（组织级 scope）
        colls = await list_collections(db, org.id, scope_type="organization")
        coll = next((c for c in colls if c.name == COLL_NAME), None)
        if not coll:
            coll = await create_collection(db, org.id, RagCollectionCreate(
                name=COLL_NAME,
                description="服装 8 类典型缺陷（漏水/压胶脱落/起球/掉色/尺寸偏差/跳针断线/印花错位/整烫烫花）历史案例知识库，供 PD-3 新品生命周期 agent 检索。",
                embedding_model="text-embedding-v4",
                chunk_size=800,
                chunk_overlap=100,
                scope_type="organization",
                scope_id=None,
            ))
            await db.commit()
            logger.info("collection_created", id=str(coll.id), name=coll.name)
        else:
            coll = await get_collection(db, coll.id)
            logger.info("collection_resolved", id=str(coll.id), name=coll.name,
                        embedding=coll.embedding_model, chunk=f"{coll.chunk_size}/{coll.chunk_overlap}")

        # 去重：已存在的 source 跳过
        existing = {d.source for d in (await db.execute(
            select(RagDocument.source).where(
                RagDocument.collection_id == coll.id, RagDocument.deleted_at.is_(None)
            )
        )).all()}

        added, skipped = 0, 0
        for d in DOCS:
            if d["source"] in existing:
                logger.info("skip_exists", source=d["source"])
                skipped += 1
                continue
            doc = await ingest_document(db, coll, org.id, RagDocumentCreate(
                source=d["source"], title=d["title"], content=d["content"], folder_path="",
            ))
            await db.commit()
            logger.info("ingested", source=doc.source, title=doc.title, doc_id=str(doc.id))
            added += 1

        logger.info("done", added=added, skipped=skipped, total=len(DOCS),
                    collection_id=str(coll.id), collection=COLL_NAME)


if __name__ == "__main__":
    asyncio.run(main())
