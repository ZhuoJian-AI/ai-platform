import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const tempDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-business-conversation-'));

try {
  const source = await readFile(resolve('src/utils/businessConversation.ts'), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(tempDirectory, 'businessConversation.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const { resolveBusinessConversationId } = await import(
    `${pathToFileURL(modulePath).href}?v=${Date.now()}`
  );

  const appId = 'app-1';
  const conversationId = 'conversation-from-url';
  assert.equal(
    resolveBusinessConversationId(appId, false, { [appId]: conversationId }, []),
    conversationId,
    'the URL conversation must survive while the application catalog is loading',
  );
  assert.equal(
    resolveBusinessConversationId(appId, true, { [appId]: null }, [{
      id: 'recent-conversation', config: { application_id: appId },
    }]),
    null,
    'an explicit new-conversation draft must not restore an older task',
  );
  assert.equal(
    resolveBusinessConversationId(appId, true, {}, [{
      id: 'recent-conversation', config: { application_id: appId },
    }]),
    'recent-conversation',
    'an application without an explicit selection restores its latest task',
  );
  process.stdout.write('business conversation tests passed\n');
} finally {
  await rm(tempDirectory, { recursive: true, force: true });
}
