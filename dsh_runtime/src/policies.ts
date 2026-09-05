/**
 * Run-scoped loop policies implemented on DSH's own event pipeline:
 * repeat-failure guard, file-delivery tracking, continuation nudge, plus the
 * helpers the tool pipeline uses for hard timeouts and model-facing truncation.
 * Everything here is registered through the unpublished agent scope, so the
 * listeners are scope-filtered to one run and unwind with the agent.
 */
import type { Context } from '@deepseek-ai/cordis'
import { createUserMessage, type ContentBlock, type UserMessage } from '@deepseek-ai/dsh-llm'
import type { PostToolDecision } from '@deepseek-ai/dsh-tools'
import type { CompletionPolicy, RuntimeEvent } from './contracts.js'

/** `source.plugin` stamped on every user-role message this runtime injects. */
export const POLICY_PLUGIN = 'ai-platform-policy'

/** Capability-owned code carried by the tool deadline's `TimeoutReason`. */
export const TOOL_TIMEOUT_CODE = 'TOOL_TIMEOUT'

export const DEFAULT_NUDGE_TEXT =
  '请继续：上一步只加载了技能/读取了资料但还没有产出用户要求的文件。现在直接调用相应工具生成并保存文件，完成后再总结。'

const REPEAT_FAILURE_GUIDANCE =
  '[系统提示] 同一工具以相同参数反复失败，继续原样重试不会成功。请：'
  + '① 仔细阅读上一次的错误信息，修正参数（路径、格式、必填字段）；'
  + '② 若前置条件不满足（文件不存在、权限不足、依赖未就绪），先用其他工具补齐；'
  + '③ 仍无法完成时，向用户说明原因并给出可行的替代方案，不要声称已完成。'

export function repeatFailureFeedback(count: number): string {
  return `相同工具与参数已连续失败 ${count} 次，请改变参数或换一种方法，不要原样重试。`
}

export function toolTimeoutMessage(timeoutMs: number): string {
  return `工具执行超时（${TOOL_TIMEOUT_CODE}，${timeoutMs} ms）`
}

/** JSON with recursively sorted object keys, so argument order never defeats the repeat-failure key. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    const entries = Object.keys(record).sort().map(
      key => `${JSON.stringify(key)}:${stableStringify(record[key])}`,
    )
    return `{${entries.join(',')}}`
  }
  return JSON.stringify(value) ?? 'undefined'
}

export function failureKey(name: string, args: unknown): string {
  return `${name}:${stableStringify(args)}`
}

/** Build a plugin-sourced user message (nudges, guidance) that the loop appends to the model-visible history. */
export function pluginMessage(text: string): UserMessage {
  return createUserMessage({
    content: [{ type: 'text', text }],
    source: { kind: 'plugin', plugin: POLICY_PLUGIN, form: 'instructions' },
  })
}

/**
 * Truncate the text blocks of a tool result to `maxChars` and append a notice.
 * Returns `undefined` when nothing needs to change (the registry then keeps the content).
 */
export function truncateModelContent(content: readonly ContentBlock[], maxChars: number): ContentBlock[] | undefined {
  if (!Number.isFinite(maxChars) || maxChars <= 0) return undefined
  const total = content.reduce((sum, block) => block.type === 'text' ? sum + block.text.length : sum, 0)
  if (total <= maxChars) return undefined
  let remaining = Math.floor(maxChars)
  const truncated: ContentBlock[] = []
  for (const block of content) {
    if (block.type !== 'text') {
      truncated.push(block)
      continue
    }
    if (remaining <= 0) continue
    const slice = block.text.slice(0, remaining)
    remaining -= slice.length
    if (slice) truncated.push({ type: 'text', text: slice })
  }
  truncated.push({ type: 'text', text: `\n[工具结果已截断，共 ${total} 字符；如需更多内容请分页读取]` })
  return truncated
}

