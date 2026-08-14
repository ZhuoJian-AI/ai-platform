const { chromium } = require('playwright');
const BASE='http://[::1]:5173';
async function login(u){
  const r=await fetch('http://127.0.0.1:8000/api/v1/users/login-by-slug',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:'starclothing',username:u,password:'12345678'})});
  return await r.json();
}
(async()=>{
  const {access_token,user}=await login('dev-lead');
  console.log('step: logged in');
  const b=await chromium.launch({args:['--no-sandbox']});
  console.log('step: launched');
  const ctx=await b.newContext({viewport:{width:1500,height:1000}});
  await ctx.addInitScript(([t,u])=>{localStorage.setItem('ai_infra_user_token',t);localStorage.setItem('ai_infra_user',JSON.stringify(u));},[access_token,user]);
  const p=await ctx.newPage();
  console.log('step: newPage');
  const apis=[];
  p.on('request',r=>{const u=r.url();if(u.includes('/api/'))console.log('REQ',u.replace(BASE,''));});
  p.on('response',async r=>{try{const u=r.url();if(u.includes('/api/'))apis.push(`${r.status()} ${u.replace(BASE,'')}`);}catch(e){}});
  p.on('console',m=>console.log('[console]',m.type(),m.text().slice(0,200)));
  p.on('pageerror',e=>console.log('[pageerror]',e.message.slice(0,200)));
  await p.route('**/api/v1/**',async route=>{
    const req=route.request();const url=new URL(req.url());
    const target='http://127.0.0.1:8000'+url.pathname+url.search;
    const h={};for(const[k,v]of Object.entries(req.headers()))if(['authorization','content-type','accept'].includes(k.toLowerCase()))h[k]=v;
    try{const resp=await fetch(target,{method:req.method(),headers:h,body:['GET','HEAD'].includes(req.method())?undefined:(req.postData()||undefined)});
      const buf=Buffer.from(await resp.arrayBuffer());const rh={};resp.headers.forEach((v,k)=>{if(!['content-encoding','content-length','transfer-encoding','connection'].includes(k.toLowerCase()))rh[k]=v;});
      await route.fulfill({status:resp.status,headers:rh,body:buf});
    }catch(e){console.log('[route err]',e.message);await route.continue();}
  });
  console.log('step: route set, goto...');
  await p.goto(`${BASE}/starclothing/terminal`,{waitUntil:'domcontentloaded',timeout:30000});
  console.log('step: goto done, url=',p.url());
  await p.waitForTimeout(6000);
  console.log('step: waited, url=',p.url(),'title=',await p.title());
  console.log('APIs:\n'+apis.join('\n'));
  await p.screenshot({path:'/tmp/pwpdf/debug.png'});
  console.log('step: screenshot done');
  await b.close();
  console.log('step: closed');
})().catch(e=>{console.error('ERR',e)});
