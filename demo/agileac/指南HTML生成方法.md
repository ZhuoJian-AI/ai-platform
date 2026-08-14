# 客户 POC 指南 HTML 生成方法（敏睿空调 agileac）

> 记录敏睿空调 demo 的《空调企业 AI 底座 POC 指南》HTML 网页的生成方法。
> 产出：一个**网页版**指南（不转 PDF），含真实系统截图（终端任务结果 + 管理端功能页）。
> 最终公开链接：`https://infra.aievolve.org.cn/guide/agileac-poc-guide.html`
>
> 复用自 `demo/starclothing/指南HTML生成方法.md` 的通用方法；本文只记录**与星途服装不同的 agileac 专属点**。通用踩坑（vite IPv6 / route 转发 / 两个 aside / exact 匹配 / domcontentloaded）同 starclothing，不重复。

---

## 0. 产出形态与原则

- **交付网页 HTML**（不转 PDF），网页可读性 CSS。
- **截图必须真实**：登录对应归口用户 / 管理员 → 进对应功能页 / 任务页 → 截图。不编造界面。
- **指南只做 POC 业务介绍、不支持验证、不含任何凭证**：终端登录地址、归口用户名、统一密码 `12345678` 全部剥离到**一企业一个独立访问页** `demo/agileac/poc-access.html`（发布为 `https://infra.aievolve.org.cn/guide/agileac-poc-access.html`，星途服装对应 `starclothing-poc-access.html`，两页互不引用）。指南正文**不再以任何形式（含链接）提及访问页**——直接删掉第二章"终端访问方式"callout、§3.8 终端访问信息、附录"访问信息指引"整节、nav/目录里"附录 / 3.8"引用、§3.2 用户管理描述中内嵌的统一密码；只保留企业概况、十一大场景方案描述（含真截图、场景→选模型→选技能→绑定智能体对照表）、第三章管理端配置。**场景介绍（pill / 图注 / 1.3 总览表 / 第二章场景→用户汇总表 / 第三章资源 scope 表 / 场景正文跨智能体交接叙述）一律不出现具体用户名**——图注用"归口用户视图"、对照表去掉"登录用户"列、节点列只留角色名、交接叙述用角色名（如"售后工程师""物流岗用户""应收子任务""培训岗/薪酬岗"）。"场景→归口用户→模型→技能"对照表 + 子任务用户清单（hr-trainer/scm-logistics 等）只放访问页。改指南用 `demo/scripts/redact_guides.py`：从 `git show HEAD:<path>` 读原始指南一次性产出脱敏版（用户名脱敏 + 访问/验证块整块删除），每条替换 assert 命中数、末尾断言无敏感 token 与 `poc-access` 引用残留；改完 `/bin/cp -f` 到 `demo/publish/guide/`（`cp` 被 alias 成 `cp -i` 会跳过覆盖，必须用 `/bin/cp -f`）。注意 starclothing SC-1 行有缺 `</code>` 的历史 typo（脚本按原样匹配）。
- 管理端介绍**参照平台帮助文档** `frontend/src/help/content.ts`，不自创。
- **指南是组织层级的功能介绍，不提超级管理员（super_admin）**：只写管理员（admin）能力与边界，不写超管、不拍超管页（`/org/admins`）。详见 `guide-is-org-level-no-superadmin` 记忆。
- agileac 定位「**员工 vibe working 副驾驶**」——AI 是员工的辅助、不对终端客户直接交互（B3 智能电话客服等对外服务不纳入）。

---

## 1. 前置条件

```bash
# 1) 基础设施 + 后端 + mock 起来
docker compose up -d postgres redis
make dev                       # 后端 127.0.0.1:8000
cd mock && python -m mock      # 或 make mock-up-bg，端口 8010
# 2) agileac 数据已 seed（6 个 seed 脚本按顺序跑，见 demo/agileac/README §9）
# 3) 11 场景终端任务已跑通并落库（每个归口用户名下 title=场景名、task_messages>=2）
# 4) vite dev server 起来
cd frontend && nohup npm run dev > /tmp/vite_dev.log 2>&1 &
#    → 监听 http://[::1]:5173（只听 IPv6 ::1）
# 5) Playwright + chromium 就绪（前端自带 playwright，见 §4 前置）
```

nginx 已对外服务 `infra.aievolve.org.cn`，root = `/root/ai_infra/frontend/dist`，带 SPA fallback（`dist/guide/` 下静态 HTML 可直接访问）。

---

## 2. 数据先读库确认（决定拍哪些页 / 点哪个节点）

