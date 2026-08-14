// agileac 智能体管理页截图：/agent/agents → 点选有 agent 数据的部门节点（售后服务部，售后故障诊断）→ 截图
// 同 capture_mgmt_nodes.js 套路。agents 全部门级 scope，点部门节点右栏才出 agent 列表。
const { chromium } = require('playwright');
const fs = require('fs');
const WEB = 'http://[::1]:5173', API = 'http://127.0.0.1:8000';
const SLUG = 'agileac', USER = 'admin', PASS = '12345678';
const OUT = '/root/ai_infra/demo/agileac/shots/mgmt';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });
async function adminLogin() {
  const r = await fetch(`${API}/api/v1/auth/login`, { method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ slug: SLUG, username: USER, password: PASS }) });
  if (!r.ok) throw new Error(`admin login ${r.status} ${await r.text()}`);
  return await r.json();
}
async function clickTreeNode(page, label) {
  const aside = page.locator('aside').nth(1);
  const node = aside.getByText(label, { exact: true }).first();
  await node.waitFor({ state: 'visible', timeout: 15000 });
  await node.click({ timeout: 3000 });
}
(async () => {
  const { access_token, admin } = await adminLogin();
  console.log('admin login ok:', admin && admin.organization_name);
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(([tok, ad]) => { localStorage.setItem('ai_infra_token', tok); localStorage.setItem('ai_infra_admin', JSON.stringify(ad)); }, [access_token, admin]);
  await ctx.route('**/api/v1/**', async route => {
    const req = route.request(); const url = new URL(req.url()); const target = API + url.pathname + url.search;
    const h = {}; for (const [k, v] of Object.entries(req.headers())) if (['authorization','content-type','accept'].includes(k.toLowerCase())) h[k] = v;
    try { const resp = await fetch(target, { method: req.method(), headers: h, body: ['GET','HEAD'].includes(req.method()) ? undefined : (req.postData() || undefined) });
      const buf = Buffer.from(await resp.arrayBuffer()); const rh = {};
      resp.headers.forEach((v,k)=>{ if(!['content-encoding','content-length','transfer-encoding','connection'].includes(k.toLowerCase())) rh[k]=v; });
      await route.fulfill({ status: resp.status, headers: rh, body: buf });
    } catch (e) { await route.continue(); }
  });
  const page = await ctx.newPage();
  const file = 'agent-agents', nodeText = '售后服务部';
  try {
    await page.goto(`${WEB}/agent/agents`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2800);
    await clickTreeNode(page, nodeText);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/${file}.png`, fullPage: true });
    console.log(`OK ${file} (/agent/agents) node=${nodeText}`);
  } catch (e) {
    console.error(`FAIL ${file}: ${e.message.split('\n')[0]}`);
    await page.screenshot({ path: `${OUT}/${file}_err.png` }).catch(()=>{});
  }
  await browser.close();
  console.log('done');
})().catch(e => { console.error('ERR', e); process.exit(1) });
