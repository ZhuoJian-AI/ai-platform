import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium, devices, firefox, webkit } from 'playwright';

const baseURL = process.env.RESPONSIVE_BASE_URL || 'http://127.0.0.1:4179';
const outputDir = new URL('../test-results/responsive/', import.meta.url);
const engines = process.env.RESPONSIVE_ENGINES
  ? process.env.RESPONSIVE_ENGINES.split(',').map((name) => name.trim())
  : ['chromium'];
const engineTypes = { chromium, firefox, webkit };
const chromeCandidates = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].filter(Boolean);
const viewports = [
  { name: 'phone-320', width: 320, height: 568 },
  { name: 'phone-390', width: 390, height: 844 },
  { name: 'phone-landscape', width: 844, height: 390 },
  { name: 'tablet-portrait', width: 768, height: 1024 },
  { name: 'tablet-landscape', width: 1024, height: 768 },
  { name: 'desktop-small', width: 1280, height: 720 },
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'desktop-wide', width: 1920, height: 1080 },
];

function isMobileViewport(viewport) {
  return viewport.width <= 768 || (viewport.width <= 900 && viewport.height <= 500);
}

const organization = {
  id: 'org-1', name: 'Alphabet 测试企业', slug: 'alphabet', description: '响应式验收',
  is_default: true, rate_limit_rpm: null, rate_limit_tpm: null,
  budget_cap_tokens: null, budget_cap_credits: null, budget_cap_usd: null,
};
const user = {
  id: 'user-1', username: 'zhangsan', display_name: '张三', role: 'employee',
  organization_id: 'org-1', organization_slug: 'alphabet', organization_name: 'Alphabet 测试企业',
  department_ids: ['dept-1'], department_id: 'dept-1',
};
const capabilities = { read: true, create: true, update: true, delete: true, manage: true, publish: true };
const workspaces = [
  { id: 'ws-org', organization_id: 'org-1', name: 'Alphabet 企业空间', slug: 'company', description: null, storage_backend: 'oss', root_path: '', config: {}, scope_type: 'organization', scope_id: 'org-1', is_active: true, capabilities, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'ws-dept', organization_id: 'org-1', name: '生产部', slug: 'production', description: null, storage_backend: 'oss', root_path: '', config: {}, scope_type: 'department', scope_id: 'dept-1', is_active: true, capabilities, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'ws-user', organization_id: 'org-1', name: '张三', slug: 'zhangsan', description: null, storage_backend: 'oss', root_path: '', config: {}, scope_type: 'user', scope_id: 'user-1', is_active: true, capabilities, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
];
const application = {
  id: 'app-1', name: '爱法贝生产协同', slug: 'garment-production-collaboration', description: '测试超长的企业生产协同应用名称',
  icon_url: null, display_mode: 'embedded', sort_order: 1, assistant_enabled: true,
  permissions: ['view', 'ai_query', 'export'], module_keys: ['progress'], modules: [{ module_key: 'progress', name: '生产进度看板与异常监测' }],
};

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: 'application/json; charset=utf-8', body: JSON.stringify(body) });
}

function screenshotPath(name) {
  return fileURLToPath(new URL(name, outputDir));
}

async function activate(page, locator, emulateTouch) {
  if (!emulateTouch) {
    await locator.click();
    return;
  }
  const box = await locator.boundingBox();
  assert.ok(box, '触摸目标必须在视口内可见');
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
}

