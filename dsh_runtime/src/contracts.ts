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
  /**
   * `'ask'` marks a tool with external side effects: before every call the runtime asks the
   * platform for a user decision (`POST /api/v1/internal/dsh/approval/request`) and only an
   * `allowed-once` outcome lets the call run; anything else (rejected / cancelled / unavailable /
   * transport failure) denies the call fail-closed.  Irrelevant in ask/plan modes, which expose no tools.
   */
  approval?: 'ask'
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
    action:
      | 'continuation' | 'repeat_failure_block' | 'tool_timeout'
      | 'approval_requested' | 'approval_decided'
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

/** Body of `POST /api/v1/internal/dsh/approval/request`; the backend holds the request until the user decides. */
export interface PlatformApprovalRequest {
  run_token: string
  /** Runtime-minted UUID that pairs the `approval_requested` / `approval_decided` policy events with the backend record. */
  approval_id: string
  tool: string
  /** The exact tool call being decided (DSH `CallId`), when the asker had one. */
  call_id?: string
  reason: string
  /** Raw JSON arguments of the call, cut to at most 500 characters. */
  arguments_preview: string
  /** How long the backend may hold the request before answering `unavailable`. */
  timeout_ms: number
}

/** Backend answer; `outcome` is validated against the DSH `ApprovalOutcome` vocabulary (unknown -> `unavailable`). */
export interface PlatformApprovalResponse {
  outcome: string
  decided_by?: string
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
