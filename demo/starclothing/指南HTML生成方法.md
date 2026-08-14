# 客户 POC 指南 HTML 生成方法

> 记录星途服装 demo 的《服装企业 AI 底座 POC 指南》HTML 网页的生成方法，供其他 demo 项目（如 agileac）参考复用。
> 产出：一个**网页版**指南（不再转 PDF），含真实系统截图（终端任务结果 + 管理端功能页）。
> 最终公开链接：`https://infra.aievolve.org.cn/guide/starclothing-poc-guide.html`

---

## 0. 产出形态与原则

- **交付网页 HTML**（不转 PDF）。样式按"网页可读性"设计，不再用 A4/分页打印导向。
- **截图必须真实**：登录对应归口用户/管理员 → 进对应功能页/任务页 → 截图。不编造界面。
- **指南只做 POC 业务介绍、不支持验证、不含任何凭证**：终端登录地址、归口用户名、统一密码 `12345678` 全部剥离到**一企业一个独立访问页** `demo/starclothing/poc-access.html`（发布为 `https://infra.aievolve.org.cn/guide/starclothing-poc-access.html`，敏睿空调对应 `agileac-poc-access.html`，两页互不引用）。指南正文**不再以任何形式（含链接）提及访问页**——直接删掉第二章"终端访问方式"callout、§3.8 终端访问信息、附录"访问信息指引"整节、nav/目录里"附录 / 3.8"引用、§3.2 用户管理描述中内嵌的统一密码；只保留企业概况、七大场景方案描述（含真截图、场景→选模型→选技能对照表）、第三章管理端配置。**场景介绍（pill / 图注 / 1.3 总览表 / 第二章场景→用户汇总表 / 第三章资源 scope 表 / 场景正文跨智能体交接叙述）一律不出现具体用户名**——图注用"归口用户视图"、对照表去掉"登录用户"列、节点列只留部门/角色名、交接叙述用角色名。"场景→归口用户→模型→技能"对照表只放访问页。改指南用 `demo/scripts/redact_guides.py`：从 `git show HEAD:<path>` 读原始指南一次性产出脱敏版（用户名脱敏 + 访问/验证块整块删除），每条替换 assert 命中数、末尾再断言无敏感 token 与 `poc-access` 引用残留；改完 `/bin/cp -f` 到 `demo/publish/guide/`（注意 `cp` 被 alias 成 `cp -i` 会跳过覆盖，必须用 `/bin/cp -f`）。
- 管理端介绍**参照平台帮助文档** `frontend/src/help/content.ts`（按"使用功能"层面组织的逐页说明），不自创。
- **指南是组织层级的功能介绍，不提超级管理员（super_admin）内容**：客户拿到的是自己组织的 POC 视角，超管（平台级、跨组织、管理管理员账号）不归他们管。角色描述只写管理员（admin）——可管理本组织的组织架构、API Key、安全规则、智能体、工具等资源，**但不能管理管理员账号**；不可删除自己、不可降级自己。**不**写「两个管理员角色：超管可管理一切…」这类把 super_admin 与 admin 并列的句子；**不**写「多数页面需先在顶部选择组织再操作」（org admin 组织已锁定，顶部蓝色标签展示本组织名，查询自动限定本组织）；**不**拍超管专属页（如 `/org/admins` 管理员管理）。注：`frontend/src/help/content_org_admin.ts` 内部帮助里大量出现「超管/超级管理员」字样（向 org_admin 解释其边界时引用），那是内部帮助、**不要照搬进指南正文**，只保留 org admin 的能力与边界。

---

## 1. 前置条件