agileac org_id：

```bash
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -t -A -c \
 "select id from organizations where slug='agileac';"
# = dc62030b-a622-4937-9179-152f864425f3
```

### 2.1 终端任务：确认 11 场景已完成（title + messages>=2）

```bash
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select u.username, t.title, count(m.id) msgs
from tasks t join users u on u.id=t.user_id
left join task_messages m on m.task_id=t.id
where u.organization_id='dc62030b-a622-4937-9179-152f864425f3' and t.deleted_at is null
group by 1,2 order by 1,2;"
```

> **坑**：task 消息表名是 `task_messages`（不是 `messages`）。sal-ops 名下有两条任务（SAL-01 销售订单回款 + SAL-02 差旅报销），按 title 精确区分；pm-product 名下有 "cancel test" 等未完成任务（msgs=0），按 title 精确选中"产品参数核对与卖点提炼"那条。

11 场景 → 归口用户 → 任务 title 映射（== DB tasks.title）：

| 场景 | 归口用户 | 任务 title |
|---|---|---|
| RND-01 | `rnd-translator` | 多语技术资料翻译与术语统一 |
| PRD-01 | `pm-product` | 产品参数核对与卖点提炼 |
| MFG-01 | `mfg-planner` | 工单进度与产能报表 |
| QAL-01 | `qal-engineer` | 质量数据报表与缺陷闭环 |
| SCM-01 | `scm-buyer` | 供应商评审与采购物流一体化 |
| SAL-01 | `sal-ops` | 销售订单回款与电商退换货 |
| SVC-01 | `svc-engineer` | 售后故障AI诊断与8D闭环 |
| MKT-01 | `mkt-specialist` | 营销内容与培训课件生成 |
| FIN-01 | `fin-accountant` | 多系统对账与应收催办 |
| HR-01 | `hr-recruiter` | 招聘培训薪酬一体化 |
| SAL-02 | `sal-ops` | 差旅报销进度问答 |

### 2.2 管理端各页数据量 + scope 分布（决定左树点哪个节点）

```bash
OID=dc62030b-a622-4937-9179-152f864425f3
# 各类资源计数
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -t -A -c "
select 'dlp',count(*) from dlp_rules where organization_id='$OID'
union all select 'keys',count(*) from api_keys where organization_id='$OID'
union all select 'providers',count(*) from llm_providers where organization_id='$OID' and deleted_at is null
union all select 'workspaces',count(*) from workspaces where organization_id='$OID' and deleted_at is null
union all select 'rag_colls',count(*) from rag_collections where organization_id='$OID' and deleted_at is null
union all select 'data_systems',count(*) from data_systems where organization_id='$OID' and deleted_at is null
union all select 'data_interfaces',count(*) from data_interfaces where deleted_at is null and data_system_id in (select id from data_systems where organization_id='$OID' and deleted_at is null)
union all select 'skill_folders',count(*) from skill_folders where organization_id='$OID' and deleted_at is null
union all select 'ontology_files',count(*) from ontology_files where organization_id='$OID' and deleted_at is null
union all select 'memories',count(*) from memories where organization_id='$OID' and deleted_at is null
union all select 'users',count(*) from users where organization_id='$OID';"
# 实测：dlp=9 keys=16 providers=3 workspaces=52 rag=9 data_systems=6 data_interfaces=101
#       skill_folders=10 ontology_files=50 memories=14 users=17
```

> **agileac 与 starclothing 的关键差异：资源按 scope 分级，不按部门复制。** starclothing 把 13 套系统按归口部门各复制一份；agileac 的 6 套 mock 系统**统一建在组织级**（一把 mock API Key 全租户用），部门级**技能**只绑本部门授权的端点子集——同一套端点，不同部门技能绑不同子集。故管理端左树点选的归口节点与 starclothing 完全不同（见 §4.3 表）。

scope 分布查询（找哪个节点有数据）：

```bash
OID=dc62030b-a622-4937-9179-152f864425f3
# 各资源 scope_type 分布（join dept/team/user 名）
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select 'dlp' r, r.scope_type, count(*) from dlp_rules r where r.organization_id='$OID' group by 1,2
union all select 'rag', c.scope_type, count(*) from rag_collections c where c.organization_id='$OID' and c.deleted_at is null group by 1,2
union all select 'skills', sf.scope_type, count(*) from skill_folders sf where sf.organization_id='$OID' and sf.deleted_at is null group by 1,2
union all select 'systems', s.scope_type, count(*) from data_systems s where s.organization_id='$OID' and s.deleted_at is null group by 1,2
union all select 'ontology', ofi.scope_type, count(*) from ontology_files ofi where ofi.organization_id='$OID' and ofi.deleted_at is null group by 1,2
union all select 'memory', m.scope_type, count(*) from memories m where m.organization_id='$OID' and m.deleted_at is null group by 1,2
order by 1,2;"
```

