import assert from 'node:assert/strict'
import { createServer, type IncomingMessage, type Server } from 'node:http'
import { afterEach, test } from 'node:test'
import { DshRuntime, resolveMaxParallelToolCalls } from '../runtime.js'
import type { RunRequest, RuntimeEvent, ToolSpec } from '../contracts.js'
import { parseNdjson } from '../platform.js'
import { stableStringify, truncateModelContent } from '../policies.js'

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
  return multiToolStream([{ id: 'call-1', name, args }])
}

function multiToolStream(calls: Array<{ id: string; name: string; args: Record<string, unknown> }>): string {
  const events: unknown[] = []
  calls.forEach((call, index) => {
    const argumentsJson = JSON.stringify(call.args)
    events.push(
      { type: 'block-start', index, blockType: 'tool-call' },
      { type: 'tool-call-delta', index, id: call.id, name: call.name, argumentsDelta: argumentsJson },
      { type: 'block-end', index, block: { type: 'tool-call', id: call.id, name: call.name, arguments: argumentsJson } },
    )
  })
  events.push(
    { type: 'usage', usage: { inputTokens: 3, outputTokens: 2 } },
    { type: 'finish', reason: { kind: 'tool-calls' } },
  )
  return events.map(event => JSON.stringify(event)).join('\n') + '\n'
}

function tool(name: string, extra: Partial<ToolSpec> = {}): ToolSpec {
  return { name, description: `工具 ${name}`, input_schema: { type: 'object', properties: {} }, ...extra }
}

function policyEvents(events: RuntimeEvent[], action: string): Array<Extract<RuntimeEvent, { type: 'policy' }>> {
  return events.filter(
    (event): event is Extract<RuntimeEvent, { type: 'policy' }> => event.type === 'policy' && event.action === action,
  )
}

function toolResults(events: RuntimeEvent[]): Array<Extract<RuntimeEvent, { type: 'tool_result' }>> {
  return events.filter((event): event is Extract<RuntimeEvent, { type: 'tool_result' }> => event.type === 'tool_result')
}

const sleep = (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms))

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

test('surfaces a model stream that finishes with an error reason instead of an empty done', async () => {
  const backendUrl = await fakeBackend(async incoming => {
    await body(incoming)
    return JSON.stringify({ type: 'finish', reason: { kind: 'error', message: '上游模型超时', code: 'UPSTREAM_TIMEOUT' } }) + '\n'
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request(), event => events.push(event))
  const error = events.find(event => event.type === 'error')
  assert.deepEqual(error, { type: 'error', message: '上游模型超时', code: 'UPSTREAM_TIMEOUT' })
  assert(!events.some(event => event.type === 'done'), JSON.stringify(events))
  assert(!events.some(event => event.type === 'status' && event.status === 'completed'))
  assert.equal(runtime.health().active_runs, 0)
})

test('surfaces a failed model bridge response as an error event', async () => {
  const backendUrl = await fakeBackend(async () => { throw new Error('bridge down') })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request(), event => events.push(event))
  const error = events.find(event => event.type === 'error')
  assert(error && error.type === 'error', JSON.stringify(events))
  // `parseNdjson` surfaces the backend `detail` when the failure body is JSON; the status
  // fallback only applies to non-JSON proxy responses.
  assert.match(error.message, /^bridge down$|model bridge failed \(500\)/)
  assert(!events.some(event => event.type === 'done'))
})