```bash
# 1) 基础设施 + 后端 + mock 起来
docker compose up -d postgres redis
make dev            # 后端 127.0.0.1:8000
cd mock && python -m mock   # 或 make mock-up-bg，端口 8010
# 2) 数据已 seed（按 demo 的 seed 脚本顺序执行）
# 3) vite dev server 起来（提供管理端/终端 SPA）
cd frontend && nohup npm run dev > /tmp/vite_dev.log 2>&1 &
#    → 监听 http://[::1]:5173  （注意：只听 IPv6 ::1，见 §3 踩坑）
# 4) Playwright + chromium 已就绪（前端自带 playwright，见 §3）
```

nginx 已对外服务 `infra.aievolve.org.cn`，root = `/root/ai_infra/frontend/dist`，带 SPA fallback `try_files $uri $uri/ /index.html`（文件存在就直接返回，所以放到 `dist/guide/` 下的静态 HTML 可直接访问）。

---

## 2. 数据先读库确认（决定拍哪些页/点哪个节点）

拍前先查库，确认每个功能页**有数据**、终端任务**已完成**、管理端左树**哪个节点有数据**：

```bash
# 终端任务：每个归口用户名下的任务标题=场景名、且 messages>=2（用户提示词+助手结果）
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
 "select u.username, t.title, count(m.*) msgs from tasks t join users u on u.id=t.user_id
  where u.username in ('dev-lead','fabric-dev',...) and t.deleted_at is null group by 1,2;"

# 管理端各页数据量
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -t -A -c \
 "select 'providers',count(*) from llm_providers where deleted_at is null
  union all select 'dlp',count(*) from dlp_rules
  union all select 'keys',count(*) from api_keys
  union all select 'workspaces',count(*) from workspaces where deleted_at is null
  union all select 'rag',count(*) from rag_collections where deleted_at is null
  union all select 'data_interfaces',count(*) from data_interfaces where deleted_at is null
  union all select 'skills',count(*) from skill_folders where deleted_at is null
  union all select 'ontology_files',count(*) from ontology_files where deleted_at is null;"

# API Key 绑定在哪个节点（决定截图点哪个组织树节点）
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c \
 "select scope_type, coalesce(department_id::text,'-'), coalesce(team_id::text,'-'), count(*)
  from api_keys where organization_id='<org_id>' group by 1,2,3;"
```

> 关键：**带数据的页才拍**；左树型页面（API Key/提供商/DLP/工作空间/RAG/记忆/数据接口/技能/本体）要**点选有数据的组织树节点**再截图，否则右栏空。

### 2.1 生成第三章四张资源清单表（RAG / 数据接口 / 技能 / 本体）

第三章 §3.4（RAG）、§3.5（数据接口/技能/本体）每节正文后，要插一张**「星途服装 ×× 清单」表**，把该类资源按"组织节点 → 子项 → 子子项"全量列出来（读库，不手填、不写死数量）。这四张表的数据直接来自下面这组查询（`OID` 换成当前 demo 的 org_id）：

```bash
OID=54f5f892-cf08-4a75-88b2-b649fea392a4   # starclothing

# RAG：组织节点 / 知识库 / 文件夹·文档
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,u.display_name,'星途服装(组织)') node, c.name collection
from rag_collections c
left join departments d on d.id=c.scope_id::uuid
left join users u on u.id=c.scope_id::uuid
where c.organization_id='$OID' and c.deleted_at is null order by 1,2;"
# 知识库下的文档：rag_documents.title / folder_path（rag_documents 无 name 列，有 title+source+folder_path；
#   rag_folders 用 path 列，不是 name 列）

# 数据接口：组织节点 / 系统 / 端点
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,u.display_name,'星途服装(组织)') node, s.name system, i.name, i.path
from data_systems s
join data_interfaces i on i.data_system_id=s.id
left join departments d on d.id=s.scope_id::uuid
left join users u on u.id=s.scope_id::uuid
where s.organization_id='$OID' and s.deleted_at is null and i.deleted_at is null
order by 1,2,i.path;"
# data_interfaces 表自身无 organization_id/scope——归属靠 data_systems（有 scope_type/scope_id），
#   join data_systems 才拿得到节点 + 系统名。

# 技能：组织节点 / 技能文件夹
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,u.display_name,'星途服装(组织)') node, sf.name skill_folder
from skill_folders sf
left join departments d on d.id=sf.scope_id::uuid
left join users u on u.id=sf.scope_id::uuid
where sf.organization_id='$OID' and sf.deleted_at is null order by 1,2;"
# skill_files 用 skill_folder_id 关联 skill_folders.id（不是 folder_id）

# 本体：组织节点 / 文件夹 / 文件
docker exec ai_infra_postgres psql -U ai_infra -d ai_infra -c "
select coalesce(d.name,u.display_name,'星途服装(组织)') node, ofi.path
from ontology_files ofi
left join departments d on d.id=ofi.scope_id::uuid
left join users u on u.id=ofi.scope_id::uuid
where ofi.organization_id='$OID' and ofi.deleted_at is null order by 1,2;"
# ontology_files 自带 scope_type/scope_id/path（无 folder_id）；文件夹在 ontology_folders（path 列，无 name 列）。
#   节点名：scope_type=organization→'星途服装(组织)'；department→departments.name；user→users.display_name
```

