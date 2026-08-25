import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { DshRuntime } from './runtime.js'
import type { RunRequest, RuntimeEvent } from './contracts.js'
import type { ReleaseRequest } from './extensions.js'

const port = Number(process.env.PORT ?? 8030)
const serviceToken = process.env.DSH_RUNTIME_TOKEN?.trim() ?? ''
const backendUrl = (process.env.AI_PLATFORM_BACKEND_URL ?? 'http://backend:8000').replace(/\/$/, '')
if (!serviceToken) throw new Error('DSH_RUNTIME_TOKEN is required')

const runtime = new DshRuntime({
  backendUrl, serviceToken,
  extensionCacheRoot: process.env.EXTENSION_CACHE_ROOT ?? '/extensions',
  maxConcurrentRuns: Number(process.env.DSH_RUNTIME_HARD_CONCURRENCY ?? 14),
})
await runtime.start()

function authorized(request: IncomingMessage): boolean {
  return request.headers.authorization === `Bearer ${serviceToken}`
}

async function jsonBody<T>(request: IncomingMessage): Promise<T> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of request) {
    const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    size += value.length
    if (size > 4 * 1024 * 1024) throw new Error('request body too large')
    chunks.push(value)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as T
}

function json(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
  response.end(JSON.stringify(body))
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`)
    if (request.method === 'GET' && url.pathname === '/health') {
      json(response, 200, runtime.health())
      return
    }
    if (!authorized(request)) {
      json(response, 401, { detail: 'unauthorized' })
      return
    }
    if (request.method === 'POST' && url.pathname === '/v1/runs') {
      const body = await jsonBody<RunRequest>(request)
      response.writeHead(200, {
        'content-type': 'application/x-ndjson; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      })
      const emit = (event: RuntimeEvent): void => { response.write(`${JSON.stringify(event)}\n`) }
      await runtime.run(body, emit)
      response.end()
      return
    }
    if (request.method === 'POST' && url.pathname === '/v1/extensions/validate') {
      json(response, 200, await runtime.validateRelease(await jsonBody<ReleaseRequest>(request)))
      return
    }
    if (request.method === 'POST' && url.pathname === '/v1/extensions/activate') {
      json(response, 200, await runtime.activateRelease(await jsonBody<ReleaseRequest>(request)))
      return
    }
    const match = /^\/v1\/runs\/([^/]+)\/cancel$/.exec(url.pathname)
    if (request.method === 'POST' && match?.[1]) {
      json(response, runtime.cancel(decodeURIComponent(match[1])) ? 202 : 404, { ok: true })
      return
    }
    json(response, 404, { detail: 'not found' })
  } catch (error) {
    json(response, 500, { detail: error instanceof Error ? error.message : String(error) })
  }
})

server.listen(port, '0.0.0.0')

for (const signal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(signal, () => server.close(() => process.exit(0)))
}