test('treats a model stream that terminates without a finish line as an error', async () => {
  const backendUrl = await fakeBackend(async incoming => {
    await body(incoming)
    return [
      { type: 'block-start', index: 0, blockType: 'text' },
      { type: 'text-delta', index: 0, text: '半截' },
    ].map(event => JSON.stringify(event)).join('\n') + '\n'
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request(), event => events.push(event))
  const error = events.find(event => event.type === 'error')
  assert(error && error.type === 'error', JSON.stringify(events))
  assert.match(error.message, /ended without a finish event/)
  assert(!events.some(event => event.type === 'done'))
})

test('nudges the model once when the completion policy requires a file that was never produced', async () => {
  let modelCalls = 0
  const runTokens: unknown[] = []
  let thirdRequestSawNudge = false
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) {
      const payload = await body(incoming)
      assert.equal(payload.name, 'load_skill')
      return { ok: true, content: 'skill loaded', value: { ok: true, content: 'skill loaded' } }
    }
    modelCalls += 1
    const payload = await body(incoming)
    runTokens.push(payload.run_token)
    if (modelCalls === 1) return toolStream('load_skill', { name: 'excel' })
    if (modelCalls === 2) return textStream('技能已加载，任务完成。')
    thirdRequestSawNudge = JSON.stringify(payload.messages).includes('请继续生成文件')
    return textStream('已生成文件。')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({
    tools: [tool('load_skill', { kind: 'skill' }), tool('spreadsheet_tool', { kind: 'platform_tool' })],
    completion_policy: {
      require_file_output: true, file_output_tools: ['spreadsheet_tool'], max_nudges: 1, nudge_text: '请继续生成文件',
    },
  }), event => events.push(event))

  assert.equal(modelCalls, 3, JSON.stringify(events))
  assert(thirdRequestSawNudge, 'the third model request must carry the nudge message')
  const continuations = policyEvents(events, 'continuation')
  assert.equal(continuations.length, 1)
  assert.equal(continuations[0]?.nudge, 1)
  const done = events.find(event => event.type === 'done')
  assert(done && done.type === 'done', JSON.stringify(events))
  assert.equal(done.text, '已生成文件。', 'done.text is the post-nudge answer only')
  assert(!events.some(event => event.type === 'error'))
  assert.deepEqual([...new Set(runTokens)], ['opaque-token'], 'a nudge must not start a second run')
  assert.equal(events.filter(event => event.type === 'status' && event.status === 'running').length, 1)
  const continuationIndex = events.findIndex(event => event.type === 'policy' && event.action === 'continuation')
  const thirdPhaseIndex = events.findIndex(event => event.type === 'phase' && event.index === 2)
  assert(continuationIndex >= 0 && thirdPhaseIndex > continuationIndex, 'continuation precedes the next llm phase')
})

test('does not nudge when a file output tool already succeeded', async () => {
  let modelCalls = 0
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) {
      await body(incoming)
      return { ok: true, content: '/out/report.xlsx' }
    }
    modelCalls += 1
    await body(incoming)
    if (modelCalls === 1) return toolStream('spreadsheet_tool', { rows: 3 })
    return textStream('表格已生成')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({
    tools: [tool('spreadsheet_tool')],
    completion_policy: { require_file_output: true, file_output_tools: ['spreadsheet_tool'], max_nudges: 2 },
  }), event => events.push(event))
  assert.equal(modelCalls, 2)
  assert.equal(policyEvents(events, 'continuation').length, 0)
  assert(events.some(event => event.type === 'done' && event.text === '表格已生成'))
})

test('blocks the third identical tool failure before it reaches the backend', async () => {
  let modelCalls = 0
  let toolCalls = 0
  let fourthRequestSawGuidance = false
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) {
      toolCalls += 1
      await body(incoming)
      return { ok: false, content: '文件不存在' }
    }
    modelCalls += 1
    const payload = await body(incoming)
    // Same tool, same arguments (different key order must still count as identical).
    if (modelCalls === 1) return toolStream('read_file', { path: '/missing.txt', encoding: 'utf8' })
    if (modelCalls <= 3) return toolStream('read_file', { encoding: 'utf8', path: '/missing.txt' })
    // The 3rd occurrence attaches guidance as `additionalContexts`; it must reach the next request.
    fourthRequestSawGuidance = JSON.stringify(payload.messages).includes('[系统提示]')
    return textStream('放弃读取')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({ tools: [tool('read_file')] }), event => events.push(event))

  assert.equal(toolCalls, 2, 'the third identical call must not hit the backend')
  assert.equal(modelCalls, 4)
  const results = toolResults(events)
  assert.equal(results.length, 3)
  assert(results.every(result => !result.ok))
  assert.match(results[0]?.content ?? '', /文件不存在/)
  assert.match(results[1]?.content ?? '', /已连续失败 2 次/)
  assert.match(results[2]?.content ?? '', /已连续失败 3 次/)
  const blocks = policyEvents(events, 'repeat_failure_block')
  assert.equal(blocks.length, 2)
  assert.equal(blocks[0]?.tool, 'read_file')
  assert.match(blocks[1]?.detail ?? '', /backend_skipped=true/)
  assert(fourthRequestSawGuidance, 'guidance context must be appended after the third identical failure')
  assert(events.some(event => event.type === 'done' && event.text === '放弃读取'))
})