agileac 实测分布（决定节点选择）：

| 资源 | scope 分布 | 含义 |
|---|---|---|
| DLP 9 条 | 全 organization | 点 org 节点 |
| RAG 9 个 | 6 dept + 2 team + 1 org | 点 dept 节点（如售后服务部） |
| 技能 10 个 | 全 department（11 部门除 IT） | 点 dept 节点 |
| 数据系统 6 套 | 全 organization | 点 org 节点（唯一有数据的节点） |
| 本体 50 文件 | 34 organization + 12 dept + 4 team | 点 org 节点（数据最丰富） |
| 工作空间 52 | org/dept/team/user 各级 | 点 user 节点（有文件的归口用户） |
| 记忆 14 | 全 user | **必须点 user 节点**（仅 user scope） |

### 2.3 admin 是否 org-scoped（决定要不要手点 OrgSelect）

```bash
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
 "select username, role, organization_id from users where username='admin' and organization_id='dc62030b-a622-4937-9179-152f864425f3';"
```

agileac admin 是 org_admin（绑 organization_id）→ `isOrgScoped()` 真 → OrgSelect 渲染成不可点 Tag 且自动锁敏睿空调组织，无需手点 OrgSelect（同 starclothing）。树会自动加载。

---

## 3. RAG 重复清理（agileac 专属，生成指南前必做）

> **`seed_agileac_rag.py` 非幂等**：重跑会造 **3 倍同名 RAG collection**（slug 随机生成不查重，chunks 也跟着翻 3 倍）。表现为 RAG 页每个节点下出现 3 个同名知识库、`count(*)=25` 而非设计的 9。指南前必须清理，否则截图显示 3 个重复知识库、数量与 README 设计不符。

### 3.1 确认重复 + 找 agent 引用的 collection id

```bash
OID=dc62030b-a622-4937-9179-152f864425f3
# 每个 (name,scope) 几个副本
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select c.scope_type, coalesce(d.name,t.name,'敏睿空调(org)') node, c.name, count(*) dupes
from rag_collections c left join departments d on d.id=c.scope_id::uuid left join teams t on t.id=c.scope_id::uuid
where c.organization_id='$OID' and c.deleted_at is null group by 1,2,3 order by 1,2,3;"
# 若每个 (name,scope) dupes>1 → 有重复

# agent 引用的 collection id（注意列名是单数 rag_collection_id，不是 ids）
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select a.slug, a.rag_collection_id from agents a
where a.organization_id='$OID' and a.rag_collection_id is not null order by 1;"
# 8 个 agent 各引用 1 个 collection（HR-01 培训制度子任务靠 org 级员工综合库 auto-load，不在此列）
```

### 3.2 清理：每个 (name,scope_type,scope_id) 保留 1 个，优先保留 agent 引用的

```bash
OID=dc62030b-a622-4937-9179-152f864425f3
# 把下面 8 个 UUID 换成 §3.1 查出的 agent 引用 id
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
WITH ranked AS (
  SELECT id,
    row_number() OVER (
      PARTITION BY name, scope_type, coalesce(scope_id,'')
      ORDER BY (id IN ('<agent-ref-uuid-1>','<agent-ref-uuid-2>',...)) DESC, created_at
    ) rn
  FROM rag_collections
  WHERE organization_id='$OID' AND deleted_at IS NULL
)
DELETE FROM rag_collections WHERE id IN (SELECT id FROM ranked WHERE rn > 1);"
```

> **关键约束**：`rag_chunks` 无 `deleted_at` 列、且 FK `rag_chunks_collection_id_fkey` 是 `ON DELETE CASCADE`，所以**只能 hard-delete collection**（chunks 随之级联删）；不能用软删除（软删 collection 会留 orphan chunks）。**必须保留 agent 引用的 collection**（`agents.rag_collection_id` FK 是 `ON DELETE SET NULL`，删了 agent 的 RAG 检索会挂）。清理后 25 → 9 个，与 README §6.1 设计一致。
>
> 清理是可重建的（重跑 `seed_agileac_rag.py` 会再加），不影响 11 场景可复现性。

---

