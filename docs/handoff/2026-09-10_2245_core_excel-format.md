# Excel 默认格式与真实浏览器失败复核

任务 PLATFORM-UNIFIED-ASSISTANT-RUNTIME-E2E-20260910。

本轮重跑独立浏览器 staging 测试，等待执行按钮退出 loading 后下载，实际扩展名 `.csv`、1341 字节；请求明确为“根据当前业务数据生成一份 Excel”。页面仍处于 application 视图，有弹窗及产物卡片。清理结果：测试 Task 删除 1、文件移入回收站 1、failures=[]。这证明至少该次不是单纯弹窗定位失败；不推断业务数据内容正确。

本地复核：复合导出 Schema 默认 xlsx，但 output_name 描述建议 xlsx 或 csv，且共享显式格式完成保护未识别 Excel/Word/PPT 产品名。补充现代格式别名 Excel→xlsx、Word→docx、PPT→pptx，并明确 CSV 需用户请求。仅作用于显式输出声明及完成检查，不作为前置意图门禁或工具路由。

新增纯函数测试覆盖 Excel 默认、Word/PPT 默认、输入 Excel 输出 CSV、输入 CSV 输出 Excel、只读 Excel 不要求产物，以及 CSV 拒绝/XLSX 接受。

验证：`pytest tests/test_delivery_format_aliases.py tests/test_assistant_policy.py tests/test_native_assistant_core.py tests/test_message_verification.py -q --tb=short` 91 passed；三个变更 Python 文件 Ruff 通过。首次收集因测试参数误用 pytest 保留名 request 失败，改为 prompt 后重跑通过。

浏览器脚本补充脱敏的主页面路径/view/是否带 conversation 变化记录，不包含业务正文、凭据或完整查询参数。

未部署本地代码。弹窗间歇性消失尚未定位；跨视图检查仍未执行到；隐含自然语言产物目标、多模态交付和全目标验收仍未完成。
