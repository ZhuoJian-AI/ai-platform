// Candidate UI against staging APIs, with a real employee login. No model invocation.
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
const base = 'https://ai-platform.staging.zhuojianai.com';
const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--no-proxy-server', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
try {
  const page = await browser.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  if (process.env.E2E_ONLINE !== '1') await page.route(`${base}/**`, async route => {
    const pathname = new URL(route.request().url()).pathname;
    const local = pathname.startsWith('/assets/') ? pathname.slice(1) : pathname.startsWith('/alphabet/terminal') ? 'index.html' : null;
    if (!local) return route.continue();
    try {
      const body = await readFile(resolve('dist', local));
      return route.fulfill({ body, contentType: local.endsWith('.js') ? 'application/javascript' : local.endsWith('.css') ? 'text/css' : local.endsWith('.html') ? 'text/html' : 'application/octet-stream' });
    } catch { return route.continue(); }
  });
  await page.addInitScript(() => {
    window.__tracks = [];
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async c => { const s = await original(c); window.__tracks.push(...s.getTracks()); return s; };
  });
  await page.goto(`${base}/alphabet/terminal/login`);
  await page.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_EMPLOYEE_USERNAME);
  await page.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_EMPLOYEE_PASSWORD);
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await page.waitForURL(u => !u.pathname.endsWith('/login'));
  await page.getByRole('button', { name: '语音模式', exact: true }).waitFor();
  const mode = page.getByRole('button', { name: '语音模式', exact: true });
  assert(await mode.isEnabled());
  const beforeUrl = page.url();
  await mode.click();
  await page.waitForFunction(() => window.__tracks.length > 0);
  await page.getByRole('button', { name: '退出语音', exact: true }).click();
  assert(await page.evaluate(() => window.__tracks.every(t => t.readyState === 'ended')));
  assert.equal(page.url(), beforeUrl, 'No task created by opening/cancelling voice');
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log('PASS: real employee login, draft voice entry, microphone start/exit, no empty task navigation, no page errors');
} finally { await browser.close(); }