## 4. 截图脚本（Playwright，3 个脚本）

> 运行方式：`cd frontend && NODE_PATH=$PWD/node_modules node <script>.js`
> 前端自带 `playwright`；chromium 首次需 `npx playwright install chromium` + 运行依赖 + CJK 字体（`google-noto-sans-cjk-ttc-fonts`）。
> 三个脚本在 `demo/agileac/scripts/guide_capture/`：
> `capture_terminal.js` / `capture_mgmt_nodes.js` / `capture_mgmt_extra.js`

### 4.1 通用片段（所有脚本共用，详见 starclothing 方法 §4.1）

- `WEB='http://[::1]:5173'`，`API='http://127.0.0.1:8000'`，`SLUG='agileac'`，`PASS='12345678'`。
- 登录：终端用户 `POST /api/v1/users/login-by-slug` → `ai_infra_user_token`/`ai_infra_user`；admin `POST /api/v1/auth/login` → `ai_infra_token`/`ai_infra_admin`。`ctx.addInitScript` 导航前注入。
- **`ctx.route('**/api/v1/**', ...)`** 把 SPA 的 `/api/v1` 直转 `127.0.0.1:8000`，绕开 vite 坏代理 + IPv6 问题。route 模式必须 `**/api/v1/**`，**不能** `**/api/**`（会拦 `/src/api/client.ts` 源码 → 404 → SPA API 客户端加载失败 → 任务列表空）。
- 导航用 `waitUntil:'domcontentloaded'` + 等关键文本；别用 networkidle（vite HMR 长连接永不 idle）。

### 4.2 终端任务截图（capture_terminal.js）

11 场景，每场景**第一屏 + 最后一屏**两张（除 PRD-01）：

```js
const SCEN = [
  { key:'rnd01', user:'rnd-translator', title:'多语技术资料翻译与术语统一' },
  { key:'prd01', user:'pm-product',    title:'产品参数核对与卖点提炼' },
  { key:'mfg01', user:'mfg-planner',   title:'工单进度与产能报表' },
  { key:'qal01', user:'qal-engineer',  title:'质量数据报表与缺陷闭环' },
  { key:'scm01', user:'scm-buyer',     title:'供应商评审与采购物流一体化' },
  { key:'sal01', user:'sal-ops',       title:'销售订单回款与电商退换货' },
  { key:'svc01', user:'svc-engineer',  title:'售后故障AI诊断与8D闭环' },
  { key:'mkt01', user:'mkt-specialist',title:'营销内容与培训课件生成' },
  { key:'fin01', user:'fin-accountant',title:'多系统对账与应收催办' },
  { key:'hr01',  user:'hr-recruiter',  title:'招聘培训薪酬一体化' },
  { key:'sal02', user:'sal-ops',       title:'差旅报销进度问答' },
];
// getByText(title,{exact:false}).first() → click 打开任务（回放已持久化 messages，无需重跑）
// setMsgScroll(true) → 截 _top.png（第一屏：入口+composer+首条消息）
// setMsgScroll(false) → 截 .png fullPage（最后一屏：最终输出+闭环待办）
```

> **`setMsgScroll`**（找含 `.wb-md` 的 `overflowY:auto` 容器滚顶/底）同 starclothing——终端消息区是内层 scroll 容器，`fullPage:true` 抓不到被滚走的内容；任务点开时自动 smooth-scroll 到底，故默认截到的就是最后一屏，要补第一屏需手动滚到顶再 viewport 截图（不 fullPage）。
>
> **PRD-01 专属坑**：该场景输出较短，消息区一屏放得下，`_top` 与 last 的 md5 相同（11 场景中唯一）→ HTML 里该场景只放 1 张图 + 注「首末屏一致」。跑完用 `md5sum <key>_top.png <key>.png` 比对，相同者只放一张。

### 4.3 管理端截图（capture_mgmt_nodes.js + capture_mgmt_extra.js + capture_agents.js，共 16 张）

> **agileac 要 16 张 mgmt 图，不是 starclothing 的 8 张**。starclothing 的 `capture_mgmt_nodes.js` 只拍 8 页，但 starclothing HTML 有 ~15 张（org-structure/users/keys/providers/monitor-overview/agents/tools 由更早的临时脚本拍）。agileac 需跑三个脚本：`capture_mgmt_nodes.js`（8 张树型页）+ `capture_mgmt_extra.js`（7 张 org/keys/providers/monitor 页）+ `capture_agents.js`（1 张智能体页），否则 §3.2/§3.3/§3.4 智能体/§3.6 缺图。
>
> **注意**：`/agent/agents`（智能体）页在 agileac 是**可见菜单**（label「智能体」），与 starclothing 把智能体/测试广场/Judge 标 hidden 不同——agileac 已配 11 个业务智能体故启用该页。

