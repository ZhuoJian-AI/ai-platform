import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/pages/terminal/voiceConversation.ts', import.meta.url), 'utf8');
const { VoiceConversation, SentenceEndpoint } = await import(`data:text/javascript;base64,${Buffer.from(ts.transpile(source, {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022})).toString('base64')}`);
const tick = () => new Promise(r => setImmediate(r));
const pending = () => { let resolve; const promise = new Promise(r => { resolve=r; }); return { promise, resolve }; };
function setup({ confirm=false, ttsFail=false }={}) {
  const captured=pending(), spoken=pending(), calls=[];
  let count=0;
  const c=new VoiceConversation({
    capture:async()=>{calls.push('capture'); if (++count===1) return captured.promise; return new Promise(()=>{});},
    finishCapture:()=>captured.resolve(new Blob(['voice'])),
    stopMedia:()=>calls.push('stop'),
    transcribe:async()=>{calls.push('asr');return '查询订单';},
    submit:async text=>{calls.push(text);return {taskId:'same-task',messageId:'new-message',needsConfirmation:confirm};},
    speak:async()=>{calls.push('tts');if(ttsFail)throw Error('播放被拒绝');return spoken.promise;},
  });
  return {c,calls,captured,spoken};
}
{
 const {c,calls,spoken}=setup();c.start();c.start();c.finishSentence();await tick();
 assert.equal(c.getSnapshot().phase,'speaking');assert.equal(calls.filter(x=>x==='capture').length,1);
 assert(calls.indexOf('asr')>calls.lastIndexOf('stop'));
 spoken.resolve();await tick();assert.equal(c.getSnapshot().phase,'listening');c.exit();
}
{
 const {c,calls,captured}=setup();c.start();c.exit();captured.resolve(new Blob());await tick();
 assert.equal(c.getSnapshot().phase,'off');assert(!calls.includes('asr'));
}
{
 const {c,calls}=setup({confirm:true});c.start();c.finishSentence();await tick();
 assert.equal(c.getSnapshot().phase,'confirmation');c.start();assert(!calls.includes('tts'));
 assert.equal(calls.filter(x=>x==='capture').length,1);c.confirmationResolved();assert.equal(c.getSnapshot().phase,'paused');c.exit();
}
{
 const {c,calls}=setup({ttsFail:true});c.start();c.finishSentence();await tick();
 assert.equal(c.getSnapshot().phase,'error');assert.equal(calls.filter(x=>x==='查询订单').length,1);c.exit();
}
const endpoint=new SentenceEndpoint();assert.equal(endpoint.sample(0,0),'continue');assert.equal(endpoint.sample(0,15000),'silence');
const speech=new SentenceEndpoint();speech.sample(0.1,0);assert.equal(speech.sample(0,1200),'finish');
console.log('PASS: half-duplex, duplicate start, late capture, confirmation, TTS failure and silence endpoints');
