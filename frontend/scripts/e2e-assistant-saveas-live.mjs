import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
const base = 'https://ai-platform.staging.zhuojianai.com';
for (const key of ['E2E_USERNAME', 'E2E_PASSWORD', 'E2E_ADMIN_USERNAME', 'E2E_ADMIN_PASSWORD']) {
  assert.ok(process.env[key], `Missing ${key}`);
}
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const context = await browser.newContext({ acceptDownloads: true });
const page = await context.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('response', r => { if (r.url().includes('/uploads/') || r.url().includes('/files/upload')) console.log(JSON.stringify({ phase: 'upload_http', status: r.status(), path: new URL(r.url()).pathname })); });
page.on('response', r => { if (r.status() === 401) console.log(JSON.stringify({ phase: 'unauthorized', path: new URL(r.url()).pathname })); });
const name = `E2E-SAVEAS-${Date.now()}.md`;
const sourceText = '# 保存策略验收\n\n原始数量：100\n';
let source, output, taskId;
async function api(path, method = 'GET', body) {
  return page.evaluate(async ({ path, method, body }) => {
    const r = await fetch(`/api/v1/terminal/${path}`, { method,
      headers: { Authorization: `Bearer ${sessionStorage.getItem('ai_infra_user_token')}`, 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!r.ok) throw new Error(`API ${method} ${path.split('?')[0]}: ${r.status}`);
    return r.status === 204 ? null : r.json();
  }, { path, method, body });
}
async function preview(p, prefix, file) {
  await p.goto(`${base}${prefix}?view=workspace&workspace=${file.workspace_id}&file=${file.id}`);
  const drawer = p.getByRole('dialog').last();
  await drawer.getByRole('button', { name: '下载', exact: true }).waitFor({ timeout: 60000 });
  await drawer.getByText(/原始数量/).first().waitFor({ timeout: 60000 });
  assert.equal(await drawer.getByRole('button', { name: /^(编辑|保存修改|保存)$/ }).count(), 0);
  assert.equal(await drawer.locator('textarea,[contenteditable=true]').count(), 0);
  const downloadPromise = p.waitForEvent('download');
  await drawer.getByRole('button', { name: '下载', exact: true }).click();
  const download = await downloadPromise;
  const bytes = await readFile(await download.path());
  assert.ok(bytes.length > 0);
  console.log(JSON.stringify({ phase: 'preview_download', view: prefix, fileId: file.id, bytes: bytes.length, editor: false }));
  return bytes.toString('utf8');
}
try {
  await page.goto(`${base}/alphabet/terminal/login`);
  await page.getByRole('textbox', { name: '用户名' }).fill(process.env.E2E_USERNAME);
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(process.env.E2E_PASSWORD);
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForURL(`${base}/alphabet/terminal`);
  console.log(JSON.stringify({ phase: 'logged_in', name }));
  if (process.env.E2E_RESUME_TASK) {
    taskId = process.env.E2E_RESUME_TASK;
    if (process.env.E2E_RESTORE_TESTS === '1') {
      const ws = '0e9c1811-ab44-4101-a2c7-cbc9c455823b';
      const prior = await api(`tasks/${taskId}`);
      const artifacts = prior.messages.filter(m => m.role === 'assistant').at(-1)?.metadata?.artifacts || [];
      for (const fileId of [process.env.E2E_RESUME_SOURCE, ...artifacts.map(a => a.fileId || a.file_id)]) {
        const trash = await api(`workspaces/${ws}/trash`);
        const item = (Array.isArray(trash) ? trash : trash.items || []).find(f => f.id === fileId);
        if (item) {
          assert.ok(item.path.includes('E2E-SAVEAS-'));
          await api(`workspaces/${ws}/trash/${fileId}/restore`, 'POST', { base_version_id: item.current_version_id, idempotency_key: crypto.randomUUID() });
        }
      }
    }
    source = await api(`files/${process.env.E2E_RESUME_SOURCE}`);
    assert.equal(source.current_version_id, process.env.E2E_SOURCE_VERSION);
    console.log(JSON.stringify({ phase: 'resumed', taskId, sourceId: source.id }));
  } else {
  await page.getByText(/工作空间 zhangsan/).first().waitFor({ timeout: 30000 });
  await page.getByLabel('选择上传附件').setInputFiles({ name, mimeType: 'text/markdown', buffer: Buffer.from(sourceText) });
  const uploadDeadline = Date.now() + 60000;
  while (Date.now() < uploadDeadline) {
    source = (await api('workspace-files')).find(f => f.path?.endsWith(name));
    if (source) break;
    await page.waitForTimeout(1500);
  }
  if (!source) console.log(JSON.stringify({ phase: 'upload_ui', text: (await page.locator('body').innerText()).slice(-1800) }));
  assert.ok(source, 'Upload did not produce workspace file');
  source = await api(`files/${source.id}`);
  console.log(JSON.stringify({ phase: 'source_uploaded', fileId: source.id, versionId: source.current_version_id }));
  await page.getByText('可以发送', { exact: true }).first().waitFor({ timeout: 90000 });
  const input = page.locator('[contenteditable=true]').first();
  await input.fill(`请修改刚上传的 ${name}：把原始数量 100 改成 120，其他内容保留。交付修改后的 Markdown 文件，保留原件。`);
  await input.press('Enter');
  await page.waitForURL(u => u.pathname.includes('/tasks/') || !!u.searchParams.get('conversation'));
  const url = new URL(page.url());
  taskId = url.searchParams.get('conversation') || url.pathname.split('/').pop();
  console.log(JSON.stringify({ phase: 'task_started', taskId }));
  }
  let task;
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) {
    task = await api(`tasks/${taskId}`);
    if (task.messages?.some(m => m.role === 'assistant') && !['queued', 'running'].includes(task.run_status)) break;
    await page.waitForTimeout(2000);
  }
  const answer = task.messages.filter(m => m.role === 'assistant').at(-1);
  const artifacts = answer?.metadata?.artifacts || [];
  console.log(JSON.stringify({ phase: 'task_result', taskId, status: task.run_status, artifactCount: artifacts.length, tools: answer?.metadata?.tool_executions }));
  assert.ok(artifacts.length, 'No artifact delivered');
  const artifact = artifacts.at(-1);
  output = await api(`files/${artifact.fileId || artifact.file_id}`);
  assert.notEqual(output.id, source.id);
  const current = await api(`files/${source.id}`);
  assert.equal(current.current_version_id, source.current_version_id);
  assert.equal(current.content_hash, source.content_hash);
  assert.equal(await preview(page, '/alphabet/terminal', source), sourceText);
  assert.match(await preview(page, '/alphabet/terminal', output), /120/);
  const adminContext = await browser.newContext({ acceptDownloads: true });
  const admin = await adminContext.newPage();
  if (process.env.E2E_CANDIDATE === '1') {
    const root = resolve('dist');
    await admin.route(`${base}/**`, async route => {
      const path = new URL(route.request().url()).pathname;
      const shell = route.request().isNavigationRequest() && !path.startsWith('/api/');
      if (!shell && !path.startsWith('/assets/')) return route.continue();
      const file = resolve(root, shell ? 'index.html' : `.${path}`);
      assert.ok(file.startsWith(root + sep));
      await route.fulfill({ body: await readFile(file), contentType: shell ? 'text/html' : file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : undefined });
    });
  }
  admin.on('response', r => { if (r.status() >= 400 && new URL(r.url()).pathname.startsWith('/api/')) console.log(JSON.stringify({ phase: 'admin_api_error', status: r.status(), path: new URL(r.url()).pathname })); });
  admin.on('pageerror', e => errors.push(e.message));
  await admin.goto(`${base}/login`);
  await admin.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME);
  await admin.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD);
  await admin.getByRole('button', { name: '登 录' }).click();
  await admin.waitForURL(u => !u.pathname.endsWith('/login'));
  try { assert.match(await preview(admin, '/agent/workspaces', output), /120/); }
  catch (e) { console.log(JSON.stringify({ phase: 'admin_ui_failed', path: new URL(admin.url()).pathname, hasFileLink: new URL(admin.url()).searchParams.has('file') })); throw e; }
  await adminContext.close();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', adminFrontend: process.env.E2E_CANDIDATE === '1' ? 'local_candidate' : 'deployed', reusedTask: !!process.env.E2E_RESUME_TASK, taskId, sourceId: source.id, outputId: output.id, checks: ['real_upload', 'llm_edit', 'new_artifact', 'original_unchanged', 'employee_admin_readonly_download'] }));
} finally {
  for (const f of [output, source].filter(Boolean)) {
    try {
      const current = await api(`files/${f.id}`);
      assert.ok(current.path.includes('E2E-SAVEAS-'), 'Unsafe cleanup');
      await api(`files/${f.id}`, 'DELETE', { base_version_id: current.current_version_id, idempotency_key: crypto.randomUUID() });
      console.log(JSON.stringify({ cleanup: 'recycle_bin', fileId: f.id }));
    } catch (e) { console.log(JSON.stringify({ cleanup: 'pending', fileId: f.id, error: e.message })); }
  }
  await browser.close();
}
