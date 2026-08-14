// Re-capture the API Key management page: click the org-tree node that HAS key data, then screenshot.
const { chromium } = require('playwright');
const WEB = 'http://[::1]:5173', API = 'http://127.0.0.1:8000';
const OUT = '/root/ai_infra/demo/starclothing/shots/mgmt/keys.png';

async function adminLogin() {
  const r = await fetch(`${API}/api/v1/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug: 'starclothing', username: 'admin', password: '12345678' }) });
  if (!r.ok) throw new Error(`login ${r.status}`);
  return await r.json();
}
(async () => {
  const { access_token, admin } = await adminLogin();
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(([t, a]) => { localStorage.setItem('ai_infra_token', t); localStorage.setItem('ai_infra_admin', JSON.stringify(a)); }, [access_token, admin]);
  await ctx.route('**/api/v1/**', async route => {
    const req = route.request(); const url = new URL(req.url()); const target = API + url.pathname + url.search;
    const h = {}; for (const [k, v] of Object.entries(req.headers())) if (['authorization', 'content-type', 'accept'].includes(k.toLowerCase())) h[k] = v;
    try { const resp = await fetch(target, { method: req.method(), headers: h, body: ['GET', 'HEAD'].includes(req.method()) ? undefined : (req.postData() || undefined) });
      const buf = Buffer.from(await resp.arrayBuffer()); const rh = {}; resp.headers.forEach((v, k) => { if (!['content-encoding', 'content-length', 'transfer-encoding', 'connection'].includes(k.toLowerCase())) rh[k] = v; });
      await route.fulfill({ status: resp.status, headers: rh, body: buf });
    } catch (e) { await route.continue(); }
  });
  const page = await ctx.newPage();
  await page.goto(`${WEB}/keys`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2500);
  // try each '星途服装' occurrence; after click, check if key table populated (sk- prefix or empty-state gone)
  let ok = false;
  const loc = page.getByText('星途服装', { exact: false });
  const n = await loc.count();
  console.log('matches:', n);
  for (let i = 0; i < n; i++) {
    try {
      const el = loc.nth(i);
      if (!(await el.isVisible())) continue;
      await el.click({ timeout: 1500 });
      await page.waitForTimeout(1800);
      // close any popover/dropdown that may have opened
      await page.keyboard.press('Escape').catch(() => {});
      // check right panel for key data: look for 'sk-' text or key_name cells
      const hasKey = await page.getByText(/sk-|XT-|xt-/, { exact: false }).first().isVisible({ timeout: 800 }).catch(() => false);
      console.log(`  click #${i}: hasKey=${hasKey}`);
      if (hasKey) { ok = true; break; }
    } catch (e) { console.log(`  click #${i} err: ${e.message.split('\n')[0]}`); }
  }
  if (!ok) {
    // fallback: ensure org selected, then click org node again after popover closed
    await page.waitForTimeout(1000);
  }
  await page.screenshot({ path: OUT, fullPage: true });
  console.log(ok ? 'OK keys captured with data' : 'WARN keys may still be empty -> ' + OUT);
  await browser.close();
})().catch(e => { console.error('ERR', e); process.exit(1); });
