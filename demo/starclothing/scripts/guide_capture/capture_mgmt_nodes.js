// Re-capture the 8 chapter-3 management screenshots with the correct data-bearing
// scope node selected (per SCENARIO_ROSTER + DB). The starclothing `admin` is
// org-scoped to 星途服装, so OrgSelect auto-locks the org — the only thing to do
// is click the right data-bearing node in the left MacTree (scoped to <aside>),
// then screenshot. monitor/router needs the 路由指标 tab clicked first.
//
// Node picks (from DB at authoring time, see SCENARIO_ROSTER.md):
//   dlp               → 星途服装 (org, 9 rules)            [org level]
//   agent-workspaces  → 开发部长 (dev-lead user)          [user level]
//   agent-rag         → 品控部   (qc dept, 1 collection)  [dept level]
//   agent-memory      → 开发部长 (dev-lead user)          [user level]
//   tools-data-interfaces → 开发部 (dev dept, PLM system) [dept level]
//   tools-skills      → 商品部   (merch dept, 3 skills)   [dept level]
//   tools-ontology    → 设计部   (design dept, 5 files)   [dept level]
//   monitor-router    → click 路由指标 tab
const { chromium } = require('playwright');
const fs = require('fs');

const WEB = 'http://[::1]:5173';
const API = 'http://127.0.0.1:8000';
const SLUG = 'starclothing', USER = 'admin', PASS = '12345678';
const OUT = '/root/ai_infra/demo/starclothing/shots/mgmt';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// [route, file, nodeText?]  nodeText 留空 = 非树型页（只点 tab 或直接截）
const PAGES = [
  ['/dlp',                   'dlp',                   '星途服装'],
  ['/agent/workspaces',      'agent-workspaces',      '开发部长'],
  ['/agent/rag',             'agent-rag',             '品控部'],
  ['/agent/memory',          'agent-memory',          '开发部长'],
  ['/tools/data-interfaces', 'tools-data-interfaces', '开发部'],
  ['/tools/skills',          'tools-skills',          '商品部'],
  ['/tools/ontology',        'tools-ontology',        '设计部'],
  ['/monitor/router',        'monitor-router',        null],   // 点 路由指标 tab
];

async function adminLogin() {
  const r = await fetch(`${API}/api/v1/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug: SLUG, username: USER, password: PASS }),
  });
  if (!r.ok) throw new Error(`admin login ${r.status} ${await r.text()}`);
  return await r.json();
}

// 在左侧 MacTree 里点指定节点。注意：页面有两个 <aside> —— 第一个是全局导航栏
// （含「组织管理/模型路由器/...」菜单），第二个才是 FinderShell 的组织架构树。用 nth(1)。
// exact 避免子串误匹配（如「开发部」命中「开发部长」）。
async function clickTreeNode(page, label) {
  const aside = page.locator('aside').nth(1);
  const node = aside.getByText(label, { exact: true }).first();
  await node.waitFor({ state: 'visible', timeout: 15000 });
  await node.click({ timeout: 3000 });
}

(async () => {
  const { access_token, admin } = await adminLogin();
  console.log('admin login ok:', admin && (admin.username || admin.display_name), 'org:', admin && admin.organization_name);
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(([tok, ad]) => {
    localStorage.setItem('ai_infra_token', tok);
    localStorage.setItem('ai_infra_admin', JSON.stringify(ad));
  }, [access_token, admin]);
  await ctx.route('**/api/v1/**', async route => {
    const req = route.request(); const url = new URL(req.url());
    const target = API + url.pathname + url.search;
    const h = {}; for (const [k, v] of Object.entries(req.headers())) if (['authorization', 'content-type', 'accept'].includes(k.toLowerCase())) h[k] = v;
    try {
      const resp = await fetch(target, { method: req.method(), headers: h, body: ['GET', 'HEAD'].includes(req.method()) ? undefined : (req.postData() || undefined) });
      const buf = Buffer.from(await resp.arrayBuffer());
      const rh = {}; resp.headers.forEach((v, k) => { if (!['content-encoding', 'content-length', 'transfer-encoding', 'connection'].includes(k.toLowerCase())) rh[k] = v; });
      await route.fulfill({ status: resp.status, headers: rh, body: buf });
    } catch (e) { await route.continue(); }
  });
  const page = await ctx.newPage();
  for (const [route, file, nodeText] of PAGES) {
    try {
      await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2800);            // 等 OrgSelect 自动锁组织 + 树渲染
      if (nodeText) {
        await clickTreeNode(page, nodeText);
        await page.waitForTimeout(2500);          // 等右栏按 scope 取数渲染
      } else if (route === '/monitor/router') {
        // 路由器监控：点「路由指标」tab
        const tab = page.getByRole('tab', { name: '路由指标' });
        try { await tab.waitFor({ state: 'visible', timeout: 8000 }); await tab.click({ timeout: 3000 }); }
        catch { await page.getByText('路由指标', { exact: true }).first().click({ timeout: 3000 }); }
        await page.waitForTimeout(2500);
      }
      const out = `${OUT}/${file}.png`;
      await page.screenshot({ path: out, fullPage: true });
      console.log(`OK ${file} (${route}) node=${nodeText || '路由指标tab'}`);
    } catch (e) {
      console.error(`FAIL ${file} (${route}): ${e.message.split('\n')[0]}`);
      await page.screenshot({ path: `${OUT}/${file}_err.png` }).catch(() => {});
    }
  }
  await browser.close();
  console.log('done');
})().catch(e => { console.error('ERR', e); process.exit(1) });
