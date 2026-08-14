"""为「敏睿制造」组织的「规章制度」RAG 知识库批量导入制造企业规章制度文档。

直接走 service 层入库（分块 + 嵌入），无需 JWT。幂等：按 (collection, source) 去重，
已存在的 source 跳过，可安全重复执行。

用法:
    cd llm_router/backend
    python scripts/seed_rag_regulations.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from sqlalchemy import select

from app.database import async_session_factory
from app.models.organization import Organization
from app.models.rag import RagCollection, RagDocument
from app.schemas.rag import RagDocumentCreate
from app.services.rag_service import get_collection, ingest_document, list_collections

logger = structlog.get_logger()

ORG_NAME = "敏睿制造"
COLL_NAME = "规章制度"

# ───────────────────────── 规章制度文档 ─────────────────────────

DOCS: list[dict] = [
    {
        "source": "安全生产管理制度.md",
        "title": "安全生产管理制度",
        "content": """# 安全生产管理制度

## 第一章 总则
第一条 为贯彻「安全第一、预防为主、综合治理」的方针，保障员工生命安全与企业财产安全，特制定本制度。
第二条 本制度适用于公司全体员工、实习生、外包及来访人员。
第三条 总经理是安全生产第一责任人；各车间、部门负责人为本单位安全直接责任人。

## 第二章 安全生产责任
第四条 落实「管生产必须管安全」原则，各级管理人员在计划、布置、检查、总结、评比生产时，同时计划、布置、检查、总结、评比安全工作。
第五条 员工有权拒绝违章指挥和强令冒险作业，有权对安全隐患提出批评、检举和控告。

## 第三章 安全教育与培训
第六条 新员工上岗前必须接受公司级、车间级、班组级「三级安全教育」，考核合格后方可上岗，并建立培训档案。
第七条 特种作业人员（电工、焊工、叉车工、压力容器操作等）必须持证上岗，证件定期复审。
第八条 每年至少组织一次全员安全复训和应急演练。

## 第四章 现场安全
第九条 进入生产现场必须正确佩戴劳动防护用品（安全帽、护目镜、劳保鞋、耳塞等）。
第十条 严禁违章操作、违章指挥、违反劳动纪律；严禁脱岗、串岗、睡岗。
第十一条 危险作业（动火、高处、有限空间、吊装、临时用电等）必须办理作业许可证，落实专人监护。

## 第五章 隐患排查与事故处理
第十二条 建立日常巡检、周检、月度大检查制度，隐患实行「登记—整改—验收—销账」闭环管理。
第十三条 发生事故必须立即报告，不得瞒报、迟报、漏报；按「四不放过」原则调查处理。

## 第六章 附则
第十四条 本制度自发布之日起施行，由安全环保部负责解释。
""",
    },
    {
        "source": "质量管理制度.md",
        "title": "质量管理制度",
        "content": """# 质量管理制度

## 第一章 总则
第一条 为稳定并持续提升产品质量，满足客户要求，依据 ISO 9001 体系制定本制度。
第二条 质量方针：全员参与、过程控制、持续改进、客户满意。

## 第二章 进货检验（IQC）
第三条 原材料、外协件进厂须附合格证或检验报告，按抽样方案检验，不合格品予以退货或让步接收（须经技术负责人批准）。
第四条 建立供应商质量档案，定期进行业绩评价与现场审核。

## 第三章 过程检验（IPQC）
第五条 首件必须经检验合格后方可批量生产；关键工序设置质量控制点，按规定频次巡检。
第六条 出现不合格品立即标识、隔离，并启动不合格品评审流程。

## 第四章 成品检验（FQC）
第七条 成品按检验规范全检或抽检，合格开具入库检验单方可入库。
第八条 出货前进行最终核查，确保型号、数量、包装、标识符合订单要求。

## 第五章 不合格品与纠正措施
第九条 不合格品分为返工、返修、降级、报废四种处置方式。
第十条 对重复性质量问题启动 8D 或纠正与预防措施（CAPA），跟踪验证闭环。

