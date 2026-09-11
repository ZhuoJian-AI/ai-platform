import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { chromium } from 'playwright';

const base = process.env.E2E_BASE_URL || 'https://ai-platform.staging.zhuojianai.com';
const app = '9689828b-9d07-4a93-8b52-0eefad8be885';
const name = process.env.E2E_CLEANUP_NAME || `E2E-ASSISTANT-CONFIRM-${Date.now()}`;
assert.match(name, /^E2E-ASSISTANT-CONFIRM-\d+$/);
if (!process.env.E2E_USERNAME || !process.env.E2E_PASSWORD) throw new Error('Missing environment credentials');
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const root = resolve('dist');
const errors = [];
page.on('pageerror', e => errors.push(e.message));
async function action(key, params, expectedVersion) {
  return page.evaluate(async ({ app, key, params, expectedVersion }) => {
    const response = await fetch(`/api/v1/terminal/applications/${app}/actions/${key}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionStorage.getItem('ai_infra_user_token')}` },
      body: JSON.stringify({ module_key: 'material_suppliers', page_key: 'material_suppliers.main', params, expected_version: expectedVersion, request_id: crypto.randomUUID() }),
    });
    return { http: response.status, body: await response.json() };
  }, { app, key, params, expectedVersion });
}
try {
  await page.route(`${base}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    const shell = route.request().isNavigationRequest() && path.startsWith('/alphabet/terminal');
    if (!shell && !path.startsWith('/assets/')) return route.continue();
    const file = resolve(root, shell ? 'index.html' : `.${path}`);
    if (!file.startsWith(root + sep)) throw new Error('Invalid asset path');
    await route.fulfill({ body: await readFile(file), contentType: shell ? 'text/html' : file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : undefined });
  });
  await page.goto(`${base}/alphabet/terminal/login`);
  await page.getByRole('textbox', { name: '用户名' }).fill(process.env.E2E_USERNAME);
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(process.env.E2E_PASSWORD);
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForURL(`${base}/alphabet/terminal`);
  if (!process.env.E2E_CLEANUP_NAME) {
  await page.goto(`${base}/alphabet/terminal?view=application&app=${app}&module=material_suppliers&page=material_suppliers.main`);
  await page.getByRole('button', { name: /灼见助手$/ }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByPlaceholder('描述你要查询或执行的业务任务…').fill(`帮我新增一家面料厂商，名称“${name}”，备注“统一助手真实验收临时数据”，合作状态待联系。请先展示确认卡片，等我点击再执行。`);
  await dialog.getByRole('button', { name: /在当前页面执行$/ }).click();
  const confirm = dialog.getByRole('button', { name: /确认执行|确认操作|允许本次/ }).first();
  await confirm.waitFor({ timeout: 180000 });
  const before = await action('material_suppliers.query', { query: name });
  assert.equal(before.http, 200);
  assert.equal(before.body.result.items.length, 0, 'Business mutation happened before confirmation');
  console.log(JSON.stringify({ phase: 'confirmation_visible_no_write', name }));
  await confirm.click();
  await page.waitForFunction(() => {
    const input = document.querySelector('.business-assistant-drawer__composer textarea');
    return input && !input.disabled;
  }, null, { timeout: 180000 });
  const after = await action('material_suppliers.query', { query: name });
  assert.equal(after.http, 200);
  const matching = after.body.result.items.filter(row => row.name === name);
  assert.equal(matching.length, 1, 'Confirmed creation did not create exactly one test record');
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', name, checks: ['real_subsystem', 'confirmation_before_write', 'confirmed_single_create'] }));
  }
} finally {
  // Cleanup may only target the exact, unique record created by this test.
  try {
    const query = await action('material_suppliers.query', { query: name });
    for (const row of query.body?.result?.items || []) {
      if (row.name !== name) continue;
      const version = row.version ?? row.dataVersion ?? query.body.result.version ?? query.body.result.dataVersion;
      assert.ok(version !== undefined, 'Cleanup requires a trusted query version');
      const deletion = await action('material_suppliers.delete', { id: row.id }, version);
      if (deletion.body.status === 'pending' && deletion.body.confirmation_id) {
        const resolved = await page.evaluate(async id => {
          const r = await fetch(`/api/v1/terminal/application-action-confirmations/${id}/approve`, { method: 'POST', headers: { Authorization: `Bearer ${sessionStorage.getItem('ai_infra_user_token')}` } });
          if (!r.ok) throw new Error('E2E cleanup confirmation failed');
          return r.json();
        }, deletion.body.confirmation_id);
        console.log(JSON.stringify({ cleanupReceipt: resolved }));
      } else if (deletion.body.status !== 'completed') throw new Error('E2E cleanup failed');
    }
    const remaining = await action('material_suppliers.query', { query: name });
    assert.equal(remaining.body.result.items.filter(row => row.name === name).length, 0);
    console.log(JSON.stringify({ cleanup: 'passed', name }));
  } finally {
    await context.close();
    await browser.close();
  }
}