**agileac 管理端节点选择表（与 starclothing 完全不同，按 §2.2 scope 分布定）：**

| 页面 | 路由 | 点选节点 | 节点类型 | DB 依据 |
|---|---|---|---|---|
| 安全围栏 | `/dlp` | 敏睿空调 | organization | 9 条全 org scope |
| 工作空间 | `/agent/workspaces` | 售后工程师 | user（svc-engineer） | workspaces user 级有文件 |
| RAG 知识库 | `/agent/rag` | 售后服务部 | department | 售后故障与维修知识库（P0 场景归口） |
| 长期记忆 | `/agent/memory` | 售后工程师 | user（svc-engineer） | memory **仅 user scope**，必须点用户节点 |
| 数据接口 | `/tools/data-interfaces` | 敏睿空调 | organization | 6 系统全 org scope（唯一有数据的节点） |
| 技能 | `/tools/skills` | 售后服务部 | department | 售后部查询技能（P0 场景归口） |
| 本体 | `/tools/ontology` | 敏睿空调 | organization | 34 文件 / 7 文件夹（数据最丰富） |
| 智能体 | `/agent/agents` | 售后服务部 | department | 11 agent 全部门级，售后服务部有售后故障诊断（P0 场景归口）；销售部 2 个 |
| 路由器监控 | `/monitor/router` | （点「路由指标」tab） | — | 非树型页 |
| 组织架构 | `/org/structure` | （非树型，直接截） | — | extra 脚本 |
| 用户管理 | `/org/users` | （非树型，直接截） | — | extra 脚本 |
| API Key | `/keys` | 敏睿空调 | organization | 16 key 分布 org/dept/team，org 有默认 key |
| 模型提供商 | `/providers` | 敏睿空调 | organization | 3 provider 全 org scope |
| 监控总览 | `/monitor/overview` | （非树型，直接截） | — | extra 脚本 |
| 智能体监控 | `/monitor/agents` | （非树型，直接截） | — | extra 脚本 |
| 工具监控 | `/monitor/tools` | （非树型，直接截） | — | extra 脚本 |

**同 starclothing 的三个坑（同套 SPA，不变）**：
1. 页面有**两个 `<aside>`**——第 1 个全局导航菜单，第 2 个才是 FinderShell 组织架构树。`page.locator('aside').nth(1)`，**不能** `.first()`。
2. agileac admin 是 org_admin → `isOrgScoped()` 真 → OrgSelect 自动锁敏睿空调，无需手点（若用 super_admin 登录则 OrgSelect 是下拉需先选组织）。
3. `getByText(label,{exact:true})` **exact 必须开**，否则「售后服务部」命中「售后工程师组」、「售后工程师」命中「售后工程师组」。树节点 user 显示 **display_name**（售后工程师=svc-engineer），不是 username；team 显示 team name（售后工程师组）。

```js
// capture_mgmt_nodes.js 的 PAGES（8 张树型/路由页）
const PAGES = [
  ['/dlp',                   'dlp',                   '敏睿空调'],
  ['/agent/workspaces',      'agent-workspaces',      '售后工程师'],
  ['/agent/rag',             'agent-rag',             '售后服务部'],
  ['/agent/memory',          'agent-memory',          '售后工程师'],
  ['/tools/data-interfaces', 'tools-data-interfaces', '敏睿空调'],
  ['/tools/skills',          'tools-skills',          '售后服务部'],
  ['/tools/ontology',        'tools-ontology',        '敏睿空调'],
  ['/monitor/router',        'monitor-router',        null],   // 点 路由指标 tab
];
// capture_mgmt_extra.js 的 PAGES（7 张 org/keys/providers/monitor 页）
const PAGES = [
  ['/org/structure',   'org-structure',   null],
  ['/org/users',        'org-users',        null],
  ['/keys',             'keys',             '敏睿空调'],
  ['/providers',        'providers',        '敏睿空调'],
  ['/monitor/overview', 'monitor-overview', null],
  ['/monitor/agents',   'monitor-agents',   null],
  ['/monitor/tools',    'monitor-tools',    null],
];
async function clickTreeNode(page, label){
  const aside = page.locator('aside').nth(1);
  const node = aside.getByText(label, { exact: true }).first();
  await node.waitFor({ state:'visible', timeout:15000 });
  await node.click({ timeout:3000 });
}
// 每页：goto domcontentloaded → waitForTimeout(2800)（等 OrgSelect 锁组织+树渲染）
//       → 若 nodeText：clickTreeNode + waitForTimeout(2500)（等右栏按 scope 取数）
//       → 若 /monitor/router：点「路由指标」tab
//       → fullPage screenshot
```

