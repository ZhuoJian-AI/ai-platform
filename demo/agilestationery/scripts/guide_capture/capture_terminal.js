// agilestationery 终端任务截图（9 场景，第一屏 + 最后一屏）
// 自包含：login → 创建任务(绑 template_agent_id) → POST run（SSE 跑到 final）→ 截图 top + bottom。
// 运行：cd /root/ai_infra/frontend && NODE_PATH=$PWD/node_modules node /root/ai_infra/demo/agilestationery/scripts/guide_capture/capture_terminal.js
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'http://[::1]:5173', API = 'http://127.0.0.1:8000', SLUG = 'agilestationery', PASS = '12345678';
const OUT = '/root/ai_infra/demo/agilestationery/shots';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// 9 场景：归口用户 + 任务标题 + template_agent_id + composer
const SCEN = [
  { key:'sal01', user:'sal-channel',  title:'渠道健康度监测与销售补货预测', agent:'31c218ce-605c-4844-85e7-fc81a37477a3',
    msg:'对经销商渠道做健康度监测 + 销售预测与补货建议，重点 DLR-01（华东经销商）、DLR-03（华南）。扫所有经销商与未交付订单，按渠道检索经销商画像与渠道规则库给健康度评分与补货建议。 /agilestationery-sales-crm-erp-query' },
  { key:'ecm01', user:'ecm-ops',      title:'线上渠道秩序管控与渠道效能分析', agent:'e2d0ac89-fbca-4a8a-99de-2ec4a47f0f3a',
    msg:'对线上渠道做秩序管控与渠道效能分析，重点 MR-EC-09（淘宝冒名店，假冒+低价）、MR-DL-12（义乌窜货商，假冒+跨区）+ 渠道效能拼多多 ROI 下降。扫所有非授权店铺与违规取证，按渠道检索渠道秩序与平台规则库给风险队列与处置建议。 /agilestationery-ecom-chn-crm-query' },
  { key:'mkt01', user:'mkt-analyst',  title:'竞品动态监测与B端营销物料生成', agent:'a54ea1b8-2d19-435c-a3c2-6fcd1d053856',
    msg:'做竞品动态监测与 B 端营销物料生成，重点 CMP-01（百乐 V5 新品线上加码）、CMP-02（三菱政企集采）。扫所有竞品动态，按品类检索竞品情报与营销物料库给竞品周报 + 中性笔订货会宣讲文案（纯文本）+ 合规初审。 /agilestationery-mkt-chn-query' },
  { key:'scm01', user:'scm-customs',  title:'报关单证智能处理与库存补货规划', agent:'a547d723-6bde-4edb-b400-f5d9d39c4787',
    msg:'对当前进口报关单做单证识别与合规校验 + 库存补货规划，重点 CD202607001（SKU-ZB-G001 中性笔，已申报）、CD202607005（中性笔 0.4，异常-归类存疑）+ 发票 INV202607001 验真。扫所有在途报关单与低库存 SKU，按品类检索报关合规与库存规则库给归类/合规/补货/汇率建议。 /agilestationery-supply-cst-scm-erp-query' },
  { key:'prd01', user:'prd-quality',  title:'渠道假货识别与全渠道反馈分析', agent:'083e3434-0ca8-4968-8752-4384784ad201',
    msg:'对渠道抽检样本做假货识别与全渠道反馈分析，重点 CTF20260701（SKU-ZB-G001 华南电商抽检，假货）、CTF20260704（SKU-ZB-M001 华北电商抽检，假货）+ 反馈 FB20260706（中性笔 黑整批笔尖偏磨，严重）。扫所有假货样本与反馈，按产品检索假货特征与产品标准库给鉴定/分布/反馈/改进建议。 /agilestationery-product-pim-query' },
  { key:'svc01', user:'svc-agent',    title:'售后工单智能处理与B端客服辅助', agent:'3ea7092f-4a06-4619-9790-d23e81cdf0e6',
    msg:'对当前售后工单做智能处理与客服辅助，重点 CASE-0002（KA-02 笔夹松动脱落，严重，8D）、CASE-0006（DLR-01 中性笔 整批笔尖偏磨，严重，8D）+ CASE-0005（运输破损补发）。扫所有未闭环工单，按问题类型检索售后政策与工单规则库给资质校验/分派/超时升级建议。 /agilestationery-service-crm-erp-query' },
  { key:'fin01', user:'fin-accountant', title:'发票识别审核与费用对账', agent:'51c787d2-34ac-46dd-8004-f05bbafa5b12',
    msg:'做发票识别审核与费用对账，重点发票 INV202607001（进项，关联凭证 BV-AS-2026-0701）、INV202607007（存疑-发票代码异常）+ 应收 DLR-03 逾期。扫所有发票与凭证/应付/应收做对账，差异率>2% 标异常，按场景检索财务合规与发票规则库给验真/对账/催收建议。 /agilestationery-finance-erp-cst-crm-query' },
  { key:'hr01',  user:'hr-recruiter',  title:'招聘人岗匹配与人事事务', agent:'005f421e-8a18-42f3-aa02-325b34ff5bc4',
    msg:'对电商运营专员 P-EC 岗位做简历筛选与人岗匹配，招聘需求 ASRC（headcount 2，紧急）。扫该岗位所有简历，按岗位检索岗位JD与人事制度库给 5 维度评估排序 + 推荐短名单 + 面试题 + 到岗催办。 /agilestationery-hr-hrm-query' },
  { key:'leg01', user:'leg-counsel',   title:'合同智能审核与渠道维权合规', agent:'52393ef8-7b1e-41a0-85de-ab351f6637c0',
    msg:'做合同智能审核与渠道维权合规，重点 MR-EC-09（淘宝冒名店，取证 EV20260701 + 假货 CTF20260701）、MR-EC-15（拼多多冒名，EV20260706 + CTF20260706）。扫所有违规取证，按场景检索合同条款与合规规则库给合同风险条款/维权清单/合规审查。 /agilestationery-legal-chn-crm-query' },
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

// 创建任务 + 跑 SSE 直到 final/done（完整消费，不早退，避免 abort 误伤后台 run；最多 400s）
async function createAndRun(access_token, s){
  const taskRes = await fetch(`${API}/api/v1/terminal/tasks`,{method:'POST',headers:{'Authorization':`Bearer ${access_token}`,'Content-Type':'application/json'},body:JSON.stringify({title:s.title,config:{template_agent_id:s.agent,skill_ids:[],model_alias:'glm-5.2',exec_mode:'craft'}})});
  if(!taskRes.ok) throw new Error(`create task ${s.key} ${taskRes.status} ${await taskRes.text()}`);
  const task = await taskRes.json();
  const ctrl = new AbortController();
  const to = setTimeout(()=>ctrl.abort(), 400000);
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
  } catch(e){ /* abort on done/timeout */ }
  finally{ clearTimeout(to); }
  // 兜底：再轮询 run_status 直到非 running（确保后台跑完）
  const deadline = Date.now() + 120000;
  while(Date.now() < deadline){
    await new Promise(r=>setTimeout(r, 3000));
    const r = await fetch(`${API}/api/v1/terminal/tasks/${task.id}`,{headers:{'Authorization':`Bearer ${access_token}`}});
    if(r.ok){ const t = await r.json(); if(t.run_status && t.run_status!=='running') break; }
  }
  return task.id;
}

