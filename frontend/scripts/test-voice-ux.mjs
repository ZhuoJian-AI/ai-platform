import { chromium } from 'playwright';
import assert from 'node:assert/strict';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:4181');
  const result = await page.evaluate(async () => {
    const ReactModule = await import('/node_modules/.vite/deps/react.js');
    const React = ReactModule.default || ReactModule;
    const rootModule = await import('/node_modules/.vite/deps/react-dom_client.js');
    const { createRoot } = rootModule.default || rootModule;
    const { useCurrentTurnAnchor } = await import('/src/pages/terminal/useCurrentTurnAnchor.ts');
    const { default: Panel, VoiceConversationProvider } = await import('/src/pages/terminal/VoiceConversationPanel.tsx');
    const h = React.createElement;
    const host = document.createElement('div'); document.body.replaceChildren(host);
    const root = createRoot(host);
    const adoptedTask = { current: null };
    function Harness({ suffix }) {
      const { listRef, jump } = useCurrentTurnAnchor('task', 3);
      return h(VoiceConversationProvider, { scopeKey: 'draft:1', adoptedTask, enabled: true, submit: async () => ({ taskId: 'task', needsConfirmation: false }) },
        h('div', { id: 'scroller', style: { height: 150, overflowY: 'auto' } },
          h('div', { ref: listRef }, ...[1, 2, 3].map(i => h('div', { key: i, 'data-user-turn': '', style: { height: 250 } }, `Turn ${i}${suffix}`)))),
        h('button', { onClick: jump, id: 'jump' }, '回到当前回复'), h(Panel));
    }
    const wait = () => new Promise(r => setTimeout(r, 120));
    root.render(h(Harness, { suffix: '' })); await wait();
    const scroller = document.getElementById('scroller');
    const positioned = scroller.scrollTop > 0;
    scroller.scrollTop = 25;
    root.render(h(Harness, { suffix: 'new streamed content' })); await wait();
    const freeScroll = scroller.scrollTop === 25;
    document.getElementById('jump').click(); await wait();
    const returned = scroller.scrollTop > 25;
    const button = document.querySelector('button[aria-label="语音模式"]');
    const draftEnabled = button && !button.disabled;
    root.unmount();
    return { positioned, freeScroll, returned, draftEnabled };
  });
  for (const [key, value] of Object.entries(result)) assert.equal(value, true, key);
  console.log(result);
} finally { await browser.close(); }
