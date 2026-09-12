// Read-only diagnostic. Never print SSO query strings, cookies or tokens.
import {chromium} from 'playwright';
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--no-proxy-server']});
const page=await browser.newPage();
const failures=[];
const safe=url=>{try{const u=new URL(url);return u.origin+u.pathname;}catch{return 'unknown';}};
page.on('requestfailed',r=>failures.push({url:safe(r.url()),error:r.failure()?.errorText}));
page.on('response',async r=>{if(r.status()>=400){
 const entry={url:safe(r.url()),status:r.status()};failures.push(entry);
 if(new URL(r.url()).pathname==='/api/integration/sso'){
  entry.csp=r.headers()['content-security-policy'];
  const data=await r.json().catch(()=>null);
  if(data) entry.error={code:data.code,error:data.error,message:data.message,detail:data.detail};
 }
}});
try{
 await page.goto('http://127.0.0.1:4183/alphabet/terminal/login');
 await page.getByPlaceholder('用户名',{exact:true}).fill(process.env.E2E_EMPLOYEE_USERNAME);
 await page.getByPlaceholder('密码',{exact:true}).fill(process.env.E2E_EMPLOYEE_PASSWORD);
 await page.getByRole('button',{name:/登\s*录/}).click();
 await page.waitForURL(u=>!u.pathname.endsWith('/login'));
 await page.getByText('爱法贝生产协同',{exact:true}).first().click();
 await page.waitForTimeout(8000);
 console.log(JSON.stringify({failures,frames:page.frames().map(f=>safe(f.url())),alerts:await page.getByRole('alert').allTextContents()}));
}finally{await browser.close();}
