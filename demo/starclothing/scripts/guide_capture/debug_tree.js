const { chromium } = require('playwright');
const WEB='http://[::1]:5173', API='http://127.0.0.1:8000', SLUG='starclothing', PASS='12345678';
async function adminLogin(){const r=await fetch(`${API}/api/v1/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:SLUG,username:'admin',password:PASS})});if(!r.ok)throw new Error(r.status);return await r.json();}
(async()=>{
  const {access_token,admin}=await adminLogin();
  const b=await chromium.launch({args:['--no-sandbox']});
  const ctx=await b.newContext({viewport:{width:1500,height:1000},deviceScaleFactor:2});
  await ctx.addInitScript(([t,a])=>{localStorage.setItem('ai_infra_token',t);localStorage.setItem('ai_infra_admin',JSON.stringify(a));},[access_token,admin]);
  await ctx.route('**/api/v1/**',async route=>{const req=route.request();const u=new URL(req.url());const tg=API+u.pathname+u.search;const h={};for(const[k,v]of Object.entries(req.headers()))if(['authorization','content-type','accept'].includes(k.toLowerCase()))h[k]=v;try{const r=await fetch(tg,{method:req.method(),headers:h,body:['GET','HEAD'].includes(req.method())?undefined:(req.postData()||undefined)});const buf=Buffer.from(await r.arrayBuffer());const rh={};r.headers.forEach((v,k)=>{if(!['content-encoding','content-length','transfer-encoding','connection'].includes(k.toLowerCase()))rh[k]=v;});await route.fulfill({status:r.status,headers:rh,body:buf});}catch(e){await route.continue();}});
  const page=await ctx.newPage();
  for(const route of ['/dlp','/agent/memory','/tools/skills']){
    await page.goto(`${WEB}${route}`,{waitUntil:'domcontentloaded'});
    await page.waitForTimeout(4000);
    const asideCount=await page.locator('aside').count();
    const asideText=await page.locator('aside').first().innerText().catch(()=>'(no aside)');
    const hasXingtu=await page.getByText('星途服装',{exact:true}).count();
    const hasKaiFaBu=await page.getByText('开发部',{exact:true}).count();
    const hasKaiFaZhang=await page.getByText('开发部长',{exact:true}).count();
    const hasPinKong=await page.getByText('品控部',{exact:true}).count();
    const hasShangPin=await page.getByText('商品部',{exact:true}).count();
    console.log(`\n=== ${route} ===`);
    console.log('aside count:',asideCount);
    console.log('aside text (first 300):',asideText.slice(0,300).replace(/\n/g,' | '));
    console.log(`星途服装:${hasXingtu} 开发部:${hasKaiFaBu} 开发部长:${hasKaiFaZhang} 品控部:${hasPinKong} 商品部:${hasShangPin}`);
    await page.screenshot({path:`/tmp/debug_${route.replace(/\//g,'_')}.png`});
  }
  await b.close();
})().catch(e=>{console.error('ERR',e);process.exit(1)});
