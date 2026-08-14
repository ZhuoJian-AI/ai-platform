// starhma 终端任务截图（9 场景，第一屏 + 最后一屏）
// 自包含：login → 创建任务(绑 template_agent_id) → POST run（SSE 跑到 final）→ 截图 top + bottom。
// 运行：cd /root/ai_infra/frontend && NODE_PATH=$PWD/node_modules node /root/ai_infra/demo/starhma/scripts/guide_capture/capture_terminal.js
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'http://[::1]:5173', API = 'http://127.0.0.1:8000', SLUG = 'starhma', PASS = '12345678';
const OUT = '/root/ai_infra/demo/starhma/shots';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// 9 场景：归口用户 + 任务标题 + template_agent_id + composer（不含场景代号，用具体示例）
const SCEN = [
  { key:'rdm01', user:'rd-formulator', title:'配方智能推荐与初始配比', agent:'e5188ebd-24e3-4adc-8fa7-8118832da288',
    msg:'对医疗用品低温热熔胶做配方智能推荐：客户基材无纺布/PE 膜、施胶温度 130℃、开放时间 6s、剥离力 14N、需 FDA 与 ISO-10993 环保、成本上限 40 元/kg；推荐历史相似配方 FORM-CUS-002 与初始配比 ING-RES-001/ING-TK-002，并给预估性能。' },
  { key:'rdm02', user:'rd-analyst', title:'实验数据分析与报告生成', agent:'fe5e56d7-84cc-426a-920d-a8a17d90be71',
    msg:'对配方 FORM-CUS-002 做实验数据分析与报告生成：分析流变实验 EXP-RHE-001 与拉力实验 EXP-TEN-001 数据、识别异常、关联失效记录 FR-2025-021，生成标准化实验报告。' },
  { key:'sal01', user:'sales-rep', title:'智能询盘与初步粘接方案', agent:'911847f5-57a3-43f5-8d5b-b98b92918e21',
    msg:'对询盘 INQ-002 医疗用品客户做智能询盘：解析基材/工况需求、匹配配方 FORM-CUS-002、生成初步粘接方案与报价、联动样品 SMP-2026-002。' },
  { key:'mfg01', user:'mfg-planner', title:'智能排产与订单冲突识别', agent:'f881da63-63d9-4d6d-a6ff-71ec404941c8',
    msg:'做智能排产与订单冲突识别：综合 MES 工单 WO202607001..005 交期、产线 LINE-AUTO-01/02 与 LINE-03 负荷、换线成本，调 optimizeProductionSchedule 给排产建议与冲突订单。' },
  { key:'eqp01', user:'eqp-maintainer', title:'设备预测性维护与保养提醒', agent:'9f6a623a-88dd-4b3c-a40f-3b58e6fb1872',
    msg:'对设备 EQ-MTR-02 做预测性维护：调 predictEquipmentFault 看振动/温升/健康分，给风险等级与保养提醒，关联产线 LINE-AUTO-02 与工艺参数 PP-REACT-002。' },
  { key:'scm01', user:'scm-manager', title:'库存智能预警与补货建议', agent:'31065753-d025-44a4-8d7d-3fd48d5a0864',
    msg:'做库存智能预警与补货建议：查 ERP 原料 M-RES-001/M-TK-002/M-AO-001 与成品 M-FG-002 库存对比安全库存，列低库存预警与补货建议，联动采购单 POHMA 与销售预测。' },
  { key:'qas01', user:'qas-engineer', title:'售后粘接故障智能诊断', agent:'011fa0f8-ef5a-417e-a1a4-881694794c81',
    msg:'对客诉 CC-2026-001 开胶故障做智能诊断：调 diagnoseAfterSalesFault 按现象/基材/工况匹配故障案例 FC-2025-008 与历史客诉，给排查方案与配方 FORM-CUS-001 调整建议。' },
  { key:'adm01', user:'admin-officer', title:'跨系统经营数据汇总', agent:'269c904a-9a0b-4f35-81e1-2522e90989bf',
    msg:'做跨系统经营数据汇总：汇总 ERP 营收/采购/库存、CRM 订单/客户/回款、MES 产能/工单，生成经营简报（营收/产能/订单/客户统计+应收应付对账 INV↔BV-HMA-）。' },
  { key:'doc01', user:'doc-clerk', title:'文档智能处理与检索', agent:'3c14d454-8f08-4e70-a613-83c14387036c',
    msg:'做文档智能处理与检索：检索合同 CT-HMA-001/002 与采购单 POHMA、凭证 BV-HMA- 的关键条款/摘要，提取付款里程碑与风险点，生成文档摘要。' },
];

