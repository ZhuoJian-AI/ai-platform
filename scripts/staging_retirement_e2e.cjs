const { chromium } = require('../frontend/node_modules/playwright');

const baseUrl = process.env.E2E_BASE_URL || 'https://ai-platform.staging.zhuojianai.com';
const adminUsername = process.env.E2E_ADMIN_USERNAME;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const employeeUsername = process.env.E2E_EMPLOYEE_USERNAME;
const employeePassword = process.env.E2E_EMPLOYEE_PASSWORD;

if (!adminUsername || !adminPassword || !employeeUsername || !employeePassword) {
  throw new Error('缺少 E2E 管理员或员工凭据环境变量');
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function diagnostics(page) {
  const javascriptErrors = [];
  const serverErrors = [];
  page.on('pageerror', (error) => javascriptErrors.push(error.message));
  page.on('response', (response) => {
    if (response.status() >= 500) {
      serverErrors.push({ status: response.status(), url: response.url() });
    }
  });
  return { javascriptErrors, serverErrors };
}

async function login(page, url, username, password) {
  await page.goto(`${baseUrl}${url}`, { waitUntil: 'networkidle' });
  const usernameInput = page.locator('input[autocomplete="username"]');
  const passwordInput = page.locator('input[autocomplete="current-password"]');
  await usernameInput.fill(username);
  await passwordInput.fill(`${password}-E2E-错误`);
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await page.waitForFunction(
    () => /密码|错误|失败|不正确|无效/.test(document.body.innerText),
    undefined,
    { timeout: 10_000 },
  ).catch(() => undefined);
  const rejectedText = await page.locator('body').innerText();
  assert(/密码|错误|失败|不正确|无效/.test(rejectedText), `${url} 错误密码没有中文提示`);
  await passwordInput.fill(password);
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await page.waitForURL((current) => !current.pathname.endsWith('/login'), { timeout: 20_000 });
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(500);
}

async function adminFlow(browser) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const observed = diagnostics(page);
  await login(page, '/login', adminUsername, adminPassword);

  const routes = [
    ['/org/structure', '组织架构'],
    ['/enterprise-apps', '企业模块'],
    ['/enterprise-apps/permissions', '角色权限'],
    ['/org/users', '员工授权'],
    ['/org/admins', '管理员'],
    ['/org/profile', '企业资料'],
    ['/org/contact', '联系方式'],
    ['/keys', 'API Key 管理'],
    ['/providers', '模型提供商'],
    ['/dlp', '安全围栏'],
    ['/agent/workspaces?view=workspace', '工作空间'],
    ['/agent/agents', '智能体'],
    ['/agent/memory', '长期记忆'],
    ['/monitor/overview', '总览'],
    ['/monitor/router', '路由器监控'],
    ['/monitor/agents', '智能体监控'],
    ['/monitor/tools', '工具监控'],
  ];
  const routeResults = [];
  for (const [route, expected] of routes) {
    const response = await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle' });
    const body = await page.locator('body').innerText();
    const ok = response && response.status() < 400 && body.includes(expected) && body.trim().length > 20;
    routeResults.push({ route, expected, status: response?.status(), ok });
    assert(ok, `管理员页面不可用：${route}`);
    assert(!body.includes('知识库'), `管理员页面仍显示知识库：${route}`);
    assert(!body.includes('\n技能\n'), `管理员页面仍显示技能：${route}`);
    if (route === '/providers') {
      assert(!/embedding/i.test(body), '模型提供商页面仍显示 Embedding 配置');
    }
  }

  await page.goto(`${baseUrl}/agent/agents`, { waitUntil: 'networkidle' });
  const temporaryName = 'E2E-RETIRE-TEXT-20260909';
  const existing = page.getByText(temporaryName, { exact: true });
  let temporaryAgentCleaned = false;
  if (await existing.count()) {
    await existing.first().evaluate((element) => element.click());
    await page.waitForTimeout(300);
    const editorText = await page.locator('main').innerText();
    assert(editorText.includes('文本角色继承个人助手'), '智能体没有退化为文本角色');
    assert(!/RAG|Skill|工作空间绑定|业务页面/.test(editorText), '智能体仍暴露已退役绑定配置');
    await page.locator('main button').filter({ hasText: '删除' }).evaluate((element) => element.click());
    await page.waitForTimeout(200);
    const confirmDelete = page.getByRole('button', { name: '删除', exact: true }).last();
    const deleteResponse = page.waitForResponse(
      (response) => response.request().method() === 'DELETE' && response.url().includes('/agents/'),
    );
    await confirmDelete.evaluate((element) => element.click());
    assert((await deleteResponse).status() === 204, 'E2E 文本智能体删除失败');
    temporaryAgentCleaned = true;
  } else {
    const result = await page.evaluate(async ({ id }) => {
      const csrf = document.cookie
        .split('; ')
        .find((item) => item.startsWith('ai_infra_admin_csrf='))
        ?.split('=')
        .slice(1)
        .join('=');
      const response = await fetch(`/api/v1/agents/${id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {},
      });
      return { status: response.status, body: await response.text() };
    }, { id: '4eeee1ac-3876-49ef-90be-aa2954510d23' });
    assert(result.status === 204 || result.status === 404, `E2E 文本智能体 API 清理失败：${result.status}`);
    temporaryAgentCleaned = true;
  }

  const embeddingApiRejection = await page.evaluate(async () => {
    const csrf = document.cookie
      .split('; ')
      .find((item) => item.startsWith('ai_infra_admin_csrf='))
      ?.split('=')
      .slice(1)
      .join('=');
    const headers = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
    const organizationResponse = await fetch('/api/v1/organizations', { credentials: 'same-origin' });
    const organizations = await organizationResponse.json().catch(() => []);
    const organization = Array.isArray(organizations) ? organizations[0] : null;
    if (!organization?.id) return { skipped: true, reason: '没有可用于负向验证的企业' };
    const providerResponse = await fetch(`/api/v1/organizations/${organization.id}/providers`, {
      credentials: 'same-origin',
    });
    const providers = await providerResponse.json().catch(() => []);
    const provider = Array.isArray(providers) ? providers[0] : null;
    if (!provider?.id) return { skipped: true, reason: '没有可用于负向验证的模型提供商' };
    const response = await fetch(`/api/v1/providers/${provider.id}/models`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify({
        model_id: 'E2E-EMBEDDING-MUST-BE-REJECTED',
        adapter: 'openai_embeddings',
        capabilities: ['embedding'],
      }),
    });
    return { skipped: false, status: response.status, body: await response.text() };
  });
  assert(
    embeddingApiRejection.skipped || embeddingApiRejection.status === 422,
    `管理员仍可创建 Embedding 部署：${JSON.stringify(embeddingApiRejection)}`,
  );

  await context.close();
  return { routeResults, temporaryAgentCleaned, embeddingApiRejection, ...observed };
}

async function employeeFlow(browser) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const observed = diagnostics(page);
  await login(page, '/alphabet/terminal/login', employeeUsername, employeePassword);

  const currentUser = await page.evaluate(async () => {
    const token = sessionStorage.getItem('ai_infra_user_token');
    const response = await fetch('/api/v1/terminal/me', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const body = await response.json().catch(() => null);
    return { status: response.status, username: body?.user?.username };
  });
  const homeText = await page.locator('body').innerText();
  assert(
    currentUser.status === 200 && currentUser.username === employeeUsername,
    `员工会话身份校验失败：${JSON.stringify(currentUser)}`,
  );
  assert(homeText.includes('工作空间'), '员工端缺少工作空间');
  assert(homeText.includes('智能体'), '员工端缺少智能体');
  assert(!homeText.includes('知识库'), '员工端仍显示知识库');
  assert(!homeText.includes('\n技能\n'), '员工端仍显示技能');

  const routeResults = [];
  const routes = [
    ['/alphabet/terminal?view=workspace', '工作空间'],
    ['/alphabet/terminal?view=agents', '智能体'],
  ];
  for (const [route, expected] of routes) {
    const response = await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.waitForTimeout(1_200);
    const body = await page.locator('body').innerText();
    const ok = response && response.status() < 400 && body.includes(expected);
    routeResults.push({ route, expected, status: response?.status(), ok });
    assert(ok, `员工页面不可用：${route}`);
  }

  const memoryResult = await page.evaluate(async () => {
    const token = sessionStorage.getItem('ai_infra_user_token');
    const response = await fetch('/api/v1/terminal/memory', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const body = await response.json().catch(() => null);
    return { status: response.status, isList: Array.isArray(body) };
  });
  assert(memoryResult.status === 200, `员工长期记忆接口不可用：${JSON.stringify(memoryResult)}`);
  routeResults.push({ route: '/api/v1/terminal/memory', expected: '长期记忆', status: 200, ok: true });

  await context.close();
  return { routeResults, ...observed };
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    channel: 'chrome',
  });
  try {
    const admin = await adminFlow(browser);
    const employee = await employeeFlow(browser);
    assert(admin.javascriptErrors.length === 0, `管理员端 JavaScript 异常：${admin.javascriptErrors.join('; ')}`);
    assert(employee.javascriptErrors.length === 0, `员工端 JavaScript 异常：${employee.javascriptErrors.join('; ')}`);
    assert(admin.serverErrors.length === 0, `管理员端 5xx：${JSON.stringify(admin.serverErrors)}`);
    assert(employee.serverErrors.length === 0, `员工端 5xx：${JSON.stringify(employee.serverErrors)}`);
    console.log(JSON.stringify({ status: 'passed', admin, employee }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
