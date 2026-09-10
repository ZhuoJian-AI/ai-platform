import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';

const DEFAULT_BASE_URL = 'https://ai-platform.staging.zhuojianai.com';
const REQUIRED_ENV = [
  'E2E_ADMIN_USERNAME',
  'E2E_ADMIN_PASSWORD',
  'E2E_USER_USERNAME',
  'E2E_USER_PASSWORD',
];
const missingEnv = REQUIRED_ENV.filter((name) => !process.env[name]);
if (missingEnv.length) {
  throw new Error(`缺少运行时环境变量：${missingEnv.join('、')}`);
}

const baseUrl = new URL(process.env.E2E_BASE_URL || DEFAULT_BASE_URL);
const orgSlug = process.env.E2E_ORG_SLUG || 'alphabet';
const adminUsername = process.env.E2E_ADMIN_USERNAME;
const adminPassword = process.env.E2E_ADMIN_PASSWORD;
const userUsername = process.env.E2E_USER_USERNAME;
const userPassword = process.env.E2E_USER_PASSWORD;
const applicationIdOverride = process.env.E2E_APPLICATION_ID || '';
const moduleKey = process.env.E2E_MODULE_KEY || 'progress_dashboard';
const modelAliasOverride = process.env.E2E_MODEL_ALIAS || '';
const proxyServer = process.env.E2E_PROXY_SERVER || '';
const browserExecutable = process.env.E2E_BROWSER_EXECUTABLE || '';
const artifactTimeoutMs = Math.min(
  Math.max(Number(process.env.E2E_ARTIFACT_TIMEOUT_MS || 12 * 60_000), 60_000),
  20 * 60_000,
);

if (
  baseUrl.hostname !== 'ai-platform.staging.zhuojianai.com'
  && process.env.E2E_ALLOW_NON_STAGING !== '1'
) {
  throw new Error('非 staging 地址必须显式设置 E2E_ALLOW_NON_STAGING=1');
}

const runId = `${new Date().toISOString().replace(/\D/g, '').slice(0, 14)}-${crypto.randomUUID().slice(0, 6)}`;
const runMarker = `E2E-${runId}`;
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-platform-staging-core-'));
const outputRoot = `${path.resolve(os.tmpdir())}${path.sep}`.toLowerCase();

const ADMIN_NAVIGATION = [
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
  ['/agent/workspaces', '工作空间'],
  ['/agent/agents', '智能体'],
  ['/agent/memory', '长期记忆'],
  ['/monitor/overview', '总览'],
  ['/monitor/router', '路由器监控'],
  ['/monitor/agents', '智能体监控'],
  ['/monitor/tools', '工具监控'],
];

const ADMIN_DIRECT_ROUTES = [
  ['/org/roles', '角色'],
  ['/enterprise-apps/navigation', '导航配置'],
  ['/enterprise-apps/assistant', '业务助手'],
  ['/org/voices', '音色'],
];

const EMPLOYEE_NAVIGATION = [
  ['工作空间', 'workspace'],
  ['智能体', 'agents'],
];

const RETIRED_ADMIN_ROUTES = ['/agent/rag', '/tools/skills'];
const RETIRED_EMPLOYEE_LABELS = ['知识库', '技能'];

function safePath(value) {
  try {
    const parsed = new URL(value, baseUrl);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return String(value).slice(0, 180);
  }
}

function redact(value) {
  let text = String(value ?? '');
  for (const secret of [adminPassword, userPassword]) {
    if (secret) text = text.split(secret).join('[REDACTED]');
  }
  text = text.replace(/Bearer\s+[A-Za-z0-9._~-]+/gi, 'Bearer [REDACTED]');
  text = text.replace(/https?:\/\/[^\s"'<>]+/gi, (match) => safePath(match));
  return text.slice(0, 800);
}

function exactTextPattern(value) {
  const escaped = String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`^\\s*${escaped}\\s*$`);
}

function diagnosticsFor(page) {
  const consoleErrors = [];
  const serverErrors = [];
  const authorizationErrors = [];
  let authenticated = false;

  page.on('console', (entry) => {
    if (entry.type() === 'error') consoleErrors.push(redact(entry.text()));
  });
  page.on('pageerror', (error) => consoleErrors.push(redact(error.message)));
  page.on('response', (response) => {
    const status = response.status();
    const request = response.request();
    const url = response.url();
    if (status >= 500) serverErrors.push(`${status} ${request.method()} ${safePath(url)}`);
    if (
      authenticated
      && (status === 401 || status === 403)
      && url.startsWith(baseUrl.origin)
      && url.includes('/api/v1/')
    ) {
      authorizationErrors.push(`${status} ${request.method()} ${safePath(url)}`);
    }
  });

  return {
    snapshot() { return { consoleErrors: [...consoleErrors], serverErrors: [...serverErrors], authorizationErrors: [...authorizationErrors] }; },
    authenticated(value = true) { authenticated = value; },
    reset() {
      consoleErrors.length = 0;
      serverErrors.length = 0;
      authorizationErrors.length = 0;
    },
    assertClean(stage) {
      const ignoredConsole = consoleErrors.filter((entry) => !/favicon\.ico/i.test(entry));
      const failures = [...ignoredConsole, ...serverErrors, ...authorizationErrors];
      assert.equal(failures.length, 0, `${stage} 出现浏览器或接口错误：${failures.join('；')}`);
    },
  };
}

async function waitForRenderedMain(page, selector, expectedPath) {
  const main = page.locator(selector);
  await main.waitFor({ state: 'visible', timeout: 30_000 });
  await page.waitForFunction(
    ({ mainSelector, pathname }) => {
      const element = document.querySelector(mainSelector);
      return location.pathname === pathname && (element?.textContent || '').trim().length >= 12;
    },
    { mainSelector: selector, pathname: expectedPath },
    { timeout: 30_000 },
  );
  assert.equal(await main.getByText('页面不存在', { exact: true }).count(), 0, `${expectedPath} 错误进入 404 页面`);
}

async function submitInvalidLogin(page, endpointSuffix, submitButton) {
  await submitButton.waitFor({ state: 'visible', timeout: 120_000 });
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => {
      const candidateUrl = new URL(candidate.url());
      return candidate.request().method() === 'POST' && candidateUrl.pathname === endpointSuffix;
    }, { timeout: 30_000 }),
    submitButton.click(),
  ]);
  assert.equal(response.status(), 401, `错误密码应返回 401，实际为 ${response.status()}`);
  await page.getByText('用户名或密码错误，请重新输入', { exact: true }).waitFor({ timeout: 15_000 });
}