/** Settle with `work`, or reject as soon as `signal` aborts (whichever comes first). */
export function untilAborted<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  const abortError = (): Error => signal.reason instanceof Error ? signal.reason : new Error('aborted')
  if (signal.aborted) {
    work.catch(() => undefined)
    return Promise.reject(abortError())
  }
  return new Promise<T>((resolve, reject) => {
    const onAbort = (): void => reject(abortError())
    signal.addEventListener('abort', onAbort, { once: true })
    work.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort))
  })
}

export interface RunPolicyState {
  /** Tool name + normalised arguments of the most recent call. */
  lastKey?: string
  /** Consecutive failures of `lastKey`; reset by a success or a different key. */
  consecutiveFailures: number
  /** Whether any `completion_policy.file_output_tools` call succeeded in this run. */
  delivered: boolean
  /** Continuation nudges issued so far. */
  nudges: number
}

export interface RunPolicyOptions {
  completionPolicy?: CompletionPolicy
  emit: (event: RuntimeEvent) => void
  /** Whether one more model step still fits in the run's step budget. */
  canContinue: () => boolean
  /** Invoked right before a continuation nudge is steered in (the runtime resets its final-text buffer). */
  onContinuation?: () => void
}

/**
 * Register the run policies on the unpublished agent scope.
 *
 * - `tools/pre-execute`: a call whose key already failed twice in a row is denied
 *   before the backend is hit.
 * - `tools/post-execute`: counts consecutive identical failures; from the 2nd on the
 *   result is blocked with corrective feedback, and the 3rd/5th occurrence also
 *   attach guidance as `additionalContexts`.
 * - `tools/result`: a successful call to a file-output tool marks delivery.
 * - `agent/turn-stopping`: when file output is required but undelivered, steer a
 *   nudge into the next step (the loop then runs another step instead of closing).
 */
export function installRunPolicies(agentCtx: Context, options: RunPolicyOptions): RunPolicyState {
  const state: RunPolicyState = { consecutiveFailures: 0, delivered: false, nudges: 0 }
  const policy = options.completionPolicy
  const fileTools = new Set(policy?.file_output_tools ?? [])
  const deniedCalls = new Set<string>()

  agentCtx.on('tools/pre-execute', async (exec, next) => {
    const key = failureKey(exec.name, exec.arguments)
    if (key === state.lastKey && state.consecutiveFailures >= 2) {
      deniedCalls.add(String(exec.callId))
      return { kind: 'deny', reason: repeatFailureFeedback(state.consecutiveFailures + 1) }
    }
    return next()
  })

  agentCtx.on('tools/post-execute', async (exec, result, next) => {
    const key = failureKey(exec.name, exec.arguments)
    if (!result.isError) {
      state.lastKey = key
      state.consecutiveFailures = 0
      return next()
    }
    state.consecutiveFailures = key === state.lastKey ? state.consecutiveFailures + 1 : 1
    state.lastKey = key
    const count = state.consecutiveFailures
    if (count < 2) return next()
    const skipped = deniedCalls.delete(String(exec.callId))
    options.emit({
      type: 'policy', action: 'repeat_failure_block', tool: exec.name,
      detail: `consecutive_failures=${count}; backend_skipped=${skipped}`,
    })
    const decision: PostToolDecision = {
      kind: 'block',
      feedback: [{ type: 'text', text: repeatFailureFeedback(count) }],
    }
    if (count === 3 || count === 5) decision.additionalContexts = [pluginMessage(REPEAT_FAILURE_GUIDANCE)]
    return decision
  })

  agentCtx.on('tools/result', (exec, result) => {
    if (!result.isError && fileTools.has(exec.name)) state.delivered = true
    return undefined
  })

  agentCtx.on('agent/turn-stopping', payload => {
    if (!policy?.require_file_output || state.delivered) return
    if (payload.signal.aborted || state.nudges >= policy.max_nudges) return
    if (!options.canContinue()) return
    state.nudges += 1
    options.onContinuation?.()
    options.emit({
      type: 'policy', action: 'continuation', nudge: state.nudges,
      detail: 'file output required but no file_output_tools call succeeded',
    })
    payload.agent.steer(pluginMessage(policy.nudge_text?.trim() || DEFAULT_NUDGE_TEXT))
  })

  return state
}
