import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import { systemToolFactoryInput, verifyRelease, type ReleaseManifest } from '../extensions.js'

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function request(manifest: ReleaseManifest) {
  const canonical = structuredClone(manifest)
  for (const item of canonical.external_extensions ?? []) {
    delete item.artifact_url
    delete item.artifact_headers
  }
  return {
    release_id: '01234567-89ab-cdef-0123-456789abcdef',
    manifest,
    checksum: createHash('sha256').update(stable(canonical)).digest('hex'),
  }
}

function baseline(): ReleaseManifest {
  return {
    node_version: '22.19.0',
    dsh_version: '0.1.0-rc.8',
    plugins: [
      { slug: 'dsh-llm-runtime', enabled: true },
      { slug: 'dsh-session', enabled: true },
      { slug: 'dsh-system-prompt', enabled: true },
      { slug: 'dsh-tools', enabled: true },
      { slug: 'dsh-agent', enabled: true },
      { slug: 'dsh-agent-loop', enabled: true, capabilities: ['coordinator'] },
    ],
    external_extensions: [],
  }
}

test('accepts a checksum-matched baseline with one coordinator', () => {
  assert.doesNotThrow(() => verifyRelease(request(baseline())))
})

test('rejects coordinator removal before an alternative is installed', () => {
  const manifest = baseline()
  manifest.plugins![5]!.enabled = false
  assert.throws(() => verifyRelease(request(manifest)), /exactly one coordinator/)
})

test('rejects a system tool artifact without declared tool schemas', () => {
  const manifest = baseline()
  manifest.external_extensions = [{
    slug: 'unsafe-tool',
    type: 'system_tool',
    enabled: true,
    entry: './index.js',
    artifact_url: 'https://example.invalid/plugin.tar.gz',
    artifact_sha256: 'a'.repeat(64),
  }]
  assert.throws(() => verifyRelease(request(manifest)), /declares no tools/)
})

test('rejects malformed artifact checksums before any download', () => {
  const manifest = baseline()
  manifest.external_extensions = [{
    slug: 'reviewed-tool', type: 'system_tool', enabled: true,
    entry: './index.js', artifact_url: 'https://example.invalid/plugin.tar.gz',
    artifact_sha256: '../not-a-checksum',
    tools: [{ name: 'reviewed_lookup' }],
  }]
  assert.throws(() => verifyRelease(request(manifest)), /invalid artifact checksum/)
})

test('rejects a release built for a different fixed Node runtime', () => {
  const manifest = baseline()
  manifest.node_version = '20.18.0'
  assert.throws(() => verifyRelease(request(manifest)), /requires Node 20.18.0/)
})

test('system tool factory receives config and a run-scoped platform bridge', async () => {
  const input = systemToolFactoryInput('example-tool', { endpoint: 'https://example.test' })
  assert.equal(input.endpoint, 'https://example.test')
  assert.deepEqual(input.config, { endpoint: 'https://example.test' })
  const bridge = input.platformBridge as { invoke(name: string, args: unknown, context: unknown): Promise<unknown> }
  const calls: unknown[] = []
  const result = await bridge.invoke('workspace_list_files', { path: '/' }, {
    signal: new AbortController().signal,
    runId: 'run-1',
    taskId: 'task-1',
    invokePlatformTool: async (name: string, args: unknown) => {
      calls.push([name, args])
      return { ok: true }
    },
  })
  assert.deepEqual(result, { ok: true })
  assert.deepEqual(calls, [['workspace_list_files', { path: '/' }]])
})