test('resets the repeat-failure counter on success or a different call', async () => {
  let modelCalls = 0
  let toolCalls = 0
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) {
      toolCalls += 1
      const payload = await body(incoming)
      const args = payload.arguments as { path?: string }
      return args.path === '/ok.txt' ? { ok: true, content: 'hello' } : { ok: false, content: '失败' }
    }
    modelCalls += 1
    await body(incoming)
    if (modelCalls === 1) return toolStream('read_file', { path: '/a.txt' })
    if (modelCalls === 2) return toolStream('read_file', { path: '/b.txt' })
    if (modelCalls === 3) return toolStream('read_file', { path: '/a.txt' })
    if (modelCalls === 4) return toolStream('read_file', { path: '/ok.txt' })
    if (modelCalls === 5) return toolStream('read_file', { path: '/a.txt' })
    return textStream('完成')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({ tools: [tool('read_file')] }), event => events.push(event))
  assert.equal(toolCalls, 5, 'alternating keys and a success never trigger the guard')
  assert.equal(policyEvents(events, 'repeat_failure_block').length, 0)
})

test('times out a tool whose backend never answers and reports TOOL_TIMEOUT', async () => {
  let modelCalls = 0
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) {
      await body(incoming)
      await new Promise<void>(() => undefined) // never answers; the aborted fetch releases the socket
      return { ok: true, content: 'unreachable' }
    }
    modelCalls += 1
    await body(incoming)
    if (modelCalls === 1) return toolStream('slow_tool', {})
    return textStream('超时后收尾')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  const started = Date.now()
  await runtime.run(request({ tools: [tool('slow_tool', { timeout_ms: 200 })] }), event => events.push(event))
  assert(Date.now() - started < 1500, 'the deadline must fire well before one second')
  const result = toolResults(events)[0]
  assert(result, JSON.stringify(events))
  assert.equal(result.ok, false)
  assert.match(result.content, /TOOL_TIMEOUT/)
  assert.match(result.content, /200 ms/)
  const timeouts = policyEvents(events, 'tool_timeout')
  assert.equal(timeouts.length, 1)
  assert.equal(timeouts[0]?.tool, 'slow_tool')
  assert(events.some(event => event.type === 'done' && event.text === '超时后收尾'))
})

async function parallelProbe(maxParallelToolCalls: number): Promise<Array<{ start: number; end: number }>> {
  const timings: Array<{ start: number; end: number }> = []
  let modelCalls = 0
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) {
      const start = Date.now()
      await body(incoming)
      await sleep(150)
      timings.push({ start, end: Date.now() })
      return { ok: true, content: 'ok', value: { ok: true } }
    }
    modelCalls += 1
    await body(incoming)
    if (modelCalls === 1) {
      return multiToolStream([
        { id: 'call-1', name: 'probe', args: { n: 1 } },
        { id: 'call-2', name: 'probe', args: { n: 2 } },
      ])
    }
    return textStream('完成')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret', maxParallelToolCalls })
  assert.equal(runtime.health().max_parallel_tool_calls, maxParallelToolCalls)
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({ tools: [tool('probe', { concurrency_safe: true })] }), event => events.push(event))
  assert.equal(toolResults(events).filter(result => result.ok).length, 2, JSON.stringify(events))
  assert(events.some(event => event.type === 'done'))
  return timings.sort((a, b) => a.start - b.start)
}

