// starexploration 终端任务截图（9 场景，第一屏 + 最后一屏）
// 自包含：login → 创建任务(绑 template_agent_id) → POST run（SSE 跑到 final）→ 截图 top + bottom。
// 运行：cd /root/ai_infra/frontend && NODE_PATH=$PWD/node_modules node /root/ai_infra/demo/starexploration/scripts/guide_capture/capture_terminal.js
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'http://[::1]:5173', API = 'http://127.0.0.1:8000', SLUG = 'starexploration', PASS = '12345678';
const OUT = '/root/ai_infra/demo/starexploration/shots';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// 9 场景：归口用户 + 任务标题 + template_agent_id + composer（不含场景代号，用具体示例）
const SCEN = [
  { key:'des01', user:'des-engineer', title:'设计方案智能比选与规范合规校验', agent:'3f879a34-46ec-49de-89b3-604bfe8dc1b0',
    msg:'对 SCH-IND-001 电工装备制造厂房方案做规范合规校验：重点查图纸 DWG-ARC-001 与 DWG-STR-001 的强条合规性，并列出该方案内跨专业碰撞 CLS-。' },
  { key:'qto01', user:'cost-estimator', title:'智能算量与造价测算', agent:'5f8d0103-eec8-4329-888d-495bff80f642',
    msg:'按 SCH-IND-001 方案做智能算量与造价测算：聚合算量项 QTI-CON-/QTI-STE-，联动 ERP 物料 M-CON-001/M-STE-001 查单价（prefix 转换），输出造价与成本偏差。' },
  { key:'fin01', user:'fin-accountant', title:'票据识别审核与智能核算', agent:'fdbda49c-c8bf-45f3-b080-faca64cff369',
    msg:'做票据识别审核与智能核算：查发票 INV202607001 关联凭证 BV-SE-2026-0701 对账，应收 REC- 与应付 SEAP- 差异闭环，列出逾期风险。' },
  { key:'adm01', user:'admin-officer', title:'公文生成与会议纪要闭环', agent:'788a9132-9bff-4e96-baee-774be4731294',
    msg:'基于会议纪要 SEMT-20260002 周度经营调度会生成纪要与待办闭环：提取待办事项与责任人 SEOF-，跨部门分发设计院 PD-DES / 安全部 PD-SAF / 保密办 PD-SEC，跟踪任务闭环。' },
  { key:'leg01', user:'leg-counsel', title:'合同智能审查与履约风险校验', agent:'bd6e5ba7-02ea-4e05-834c-89040e49aa26',
    msg:'对合同 CT-SE-002 电池工厂 EPC 总承包合同做智能审查：提取关键条款、识别风险点（付款里程碑/保密条款）、关联项目 PRJ-BAT-001 与履约争议 DSP-，给修改建议与履约节点提醒。' },
  { key:'epc01', user:'epc-manager', title:'项目进度风险预警与成本管控', agent:'8164ca06-32c3-4a72-8cca-3468ed5f7634',
    msg:'对 PRJ-IND-001 电工装备厂房 EPC 项目做进度风险预警与成本管控：查关键路径工序 SCD- 延误、predictScheduleRisk 风险等级、项目成本 PC-SE- 与合同 CT-SE-001 偏差，输出赶工建议。' },
  { key:'saf01', user:'saf-inspector', title:'施工现场安全隐患智能识别', agent:'4ee432cc-3376-4af8-bcf0-8953a797e17d',
    msg:'对 PRJ-IND-001 项目做现场安全隐患识别：摄像头 C07 画面『3 名作业人员未戴安全帽通过 2#塔吊下方作业区』，调 detectSiteHazard 识别隐患 HAZ- 与整改工单 RO-，闭环整改。' },
  { key:'sec01', user:'sec-officer', title:'涉密内容检测与文档脱密', agent:'c45d1171-33d2-4e5c-a3fd-c0c76d46e621',
    msg:'对来源图纸 DWG-STR-001 做涉密检测：调 scanConfidentiality 返密级与涉密标记 SECMARK-，机密/秘密则调 desensitizeDocument 产脱敏记录 DESEN-，并列保密行为预警 BHV-。' },
  { key:'hr01', user:'hr-recruiter', title:'智能招聘与人岗匹配', agent:'3f9b762c-e9ef-4ff3-8258-75478aff7029',
    msg:'对 P-DES 设计师急招需求 ASRC20260000 做人岗匹配：调 listResumesByPosition 查简历 SERM-，按学历/年限/技能标签/评分匹配，输出短名单与录用建议。' },
];

