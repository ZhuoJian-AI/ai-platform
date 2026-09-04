import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { createServer } from 'vite';
import spreadsheetModule from 'styled-exceljs';

const XLSX = spreadsheetModule.default || spreadsheetModule;
const sheet = XLSX.utils.aoa_to_sheet([
  ['月份', '部门', '数量', '金额'],
  ['1月', '设计部', 12, 1200],
  ['2月', '生产部', 18, 2500],
  ['3月', '销售部', 20, 3600],
]);
const workbook = XLSX.utils.book_new();
XLSX.utils.book_append_sheet(workbook, sheet, '旧文件数据');
const workbookBytes = XLSX.write(workbook, { bookType: 'xlsx', type: 'buffer' });

const server = await createServer({
  server: { host: '127.0.0.1', port: 0 },
  plugins: [{
    name: 'workspace-file-ui-fixture',
    configureServer(viteServer) {
      viteServer.middlewares.use((request, response, next) => {
        if (request.url?.split('?', 1)[0] !== '/__workspace-file-ui.xlsx') return next();
        response.statusCode = 200;
        response.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
        response.setHeader('Content-Length', String(workbookBytes.byteLength));
        response.end(workbookBytes);
      });
    },
  }],
});

let browser;
try {
  await server.listen();
  const address = server.httpServer?.address();
  assert(address && typeof address !== 'string');
  const origin = `http://127.0.0.1:${address.port}`;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    if (!String(error).includes("Executable doesn't exist")) throw error;
    // Developer machines may use the system Chrome without Playwright's
    // optional browser download. CI continues to use the pinned Chromium.
    browser = await chromium.launch({ channel: 'chrome', headless: true });
  }
  const context = await browser.newContext({ viewport: { width: 1280, height: 820 } });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  const page = await context.newPage();

  // Chinese IME: intermediate pinyin must not enter React state or get prefixed
  // to the committed Chinese text.
  await page.goto(`${origin}/scripts/fixtures/workspace-file-ui.html?case=ime`);
  const folderInput = page.getByPlaceholder('文件夹名');
  await folderInput.evaluate((input) => {
    const element = input;
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    element.focus();
    element.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    setValue?.call(element, 'zhongwen');
    element.dispatchEvent(new InputEvent('input', {
      bubbles: true, data: 'zhongwen', inputType: 'insertCompositionText', isComposing: true,
    }));
    setValue?.call(element, '中文目录');
    element.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '中文目录' }));
  });
  await assert.doesNotReject(() => page.getByTestId('ime-value').waitFor({ state: 'visible' }));
  await page.getByRole('button', { name: '创建' }).click();
  assert.equal(await page.getByTestId('ime-submitted').textContent(), '中文目录');

  // Fullscreen is a presentation state only; toggling it must not remount or
  // clear the local text draft.
  await page.goto(`${origin}/scripts/fixtures/workspace-file-ui.html?case=draft`);
  await page.getByRole('button', { name: '编辑文件' }).click();
  const draft = page.locator('textarea');
  await draft.fill('尚未保存的中文草稿');
  await page.getByRole('button', { name: '全屏预览' }).click();
  assert.equal(await draft.inputValue(), '尚未保存的中文草稿');
  await page.getByRole('button', { name: '退出全屏预览' }).click();
  assert.equal(await draft.inputValue(), '尚未保存的中文草稿');

  // A user's update permission alone is insufficient when the server-side
  // WebOffice feature is unavailable: do not render a button that must fail.
  await page.goto(`${origin}/scripts/fixtures/workspace-file-ui.html?case=office-edit-disabled`);
  assert.equal(await page.getByRole('button', { name: '协同编辑' }).count(), 0);
  assert.equal(await page.getByTestId('edit-session-calls').textContent(), '0');

  // Preview/AI mode changes do not create a WebOffice edit room. Only the
  // explicit edit button may call createEditSession when the server advertises
  // availability and the role has update permission.
  await page.goto(`${origin}/scripts/fixtures/workspace-file-ui.html?case=office-edit`);
  await page.getByText('AI 解析内容', { exact: true }).click();
  assert.equal(await page.getByTestId('edit-session-calls').textContent(), '0');
  await page.getByText('原文件预览', { exact: true }).click();
  assert.equal(await page.getByTestId('edit-session-calls').textContent(), '0');
  await page.getByRole('button', { name: '协同编辑' }).click();
  await page.getByTestId('edit-session-calls').getByText('1').waitFor();

  // Workspace HTML is untrusted. It must render as escaped text, must not get
  // an executable/new-tab path, and inline/event-handler JavaScript must stay inert.
  await page.goto(`${origin}/scripts/fixtures/workspace-file-ui.html?case=html-security`);
  const htmlPreview = page.getByTestId('workspace-html-safe-preview');
  await htmlPreview.waitFor({ state: 'visible' });
  assert.match(await htmlPreview.textContent(), /<script>/);
  assert.equal(await htmlPreview.locator('script').count(), 0);
  assert.equal(await htmlPreview.locator('img').count(), 0);
  assert.equal(await page.getByRole('button', { name: '在新标签页中打开' }).count(), 0);
  await page.waitForTimeout(200);
  assert.deepEqual(await page.evaluate(() => ({
    script: localStorage.getItem('workspace-html-script'),
    onerror: localStorage.getItem('workspace-html-onerror'),
  })), { script: null, onerror: null });

  // URL-backed data models an already uploaded/old file. Exercise actual
  // renderer pointer selection and the toolbar's formatted clipboard bridge.
  await page.goto(`${origin}/scripts/fixtures/workspace-file-ui.html?case=spreadsheet`);
  const stage = page.locator('.e-virt-table-stage');
  await stage.waitFor({ state: 'visible', timeout: 30_000 });
  await page.waitForTimeout(2_000);
  const box = await stage.boundingBox();
  if (!box || box.height <= 80) {
    const debugBounds = await page.locator('[class*="e-virt"]').evaluateAll((elements) => elements.slice(0, 20).map((element) => ({
      className: element.className,
      bounds: element.getBoundingClientRect().toJSON(),
    })));
    process.stderr.write(`${JSON.stringify(debugBounds, null, 2)}\n`);
  }
  assert(box && box.width > 320 && box.height > 80, `unexpected spreadsheet stage bounds: ${JSON.stringify(box)}`);
  await page.mouse.move(box.x + 90, box.y + 48);
  await page.mouse.down();
  await page.mouse.move(box.x + 310, box.y + 108, { steps: 8 });
  await page.mouse.up();
  await page.getByTestId('spreadsheet-copy-selection').click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  assert.match(copied, /\t|\n/, 'drag selection must copy more than one spreadsheet cell');
  assert.match(copied, /月份|部门|1月|设计部/, 'copied selection must contain visible workbook data');

  process.stdout.write('workspace file UI regression tests passed\n');
} finally {
  await browser?.close();
  await server.close();
}
