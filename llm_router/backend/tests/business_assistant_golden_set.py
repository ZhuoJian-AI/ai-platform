"""Reviewed garment-business utterances used by shadow-routing evaluation.

Eight real pages multiplied by twenty-five fixed utterance patterns yields 200
stable cases. The patterns deliberately cover page explanation, live queries,
navigation, mutations, exports, platform file operations and clarification.
"""

from __future__ import annotations

PAGES = [
    ("progress_dashboard.main", "进度看板", "订单", "factory_progress.main", "工厂进度监测", True),
    ("factory_progress.main", "工厂进度监测", "工厂进度", "progress_dashboard.main", "进度看板", True),
    ("style_hub.main", "款号资料中心", "款号", "process_library.main", "服装工艺库", True),
    ("process_library.main", "服装工艺库", "工艺模板", "style_hub.main", "款号资料中心", False),
    ("size_pattern_library.main", "产品尺寸库", "尺寸表", "style_hub.main", "款号资料中心", False),
    ("material_suppliers.main", "面辅料厂商", "供应商", "material_consumption.main", "面辅料耗料核算", True),
    ("material_consumption.main", "面辅料耗料核算", "耗料记录", "material_suppliers.main", "面辅料厂商", True),
    ("wash_label.main", "洗唛合格证制作", "洗唛报告", "style_hub.main", "款号资料中心", True),
]


def build_golden_cases() -> list[dict]:
    cases: list[dict] = []
    for page_key, page_name, entity, related_key, related_name, has_export in PAGES:
        patterns = [
            (f"{page_name}是做什么的？", "explain_page", page_key),
            (f"解释一下{page_name}当前页面能解决什么问题", "explain_page", page_key),
            (f"这里的{entity}字段分别是什么意思？", "explain_page", page_key),
            (f"查询当前{entity}", "query", page_key),
            (f"当前有多少条{entity}？", "query", page_key),
            (f"列出最近更新的{entity}", "query", page_key),
            (f"查一下状态异常的{entity}", "query", page_key),
            (f"只看我当前筛选范围里的{entity}", "query", page_key),
            (f"按更新时间倒序给我前十条{entity}", "query", page_key),
            (f"刚才选中的{entity}现在是什么状态？", "query", page_key),
            (f"汇总这个页面的{entity}数量", "query", page_key),
            (f"从{page_name}带我去{related_name}处理", "navigate", related_key),
            (f"{page_name}这个问题需要在{related_name}查看", "navigate", related_key),
            (f"新增一条{entity}", "mutate", page_key),
            (f"修改我刚才选中的{entity}", "mutate", page_key),
            (f"删除编号明确的那条{entity}", "mutate", page_key),
            (f"确认并提交当前{entity}变更", "mutate", page_key),
            (f"把当前{entity}生成 Excel", "export_file" if has_export else "clarify", page_key),
            (f"导出当前筛选的{entity}为 CSV", "export_file" if has_export else "clarify", page_key),
            (f"根据实时{entity}制作一份 PDF 报告", "export_file" if has_export else "clarify", page_key),
            (f"将当前{entity}整理成 Word 文档", "export_file" if has_export else "clarify", page_key),
            (f"在{page_name}把我上传的文档转换成 PDF", "file_operation", page_key),
            (f"在{page_name}修改刚才生成的工作空间文件", "file_operation", page_key),
            (f"帮我处理一下{page_name}里的内容", "clarify", page_key),
            (f"看看那个{entity}", "clarify", page_key),
        ]
        for index, (utterance, intent, expected_page) in enumerate(patterns, start=1):
            cases.append({
                "caseId": f"{page_key}:{index:02d}",
                "pageKey": page_key,
                "utterance": utterance,
                "expectedIntent": intent,
                "expectedPageKey": expected_page,
            })
    return cases


GOLDEN_CASES = build_golden_cases()
