const puppeteer = require('puppeteer-core');

const URL = 'http://127.0.0.1:5173/login';
const EXPECT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    // wait briefly for antd components to mount
    await new Promise((r) => setTimeout(r, 1200));

    const result = await page.evaluate((expected) => {
      const pick = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const cs = getComputedStyle(el);
        return { selector: sel, tag: el.tagName, class: el.className, fontFamily: cs.fontFamily, fontSize: cs.fontSize };
      };
      const targets = ['.ant-input', '.ant-btn', '.ant-form-item-label', 'h2', 'body'];
      const samples = targets.map(pick).filter(Boolean);
      return {
        rootFontFamily: getComputedStyle(document.documentElement).fontFamily,
        rootFontSize: getComputedStyle(document.documentElement).fontSize,
        bodyFontFamily: getComputedStyle(document.body).fontFamily,
        expected,
        samples,
      };
    }, EXPECT);

    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('ERR', e); process.exit(1); });
