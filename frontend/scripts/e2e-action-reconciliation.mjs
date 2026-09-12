import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = 'http://127.0.0.1:5173';
const appId = process.env.E2E_RECONCILIATION_APP_ID;
assert(appId && process.env.E2E_ADMIN_USERNAME && process.env.E2E_ADMIN_PASSWORD);
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const page = await browser.newPage();
page.setDefaultTimeout(60000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto(base + '/login');
  await page.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME);
  await page.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD);
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await page.waitForURL(url => !url.pathname.endsWith('/login'));
  await page.goto(base + '/enterprise-apps/' + appId);
  await page.getByRole('tab', { name: '调用记录', exact: true }).click();
  await page.getByText('结果未知的业务写入核实', { exact: true }).waitFor();
  const buttons = page.getByRole('button', { name: '提交证据', exact: true });
  await buttons.first().waitFor();
  assert.equal(await buttons.count(), 2);
  const enabled = page.locator('button').filter({ hasText: /^提交证据$/ }).and(page.locator('button:enabled'));
  assert.equal(await enabled.count(), 1);
  await enabled.click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox').click();
  await page.getByText('已核实没有执行', { exact: true }).click();
  await dialog.getByLabel('核查证据').fill('E2E: 故障注入记录未发送远端请求，候选数据库验证。');
  const saved = page.waitForResponse(response => response.request().method() === 'POST'
    && response.url().includes('/action-reconciliations/'));
  await dialog.getByRole('button', { name: '记录核实结论', exact: true }).click();
  assert.equal((await saved).status(), 200);
  await page.getByText('人工核实未执行', { exact: true }).waitFor();
  await page.reload();
  await page.getByRole('tab', { name: '调用记录', exact: true }).click();
  await page.getByText('人工核实未执行', { exact: true }).waitFor();
  assert.equal(await page.locator('button:enabled').filter({ hasText: /^提交证据$/ }).count(), 0);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ candidate: true, realLogin: true, saved: true, persistedAfterReload: true,
    executingDisabled: true, javascriptErrors: errors.length }));
} finally {
  await browser.close();
}