async function routeApi(page){
  await page.route('**/api/v1/**', async route => {
    const req = route.request();
    try {
      const u = new URL(req.url());
      const target = API + u.pathname + u.search;
      const h = {};
      for (const [k,v] of Object.entries(req.headers())) if (['authorization','content-type','accept'].includes(k.toLowerCase())) h[k]=v;
      const resp = await fetch(target, { method: req.method(), headers: h, body: ['GET','HEAD'].includes(req.method())?undefined:(req.postData()||undefined) });
      const buf = Buffer.from(await resp.arrayBuffer());
      const rh = {};
      resp.headers.forEach((v,k)=>{ if(!['content-encoding','content-length','transfer-encoding','connection'].includes(k.toLowerCase())) rh[k]=v; });
      await route.fulfill({ status: resp.status, headers: rh, body: buf });
    } catch(e){ await route.continue(); }
  });
}

async function login(user){
  const r = await fetch(`${API}/api/v1/users/login-by-slug`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:SLUG,username:user,password:PASS})});
  if(!r.ok) throw new Error(`login ${user} ${r.status}`);
  return await r.json();
}

async function createAndRun(access_token, s){
  const taskRes = await fetch(`${API}/api/v1/terminal/tasks`,{method:'POST',headers:{'Authorization':`Bearer ${access_token}`,'Content-Type':'application/json'},body:JSON.stringify({title:s.title,config:{template_agent_id:s.agent,skill_ids:[],model_alias:'glm-5.2',exec_mode:'craft'}})});
  if(!taskRes.ok) throw new Error(`create task ${s.key} ${taskRes.status} ${await taskRes.text()}`);
  const task = await taskRes.json();
  const ctrl = new AbortController();
  const to = setTimeout(()=>ctrl.abort(), 300000);
  try {
    const r = await fetch(`${API}/api/v1/terminal/tasks/${task.id}/run`,{method:'POST',headers:{'Authorization':`Bearer ${access_token}`,'Content-Type':'application/json'},body:JSON.stringify({message:s.msg,stream:true}),signal:ctrl.signal});
    const reader = r.body.getReader(); const dec = new TextDecoder();
    let done=false;
    while(!done){
      const { value, done: rd } = await reader.read();
      if(rd) break;
      const txt = dec.decode(value,{stream:true});
      if(txt.includes('"type":"final"') || txt.includes('"type":"done"') || txt.includes('data: [DONE]')) done=true;
    }
  } catch(e){ /* abort on done/timeout fine */ }
  finally{ clearTimeout(to); }
  return task.id;
}

async function setMsgScroll(page, toTop){
  await page.evaluate(top => {
    const picks = [];
    document.querySelectorAll('div').forEach(d => {
      const s = getComputedStyle(d);
      if ((s.overflowY==='auto'||s.overflowY==='scroll') && d.scrollHeight > d.clientHeight + 4) picks.push(d);
    });
    // 按可滚动高度降序，主消息容器通常最大
    picks.sort((a,b)=>b.scrollHeight-a.scrollHeight);
    const main = picks.find(d => d.querySelector('.wb-md')) || picks[0];
    if (main) main.scrollTop = top ? 0 : main.scrollHeight;
    // 兜底：所有可滚动容器一并滚到顶/底，确保 top≠bottom
    for (const d of picks) { if (d !== main) d.scrollTop = top ? 0 : d.scrollHeight; }
  }, toTop);
}

(async()=>{
  const browser = await chromium.launch({args:['--no-sandbox']});
  const KEYS = process.env.KEYS ? process.env.KEYS.split(',') : null;
  for (const s of SCEN) {
    if (KEYS && !KEYS.includes(s.key)) continue;
    const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 });
    try {
      const { access_token, user } = await login(s.user);
      await ctx.addInitScript(([tok, u]) => { localStorage.setItem('ai_infra_user_token', tok); localStorage.setItem('ai_infra_user', JSON.stringify(u)); }, [access_token, user]);
      const page = await ctx.newPage();
      await routeApi(page);
      const taskId = await createAndRun(access_token, s);
      await page.goto(`${BASE}/${SLUG}/terminal`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2500);
      const item = page.getByText(s.title, { exact: false }).first();
      await item.waitFor({ state: 'visible', timeout: 20000 });
      await item.click();
      try { await page.getByText('场景模板注入', { exact: false }).first().waitFor({ state: 'visible', timeout: 25000 }); }
      catch { await page.getByText('已完成', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 }); }
      await page.waitForTimeout(2500);
      await setMsgScroll(page, true);
      await page.waitForTimeout(1200);
      await page.screenshot({ path: `${OUT}/${s.key}_top.png` });
      await setMsgScroll(page, false);
      await page.waitForTimeout(1800);
      await page.screenshot({ path: `${OUT}/${s.key}.png`, fullPage: true });
      console.log(`OK ${s.key} task=${taskId}`);
    } catch(e){
      console.error(`FAIL ${s.key}: ${e.message.split('\n')[0]}`);
    } finally { await ctx.close(); }
  }
  await browser.close();
  console.log('done');
})().catch(e=>{ console.error('ERR', e); process.exit(1); });
