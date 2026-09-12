import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/pages/terminal/speechPlaybackQueue.ts', import.meta.url), 'utf8');
const { playSpeechQueue } = await import(`data:text/javascript;base64,${Buffer.from(ts.transpile(source, {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
})).toString('base64')}`);
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
{
  const first = deferred(), playback = deferred(), prepared = [], played = [];
  const task = playSpeechQueue({ count: 3, signal: new AbortController().signal,
    prepare: async index => { prepared.push(index); if (index === 0) await first.promise; return index; },
    play: async index => { played.push(index); if (index === 0) await playback.promise; },
  });
  await tick(); assert.deepEqual(prepared, [0, 1]); assert.deepEqual(played, []);
  first.resolve(); await tick(); assert.deepEqual(played, [0]); assert.deepEqual(prepared, [0, 1]);
  playback.resolve(); await task; assert.deepEqual(played, [0, 1, 2]);
}
{
  const late = deferred(), controller = new AbortController(), played = [];
  const task = playSpeechQueue({ count: 2, signal: controller.signal,
    prepare: async () => late.promise, play: async value => { played.push(value); },
  });
  const rejected = assert.rejects(task, { name: 'AbortError' });
  controller.abort(); late.resolve('late audio'); await rejected; assert.deepEqual(played, []);
}
{
  let calls = 0;
  await assert.rejects(playSpeechQueue({ count: 4, signal: new AbortController().signal,
    prepare: async index => { calls++; if (index === 1) throw Error('prefetch failure'); return index; },
    play: async () => {},
  }), /prefetch failure/);
  assert(calls <= 3, 'bounded preparation; no unbounded retry');
}
console.log('PASS: ordered prefetch, bounded preparation, cancellation and failed prefetch');
