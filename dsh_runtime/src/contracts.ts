import type { ContentBlock, Message, StreamChunk } from '@deepseek-ai/dsh-llm'

export interface ToolSpec {
  name: string
  description: string
  input_schema: Record<string, unknown>
  /** Backend classification (workspace_file / platform_tool / skill / ...); informational for the runtime. */
  kind?: string
  /** Hard per-call deadline enforced by the runtime; the backend HTTP call is aborted when it elapses. */
  timeout_ms?: number
  /** Only an exact `true` lets the call overlap with sibling calls in one model step. */
  concurrency_safe?: boolean
  /** Model-facing text budget; longer tool results are truncated with a Chinese notice appended. */
  max_model_chars?: number
}

/** Loop-completion policy the backend attaches to a run (owned by DSH, not the Python bridge). */
export interface CompletionPolicy {
  require_file_output: boolean
  file_output_tools: string[]
  max_nudges: number
  nudge_text?: string
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
  completion_policy?: CompletionPolicy
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
  | {
    type: 'policy'
    action: 'continuation' | 'repeat_failure_block' | 'tool_timeout'
    tool?: string
    detail?: string
    nudge?: number
  }

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
