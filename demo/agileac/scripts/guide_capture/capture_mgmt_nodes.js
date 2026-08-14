// agileac 管理端截图（admin 登录 → 逐功能页 → 左树点选有数据的归口节点 → 截图）
// 复用自 starclothing capture_mgmt_nodes.js。agileac admin 是 org_admin（绑 organization_id）
// → OrgSelect 自动锁敏睿空调组织，无需手点；只点左树数据节点。
//
// Node picks（按 agileac DB 实测，资源 scope 分布与 starclothing 不同）：
//   dlp               → 敏睿空调 (org, 9 rules)              [org level — 全部 org scope]
//   agent-workspaces  → 售后工程师 (svc-engineer user, 1 file)[user level — 有文件的归口用户]
//   agent-rag         → 售后服务部 (dept, 售后故障与维修知识库)[dept level — P0 场景归口]
//   agent-memory      → 售后工程师 (svc-engineer user, 1 mem) [user level — memory 仅 user scope]
//   tools-data-interfaces → 敏睿空调 (org, 6 系统/101 端点)    [org level — 6 系统全 org scope]
//   tools-skills      → 售后服务部 (dept, 售后部查询技能)      [dept level — P0 场景归口]
//   tools-ontology    → 敏睿空调 (org, 7 文件夹/34 文件)       [org level — 本体主体在 org]
//   monitor-router    → 点「路由指标」tab
const { chromium } = require('playwright');
const fs = require('fs');

const WEB = 'http://[::1]:5173';
const API = 'http://127.0.0.1:8000';
const SLUG = 'agileac', USER = 'admin', PASS = '12345678';
const OUT = '/root/ai_infra/demo/agileac/shots/mgmt';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// [route, file, nodeText?]  nodeText 留空 = 非树型页（只点 tab 或直接截）
const PAGES = [
  ['/dlp',                   'dlp',                   '敏睿空调'],
  ['/agent/workspaces',      'agent-workspaces',      '售后工程师'],
  ['/agent/rag',             'agent-rag',             '售后服务部'],
  ['/agent/memory',          'agent-memory',          '售后工程师'],
  ['/tools/data-interfaces', 'tools-data-interfaces', '敏睿空调'],
  ['/tools/skills',          'tools-skills',          '售后服务部'],
  ['/tools/ontology',        'tools-ontology',        '敏睿空调'],
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

// 页面有两个 <aside>：第 1 个是全局导航菜单，第 2 个才是 FinderShell 组织架构树。用 nth(1)。
// exact 避免子串误匹配（如「售后服务部」命中「售后工程师组」）。
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