test('overlaps concurrency-safe tool calls when the parallel cap allows it', async () => {
  const parallel = await parallelProbe(2)
  assert.equal(parallel.length, 2)
  assert(parallel[1]!.start < parallel[0]!.end, `expected overlap, got ${JSON.stringify(parallel)}`)
})

test('serialises tool calls when the parallel cap is one', async () => {
  const serial = await parallelProbe(1)
  assert.equal(serial.length, 2)
  assert(serial[1]!.start >= serial[0]!.end, `expected serial execution, got ${JSON.stringify(serial)}`)
})

test('resolves the parallel tool-call cap from the environment with clamping', () => {
  assert.equal(resolveMaxParallelToolCalls(undefined, undefined), 4)
  assert.equal(resolveMaxParallelToolCalls(undefined, ''), 4)
  assert.equal(resolveMaxParallelToolCalls(undefined, '2'), 2)
  assert.equal(resolveMaxParallelToolCalls(undefined, '12'), 8)
  assert.equal(resolveMaxParallelToolCalls(undefined, '0'), 1)
  assert.equal(resolveMaxParallelToolCalls(undefined, 'abc'), 4)
  assert.equal(resolveMaxParallelToolCalls(3, '7'), 3)
})

test('emits a cancelled status when the turn is aborted by cancel()', async () => {
  let entered!: () => void
  const modelEntered = new Promise<void>(resolve => { entered = resolve })
  const backendUrl = await fakeBackend(async incoming => {
    await body(incoming)
    entered()
    await new Promise<void>(() => undefined) // the model stream hangs until the client aborts it
    return textStream('unreachable')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  const run = runtime.run(request({ run_id: 'run-cancel' }), event => events.push(event))
  await modelEntered
  assert.equal(runtime.cancel('run-cancel'), true)
  await run
  assert.equal(events.filter(event => event.type === 'status' && event.status === 'cancelled').length, 1)
  assert(!events.some(event => event.type === 'done'), JSON.stringify(events))
  assert(!events.some(event => event.type === 'status' && event.status === 'completed'))
  const error = events.find(event => event.type === 'error')
  assert(error && error.type === 'error')
  assert.equal(error.code, 'CANCELLED')
  assert.equal(runtime.health().active_runs, 0)
})

test('truncates long tool results to max_model_chars for the model', async () => {
  let modelCalls = 0
  const backendUrl = await fakeBackend(async incoming => {
    if (incoming.url?.endsWith('/tools/execute')) {
      await body(incoming)
      return { ok: true, content: 'x'.repeat(500) }
    }
    modelCalls += 1
    const payload = await body(incoming)
    if (modelCalls === 1) return toolStream('read_file', {})
    assert(JSON.stringify(payload.messages).includes('工具结果已截断'))
    return textStream('读完了')
  })
  const runtime = new DshRuntime({ backendUrl, serviceToken: 'secret' })
  await runtime.start()
  const events: RuntimeEvent[] = []
  await runtime.run(request({ tools: [tool('read_file', { max_model_chars: 100 })] }), event => events.push(event))
  const result = toolResults(events)[0]
  assert(result && result.ok)
  assert.match(result.content, /^\{"ok":true,"content":"x+\n\[工具结果已截断，共 \d+ 字符；如需更多内容请分页读取\]$/)
  assert.equal(result.content.indexOf('\n['), 100)
  assert(events.some(event => event.type === 'done' && event.text === '读完了'))
})

test('policy helpers normalise argument order and leave short content untouched', () => {
  assert.equal(stableStringify({ b: 1, a: [{ d: 2, c: 3 }] }), '{"a":[{"c":3,"d":2}],"b":1}')
  assert.equal(truncateModelContent([{ type: 'text', text: 'short' }], 100), undefined)
  const truncated = truncateModelContent([{ type: 'text', text: 'abcdef' }], 3)
  assert.deepEqual(truncated, [
    { type: 'text', text: 'abc' },
    { type: 'text', text: '\n[工具结果已截断，共 6 字符；如需更多内容请分页读取]' },
  ])
})
