import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const temporaryDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-office-edit-'));
try {
  const source = await readFile(resolve('src/utils/workspaceOfficeEdit.ts'), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(temporaryDirectory, 'workspaceOfficeEdit.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const { workspaceOfficeEditOutcome } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  assert.deepEqual(workspaceOfficeEditOutcome({
    room_id: 'room-1', status: 'closing', save_status: 'closing',
    final_file_version_id: null, current_version_id: 'unrelated-new-version', error: null,
  }), { kind: 'pending' });
  assert.deepEqual(workspaceOfficeEditOutcome({
    room_id: 'room-1', status: 'closed', save_status: 'closed',
    final_file_version_id: 'room-1-version', current_version_id: 'later-version', error: null,
  }), { kind: 'saved', finalFileVersionId: 'room-1-version' });
  assert.deepEqual(workspaceOfficeEditOutcome({
    room_id: 'room-2', status: 'failed', save_status: 'failed',
    final_file_version_id: null, current_version_id: 'same-version', error: '对象版本校验失败',
  }), { kind: 'failed', error: '对象版本校验失败' });
  assert.deepEqual(workspaceOfficeEditOutcome({
    room_id: 'room-3', status: 'unchanged', save_status: 'unchanged',
    final_file_version_id: null, current_version_id: 'same-version', error: null,
  }), { kind: 'unchanged' });

  const apiSource = await readFile(resolve('src/api/client.ts'), 'utf8');
  assert.match(
    apiSource,
    /refreshFileEditSession:[\s\S]*?JSON\.stringify\(\{ room_id: roomId, access_token:/,
    'admin edit-token refresh must identify the exact room',
  );
  assert.match(
    apiSource,
    /refreshWsFileEditSession:[\s\S]*?JSON\.stringify\(\{ room_id: roomId, access_token:/,
    'employee edit-token refresh must identify the exact room',
  );

  process.stdout.write('workspace office edit tests passed\n');
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