async function installMocks(page) {
  await page.route('https://subsystem.test/**', (route) => route.fulfill({
    status: 200,
    contentType: 'text/html; charset=utf-8',
    body: '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>html,body{margin:0;max-width:100%;overflow-x:hidden;font-family:sans-serif}main{padding:16px}button{min-height:44px}</style><main><h1>生产进度看板</h1><button>刷新数据</button></main><script>setTimeout(()=>{parent.postMessage({type:"zhuojian:ready",version:1,launch_nonce:"responsive-test-nonce",application_slug:"garment-production-collaboration"},"*");parent.postMessage({type:"zhuojian:context",version:1,launch_nonce:"responsive-test-nonce",application_slug:"garment-production-collaboration",route:"/progress",module_key:"progress",module_name:"生产进度",page_key:"progress-dashboard",page_name:"生产进度看板",filters:{},selection:{},data_version:"1"},"*")},50)<\/script>',
  }));
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/v1/auth/me') return json(route, { id: 1, username: 'root', display_name: 'Root', role: 'platform_super_admin', is_active: true });
    if (path === '/api/v1/auth/csrf') return json(route, { csrf_token: 'test-csrf' });
    if (path === '/api/v1/organizations') return json(route, [organization]);
    if (path === '/api/v1/terminal/resources') return json(route, { workspaces, skills: [], rags: [], defaults: { workspace_id: 'ws-user', model_alias: 'test-model' } });
    if (path === '/api/v1/terminal/models') return json(route, { models: ['test-model'], capabilities: { 'test-model': { vision: false } }, vision_fallback_available: false, image_generation_available: false });
    if (path === '/api/v1/terminal/agents') return json(route, { agents: [] });
    if (path === '/api/v1/terminal/applications') return json(route, [application]);
    if (path === '/api/v1/terminal/applications/app-1/launch') return json(route, {
      application_id: 'app-1', application_slug: application.slug, url: 'https://subsystem.test/app', display_mode: 'embedded',
      permissions: application.permissions, module_keys: ['progress'], module_key: 'progress', modules: application.modules,
      page_keys: ['progress-dashboard'], launch_nonce: 'responsive-test-nonce', allowed_origin: 'https://subsystem.test',
    });
    if (path === '/api/v1/terminal/application-action-confirmations') return json(route, []);
    if (path === '/api/v1/terminal/workspace-files') return json(route, []);
    if (path === '/api/v1/terminal/memory' || path === '/api/v1/terminal/tasks') return json(route, []);
    if (/\/api\/v1\/terminal\/workspaces\/[^/]+\/folders$/.test(path)) return json(route, []);
    if (/\/api\/v1\/terminal\/workspaces\/[^/]+\/files$/.test(path)) return json(route, { items: [], total: 0, page: 1, page_size: 100 });
    if (path === '/api/v1/workspaces/file-capabilities') return json(route, { formats: [] });
    if (path === '/api/v1/terminal/effective-access') return json(route, {});
    return json(route, route.request().method() === 'GET' ? [] : {});
  });
}

async function seedEmployee(page) {
  await page.addInitScript((employee) => {
    sessionStorage.setItem('ai_infra_user_token', 'responsive-test-token');
    localStorage.setItem('ai_infra_user', JSON.stringify(employee));
  }, user);
}

async function assertNoRootOverflow(page, label) {
  const overflow = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    html: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  assert.ok(Math.max(overflow.html, overflow.body) <= overflow.viewport + 1, `${label} 根页面横向溢出：${JSON.stringify(overflow)}`);
}

async function assertPrimaryTouchTargets(page, label) {
  const undersized = await page.locator('.ant-btn-primary:visible').evaluateAll((buttons) => buttons
    .map((button) => {
      const box = button.getBoundingClientRect();
      return { label: button.getAttribute('aria-label') || button.textContent?.trim(), width: box.width, height: box.height };
    })
    .filter((button) => button.height < 44 || button.width < 24));
  assert.deepEqual(undersized, [], `${label} 主要触摸操作尺寸不足：${JSON.stringify(undersized)}`);
}

