import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173';
assert.ok(process.env.E2E_ADMIN_USERNAME && process.env.E2E_ADMIN_PASSWORD);
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${base}/login`);
  await page.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME);
  await page.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD);
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForURL(url => !url.pathname.endsWith('/login'));
  const result = await page.evaluate(async () => {
    async function read(path) {
      const r = await fetch(`/api/v1/${path}`, { credentials: 'include' });
      if (!r.ok) throw new Error(`Admin read failed: ${r.status}`);
      return r.json();
    }
    const organizations = await read('organizations');
    const items = Array.isArray(organizations) ? organizations : organizations.items;
    const results = [];
    for (const org of items) {
      const providers = await read(`organizations/${org.id}/providers`);
      for (const provider of providers) {
        const models = await read(`providers/${provider.id}/models`);
        results.push(...models.map(model => ({ model: model.model_id, capabilities: model.capabilities,
          verification: model.verification_status, enabled: model.is_active })));
      }
    }
    return results;
  });
  console.log(JSON.stringify({ adminLogin: 'passed', deployments: result }));
} finally {
  await browser.close();
}
