// Candidate-only real login + one TTS synthesis; second click must reuse the job.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
const base = 'http://127.0.0.1:4173';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const report = {};
let adminPage, temporaryVoice;
try {
  const page = await browser.newPage();
  await page.goto(base + '/alphabet/terminal/login');
  await page.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_EMPLOYEE_USERNAME);
  await page.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_EMPLOYEE_PASSWORD);
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await page.waitForURL(url => !url.pathname.endsWith('/login'));
  const token = await page.evaluate(() => sessionStorage.getItem('ai_infra_user_token'));
  assert(token, 'Missing real-login session');
  const headers = { Authorization: `Bearer ${token}` };
  const get = async path => {
    const response = await page.request.get(base + path, { headers });
    assert.equal(response.status(), 200, path);
    return response.json();
  };
  let capabilities = await get('/api/v1/terminal/resources');
  if (capabilities.audio_capabilities.text_to_speech.code === 'no_available_voice') {
    const { user: me } = await get('/api/v1/terminal/me');
    assert(me.role_ids?.length && me.organization_id, 'Missing explicit role scope');
    adminPage = await (await browser.newContext()).newPage();
    await adminPage.goto(base + '/login');
    await adminPage.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME);
    await adminPage.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD);
    await adminPage.getByRole('button', { name: /登\s*录/ }).click();
    await adminPage.waitForURL(url => !url.pathname.endsWith('/login'));
    temporaryVoice = await adminPage.evaluate(async ({ org, role }) => {
      const { voiceAdmin } = await import('/src/api/client.ts');
      return voiceAdmin.createBuiltin(org, { name: `E2E-read-aloud-${Date.now()}`,
        provider_voice_id: 'mimo_default', grants: [{ scope_type: 'role', scope_id: role }] });
    }, { org: me.organization_id, role: me.role_ids[0] });
    capabilities = await get('/api/v1/terminal/resources');
  }
  const capability = capabilities.audio_capabilities.text_to_speech;
  if (!capability.available) throw new Error(`TTS unavailable: ${capability.code}`);
  const before = (await get('/api/v1/terminal/workspace-files')).map(f => f.id).sort();
  const tasks = await get('/api/v1/terminal/tasks?limit=30');
  let target;
  for (const task of tasks) {
    const full = await get(`/api/v1/terminal/tasks/${task.id}`);
    const assistant = full.messages.find(m => m.role === 'assistant' && m.content?.trim()
      && m.content.length < 400 && !m.content.includes('```'));
    if (assistant && !['queued', 'running'].includes(full.run_status)) {
      target = { taskId: task.id, messageId: assistant.id };
      break;
    }
  }
  assert(target, 'No completed short assistant message in candidate');
  await page.goto(`${base}/alphabet/terminal/tasks/${target.taskId}`);
  const button = page.locator('button').filter({ hasText: /^\s*朗\s*读\s*$/ }).first();
  try { await button.waitFor({ timeout: 10000 }); }
  catch (error) {
    console.log(JSON.stringify({ path: new URL(page.url()).pathname,
      buttons: await page.locator('button').allTextContents() }));
    throw error;
  }
  const clicked = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/message-speech'));
  await button.click();
  const creation = await clicked;
  assert.equal(creation.status(), 202);
  const jobId = (await creation.json()).job_id;
  report.jobId = jobId;
  for (let attempt = 0; attempt < 90; attempt++) {
    const job = await get(`/api/v1/multimodal/jobs/${jobId}`);
    if (job.status === 'succeeded') {
      assert(job.output_url);
      const media = await page.request.get(job.output_url);
      assert.equal(media.status(), 200);
      assert((await media.body()).length > 100);
      report.mediaBytes = (await media.body()).length;
      break;
    }
    assert(!['failed', 'cancelled'].includes(job.status), job.error_detail || job.status);
    await page.waitForTimeout(2000);
  }
  assert(report.mediaBytes, 'Synthesis timed out');
  const manual = page.getByRole('button', { name: /播放朗读/ });
  if (await manual.isVisible()) { await manual.click(); report.manualPlayback = true; }
  await page.getByRole('button', { name: /停止朗读/ }).waitFor({ timeout: 10000 });
  await page.getByRole('button', { name: /停止朗读/ }).click();
  const repeat = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/message-speech'));
  await button.click();
  assert.equal((await (await repeat).json()).job_id, jobId);
  await page.goto(base + '/alphabet/terminal'); // unmount stops playback and pending polls
  assert.deepEqual((await get('/api/v1/terminal/workspace-files')).map(f => f.id).sort(), before);
  console.log(JSON.stringify({ ...report, realLogin: true, playback: 'passed', cacheReuse: 'passed',
    workspaceFilesUnchanged: true, rolesChanged: false, environment: 'candidate' }));
} finally {
  if (temporaryVoice) {
    await adminPage.evaluate(async id => {
      const { voiceAdmin } = await import('/src/api/client.ts');
      await voiceAdmin.delete(id);
    }, temporaryVoice.id);
    console.log(JSON.stringify({ temporaryVoiceRemoved: true }));
  }
  await browser.close();
}