async function testAdmin(page, viewport, engine) {
  await page.goto(`${baseURL}/org/profile`);
  await page.locator('.admin-shell__main').waitFor({ state: 'visible' });
  await assertNoRootOverflow(page, `${engine}/${viewport.name}/admin`);
  const trigger = page.getByRole('button', { name: '打开管理导航' });
  if (isMobileViewport(viewport)) {
    const emulateTouch = engine !== 'firefox';
    await assert.doesNotReject(() => trigger.waitFor({ state: 'visible' }));
    await activate(page, trigger, emulateTouch);
    const nav = page.getByRole('dialog', { name: '管理导航' });
    await nav.waitFor({ state: 'visible' });
    await page.waitForFunction(() => {
      const element = document.querySelector('.admin-shell__sidebar--open');
      if (!(element instanceof HTMLElement)) return false;
      const box = element.getBoundingClientRect();
      return box.x >= -1 && box.right <= window.innerWidth + 1;
    });
    const box = await nav.boundingBox();
    assert.ok(box && box.x >= -1 && box.x + box.width <= viewport.width + 1, `管理导航必须完整位于手机视口内：${JSON.stringify(box)}`);
    assert.equal(await page.locator('.admin-shell__main').getAttribute('inert'), '', '手机导航打开后背景必须停止交互');
    try {
      await page.waitForFunction(() => {
        const element = document.querySelector('.admin-shell__sidebar--open');
        return element instanceof HTMLElement && element.contains(document.activeElement);
      }, null, { timeout: 2_000 });
    } catch (error) {
      const active = await page.evaluate(() => ({
          tag: document.activeElement?.tagName,
          label: document.activeElement?.getAttribute('aria-label'),
          className: document.activeElement?.getAttribute('class'),
      }));
      throw new Error(`管理导航打开后焦点必须进入抽屉，当前焦点：${JSON.stringify(active)}`, { cause: error });
    }
    await page.keyboard.press('Escape');
    await nav.waitFor({ state: 'hidden' });
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === '打开管理导航');
    assert.equal(await page.locator('.admin-shell__main').getAttribute('inert'), null, '关闭手机导航后背景必须恢复交互');
    await activate(page, trigger, emulateTouch);
    await nav.waitFor({ state: 'visible' });
    const urlBeforeBack = page.url();
    await page.evaluate(() => window.history.back());
    await nav.waitFor({ state: 'hidden' });
    assert.equal(page.url(), urlBeforeBack, '手机返回键关闭管理导航时不得离开当前页面');
    await assertPrimaryTouchTargets(page, `${engine}/${viewport.name}/admin`);
  } else {
    assert.equal(await trigger.isVisible(), false, '桌面不应显示手机导航按钮');
  }
  await page.screenshot({ path: screenshotPath(`${engine}-${viewport.name}-admin.png`), fullPage: false });
}

async function testWorkspace(page, viewport, engine) {
  await page.goto(`${baseURL}/alphabet/terminal?view=workspace`);
  await page.locator('.workspace-manager').waitFor({ state: 'visible' });
  await assertNoRootOverflow(page, `${engine}/${viewport.name}/workspace`);
  if (isMobileViewport(viewport)) {
    const emulateTouch = engine !== 'firefox';
    const trigger = page.getByRole('button', { name: '打开平台导航' });
    await activate(page, trigger, emulateTouch);
    const nav = page.getByRole('dialog', { name: '员工平台导航' });
    await nav.waitFor({ state: 'visible' });
    assert.equal(await page.locator('.terminal-shell__main').getAttribute('inert'), '', '员工导航打开后背景必须停止交互');
    await page.waitForFunction(() => {
      const element = document.querySelector('.terminal-shell__sidebar--open');
      return element instanceof HTMLElement && element.contains(document.activeElement);
    });
    await page.keyboard.press('Escape');
    await nav.waitFor({ state: 'hidden' });
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === '打开平台导航');
    assert.equal(await page.locator('.terminal-shell__main').getAttribute('inert'), null, '员工导航关闭后背景必须恢复交互');
    await activate(page, trigger, emulateTouch);
    await nav.waitFor({ state: 'visible' });
    const urlBeforeBack = page.url();
    await page.evaluate(() => window.history.back());
    await nav.waitFor({ state: 'hidden' });
    assert.equal(page.url(), urlBeforeBack, '手机返回键关闭员工导航时不得离开当前页面');
    const spaces = page.getByLabel('工作空间列表');
    await spaces.waitFor({ state: 'visible' });
    await activate(page, spaces.getByText('Alphabet 企业空间', { exact: true }), emulateTouch);
    try {
      await page.getByRole('button', { name: '返回工作空间列表' }).waitFor({ state: 'visible', timeout: 3_000 });
    } catch (error) {
      const diagnostic = await page.evaluate(() => ({
        url: window.location.href,
        bodyClass: document.body.className,
        managerClass: document.querySelector('.workspace-manager')?.getAttribute('class'),
        navClass: document.querySelector('.terminal-shell__sidebar')?.getAttribute('class'),
        elementAtCenter: document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2)?.outerHTML.slice(0, 300),
      }));
      throw new Error(`${engine}/${viewport.name} 选择工作空间后未进入文件区域：${JSON.stringify(diagnostic)}`, { cause: error });
    }
    await assertNoRootOverflow(page, `${engine}/${viewport.name}/workspace-files`);
    await assertPrimaryTouchTargets(page, `${engine}/${viewport.name}/workspace`);
  }
  await page.screenshot({ path: screenshotPath(`${engine}-${viewport.name}-workspace.png`), fullPage: false });
}

