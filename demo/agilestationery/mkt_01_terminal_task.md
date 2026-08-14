# MKT-01 竞品动态监测与B端营销物料生成

> 场景文档（7 节）。归口市场营销部·市场分析组，登录用户 `mkt-analyst`。模型 `glm-5.2`，exec_mode `craft`。
> template_agent_id `a54ea1b8-2d19-435c-a3c2-6fcd1d053856`（`agilestationery-mkt-01-competitor-content`）。

## 1. 演示身份
- 组织 slug：`agilestationery`（敏睿文具）
- 用户名：`mkt-analyst` / 密码：`12345678`（统一）
- 角色：member，部门 marketing，团队 mkt-analysis
- template_agent_id：`a54ea1b8-2d19-435c-a3c2-6fcd1d053856`（`agilestationery-mkt-01-competitor-content`）

## 2. 前置条件
- 平台 + mock 网关运行（`docker compose up -d`，mock 含 CHN/CRM）
- 5 个 seed 已跑（org / mock_connectors / ontology / rag / agents）
- glm-5.2 路由指向 `aliyun-all-openai`（真实 key 由 README §3 从 agileac 复制，A3）
- mock health：`curl -H "X-API-Key: chn-agilestationery-demo-key" http://localhost:8010/chn/health` 与 `crm-agilestationery-demo-key`/crm

## 3. 操作步骤
1. 登录 `http://localhost:8000/agilestationery/terminal/login`（mkt-analyst / 12345678）
2. 新建任务
3. TaskConfigDrawer：模型 `glm-5.2` / exec_mode `craft` / 绑定智能体 `竞品动态监测与B端营销物料生成`
4. composer 提示词（贴入）：

```
做竞品动态监测与 B 端营销物料生成，重点 CMP-01（百乐 V5 新品线上加码）、CMP-02（三菱政企集采）。扫所有竞品动态，按品类检索竞品情报与营销物料库给竞品周报 + 中性笔订货会宣讲文案（纯文本）+ 合规初审。

/agilestationery-mkt-chn-query
```

5. 提交运行，观察 SSE

**资源注入表**：

| 项 | 值 |
|---|---|
| template_agent_id | `a54ea1b8-2d19-435c-a3c2-6fcd1d053856` |
| skill_slug | `agilestationery-mkt-chn-query`（dept scope，归口 marketing） |
| RAG collection | 竞品情报与营销物料库（dept） |
| model_alias | `glm-5.2` |
| exec_mode | `craft` |
| scope | dept（marketing） |

## 4. 期望输出
三段分析上屏 + generate_docx：

1. 竞品动态周报（CMP-01/CMP-02 | 厂商 百乐/三菱 | 动态 | 影响 | 应对）
2. 中性笔订货会宣讲文案（纯文本，剔除多模态生成——不生成图片/视频）
3. 合规初审意见（文案合规风险 + 修改建议）

**SSE trace 表（6 类）**：

| trace 类 | 命中内容 |
|---|---|
| template | `load_config` `template:true`（四段 system_prompt 注入） |
| rag | 竞品情报与营销物料库（dept），retriever=vector（非 keyword_fallback） |
| memory | memory.load（+ memory.extract，中文保守 0 facts 非致命，A9） |
| ontology | CHN/CRM identifiers.md + object/link/action types（39 文件中相关域） |
| data_interface | CHN + CRM，5 bound endpoints（A8 path-param 用真实码） |
| skill | `agilestationery-mkt-chn-query` bound（5 endpoints，args 非空） |

## 5. 故障排查
- model not available → 检查 glm-5.2 路由指向 aliyun-all-openai（README §3，A3）
- skill chip 不识别 → 检查 `agilestationery-mkt-chn-query` 技能已绑（管理端技能页）
- tool_call args `{}` → 检查端点 spec 已导入（mock_connectors seed，A1/A2）
- `getCompetitor(CMP-01)` not found → 竞品码写对，path-param 勿用 `{competitor_code}` 占位符（A8）
- CMP-(CHN) 竞品码空间；经销商 DLR-(CRM) 跨查时按 customer_code 关联（A7）
- 营销物料仅纯文本——不调图像/视频生成端点（README §0：剔除多模态生成）
- RAG retriever=keyword_fallback → embedding 未通（A3）
- 无 docx 落盘 → 任务未绑 workspace_id（A6）

## 6. 附：手工调 API 复现
```bash
# 1) 登录取 token
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/users/login-by-slug \
  -H "Content-Type: application/json" \
  -d '{"slug":"agilestationery","username":"mkt-analyst","password":"12345678"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) 创建任务（绑 template_agent_id + 模型 + craft）
TASK=$(curl -sS -X POST http://localhost:8000/api/v1/terminal/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"竞品动态监测与B端营销物料生成","config":{"template_agent_id":"a54ea1b8-2d19-435c-a3c2-6fcd1d053856","skill_ids":[],"model_alias":"glm-5.2","exec_mode":"craft"}}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task=$TASK"

# 3) 运行（SSE 流）
curl -N -X POST "http://localhost:8000/api/v1/terminal/tasks/$TASK/run" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"做竞品动态监测与 B 端营销物料生成，重点 CMP-01（百乐 V5 新品线上加码）、CMP-02（三菱政企集采）。扫所有竞品动态，按品类检索竞品情报与营销物料库给竞品周报 + 中性笔订货会宣讲文案（纯文本）+ 合规初审。","stream":true}'
```

## 7. 验收要点
- [ ] `load_config` event `template:true`（模板注入）
- [ ] 6 类 trace：rag（竞品情报与营销物料库 vector）+ memory.load + ontology（CHN/CRM identifiers）+ data_interface（CHN+CRM）+ skill + memory.extract
- [ ] `tool_call` args 非全 `{}`（listCompetitors/getCompetitor/listChannelPerformance/listOpportunities/listCustomers 带真实 CMP-01/CMP-02/DLR-）
- [ ] no-guessing：竞品 CMP-01/CMP-02、经销商 DLR- 命中正确前缀（A7）
- [ ] RAG retriever=vector（非 keyword_fallback）
- [ ] 输出含三段（竞品周报 + 中性笔 纯文本宣讲文案 + 合规初审）+ generate_docx 附件；不生成多模态
- [ ] 同一 prompt 跑 2 次，第二次 text 字符数不暴跌（稳定性）