---

## 5. 第三章五张资源清单表（读库生成，数量不写死）

> 列按用户指定：智能体=(组织节点, 智能体, slug, RAG)；RAG=(组织节点, 知识库, 文件夹/文档)；数据接口=(组织节点, 系统, 数据接口)；技能=(组织节点, 技能)；本体=(组织节点, 文件夹, 本体文件)。**数量一律取实测 count**（§2.2），改数据后重跑查询刷新。

```bash
OID=dc62030b-a622-4937-9179-152f864425f3
# RAG：组织节点 / 知识库 / 文档（rag_documents 有 title，无 name 列）
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,t.name,'敏睿空调(org)') node, c.name coll,
       string_agg(doc.title,' · ' order by doc.title) docs, count(doc.*) n
from rag_collections c
left join departments d on d.id=c.scope_id::uuid left join teams t on t.id=c.scope_id::uuid
left join rag_documents doc on doc.collection_id=c.id and doc.deleted_at is null
where c.organization_id='$OID' and c.deleted_at is null group by 1,2 order by 1,2;"

# 数据接口：组织节点 / 系统 / 端点（data_interfaces 自身无 scope，靠 data_systems join）
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,t.name,'敏睿空调(org)') node, s.name system,
       count(i.*) n, string_agg(i.name,' · ' order by i.path) endpoints
from data_systems s join data_interfaces i on i.data_system_id=s.id
left join departments d on d.id=s.scope_id::uuid left join teams t on t.id=s.scope_id::uuid
where s.organization_id='$OID' and s.deleted_at is null and i.deleted_at is null
group by 1,2 order by 1,2;"

# 技能：组织节点 / 技能文件夹
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,t.name,'敏睿空调(org)') node, sf.name skill
from skill_folders sf
left join departments d on d.id=sf.scope_id::uuid left join teams t on t.id=sf.scope_id::uuid
where sf.organization_id='$OID' and sf.deleted_at is null order by 1,2;"

# 本体：组织节点 / 文件夹 / 文件（ontology_files 无 folder_id，path='folder/file'）
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select ofi.scope_type, coalesce(d.name,t.name,'敏睿空调(org)') node,
       split_part(ofi.path,'/',1) folder,
       string_agg(split_part(ofi.path,'/',2),' · ' order by ofi.path) files, count(*) n
from ontology_files ofi
left join departments d on d.id=ofi.scope_id::uuid left join teams t on t.id=ofi.scope_id::uuid
where ofi.organization_id='$OID' and ofi.deleted_at is null
group by 1,2,3 order by 1,2,3;"

# 智能体：组织节点 / 智能体名 / slug / 是否绑 RAG
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,t.name,u.display_name,'敏睿空调(org)') node, a.name, a.slug,
       (case when a.rag_collection_id is not null then '有' else '-' end) rag
from agents a
left join departments d on d.id=a.scope_id::uuid left join teams t on t.id=a.scope_id::uuid left join users u on u.id=a.scope_id::uuid
where a.organization_id='$OID' and a.deleted_at is null order by 1,2;"
```

agileac 五张表实测（清理 RAG 后）：

- **智能体（11 个 dept 级）**：研发部·多语技术翻译 / 产品部·产品参数核对 / 生产制造部·工单产能报表 / 质量部·质量数据报表 / 供应链部·供应商评审 / 销售部·销售订单回款+差旅报销问答(2) / 售后服务部·售后故障诊断 / 市场部·营销内容生成 / 财务部·财务对账催办 / 人力资源部·招聘培训薪酬；8 个绑 RAG、3 个无（MFG/SAL-01/FIN）
- **RAG（9 个）**：研发翻译组·多语术语与海外资料库(2 文档) / 产品部·产品参数与卖点库(3) / 质量部·质量缺陷案例库(6) / 供应链部·供应商资质与历史表现库(3) / 售后服务部·售后故障与维修知识库(3) / 市场部·营销与竞品情报库(4) / 招聘组·岗位JD与简历评估库(2) / 人力资源部·员工制度知识库(3) / 敏睿空调(org)·员工综合知识库(5)
- **数据接口（6 套 org 级系统 / 101 端点）**：PLM(24) / SCM(16) / ERP(16) / MES(14) / CRM(14) / HRM(17)，全敏睿空调(org) 节点
- **技能（10 个 dept 级）**：11 归口部门除 IT（IT 作平台运维方不设对外技能），每部 1 个查询技能
- **本体（11 文件夹 / 50 文件）**：org 级 7 文件夹（PLM/SCM/ERP/MES/CRM/HRM 各 5 + Cross 4 无 identifiers）+ dept 3 文件夹（hr/after-sales/marketing 各 4）+ team 1 文件夹（rnd-translation 4）

