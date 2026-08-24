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

async function parseNdjson(response: Response, signal?: AbortSignal): Promise<AsyncGenerator<unknown>> {
  async function* iterate(): AsyncGenerator<unknown> {
    if (!response.ok || !response.body) {
      throw new Error(`AI Platform model bridge failed (${response.status})`)
    }
    const reader = response.body.getReader()
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
    for await (const event of events) {
      if (!isStreamChunk(event)) throw new Error('invalid model stream event from AI Platform')
      yield event
    }
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