清单表渲染要点：
- **列按用户指定**：RAG=(组织节点, 知识库, 文件夹/文档)；数据接口=(组织节点, 系统, 数据接口)；技能=(组织节点, 技能)；本体=(组织节点, 文件夹, 本体)。
- 同一类系统在多部门各有一份副本（端点集基本一致）时，副本行用「同××端点集（N）」省略重复列举，避免表格过长；但**行不能省**（要"所有"）。
- **数量必须读库**：正文里"共 N 个数据接口/技能/文件"等数字一律取上面 count，不写死（曾出现 368/29/100 陈旧值与实测 211/13/34 不符）。
- 节点排序按 7 个归口部门顺序（开发/设计/品控/供应链/生产/财务/商品），组织级节点放最后。

---

## 3. 关键踩坑（高频出错点）

| 现象 | 根因 | 解决 |
|---|---|---|
| `node` fetch `localhost:8000` → ECONNREFUSED `::1:8000` | node 把 localhost 解析成 IPv6 ::1，后端只听 IPv4 127.0.0.1 | 登录等 node 侧请求用 `http://127.0.0.1:8000` |
| 浏览器访问 `127.0.0.1:5173` 拒绝 | vite dev 只听 `::1`（IPv6） | 用 `http://[::1]:5173` 或 `http://localhost:5173` |
| SPA 自己的 `/api` 请求全 500/空 | vite 代理 `/api → http://localhost:8000` 也解析成 `::1:8000` 被拒 | 在 Playwright 用 `page.route('**/api/v1/**', ...)` 把 `/api/v1` 直转 `127.0.0.1:8000`，绕开 vite 代理 |
| SPA 加载后任务列表/数据空、`/src/api/client.ts` 404 | route 模式 `**/api/**` 太贪心，把 vite 源码模块 `/src/api/client.ts` 也拦截转发到后端 → 404 → API 客户端模块加载失败 | route 模式用 **`**/api/v1/**`**（只拦真 API，不拦 `/src/api/...` 源码） |
| `page.goto` 用 `waitUntil:'networkidle'` 一直挂超时 | vite HMR 有长连接 websocket，networkidle 永不触发 | 用 `waitUntil:'domcontentloaded'` + 显式等关键文本出现 |
| 管理端左树型页面右栏空 | `getByText('星途服装').first()` 点到顶部 OrgSelect（下拉）而非左树 MacTree 节点 | 逐个尝试 '星途服装' 匹配项点击，每次检查右栏是否出现数据（如 key_prefix `lr_sk_`）；见 §4 脚本 |
| 权限分类器 `glm-5.2 is temporarily unavailable` 拦 Bash/Write | harness 安全分类器服务间歇不可用，只读命令不受影响 | 等 20–60s 重试；`sleep` 类内置命令能过，外部命令多试几次 |