async function loginAdmin(page, diagnostics) {
  await page.goto(new URL('/login', baseUrl).href, { waitUntil: 'commit', timeout: 60_000 });
  const usernameInput = page.getByRole('textbox', { name: '用户名' });
  const passwordInput = page.getByRole('textbox', { name: '密码' });
  const submitButton = page.locator('form#login button[type="submit"]');
  await usernameInput.waitFor({ state: 'visible', timeout: 120_000 });
  await usernameInput.fill(adminUsername);
  await passwordInput.fill(`${runMarker}-invalid`);
  await submitInvalidLogin(page, '/api/v1/auth/login', submitButton);

  await usernameInput.fill(adminUsername);
  await passwordInput.fill(adminPassword);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => (
      candidate.request().method() === 'POST'
      && new URL(candidate.url()).pathname === '/api/v1/auth/login'
    ), { timeout: 30_000 }),
    submitButton.click(),
  ]);
  assert.equal(response.ok(), true, `管理员 UI 登录失败（HTTP ${response.status()}）`);
  await page.waitForURL((url) => url.pathname === '/monitor/router', { timeout: 30_000 });

  const session = await page.evaluate(async () => {
    const response = await fetch('/api/v1/auth/me', { credentials: 'include' });
    if (!response.ok) return { status: response.status, role: null };
    const body = await response.json();
    return { status: response.status, role: body?.role ?? null };
  });
  assert.equal(session.status, 200, '管理员登录后 /auth/me 不可用');
  assert.ok(['platform_super_admin', 'super_admin'].includes(session.role), '管理员账号不是超级平台管理员');
  diagnostics.reset();
  diagnostics.authenticated();
}

