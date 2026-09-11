import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173';
assert(new URL(base).hostname === '127.0.0.1', 'Candidate-only test');
const browser = await chromium.launch({ headless: true, channel: 'chrome', args: [
  '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
  `--use-file-for-fake-audio-capture=${process.env.E2E_AUDIO_FILE}`,
] });
let admin, employee, user, adminHeaders = {}, employeeHeaders = {};
const report = {};
async function login(kind) {
  const ctx = await browser.newContext({ permissions: ['microphone'] });
  const page = await ctx.newPage();
  page.on('console', entry => {
    if (/CORS policy/i.test(entry.text())) {
      report.corsBlocked = true;
      report.corsReason = entry.text().replace(/https?:\/\/[^\s'"]+/g, '[URL]').slice(0, 600);
    }
  });
  page.on('request', request => {
    const auth = request.headers().authorization;
    if (auth && new URL(request.url()).origin === base) {
      if (kind === 'ADMIN') adminHeaders = { Authorization: auth };
      else employeeHeaders = { Authorization: auth };
    }
  });
  await page.goto(base + (kind === 'ADMIN' ? '/login' : '/alphabet/terminal/login'));
  await page.getByPlaceholder('用户名', { exact: true }).fill(process.env[`E2E_${kind}_USERNAME`]);
  await page.getByPlaceholder('密码', { exact: true }).fill(process.env[`E2E_${kind}_PASSWORD`]);
  const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().includes('/login'));
  await page.getByRole('button', { name: /登\s*录/ }).click();
  assert.equal((await response).status(), 200);
  await page.waitForURL(url => !url.pathname.endsWith('/login'));
  if (kind === 'EMPLOYEE') {
    const token = await page.evaluate(() => sessionStorage.getItem('ai_infra_user_token'));
    assert(token, 'Missing token from real login');
    employeeHeaders = { Authorization: `Bearer ${token}` };
  }
  return { ctx, page };
}
async function call(session, path, method = 'GET', data) {
  const headers = session === admin ? adminHeaders : employeeHeaders;
  const response = await session.ctx.request.fetch(base + path, { method, headers, data });
  assert(response.ok(), `${method} ${path}: ${response.status()}`);
  return response.status() === 204 ? null : response.json();
}
try {
  admin = await login('ADMIN'); employee = await login('EMPLOYEE');
  const me = await call(employee, '/api/v1/terminal/me'); user = me.user;
  assert(user?.id && user.organization_id, 'Missing employee identity');
  const record = await call(admin, `/api/v1/users/${user.id}`);
  assert(Array.isArray(record.role_ids));
  const before = await call(employee, '/api/v1/terminal/resources');
  report.initialAsr = before.audio_capabilities.speech_to_text.code;
  assert(before.audio_capabilities.speech_to_text.available, 'Candidate employee requires existing ASR test role');
  const capabilities = await call(employee, '/api/v1/terminal/resources');
  assert(capabilities.audio_capabilities.speech_to_text.available,
    capabilities.audio_capabilities.speech_to_text.messageZh);
  const page = employee.page;
  await page.getByRole('button', { name: /新建任务/ }).first().click();
  const beforeFiles = await call(employee, '/api/v1/terminal/workspace-files');
  let workspaceWrites = 0;
  page.on('request', r => { if (r.method() === 'POST' && /workspaces.*upload/.test(r.url())) workspaceWrites++; });
  await page.locator('button').filter({ hasText: /^\s*录音\s*$/ }).first().click();
  await page.locator('button').filter({ hasText: '完成转写' }).waitFor();
  await page.waitForTimeout(7000);
  const created = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname.endsWith('/multimodal/recordings'));
  await page.locator('button').filter({ hasText: '完成转写' }).click();
  const createResponse = await created;
  assert.equal(createResponse.status(), 201);
  const jobId = (await createResponse.json()).job_id;
  const upload = await createResponse.json();
  report.uploadHeaders = Object.keys(upload.headers || {});
  report.uploadHosts = [upload.url, upload.fallback_url].filter(Boolean).map(url => new URL(url).hostname);
  report.jobId = jobId;
  await page.locator('[contenteditable="true"]').first().fill('等待期间新输入的文字');
  for (let attempt = 0; attempt < 60; attempt++) {
    const status = await call(employee, `/api/v1/multimodal/jobs/${jobId}`);
    if (status.status === 'succeeded') break;
    if (['failed', 'cancelled'].includes(status.status)) {
      report.failureCategory = status.error_category;
      report.feedback = await page.locator('.ant-message').allTextContents();
      throw new Error(`Recording ended as ${status.status}`);
    }
    await page.waitForTimeout(2000);
  }
  await page.waitForFunction(() => {
    const value = document.querySelector('[contenteditable="true"]')?.textContent || '';
    return value.startsWith('等待期间新输入的文字') && value.length > 20;
  }, null, { timeout: 10000 });
  const job = await call(employee, `/api/v1/multimodal/jobs/${jobId}`);
  assert.equal(job.status, 'succeeded'); assert(job.result.text.trim()); assert.equal(job.input_file_id, null);
  assert.equal(workspaceWrites, 0);
  assert.deepEqual((await call(employee, '/api/v1/terminal/workspace-files')).map(x => x.id).sort(), beforeFiles.map(x => x.id).sort());
  report.recording = 'passed'; report.preserveTyping = 'passed'; report.noWorkspaceFile = 'passed';
} catch (error) {
  if (employee) console.log(JSON.stringify({ path: new URL(employee.page.url()).pathname,
    buttons: await employee.page.locator('button').allTextContents() }));
  throw error;
} finally {
  report.rolesChanged = false;
  await browser.close();
  console.log(JSON.stringify(report));
}
