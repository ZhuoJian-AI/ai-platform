import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173';
assert.ok(process.env.E2E_USERNAME && process.env.E2E_PASSWORD, 'Missing environment credentials');
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] });
const context = await browser.newContext({ acceptDownloads: true });
const page = await context.newPage();
const errors = [];
let rejectedRun = null;
page.on('pageerror', error => errors.push(error.message));
page.on('response', async response => {
  const path = new URL(response.url()).pathname;
  if (response.request().method() === 'POST' && path.startsWith('/api/') && !path.includes('/login')) {
    console.log(JSON.stringify({ step: 'post', path, status: response.status() }));
    if (response.status() >= 400) {
      const body = await response.json().catch(() => ({}));
      console.log(JSON.stringify({ step: 'public_error', detail: body.detail }));
      if (path.endsWith('/run')) rejectedRun = response.status();
    }
  }
});
let taskId = process.env.E2E_RESUME_TASK;
const phase = process.env.E2E_MEDIA_PHASE || 'speech';
const name = `E2E-MEDIA-${phase}-${Date.now()}`;
async function api(path) {
  return page.evaluate(async path => {
    const response = await fetch(`/api/v1/terminal/${path}`, {
      headers: { Authorization: `Bearer ${sessionStorage.getItem('ai_infra_user_token')}` },
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error(`Read failed ${response.status}`);
    return response.json();
  }, path);
}
try {
  await page.goto(`${base}/alphabet/terminal/login`);
  await page.getByRole('textbox', { name: '用户名' }).fill(process.env.E2E_USERNAME);
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(process.env.E2E_PASSWORD);
  await page.getByRole('button', { name: '登 录' }).click();
  await page.waitForURL(`${base}/alphabet/terminal`, { timeout: 30000 });
  if (taskId) await page.goto(`${base}/alphabet/terminal/tasks/${taskId}`);
  const before = taskId ? await api(`tasks/${taskId}`) : { messages: [] };
  if (process.env.E2E_INSPECT_ONLY === '1') {
    await page.locator('[contenteditable=true]').first().waitFor({ timeout: 30000 });
    console.log(JSON.stringify({ taskId, status: before.run_status, messageRoles: before.messages.map(m => m.role),
      ui: (await page.locator('body').innerText()).slice(-2500) }));
    await browser.close();
    process.exit(0);
  }
  assert.ok(!['running', 'queued'].includes(before.run_status), 'Do not resubmit a running task');
  const prompts = {
    speech: `请将“今天检验一百件衣服，发现三个缺陷。”用标准音色转成可以下载的 MP3，文件名 ${name}.mp3。`,
    design: `请设计温和清晰的成年女性普通话音色，读“今天检验一百件衣服，发现三个缺陷。”，交付 ${name}.mp3。使用音色设计模式，不使用预设或克隆音色。`,
    image: `请生成一张白底蓝色短袖T恤效果图，使用生图模型，保存为 ${name}.png。`,
    vision: '请实际读取刚才生成的图片，用识图能力确认衣服的颜色、袖长与背景。只分析，不生成新文件。',
    asr: '请调用语音转写能力，转写刚才生成的音频，告诉我检验件数和缺陷数。只返回文字，不生成文件。',
    understand: '请使用原生音频理解能力听刚才生成的音频，说明讲话内容和声音特点。只返回文字，不生成文件。',
  };
  assert.ok(prompts[phase], 'Unknown test phase');
  const input = page.locator('[contenteditable=true]').first();
  await input.waitFor({ timeout: 30000 });
  await input.fill(prompts[phase]);
  await input.press('Enter');
  await page.waitForURL(url => url.pathname.includes('/tasks/') || !!url.searchParams.get('conversation'));
  const url = new URL(page.url());
  taskId = url.searchParams.get('conversation') || url.pathname.split('/').pop();
  console.log(JSON.stringify({ phase, taskId, step: 'submitted' }));
  const priorIds = new Set(before.messages.map(message => message.id));
  let task, answer;
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) {
    assert.equal(rejectedRun, null, `Run rejected with HTTP ${rejectedRun}`);
    task = await api(`tasks/${taskId}`);
    answer = task.messages.filter(message => message.role === 'assistant' && !priorIds.has(message.id)).at(-1);
    if (answer && !['queued', 'running'].includes(task.run_status)) break;
    await page.waitForTimeout(2000);
  }
  const executions = answer?.metadata?.tool_executions || [];
  const artifacts = answer?.metadata?.artifacts || [];
  console.log(JSON.stringify({ phase, taskId, status: task?.run_status, tools: executions, artifactCount: artifacts.length }));
  const tool = { speech: 'speech_synthesize', design: 'speech_synthesize', image: 'image_generation_tool',
    vision: 'image_tool', asr: 'audio_transcribe', understand: 'audio_understand' }[phase];
  assert.ok(executions.some(call => call.name === tool && call.ok), `No verified ${tool} result`);
  assert.ok(!['failed', 'error', 'cancelled', 'running', 'queued'].includes(task.run_status), 'Task did not complete');
  if (['speech', 'design', 'image'].includes(phase)) {
    assert.ok(artifacts.length, 'No committed artifact');
    const artifact = artifacts.at(-1);
    const file = await api(`files/${artifact.fileId || artifact.file_id}`);
    assert.ok(file.path.includes(name), 'Artifact points to another output');
    assert.equal(file.current_version_id, artifact.versionId || artifact.version_id);
    await page.reload();
    const buttons = page.getByRole('button', { name: '下载原文件', exact: true });
    await buttons.last().waitFor({ timeout: 60000 });
    const pendingDownload = page.waitForEvent('download', { timeout: 45000 });
    await buttons.last().click();
    const download = await pendingDownload;
    const bytes = await readFile(await download.path());
    const hash = createHash('sha256').update(bytes).digest('hex');
    assert.equal(hash, file.content_hash, 'Downloaded bytes differ from saved version');
    if (phase === 'image') assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    else assert.ok(bytes.subarray(0, 3).toString() === 'ID3' || bytes[0] === 0xff);
    console.log(JSON.stringify({ phase, fileId: file.id, versionId: file.current_version_id, bytes: bytes.length, checksum: hash }));
  } else {
    assert.equal(artifacts.length, 0, 'Analysis unexpectedly generated a new file');
    if (phase === 'asr') {
      assert.match(answer.content, /100|一百/);
      assert.match(answer.content, /3|三/);
    }
    if (phase === 'vision') assert.match(answer.content, /蓝/);
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ phase, taskId, status: 'passed', cleanup: 'retained for follow-up; E2E files only' }));
} finally {
  await browser.close();
}