async function testApplication(page, viewport, engine) {
  await page.goto(`${baseURL}/alphabet/terminal?view=application&app=app-1&module=progress`);
  await page.getByRole('button', { name: '打开平台导航' }).waitFor();
  const applicationFrame = page.locator('iframe.enterprise-app-view__frame--active');
  await applicationFrame.evaluate((frame) => { frame.dataset.responsiveIdentity = 'preserve'; });
  try {
    await page.frameLocator('iframe.enterprise-app-view__frame--active').getByRole('heading', { name: '生产进度看板' }).waitFor();
  } catch (error) {
    const diagnostic = await page.evaluate(() => ({
      iframeSrc: document.querySelector('iframe.enterprise-app-view__frame--active')?.getAttribute('src'),
      iframeCount: document.querySelectorAll('iframe').length,
    }));
    diagnostic.frameUrls = page.frames().map((frame) => frame.url());
    diagnostic.frameHtml = await page.frames()[1]?.content().catch(() => 'unavailable');
    throw new Error(`内嵌子系统未真实呈现：${JSON.stringify(diagnostic)}`, { cause: error });
  }
  await assertNoRootOverflow(page, `${engine}/${viewport.name}/application`);
  if (isMobileViewport(viewport)) {
    const emulateTouch = engine !== 'firefox';
    const platformNavigation = page.getByRole('button', { name: '打开平台导航' });
    await activate(page, platformNavigation, emulateTouch);
    const terminalNavigation = page.locator('.terminal-app-nav-drawer .ant-drawer-content-wrapper');
    await terminalNavigation.waitFor({ state: 'visible' });
    const urlBeforeNavigationBack = page.url();
    await page.goBack({ waitUntil: 'commit' }).catch(() => null);
    await terminalNavigation.waitFor({ state: 'hidden' });
    assert.equal(page.url(), urlBeforeNavigationBack, '手机返回键关闭平台导航时不得离开当前应用');
    await page.getByRole('button', { name: '更多应用操作' }).waitFor({ state: 'visible' });
    await activate(page, page.locator('.enterprise-app-view__header .ant-btn-primary'), emulateTouch);
    const drawer = page.locator('.business-assistant-drawer .ant-drawer-content-wrapper');
    await drawer.waitFor({ state: 'visible' });
    await page.waitForFunction(() => {
      const element = document.querySelector('.business-assistant-drawer .ant-drawer-content-wrapper');
      if (!(element instanceof HTMLElement)) return false;
      const box = element.getBoundingClientRect();
      return Math.abs(box.x) <= 1 && Math.abs(box.width - window.innerWidth) <= 1;
    });
    const box = await drawer.boundingBox();
    assert.ok(box && Math.abs(box.x) <= 1 && Math.abs(box.width - viewport.width) <= 1, `手机助手必须全屏，实际 ${JSON.stringify(box)}`);
    assert.equal(await page.locator('iframe.enterprise-app-view__frame--active').getAttribute('inert'), '', '助手打开后底层 iframe 必须停止交互');
    const composer = page.getByPlaceholder('描述你要查询或执行的业务任务…');
    await composer.fill('旋转屏幕后必须保留的输入草稿');
    await composer.focus();
    const composerBox = await composer.boundingBox();
    assert.ok(composerBox && composerBox.y + composerBox.height <= page.viewportSize().height + 1, `手机输入框不得超出可视区域：${JSON.stringify(composerBox)}`);
    if (viewport.name === 'phone-390') {
      await page.setViewportSize({ width: 844, height: 390 });
      await page.waitForFunction(() => {
        const element = document.querySelector('.business-assistant-drawer .ant-drawer-content-wrapper');
        if (!(element instanceof HTMLElement)) return false;
        const box = element.getBoundingClientRect();
        return Math.abs(box.x) <= 1 && Math.abs(box.width - window.innerWidth) <= 1;
      });
      assert.equal(await composer.inputValue(), '旋转屏幕后必须保留的输入草稿', '手机旋转后业务助手输入草稿不得丢失');
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
    }
    await page.screenshot({ path: screenshotPath(`${engine}-${viewport.name}-assistant.png`), fullPage: false });
    const urlBeforeBack = page.url();
    await page.goBack({ waitUntil: 'commit' }).catch(() => null);
    await drawer.waitFor({ state: 'hidden' });
    assert.equal(page.url(), urlBeforeBack, '手机返回键关闭助手时不得离开当前业务页面');
    assert.equal(await page.locator('iframe.enterprise-app-view__frame--active').getAttribute('inert'), null, '助手关闭后底层 iframe 必须恢复交互');
    assert.equal(await page.locator('iframe.enterprise-app-view__frame--active').getAttribute('data-responsive-identity'), 'preserve', '开关手机浮层不得重建 iframe');
    await assertPrimaryTouchTargets(page, `${engine}/${viewport.name}/application`);
  }
  await page.screenshot({ path: screenshotPath(`${engine}-${viewport.name}-application.png`), fullPage: false });
}

