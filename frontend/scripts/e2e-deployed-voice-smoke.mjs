// Deployed assets/API/LLM/TTS. Only microphone and ASR response are synthetic.
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base='https://ai-platform.staging.zhuojianai.com';
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--no-proxy-server','--autoplay-policy=no-user-gesture-required']});
const page=await browser.newPage();let taskId;let submits=0;const segments=[];
const label='E2E-voice-'+Date.now();
page.on('response',async response=>{
 const path=new URL(response.url()).pathname;
 if(path==='/api/v1/terminal/tasks'&&response.request().method()==='POST'&&response.ok())taskId=(await response.json()).id;
 if(/\/tasks\/[^/]+\/run$/.test(path)&&response.request().method()==='POST')submits++;
 if(path==='/api/v1/multimodal/run-speech'&&response.ok())segments.push(await response.json());
});
try{
 await page.goto(base+'/alphabet/terminal/login');
 await page.getByPlaceholder('用户名',{exact:true}).fill(process.env.E2E_EMPLOYEE_USERNAME);
 await page.getByPlaceholder('密码',{exact:true}).fill(process.env.E2E_EMPLOYEE_PASSWORD);
 await page.getByRole('button',{name:/登\s*录/}).click();await page.waitForURL(u=>!u.pathname.endsWith('/login'));
 await page.route('**/api/v1/multimodal/recordings',r=>r.fulfill({json:{job_id:'e2e-recording',url:base+'/e2e-audio-upload',headers:{}}}));
 await page.route('**/e2e-audio-upload',r=>r.fulfill({status:200,body:''}));
 await page.route('**/api/v1/multimodal/recordings/e2e-recording/**',r=>r.fulfill({json:{job_id:'e2e-recording'}}));
 await page.route('**/api/v1/multimodal/jobs/e2e-recording',r=>r.fulfill({json:{status:'succeeded',result:{text:label+'：请用六个简短中文句子介绍睡眠的好处。不要标题、表格、链接，不查询业务数据，不生成文件。'}}}));
 await page.evaluate(()=>{
  window.__tracks=[];window.__contexts=[];window.__played=0;
  navigator.mediaDevices.getUserMedia=async()=>{const ctx=new AudioContext();window.__contexts.push(ctx);const d=ctx.createMediaStreamDestination();const o=ctx.createOscillator();o.connect(d);o.start();window.__tracks.push(...d.stream.getTracks());return d.stream;};
  const play=HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play=function(){this.addEventListener('playing',()=>window.__played++,{once:true});return play.call(this);};
 });
 await page.getByRole('button',{name:'语音模式',exact:true}).click();
 await page.waitForFunction(()=>window.__tracks.length===1);await page.waitForTimeout(500);
 await page.getByRole('button',{name:'语音设置'}).click();await page.getByRole('button',{name:'结束本句',exact:true}).click();
 await page.waitForFunction(()=>window.__played>0&&window.__tracks.length>=2,{},{timeout:150000});
 await page.getByRole('button',{name:'退出语音'}).last().click();
 const report=await page.evaluate(()=>({played:window.__played,released:window.__tracks.every(t=>t.readyState==='ended')}));
 assert.equal(submits,1);assert(report.played>0&&report.released);assert(segments.length>0);
 console.log(JSON.stringify({deployed:true,taskId,submits,segments:segments.length,...report}));
}finally{
 // Use the already authenticated app's own deletion UI; never read or inject tokens.
 if(taskId){
  await page.goto(base+'/alphabet/terminal/tasks/'+taskId);
  await page.getByRole('button',{name:new RegExp('^管理任务 '+label)}).click();
  await page.getByRole('menuitem',{name:/删除/}).click();
  const deleted=page.waitForResponse(r=>r.request().method()==='DELETE'&&new URL(r.url()).pathname==='/api/v1/terminal/tasks/'+taskId);
  await page.getByRole('button',{name:'删除',exact:true}).click();
  assert((await deleted).ok(),'E2E task cleanup failed');
 }
 await page.evaluate(()=>Promise.all((window.__contexts||[]).map(c=>c.close()))).catch(()=>{});
 await browser.close();
}