### 登录端点与 token 存储 key

| 角色 | 登录端点 | 请求体 | 返回 | localStorage key |
|---|---|---|---|---|
| 终端业务用户 | `POST /api/v1/users/login-by-slug` | `{slug,username,password}` | `{access_token,user}` | `ai_infra_user_token` / `ai_infra_user` |
| 组织管理员 | `POST /api/v1/auth/login` | `{slug,username,password}` | `{access_token,admin}` | `ai_infra_token` / `ai_infra_admin` |

> 注意两类账号 token 的 localStorage key 不同；浏览器导航前用 `ctx.addInitScript` 注入对应 key，SPA 的 RequireAuth 才放行。

### 路由（管理端功能页路径，见 `frontend/src/App.tsx` SUBSYSTEMS）

- 组织管理：`/org/structure` `/org/users` `/org/contact`（`/org/admins` 管理员管理为超管专属页，指南不拍、不介绍）
- 模型路由器：`/keys` `/providers` `/dlp`
- 智能体平台：`/agent/workspaces` `/agent/agents` `/agent/rag` `/agent/memory`（`/agent/agents` 智能体页已可见——星途配了 7 个部门级业务 agent，指南 §3.4 在工作空间与 RAG 之间插「智能体」子节：7 agent 清单表 + 截图；测试广场/Judge 仍为二期菜单 hidden）
- 工具连接器：`/tools/data-interfaces` `/tools/skills` `/tools/ontology`（连接器 hidden）
- 应用监控台：`/monitor/overview` `/monitor/router` `/monitor/agents` `/monitor/tools`
- 终端用户门户：`/{slug}/terminal`（登录页 `/{slug}/terminal/login`）

---

## 4. 截图脚本（Playwright，可复用）

> 运行方式：`cd frontend && NODE_PATH=$PWD/node_modules node <script>.js`
> 前端自带 `playwright`；chromium 首次需 `npx playwright install chromium` + 装运行依赖：`yum -y install atk at-spi2-atk at-spi2-core libX11 libXcomposite libXdamage libXext libXfixes libXrandr libgbm libxcb libxshmfence alsa-lib pango cairo nss nspr cups-libs mesa-libgbm`。CJK 字体：`yum -y install google-noto-sans-cjk-ttc-fonts`。

### 4.1 通用 API 路由 + 登录注入片段（所有脚本共用）

