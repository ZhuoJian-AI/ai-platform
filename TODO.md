# 待办与二期开发计划

本文件记录尚未交付或已暂缓的功能项。已完成项可归档至历史记录。

## 工具连接器

管理端「连接器」已恢复，用于创建企业系统连接、手工维护或从 OpenAPI Spec 导入端点、测试真实 HTTPS 调用，并把选中的端点发布为组织级 Skill 供聊天智能体调用。

新菜单「数据接口」（[DataInterfaces.tsx](frontend/src/pages/tools/DataInterfaces.tsx)）采用**独立数据结构**（`data_systems` + `data_interfaces`，节点作用域化），与连接器解耦；页面仅启用/禁用 + 搜索 + 查看输入输出样例，创建/编辑/删除由后端 API 录入（暂不暴露 UI）。

- [ ] 为「数据接口」补一个录入入口（独立页或超管页），供系统/接口的创建/编辑/删除。
- [ ] 评估是否清理 dormant 的旧 `ontologies`(JSONB) / `skills`(definition) 表（已被文件化存储取代，详见 [本体/技能文件化改造](llm_router/backend/alembic/versions/) 0018/0019/0020 迁移）。

## 二期开发内容（智能体平台二级菜单暂缓项）

以下三项在管理端「智能体平台」中已暂时隐藏于二级菜单，对应页面与路由保留，待二期完善后再行启用。
启用方式：移除 [frontend/src/App.tsx](frontend/src/App.tsx) 中对应菜单项的 `hidden: true` 标记即可。

| 菜单项 | 路由 | 页面文件 | 说明 |
| --- | --- | --- | --- |
| 智能体 | `/agent/agents` | [frontend/src/pages/agent/Agents.tsx](frontend/src/pages/agent/Agents.tsx) | 智能体编排与配置管理 |
| 测试广场 | `/agent/playground` | [frontend/src/pages/agent/AgentPlayground.tsx](frontend/src/pages/agent/AgentPlayground.tsx) | 智能体在线调试与评测 |
| Judge 模板 | `/agent/judges` | [frontend/src/pages/agent/Judges.tsx](frontend/src/pages/agent/Judges.tsx) | 评测 Judge 模板管理 |

### 启用检查清单
- [ ] 确认后端 API（智能体 / Playground / Judge）接口稳定
- [ ] 完成前端页面与帮助文档（[content.ts](frontend/src/help/content.ts) / [content_org_admin.ts](frontend/src/help/content_org_admin.ts)）的内容校对
- [ ] 同步更新用户手册（[docs/](docs/)）
- [ ] 移除 `hidden: true` 并回归验证菜单展示与路由跳转
