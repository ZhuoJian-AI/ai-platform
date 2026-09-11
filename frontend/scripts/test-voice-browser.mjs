// Browser lifecycle test with synthetic microphone and stubbed ASR/TTS; no provider calls.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  const page = await browser.newPage();
  await page.route('**/voice-test', route => route.fulfill({ contentType: 'text/html', body: '<html><body>Voice lifecycle test</body></html>' }));
  await page.goto('http://127.0.0.1:4173/voice-test');
  const result = await page.evaluate(async () => {
    const { browserVoiceAdapter } = await import('/src/pages/terminal/browserVoiceAdapter.ts');
    const { VoiceConversation } = await import('/src/pages/terminal/voiceConversation.ts');
    const compiled = await (await fetch('/src/pages/terminal/browserVoiceAdapter.ts')).text();
    const clientPath = compiled.match(/from "([^\"]*\/api\/client.ts[^\"]*)"/)[1];
    const { terminal, multimodal } = await import(clientPath);
    const originalFetch = window.fetch;
    const tracks = [];
    const contexts = [];
    let submissions = 0, tts = 0;
    terminal.resources = async () => ({ audio_capabilities: { speech_to_text: { available: true }, text_to_speech: { available: true } } });
    navigator.mediaDevices.getUserMedia = async () => {
      const context = new AudioContext(); contexts.push(context);
      const dest = context.createMediaStreamDestination();
      const oscillator = context.createOscillator(); oscillator.connect(dest); oscillator.start();
      tracks.push(...dest.stream.getTracks()); return dest.stream;
    };
    multimodal.createRecording = async () => ({job_id:'record',url:'/synthetic-upload',headers:{}});
    window.fetch = async (url, init) => url === '/synthetic-upload' ? new Response('', {status:200}) : originalFetch(url,init);
    multimodal.completeRecording = async () => ({job_id:'record'});
    multimodal.cancelRecording = async () => {};
    multimodal.readMessage = async () => { tts++;return {job_id:'speech'}; };
    multimodal.cancelMessageSpeech = async () => {};
    const bytes = new Uint8Array(44+16000);const dv=new DataView(bytes.buffer);
    const str=(at,s)=>[...s].forEach((c,i)=>bytes[at+i]=c.charCodeAt(0));
    str(0,'RIFF');dv.setUint32(4,bytes.length-8,true);str(8,'WAVEfmt ');dv.setUint32(16,16,true);dv.setUint16(20,1,true);dv.setUint16(22,1,true);dv.setUint32(24,8000,true);dv.setUint32(28,16000,true);dv.setUint16(32,2,true);dv.setUint16(34,16,true);str(36,'data');dv.setUint32(40,16000,true);
    const url=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
    multimodal.job = async id => ({status:'succeeded',result:{text:'你好'},output_url:id==='speech'?url:null});
    const c=new VoiceConversation(browserVoiceAdapter(async()=>{submissions++;return {taskId:'existing',messageId:'reply',needsConfirmation:false};}));
    const sleep=ms=>new Promise(r=>setTimeout(r,ms));
    try {
      c.start();await sleep(500);c.finishSentence();
      for(let i=0;i<100 && tracks.length<2 && c.getSnapshot().phase!=='error';i++) await sleep(100);
      const phase=c.getSnapshot().phase;
      const oldReleased=tracks[0]?.readyState==='ended';
      c.exit();await sleep(100);
      return {submissions,tts,phase,oldReleased,allReleased:tracks.every(t=>t.readyState==='ended'),error:c.getSnapshot().error};
    } finally { c.exit();URL.revokeObjectURL(url);await Promise.all(contexts.map(c=>c.close())); }
  });
  assert.equal(result.submissions,1);assert.equal(result.tts,1);
  assert.equal(result.phase,'listening');assert(result.oldReleased && result.allReleased);
  console.log(JSON.stringify({syntheticBrowserLoop:'passed',...result}));
} finally {await browser.close();}