async function traverseAdminNavigation(page) {
  const nav = page.locator('aside').first();
  await nav.waitFor({ state: 'visible', timeout: 30_000 });
  for (const [route, label] of ADMIN_NAVIGATION) {
    await nav.locator('button').filter({ hasText: exactTextPattern(label) }).first().click();
    await page.waitForURL((url) => url.pathname === route, { timeout: 30_000 });
    await waitForRenderedMain(page, 'main.admin-shell__main', route);
  }
  for (const [route, marker] of ADMIN_DIRECT_ROUTES) {
    await page.goto(new URL(route, baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await waitForRenderedMain(page, 'main.admin-shell__main', route);
    const text = await page.locator('main.admin-shell__main').innerText();
    assert.ok(text.includes(marker), `${route} 未呈现预期功能标识`);
  }
  for (const route of RETIRED_ADMIN_ROUTES) {
    await page.goto(new URL(route, baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.waitForFunction(
      (retiredRoute) => (
        location.pathname !== retiredRoute
        || document.querySelector('main.admin-shell__main')?.textContent?.includes('页面不存在')
      ),
      route,
      { timeout: 30_000 },
    );
    const currentPath = new URL(page.url()).pathname;
    const showsNotFound = await page.getByText('页面不存在', { exact: true }).count() === 1;
    assert.ok(
      currentPath !== route || showsNotFound,
      `${route} 退役后仍可进入`,
    );
  }
}

async function adminEffectiveAccess(page) {
  return page.evaluate(async ({ canonicalSlug, targetUsername }) => {
    const getJson = async (url) => {
      const response = await fetch(url, { credentials: 'include' });
      if (!response.ok) throw new Error(`只读鉴权接口失败（HTTP ${response.status}）`);
      return response.json();
    };
    const organizations = await getJson('/api/v1/organizations');
    const organization = organizations.find((item) => item.slug === canonicalSlug);
    if (!organization) throw new Error('管理员端找不到目标企业');
    const users = await getJson(`/api/v1/organizations/${organization.id}/users`);
    const user = users.find((item) => String(item.username).toLowerCase() === targetUsername.toLowerCase());
    if (!user) throw new Error('管理员端找不到目标员工');
    return getJson(`/api/v1/users/${user.id}/effective-access`);
  }, { canonicalSlug: orgSlug, targetUsername: userUsername });
}

async function loginEmployee(page, diagnostics) {
  await page.goto(new URL(`/${orgSlug}/terminal/login`, baseUrl).href, {
    waitUntil: 'commit', timeout: 60_000,
  });
  const usernameInput = page.getByRole('textbox', { name: '用户名' });
  const passwordInput = page.getByRole('textbox', { name: '密码' });
  const submitButton = page.locator('form#user-login button[type="submit"]');
  await usernameInput.waitFor({ state: 'visible', timeout: 120_000 });
  await usernameInput.fill(userUsername);
  await passwordInput.fill(`${runMarker}-invalid`);
  await submitInvalidLogin(page, '/api/v1/users/login-by-slug', submitButton);

  await usernameInput.fill(userUsername);
  await passwordInput.fill(userPassword);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => (
      candidate.request().method() === 'POST'
      && new URL(candidate.url()).pathname === '/api/v1/users/login-by-slug'
    ), { timeout: 30_000 }),
    submitButton.click(),
  ]);
  assert.equal(response.ok(), true, `员工 UI 登录失败（HTTP ${response.status()}）`);
  await page.waitForURL((url) => url.pathname === `/${orgSlug}/terminal`, { timeout: 30_000 });
  await page.locator('aside').first().waitFor({ state: 'visible', timeout: 30_000 });

  const me = await userJson(page, '/api/v1/terminal/me');
  assert.equal(String(me.user?.username).toLowerCase(), userUsername.toLowerCase(), '员工会话身份与登录账号不一致');
  diagnostics.reset();
  diagnostics.authenticated();
}

async function userJson(page, url, options = {}) {
  const result = await page.evaluate(async ({ requestUrl, requestOptions }) => {
    const token = sessionStorage.getItem('ai_infra_user_token') || '';
    if (!token) return { ok: false, status: 401, body: null };
    const response = await fetch(requestUrl, {
      ...requestOptions,
      headers: {
        ...(requestOptions.headers || {}),
        Authorization: `Bearer ${token}`,
      },
    });
    const body = response.status === 204 ? null : await response.json().catch(() => null);
    return { ok: response.ok, status: response.status, body };
  }, { requestUrl: url, requestOptions: options });
  assert.equal(result.ok, true, `员工接口 ${safePath(url)} 失败（HTTP ${result.status}）`);
  return result.body;
}

function normalizeEffectiveAccess(access) {
  const roles = (access?.roles || []).map((role) => ({
    id: String(role.id),
    code: String(role.code || ''),
    dataScope: String(role.data_scope || ''),
    builtin: Boolean(role.is_builtin),
  })).sort((left, right) => left.id.localeCompare(right.id));
  const workspaces = (access?.workspaces || []).map((workspace) => ({
    id: String(workspace.id),
    scopeType: String(workspace.scope_type),
    scopeId: workspace.scope_id ? String(workspace.scope_id) : null,
    capabilities: {
      read: Boolean(workspace.capabilities?.read),
      create: Boolean(workspace.capabilities?.create),
      update: Boolean(workspace.capabilities?.update),
      delete: Boolean(workspace.capabilities?.delete),
      manage: Boolean(workspace.capabilities?.manage),
      publish: Boolean(workspace.capabilities?.publish),
    },
  })).sort((left, right) => left.id.localeCompare(right.id));
  return { roles, workspaces };
}

async function traverseEmployeeNavigation(page) {
  const nav = page.locator('aside').first();
  for (const label of RETIRED_EMPLOYEE_LABELS) {
    assert.equal(
      await nav.locator('button').filter({ hasText: exactTextPattern(label) }).count(),
      0,
      `员工端仍显示已退役入口：${label}`,
    );
  }
  for (const [label, view] of EMPLOYEE_NAVIGATION) {
    await nav.locator('button').filter({ hasText: exactTextPattern(label) }).first().click();
    await page.waitForFunction(
      (expectedView) => new URL(location.href).searchParams.get('view') === expectedView,
      view,
      { timeout: 30_000 },
    );
    await waitForRenderedMain(page, 'main.terminal-shell__main', `/${orgSlug}/terminal`);
  }
}

async function selectBusinessApplication(page) {
  const applications = await userJson(page, '/api/v1/terminal/applications');
  assert.ok(Array.isArray(applications) && applications.length > 0, '员工没有任何可见企业应用');
  const application = applicationIdOverride
    ? applications.find((item) => item.id === applicationIdOverride)
    : applications.find((item) => (
      item.assistant_enabled
      && item.display_mode === 'embedded'
      && (item.modules || []).some((module) => module.module_key === moduleKey)
    ));
  assert.ok(application, `找不到带 ${moduleKey} 模块且已启用业务助手的内嵌应用`);
  assert.equal(application.assistant_enabled, true, '目标应用未启用业务助手');
  assert.equal(application.display_mode, 'embedded', '目标应用不是内嵌模式');
  const module = (application.modules || []).find((item) => item.module_key === moduleKey);
  assert.ok(module, `目标应用没有 ${moduleKey} 模块`);

  const nav = page.locator('aside').first();
  await nav.locator('button').filter({ hasText: application.name }).first().click();
  await page.waitForFunction(
    (expectedId) => {
      const params = new URL(location.href).searchParams;
      return params.get('view') === 'application' && params.get('app') === expectedId;
    },
    application.id,
    { timeout: 30_000 },
  );
  await page.goto(
    new URL(`/${orgSlug}/terminal?view=application&app=${encodeURIComponent(application.id)}&module=${encodeURIComponent(moduleKey)}`, baseUrl).href,
    { waitUntil: 'domcontentloaded', timeout: 60_000 },
  );
  return { application, module };
}

async function verifyEmbeddedApplication(page) {
  await page.getByRole('button', { name: /灼见助手/ }).waitFor({ timeout: 60_000 });
  const iframe = page.locator('iframe.enterprise-app-view__frame--active');
  await iframe.waitFor({ state: 'visible', timeout: 60_000 });
  const handle = await iframe.elementHandle();
  const frame = await handle?.contentFrame();
  assert.ok(frame, '业务应用 iframe 没有浏览上下文');
  await frame.waitForURL((url) => (
    ['http:', 'https:'].includes(url.protocol)
    && url.href !== 'about:blank'
    && !url.pathname.startsWith('/api/integration/sso')
  ), { timeout: 90_000 });
  const body = frame.locator('body');
  await body.waitFor({ state: 'visible', timeout: 30_000 });
  const text = (await body.innerText()).replace(/\s+/g, ' ').trim();
  assert.ok(text.length >= 20, '业务应用 iframe 没有渲染真实内容');
  assert.doesNotMatch(text, /意外终止了连接|ERR_|无法访问此网站|This site can.t be reached/i);
}

function zipEntries(buffer) {
  const entries = [];
  for (let offset = 0; offset + 46 <= buffer.length;) {
    if (buffer.readUInt32LE(offset) !== 0x02014b50) {
      offset += 1;
      continue;
    }
    const nameLength = buffer.readUInt16LE(offset + 28);
    const extraLength = buffer.readUInt16LE(offset + 30);
    const commentLength = buffer.readUInt16LE(offset + 32);
    const nameStart = offset + 46;
    const nameEnd = nameStart + nameLength;
    if (nameEnd > buffer.length) break;
    entries.push(buffer.subarray(nameStart, nameEnd).toString('utf8'));
    offset = nameEnd + extraLength + commentLength;
  }
  return entries;
}

async function listBusinessTaskIds(page, applicationId) {
  const tasks = await userJson(
    page,
    `/api/v1/terminal/tasks?application_id=${encodeURIComponent(applicationId)}&limit=100`,
  );
  return new Set(tasks.map((task) => String(task.id)));
}

async function findRunArtifact(page, applicationId, baselineTaskIds, marker, expectedName = '') {
  return page.evaluate(async ({ appId, beforeIds, runMarkerValue, artifactName }) => {
    const token = sessionStorage.getItem('ai_infra_user_token') || '';
    const headers = { Authorization: `Bearer ${token}` };
    const tasksResponse = await fetch(
      `/api/v1/terminal/tasks?application_id=${encodeURIComponent(appId)}&limit=100`,
      { headers },
    );
    if (!tasksResponse.ok) return { error: `任务列表失败（HTTP ${tasksResponse.status}）` };
    const tasks = await tasksResponse.json();
    const candidates = tasks.filter((task) => !beforeIds.includes(String(task.id)));
    for (const candidate of candidates) {
      const taskResponse = await fetch(`/api/v1/terminal/tasks/${candidate.id}?application_id=${encodeURIComponent(appId)}`, { headers });
      if (!taskResponse.ok) continue;
      const task = await taskResponse.json();
      const messages = Array.isArray(task.messages) ? task.messages : [];
      if (!messages.some((item) => item.role === 'user' && String(item.content).includes(runMarkerValue))) continue;
      const artifacts = messages
        .filter((item) => item.role === 'assistant')
        .flatMap((item) => Array.isArray(item.metadata?.artifacts) ? item.metadata.artifacts : []);
      const rawArtifact = artifacts.find((item) => (
        (item.name || item.original_filename) === artifactName
      )) || artifacts.at(-1);
      if (!rawArtifact) return { error: '业务助手消息没有可信 Artifact', taskId: String(task.id) };
      const fileId = rawArtifact.fileId || rawArtifact.file_id;
      const versionId = rawArtifact.versionId || rawArtifact.version_id;
      if (!fileId || !versionId) return { error: 'Artifact 缺少文件或版本标识', taskId: String(task.id) };
      const fileResponse = await fetch(`/api/v1/terminal/files/${fileId}`, { headers });
      if (!fileResponse.ok) return { error: `工作空间文件读取失败（HTTP ${fileResponse.status}）`, taskId: String(task.id) };
      const file = await fileResponse.json();
      const previewUrl = `/api/v1/terminal/files/${fileId}/spreadsheet-preview?version_id=${encodeURIComponent(versionId)}`;
      let previewResponse = await fetch(previewUrl, { method: 'POST', headers });
      let preview = await previewResponse.json().catch(() => ({}));
      for (let attempt = 0; attempt < 60 && ['queued', 'processing'].includes(preview.status); attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        previewResponse = await fetch(previewUrl, { headers });
        preview = await previewResponse.json().catch(() => ({}));
      }
      return {
        taskId: String(task.id),
        runStatus: task.run_status,
        artifact: {
          fileId: String(fileId),
          versionId: String(versionId),
          checksumSha256: rawArtifact.checksumSha256 || rawArtifact.checksum_sha256 || '',
        },
        currentVersionId: file.current_version_id ? String(file.current_version_id) : null,
        previewStatus: preview.status || null,
        previewSheets: Array.isArray(preview.sheets) ? preview.sheets.length : 0,
      };
    }
    return { error: '未找到本轮独立业务助手对话' };
  }, {
    appId: applicationId,
    beforeIds: [...baselineTaskIds],
    runMarkerValue: marker,
    artifactName: expectedName,
  });
}

async function ensureAntSelectValue(page, combobox, failureMessage) {
  const selectedText = async () => combobox.evaluate((element) => (
    element.closest('.ant-select')?.querySelector('.ant-select-selection-item')?.textContent || ''
  ).trim());
  if (await selectedText()) return;
  await combobox.click();
  const firstOption = page.locator(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option',
  ).first();
  await firstOption.waitFor({ state: 'visible', timeout: 15_000 });
  await firstOption.click();
  assert.ok(await selectedText(), failureMessage);
}

async function adminJson(page, url, options = {}) {
  const result = await page.evaluate(async ({ requestUrl, requestOptions }) => {
    const method = String(requestOptions.method || 'GET').toUpperCase();
    const headers = new Headers(requestOptions.headers || {});
    if (requestOptions.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const csrfCookieNames = new Set(['__Host-ai-infra-admin-csrf', 'ai_infra_admin_csrf']);
      const cookieToken = document.cookie.split(';').map((part) => part.trim()).reduce((token, part) => {
        const separator = part.indexOf('=');
        if (separator <= 0) return token;
        const name = part.slice(0, separator);
        return csrfCookieNames.has(name) ? decodeURIComponent(part.slice(separator + 1)) : token;
      }, '');
      if (cookieToken) {
        headers.set('X-CSRF-Token', cookieToken);
      } else {
        const csrfResponse = await fetch('/api/v1/auth/csrf', { credentials: 'include' });
        const csrfBody = await csrfResponse.json().catch(() => ({}));
        if (!csrfResponse.ok || typeof csrfBody.csrf_token !== 'string') {
          return { ok: false, status: csrfResponse.status, body: csrfBody };
        }
        headers.set('X-CSRF-Token', csrfBody.csrf_token);
      }
    }
    const response = await fetch(requestUrl, {
      ...requestOptions,
      method,
      headers,
      credentials: 'include',
    });
    const body = response.status === 204 ? null : await response.json().catch(() => null);
    return { ok: response.ok, status: response.status, body };
  }, { requestUrl: url, requestOptions: options });
  assert.equal(result.ok, true, `管理员接口 ${safePath(url)} 失败（HTTP ${result.status}）`);
  return result.body;
}

async function grantModelForE2E(page, modelAlias) {
  if (!modelAlias) return null;
  const organizations = await adminJson(page, '/api/v1/organizations');
  const organization = organizations.find((item) => item.slug === orgSlug);
  assert.ok(organization, '管理员端找不到目标企业，无法准备 E2E 模型权限');
  const keys = await adminJson(page, `/api/v1/organizations/${organization.id}/api-keys`);
  const key = keys.find((item) => (
    item.scope_type === 'organization'
    && item.is_active
    && !item.revoked_at
    && item.key_name === 'Alphabet 总密钥'
  )) || keys.find((item) => item.scope_type === 'organization' && item.is_active && !item.revoked_at);
  assert.ok(key, '目标企业没有可临时扩展模型范围的组织级 API Key');
  const originalModels = Array.isArray(key.allowed_models) ? [...key.allowed_models] : [];
  if (originalModels.length === 1 && originalModels[0] === modelAlias) return null;
  await adminJson(page, `/api/v1/api-keys/${key.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ allowed_models: [modelAlias] }),
  });
  return { keyId: String(key.id), originalModels };
}

async function restoreModelGrant(page, state) {
  if (!state) return;
  await adminJson(page, `/api/v1/api-keys/${state.keyId}`, {
    method: 'PATCH',
    body: JSON.stringify({ allowed_models: state.originalModels }),
  });
}

async function selectAntOption(page, combobox, optionText, failureMessage) {
  const selectedText = async () => combobox.evaluate((element) => (
    element.closest('.ant-select')?.querySelector('.ant-select-selection-item')?.textContent || ''
  ).trim());
  if (await selectedText() === optionText) return;
  const selectState = await combobox.evaluate((element) => ({
    selected: (element.closest('.ant-select')?.querySelector('.ant-select-selection-item')?.textContent || '').trim(),
    className: element.closest('.ant-select')?.className || '',
    disabled: element.hasAttribute('disabled'),
    expanded: element.getAttribute('aria-expanded'),
  }));
  assert.equal(
    selectState.disabled || selectState.className.includes('ant-select-disabled'),
    false,
    `${failureMessage}；模型选择器当前被禁用（当前值：${selectState.selected || '空'}）`,
  );
  // The searchable input itself can have a zero-width box. Click Ant Select's
  // visible selector node, while resolving it from the current input so drawer
  // polling cannot leave us holding a detached element.
  const selector = combobox.locator(
    'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " ant-select-selector ")][1]',
  );
  await selector.waitFor({ state: 'visible', timeout: 15_000 });
  await selector.scrollIntoViewIfNeeded();
  await selector.click();
  const options = page.locator(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option',
  );
  await options.first().waitFor({ state: 'visible', timeout: 15_000 });
  const option = options.filter({ hasText: exactTextPattern(optionText) }).first();
  if (!await option.count()) {
    const available = (await options.allTextContents()).map((item) => item.trim()).filter(Boolean);
    throw new Error(`${failureMessage}；界面可选项：${available.join('、') || '无'}`);
  }
  await option.click();
  assert.equal(await selectedText(), optionText, failureMessage);
}

async function generateAndVerifyArtifact(page, applicationId, cleanupState) {
  const baselineTaskIds = await listBusinessTaskIds(page, applicationId);
  Object.assign(cleanupState, {
    applicationId,
    baselineTaskIds: [...baselineTaskIds],
    runMarker,
  });
  const assistantButton = page.getByRole('button', { name: /灼见助手/ });
  await assistantButton.click();
  const drawer = page.getByRole('dialog');
  await drawer.getByText(/已连接当前模块：/).waitFor({ timeout: 30_000 });
  const modelSelect = drawer.getByRole('combobox', { name: '选择灼见助手模型' });
  const workspaceSelect = drawer.getByRole('combobox', { name: '选择灼见助手文件保存位置' });
  await modelSelect.waitFor({ timeout: 30_000 });
  await workspaceSelect.waitFor({ timeout: 30_000 });
  if (modelAliasOverride) {
    await selectAntOption(
      page,
      modelSelect,
      modelAliasOverride,
      `业务小助手无法选择指定模型：${modelAliasOverride}`,
    );
  } else {
    await ensureAntSelectValue(page, modelSelect, '业务小助手没有可用模型');
  }
  await ensureAntSelectValue(page, workspaceSelect, '业务小助手没有可写工作空间');

  const newConversation = drawer.getByRole('button', { name: '新建对话' });
  await newConversation.click();
  await page.waitForFunction(() => {
    const button = document.querySelector('button[aria-label="新建对话"]');
    return button && !button.hasAttribute('disabled') && !button.classList.contains('ant-btn-loading');
  }, undefined, { timeout: 30_000 });

  const deliveredSections = drawer.locator('section[aria-label="本轮交付文件"]');
  const baselineArtifactCount = await deliveredSections.count();
  const formatRequest = process.env.E2E_EXPLICIT_XLSX === '1' ? 'Excel（.xlsx）' : 'Excel';
  const prompt = `${runMarker}：根据当前业务数据生成一份 ${formatRequest}，并把真实文件保存到我的个人工作空间。`;
  await drawer.getByPlaceholder('描述你要查询或执行的业务任务…').fill(prompt);
  await drawer.getByRole('button', { name: /在当前页面执行/ }).click();

  const deadline = Date.now() + artifactTimeoutMs;
  while (
    await deliveredSections.count() <= baselineArtifactCount
    || await drawer.getByRole('button', { name: /在当前页面执行/ }).evaluate(
      (element) => element.classList.contains('ant-btn-loading'),
    )
  ) {
    if (Date.now() >= deadline) throw new Error('业务助手在限定时间内没有交付文件卡片');
    const drawerText = await drawer.innerText();
    if (drawerText.includes('执行未完成，请查看下方原因')) {
      throw new Error('业务助手明确报告本轮执行失败');
    }
    await page.waitForTimeout(1_000);
  }

  const delivered = deliveredSections.nth(baselineArtifactCount);
  const downloadButton = delivered.getByRole('button', { name: /下载/ }).last();
  const downloadPromise = page.waitForEvent('download');
  await downloadButton.click();
  const download = await downloadPromise;
  const suggestedName = download.suggestedFilename();
  const localPath = path.join(outputDir, path.basename(suggestedName));
  await download.saveAs(localPath);
  const bytes = fs.readFileSync(localPath);
  console.log('E2E 下载产物格式', JSON.stringify({ extension: path.extname(suggestedName).toLowerCase(), sizeBytes: bytes.length }));
  assert.match(suggestedName.toLowerCase(), /\.xlsx$/, '业务助手交付物不是 XLSX');
  assert.ok(bytes.length > 100 && bytes.readUInt16LE(0) === 0x4b50, '下载文件不是有效 ZIP 容器');
  const entries = new Set(zipEntries(bytes));
  assert.ok(entries.has('[Content_Types].xml'), 'XLSX 缺少 OOXML Content Types');
  assert.ok(entries.has('xl/workbook.xml'), 'XLSX 缺少 workbook.xml');

  const verified = await findRunArtifact(
    page,
    applicationId,
    baselineTaskIds,
    runMarker,
    suggestedName,
  );
  assert.equal(verified.error, undefined, verified.error || 'Artifact 校验失败');
  assert.notEqual(verified.runStatus, 'error', '业务助手 Task 最终状态为 error');
  assert.equal(verified.currentVersionId, verified.artifact.versionId, 'Artifact 版本不是工作空间当前版本');
  assert.match(verified.artifact.checksumSha256, /^[a-f0-9]{64}$/, 'Artifact 缺少有效 SHA-256');
  assert.equal(verified.previewStatus, 'ready', 'Excel 预览没有就绪');
  assert.ok(verified.previewSheets >= 1, 'Excel 预览没有工作表');
  Object.assign(cleanupState, { taskId: verified.taskId, artifact: verified.artifact });
  return cleanupState;
}

async function cleanupBusinessRun(page, state) {
  if (!state) return { tasksDeleted: 0, filesTrashed: 0, failures: [] };
  return page.evaluate(async ({ taskId, artifact, applicationId, baselineTaskIds, runMarkerValue }) => {
    const token = sessionStorage.getItem('ai_infra_user_token') || '';
    const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
    const result = { tasksDeleted: 0, filesTrashed: 0, failures: [] };
    let resolvedTaskId = taskId || null;
    let resolvedArtifact = artifact || null;
    if (!resolvedTaskId && applicationId && runMarkerValue) {
      const tasksResponse = await fetch(
        `/api/v1/terminal/tasks?application_id=${encodeURIComponent(applicationId)}&limit=100`,
        { headers },
      );
      if (tasksResponse.ok) {
        const tasks = await tasksResponse.json();
        const candidates = tasks.filter((task) => !(baselineTaskIds || []).includes(String(task.id)));
        for (const candidate of candidates) {
          const taskResponse = await fetch(
            `/api/v1/terminal/tasks/${candidate.id}?application_id=${encodeURIComponent(applicationId)}`,
            { headers },
          );
          if (!taskResponse.ok) continue;
          const task = await taskResponse.json();
          const messages = Array.isArray(task.messages) ? task.messages : [];
          if (!messages.some((item) => item.role === 'user' && String(item.content).includes(runMarkerValue))) continue;
          resolvedTaskId = String(task.id);
          const artifacts = messages
            .filter((item) => item.role === 'assistant')
            .flatMap((item) => Array.isArray(item.metadata?.artifacts) ? item.metadata.artifacts : []);
          const rawArtifact = artifacts.at(-1);
          if (rawArtifact) {
            const fileId = rawArtifact.fileId || rawArtifact.file_id;
            const versionId = rawArtifact.versionId || rawArtifact.version_id;
            if (fileId) resolvedArtifact = { fileId: String(fileId), versionId: versionId ? String(versionId) : null };
          }
          break;
        }
      } else {
        result.failures.push(`测试对话发现失败（HTTP ${tasksResponse.status}）`);
      }
    }
    if (resolvedArtifact?.fileId) {
      const fileResponse = await fetch(`/api/v1/terminal/files/${resolvedArtifact.fileId}`, { headers });
      if (fileResponse.ok) {
        const file = await fileResponse.json();
        const deleteResponse = await fetch(`/api/v1/terminal/files/${resolvedArtifact.fileId}`, {
          method: 'DELETE',
          headers,
          body: JSON.stringify({
            base_version_id: file.current_version_id,
            idempotency_key: `staging-core-cleanup-${crypto.randomUUID()}`,
          }),
        });
        if (deleteResponse.ok) result.filesTrashed += 1;
        else result.failures.push(`测试文件清理失败（HTTP ${deleteResponse.status}）`);
      } else {
        result.failures.push(`测试文件读取失败（HTTP ${fileResponse.status}）`);
      }
    }
    if (resolvedTaskId) {
      const deleteResponse = await fetch(`/api/v1/terminal/tasks/${resolvedTaskId}`, { method: 'DELETE', headers });
      if (deleteResponse.ok) result.tasksDeleted += 1;
      else result.failures.push(`测试对话清理失败（HTTP ${deleteResponse.status}）`);
    }
    return result;
  }, {
    taskId: state.taskId,
    artifact: state.artifact,
    applicationId: state.applicationId,
    baselineTaskIds: state.baselineTaskIds,
    runMarkerValue: state.runMarker,
  });
}

async function verifySharedTaskViews(page, application, state) {
  const before = await listBusinessTaskIds(page, application.id);
  assert.equal(new URL(page.url()).searchParams.get('conversation'), state.taskId,
    '新建侧栏任务未写入地址，刷新将丢失当前会话');
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.getByRole('button', { name: /灼见助手/ }).waitFor({ timeout: 30_000 });
  await page.getByRole('button', { name: /灼见助手/ }).click();
  const reloadedDrawer = page.getByRole('dialog');
  await reloadedDrawer.getByText(runMarker, { exact: false }).first().waitFor({ timeout: 30_000 });
  await reloadedDrawer.locator('section[aria-label="本轮交付文件"]').first().waitFor({ timeout: 30_000 });
  assert.equal(new URL(page.url()).searchParams.get('conversation'), state.taskId);
  await page.goto(new URL(`/${orgSlug}/terminal/tasks/${state.taskId}`, baseUrl).href, {
    waitUntil: 'domcontentloaded', timeout: 60_000,
  });
  const main = page.locator('main.terminal-shell__main');
  await main.getByText(runMarker, { exact: false }).first().waitFor({ timeout: 30_000 });
  await main.locator('section[aria-label="本轮交付文件"]').first().waitFor({ timeout: 30_000 });
  assert.equal(new URL(page.url()).pathname, `/${orgSlug}/terminal/tasks/${state.taskId}`);
  const followUp = `${runMarker}-续问：刚才生成的文件是什么格式？只回答格式，不要创建或修改文件。`;
  const composer = main.locator('[contenteditable="true"][data-placeholder^="追加消息"]');
  await composer.fill(followUp);
  await composer.press('Enter');
  const deadline = Date.now() + artifactTimeoutMs;
  let continued = false;
  while (Date.now() < deadline) {
    const task = await userJson(page, `/api/v1/terminal/tasks/${state.taskId}`);
    const index = task.messages.findIndex((item) => item.role === 'user' && item.content === followUp);
    const reply = index < 0 ? null : task.messages.slice(index + 1).find((item) => item.role === 'assistant');
    if (reply && !['queued', 'running'].includes(task.run_status)) {
      assert.notEqual(task.run_status, 'error', '总入口续问执行失败');
      assert.match(reply.content, /xlsx|excel/i, '总入口续问未识别刚才交付的文件格式');
      continued = true;
      break;
    }
    await page.waitForTimeout(1_000);
  }
  assert.ok(continued, '总入口续问没有在原任务完成');
  await page.locator('aside').first().locator('button').filter({ hasText: application.name }).first().click();
  await page.getByRole('button', { name: /灼见助手/ }).waitFor({ timeout: 30_000 });
  await page.getByRole('button', { name: /灼见助手/ }).click();
  const drawer = page.getByRole('dialog');
  await drawer.getByText(runMarker, { exact: false }).first().waitFor({ timeout: 30_000 });
  await drawer.getByText(followUp, { exact: true }).waitFor({ timeout: 30_000 });
  await drawer.locator('section[aria-label="本轮交付文件"]').first().waitFor({ timeout: 30_000 });
  const after = await listBusinessTaskIds(page, application.id);
  assert.deepEqual([...after].sort(), [...before].sort(), '切换助手视图意外创建了任务');
  const restored = await findRunArtifact(page, application.id, new Set(state.baselineTaskIds), runMarker);
  assert.equal(restored.taskId, state.taskId, '切换视图后任务 ID 发生变化');
  assert.deepEqual(restored.artifact, state.artifact, '切换视图后文件版本引用发生变化');
}

async function logoutFromUi(page, { endpoint, expectedPath, roleLabel }) {
  const openDrawer = page.locator('.ant-drawer-open').last();
  if (await openDrawer.count()) {
    const closeButton = openDrawer.locator('.ant-drawer-close');
    if (await closeButton.count()) await closeButton.click();
    else await page.keyboard.press('Escape');
    await openDrawer.waitFor({ state: 'hidden', timeout: 30_000 });
  }
  console.log(`E2E ${roleLabel}真实退出登录：开始`);
  const logoutButton = page.locator(
    'button[aria-label="退出登录"]:visible, button:has-text("退出登录"):visible',
  ).last();
  if (!await logoutButton.count()) {
    const avatar = page.locator('aside:visible .ant-avatar:visible').last();
    await avatar.waitFor({ state: 'visible', timeout: 30_000 });
    await avatar.click();
  }
  await logoutButton.waitFor({ state: 'visible', timeout: 15_000 });
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => (
      candidate.request().method() === 'POST'
      && new URL(candidate.url()).pathname === endpoint
    ), { timeout: 30_000 }),
    logoutButton.click(),
  ]);
  assert.equal(response.status(), 204, `${roleLabel}退出登录应返回 204，实际为 ${response.status()}`);
  await page.waitForURL((url) => url.pathname === expectedPath, { timeout: 30_000 });
  console.log(`E2E ${roleLabel}真实退出登录：通过`);
}

const browser = await chromium.launch({
  headless: process.env.E2E_HEADLESS !== '0',
  executablePath: browserExecutable || undefined,
  proxy: proxyServer ? { server: proxyServer } : undefined,
  args: ['--disable-quic', '--disable-features=UseDnsHttpsSvcbAlpn'],
});
const desktopViewport = { width: 1920, height: 1080 };
const adminContext = await browser.newContext({ viewport: desktopViewport });
const employeeContext = await browser.newContext({ acceptDownloads: true, viewport: desktopViewport });
// Optional pre-deployment frontend verification. API, login, model and storage
// requests stay live; only this browser's static application assets are local.
if (process.env.E2E_LOCAL_FRONTEND === '1') {
  const distRoot = fs.realpathSync(path.resolve('dist'));
  assert.ok(fs.existsSync(path.join(distRoot, 'index.html')), '先构建本地前端');
  for (const context of [adminContext, employeeContext]) {
    await context.route(`${baseUrl.origin}/**`, async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (request.method() !== 'GET' || /^\/(api|v1)(\/|$)/.test(pathname)) return route.continue();
      const candidate = path.resolve(distRoot, `.${decodeURIComponent(pathname)}`);
      if (candidate !== distRoot && !candidate.startsWith(`${distRoot}${path.sep}`)) return route.abort();
      const file = fs.existsSync(candidate) && fs.statSync(candidate).isFile()
        ? fs.realpathSync(candidate)
        : request.isNavigationRequest() ? path.join(distRoot, 'index.html') : null;
      if (!file) return route.continue();
      if (!file.startsWith(`${distRoot}${path.sep}`)) return route.abort();
      return route.fulfill({ path: file });
    });
  }
  console.log('E2E 模式：本地构建前端＋真实 staging 接口（非已部署前端验收）');
}
const adminPage = await adminContext.newPage();
const employeePage = await employeeContext.newPage();
const viewTransitions = [];
employeePage.on('framenavigated', (frame) => {
  if (frame !== employeePage.mainFrame()) return;
  const url = new URL(frame.url());
  viewTransitions.push({ path: url.pathname, view: url.searchParams.get('view'), hasConversation: url.searchParams.has('conversation') });
});
const adminDiagnostics = diagnosticsFor(adminPage);
const employeeDiagnostics = diagnosticsFor(employeePage);
let artifactState = {};
let cleanupResult = null;
let modelGrantState = null;

try {
  console.log('E2E 管理员登录与中文错误提示：开始');
  await loginAdmin(adminPage, adminDiagnostics);
  console.log('E2E 管理员保留导航：开始');
  await traverseAdminNavigation(adminPage);
  const accessFromAdmin = await adminEffectiveAccess(adminPage);
  modelGrantState = await grantModelForE2E(adminPage, modelAliasOverride);
  adminDiagnostics.assertClean('管理员端');
  console.log(`E2E 管理员保留导航：通过（可见 ${ADMIN_NAVIGATION.length}，隐藏直达 ${ADMIN_DIRECT_ROUTES.length}）`);

  console.log('E2E 员工登录与中文错误提示：开始');
  await loginEmployee(employeePage, employeeDiagnostics);
  if (modelAliasOverride) {
    const models = await userJson(employeePage, '/api/v1/terminal/models');
    assert.ok(
      Array.isArray(models.models) && models.models.includes(modelAliasOverride),
      `员工端未获得指定 E2E 模型：${modelAliasOverride}`,
    );
  }
  console.log('E2E 员工核心导航：开始');
  await traverseEmployeeNavigation(employeePage);
  const accessFromEmployee = await userJson(employeePage, '/api/v1/terminal/effective-access');
  assert.deepEqual(
    normalizeEffectiveAccess(accessFromEmployee),
    normalizeEffectiveAccess(accessFromAdmin),
    '管理员预览权限与员工实时有效权限不一致',
  );
  console.log(`E2E 管理员—员工只读权限闭环：通过（工作空间 ${accessFromEmployee.workspaces.length}）`);

  console.log('E2E 企业应用 iframe 与 Bridge：开始');
  const { application } = await selectBusinessApplication(employeePage);
  await verifyEmbeddedApplication(employeePage);
  console.log('E2E 企业应用 iframe 与 Bridge：通过');

  console.log('E2E 业务助手 Excel Artifact：开始');
  artifactState = await generateAndVerifyArtifact(employeePage, application.id, artifactState);
  console.log('E2E 业务助手 Excel Artifact：通过');
  console.log('E2E 同一任务总入口与页面侧栏：开始');
  await verifySharedTaskViews(employeePage, application, artifactState);
  console.log('E2E 同一任务总入口与页面侧栏：通过');
  cleanupResult = await cleanupBusinessRun(employeePage, artifactState);
  artifactState = null;
  assert.equal(cleanupResult.failures.length, 0, cleanupResult.failures.join('；'));
  employeeDiagnostics.assertClean('员工端');
  console.log(`E2E 测试记录清理：通过（对话 ${cleanupResult.tasksDeleted}，文件移入回收站 ${cleanupResult.filesTrashed}）`);
  await restoreModelGrant(adminPage, modelGrantState);
  modelGrantState = null;
  await logoutFromUi(employeePage, {
    endpoint: '/api/v1/users/logout',
    expectedPath: `/${orgSlug}/terminal/login`,
    roleLabel: '员工',
  });
  await logoutFromUi(adminPage, {
    endpoint: '/api/v1/auth/logout',
    expectedPath: '/login',
    roleLabel: '管理员',
  });
  console.log('E2E 双端退出登录与会话撤销：通过');
  console.log('E2E PASS：管理员与员工 staging 核心回归全部通过');
} catch (error) {
  console.log('E2E failure location', JSON.stringify({
    path: safePath(employeePage.url()),
    dialogs: await employeePage.getByRole('dialog').count().catch(() => -1),
    artifactSections: await employeePage.locator('section[aria-label="本轮交付文件"]').count().catch(() => -1),
    transitions: viewTransitions.slice(-12),
    diagnostics: employeeDiagnostics.snapshot(),
    viewStatus: await employeePage.evaluate(() => {
      const text = document.querySelector('main')?.textContent || '';
      return ['正在校验应用权限', '应用入口不可用', '应用加载失败', '应用未授权或已停用'].filter((label) => text.includes(label));
    }).catch(() => []),
  }));
  throw new Error(redact(error instanceof Error ? error.message : error));
} finally {
  if (artifactState) {
    cleanupResult = await cleanupBusinessRun(employeePage, artifactState).catch(() => null);
    console.log('E2E failure cleanup', JSON.stringify(cleanupResult));
  }
  if (modelGrantState) {
    await restoreModelGrant(adminPage, modelGrantState).catch(() => null);
  }
  await employeeContext.close();
  await adminContext.close();
  await browser.close();
  const resolvedOutputDir = `${path.resolve(outputDir)}${path.sep}`.toLowerCase();
  if (resolvedOutputDir.startsWith(outputRoot)) {
    fs.rmSync(outputDir, { recursive: true, force: true });
  }
}
