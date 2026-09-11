import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.E2E_BASE_URL || 'https://ai-platform.staging.zhuojianai.com';
const app = '9689828b-9d07-4a93-8b52-0eefad8be885';
const name = `E2E-SPECIALIST-${Date.now()}.png`;
if (!process.env.E2E_USERNAME || !process.env.E2E_PASSWORD) throw new Error('Missing environment credentials');
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
try {
  const fixture = await context.newPage();
  await fixture.setContent('<main style="font:32px Arial;padding:40px;background:white;color:black"><h1>Inspection Report</h1><p>Style: 204A231</p><p>Inspected: 100</p><p>Defects: 3</p><p>Result: PASS</p></main>');
  const buffer = await fixture.screenshot();
  await fixture.close();
  await page.goto(`${base}/alphabet/terminal/login`);
  await page.getByRole('textbox', { name: '用户名' }).fill(process.env.E2E_USERNAME);
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(process.env.E2E_PASSWORD);
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForURL(`${base}/alphabet/terminal`);
  await page.goto(`${base}/alphabet/terminal?view=application&app=${app}&module=style_hub&page=style_hub.main`);
  await page.getByRole('button', { name: /灼见助手$/ }).click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('input[type=file]').setInputFiles({ name, mimeType: 'image/png', buffer });
  await dialog.getByText(name, { exact: false }).first().waitFor({ timeout: 60000 });
  await dialog.getByPlaceholder('描述你要查询或执行的业务任务…').fill('请使用当前页面登记的质检报告专业 AI 识别能力，识别我刚上传的报告，告诉我款号、检验数量和缺陷数量。只要分析草稿，不要创建或修改业务记录。');
  await dialog.getByRole('button', { name: /在当前页面执行$/ }).click();
  await page.waitForURL(url => !!url.searchParams.get('conversation'));
  const taskId = new URL(page.url()).searchParams.get('conversation');
  let task;
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) {
    task = await page.evaluate(async id => {
      const r = await fetch(`/api/v1/terminal/tasks/${id}`, { headers: { Authorization: `Bearer ${sessionStorage.getItem('ai_infra_user_token')}` } });
      if (!r.ok) throw new Error(`Task read failed: ${r.status}`);
      return r.json();
    }, taskId);
    if (task.messages.some(m => m.role === 'assistant') && !['queued', 'running'].includes(task.run_status)) break;
    await page.waitForTimeout(2000);
  }
  const answer = task.messages.filter(m => m.role === 'assistant').at(-1);
  const executions = answer?.metadata?.tool_executions || [];
  assert.ok(executions.some(t => t.kind === 'subsystem_specialist' && t.ok), JSON.stringify({ status: task.run_status, executions }));
  assert.match(answer.content, /204A231/);
  assert.match(answer.content, /100/);
  assert.match(answer.content, /3/);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', taskId, fixture: name, checks: ['real_upload', 'specialist_tool_completed', 'same_task_answer_contains_facts'] }));
} finally {
  try {
    const cleanup = await page.evaluate(async expectedName => {
      const headers = { Authorization: `Bearer ${sessionStorage.getItem('ai_infra_user_token')}`, 'Content-Type': 'application/json' };
      const list = await fetch('/api/v1/terminal/workspace-files', { headers });
      if (!list.ok) throw new Error(`Cleanup list failed: ${list.status}`);
      const files = await list.json();
      const matches = files.filter(f => (f.path || '').endsWith(expectedName));
      for (const file of matches) {
        const detail = await fetch(`/api/v1/terminal/files/${file.id}`, { headers });
        if (!detail.ok) throw new Error('Cleanup detail failed');
        const current = await detail.json();
        if (!(current.path || '').endsWith(expectedName) || !current.current_version_id) throw new Error('Unsafe cleanup target');
        const removed = await fetch(`/api/v1/terminal/files/${file.id}`, { method: 'DELETE', headers, body: JSON.stringify({ base_version_id: current.current_version_id, idempotency_key: crypto.randomUUID() }) });
        if (!removed.ok) throw new Error(`Cleanup delete failed: ${removed.status}`);
      }
      return { cleanup: 'moved_test_file_to_recycle_bin', count: matches.length };
    }, name);
    console.log(JSON.stringify(cleanup));
  } finally {
    await context.close();
    await browser.close();
  }
}