## 第六章 质量追溯
第十一条 建立批号追溯体系，从原材料到成品全过程可追溯，保存记录至少三年。
""",
    },
    {
        "source": "设备设施管理制度.md",
        "title": "设备设施管理制度",
        "content": """# 设备设施管理制度

## 第一章 总则
第一条 为保证生产设备安全、稳定、高效运行，延长设备寿命，降低故障率，制定本制度。
第二条 设备管理实行「谁使用、谁维护、谁负责」原则。

## 第二章 设备台账与档案
第三条 建立全公司设备台账，一机一档，包含说明书、图纸、维修记录、点检记录。
第四条 关键设备（A类）重点管理，配备备品备件清单与应急预案。

## 第三章 日常点检与保养
第五条 操作工每日班前按点检表进行日常点检，填写记录。
第六条 推行自主保养（操作工）与专业保养（维修工）相结合的 TPM 体系，执行日、周、月、年保养计划。

## 第四章 维修管理
第七条 设备故障实行报修—派工—维修—验收流程，响应与修复时限纳入考核。
第八条 重大故障进行根因分析，制定预防措施。

## 第五章 备件管理
第九条 备件实行最低库存管理，重要备件保持安全库存，领用实行以旧换新。

## 第六章 设备报废
第十条 设备满足报废条件（无修复价值、技术淘汰、安全不达标）经鉴定批准后报废。
""",
    },
    {
        "source": "员工考勤与请假管理制度.md",
        "title": "员工考勤与请假管理制度",
        "content": """# 员工考勤与请假管理制度

## 第一章 考勤管理
第一条 公司实行标准工时制，工作时间为周一至周五 8:30—17:30，午休 1 小时。
第二条 采用打卡考勤，员工须本人上下班打卡，严禁代打卡。
第三条 迟到、早退、旷工按考勤细则扣罚；月满勤给予全勤奖。

## 第二章 请假流程
第四条 请假须提前在系统提交申请，按权限审批：
  - 请假 1 天以内由班组长审批；
  - 1—3 天由车间/部门负责人审批；
  - 3 天以上报人力资源部、分管副总审批。
第五条 病假须提供县级及以上医院证明；事假一般不超过 5 天。

## 第三章 假期类别
第六条 法定假期按国家规定执行；年休假按工龄累计，当年未休可结转一次。
第七条 婚假、产假、陪产假、丧假、工伤假按国家及地方规定执行。

## 第四章 加班管理
第八条 因生产需要加班须事前审批，实行调休或支付加班费。
第九条 严禁安排孕期、哺乳期女工及未成年工加班或夜班。

## 第五章 附则
第十条 考勤数据为工资计算依据，弄虚作假者按违纪处理。
""",
    },
    {
        "source": "仓库与物料管理制度.md",
        "title": "仓库与物料管理制度",
        "content": """# 仓库与物料管理制度

## 第一章 总则
第一条 为规范物料收发存管理，做到账、卡、物一致，制定本制度。

## 第二章 入库管理
第二条 物料到货须核对品名、规格、数量、批号，经质检合格方可办理入库。
第三条 入库及时登账、挂料卡，按分类分区码放，符合先进先出原则。

## 第三章 在库管理
第四条 仓库实行定置定位管理，标识清晰；通道畅通，符合消防要求。
第五条 易燃、易爆、危化品专库专柜存放，双人双锁，建立 MSDS 档案。
第六条 定期盘点（日抽盘、月盘、年大盘），差异查明原因并审批调整。

## 第四章 出库管理
第七条 出库须凭领料单，按先进先出发料，严禁白条出库。
第八条 生产余料、废料及时退库或分类处置。

## 第五章 账务与报表
第九条 仓管员每日更新台账，月末编制收发存报表，与财务、采购对账。
""",
    },
    {
        "source": "车间5S现场管理制度.md",
        "title": "车间5S现场管理制度",
        "content": """# 车间5S现场管理制度

## 第一章 总则
第一条 为营造整洁、高效、安全的工作环境，提升员工素养，推行 5S（整理、整顿、清扫、清洁、素养）管理。