```js
const WEB = 'http://[::1]:5173', API = 'http://127.0.0.1:8000';
// 登录（终端用户）
async function userLogin(slug,user,pass){
  const r=await fetch(`${API}/api/v1/users/login-by-slug`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug,username:user,password:pass})});
  if(!r.ok) throw new Error(`login ${user} ${r.status}`);
  return await r.json(); // {access_token,user}
}
// 登录（管理员）
async function adminLogin(slug,user,pass){
  const r=await fetch(`${API}/api/v1/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug,username:user,password:pass})});
  if(!r.ok) throw new Error(`admin login ${r.status}`);
  return await r.json(); // {access_token,admin}
}
// 终端用户 token 注入
await ctx.addInitScript(([t,u])=>{localStorage.setItem('ai_infra_user_token',t);localStorage.setItem('ai_infra_user',JSON.stringify(u));},[token,user]);
// 管理员 token 注入
await ctx.addInitScript(([t,a])=>{localStorage.setItem('ai_infra_token',t);localStorage.setItem('ai_infra_admin',JSON.stringify(a));},[token,admin]);
// 关键：把 SPA 的 /api/v1 请求直转到后端，绕开 vite 坏代理 + IPv6 问题
await ctx.route('**/api/v1/**', async route=>{
  const req=route.request(),u=new URL(req.url()),target=API+u.pathname+u.search;
  const h={};for(const[k,v]of Object.entries(req.headers()))if(['authorization','content-type','accept'].includes(k.toLowerCase()))h[k]=v;
  try{const resp=await fetch(target,{method:req.method(),headers:h,body:['GET','HEAD'].includes(req.method())?undefined:(req.postData()||undefined)});
    const buf=Buffer.from(await resp.arrayBuffer());const rh={};resp.headers.forEach((v,k)=>{if(!['content-encoding','content-length','transfer-encoding','connection'].includes(k.toLowerCase()))rh[k]=v;});
    await route.fulfill({status:resp.status,headers:rh,body:buf});
  }catch(e){await route.continue();}
});
// 导航用 domcontentloaded（vite HMR 会让 networkidle 永不返回）
await page.goto(`${WEB}/${slug}/terminal`,{waitUntil:'domcontentloaded',timeout:30000});
```

### 4.2 终端任务截图（每个归口用户 → 打开"对应名称"的已完成任务 → 第一屏 + 最后一屏）

> 终端消息区是内层 `overflowY:auto` 容器（`Terminal.tsx` 的 `scrollRef`，含 `.wb-md`），
> `fullPage:true` 抓不到被滚走的内容、只截当前 viewport；任务点开时该容器自动
> smooth-scroll 到底，所以默认截到的就是「最后一屏」。要补「第一屏」需手动把该容器
> 滚到顶再 viewport 截图。每场景产出两张：`{key}_top.png`（第一屏）+ `{key}.png`（最后一屏）。

```js
const SCEN=[
  {key:'pd1',user:'dev-lead',title:'逾期订单风险汇总与推送'},
  // ... 每场景一项；title 必须 == 任务在 DB 里的 title
];
// 找消息区 scroll 容器并滚到顶/底
async function setMsgScroll(page,toTop){
  await page.evaluate(top=>{
    const picks=[];
    document.querySelectorAll('div').forEach(d=>{
      const s=getComputedStyle(d);
      if((s.overflowY==='auto'||s.overflowY==='scroll')&&d.scrollHeight>d.clientHeight+4) picks.push(d);
    });
    const target=picks.find(d=>d.querySelector('.wb-md'))||picks.sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
    if(target) target.scrollTop=top?0:target.scrollHeight;
  },toTop);
}
for(const s of SCEN){
  const {access_token,user}=await userLogin(slug,s.user,pass);
  const ctx=await browser.newContext({viewport:{width:1500,height:1000},deviceScaleFactor:2});
  await ctx.addInitScript(/* 注入 user token */);
  await ctx.route('**/api/v1/**',/* 转发 */);
  const page=await ctx.newPage();
  await page.goto(`${WEB}/${slug}/terminal`,{waitUntil:'domcontentloaded'});
  const item=page.getByText(s.title,{exact:false}).first();
  await item.waitFor({state:'visible',timeout:20000});
  await item.click();            // 打开任务 → 回放已持久化的 messages（无需重跑）
  await page.waitForTimeout(3000);
  // 第一屏：滚到顶（任务入口 + composer 提示词 + 首条消息）
  await setMsgScroll(page,true);
  await page.waitForTimeout(1200);
  await page.screenshot({path:`${OUT}/${s.key}_top.png`});
  // 最后一屏：滚回底（最终助手输出 / 闭环待办）
  await setMsgScroll(page,false);
  await page.waitForTimeout(1500);
  await page.screenshot({path:`${OUT}/${s.key}.png`,fullPage:true});
  await ctx.close();
}
```

> HTML 里每场景配两张：`图 2-N①第一屏 / ②最后一屏`，`<img class="realshot" src="shots/pdN_top.png">` + `src="shots/pdN.png"`。

### 4.3 管理端截图（admin 登录 → 逐功能页 → 左树点选**有数据的归口节点** → 截图）

> 每个左树型页打开后右栏默认**空**（`selectedNode` 为空时 `scopedRules`/资源列表返回 `[]`），
> 必须点选一个**有数据的组织树节点**右栏才会出数据。点哪个节点由 §2 的 DB 查询决定：
> 读各资源表 `scope_type`+`scope_id` 的分布，选一个有数据的节点，join 出节点名
> （org=组织名、dept=部门名、user=用户 display_name）。星途服装实测的归口节点映射：
>
> | 页面 | 路由 | 点选节点 | 节点类型 | DB 依据 |
> |---|---|---|---|---|
> | 安全围栏 | `/dlp` | 星途服装 | organization | dlp_rules 9 条在 org scope |
> | 工作空间 | `/agent/workspaces` | 开发部长 | user（dev-lead） | workspaces user 级，dev-lead 有 1 |
> | RAG 知识库 | `/agent/rag` | 品控部 | department | rag_collections 仅品控部有 1 |
> | 长期记忆 | `/agent/memory` | 开发部长 | user（dev-lead） | memories user 级，dev-lead 有 1 |
> | 数据接口 | `/tools/data-interfaces` | 开发部 | department | data_systems 开发部有 PLM |
> | 技能 | `/tools/skills` | 商品部 | department | skill_folders 商品部 3 个 |
> | 本体 | `/tools/ontology` | 设计部 | department | ontology_files 设计部 5 个 |
> | 路由器监控 | `/monitor/router` | （点「路由指标」tab） | — | 非树型页 |
>
> **两个坑**：
> 1. **页面有两个 `<aside>`** —— 第一个是全局导航栏（组织管理/模型路由器/…菜单），第二个才是
>    FinderShell 的组织架构树。`page.locator('aside').first()` 会点到导航栏 → 树节点永远
>    waitFor 超时。必须用 `nth(1)`。
> 2. **starclothing admin 是 org_admin（绑了 organization_id）** → `isOrgScoped()` 为真，OrgSelect
>    渲染成不可点的 Tag 且自动锁定到星途服装组织，无需手动点 OrgSelect；树会自动加载。
>    （若用 super_admin 登录则 OrgSelect 是下拉，需先选组织。）
> 3. `getByText(label,{exact:true})`：exact 必须开，否则「开发部」会命中「开发部长」。

```js
// [route, file, nodeText?]；nodeText 留空 = 非树型页
const PAGES=[
  ['/dlp','dlp','星途服装'],
  ['/agent/workspaces','agent-workspaces','开发部长'],
  ['/agent/rag','agent-rag','品控部'],
  ['/agent/memory','agent-memory','开发部长'],
  ['/tools/data-interfaces','tools-data-interfaces','开发部'],
  ['/tools/skills','tools-skills','商品部'],
  ['/tools/ontology','tools-ontology','设计部'],
  ['/monitor/router','monitor-router',null],   // 点「路由指标」tab
];
async function clickTreeNode(page,label){
  const aside=page.locator('aside').nth(1);                 // 第二个 aside = 组织架构树
  const node=aside.getByText(label,{exact:true}).first();
  await node.waitFor({state:'visible',timeout:15000});
  await node.click({timeout:3000});
}
const {access_token,admin}=await adminLogin(slug,'admin',pass);
for(const [route,file,nodeText] of PAGES){
  await page.goto(`${WEB}${route}`,{waitUntil:'domcontentloaded'});
  await page.waitForTimeout(2800);                          // 等 OrgSelect 锁组织 + 树渲染
  if(nodeText){ await clickTreeNode(page,nodeText); await page.waitForTimeout(2500); }
  else if(route==='/monitor/router'){
    const tab=page.getByRole('tab',{name:'路由指标'});
    try{await tab.waitFor({state:'visible',timeout:8000});await tab.click({timeout:3000});}
    catch{await page.getByText('路由指标',{exact:true}).first().click({timeout:3000});}
    await page.waitForTimeout(2500);
  }
  await page.screenshot({path:`${OUT}/${file}.png`,fullPage:true});
}
```

> 实测脚本：`scripts/guide_capture/capture_mgmt_nodes.js`（8 页全 OK）。
> 左树"点哪个节点"由 §2 的 DB 查询决定（哪个 scope 有数据）；改 demo 数据后重跑 §2 查询确认节点名仍有效。

### 4.4 实际脚本（星途服装用，可作模板）

`/tmp/pwpdf/capture_terminal.js`、`capture_mgmt.js`、`recapture_keys.js`、`debug.js` —— 临时脚本，按上节模板改 slug/user/路径即可复用到 agileac 等项目。建议把可复用版存到 `<demo>/scripts/`。

---

## 5. HTML 网页版样式要点

源文件：`demo/starclothing/服装企业AI底座POC指南.html`。结构：封面 → 目录 → 第一章企业概况痛点 → 第二章 7 场景（终端真截图）→ 第三章管理端（管理端真截图）→ 附录。

**网页可读性 CSS 要点**（区别于 PDF/A4 导向）：

- `html{scroll-behavior:smooth;}`；body 浅灰底（`#eef1f6`）+ 16px / 行高 1.85。
- **通栏 section + 居中内容列**（封面与各章宽度一致）：
  `section{max-width:100%;margin:0;padding:52px max(24px,calc(50% - 480px));background:#fff;}`
  `.cover{padding:84px max(24px,calc(50% - 480px)) 104px;min-height:62vh;...}` —— 通栏深色封面、白色章节、内容同宽左右对齐。
