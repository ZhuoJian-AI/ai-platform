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
  const { parseBridgeContext } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  const selected = parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review',
    module_key: 'sample_review', page_key: 'sample_review.list',
    entity_id: 'SR-1', selection: { id: 'SR-1', status: 'approved' },
    filters: { status: '' }, data_version: 3,
  }, 'sample-review');
  assert.equal(selected?.entity_id, 'SR-1');
  assert.equal(selected?.data_version, 3);
  assert.deepEqual(selected?.selection, { id: 'SR-1', status: 'approved' });

  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'other', data_version: 3,
  }, 'sample-review'), null);
  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review', data_version: Number.NaN,
  }, 'sample-review'), null);
  assert.equal(parseBridgeContext({
    type: 'zhuojian:context', version: 1, application_slug: 'sample-review', selection: [],
  }, 'sample-review'), null);

  process.stdout.write('subsystem bridge tests passed\n');
} finally {
  await rm(tempDirectory, { recursive: true, force: true });
}

