// agileac 管理端补充截图：补全 §3.2 组织架构/用户管理、§3.3 API Key/提供商、§3.6 监控总览/智能体/工具
// 与 capture_mgmt_nodes.js 同套路（admin 登录 + route 转发 + 树节点 nth(1)）。
const { chromium } = require('playwright');
const fs = require('fs');
const WEB = 'http://[::1]:5173', API = 'http://127.0.0.1:8000';
const SLUG = 'agileac', USER = 'admin', PASS = '12345678';
const OUT = '/root/ai_infra/demo/agileac/shots/mgmt';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });
// [route, file, nodeText?] nodeText 留空 = 非树型页
const PAGES = [
  ['/org/structure', 'org-structure', null],
  ['/org/users',      'org-users',      null],
  ['/keys',           'keys',           '敏睿空调'],
  ['/providers',      'providers',      '敏睿空调'],
  ['/monitor/overview','monitor-overview', null],
  ['/monitor/agents', 'monitor-agents', null],
  ['/monitor/tools',  'monitor-tools',  null],
];
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
  for (const [route, file, nodeText] of PAGES) {
    try {
      await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2800);
      if (nodeText) { await clickTreeNode(page, nodeText); await page.waitForTimeout(2500); }
      await page.screenshot({ path: `${OUT}/${file}.png`, fullPage: true });
      console.log(`OK ${file} (${route}) node=${nodeText||'-'}`);
    } catch (e) {
      console.error(`FAIL ${file} (${route}): ${e.message.split('\n')[0]}`);
      await page.screenshot({ path: `${OUT}/${file}_err.png` }).catch(()=>{});
    }
  }
  await browser.close();
  console.log('done');
})().catch(e => { console.error('ERR', e); process.exit(1) });