- **吸顶导航** `.topnav`（position:sticky），链接到各章 id；**目录可点击**（`<li><a href="#chN">`）；**返回顶部**按钮 + scroll 监听显隐。
- **响应式** `@media(max-width:760px)`：双列变单列、侧栏收窄、字号略降。
- 截图 `.realshot{width:100%;border-radius;box-shadow}`；图注 `.cap` 居中。
- 保留一份 `@media print` 兜底（万一浏览器打印成 PDF）。
- 章节加 `id`（cover→top、toc、ch1/ch2/ch3/appendix）供锚点跳转。

### 用脚本批量改样式/图号（避免手改大文件）

- 替换 `<style>` 块、插 topnav、加 id、目录加链接：用 Python `re` / 字符串替换（见当时用的 `/tmp/pwpdf/webify.py`）。
- 把渲染面板换成 `<img class="realshot">`：按行范围替换（`/tmp/pwpdf/replace_shots.py`，从后往前避免行号漂移，带 assert 校验边界）。
- 删整块 + 图号重排：`re.sub(r'图 3-\d+　', 顺序计数器)` 自动连续编号（`/tmp/pwpdf/edit_ch3.py`）。

---

## 6. 发布到公开链接

> **发布目标已从 `frontend/dist/guide/` 迁到独立稳定目录 `demo/publish/guide/`，并由 nginx 专属 location `/guide/` 直接服务。** 此前指南放在 `dist/` 下，每次 `npm run build`（vite `emptyOutDir`）会把 `dist/` 清空、连带 `dist/guide/` 冲掉，nginx SPA fallback 便回退到 `index.html` → 未登录显示登录框（即“指南变登录框”顽疾）。迁出 `dist/` 后，前端重新 build 再也碰不到指南，无需每次重发。

