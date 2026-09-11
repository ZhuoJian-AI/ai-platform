import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
const { chromium } = createRequire(import.meta.url)('playwright');
const base = 'http://127.0.0.1:4173';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  const page = await browser.newPage();
  await page.goto(base + '/login');
  // Candidate-only component checks. No business Action or real deletion.
  await page.evaluate(async () => {
    const adapter = await (await fetch('/src/antdReact19.ts')).text();
    const moduleUrl = adapter.match(/from\s+["']([^"']*\/antd\.js[^"']*)["']/)?.[1];
    if (!moduleUrl) throw new Error('Cannot resolve candidate Ant Design module');
    const { message, Modal, notification } = await import(moduleUrl);
    window.__feedbackTest = { message, Modal, notification };
    message.warning('E2E-语音权限提示', 0);
  });
  await page.getByText('E2E-语音权限提示', { exact: true }).waitFor();
  await page.evaluate(() => window.__feedbackTest.message.destroy());
  await page.getByText('E2E-语音权限提示', { exact: true }).waitFor({ state: 'hidden' });
  await page.evaluate(() => window.__feedbackTest.notification.info({ message: 'E2E-通知', duration: 0 }));
  await page.getByText('E2E-通知', { exact: true }).waitFor();
  await page.evaluate(() => {
    window.__feedbackTest.notification.destroy();
    window.__feedbackTest.Modal.confirm({ title: 'E2E-确认展示', okText: '确认', cancelText: '取消', onOk: () => { window.__confirmed = true; } });
  });
  await page.locator('.ant-modal-confirm-title').filter({ hasText: 'E2E-确认展示' }).waitFor();
  await page.getByRole('button', { name: /取\s*消/ }).click();
  await page.locator('.ant-modal-confirm-title').filter({ hasText: 'E2E-确认展示' }).waitFor({ state: 'hidden' });
  assert.equal(await page.evaluate(() => !!window.__confirmed), false);
  await page.evaluate(() => window.__feedbackTest.message.success('E2E-再次显示', 0));
  await page.getByText('E2E-再次显示', { exact: true }).waitFor();
  console.log(JSON.stringify({ message: 'passed', notification: 'passed', confirmCancel: 'passed', remount: 'passed', businessWrites: 0 }));
} finally { await browser.close(); }