> agileac 数据接口表与 starclothing 形态不同：starclothing 是 13 套部门级系统副本（每行不同节点）；agileac 是 6 套 org 级系统（节点列都是敏睿空调），正文配「6 套系统组织级共享、部门级技能只绑端点子集」说明，**不要**写成按部门复制。

---

## 6. HTML 网页版样式

源文件：`demo/agileac/空调企业AI底座POC指南.html`。结构：封面 → 目录 → 第一章企业概况痛点 → 第二章 11 场景（终端真截图）→ 第三章管理端（16 张真截图 + 五张清单表）→ 附录。

CSS 直接复用 starclothing（`demo/starclothing/服装企业AI底座POC指南.html` 的 `<style>` 块）；agileac 把主色从 starclothing 的蓝（`#1677ff`）调成青色系（`#0e7490` / `#22d3ee`）以呼应空调行业，结构/类名/响应式/print 兜底全沿用。agileac 额外加两类：`.pill.purple`（紫药丸，曾用于 pill 行标智能体，现已弃用但 CSS 留着无害）+ `.agentline`（紫渐变 + 左边框的醒目徽章，用于提示词区「绑定智能体」）。

- 章节加 `id`（cover→top、toc、ch1/ch2/ch3/appendix）供锚点跳转；吸顶 `.topnav` + 返回顶部按钮 + scroll 监听显隐。
- 截图 `.realshot{width:100%;border-radius;box-shadow}`；图注 `.cap` 居中。
- 11 场景每节用 `.grid2`（左：pills+lead+composer prompt / 右：输出结构）+ 2 张 `<img class="realshot">`（PRD-01 只 1 张）。
- composer 提示词用 `.prompt`（深色块 + `composer` label），直接从 `SCENARIO_ROSTER.md` 各场景章节复制。
- **每个场景的提示词 callout 内放醒目「绑定智能体」徽章**：在 `<h5>提示词…</h5>` 与 `<div class="prompt">` 之间插 `<div class="agentline"><b>绑定智能体：</b>智能体名</div>`，用紫渐变 + 左边框的 `.agentline` 样式（区别于 pill / prompt，落在视觉焦点）。**只写智能体名（如「售后故障诊断」），不写 slug**——slug 仅放章末「客户自助验证方式」表的「绑定智能体」列（与登录用户/选模型/选技能并列）。智能体名取自 `agents.name`（按场景章节顺序 11 个，见 §5 智能体清单）。曾试过放 pill 行里的紫色「智能体：名」标签，反馈是「不够明显」，故移到提示词区做醒目徽章。
- §3.4 智能体平台子节顺序：工作空间 → **智能体**（插在 RAG 前，含 11 agent 清单表 + 截图）→ RAG 知识库 → 长期记忆。插入智能体节后，其后所有图号 +1（RAG 起 3-8 … 工具监控 3-16）。
- **终端模型写 `glm-5.2`（真实模型 id）**——agileac 终端下拉直接列真实 id、无别名层（区别于 starclothing 的 glm/smart/balanced 别名）。

---

## 7. 发布到公开链接

```bash
DIST=/root/ai_infra/demo/publish/guide   # 已从 frontend/dist/guide 迁出（vite emptyOutDir 会清空 dist，见 starclothing 文档 §6）
mkdir -p "$DIST/shots/agileac/mgmt"
bash demo/scripts/publish_guides.sh   # 发布四件套（2 指南 + 2 访问页），含不变量校验，绑定同步、不可只发其一
/bin/cp -f demo/agileac/shots/*.png "$DIST/shots/agileac/"                                # 终端截图
/bin/cp -f demo/agileac/shots/mgmt/*.png "$DIST/shots/agileac/mgmt/"                     # 管理端截图
chmod -R a+rX "$DIST"
# 验证
curl -s -o /dev/null -w "%{http_code}\n" https://infra.aievolve.org.cn/guide/agileac-poc-guide.html        # 200
curl -s -o /dev/null -w "%{http_code}\n" https://infra.aievolve.org.cn/guide/shots/agileac/svc01.png       # 200
curl -s -o /dev/null -w "%{http_code}\n" https://infra.aievolve.org.cn/guide/shots/agileac/mgmt/dlp.png    # 200
curl -s -o /dev/null -w "%{http_code}\n" https://infra.aievolve.org.cn/agileac/terminal/login             # 200（终端 SPA 路由可达）
```

