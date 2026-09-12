// Real candidate login/UI/navigation; synthetic audio isolates lifecycle from provider latency.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const base = process.env.E2E_BASE || 'http://127.0.0.1:4183';
assert.equal(new URL(base).hostname, '127.0.0.1');
const browser = await chromium.launch({channel:'chrome',headless:true,args:['--no-proxy-server','--autoplay-policy=no-user-gesture-required']});
const page = await browser.newPage();
let taskId;
try {
  await page.goto(base+'/alphabet/terminal/login');
  await page.getByPlaceholder('用户名',{exact:true}).fill(process.env.E2E_EMPLOYEE_USERNAME);
  await page.getByPlaceholder('密码',{exact:true}).fill(process.env.E2E_EMPLOYEE_PASSWORD);
  await page.getByRole('button',{name:/登\s*录/}).click();
  await page.waitForURL(u=>!u.pathname.endsWith('/login'));
  await page.evaluate(async()=>{
    const compiled=await(await fetch('/src/pages/terminal/browserVoiceAdapter.ts')).text();
    const clientPath=compiled.match(/from "([^\"]*\/api\/client.ts[^\"]*)"/)[1];
    const {terminal,multimodal}=await import(clientPath);
    const apps=await terminal.applications();
    window.__voiceApplications=(Array.isArray(apps)?apps:apps.items||apps.applications||[]).map(a=>({id:a.id,name:a.name}));
    const original=terminal.resources.bind(terminal);
    terminal.resources=async()=>({...await original(),audio_capabilities:{speech_to_text:{available:true},text_to_speech:{available:true}}});
    window.__voiceTracks=[];window.__voiceContexts=[];
    navigator.mediaDevices.getUserMedia=async()=>{
      const ctx=new AudioContext();window.__voiceContexts.push(ctx);
      const dest=ctx.createMediaStreamDestination();const osc=ctx.createOscillator();osc.connect(dest);osc.start();
      window.__voiceTracks.push(...dest.stream.getTracks());return dest.stream;
    };
    const originalFetch=window.fetch;
    window.fetch=(url,init)=>url==='/synthetic-upload'?Promise.resolve(new Response('',{status:200})):originalFetch(url,init);
    multimodal.createRecording=async()=>({job_id:'synthetic-recording',url:'/synthetic-upload',headers:{}});
    multimodal.completeRecording=async()=>({});multimodal.cancelRecording=async()=>({});
    const originalJob=multimodal.job.bind(multimodal);
    multimodal.job=async id=>id==='synthetic-recording'?{status:'succeeded',result:{text:'请打开爱法贝生产协同的进度看板。'}}:originalJob(id);
    window.__createdTasks=[];
    const create=terminal.createTask.bind(terminal);
    terminal.createTask=async args=>{const task=await create({...args,title:'E2E-voice-navigation-'+Date.now()});window.__createdTasks.push(task.id);return task;};
  });
  console.log(JSON.stringify(await page.evaluate(()=>({applications:window.__voiceApplications}))));
  if(process.env.E2E_PREFLIGHT_ONLY==='1') { await browser.close(); process.exit(0); }
  await page.getByRole('button',{name:'语音模式',exact:true}).click();
  await page.getByText('正在听，请说话',{exact:true}).waitFor();
  await page.waitForFunction(()=>window.__voiceTracks.length===1);
  // Allow MediaRecorder's first chunk; the listening label precedes mic acquisition.
  await page.waitForTimeout(500);
  await page.getByRole('button',{name:'语音设置'}).click();
  await page.getByLabel('静音回复').check();
  await page.getByRole('button',{name:'结束本句',exact:true}).click();
  await page.waitForFunction(()=>window.__createdTasks.length===1,{},{timeout:30000});
  taskId=await page.evaluate(()=>window.__createdTasks[0]);
  await page.getByText('已连接当前模块：',{exact:false}).waitFor({timeout:120000});
  const result=await page.evaluate(()=>({tasks:window.__createdTasks,url:location.href,
    voiceActive:!!document.querySelector('button[aria-label="退出语音"]'),
    frames:[...document.querySelectorAll('iframe')].map(f=>({src:f.src,loaded:!!f.contentWindow})),
    currentTurnVisible:[...document.querySelectorAll('[data-user-turn]')].some(e=>e.textContent.includes('请打开爱法贝')&&e.getBoundingClientRect().top>=0&&e.getBoundingClientRect().top<innerHeight)}));
  assert.equal(result.tasks.length,1);assert(result.voiceActive);assert(result.currentTurnVisible);
  await page.getByRole('button',{name:'退出语音'}).last().click();
  assert(await page.evaluate(()=>window.__voiceTracks.every(t=>t.readyState==='ended')));
  console.log(JSON.stringify({...result,allTracksReleased:true}));
} catch(error) {
  console.log(JSON.stringify(await page.evaluate(()=>({url:location.href,status:[...document.querySelectorAll('[role="status"],[role="alert"]')].map(e=>e.textContent),tasks:window.__createdTasks,tracks:window.__voiceTracks?.map(t=>t.readyState)}))));
  console.log(JSON.stringify(await page.evaluate(()=>({applications:window.__voiceApplications}))));
  throw error;
} finally {
  if(taskId) await page.evaluate(async id=>{const {terminal}=await import('/src/api/client.ts');await terminal.cancelTask(id).catch(()=>{});await terminal.deleteTask(id);},taskId).catch(()=>{});
  await page.evaluate(()=>Promise.all((window.__voiceContexts||[]).map(c=>c.close()))).catch(()=>{});
  await browser.close();
}