async function setMsgScroll(page, toTop){
  await page.evaluate(top => {
    const picks = [];
    document.querySelectorAll('div').forEach(d => {
      const s = getComputedStyle(d);
      if ((s.overflowY==='auto'||s.overflowY==='scroll') && d.scrollHeight > d.clientHeight + 4) picks.push(d);
    });
    const target = picks.find(d => d.querySelector('.wb-md'))
                || picks.sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
    if (target) target.scrollTop = top ? 0 : target.scrollHeight;
  }, toTop);
}

(async()=>{
  const browser = await chromium.launch({args:['--no-sandbox']});
  const filterKeys = process.env.KEYS ? new Set(process.env.KEYS.split(',')) : null;
  const scenes = filterKeys ? SCEN.filter(s=>filterKeys.has(s.key)) : SCEN;
  for(const s of scenes){
    const ctx = await browser.newContext({viewport:{width:1500,height:1000},deviceScaleFactor:2});
    const { access_token, user } = await login(s.user);
    await ctx.addInitScript(([tok,u])=>{localStorage.setItem('ai_infra_user_token',tok);localStorage.setItem('ai_infra_user',JSON.stringify(u));},[access_token,user]);
    const page = await ctx.newPage();
    try{
      await routeApi(page);
      const taskId = await createAndRun(access_token, s);
      await page.goto(`${BASE}/${SLUG}/terminal`,{waitUntil:'domcontentloaded',timeout:30000});
      await page.waitForTimeout(2500);
      // 按标题点选刚跑完的任务（终端路由不识别 ?task=，必须点列表项）
      const item = page.getByText(s.title,{exact:false}).first();
      await item.waitFor({state:'visible',timeout:20000});
      await item.click();
      // 等聊天区渲染出实质内容（main innerText 长度>300），比等特定 chip 稳；最多 35s
      const t0 = Date.now(); let rendered = false;
      while(Date.now()-t0 < 35000){
        await page.waitForTimeout(1500);
        const len = await page.locator('main').first().innerText().then(s=>s.length).catch(()=>0);
        if(len > 300){ rendered = true; break; }
      }
      if(!rendered) throw new Error('chat content not rendered within 35s');
      await page.waitForTimeout(2500);
      await setMsgScroll(page, true);
      await page.waitForTimeout(1200);
      await page.screenshot({path:`${OUT}/${s.key}_top.png`});
      await setMsgScroll(page, false);
      await page.waitForTimeout(1800);
      await page.screenshot({path:`${OUT}/${s.key}.png`,fullPage:true});
      console.log(`OK ${s.key} (${s.user}) task=${taskId}`);
    }catch(e){
      console.error(`FAIL ${s.key} (${s.user}): ${e.message.split('\n')[0]}`);
      await page.screenshot({path:`${OUT}/${s.key}_err.png`}).catch(()=>{});
    }finally{ await ctx.close(); }
  }
  await browser.close();
  console.log('done');
})().catch(e=>{console.error('ERR',e);process.exit(1)});
