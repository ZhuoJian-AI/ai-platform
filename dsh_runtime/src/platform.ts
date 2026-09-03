import type { GenerateOptions, LlmModelInfo, LlmProviderInfo, StreamChunk } from '@deepseek-ai/dsh-llm'
import { LlmAdapter } from '@deepseek-ai/dsh-llm'
import type { PlatformModelRequest, PlatformToolResult } from './contracts.js'
import { isStreamChunk } from './contracts.js'

export interface PlatformAdapterOptions {
  backendUrl: string
  serviceToken: string
  resolveRunToken(sessionId: string): string | undefined
  consumeModelStep(sessionId: string): void
}

export async function parseNdjson(response: Response, signal?: AbortSignal): Promise<AsyncGenerator<unknown>> {
  if (!response.ok) {
    let message = `AI Platform model bridge failed (${response.status})`
    try {
      const payload = await response.json() as { detail?: unknown }
      if (typeof payload.detail === 'string' && payload.detail.trim()) message = payload.detail.trim()
    } catch {
      // Keep the credential-safe status fallback for non-JSON proxy responses.
    }
    throw new Error(message)
  }
  if (!response.body) throw new Error('AI Platform model bridge returned an empty response body')

  async function* iterate(): AsyncGenerator<unknown> {
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (true) {
        if (signal?.aborted) throw new Error('aborted')
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let newline = buffer.indexOf('\n')
        while (newline >= 0) {
          const line = buffer.slice(0, newline).trim()
          buffer = buffer.slice(newline + 1)
          if (line) yield JSON.parse(line)
          newline = buffer.indexOf('\n')
        }
      }
      const tail = buffer.trim()
      if (tail) yield JSON.parse(tail)
    } finally {
      reader.releaseLock()
    }
  }
  return iterate()
}

export class PlatformLlmAdapter extends LlmAdapter {
  constructor(private readonly options: PlatformAdapterOptions) {
    super()
  }

  override providerInfo(provider: string): LlmProviderInfo {
    return { id: provider, name: 'AI Platform Model Gateway' }
  }

  override listModels(provider: string): Promise<readonly LlmModelInfo[]> {
    return Promise.resolve([{ provider, id: 'platform', name: 'AI Platform routed model' }])
  }

  async * stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const sessionId = String(options.sessionId ?? '')
    const runToken = this.options.resolveRunToken(sessionId)
    if (!runToken) throw new Error('unknown or expired DSH session')
    this.options.consumeModelStep(sessionId)
    const payload: PlatformModelRequest = {
      run_token: runToken,
      messages: options.messages,
      system_prompt: options.system,
      tools: options.tools,
      temperature: options.temperature,
      max_tokens: options.maxTokens,
    }
    const response = await fetch(`${this.options.backendUrl}/api/v1/internal/dsh/model/stream`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${this.options.serviceToken}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: options.signal,
    })
    const events = await parseNdjson(response, options.signal)
    let finished = false
    for await (const event of events) {
      if (!isStreamChunk(event)) throw new Error('invalid model stream event from AI Platform')
      if (event.type === 'finish') {
        finished = true
        const reason = event.reason as { kind?: string; failure?: unknown; message?: unknown; code?: unknown; error?: unknown }
        if (reason.kind === 'error' || reason.kind === 'aborted') {
          // The agent loop reads `reason.failure.message`; the backend may only send a
          // flat `{kind, message, code}` – normalise so the real cause reaches the user.
          const failure = reason.failure as { message?: unknown; code?: unknown } | undefined
          const message = typeof failure?.message === 'string' ? failure.message
            : typeof reason.message === 'string' ? reason.message
            : typeof reason.error === 'string' ? reason.error
            : 'AI Platform model stream reported an error'
          const code = typeof failure?.code === 'string' ? failure.code
            : typeof reason.code === 'string' ? reason.code
            : reason.kind === 'aborted' ? 'ABORTED' : 'MODEL_ERROR'
          yield { type: 'finish', reason: { kind: reason.kind, failure: { message, code } } }
          continue
        }
      }
      yield event
    }
    // A bridge that dies mid-response terminates the NDJSON body without a finish line;
    // without this the assembler defaults to `stop` and the run "completes" with nothing.
    if (!finished) throw new Error('AI Platform model stream ended without a finish event')
  }
}

export async function executePlatformTool(options: {
  backendUrl: string
  serviceToken: string
  runToken: string
  name: string
  arguments: unknown
  signal: AbortSignal
}): Promise<PlatformToolResult> {
  const response = await fetch(`${options.backendUrl}/api/v1/internal/dsh/tools/execute`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${options.serviceToken}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      run_token: options.runToken,
      name: options.name,
      arguments: options.arguments,
    }),
    signal: options.signal,
  })
  if (!response.ok) throw new Error(`AI Platform tool bridge failed (${response.status})`)
  return await response.json() as PlatformToolResult
}
