const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'http://[::1]:5173', SLUG = 'starclothing', PASS = '12345678';
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
const OUT = '/root/ai_infra/demo/starclothing/shots';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });
const SCEN = [
  { key:'pd1', user:'dev-lead',     title:'逾期订单风险汇总与推送' },
  { key:'pd2', user:'fabric-dev',   title:'关键面料成本交期产能测算与异动检测' },
  { key:'pd3', user:'qc-lead',      title:'新品缺陷风险预警与闭环待办' },
  { key:'sc1', user:'supply-lead',  title:'来料批次物料校验与异常回写' },
  { key:'sc2', user:'prod-lead',    title:'下周工单产线排程与风险提示' },
  { key:'sc3', user:'finance-lead', title:'跨系统单据对账与差异闭环' },
  { key:'sc4', user:'merch-lead',   title:'采购报价比对与成本台账建议' },
];
// 终端消息区是 overflowY:auto 的内层容器（Terminal.tsx scrollRef），fullPage 抓不到
// 被滚走的内容；任务打开时自动 smooth-scroll 到底（最后一屏）。这里手动把该容器
// 滚到顶/底分别截第一屏 / 最后一屏（均 viewport 截图，不 fullPage）。
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
      // 第一屏：消息区滚到顶（任务入口 + composer 提示词 + 首条消息）
      await setMsgScroll(page, true);
      await page.waitForTimeout(1200);
      const top = `${OUT}/${s.key}_top.png`;
      await page.screenshot({path:top});
      // 最后一屏：滚回底（最终助手输出 / 闭环待办）
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
