// agilesteel 管理端截图（admin 登录 → 16 个功能页 → 左树点选有数据的归口节点 → 截图）
// 合并 agileac 的 capture_mgmt_nodes + capture_mgmt_extra + capture_agents 三脚本。
// agilesteel admin 是 org_admin（绑 organization_id）→ OrgSelect 自动锁敏睿钢铁组织，无需手点；只点左树数据节点。
//
// Node picks（按 agilesteel DB 实测，资源 scope 分布）：
//   dlp / keys / providers / tools-data-interfaces / tools-ontology → 敏睿钢铁 (org level)
//   agent-workspaces / agent-memory → 设备工程师 (eqp-engineer user, 有文件/记忆)
//   agent-rag / tools-skills / agent-agents → 设备管理部 (dept, 设备故障案例库 + 设备部技能 + eqp agent)
//   monitor-router → 点「路由指标」tab
const { chromium } = require('playwright');
const fs = require('fs');

const WEB = 'http://[::1]:5173';
const API = 'http://127.0.0.1:8000';
const SLUG = 'agilesteel', USER = 'admin', PASS = '12345678';
const OUT = '/root/ai_infra/demo/agilesteel/shots/mgmt';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// [route, file, nodeText?] nodeText 留空 = 非树型页（直接截或点 tab）
const PAGES = [
  ['/org/structure',        'org-structure',        null],
  ['/org/users',            'org-users',            null],
  ['/keys',                 'keys',                 '敏睿钢铁'],
  ['/providers',            'providers',            '敏睿钢铁'],
  ['/dlp',                  'dlp',                  '敏睿钢铁'],
  ['/agent/workspaces',     'agent-workspaces',     '设备工程师'],
  ['/agent/agents',         'agent-agents',         '设备管理部'],
  ['/agent/rag',            'agent-rag',            '设备管理部'],
  ['/agent/memory',        'agent-memory',         '设备工程师'],
  ['/tools/data-interfaces','tools-data-interfaces','敏睿钢铁'],
  ['/tools/skills',         'tools-skills',         '设备管理部'],
  ['/tools/ontology',       'tools-ontology',       '敏睿钢铁'],
  ['/monitor/overview',     'monitor-overview',     null],
  ['/monitor/router',       'monitor-router',       null],   // 点 路由指标 tab
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
        // 组织架构三栏：点组织(敏睿钢铁)→部门列表出→点部门(设备管理部)→团队出，三栏全显示
        try {
          await page.getByText('敏睿钢铁', { exact: true }).first().click({ timeout: 8000 });
          await page.waitForTimeout(1500);
        } catch {}
        await page.getByText('设备管理部', { exact: true }).first().click({ timeout: 10000 });
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
      console.log(`OK ${file} (${route}) node=${nodeText || (route === '/org/structure' ? '组织→设备管理部' : (route === '/monitor/router' ? '路由指标tab' : '-'))}`);
    } catch (e) {
      console.error(`FAIL ${file} (${route}): ${e.message.split('\n')[0]}`);
      await page.screenshot({ path: `${OUT}/${file}_err.png` }).catch(() => {});
    }
  }
  await browser.close();
  console.log('done');
})().catch(e => { console.error('ERR', e); process.exit(1) });
