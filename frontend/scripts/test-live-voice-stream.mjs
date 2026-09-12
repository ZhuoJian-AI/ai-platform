import assert from 'node:assert/strict';
import { build } from 'esbuild';
const result = await build({
  entryPoints: ['src/pages/terminal/browserVoiceAdapter.ts'], bundle: true, write: false,
  format: 'esm', platform: 'browser', plugins: [{ name: 'fake-voice-api', setup(builder) {
    builder.onResolve({ filter: /api\/client$/ }, () => ({ path: 'voice-api', namespace: 'mock' }));
    builder.onLoad({ filter: /.*/, namespace: 'mock' }, () => ({
      contents: 'export const multimodal=globalThis.__voiceApi; export const terminal={};', loader: 'js',
    }));
  } }],
});
const tick = () => new Promise(resolve => setImmediate(resolve));
const calls = [], played = [];
globalThis.__voiceApi = {
  readRunSpeech: async (task, run, index) => { calls.push({ task, run, index }); return { job_id: `segment-${index}` }; },
  job: async id => ({ status: 'succeeded', output_url: `https://test.invalid/${id}` }),
  cancelMessageSpeech: async () => {},
};
globalThis.Audio = class {
  constructor(url) { this.url = url; }
  play() { played.push(this.url); queueMicrotask(() => this.onended?.()); return Promise.resolve(); }
  pause() {} removeAttribute() {} load() {}
};
const { browserVoiceAdapter } = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
let finishModel, submitCount = 0;
const modelPending = new Promise(resolve => { finishModel = resolve; });
const adapter = browserVoiceAdapter(async (_text, _signal, hooks) => {
  submitCount++;
  const event = { type: 'speech_segment', taskId: 'owned-task', runId: 7, segmentIndex: 0, contentVersion: 'a'.repeat(64) };
  hooks.onEvent(event);
  hooks.onEvent(event); // same Run replay must not play again
  hooks.onEvent({ type: 'speech_reset', taskId: 'owned-task', runId: 7, invalidatesBefore: 0 });
  hooks.onEvent({ type: 'speech_reset', taskId: 'other-task', runId: 8, invalidatesBefore: 1 });
  await modelPending;
  hooks.onEvent({ ...event, segmentIndex: 1, contentVersion: 'b'.repeat(64) });
  return { taskId: 'owned-task', messageId: 'final-message', needsConfirmation: false };
});
let started = 0;
const run = adapter.submit('hello', new AbortController().signal, {
  isMuted: () => false, onSpeechStart: () => { started++; },
});
await tick(); await tick();
assert.equal(played.length, 1, 'first audio plays while model submission remains pending');
finishModel();
const reply = await run;
assert.equal(reply.speechHandled, true, 'controller must not replay the full final message');
assert.deepEqual(calls.map(c => c.index), [0, 1]);
assert.equal(played.length, 2); assert.equal(started, 2); assert.equal(submitCount, 1);
console.log('PASS: live first audio before final model result, replay deduplication, ordered speech, one business submit');

// A job created after exit must be cancelled without starting audio or another run.
let releaseJob;
const lateJob = new Promise(resolve => { releaseJob = resolve; });
const cancelled = [];
globalThis.__voiceApi.readRunSpeech = async () => lateJob;
globalThis.__voiceApi.cancelMessageSpeech = async id => { cancelled.push(id); };
const abort = new AbortController();
let submissions = 0;
const lateAdapter = browserVoiceAdapter(async (_text, _signal, hooks) => {
  submissions++;
  hooks.onEvent({ type: 'speech_segment', taskId: 'owned-task', runId: 9, segmentIndex: 0, contentVersion: 'c'.repeat(64) });
  return { taskId: 'owned-task', needsConfirmation: false };
});
const lateRun = lateAdapter.submit('one request', abort.signal).catch(error => error);
await tick(); abort.abort(); releaseJob({ job_id: 'late-job' });
assert.equal((await lateRun).name, 'AbortError');
assert(cancelled.includes('late-job'));
assert.equal(played.length, 2); assert.equal(submissions, 1);
console.log('PASS: historical/foreign reset ignored; exit cancels late job, no late playback or resubmission');

globalThis.__voiceApi.readRunSpeech = async () => ({ job_id: 'withdrawn-job' });
const withdrawn = browserVoiceAdapter(async (_text, _signal, hooks) => {
  hooks.onEvent({ type: 'speech_segment', taskId: 'owned-task', runId: 10, segmentIndex: 0, contentVersion: 'd'.repeat(64) });
  hooks.onEvent({ type: 'speech_reset', taskId: 'owned-task', runId: 10, invalidatesBefore: 1 });
  return { taskId: 'owned-task', needsConfirmation: false };
});
await assert.rejects(withdrawn.submit('one request', new AbortController().signal), /回复正在纠正/);
assert.equal(played.length, 2, 'a current reset must still invalidate pending audio');
console.log('PASS: genuine current-run withdrawal still stops pending playback');
