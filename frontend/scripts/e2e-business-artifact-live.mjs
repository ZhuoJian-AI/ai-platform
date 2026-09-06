import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { chromium } from 'playwright';

const baseUrl = process.env.E2E_BASE_URL || 'https://ai-platform.staging.zhuojianai.com';
const orgSlug = process.env.E2E_ORG_SLUG;
const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const applicationId = process.env.E2E_APPLICATION_ID;
const moduleKey = process.env.E2E_MODULE_KEY || 'progress_dashboard';
const prompt = process.env.E2E_PROMPT || '根据当前业务数据生成一份 Excel';
const browserExecutable = process.env.E2E_BROWSER_EXECUTABLE;

if (!orgSlug || !username || !password || !applicationId) {
  throw new Error('请设置 E2E_ORG_SLUG、E2E_USERNAME、E2E_PASSWORD 和 E2E_APPLICATION_ID');
}

const browser = await chromium.launch({
  headless: true,
  executablePath: browserExecutable || undefined,
  args: ['--disable-quic', '--disable-features=UseDnsHttpsSvcbAlpn'],
});
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'business-artifact-e2e-'));
const context = await browser.newContext({ acceptDownloads: true });
const page = await context.newPage();
const consoleErrors = [];
const serverErrors = [];

page.on('console', (entry) => {
  if (entry.type() === 'error') consoleErrors.push(entry.text());
});
page.on('pageerror', (error) => consoleErrors.push(error.message));
page.on('response', (response) => {
  if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`);
});

try {
  console.log('E2E login:start');
  await page.goto(`${baseUrl}/${orgSlug}/terminal/login`, { waitUntil: 'commit', timeout: 60_000 });
  await page.getByRole('textbox', { name: '用户名' }).waitFor({ timeout: 120_000 });
  await page.getByRole('textbox', { name: '用户名' }).fill(username);
  await page.getByRole('textbox', { name: '密码' }).fill(password);
  const loginResponse = page.waitForResponse((response) => (
    response.request().method() === 'POST' && response.url().endsWith('/api/v1/users/login-by-slug')
  ));
  await page.locator('form#user-login button[type="submit"]').click();
  if (!(await loginResponse).ok()) throw new Error('真实员工账号登录失败');
  await page.waitForURL(new RegExp(`/${orgSlug}/terminal(?:\\?|$)`), { timeout: 30_000 });
  console.log('E2E login:ok');

  const applicationUrl = `${baseUrl}/${orgSlug}/terminal?view=application&app=${applicationId}&module=${moduleKey}`;
  await page.goto(applicationUrl, { waitUntil: 'commit', timeout: 60_000 });
  await page.getByRole('button', { name: /业务小助手/ }).waitFor({ timeout: 60_000 });
  console.log('E2E application:ok');
  await page.getByRole('button', { name: /业务小助手/ }).click();
  const drawer = page.getByRole('dialog');
  const modelSelect = drawer.getByRole('combobox', { name: '选择业务小助手模型' });
  const workspaceSelect = drawer.getByRole('combobox', { name: '选择业务小助手文件保存位置' });
  await modelSelect.waitFor({ timeout: 30_000 });
  await workspaceSelect.waitFor({ timeout: 30_000 });
  const modelText = await modelSelect.locator('xpath=../..').textContent();
  if (!modelText?.trim()) throw new Error('业务小助手没有可用模型');
  console.log('E2E assistant:ready');

  // Business-assistant tasks are intentionally persistent. Existing turns may
  // already contain artifact cards, so the E2E must wait for the card created
  // by this turn instead of accepting (or blocking on) stale history.
  await page.waitForTimeout(1_000);
  const progressRuns = drawer.getByLabel('业务小助手实时执行过程');
  const deliveredSections = drawer.locator('section[aria-label="本轮交付文件"]');
  const baselineProgressCount = await progressRuns.count();
  const baselineArtifactCount = await deliveredSections.count();

  await drawer.getByPlaceholder('描述你要查询或执行的业务任务…').fill(prompt);
  const submitButton = drawer.getByRole('button', { name: /在当前页面执行/ });
  await submitButton.click();
  const currentProgress = progressRuns.nth(baselineProgressCount);
  await currentProgress.waitFor({ timeout: 30_000 });
  console.log('E2E run:started');

  const completionDeadline = Date.now() + (12 * 60_000);
  let progressText = '';
  let lastProgressLog = 0;
  while (Date.now() < completionDeadline) {
    // A successful query invalidation replaces the transient running message
    // with the persisted Task history, which intentionally has no progress UI.
    if (await progressRuns.count() <= baselineProgressCount) {
      progressText = '';
      break;
    }
    progressText = (await currentProgress.textContent({ timeout: 2_000 })) || '';
    if (!progressText.includes('实时执行中')) break;
    if (Date.now() - lastProgressLog >= 30_000) {
      console.log(`E2E run:waiting ${progressText.replace(/\s+/g, ' ').slice(0, 240)}`);
      lastProgressLog = Date.now();
    }
    await page.waitForTimeout(2_000);
  }
  if (progressText.includes('实时执行中')) throw new Error('本轮业务助手执行超过 12 分钟');
  if (progressText.includes('执行未完成')) {
    throw new Error(`本轮业务助手执行失败：${progressText.slice(0, 300)}`);
  }
  const artifactDeadline = Date.now() + 30_000;
  while (await deliveredSections.count() <= baselineArtifactCount) {
    if (Date.now() >= artifactDeadline) throw new Error('本轮执行完成但没有新增文件卡片');
    await page.waitForTimeout(500);
  }
  const delivered = deliveredSections.nth(baselineArtifactCount);
  await delivered.waitFor({ timeout: 30_000 });
  const downloadButton = delivered.getByRole('button', { name: /下载/ }).last();
  const downloadPromise = page.waitForEvent('download');
  await downloadButton.click();
  const download = await downloadPromise;
  const suggestedName = download.suggestedFilename();
  const downloadPath = path.join(outputDir, suggestedName);
  await download.saveAs(downloadPath);
  const bytes = fs.readFileSync(downloadPath);
  if (!suggestedName.toLowerCase().endsWith('.xlsx')) throw new Error(`产物不是 XLSX：${suggestedName}`);
  if (bytes.length < 100 || !bytes.subarray(0, 2).equals(Buffer.from('PK'))) {
    throw new Error('下载文件不是有效的 OOXML ZIP 包');
  }
  console.log(`E2E artifact:downloaded ${suggestedName} ${bytes.length}`);

  const result = await page.evaluate(async ({ appId, expectedName }) => {
    const token = sessionStorage.getItem('ai_infra_user_token') || '';
    const headers = { Authorization: `Bearer ${token}` };
    const tasksResponse = await fetch('/api/v1/terminal/tasks', { headers });
    const tasks = await tasksResponse.json();
    const task = Array.isArray(tasks)
      ? tasks.find((item) => item?.config?.application_id === appId)
      : null;
    if (!task?.id) return { error: '未找到业务助手 Task' };
    const taskResponse = await fetch(`/api/v1/terminal/tasks/${task.id}`, { headers });
    const taskData = await taskResponse.json();
    const assistant = [...(taskData.messages || [])].reverse().find((item) => item.role === 'assistant');
    const artifacts = assistant?.metadata?.artifacts || [];
    const artifact = artifacts.find((item) => (
      (item.name || item.original_filename) === expectedName
    )) || artifacts.at(-1);
    if (!artifact?.fileId && !artifact?.file_id) return { error: '消息没有可信 Artifact' };
    const fileId = artifact.fileId || artifact.file_id;
    const versionId = artifact.versionId || artifact.version_id;
    const fileResponse = await fetch(`/api/v1/terminal/files/${fileId}`, { headers });
    const file = await fileResponse.json();
    return {
      taskId: task.id,
      runStatus: taskData.run_status,
      fileId,
      versionId,
      canonicalPath: artifact.canonicalPath || artifact.canonical_path,
      checksumSha256: artifact.checksumSha256 || artifact.checksum_sha256,
      workspaceId: artifact.workspaceId || artifact.workspace_id,
      fileStatus: fileResponse.status,
      currentVersionId: file.current_version_id,
      parseStatus: file.parse_status,
    };
  }, { appId: applicationId, expectedName: suggestedName });
  if (result.error) throw new Error(result.error);
  if (result.runStatus === 'error') throw new Error('Task 最终状态为 error');
  if (result.fileStatus !== 200) throw new Error(`工作空间文件实时鉴权失败：${result.fileStatus}`);
  if (!result.versionId || result.currentVersionId !== result.versionId) {
    throw new Error('Artifact 版本与工作空间当前版本不一致');
  }
  if (!/^[a-f0-9]{64}$/.test(result.checksumSha256 || '')) throw new Error('Artifact 缺少 SHA-256');
  console.log(`E2E workspace:verified ${JSON.stringify(result)}`);

  const fatalConsoleErrors = consoleErrors.filter((entry) => !entry.includes('favicon'));
  if (serverErrors.length) throw new Error(`出现服务端错误：${serverErrors.join('; ')}`);
  if (fatalConsoleErrors.length) throw new Error(`浏览器控制台错误：${fatalConsoleErrors.join('; ')}`);
  console.log('E2E PASS');
} finally {
  await browser.close();
}