let preview;
try {
  await mkdir(outputDir, { recursive: true });
  if (!process.env.RESPONSIVE_BASE_URL) {
    preview = spawn(process.execPath, ['node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '4179'], { stdio: 'ignore' });
    for (let attempt = 0; attempt < 60; attempt += 1) {
      try { if ((await fetch(baseURL)).ok) break; } catch { /* preview is starting */ }
      await new Promise((resolve) => setTimeout(resolve, 250));
      if (attempt === 59) throw new Error('前端预览服务启动超时');
    }
  }

  for (const engineName of engines) {
    const browserType = engineTypes[engineName];
    if (!browserType) throw new Error(`未知浏览器引擎：${engineName}`);
    const systemChrome = engineName === 'chromium' ? chromeCandidates.find((candidate) => existsSync(candidate)) : undefined;
    const browser = await browserType.launch({ headless: true, ...(systemChrome ? { executablePath: systemChrome } : {}) });
    try {
      for (const viewport of viewports) {
        const emulateHandset = isMobileViewport(viewport) && engineName !== 'firefox';
        const deviceName = engineName === 'webkit' ? 'iPhone 13' : 'Pixel 5';
        const { defaultBrowserType: _defaultBrowserType, ...device } = emulateHandset ? devices[deviceName] : {};
        const context = await browser.newContext({
          ...device,
          viewport: { width: viewport.width, height: viewport.height },
          screen: { width: viewport.width, height: viewport.height },
          ...(emulateHandset ? { isMobile: true, hasTouch: true } : {}),
        });
        const page = await context.newPage();
        await installMocks(page);
        await seedEmployee(page);
        await testAdmin(page, viewport, engineName);
        await testWorkspace(page, viewport, engineName);
        await testApplication(page, viewport, engineName);
        await context.close();
      }
    } finally {
      await browser.close();
    }
  }
  console.log(`RESPONSIVE_ACCEPTANCE_OK engines=${engines.join(',')} viewports=${viewports.length}`);
} finally {
  preview?.kill();
}
