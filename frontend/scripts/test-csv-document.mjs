import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const temporaryDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-csv-'));
try {
  const source = await readFile(resolve('src/utils/csvDocument.ts'), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(temporaryDirectory, 'csvDocument.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const { parseCsvDocument, serializeCsvDocument } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  const original = '\uFEFF姓名,备注\r\n王鑫涛,"中文,可编辑"\r\n张三,"第一行\r\n第二行"\r\n';
  const parsed = parseCsvDocument(original);
  assert.equal(parsed.bom, true);
  assert.equal(parsed.newline, '\r\n');
  assert.equal(parsed.trailingNewline, true);
  assert.deepEqual(parsed.rows[1], ['王鑫涛', '中文,可编辑']);
  assert.deepEqual(parsed.rows[2], ['张三', '第一行\r\n第二行']);
  assert.equal(serializeCsvDocument(parsed), original);

  parsed.rows[1][1] = '修改后的中文';
  const edited = serializeCsvDocument(parsed);
  assert.equal(edited.startsWith('\uFEFF'), true);
  assert.equal(edited.endsWith('\r\n'), true);
  assert.equal(edited.includes('修改后的中文'), true);
  process.stdout.write('csv document tests passed\n');
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
