import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { transform } from 'esbuild';

const source = await readFile('src/pages/terminal/terminalConversationModel.ts', 'utf8');
const compiled = await transform(source, { loader: 'ts', format: 'esm' });
const { applyArtifactEvent, messageArtifacts } = await import(`data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`);
const initial = [{ role: 'user', content: '生成文件' }, { role: 'assistant', content: '' }];
const artifact = { file_id: 'file-1', version_id: 'version-1', display_name: '测试.txt', mime_type: 'text/plain' };
const first = applyArtifactEvent(initial, { type: 'artifact', artifact });
assert.equal(first[1].artifacts.length, 1);
assert.equal(first[1].artifacts[0].versionId, 'version-1');
assert.equal(initial[1].artifacts, undefined);
const replay = applyArtifactEvent(first, { type: 'final', artifacts: [artifact] });
assert.equal(replay[1].artifacts.length, 1);
const nextVersion = applyArtifactEvent(replay, { type: 'artifact', artifact: { ...artifact, version_id: 'version-2' } });
assert.equal(nextVersion[1].artifacts.length, 2);
assert.equal(applyArtifactEvent(initial, { type: 'text', artifact }), initial);
assert.equal(applyArtifactEvent(initial, { type: 'artifact', artifact: { workspace_path: '/fake.txt' } }), initial);
assert.equal(applyArtifactEvent(initial.slice(0, 1), { type: 'artifact', artifact }).length, 1);
assert.deepEqual(messageArtifacts({ artifacts: [artifact] }), first[1].artifacts);
console.log('terminal artifact event tests passed');

const labelsSource = await readFile('src/pages/terminal/executionVerificationLabel.ts', 'utf8');
const labelsCompiled = await transform(labelsSource, { loader: 'ts', format: 'esm' });
const { executionVerificationLabel } = await import(`data:text/javascript;base64,${Buffer.from(labelsCompiled.code).toString('base64')}`);
assert.equal(executionVerificationLabel('verified'), '工具调用成功');
assert.equal(executionVerificationLabel('partial'), '部分工具调用失败');
for (const status of ['verified', 'partial', 'failed', 'recovered', 'legacy_unverified']) {
  assert.doesNotMatch(executionVerificationLabel(status), /已完成|部分完成|任务成功/);
}
assert.equal(executionVerificationLabel('unknown'), '工具状态未知');
console.log('tool receipts do not claim goal completion: passed');