```bash
PUB=/root/ai_infra/demo/publish/guide
mkdir -p "$PUB/shots/starclothing/mgmt" "$PUB/shots/agileac/mgmt"
bash demo/scripts/publish_guides.sh   # 发布四件套（2 指南 + 2 访问页），含不变量校验，绑定同步、不可只发其一；用 /bin/cp -f 绕开 cp -i 别名
/bin/cp -r "demo/starclothing/shots/." "$PUB/shots/starclothing/"   # 截图随 HTML 同目录（相对路径 shots/starclothing/...）
chmod -R a+rX "$PUB"                                      # nginx worker 可读
# 验证（应 200，HTML 含 realshot、无 id="root"）
curl -s -o /dev/null -w "%{http_code}\n" https://infra.aievolve.org.cn/guide/starclothing-poc-guide.html
curl -s -o /dev/null -w "%{http_code}\n" https://infra.aievolve.org.cn/guide/shots/starclothing/pd1.png
curl -s -o /dev/null -w "%{http_code}\n" https://infra.aievolve.org.cn/guide/shots/starclothing/mgmt/keys.png
```

nginx 配置（`/etc/nginx/conf.d/infra.aievolve.org.cn.conf`，已落地，改完 `nginx -t && nginx -s reload`）：

```nginx
# 客户 POC 指南 HTML（纯静态，独立于前端 build 产物 dist/，避免 vite build 清空 dist 后变登录框）
location /guide/ {
    alias /root/ai_infra/demo/publish/guide/;
    try_files $uri $uri/ =404;     # 文件不在直接 404，不走 SPA fallback
}
```

