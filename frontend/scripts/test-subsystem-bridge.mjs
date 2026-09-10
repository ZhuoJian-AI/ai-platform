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
  const {
    buildHostReadyMessage, buildRefreshMessage, isBridgeReady,
    parseBridgeAiRun, parseBridgeContext, parseBridgeRefreshResult,
  } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

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

  const pageWithoutSelectedEntity = parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce,
    module_key: 'sample_review', page_key: 'sample_review.list',
    entity_type: '', entity_id: '', filters: {}, selection: {},
  }, expected);
  assert.equal(pageWithoutSelectedEntity?.module_key, 'sample_review');
  assert.equal('entity_type' in (pageWithoutSelectedEntity ?? {}), false);
  assert.equal('entity_id' in (pageWithoutSelectedEntity ?? {}), false);

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
  const refreshExpected = {
    ...expected,
    moduleKey: 'sample_review',
    pageKey: 'sample_review.list',
    requestId: 'refresh-0123456789abcdef',
  };
  assert.deepEqual(buildRefreshMessage(refreshExpected), {
    type: 'zhuojian:refresh', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, module_key: 'sample_review',
    page_key: 'sample_review.list', request_id: 'refresh-0123456789abcdef',
  });
  assert.deepEqual(parseBridgeRefreshResult({
    type: 'zhuojian:refresh-result', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, module_key: 'sample_review',
    page_key: 'sample_review.list', request_id: 'refresh-0123456789abcdef',
    status: 'completed', data_version: 12,
  }, refreshExpected), { status: 'completed', dataVersion: 12 });
  assert.equal(parseBridgeRefreshResult({
    type: 'zhuojian:refresh-result', version: 1, application_slug: 'sample-review',
    launch_nonce: 'stale', module_key: 'sample_review', page_key: 'sample_review.list',
    request_id: 'refresh-0123456789abcdef', status: 'completed',
  }, refreshExpected), null, 'refresh results must be bound to the active launch');
  assert.equal(parseBridgeRefreshResult({
    type: 'zhuojian:refresh-result', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, module_key: 'sample_review', page_key: 'sample_review.list',
    request_id: 'other-request', status: 'completed',
  }, refreshExpected), null, 'refresh results must be bound to the request');

  const aiRun = parseBridgeAiRun({
    type: 'zhuojian:ai-run', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, module_key: 'sample_review',
    page_key: 'sample_review.list', action_key: 'sample_review.ocr',
    request_id: 'ai-request-01234567', capability: 'vision.ocr',
    instruction: '识别图片中的手写意见', context: { record_id: 'SR-1' },
    files: [{ name: 'review.png', mime_type: 'image/png', blob: new Blob(['png']) }],
  }, expected);
  assert.equal(aiRun?.capability, 'vision.ocr');
  assert.equal(aiRun?.files[0].name, 'review.png');
  assert.equal(parseBridgeAiRun({
    type: 'zhuojian:ai-run', version: 1, application_slug: 'sample-review',
    launch_nonce: 'stale', module_key: 'sample_review', page_key: 'sample_review.list',
    action_key: 'sample_review.ocr', request_id: 'ai-request-01234567',
    capability: 'vision.ocr', context: {}, files: [],
  }, expected), null, 'specialist AI requests must be bound to the active launch');
  assert.equal(parseBridgeAiRun({
    type: 'zhuojian:ai-run', version: 1, application_slug: 'sample-review',
    launch_nonce: expected.launchNonce, module_key: 'sample_review', page_key: 'sample_review.list',
    action_key: 'sample_review.ocr', request_id: 'short', capability: 'vision.ocr',
    context: {}, files: [],
  }, expected), null, 'specialist AI request ids must be safe and replay-stable');

  const applicationViewSource = await readFile(
    resolve('src/pages/terminal/EnterpriseApplicationView.tsx'),
    'utf8',
  );
  assert.match(
    applicationViewSource,
    /sandbox="[^"]*allow-modals[^"]*"/,
    'embedded enterprise applications must be allowed to show confirmation dialogs',
  );
  assert.match(applicationViewSource, /event\.source !== frameRefs\.current\[activeFrameIndex\]\?\.contentWindow/);
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
    /onAskAI: \([\s\S]*onProgress: \(event: Record<string, unknown>\) => void,[\s\S]*\) => Promise<BusinessAssistantTurnResult>/,
    'business assistant must execute inline and return its answer to the application drawer',
  );
  assert.match(
    applicationViewSource,
    /isBridgeReady\(event\.data[\s\S]*setFrameLoaded\(true\)/,
    'only a validated subsystem bridge message may mark the iframe as ready',
  );
  assert.doesNotMatch(
    applicationViewSource,
    /onLoad=\{[\s\S]{0,500}setFrameLoaded\(true\)/,
    'browser error documents must not be mistaken for a loaded subsystem',
  );
  const submitSource = applicationViewSource.slice(
    applicationViewSource.indexOf('const submit = async'),
    applicationViewSource.indexOf('const uploadInputFiles'),
  );
  assert.doesNotMatch(
    submitSource,
    /refreshFrame\(/,
    'a completed assistant turn must never destroy and recreate the iframe unconditionally',
  );
  assert.match(
    submitSource,
    /if \(result\.refreshRequired\) scheduleSilentRefresh\(\)/,
    'only a trusted successful business mutation may request a silent refresh',
  );
  assert.match(applicationViewSource, /buildRefreshMessage\(refreshExpectation\)/);
  assert.match(applicationViewSource, /parseBridgeRefreshResult\(event\.data, refreshExpectation\)/);
  assert.match(applicationViewSource, /parseBridgeAiRun\(event\.data, security\.expectation\)/);
  assert.match(applicationViewSource, /terminal\.createSubsystemAiRun\(/);
  assert.match(applicationViewSource, /activeContext\.page_key !== aiRequest\.pageKey/);
  assert.match(applicationViewSource, /enterprise-app-view__frame--standby/);
  assert.match(applicationViewSource, /setActiveFrameIndex\(nextIndex\)/);
  assert.match(
    applicationViewSource,
    /aria-label="选择灼见助手模型"[\s\S]*placeholder="请选择模型"/,
    'business assistant must expose the selected model instead of silently choosing one',
  );
  assert.match(
    applicationViewSource,
    /在当前页面执行/,
    'business assistant must keep the user on the embedded application page',
  );
  assert.match(
    applicationViewSource,
    /aria-label="灼见助手实时执行过程"/,
    'business assistant must show accessible live execution progress instead of a spinner-only state',
  );
  assert.doesNotMatch(
    applicationViewSource,
    /\b(?:data_interface|ontology)\b/,
    'retired data-interface and ontology trace categories must not leak into the business assistant',
  );

  const terminalSource = await readFile(resolve('src/pages/terminal/Terminal.tsx'), 'utf8');
  const apiClientSource = await readFile(resolve('src/api/client.ts'), 'utf8');
  const terminalStreamSource = await readFile(resolve('src/pages/terminal/terminalConversationModel.ts'), 'utf8');
  assert.match(
    terminalSource,
    /case 'ui_intent':[\s\S]*navigateToEnterpriseIntent/,
    'a trusted navigation intent must move the same assistant conversation into the authorized application view',
  );
  assert.match(
    terminalSource,
    /pageKey=\{selectedApplicationPageKey\}[\s\S]*assistantOpenRequestKey=\{assistantOpenRequestKey\}/,
    'assistant navigation must preserve the exact page target and keep the assistant visible',
  );
  assert.match(
    apiClientSource,
    /if \(pageKey\) params\.set\('page_key', pageKey\)/,
    'the launch request must send the exact page key for server-side role authorization',
  );
  const applicationAssistantSource = terminalSource.slice(terminalSource.indexOf('onAskAI={async'));
  assert.match(
    applicationAssistantSource,
    /params\.set\('conversation', created\.id\);\s*navigate\([\s\S]*replace: true/,
    'a new sidebar task must persist its conversation id in the URL before streaming for reload recovery',
  );
  assert.match(
    applicationAssistantSource,
    /terminal\.runTaskStream\(/,
    'business assistant must consume the real task event stream',
  );
  assert.match(
    applicationAssistantSource,
    /consumeTerminalEventStream\(streamResponse, \(event\) =>/,
    'business assistant must forward real run events to its progress timeline',
  );
  assert.match(
    applicationAssistantSource,
    /onProgress\(\{ \.\.\.event, task_id: activeTaskId \}\)/,
    'business assistant approval events must carry their task id to the inline UI',
  );
  assert.match(
    applicationAssistantSource,
    /event\.type === 'tool_result' && event\.business_mutation_committed === true/,
    'the host may refresh only from a backend-authenticated successful mutation result',
  );
  assert.match(applicationAssistantSource, /refreshRequired,/);
  assert.match(
    terminalStreamSource,
    /event\.type === 'final'[\s\S]*reader\.cancel\(\)/,
    'business assistant must stop waiting as soon as the terminal final event arrives',
  );
  assert.match(
    applicationViewSource,
    /<ApprovalCard[\s\S]*taskId=\{item\.taskId\}/,
    'business assistant must render actionable runtime approval cards inline',
  );

  process.stdout.write('subsystem bridge tests passed\n');
} finally {
  await rm(tempDirectory, { recursive: true, force: true });
}

