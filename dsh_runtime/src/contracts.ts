import type { ContentBlock, Message, StreamChunk } from '@deepseek-ai/dsh-llm'

export interface ToolSpec {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

export interface RunRequest {
  run_id: string
  user_id?: string
  task_id: string
  run_token: string
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
  message: string
  system_prompt: string
  memory_context?: string
  model: { alias: string; max_tokens?: number | null; temperature?: number | null }
  exec_mode: 'ask' | 'plan' | 'craft'
  tools: ToolSpec[]
  max_steps: number
}

export type RuntimeEvent =
  | { type: 'status'; status: 'running' | 'completed' | 'cancelled' | 'busy' }
  | { type: 'phase'; phase: 'llm'; index: number }
  | { type: 'text_delta'; delta: string }
  | { type: 'tool_call'; id: string; name: string; arguments: string }
  | { type: 'tool_result'; id: string; name: string; content: string; ok: boolean }
  | { type: 'usage'; input_tokens: number; output_tokens: number }
  | { type: 'done'; text: string; steps: number; tool_calls: number }
  | { type: 'error'; message: string; code?: string }

export interface PlatformModelRequest {
  run_token: string
  messages: readonly Message[]
  system_prompt?: string
  tools?: readonly unknown[]
  temperature?: number
  max_tokens?: number
}

export interface PlatformToolResult {
  ok: boolean
  content: string
  value?: unknown
}

export function contentText(content: readonly ContentBlock[]): string {
  return content
    .filter((block): block is Extract<ContentBlock, { type: 'text' }> => block.type === 'text')
    .map(block => block.text)
    .join('')
}

export function isStreamChunk(value: unknown): value is StreamChunk {
  return Boolean(value && typeof value === 'object' && typeof (value as { type?: unknown }).type === 'string')
}
