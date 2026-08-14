# 敏睿钢铁 Demo 已知问题（KNOWN_ISSUES）

> 与 agileac 同构的坑 + agilesteel 特有。状态：✅ 已解 / 🚧 计划中 / 🟡 演示可过但待完善。

## A1. 9 场景全部四层化 ✅
9 个 Agent `system_prompt` 均为四段式（职责 / RAG / 业务规则 / 输出格式），正文去场景代号，model_alias=`glm-5.2`（真实 id，无别名层）。FIN-01 无 RAG，对账/成本规则在模板 system_prompt 承载。

## A2. mock 镜像在 backend 容器不可见 🟡
`seed_agilesteel_mock_connectors.py` import `mock.core.registry` 需 mock 包。backend 容器镜像未含 mock 源（无 volume 挂载），已用 `docker cp mock/mock ai_infra_backend:/app/mock` 临时注入。**重建 backend 镜像后需重跑该 cp**，或给 backend compose 加 mock volume（计划中）。agileac 同坑。

## A3. embedding provider 需手工同步自 agileac ✅
seed 的 4 家 provider 是占位 key（`PRESET-REPLACE-ME`），无 embedding 能力。已从 agileac org 复制 2 把真实 provider 到 agilesteel：`aliyun-embedding-openai`（text-embedding-v4）+ `aliyun-all-openai`（glm-5.2/deepseek-v4-pro/qwen3.7-plus），含加密 key。GLM/DeepSeek 路由已指向 `aliyun-all-openai`。**重建 backend / 重跑 org seed 后需重跑此复制**（已记入 README §3 维护）。

## A4. seed_agilesteel_rag.py 非幂等 🟡
重跑会按 source 去重跳过已成功；但若曾 ingest 失败（doc status=failed 仍在库），重跑会误跳过。重跑前需先清 failed doc+chunk（见 README §6 清理脚本）。agileac 同坑。

## A5. P0 端到端实测 ✅（9 场景全部在归口用户下跑通）
9 系统 mock + 9 技能 + 9 RAG（embedded）+ 9 agent + 69 本体文件均已落库。**9 场景全部在归口用户终端执行并通过**（run success，done+final，6 trace，tool_call 带真实 args，no-guessing）：

| 场景 | 归口用户 | 任务名（已改名，去「闭环」更真实） | 验证 |
|---|---|---|---|
| MFG-01 | mfg-planner | 转炉终点碳温预测与一体化排产 | 16 tool_call，getHeat(HT2026063001/3002) 精确，15910 字分析 |
| EQP-01 | eqp-engineer | 关键设备预测性维护与备件建议 | 21 tool_call 覆盖 EQM 全 9 端点，新子系统作 bound skill 验证 |
| QAL-01 | qal-engineer | 表面缺陷检测与质量追溯 | DF/HT/P-ST- no-guessing，追溯链 DF→SWO→HT→P-ST-→DF-AS- |
| SCM-01 | scm-buyer | 大宗原料价格预测与供应商风控 | 15 tool_call，SCR-/M-SCR- 前缀转换正确 |
| SAL-01 | sal-ops | 销售需求预测与订单评审交期答复 | ASSO/C-AS-/P-ST- no-guessing |
| FIN-01 | fin-accountant | 分钢种成本核算与多系统对账 | 跨 5 系统，BV-AS-/PC-AS-(heat_no)/ASQ/CL-AS-/ASINV |
| ENE-01 | ene-dispatcher | 能源介质平衡调度与排放预警 | EMS 全端点，EM-/EMS-/EDP 前缀 |
| SAF-01 | saf-inspector | 现场违章识别与隐患排查 | EHS 全端点，HD-/VIO- 前缀，隐患关联 EQ- |
| HR-01 | hr-recruiter | 招聘人岗匹配与培训薪酬 | P-MELT vs P-ST- 不互传，team+org 双 RAG |

注：任务名按用户要求去掉「闭环」等词语、更真实（纯描述名，无场景代号前缀）。generate_docx 由 glm-5.2 自主决定是否调（见 A9）。

## A8. agent_run_events.updated_at 列缺失 ✅（已修）
后端 ORM（TimestampMixin）期望 `agent_run_events.updated_at`，表缺该列致每轮 run 结束 bulk-persist 事件失败（`UndefinedColumnError`），连带 generate_docx 收尾受阻。已 `ALTER TABLE agent_run_events ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now() NOT NULL;` 修复（重启 backend 无需，列已加；属共享后端 schema 修复，agileac/starclothing 同受益）。

