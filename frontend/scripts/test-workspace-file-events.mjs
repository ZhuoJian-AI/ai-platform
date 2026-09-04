import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const temporaryDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-file-events-'));

try {
  const source = await readFile(resolve('src/utils/workspaceFileEvents.ts'), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(temporaryDirectory, 'workspaceFileEvents.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const {
    advanceWorkspaceFileConnection,
    decodeWorkspaceFileEvent,
    decodeWorkspaceFileStreamFrame,
  } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  assert.deepEqual(
    decodeWorkspaceFileStreamFrame('id: 12\nevent: cursor\ndata: {"cursor":12}'),
    { cursor: 12, event: null },
  );

  assert.deepEqual(
    decodeWorkspaceFileEvent('id: 12\ndata: {"id":12,"file_id":"file-1","version_id":"version-2","event_type":"file_version_created"}'),
    { id: 12, file_id: 'file-1', version_id: 'version-2', event_type: 'file_version_created' },
  );
  assert.deepEqual(
    decodeWorkspaceFileEvent('data: {"id":"13","file_id":"file-2","version_id":null}\r\n'),
    { id: 13, file_id: 'file-2', version_id: null, event_type: 'file_version_changed' },
  );
  assert.equal(decodeWorkspaceFileEvent(': heartbeat'), null);
  assert.equal(decodeWorkspaceFileEvent('data: not-json'), null);
  assert.equal(decodeWorkspaceFileEvent('data: {"id":14,"file_id":""}'), null);
  assert.equal(decodeWorkspaceFileEvent('data: {"id":-1,"file_id":"file-3"}'), null);

  // Reconnection boundary: the initial cursor is persisted immediately, even
  // when the first stream disconnects before delivering a file event.
  let reconnectCursor = 0;
  const baseline = decodeWorkspaceFileStreamFrame('event: cursor\ndata: {"cursor":41}');
  reconnectCursor = Math.max(reconnectCursor, baseline?.cursor ?? reconnectCursor);
  assert.equal(reconnectCursor, 41);
  // Snapshot-before-baseline race: the first cursor frame forces one HTTP list
  // refresh, while later cursor-only progress advances without refetching again.
  const initialStep = advanceWorkspaceFileConnection({ cursor: 0, baselineHandled: false }, baseline);
  assert.equal(initialStep.state.cursor, 41);
  assert.equal(initialStep.refreshSnapshot, true);
  assert.equal(initialStep.event, null);
  const filteredProgress = decodeWorkspaceFileStreamFrame('event: cursor\ndata: {"cursor":45}');
  const progressStep = advanceWorkspaceFileConnection(initialStep.state, filteredProgress);
  assert.equal(progressStep.state.cursor, 45);
  assert.equal(progressStep.refreshSnapshot, false);
  const afterReconnect = decodeWorkspaceFileStreamFrame(
    'id: 42\nevent: workspace-file\ndata: {"id":42,"file_id":"file-after-reconnect","version_id":"v-42"}',
  );
  assert.equal(afterReconnect?.cursor, 42);
  assert.equal(afterReconnect?.event?.file_id, 'file-after-reconnect');
  assert.equal(decodeWorkspaceFileStreamFrame('event: cursor\ndata: {"cursor":-1}'), null);

  process.stdout.write('workspace file event tests passed\n');
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
