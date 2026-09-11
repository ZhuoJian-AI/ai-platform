import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

const base=process.env.E2E_BASE_URL;
assert.ok(base && process.env.E2E_ADMIN_USERNAME && process.env.E2E_ADMIN_PASSWORD && process.env.E2E_USERNAME);
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--no-proxy-server']});
const page=await browser.newPage();
let role, user;
const fileIds=[];
async function api(path,method='GET',body) {
 return page.evaluate(async ({path,method,body})=>{
  const headers={'Content-Type':'application/json'};
  if(method!=='GET') {
   const c=await fetch('/api/v1/auth/csrf',{credentials:'include'});
   if(!c.ok) throw new Error(`CSRF ${c.status}`);
   headers['X-CSRF-Token']=(await c.json()).csrf_token;
  }
  const r=await fetch(`/api/v1/${path}`,{method,credentials:'include',headers,body:body?JSON.stringify(body):undefined});
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status}`);
  return r.status===204?null:r.json();
 },{path,method,body});
}
async function run(phase,taskId) {
 const events=[];
 await new Promise((resolve,reject)=>{
  const child=spawn(process.execPath,['scripts/e2e-assistant-media-live.mjs'],{
   env:{...process.env,E2E_MEDIA_PHASE:phase,E2E_RESUME_TASK:taskId||'',E2E_INSPECT_ONLY:''},stdio:['ignore','pipe','pipe']});
  let pending='';
  child.stdout.on('data',chunk=>{
   process.stdout.write(chunk); pending+=chunk;
   const lines=pending.split('\n'); pending=lines.pop();
   for (const line of lines) { try { const event=JSON.parse(line);events.push(event);if(event.fileId)fileIds.push(event.fileId); } catch {} }
  });
  child.stderr.on('data',chunk=>process.stderr.write(chunk));
  child.on('error',reject);
  child.on('close',code=>code===0?resolve():reject(new Error(`${phase} failed: ${code}`)));
 });
 return events.find(e=>e.step==='submitted').taskId;
}
try {
 await page.goto(`${base}/login`);
 await page.getByPlaceholder('用户名',{exact:true}).fill(process.env.E2E_ADMIN_USERNAME);
 await page.getByPlaceholder('密码',{exact:true}).fill(process.env.E2E_ADMIN_PASSWORD);
 await page.getByRole('button',{name:'登 录'}).click();
 await page.waitForURL(url=>!url.pathname.endsWith('/login'));
 const orgs=await api('organizations');
 const org=(Array.isArray(orgs)?orgs:orgs.items).find(o=>o.slug==='alphabet');
 assert.ok(org);
 const users=await api(`organizations/${org.id}/users`);
 user=(Array.isArray(users)?users:users.items).find(u=>u.username===process.env.E2E_USERNAME);
 assert.ok(user && Array.isArray(user.role_ids));
 role=await api(`organizations/${org.id}/roles`,'POST',{name:`E2E-MEDIA-${Date.now()}`,code:`e2e-media-${Date.now()}`,data_scope:'self'});
 await api(`roles/${role.id}/permissions`,'PUT',{permission_codes:['multimodal.speech.use','multimodal.audio.transcribe']});
 await api(`users/${user.id}/roles`,'PUT',{role_ids:[...user.role_ids,role.id]});
 console.log(JSON.stringify({step:'temporary_role_granted',roleId:role.id,userId:user.id,originalRoleIds:user.role_ids}));
 const speech=await run('speech');
 await run('asr',speech);
 await run('design');
 const image=await run('image');
 await run('vision',image);
} finally {
 try {
  if(user && role) {
   const current=await api(`users/${user.id}`);
   const remaining=current.role_ids.filter(id=>id!==role.id);
   await api(`users/${user.id}/roles`,'PUT',{role_ids:remaining});
   assert.ok(user.role_ids.every(id=>remaining.includes(id)),'Original role changed concurrently');
   await api(`roles/${role.id}`,'DELETE');
   console.log(JSON.stringify({step:'temporary_role_removed',roleId:role.id,originalRolesPreserved:true}));
  }
  for(const id of fileIds) {
   const file=await api(`files/${id}`);
   assert.ok(/(?:^|-)E2E-MEDIA-(speech|design|image)-\d+\.(mp3|png)$/.test(file.path.split('/').pop()));
   await api(`files/${id}`,'DELETE',{base_version_id:file.current_version_id,idempotency_key:`e2e-media-cleanup-${id}`});
   console.log(JSON.stringify({fileId:id,cleanup:'recycle_bin',recoverable:true}));
  }
 } finally {await browser.close();}
}