- HTML 里图片用**相对路径** `shots/starclothing/pd1.png`、`shots/starclothing/mgmt/keys.png`（**按租户命名空间**，避免与 agileac 指南共用 `shots/` 时同名管理页截图互相覆盖），随 HTML 一起拷到 `demo/publish/guide/shots/<租户>/`。
- 用 ASCII 文件名 `starclothing-poc-guide.html`（中文文件名 URL 要 percent-encode）。
- 改动后重新 cp 即可刷新；浏览器 Ctrl+F5 清缓存。
- 源文件仍在 `demo/starclothing/`，`demo/publish/guide/` 只是**发布副本**，但它在 `dist/` 之外、不被 build 清空，故为持久副本（不再是临时副本）。

---

## 7. 完整流程速查

1. 起服务：docker（pg/redis/backend）+ mock + `cd frontend && nohup npm run dev`。
2. 读库：确认终端任务已完成、各管理页有数据、各资源绑在哪个 scope 节点（§2）。
3. 装工具：`npx playwright install chromium` + 运行依赖 + CJK 字体（§4 前置）。
4. 截图：`NODE_PATH=frontend/node_modules node capture_terminal.js`（第一屏+最后一屏）+ `capture_mgmt_nodes.js`（按 §4.3 表点归口节点）（§4）→ 输出到 `demo/starclothing/shots/`。
5. 写 HTML：结构 + 网页版 CSS（§5）；截图用 `<img class="realshot" src="shots/...">`；管理端介绍参照 `frontend/src/help/content.ts`；**组织层级口径、不提 super_admin（§0）**；§3.4/§3.5 四张资源清单表（RAG/数据接口/技能/本体）读库生成（§2.1）、数量不写死。
6. 发布：cp 到 `demo/publish/guide/`（nginx 专属 location，见 §6）→ 给客户 `https://infra.aievolve.org.cn/guide/starclothing-poc-guide.html`。不再放 `dist/`，前端 build 不会冲掉。

## 8. 复用到其他 demo（agileac 等）

- 改 §4 脚本里的 `slug`、归口用户/场景标题、管理端截图里左树要点的节点名（按该 demo §2 的 DB 查询结果，不是照搬星途服装的节点）。
- 终端任务需先在该 demo 跑出结果并落库（每个归口用户名下一个 title=场景名的任务，messages>=2）。
- 管理端功能页路径同平台一致（同套控制台），数据按该 demo 的 seed 决定拍哪些；§4.3 的两个 `<aside>`、org admin 自动锁组织、`getByText` exact 三个坑同套适用。
- 帮助文档 `frontend/src/help/content.ts` 是平台级通用，可直接参照；`content_org_admin.ts` 含超管字样是内部帮助，**不照搬进指南正文**（§0）。
- 第三章始终用组织层级口径：只写管理员（admin）的能力与边界，不提 super_admin，不拍超管页。
- §3.4/§3.5 四张资源清单表（RAG/数据接口/技能/本体）按 §2.1 的查询读库生成，列同规、数量取实测 count 不写死；改 demo 数据后重跑 §2.1 查询刷新清单与正文数字。