- HTML 用**相对路径** `shots/agileac/...` `shots/agileac/mgmt/...`（**按租户命名空间**，避免与 starclothing 指南共用 `dist/guide/shots/` 时同名管理页截图互相覆盖），随 HTML 一起拷到 `dist/guide/`。
- ASCII 文件名 `agileac-poc-guide.html`（中文文件名 URL 要 percent-encode，不便）。
- 改动后重新 cp 即可刷新；浏览器 Ctrl+F5 清缓存。
- 该副本是**临时查看副本**，源文件在 `demo/agileac/`；前端重新 build（`npm run build`）会清空 `dist/`，届时需重发。

---

## 8. 完整流程速查

1. 起服务：docker（pg/redis/backend）+ mock + `cd frontend && nohup npm run dev`。
2. 读库（§2）：确认 11 终端任务已完成、各管理页有数据、各资源绑在哪个 scope 节点；查 admin 是否 org-scoped。
3. **清理 RAG 重复（§3）**：agileac 专属，`seed_agileac_rag.py` 非幂等会造 3 倍 collection，按 (name,scope) 保留 agent 引用的那个，hard-delete 其余。
4. 装工具：`npx playwright install chromium` + 运行依赖 + CJK 字体。
5. 截图（§4）：`capture_terminal.js`（11 场景，第一屏+最后一屏，PRD-01 单图）+ `capture_mgmt_nodes.js`（8 张树型页）+ `capture_mgmt_extra.js`（7 张 org/keys/providers/monitor 页）+ `capture_agents.js`（1 张智能体页）= 16 张 mgmt 图 → 输出 `demo/agileac/shots/`。
6. 写 HTML（§6）：复用 starclothing CSS（青色主色）；§3.4/§3.5 五张清单表（智能体/RAG/数据接口/技能/本体）读库生成（§5）、数量不写死；§3.4 智能体节插在 RAG 前；管理端介绍参照 `content.ts`；组织层级口径、不提 super_admin；模型写 `glm-5.2`。
7. 发布（§7）：cp 到 `frontend/dist/guide/` → 给客户 `https://infra.aievolve.org.cn/guide/agileac-poc-guide.html`。

## 9. 与 starclothing 方法的差异汇总

| 维度 | starclothing | agileac |
|---|---|---|
| 行业 | 服装 | 家用+商用空调全产业链 |
| 场景数 | 7（PD1~3 + SC1~4） | 11（按 11 部门边界） |
| 资源 scope | 全组织级（按部门复制系统副本） | **分级 org/dept/team**（6 系统 org 共享、技能 dept 级绑端点子集） |
| RAG | 1 个（组织级） | 9 个（1 org + 6 dept + 2 team），**seed 非幂重要清理** |
| 本体 | 12（3 域 × 4，组织级） | 50（6 域 + Cross org 级 + 4 部门/团队级） |
| 终端模型 | glm/smart/balanced 别名 | **glm-5.2 真实 id（无别名层）** |
| mgmt 截图数 | ~15（8 由 capture_mgmt_nodes + 余由临时脚本） | 16（capture_mgmt_nodes 8 + capture_mgmt_extra 7 + capture_agents 1） |
| mgmt 节点选择 | 数据接口/技能/本体点不同**部门**节点 | 数据接口/本体点**组织**节点、RAG/技能点**部门**节点、记忆/工作空间点**用户**节点 |
| 终端首末屏 | 每场景 2 张 | 每场景 2 张，**PRD-01 输出短只 1 张** |
| 指南定位 | 业务流程演示 | 员工 vibe working 副驾驶（不对客户直接交互） |
| 通用踩坑 | vite IPv6 / route `**/api/v1/**` / 两个 aside / exact 匹配 / domcontentloaded | **同套适用**（同 SPA） |

> 通用的 vite IPv6 / route 转发 / 两个 aside / exact 匹配 / domcontentloaded / 登录端点 token 存储 等踩坑，详见 `demo/starclothing/指南HTML生成方法.md` §3，本文不重复。
