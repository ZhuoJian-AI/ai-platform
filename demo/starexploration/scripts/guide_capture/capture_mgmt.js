// starexploration 管理端截图（admin 登录 → 16 个功能页 → 左树点选有数据的归口节点 → 截图）
// admin 是 org_admin（绑 organization_id）→ OrgSelect 自动锁星途勘探组织，无需手点；只点左树数据节点。
//   keys / providers / dlp / tools-data-interfaces / tools-ontology / agent-workspaces → 星途勘探 (org level)
//   agent-rag / tools-skills / agent-agents → 设计研究院 (dept, 设计规范RAG + design skill + des agent)
//   agent-memory → 设计合规工程师 (des-engineer user, 有记忆)
//   monitor-router → 点「路由指标」tab
const { chromium } = require('playwright');
const fs = require('fs');

const WEB = 'http://[::1]:5173';
const API = 'http://127.0.0.1:8000';
const SLUG = 'starexploration', USER = 'admin', PASS = '12345678';
const ORG = '星途勘探';
const OUT = '/root/ai_infra/demo/starexploration/shots/mgmt';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

const PAGES = [
  ['/org/structure',        'org-structure',        null],
  ['/org/users',            'org-users',            null],
  ['/keys',                 'keys',                 ORG],
  ['/providers',            'providers',            ORG],
  ['/dlp',                  'dlp',                  ORG],
  ['/agent/workspaces',     'agent-workspaces',     ORG],
  ['/agent/agents',         'agent-agents',         '设计研究院'],
  ['/agent/rag',            'agent-rag',            '设计研究院'],
  ['/agent/memory',        'agent-memory',         '设计合规工程师'],
  ['/tools/data-interfaces','tools-data-interfaces', ORG],
  ['/tools/skills',         'tools-skills',         '设计研究院'],
  ['/tools/ontology',       'tools-ontology',       ORG],
  ['/monitor/overview',     'monitor-overview',     null],
  ['/monitor/router',       'monitor-router',       null],
  ['/monitor/agents',       'monitor-agents',       null],
  ['/monitor/tools',        'monitor-tools',        null],
];

async function adminLogin() {
  const r = await fetch(`${API}/api/v1/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug: SLUG, username: USER, password: PASS }),
  });
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
      await page.waitForTimeout(2800);
      if (route === '/org/structure') {
        try { await page.getByText(ORG, { exact: true }).first().click({ timeout: 8000 }); await page.waitForTimeout(1500); } catch {}
        await page.getByText('设计研究院', { exact: true }).first().click({ timeout: 10000 });
        await page.waitForTimeout(2200);
      } else if (nodeText) {
        await clickTreeNode(page, nodeText);
        await page.waitForTimeout(2500);
      } else if (route === '/monitor/router') {
        const tab = page.getByRole('tab', { name: '路由指标' });
        try { await tab.waitFor({ state: 'visible', timeout: 8000 }); await tab.click({ timeout: 3000 }); }
        catch { await page.getByText('路由指标', { exact: true }).first().click({ timeout: 3000 }); }
        await page.waitForTimeout(2500);
      }
      const out = `${OUT}/${file}.png`;
      await page.screenshot({ path: out, fullPage: true });
      console.log(`OK ${file} (${route}) node=${nodeText || (route === '/org/structure' ? '组织→设计研究院' : (route === '/monitor/router' ? '路由指标tab' : '-'))}`);
    } catch (e) {
      console.error(`FAIL ${file} (${route}): ${e.message.split('\n')[0]}`);
      await page.screenshot({ path: `${OUT}/${file}_err.png` }).catch(() => {});
    }
  }
  await browser.close();
  console.log('done');
})().catch(e => { console.error('ERR', e); process.exit(1) });
