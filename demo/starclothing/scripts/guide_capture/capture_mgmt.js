// Capture REAL management-console screenshots.
// Login as starclothing org admin (admin/12345678), visit each function page, screenshot data-bearing pages.
const { chromium } = require('playwright');
const fs = require('fs');

const WEB = 'http://[::1]:5173';
const API = 'http://127.0.0.1:8000';
const SLUG = 'starclothing', USER = 'admin', PASS = '12345678';
const OUT = '/root/ai_infra/demo/starclothing/shots/mgmt';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// (route, file, hasLeftTree)
const PAGES = [
  ['/org/structure', 'org-structure', true],
  ['/org/users', 'org-users', false],
  ['/org/admins', 'org-admins', false],
  ['/org/contact', 'org-contact', false],
  ['/keys', 'keys', true],
  ['/providers', 'providers', true],
  ['/dlp', 'dlp', true],
  ['/agent/workspaces', 'agent-workspaces', true],
  ['/agent/rag', 'agent-rag', true],
  ['/agent/memory', 'agent-memory', true],
  ['/tools/data-interfaces', 'tools-data-interfaces', true],
  ['/tools/skills', 'tools-skills', true],
  ['/tools/ontology', 'tools-ontology', true],
  ['/monitor/overview', 'monitor-overview', false],
  ['/monitor/router', 'monitor-router', false],
  ['/monitor/agents', 'monitor-agents', false],
  ['/monitor/tools', 'monitor-tools', false],
];

async function adminLogin() {
  const r = await fetch(`${API}/api/v1/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug: SLUG, username: USER, password: PASS }),
  });
  if (!r.ok) throw new Error(`admin login ${r.status} ${await r.text()}`);
  return await r.json();
}

(async () => {
  const { access_token, admin } = await adminLogin();
  console.log('admin login ok:', admin && (admin.username || admin.display_name));
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
  for (const [route, file, tree] of PAGES) {
    try {
      await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2500);
      if (tree) {
        try {
          const node = page.getByText('星途服装', { exact: false }).first();
          if (await node.isVisible({ timeout: 1200 })) { await node.click({ timeout: 1500 }); await page.waitForTimeout(2000); }
        } catch (e) { /* ignore */ }
      }
      const out = `${OUT}/${file}.png`;
      await page.screenshot({ path: out, fullPage: true });
      console.log(`OK ${file} (${route})`);
    } catch (e) {
      console.error(`FAIL ${file} (${route}): ${e.message.split('\n')[0]}`);
      await page.screenshot({ path: `${OUT}/${file}_err.png` }).catch(() => {});
    }
  }
  await browser.close();
  console.log('done');
})().catch(e => { console.error('ERR', e); process.exit(1); });
