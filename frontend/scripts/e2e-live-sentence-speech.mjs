// Real candidate backend/worker/TTS with real browser audio; no microphone assertion.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const base = process.env.E2E_BASE || 'http://127.0.0.1:4183';
assert.equal(new URL(base).hostname, '127.0.0.1', 'Candidate-only harness');
const browser = await chromium.launch({ headless: true, channel: 'chrome',
  args: ['--no-proxy-server', '--autoplay-policy=no-user-gesture-required'] });
let adminPage, temporaryVoice;
try {
  const page = await browser.newPage();
  await page.goto(base + '/alphabet/terminal/login');
  await page.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_EMPLOYEE_USERNAME);
  await page.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_EMPLOYEE_PASSWORD);
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await page.waitForURL(u => !u.pathname.endsWith('/login'));
  const scope = await page.evaluate(async () => {
    const { terminal } = await import('/src/api/client.ts');
    const resources = await terminal.resources();
    const me = await terminal.me();
    return { needsVoice: resources.audio_capabilities.text_to_speech.code === 'no_available_voice',
      org: me.user.organization_id, role: me.user.role_ids[0] };
  });
  if (scope.needsVoice) {
    assert(scope.org && scope.role);
    adminPage = await (await browser.newContext()).newPage();
    await adminPage.goto(base + '/login');
    await adminPage.getByPlaceholder('用户名', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME);
    await adminPage.getByPlaceholder('密码', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD);
    await adminPage.getByRole('button', { name: /登\s*录/ }).click();
    await adminPage.waitForURL(u => !u.pathname.endsWith('/login'));
    temporaryVoice = await adminPage.evaluate(async ({ org, role }) => {
      const { voiceAdmin } = await import('/src/api/client.ts');
      return voiceAdmin.createBuiltin(org, { name: `E2E-stream-${Date.now()}`,
        provider_voice_id: 'mimo_default', grants: [{ scope_type: 'role', scope_id: role }] });
    }, scope);
  }
  const report = await page.evaluate(async () => {
    const { terminal } = await import('/src/api/client.ts');
    const { browserVoiceAdapter } = await import('/src/pages/terminal/browserVoiceAdapter.ts');
    const capabilities = (await terminal.resources()).audio_capabilities;
    if (!capabilities.text_to_speech.available) return { unavailable: capabilities.text_to_speech };
    const result = { segments: 0, played: 0, firstTextMs: null, firstSoundMs: null, finalMs: null };
    const start = performance.now();
    const originalPlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      this.addEventListener('playing', () => {
        result.firstSoundMs ??= Math.round(performance.now() - start); result.played++;
      }, { once: true });
      return originalPlay.call(this);
    };
    const task = await terminal.createTask({ title: `E2E-stream-voice-${Date.now()}`, message: '', config: {} });
    result.taskId = task.id;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 180000);
    const adapter = browserVoiceAdapter(async (prompt, signal, hooks) => {
      const response = await terminal.runTaskStream(task.id, prompt, signal);
      if (!response.ok) throw Error(`Run HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let end;
        while ((end = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
          const data = frame.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()).join('\n');
          if (!data || data === '[DONE]') continue;
          const event = JSON.parse(data);
          if (event.type === 'text') result.firstTextMs ??= Math.round(performance.now() - start);
          if (event.type === 'speech_segment') result.segments++;
          if (event.type === 'final') result.finalMs = Math.round(performance.now() - start);
          hooks.onEvent(event);
        }
        if (done) break;
      }
      const latest = await terminal.getTask(task.id);
      result.runStatus = latest.run_status;
      return { taskId: task.id, messageId: latest.messages.filter(m => m.role === 'assistant').at(-1)?.id,
        needsConfirmation: false };
    });
    try {
      const reply = await adapter.submit('请用约四百字的自然中文解释为什么睡眠有助于学习。分成连续短句，不用标题、表格或列表，不查询业务系统，不生成文件。',
        controller.signal, { isMuted: () => false });
      result.speechHandled = reply.speechHandled;
    } catch (error) { result.error = String(error.message || error); }
    finally {
      clearTimeout(timeout); controller.abort(); adapter.stopMedia();
      await terminal.cancelTask(task.id).catch(() => {});
      await terminal.deleteTask(task.id);
      HTMLMediaElement.prototype.play = originalPlay;
      result.testTaskDeleted = true;
    }
    return result;
  });
  console.log(JSON.stringify(report));
  assert(!report.unavailable, 'Candidate TTS unavailable');
  assert(!report.error, report.error);
  assert(report.played > 0 && report.speechHandled, 'No actual audio playback');
  assert(report.firstSoundMs < report.finalMs, 'First sound was not earlier than final answer');
} finally {
  if (temporaryVoice) await adminPage.evaluate(async id => {
    const { voiceAdmin } = await import('/src/api/client.ts'); await voiceAdmin.delete(id);
  }, temporaryVoice.id);
  await browser.close();
}