async function routeApi(page){
  await page.route('**/api/v1/**', async route => {
    const req = route.request();
    try {
      const u = new URL(req.url());
      const target = API + u.pathname + u.search;
      const h = {};
      for (const [k,v] of Object.entries(req.headers())) if (['authorization','content-type','accept'].includes(k.toLowerCase())) h[k]=v;
      const resp = await fetch(target, { method: req.method(), headers: h, body: ['GET','HEAD'].includes(req.method())?undefined:(req.postData()||undefined) });
      const buf = Buffer.from(await resp.arrayBuffer());
      const rh = {};
      resp.headers.forEach((v,k)=>{ if(!['content-encoding','content-length','transfer-encoding','connection'].includes(k.toLowerCase())) rh[k]=v; });
      await route.fulfill({ status: resp.status, headers: rh, body: buf });
    } catch(e){ await route.continue(); }
  });
}

async function login(user){
  const r = await fetch(`${API}/api/v1/users/login-by-slug`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:SLUG,username:user,password:PASS})});
  if(!r.ok) throw new Error(`login ${user} ${r.status}`);
  return await r.json();
}

async function createAndRun(access_token, s){
  const taskRes = await fetch(`${API}/api/v1/terminal/tasks`,{method:'POST',headers:{'Authorization':`Bearer ${access_token}`,'Content-Type':'application/json'},body:JSON.stringify({title:s.title,config:{template_agent_id:s.agent,skill_ids:[],model_alias:'glm-5.2',exec_mode:'craft'}})});
  if(!taskRes.ok) throw new Error(`create task ${s.key} ${taskRes.status} ${await taskRes.text()}`);
  const task = await taskRes.json();
  const ctrl = new AbortController();
  const to = setTimeout(()=>ctrl.abort(), 300000);
  try {
    const r = await fetch(`${API}/api/v1/terminal/tasks/${task.id}/run`,{method:'POST',headers:{'Authorization':`Bearer ${access_token}`,'Content-Type':'application/json'},body:JSON.stringify({message:s.msg,stream:true}),signal:ctrl.signal});
    const reader = r.body.getReader(); const dec = new TextDecoder();
    let done=false;
    while(!done){
      const { value, done: rd } = await reader.read();
      if(rd) break;
      const txt = dec.decode(value,{stream:true});
      if(txt.includes('"type":"final"') || txt.includes('"type":"done"') || txt.includes('data: [DONE]')) done=true;
    }
  } catch(e){ /* abort on done/timeout fine */ }
  finally{ clearTimeout(to); }
  return task.id;
}

async function setMsgScroll(page, toTop){
  await page.evaluate(top => {
    const picks = [];
    document.querySelectorAll('div').forEach(d => {
      const s = getComputedStyle(d);
      if ((s.overflowY==='auto'||s.overflowY==='scroll') && d.scrollHeight > d.clientHeight + 4) picks.push(d);
    });
    const target = picks.find(d => d.querySelector('.wb-md'))
                || picks.sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
    if (target) target.scrollTop = top ? 0 : target.scrollHeight;
  }, toTop);
}

(async()=>{
  const browser = await chromium.launch({args:['--no-sandbox']});
  for(const s of SCEN){
    const ctx = await browser.newContext({viewport:{width:1500,height:1000},deviceScaleFactor:2});
    try{
      const { access_token, user } = await login(s.user);
      await ctx.addInitScript(([tok,u])=>{localStorage.setItem('ai_infra_user_token',tok);localStorage.setItem('ai_infra_user',JSON.stringify(u));},[access_token,user]);
      const page = await ctx.newPage();
      await routeApi(page);
      const taskId = await createAndRun(access_token, s);
      await page.goto(`${BASE}/${SLUG}/terminal`,{waitUntil:'domcontentloaded',timeout:30000});
      await page.waitForTimeout(2500);
      const item = page.getByText(s.title,{exact:false}).first();
      await item.waitFor({state:'visible',timeout:20000});
      await item.click();
      try { await page.getByText('场景模板注入',{exact:false}).first().waitFor({state:'visible',timeout:25000}); }
      catch { await page.getByText('已完成',{exact:false}).first().waitFor({state:'visible',timeout:15000}); }
      await page.waitForTimeout(2500);
      await setMsgScroll(page, true);
      await page.waitForTimeout(1200);
      await page.screenshot({path:`${OUT}/${s.key}_top.png`});
      await setMsgScroll(page, false);
      await page.waitForTimeout(1800);
      await page.screenshot({path:`${OUT}/${s.key}.png`,fullPage:true});
      console.log(`OK ${s.key} (${s.user}) task=${taskId}`);
    }catch(e){
      console.error(`FAIL ${s.key} (${s.user}): ${e.message.split('\n')[0]}`);
    }finally{ await ctx.close(); }
  }
  await browser.close();
  console.log('done');
})().catch(e=>{console.error('ERR',e);process.exit(1)});