## 第二章 5S 要求
第二条 整理（SEIRI）：区分要与不要的物品，清理现场多余物。
第三条 整顿（SEITON）：定置定位定量摆放，标识清晰，30 秒内可取用。
第四条 清扫（SEISO）：清扫设备与地面，发现并消除污染源与微小缺陷。
第五条 清洁（SEIKETSU）：将前 3S 制度化、标准化，维持成果。
第六条 素养（SHITSUKE）：养成遵守标准、按章操作的习惯，提升团队精神。

## 第三章 可视化与定置
第七条 通道、区域、工位划线标识；工具采用形迹管理或影子板；看板公示产量、质量、安全信息。

## 第四章 检查与考核
第八条 每日班前 5 分钟整理整顿，每周班组自查，每月公司组织 5S 评比。
第九条 评比结果与车间绩效挂钩，连续末位通报整改。
""",
    },
    {
        "source": "环境与职业健康管理制度.md",
        "title": "环境与职业健康管理制度",
        "content": """# 环境与职业健康管理制度

## 第一章 总则
第一条 依据 ISO 14001 与 ISO 45001 体系，防治污染、保障员工健康，制定本制度。

## 第二章 环境管理
第二条 废气、废水、噪声、固废达标排放，建立监测台账。
第三条 危废交有资质单位处置，执行联单制度，严禁随意排放。
第四条 推行节能减排，水电气消耗纳入车间考核。

## 第三章 职业健康
第五条 对粉尘、噪声、化学品等职业病危害因素每年检测，结果公示。
第六条 接害岗位员工上岗前、在岗期间、离岗时进行职业健康体检，建立健康档案。
第七条 配发符合标准的个体防护用品，督促正确佩戴。

## 第四章 应急管理
第八条 编制环境污染与职业病突发事件应急预案，配备应急物资，每年演练。
""",
    },
    {
        "source": "员工奖惩管理制度.md",
        "title": "员工奖惩管理制度",
        "content": """# 员工奖惩管理制度

## 第一章 总则
第一条 为表彰先进、纠正违纪，营造公平公正氛围，制定本制度。

## 第二章 奖励
第二条 奖励分为：通报表扬、嘉奖、记功、晋升、奖金。
第三条 有下列情形之一者给予奖励：提出合理化建议或技改成效显著；发现重大隐患避免事故；质量/产量指标突出；见义勇为维护公司利益。

## 第三章 惩处
第四条 惩处分为：警告、记过、降级降薪、解除劳动合同。
第五条 有下列情形之一者予以惩处：违反安全/质量/工艺纪律；旷工、打架斗殴；弄虚作假、泄密；盗窃或故意损坏财物。

## 第四章 程序
第六条 奖惩须经调查核实，重大惩处听取员工申辩，并告知工会，留存记录。
第七条 员工对惩处有异议可按申诉渠道反映。

## 第五章 附则
第八条 奖惩记录记入个人档案，作为考核、晋升依据。
""",
    },
]


async def main() -> None:
    async with async_session_factory() as db:
        # 定位组织
        org = (await db.execute(
            select(Organization).where(Organization.name == ORG_NAME, Organization.deleted_at.is_(None))
        )).scalar_one_or_none()
        if not org:
            logger.error("org_not_found", name=ORG_NAME)
            sys.exit(1)
        logger.info("org_resolved", id=str(org.id), name=org.name)

        # 定位「规章制度」集合（组织级 scope）
        colls = await list_collections(db, org.id, scope_type="organization")
        coll = next((c for c in colls if c.name == COLL_NAME), None)
        if not coll:
            logger.error("collection_not_found", name=COLL_NAME, org=ORG_NAME,
                         hint="请先在前端「敏睿制造」节点下新建知识库「规章制度」")
            sys.exit(1)
        # 刷新关系以备 ingest 使用
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

        logger.info("done", added=added, skipped=skipped, total=len(DOCS))


if __name__ == "__main__":
    asyncio.run(main())
