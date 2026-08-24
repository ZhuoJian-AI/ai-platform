import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { buildExtension, type BuildRequest } from './builder.js'

const port = Number(process.env.PORT ?? 8040)
const token = process.env.EXTENSION_BUILDER_TOKEN?.trim() ?? ''
if (!token) throw new Error('EXTENSION_BUILDER_TOKEN is required')
let buildInProgress = false

async function body(request: IncomingMessage): Promise<BuildRequest> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of request) {
    const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    size += value.length
    if (size > 2 * 1024 * 1024) throw new Error('request body too large')
    chunks.push(value)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as BuildRequest
}

function json(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
  response.end(JSON.stringify(value))
}

createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`)
    if (request.method === 'GET' && url.pathname === '/health') {
      json(response, 200, { status: 'ok', node: process.version, pnpm: '11.7.0', max_seconds: 600 })
      return
    }
    if (request.headers.authorization !== `Bearer ${token}`) {
      json(response, 401, { detail: 'unauthorized' }); return
    }
    if (request.method === 'POST' && url.pathname === '/v1/builds') {
      if (buildInProgress) {
        json(response, 409, { detail: 'another isolated build is already running' }); return
      }
      buildInProgress = true
      try {
        json(response, 200, await buildExtension(await body(request)))
      } finally {
        buildInProgress = false
      }
      return
    }
    json(response, 404, { detail: 'not found' })
  } catch (error) {
    json(response, 400, { detail: error instanceof Error ? error.message : String(error) })
  }
}).listen(port, '0.0.0.0')
