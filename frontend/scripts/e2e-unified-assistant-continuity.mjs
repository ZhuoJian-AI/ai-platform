import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { chromium } from 'playwright';

const base = process.env.E2E_BASE_URL || 'https://ai-platform.staging.zhuojianai.com';
const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
if (!username || !password) throw new Error('Provide test credentials via environment');
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const root = resolve('dist');
try {
  // Candidate static assets only. Authentication, SSO, business API and data are real.
  await page.route(`${base}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    const shell = route.request().isNavigationRequest() && path.startsWith('/alphabet/terminal');
    if (!shell && !path.startsWith('/assets/')) return route.continue();
    const file = resolve(root, shell ? 'index.html' : `.${path}`);
    if (!file.startsWith(root + sep)) throw new Error('Invalid asset path');
    const contentType = shell ? 'text/html' : file.endsWith('.js') ? 'application/javascript'
      : file.endsWith('.css') ? 'text/css' : undefined;
    await route.fulfill({ body: await readFile(file), contentType });
  });
  await page.goto(`${base}/alphabet/terminal/login`);
  await page.getByRole('textbox', { name: '用户名' }).fill(username);
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(password);
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForURL(`${base}/alphabet/terminal`);
  const title = '统一助手真实验收：请只回复“统一助手对话正常”，不要调用任何工具';
  await page.getByText(title, { exact: true }).click();
  await page.waitForURL('**/tasks/*');
  const taskId = new URL(page.url()).pathname.split('/').pop();
  assert.ok(taskId);
  await page.getByRole('button', { name: 'appstore 爱法贝生产协同 AI', exact: true }).click();
  await page.waitForURL(url => url.searchParams.get('view') === 'application');
  assert.equal(new URL(page.url()).searchParams.get('conversation'), taskId);
  await page.getByRole('button', { name: /灼见助手$/ }).click();
  await page.getByRole('dialog').getByText('统一助手对话正常', { exact: true }).waitFor();
  await page.reload();
  assert.equal(new URL(page.url()).searchParams.get('conversation'), taskId);
  await page.getByRole('button', { name: /灼见助手$/ }).click();
  await page.getByRole('dialog').getByText('统一助手对话正常', { exact: true }).waitFor();
  const reuse = process.env.E2E_REUSE_CONTINUITY_REPLY === '1';
  const marker = reuse
    ? await page.getByRole('dialog').getByText(/^E2E-CONTINUITY-\d+$/).last().innerText()
    : `E2E-CONTINUITY-${Date.now()}`;
  if (!reuse) {
    await page.getByPlaceholder('描述你要查询或执行的业务任务…').fill(`请只回复 ${marker}，不要调用工具。这是会话接续测试。`);
    await page.getByRole('button', { name: /在当前页面执行$/ }).click();
  }
  await page.getByRole('dialog').getByText(marker, { exact: true }).waitFor({ timeout: 180000 });
  await page.getByRole('dialog').locator('button.ant-drawer-close').click();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  if (!await page.getByText(title, { exact: true }).isVisible()) {
    await page.getByRole('button', { name: '打开平台导航', exact: true }).click();
  }
  await page.getByText(title, { exact: true }).click();
  await page.waitForURL('**/tasks/*');
  assert.equal(new URL(page.url()).pathname.split('/').pop(), taskId);
  await page.getByText(marker, { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', taskId, reusedGeneratedReply: reuse, frontend: 'candidate', backend: 'staging', checks: ['real_login', 'history_global', 'sidebar_same_task', 'sidebar_same_reply', 'reload_same_task', 'sidebar_reply_visible_in_global'] }));
} finally {
  await context.close();
  await browser.close();
}