## A9. generate_docx 落盘需任务绑 workspace_id ✅（已修）
内置 `generate_docx` 工具（写 .docx 二进制到当前工作空间）**只有当任务 config 绑了 `workspace_id` 才会并入给 LLM 的工具列表**（nodes.py:570 `if workspace_id: tools.extend(_builtin_tool_defs())`）。前端建任务会从 `/terminal/resources` 的 `defaults.workspace_id`（用户个人工作空间）自动填入；若用 curl 直建任务不传 `workspace_id`，则 generate_docx 不在工具列表、agent 无法调、工作空间无 docx（且 `_execute_builtin_tool` 会返回 "no workspace bound"）。
**实测**：9 场景任务绑定归口用户个人 workspace_id 后，全部 `generate_docx=true` + `done=true`，9 个用户工作空间各落 1 份 docx（如排产计划员「转炉终点碳温命中率预测与一体化排产方案_20260630.docx」、设备工程师「预测性维护与备件建议报告_20260629.docx」等，binary=true）。对比 agileac 工作空间有 15 份 docx，机制一致。

## A10. 指南 HTML + 访问页已发布 ✅
《钢铁企业 AI 底座 POC 指南》HTML + 一企业一访问页已生成并发布：
- 指南 `demo/agilesteel/钢铁企业AI底座POC指南.html` → 发布 `agilesteel-poc-guide.html`（业务介绍，零凭证/零用户名/零 terminal-login，已脱敏无需跑 redact_guides.py）
- 访问页 `demo/agilesteel/poc-access.html` → 发布 `agilesteel-poc-access.html`（凭证一企业一页，回链本指南，不引其他租户）
- 截图：18 终端（9 场景×第一屏+末屏，含 docx 附件）+ 16 管理端（org/keys/providers/dlp/workspaces/agents/rag/memory/data-interfaces/skills/ontology/monitor×4）
- 截图脚本 `demo/agilesteel/scripts/guide_capture/capture_terminal.js` + `capture_mgmt.js`
- `publish_guides.sh` 已扩展三租户（starclothing/agileac/agilesteel）互引校验 + AS_USERS
- 对外：https://infra.aievolve.org.cn/guide/agilesteel-poc-guide.html + agilesteel-poc-access.html
- 为敏捷钢铁补建了 admins 表 org_admin 行（mgmt /auth/login 需 Admin 表非 User 表）

## A6. backend 无 mock volume（与 A2 同根）🚧
根治：docker-compose.yml backend 服务加 `volumes: - ../mock/mock:/app/mock:ro`（只读），让 mock 包随源更新。计划中。

## A7. 3 新 mock 域 EQM/EMS/EHS 仅 agilesteel tenant ✅
EQM/EMS/EHS 是钢铁特有 leaf 系统，`SystemDef.tenants=("agilesteel",)`。其余 6 系统含 agilesteel tenant 行。openapi 快照 `mock/openapi/{eqm,ems,ehs}.json` 已重生成（含新 agilesteel 端点 listHeats/listSteelGrades/listScrapGrades 等）。

## 共享后端坑（与 agileac/starclothing 共存）
- #1 path-param 占位符：调 get* 端点须用真实编码，勿传模板占位（见各 terminal_task §5）。
- #2 memory/extract 对中文长文本偏保守：extract 0 facts 非致命（trace 仍计 memory.load）。
- #3 跨 agent 待办未实现：闭环待办由 agent 文本输出，未写跨 agent 待办表。

## 维护清单（重建容器后必做）
1. `docker compose build mock && docker compose up -d mock`（mock 含新 EQM/EMS/EHS）
2. `make mock-export` 或 host `cd mock && python -m mock openapi` 重生成快照（host py3.6 不支持 future annotations，改在 mock 容器内 `docker exec ai_infra_mock python -m mock openapi` 或 host `curl :8010/<sys>/openapi.json`）
3. `docker cp mock/mock ai_infra_backend:/app/mock`（backend 注入 mock 包）
4. 复制 agileac 2 把真实 provider 到 agilesteel（README §3 脚本）
5. 重跑 5 个 seed（org → mock_connectors → ontology → rag → agents）
