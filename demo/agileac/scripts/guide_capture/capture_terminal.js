// agileac 终端任务截图（11 场景，第一屏 + 最后一屏）
// 复用自 starclothing capture_terminal.js，改 SLUG/用户/标题。
// 运行：cd frontend && NODE_PATH=$PWD/node_modules node /root/ai_infra/demo/agileac/scripts/guide_capture/capture_terminal.js
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'http://[::1]:5173', SLUG = 'agileac', PASS = '12345678';
async function routeApi(page){
  await page.route('**/api/v1/**', async route => {
    const req = route.request();
    try {
      const u = new URL(req.url());
      const target = 'http://127.0.0.1:8000' + u.pathname + u.search;
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
const OUT = '/root/ai_infra/demo/agileac/shots';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });
// 11 场景归口用户 + 任务标题（== DB tasks.title）。sal-ops 名下两任务，按 title 精确区分。
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
async function login(user){
  const r = await fetch(`http://127.0.0.1:8000/api/v1/users/login-by-slug`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:SLUG,username:user,password:PASS})});
  if(!r.ok) throw new Error(`login ${user} ${r.status} ${await r.text()}`);
  return await r.json();
}
(async()=>{
  const browser = await chromium.launch({args:['--no-sandbox']});
  for(const s of SCEN){
    const { access_token, user } = await login(s.user);
    const ctx = await browser.newContext({viewport:{width:1500,height:1000},deviceScaleFactor:2});
    await ctx.addInitScript(([tok,u])=>{localStorage.setItem('ai_infra_user_token',tok);localStorage.setItem('ai_infra_user',JSON.stringify(u));},[access_token,user]);
    const page = await ctx.newPage();
    try{
      await routeApi(page);
      await page.goto(`${BASE}/${SLUG}/terminal`,{waitUntil:'domcontentloaded',timeout:30000});
      const item = page.getByText(s.title,{exact:false}).first();
      await item.waitFor({state:'visible',timeout:20000});
      await item.click();
      await page.waitForTimeout(3000);
      await setMsgScroll(page, true);
      await page.waitForTimeout(1200);
      const top = `${OUT}/${s.key}_top.png`;
      await page.screenshot({path:top});
      await setMsgScroll(page, false);
      await page.waitForTimeout(1500);
      const out = `${OUT}/${s.key}.png`;
      await page.screenshot({path:out,fullPage:true});
      console.log(`OK ${s.key} (${s.user}) -> ${top} + ${out}`);
    }catch(e){
      console.error(`FAIL ${s.key} (${s.user}): ${e.message}`);
      await page.screenshot({path:`${OUT}/${s.key}_err.png`}).catch(()=>{});
    }finally{ await ctx.close(); }
  }
  await browser.close();
  console.log('done');
})().catch(e=>{console.error('ERR',e);process.exit(1)});
