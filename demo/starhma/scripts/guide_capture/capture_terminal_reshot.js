// starhma 终端任务重新截图（不重跑：列表点入已存在的 9 个任务）
// login → /starhma/terminal 列表 → 按标题点第一个(最新)任务 → 等「已完成」→ 截 top+bottom
//   （直接 /terminal/tasks/{id} 路由会被 SPA 路由守卫重定向到 /login，故必须列表点入）
// 运行：cd /root/ai_infra/frontend && NODE_PATH=$PWD/node_modules node /root/ai_infra/demo/starhma/scripts/guide_capture/capture_terminal_reshot.js
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'http://[::1]:5173', API = 'http://127.0.0.1:8000', SLUG = 'starhma', PASS = '12345678';
const OUT = '/root/ai_infra/demo/starhma/shots';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// 9 场景：归口用户 + 任务标题（不重跑，点入列表里已有的最新任务）
const SCEN = [
  { key:'rdm01', user:'rd-formulator',  title:'配方智能推荐与初始配比' },
  { key:'rdm02', user:'rd-analyst',     title:'实验数据分析与报告生成' },
  { key:'sal01', user:'sales-rep',      title:'智能询盘与初步粘接方案' },
  { key:'mfg01', user:'mfg-planner',    title:'智能排产与订单冲突识别' },
  { key:'eqp01', user:'eqp-maintainer', title:'设备预测性维护与保养提醒' },
  { key:'scm01', user:'scm-manager',    title:'库存智能预警与补货建议' },
  { key:'qas01', user:'qas-engineer',   title:'售后粘接故障智能诊断' },
  { key:'adm01', user:'admin-officer',  title:'跨系统经营数据汇总' },
  { key:'doc01', user:'doc-clerk',      title:'文档智能处理与检索' },
];

async function routeApi(page){
  await page.route('**/api/v1/**', async route => {
    const req = route.request();
    try {
      const u = new URL(req.url()); const target = API + u.pathname + u.search;
      const h = {};
      for (const [k,v] of Object.entries(req.headers())) if (['authorization','content-type','accept'].includes(k.toLowerCase())) h[k]=v;
      const resp = await fetch(target, { method: req.method(), headers: h, body: ['GET','HEAD'].includes(req.method())?undefined:(req.postData()||undefined) });
      const buf = Buffer.from(await resp.arrayBuffer()); const rh = {};
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

async function setMsgScroll(page, toTop){
  await page.evaluate(top => {
    const picks = [];
    document.querySelectorAll('div').forEach(d => {
      const s = getComputedStyle(d);
      if ((s.overflowY==='auto'||s.overflowY==='scroll') && d.scrollHeight > d.clientHeight + 4) picks.push(d);
    });
    picks.sort((a,b)=>b.scrollHeight-a.scrollHeight);
    const main = picks.find(d => d.querySelector('.wb-md')) || picks[0];
    if (main) main.scrollTop = top ? 0 : main.scrollHeight;
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
      await page.goto(`${BASE}/${SLUG}/terminal`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(3000);
      const item = page.getByText(s.title, { exact: false }).first();
      await item.waitFor({ state: 'visible', timeout: 20000 });
      await item.click();
      // 等任务结果渲染
      let rendered = false;
      try { await page.getByText('已完成', { exact: false }).first().waitFor({ state: 'visible', timeout: 25000 }); rendered = true; }
      catch { try { await page.getByText('场景模板注入', { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 }); rendered = true; } catch {} }
      // 防御：若被重定向到登录页，记录之
      const url = page.url();
      if (url.includes('/login')) { console.error(`FAIL ${s.key}: redirected to login`); await ctx.close(); continue; }
      await page.waitForTimeout(2500);
      await setMsgScroll(page, true);
      await page.waitForTimeout(1200);
      await page.screenshot({ path: `${OUT}/${s.key}_top.png` });
      await setMsgScroll(page, false);
      await page.waitForTimeout(1800);
      await page.screenshot({ path: `${OUT}/${s.key}.png`, fullPage: true });
      console.log(`OK ${s.key} rendered=${rendered} url=${url}`);
    } catch(e){
      console.error(`FAIL ${s.key}: ${e.message.split('\n')[0]}`);
    } finally { await ctx.close(); }
  }
  await browser.close();
  console.log('done');
})().catch(e=>{ console.error('ERR', e); process.exit(1); });
