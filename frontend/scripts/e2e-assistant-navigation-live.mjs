import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';

const base = process.env.E2E_BASE_URL || 'https://ai-platform.staging.zhuojianai.com';
if (!process.env.E2E_USERNAME || !process.env.E2E_PASSWORD) throw new Error('Missing environment credentials');
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('framenavigated', frame => {
  if (frame === page.mainFrame()) {
    const url = new URL(frame.url());
    console.log(JSON.stringify({ phase: 'route', path: url.pathname, view: url.searchParams.get('view'), conversation: url.searchParams.get('conversation') }));
  }
});
try {
  if (process.env.E2E_CANDIDATE === '1') {
    const root = resolve('dist');
    await page.route(`${base}/**`, async route => {
      const path = new URL(route.request().url()).pathname;
      const shell = route.request().isNavigationRequest() && path.startsWith('/alphabet/terminal');
      if (!shell && !path.startsWith('/assets/')) return route.continue();
      const file = resolve(root, shell ? 'index.html' : `.${path}`);
      assert.ok(file.startsWith(root + sep));
      await route.fulfill({ body: await readFile(file), contentType: shell ? 'text/html' : file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : undefined });
    });
  }
  await page.goto(`${base}/alphabet/terminal/login`);
  await page.getByRole('textbox', { name: '用户名' }).fill(process.env.E2E_USERNAME);
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(process.env.E2E_PASSWORD);
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForURL(`${base}/alphabet/terminal`);
  const input = page.locator('[contenteditable=true]').first();
  await input.fill('带我去查看 204A231 款的资料，并查询这款有哪些图片。请继续完成查询，不要修改任何业务数据。');
  await input.press('Enter');
  await page.waitForURL(url => url.pathname.includes('/tasks/') || !!url.searchParams.get('conversation'));
  const first = new URL(page.url());
  const taskId = first.searchParams.get('conversation') || first.pathname.split('/').pop();
  console.log(JSON.stringify({ phase: 'task_started', taskId }));
  let task;
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    task = await page.evaluate(async id => {
      const r = await fetch(`/api/v1/terminal/tasks/${id}`, { headers: { Authorization: `Bearer ${sessionStorage.getItem('ai_infra_user_token')}` } });
      if (!r.ok) throw new Error(`Task read failed: ${r.status}`);
      return r.json();
    }, taskId);
    if (task.messages?.some(m => m.role === 'assistant') && !['running', 'queued'].includes(task.run_status)) break;
    await page.waitForTimeout(2000);
  }
  const answer = task.messages.filter(m => m.role === 'assistant').at(-1);
  const executions = answer?.metadata?.tool_executions || [];
  const url = new URL(page.url());
  console.log(JSON.stringify({ phase: 'result', taskId, status: task.run_status, view: url.searchParams.get('view'), conversation: url.searchParams.get('conversation'), executions, content: answer?.content }));
  assert.equal(url.searchParams.get('view'), 'application');
  assert.equal(url.searchParams.get('conversation'), taskId);
  assert.ok(executions.some(t => t.kind === 'enterprise_action' && t.ok));
  assert.match(answer.content, /204A231/);
  await page.getByRole('dialog').getByText(/204A231/).first().waitFor({ timeout: 30000 });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', taskId, checks: ['global_natural_request', 'automatic_navigation', 'same_task', 'real_action_query'] }));
} finally {
  await browser.close();
}
