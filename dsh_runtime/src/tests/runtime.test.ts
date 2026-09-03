import assert from 'node:assert/strict'
import { createServer, type IncomingMessage, type Server } from 'node:http'
import { afterEach, test } from 'node:test'
import { DshRuntime } from '../runtime.js'
import type { RunRequest, RuntimeEvent } from '../contracts.js'
import { parseNdjson } from '../platform.js'

const servers: Server[] = []

afterEach(async () => {
  await Promise.all(servers.splice(0).map(server => new Promise<void>(resolve => server.close(() => resolve()))))
})

async function body(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = []
  for await (const chunk of request) chunks.push(Buffer.from(chunk))
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>
}

function textStream(text: string): string {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    { type: 'text-delta', index: 0, text },
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'usage', usage: { inputTokens: 3, outputTokens: 2 } },
    { type: 'finish', reason: { kind: 'stop' } },
  ].map(event => JSON.stringify(event)).join('\n') + '\n'
}

function toolStream(name: string, args: Record<string, unknown>): string {
  const argumentsJson = JSON.stringify(args)
  return [
    { type: 'block-start', index: 0, blockType: 'tool-call' },
    { type: 'tool-call-delta', index: 0, id: 'call-1', name, argumentsDelta: argumentsJson },
    { type: 'block-end', index: 0, block: { type: 'tool-call', id: 'call-1', name, arguments: argumentsJson } },
    { type: 'usage', usage: { inputTokens: 3, outputTokens: 2 } },
    { type: 'finish', reason: { kind: 'tool-calls' } },
  ].map(event => JSON.stringify(event)).join('\n') + '\n'
}

async function fakeBackend(handler: (request: IncomingMessage) => Promise<string | Record<string, unknown>>): Promise<string> {
  const server = createServer(async (request, response) => {
    try {
      const result = await handler(request)
      if (typeof result === 'string') {
        response.writeHead(200, { 'content-type': 'application/x-ndjson' })
        response.end(result)
      } else {
        response.writeHead(200, { 'content-type': 'application/json' })
        response.end(JSON.stringify(result))
      }
    } catch (error) {
      response.writeHead(500, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ detail: error instanceof Error ? error.message : String(error) }))
    }
  })
  servers.push(server)
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  assert(address && typeof address === 'object')
  return `http://127.0.0.1:${address.port}`
}

function request(overrides: Partial<RunRequest> = {}): RunRequest {
  return {
    run_id: 'run-1', task_id: 'task-1', run_token: 'opaque-token', messages: [],
    message: '你好', system_prompt: '你是企业助手。', model: { alias: 'default' },
    exec_mode: 'craft', tools: [], max_steps: 24, ...overrides,
  }
}

test('preserves the backend model bridge error detail', async () => {
  const response = new Response(JSON.stringify({
    detail: '当前模型尚未完成全部能力验证，请管理员完成能力测试。',
  }), {
    status: 409,
    headers: { 'content-type': 'application/json' },
  })

  await assert.rejects(
    () => parseNdjson(response),
    /当前模型尚未完成全部能力验证/,
  )
})

test('runs a direct DSH answer through the platform model adapter', async () => {
  const backendUrl = await fakeBackend(async incoming => {
    assert.equal(incoming.url, '/api/v1/internal/dsh/model/stream')
    const payload = await body(incoming)
    assert.equal(payload.run_token, 'opaque-token')
    assert.equal(payload.image_inputs, undefined)
    return textStream('直接回答')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request(), event => events.push(event))
  const done = events.find(event => event.type === 'done')
  assert.deepEqual(done, { type: 'done', text: '直接回答', steps: 1, tool_calls: 0 })
})

test('executes an authorized platform tool then continues the DSH loop', async () => {
  let modelCalls = 0
  let toolCalls = 0
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url === '/api/v1/internal/dsh/tools/execute') {
      toolCalls += 1
      const payload = await body(incoming)
      assert.equal(payload.name, 'workspace_list_files')
      assert.deepEqual(payload.arguments, { path: '/' })
      return { ok: true, content: 'a.xlsx', value: { files: ['a.xlsx'] } }
    }
    modelCalls += 1
    const payload = await body(incoming)
    if (modelCalls === 1) return toolStream('workspace_list_files', { path: '/' })
    assert(JSON.stringify(payload.messages).includes('a.xlsx'))
    return textStream('已找到文件')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({
    tools: [{
      name: 'workspace_list_files', description: '列出工作空间文件',
      input_schema: { type: 'object', properties: { path: { type: 'string' } } },
    }],
  }), event => events.push(event))
  assert.equal(modelCalls, 2)
  assert.equal(toolCalls, 1)
  assert(events.some(event => event.type === 'tool_call' && event.name === 'workspace_list_files'))
  assert(events.some(event => event.type === 'tool_result' && event.ok))
  assert(events.some(event => event.type === 'done' && event.text === '已找到文件'))
})

test('enforces the request step budget inside the model adapter', async () => {
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) return { ok: true, content: 'ok', value: { ok: true } }
    await body(incoming)
    return toolStream('loop_tool', {})
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({
    max_steps: 2,
    tools: [{ name: 'loop_tool', description: '继续', input_schema: { type: 'object', properties: {} } }],
  }), event => events.push(event))
  assert(
    events.some(event => event.type === 'error' && event.code === 'MAX_STEPS_EXCEEDED'),
    JSON.stringify(events),
  )
  assert(!events.some(event => event.type === 'done'))
})

test('keeps a hard safety ceiling above the platform admission limit', async () => {
  let releaseFirst!: () => void
  let firstEntered!: () => void
  const release = new Promise<void>(resolve => { releaseFirst = resolve })
  const entered = new Promise<void>(resolve => { firstEntered = resolve })
  const backendUrl = await fakeBackend(async incoming => {
    await body(incoming)
    firstEntered()
    await release
    return textStream('完成')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret', maxConcurrentRuns: 1 })
  await runtime.start()
  const firstEvents: RuntimeEvent[] = []
  const first = runtime.run(request({ run_id: 'run-first' }), event => firstEvents.push(event))
  await entered

  const rejected: RuntimeEvent[] = []
  await runtime.run(request({ run_id: 'run-second' }), event => rejected.push(event))
  assert(rejected.some(event => event.type === 'status' && event.status === 'busy'))
  assert(rejected.some(event => event.type === 'error' && event.code === 'RUNTIME_BUSY'))
  assert.equal(runtime.health().active_runs, 1)

  releaseFirst()
  await first
  assert(firstEvents.some(event => event.type === 'done'))
  assert.equal(runtime.health().active_runs, 0)
})

test('tracks agent disposal without holding the completed run open', async () => {
  const runtime = new DshRuntime({ backendUrl: 'http://127.0.0.1:1', serviceToken: 'secret' })
  let release!: () => void
  const draining = new Promise<void>(resolve => { release = resolve })
  const internals = runtime as unknown as {
    disposeInBackground: (handle: { dispose: () => Promise<void> }) => void
  }

  internals.disposeInBackground({ dispose: () => draining })

  assert.equal(runtime.health().pending_disposals, 1)
  release()
  await new Promise<void>(resolve => setImmediate(resolve))
  assert.equal(runtime.health().pending_disposals, 0)
})
