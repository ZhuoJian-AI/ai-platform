// Focused, credential-free report. Credentials are process environment only.
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';

const require = createRequire(process.env.E2E_MODULE_ANCHOR || import.meta.url);
const { chromium } = require('playwright');
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  for (const kind of ['admin', 'employee']) {
    const prefix = kind === 'admin' ? 'E2E_ADMIN' : 'E2E_EMPLOYEE';
    const username = process.env[`${prefix}_USERNAME`];
    const password = process.env[`${prefix}_PASSWORD`];
    assert(username && password, `Missing ${prefix} credentials`);
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      const failures = [];
      page.on('response', response => {
        if (response.status() >= 500) failures.push({ path: new URL(response.url()).pathname, status: response.status() });
      });
      const loginPath = kind === 'admin' ? '/login' : `/${process.env.E2E_ORG_SLUG || 'alphabet'}/terminal/login`;
      await page.goto(base + loginPath);
      await page.getByPlaceholder('用户名', { exact: true }).fill(username);
      await page.getByPlaceholder('密码', { exact: true }).fill(password);
      const loginResponse = page.waitForResponse(r => r.request().method() === 'POST' && r.url().includes('/login'));
      await page.getByRole('button', { name: /登\s*录/ }).click();
      assert.equal((await loginResponse).status(), 200, `${kind} login`);
      await page.waitForURL(url => !url.pathname.endsWith('/login'));
      await page.getByText('工作空间', { exact: true }).first().click();
      if (kind === 'admin') {
        assert(process.env.E2E_WORKSPACE_OWNER_LABEL, 'Choose an existing workspace owner for admin smoke');
        await page.getByText(process.env.E2E_WORKSPACE_OWNER_LABEL, { exact: true }).first().click();
      }
      await page.getByText('新建文件夹', { exact: true }).first().waitFor({ timeout: 20000 });
      assert.equal(failures.length, 0, JSON.stringify(failures));
      console.log(JSON.stringify({ kind, login: 'passed', workspace: 'passed', serverErrors: failures }));
    } finally { await context.close(); }
  }
} finally { await browser.close(); }
