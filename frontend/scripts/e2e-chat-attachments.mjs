import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173';
const orgSlug = process.env.E2E_ORG_SLUG;
const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const model = process.env.E2E_MODEL || 'gpt-4o-mini';
const mockLlmPort = Number(process.env.E2E_MOCK_LLM_PORT || 0);
const fixturePaths = (process.env.E2E_ATTACHMENT_FILES || '')
  .split(path.delimiter)
  .filter(Boolean)
  .map((value) => path.resolve(value));

if (!orgSlug || !username || !password || fixturePaths.length < 4) {
  throw new Error(
    'Set E2E_ORG_SLUG, E2E_USERNAME, E2E_PASSWORD and E2E_ATTACHMENT_FILES (at least four paths).',
  );
}

for (const fixturePath of fixturePaths) {
  if (!fs.existsSync(fixturePath)) throw new Error(`Fixture does not exist: ${fixturePath}`);
}

const oversizedPath = path.join(os.tmpdir(), `chat-attachment-over-5mb-${Date.now()}.bin`);
fs.writeFileSync(oversizedPath, Buffer.alloc(5 * 1024 * 1024 + 1, 1));

let mockPromptVerified = false;
const mockServer = mockLlmPort ? http.createServer((request, response) => {
  if (request.method !== 'POST' || !request.url?.endsWith('/v1/chat/completions')) {
    response.writeHead(404).end();
    return;
  }
  const chunks = [];
  request.on('data', (chunk) => chunks.push(chunk));
  request.on('end', () => {
    const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    const prompt = (payload.messages || []).map((item) => String(item.content || '')).join('\n');
    const required = [
      'chat-e2e.docx', '今日完成 120 件',
      'chat-e2e.xlsx', '螺丝',
      'chat-e2e.pptx', '本月增长 18%',
      'chat-e2e.pdf', 'Production report 42',
    ];
    mockPromptVerified = required.every((value) => prompt.includes(value));
    const content = [
      '四个附件已精确读取：',
      'chat-e2e.docx：生产日报，今日完成 120 件。',
      'chat-e2e.xlsx：库存表，螺丝库存 300。',
      'chat-e2e.pptx：销售月报，本月增长 18%。',
      'chat-e2e.pdf：Production report 42。',
    ].join('\n');
    response.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache',
    });
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-attachment-e2e', object: 'chat.completion.chunk',
      choices: [{ index: 0, delta: { role: 'assistant', content }, finish_reason: null }],
    })}\n\n`);
    response.write(`data: ${JSON.stringify({
      id: 'chatcmpl-attachment-e2e', object: 'chat.completion.chunk',
      choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
    })}\n\n`);
    response.end('data: [DONE]\n\n');
  });
}) : null;
if (mockServer) {
  await new Promise((resolve, reject) => {
    mockServer.once('error', reject);
    mockServer.listen(mockLlmPort, '0.0.0.0', resolve);
  });
}

const executablePath = process.env.E2E_BROWSER_EXECUTABLE;
const browser = await chromium.launch({ headless: true, executablePath: executablePath || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const consoleErrors = [];
const uploadResponses = [];
let activeUploadRequests = 0;
let maxConcurrentUploadRequests = 0;

const isUploadRequest = (request) => (
  request.method() === 'POST'
  && /\/api\/v1\/terminal\/workspaces\/[^/]+\/files\/upload$/.test(request.url())
);

page.on('console', (entry) => {
  if (entry.type() === 'error') consoleErrors.push(entry.text());
});
page.on('pageerror', (error) => consoleErrors.push(error.message));
page.on('request', (request) => {
  if (!isUploadRequest(request)) return;
  activeUploadRequests += 1;
  maxConcurrentUploadRequests = Math.max(maxConcurrentUploadRequests, activeUploadRequests);
});
page.on('requestfailed', (request) => {
  if (isUploadRequest(request)) activeUploadRequests = Math.max(0, activeUploadRequests - 1);
});
page.on('response', async (response) => {
  if (isUploadRequest(response.request())) {
    activeUploadRequests = Math.max(0, activeUploadRequests - 1);
    uploadResponses.push({ status: response.status(), body: await response.json().catch(() => null) });
  }
});

async function chooseFiles(paths) {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByText('上传附件', { exact: true }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(paths);
}

async function dropFiles(target, paths) {
  const payload = paths.map((filePath) => ({
    name: path.basename(filePath),
    mime: filePath.endsWith('.docx')
      ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      : filePath.endsWith('.xlsx')
        ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        : filePath.endsWith('.pptx')
          ? 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
          : 'application/pdf',
    base64: fs.readFileSync(filePath).toString('base64'),
  }));
  const dataTransfer = await page.evaluateHandle((files) => {
    const transfer = new DataTransfer();
    for (const item of files) {
      const bytes = Uint8Array.from(atob(item.base64), (char) => char.charCodeAt(0));
      transfer.items.add(new File([bytes], item.name, { type: item.mime }));
    }
    return transfer;
  }, payload);
  await target.dispatchEvent('dragenter', { dataTransfer });
  await target.dispatchEvent('dragover', { dataTransfer });
  await target.dispatchEvent('drop', { dataTransfer });
  await dataTransfer.dispose();
}

try {
  await page.goto(`${baseUrl}/${orgSlug}/terminal/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('input').first().fill(username);
  await page.locator('input[type="password"]').fill(password);
  const loginResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST' && response.url().endsWith('/api/v1/users/login-by-slug')
  ));
  await page.locator('form#user-login button[type="submit"]').click();
  const loginResponse = await loginResponsePromise;
  if (!loginResponse.ok()) {
    throw new Error(`Login failed: ${loginResponse.status()} ${await loginResponse.text()}`);
  }
  await page.waitForFunction((slug) => location.pathname === `/${slug}/terminal`, orgSlug);
  await page.getByText('上传附件', { exact: true }).waitFor();
  await page.waitForFunction(() => {
    const trigger = document.querySelector('.wb-cfg-trigger');
    return trigger && !trigger.textContent?.includes('工作空间 未选择');
  });

  const hiddenFileInput = page.locator('input[type="file"]').first();
  const composer = hiddenFileInput.locator('..');
  await chooseFiles(fixturePaths.slice(0, 4));
  await page.getByText('可以发送', { exact: true }).nth(3).waitFor({ timeout: 120_000 });
  await dropFiles(composer, fixturePaths.slice(0, 1));
  await page.getByText('可以发送', { exact: true }).nth(4).waitFor({ timeout: 120_000 });
  const duplicateCard = page.getByText(path.basename(fixturePaths[0]), { exact: true }).last().locator('../..');
  await duplicateCard.locator('.anticon-close').click();

  await chooseFiles([oversizedPath]);
  await page.getByText('文件超过 5MB 上限', { exact: true }).waitFor();
  const oversizedCard = page.getByText(path.basename(oversizedPath), { exact: true }).locator('../..');
  await oversizedCard.locator('.anticon-close').click();

  if (
    uploadResponses.length !== 5
    || uploadResponses.some((item) => item.status < 200 || item.status >= 300)
  ) {
    throw new Error(`Expected five successful uploads, got statuses ${uploadResponses.map((item) => item.status)}`);
  }
  const allUploadBodies = uploadResponses.map((item) => item.body);
  const duplicateName = path.basename(fixturePaths[0]);
  const removedUpload = allUploadBodies
    .filter((item) => item?.metadata?.name === duplicateName)
    .sort((left, right) => String(left.created_at).localeCompare(String(right.created_at)))
    .at(-1);
  const uploadBodies = allUploadBodies.filter((item) => item?.id !== removedUpload?.id);
  if (allUploadBodies.some((item) => item?.parse_status !== 'ready')) {
    throw new Error(`Not all files parsed successfully: ${JSON.stringify(allUploadBodies)}`);
  }
  if (allUploadBodies.some((item) => !String(item?.path || '').startsWith('会话附件/草稿-'))) {
    throw new Error(`Unexpected attachment path: ${JSON.stringify(allUploadBodies.map((item) => item?.path))}`);
  }
  if (maxConcurrentUploadRequests > 3) {
    throw new Error(`Upload concurrency exceeded three: ${maxConcurrentUploadRequests}`);
  }
  const retainedFiles = await page.evaluate(async () => {
    const token = sessionStorage.getItem('ai_infra_user_token') || '';
    const response = await fetch('/api/v1/terminal/workspace-files', {
      headers: { Authorization: `Bearer ${token}` },
    });
    return response.json();
  });
  if (!Array.isArray(retainedFiles) || !retainedFiles.some((item) => item.id === removedUpload.id)) {
    throw new Error('Removing an attachment card deleted the workspace file.');
  }

  await page.locator('.wb-cfg-trigger').click();
  const drawer = page.locator('.wb-cfg-drawer');
  await drawer.waitFor();
  await drawer.locator('.ant-select-selector').nth(1).click();
  await page.getByText(model, { exact: true }).last().click();
  await drawer.getByText('应用', { exact: true }).click();

  const requestText = '逐个列出四个附件的文件名和核心内容，不要读取工作空间其他文件，不要生成新文件。';
  const editor = page.locator('.skill-composer').first();
  await editor.fill(requestText);
  const runResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST' && /\/api\/v1\/terminal\/tasks\/[^/]+\/run$/.test(response.url())
  ), { timeout: 120_000 });
  await editor.press('Enter');
  const runResponse = await runResponsePromise;
  if (!runResponse.ok()) throw new Error(`Run request failed: ${runResponse.status()} ${await runResponse.text()}`);

  for (const expected of ['生产日报', '库存', '销售月报', 'Production report 42']) {
    await page.getByText(new RegExp(expected, 'i')).last().waitFor({ timeout: 180_000 });
  }
  await page.getByText('已完成', { exact: true }).last().waitFor({ timeout: 180_000 });

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByText(requestText.slice(0, 20), { exact: false }).first().click();
  for (const fixturePath of fixturePaths.slice(0, 4)) {
    await page.getByText(path.basename(fixturePath), { exact: true }).last().waitFor();
  }

  const attachmentIds = uploadBodies.map((item) => item.id);
  const visibleText = await page.locator('body').innerText();
  if (attachmentIds.some((id) => visibleText.includes(`@${id}`))) {
    throw new Error('A structured attachment UUID leaked into visible chat text.');
  }
  if (mockServer && !mockPromptVerified) {
    throw new Error('The LLM request did not contain all four exact attachment contents.');
  }
  const unexpectedConsoleErrors = consoleErrors.filter((entry) => (
    !entry.includes('[antd: Modal] `destroyOnClose` is deprecated')
    && !entry.includes('[antd: compatible] antd v5 support React is 16 ~ 18')
    && !entry.includes('[antd: message] Static function can not consume context like dynamic theme')
  ));
  if (unexpectedConsoleErrors.length) {
    throw new Error(`Browser console errors: ${unexpectedConsoleErrors.join(' | ')}`);
  }

  console.log(JSON.stringify({
    ok: true,
    max_concurrent_uploads: maxConcurrentUploadRequests,
    removed_attachment_retained_in_workspace: removedUpload.id,
    uploads: uploadBodies.map((item) => ({ id: item.id, path: item.path, parse_status: item.parse_status })),
    history_restored: fixturePaths.slice(0, 4).map((item) => path.basename(item)),
  }, null, 2));
} finally {
  await page.screenshot({ path: path.join(os.tmpdir(), 'ai-infra-chat-attachments-e2e.png'), fullPage: true }).catch(() => {});
  await browser.close();
  if (mockServer) await new Promise((resolve) => mockServer.close(resolve));
  fs.rmSync(oversizedPath, { force: true });
}
