import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const temporaryDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-file-links-'));

try {
  const source = await readFile(resolve('src/utils/workspaceFileLinks.ts'), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(temporaryDirectory, 'workspaceFileLinks.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const {
    buildTaskRunFilePayload,
    parseWorkspaceInternalUrl,
    workspaceFileDestination,
    workspaceFileLabel,
    workspaceInternalUrl,
  } = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  const fileId = '6862088e-b8f8-4f8a-852e-1085c7ba1d4b';
  const versionId = '19ca9e41-4b2b-4e0f-8b1f-bc85b3a8e0a6';
  assert.deepEqual(parseWorkspaceInternalUrl(`/f/${fileId}`, 'https://example.cn'), { fileId, versionId: undefined });
  assert.deepEqual(parseWorkspaceInternalUrl(`https://example.cn/f/${fileId}?version=${versionId}`, 'https://example.cn'), { fileId, versionId });
  assert.equal(parseWorkspaceInternalUrl(`https://evil.example/f/${fileId}`, 'https://example.cn'), null);
  assert.equal(parseWorkspaceInternalUrl(`/f/${fileId}/伪造后缀`, 'https://example.cn'), null);
  assert.equal(parseWorkspaceInternalUrl('请查看这个普通文本', 'https://example.cn'), null);
  assert.equal(
    workspaceInternalUrl({ id: fileId, workspace_id: 'ws', path: '目录/文件.md' }, 'https://example.cn'),
    `https://example.cn/f/${fileId}`,
  );
  assert.equal(
    workspaceInternalUrl({ id: fileId, workspace_id: 'ws', path: '目录/文件.md', internal_url: `/f/${fileId}` }, 'https://example.cn'),
    `https://example.cn/f/${fileId}`,
  );
  assert.equal(
    workspaceInternalUrl({ id: fileId, workspace_id: 'ws', path: '目录/文件.md', internal_url: `https://old-host.example/f/${fileId}` }, 'https://example.cn'),
    `https://example.cn/f/${fileId}`,
  );
  assert.equal(workspaceFileLabel({ id: fileId, workspace_id: 'ws', workspace_name: '销售部', path: '目录/文件.md' }), '销售部:/目录/文件.md');
  assert.equal(workspaceFileLabel({ id: fileId, workspace_id: 'ws', workspace_name: '销售部', path: 'ignored', canonical_path: '销售部:/目录/文件.md' }), '销售部:/目录/文件.md');
  assert.equal(
    workspaceFileDestination({ id: fileId, workspace_id: 'workspace-1' }, { kind: 'admin' }, versionId),
    `/agent/workspaces?view=workspace&workspace=workspace-1&file=${fileId}&version=${versionId}`,
  );
  assert.equal(
    workspaceFileDestination({ id: fileId, workspace_id: 'workspace-1' }, { kind: 'user', organizationSlug: 'ai-fa-bei' }),
    `/ai-fa-bei/terminal?view=workspace&workspace=workspace-1&file=${fileId}`,
  );

  const payload = buildTaskRunFilePayload(
    ['legacy-attachment-id'],
    [{ file_id: fileId, scope: 'task', version_id: versionId, follow_latest: false }],
  );
  assert.deepEqual(payload.attachment_file_ids, ['legacy-attachment-id']);
  assert.deepEqual(payload.file_refs_v1, [{ file_id: fileId, scope: 'task', version_id: versionId, follow_latest: false }]);
  process.stdout.write('workspace file link tests passed\n');
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
