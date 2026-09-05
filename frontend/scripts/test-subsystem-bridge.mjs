import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const tempDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-subsystem-bridge-'));

try {
  const source = await readFile(resolve('src/utils/subsystemBridge.ts'), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(tempDirectory, 'subsystemBridge.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const { buildHostReadyMessage, isBridgeReady, parseBridgeContext } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  const expected = { applicationSlug: 'sample-review', launchNonce: 'launch-0123456789abcdef' };

  const selected = parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce,
    module_key: 'sample_review', page_key: 'sample_review.list',
    entity_id: 'SR-1', selection: { id: 'SR-1', status: 'approved' },
    filters: { status: '' }, data_version: 3,
  }, expected);
  assert.equal(selected?.entity_id, 'SR-1');
  assert.equal(selected?.data_version, 3);
  assert.deepEqual(selected?.selection, { id: 'SR-1', status: 'approved' });

  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'other',
    launch_nonce: expected.launchNonce, data_version: 3,
  }, expected), null);
  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, data_version: Number.NaN,
  }, expected), null);
  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, selection: [],
  }, expected), null);
  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    launch_nonce: 'stale-launch', module_key: 'sample_review', page_key: 'sample_review.list',
  }, expected), null, 'stale iframe messages must not cross launch boundaries');
  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, module_key: 'sample_review', page_key: 'sample_review.list',
    unexpected: 'ignored-by-old-parser',
  }, expected), null, 'bridge envelopes use additionalProperties=false semantics');
  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, module_key: 'sample_review', page_key: 'sample_review.list',
    route: '//attacker.example/path',
  }, expected), null, 'bridge routes must remain same-origin paths');

  assert.equal(isBridgeReady({
    type: 'zhuojian:ready', version: 1, application_slug: 'sample-review', launch_nonce: expected.launchNonce,
  }, expected), true);
  assert.equal(isBridgeReady({
    type: 'zhuojian:ready', version: 1, application_slug: 'sample-review', launch_nonce: 'old',
  }, expected), false);
  assert.deepEqual(buildHostReadyMessage(expected, ['sample_review', 'bad key'], ['sample_review.list']), {
    type: 'zhuojian:host-ready', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, allowed_module_keys: ['sample_review'],
    allowed_page_keys: ['sample_review.list'],
  });

  const applicationViewSource = await readFile(
    resolve('src/pages/terminal/EnterpriseApplicationView.tsx'),
    'utf8',
  );
  assert.match(
    applicationViewSource,
    /sandbox="[^"]*allow-modals[^"]*"/,
    'embedded enterprise applications must be allowed to show confirmation dialogs',
  );
  assert.match(applicationViewSource, /event\.source !== frameRef\.current\?\.contentWindow/);
  assert.match(applicationViewSource, /event\.origin !== security\.origin/);
  assert.match(applicationViewSource, /launch\.launch_nonce/);
  assert.match(applicationViewSource, /launch\.page_keys/);
  assert.match(
    applicationViewSource,
    /module_key: fallbackModuleKey,[\s\S]*page_key: fallbackPageKey,[\s\S]*\.\.\.bridgeContext/,
    'business assistant must fall back to the authorized launch module and page until bridge context arrives',
  );
  assert.match(applicationViewSource, /referrerPolicy="origin"/);
  assert.match(
    applicationViewSource,
    /onAskAI: \([\s\S]*onProgress: \(event: Record<string, unknown>\) => void,[\s\S]*\) => Promise<string>/,
    'business assistant must execute inline and return its answer to the application drawer',
  );
  assert.match(
    applicationViewSource,
    /aria-label="选择业务小助手模型"[\s\S]*placeholder="请选择模型"/,
    'business assistant must expose the selected model instead of silently choosing one',
  );
  assert.match(
    applicationViewSource,
    /在当前页面执行/,
    'business assistant must keep the user on the embedded application page',
  );
  assert.match(
    applicationViewSource,
    /aria-label="业务小助手实时执行过程"/,
    'business assistant must show accessible live execution progress instead of a spinner-only state',
  );

  const terminalSource = await readFile(resolve('src/pages/terminal/Terminal.tsx'), 'utf8');
  const applicationAssistantSource = terminalSource.slice(terminalSource.indexOf('onAskAI={async'));
  assert.match(
    applicationAssistantSource,
    /terminal\.runTaskStream\(/,
    'business assistant must consume the real task event stream',
  );
  assert.match(
    applicationAssistantSource,
    /consumeTerminalEventStream\(response, \(event\) =>/,
    'business assistant must forward real run events to its progress timeline',
  );

  process.stdout.write('subsystem bridge tests passed\n');
} finally {
  await rm(tempDirectory, { recursive: true, force: true });
}

