import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const tempDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-presentation-'));

try {
  const sourcePath = resolve('src/utils/workspacePresentation.ts');
  const source = await readFile(sourcePath, 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(tempDirectory, 'workspacePresentation.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const {
    presentAssistantMarkdown,
    removeAttachmentReferenceTokens,
    removeLegacyArtifactTables,
  } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  const legacy = [
    '已完成修订。',
    '',
    '## 交付文件（2 个）',
    '| 文件 | file_id | 路径 |',
    '| --- | --- | --- |',
    '| 方案.docx | 11111111-1111-4111-8111-111111111111 | 技能输出/22222222-2222-4222-8222-222222222222/20260827-112050-ab12cd34-方案.docx |',
    '',
    '## 处理结果',
    '两个文件均已核验。',
  ].join('\n');
  const cleaned = removeLegacyArtifactTables(legacy);
  assert.equal(cleaned.includes('file_id'), false);
  assert.equal(cleaned.includes('技能输出/'), false);
  assert.equal(cleaned.includes('## 交付文件'), false);
  assert.equal(cleaned.includes('## 处理结果'), true);

  const businessTable = '| 款号 | 状态 |\n| --- | --- |\n| 203A023 | 已完成 |';
  assert.equal(removeLegacyArtifactTables(businessTable), businessTable);

  const attachmentId = '6862088e-b8f8-4f8a-852e-1085c7ba1d4b';
  assert.equal(
    removeAttachmentReferenceTokens(`请修改附件 @${attachmentId}`, [attachmentId]),
    '请修改附件',
  );
  assert.equal(
    removeAttachmentReferenceTokens('请检查 @not-an-attachment', [attachmentId]),
    '请检查 @not-an-attachment',
  );
  assert.equal(
    removeAttachmentReferenceTokens('请修改这些文件。@19ca9e41-4b2b-4e0f-8b1f-bc85b3a8e0a6', []),
    '请修改这些文件。',
  );

  assert.equal(presentAssistantMarkdown(legacy, [], false).includes('file_id'), true);
  assert.equal(presentAssistantMarkdown(legacy, [], true).includes('file_id'), false);
  process.stdout.write('workspace presentation tests passed\n');
} finally {
  await rm(tempDirectory, { recursive: true, force: true });
}
