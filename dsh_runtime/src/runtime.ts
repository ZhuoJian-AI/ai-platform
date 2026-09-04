import { Context } from '@deepseek-ai/cordis'
import AgentRegistry from '@deepseek-ai/dsh-agent'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import LlmRuntime, { createUserMessage, type ContentBlock } from '@deepseek-ai/dsh-llm'
import SessionStore, { SessionId, type SessionEvent } from '@deepseek-ai/dsh-session'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import type { RunRequest, RuntimeEvent, ToolSpec } from './contracts.js'
import { contentText } from './contracts.js'
import { executePlatformTool, PlatformLlmAdapter } from './platform.js'
import {
  loadExternalExtensions, verifyRelease,
  type ExternalToolHandler, type ReleaseManifest, type ReleaseRequest,
} from './extensions.js'

interface ActiveRun {
  request: RunRequest
  sessionId: string
  modelSteps: number
  toolCalls: number
  finalText: string
  budgetExceeded: boolean
  /** Turn-level failure recorded from `turn/end` / `agent/error`; the loop swallows it, so we must surface it. */
  lastError?: { code: string; message: string }
  agent?: Awaited<ReturnType<Context['agents']['create']>>['agent']
}

type AgentHandle = Awaited<ReturnType<Context['agents']['create']>>

export interface RuntimeOptions {
  backendUrl: string
  serviceToken: string
  extensionCacheRoot?: string
  maxConcurrentRuns?: number
}

function renderHistory(messages: RunRequest['messages']): string {
  if (!messages.length) return ''
  return messages.map(item => `${item.role === 'user' ? '用户' : '助手'}：${item.content}`).join('\n\n')
}

function toolResultText(event: Extract<SessionEvent, { type: 'tool/result' }>): string {
  const result = event.data.message.content.find(block => block.type === 'tool-result')
  return result ? contentText(result.content) : contentText(event.data.message.content)
}

/** An error that carries a stable machine code into the terminal `error` event. */
class RunError extends Error {
  constructor(message: string, readonly code: string) {
    super(message)
  }
}

function errorMessageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function safeToolSchema(schema: Record<string, unknown>): Record<string, unknown> {
  return schema && typeof schema === 'object'
    ? schema
    : { type: 'object', properties: {}, additionalProperties: true }
}

export class DshRuntime {
  private ctx: Context | null = null
  private readonly activeByRun = new Map<string, ActiveRun>()
  private readonly activeBySession = new Map<string, ActiveRun>()
  private ready = false
  private releaseId = 'baseline'
  private releaseChecksum = 'builtin'
  private loadedExtensions: Array<{ slug: string; version: string; checksum: string }> = []
  private externalTools = new Map<string, ExternalToolHandler>()
  private restarts = 0
  private draining = false
  private activating = false
  private readonly pendingDisposals = new Set<Promise<void>>()

  constructor(private readonly options: RuntimeOptions) {}

  async start(): Promise<void> {
    if (this.ready) return
    const built = await this.buildContext()
    this.ctx = built.ctx
    this.loadedExtensions = built.loaded
    this.externalTools = built.tools
    this.ready = true
  }

  private async buildContext(manifest?: ReleaseManifest): Promise<{
    ctx: Context
    loaded: Array<{ slug: string; version: string; checksum: string }>
    tools: Map<string, ExternalToolHandler>
  }> {
    const ctx = new Context()
    try {
      const enabled = (slug: string): boolean => !manifest || (manifest.plugins ?? []).some(
        item => item.slug === slug && item.enabled !== false,
      )
      if (enabled('dsh-llm-runtime')) await ctx.plugin(LlmRuntime)
      if (enabled('dsh-session')) await ctx.plugin(SessionStore)
      if (enabled('dsh-system-prompt')) await ctx.plugin(SystemPrompt, {})
      if (enabled('dsh-tools')) await ctx.plugin(ToolRuntime, {})
      if (enabled('dsh-agent')) await ctx.plugin(AgentRegistry)
      if (enabled('dsh-agent-loop')) await ctx.plugin(AgentLoop, { agents: [], maxParallelToolCalls: 1 })
      const extensions = manifest
        ? await loadExternalExtensions(ctx, manifest, this.options.extensionCacheRoot ?? '/tmp/dsh-extensions')
        : { items: [], tools: new Map<string, ExternalToolHandler>() }
      ctx.llm.registerAdapter(['ai-platform'], new PlatformLlmAdapter({
        backendUrl: this.options.backendUrl,
        serviceToken: this.options.serviceToken,
        resolveRunToken: sessionId => this.activeBySession.get(sessionId)?.request.run_token,
        consumeModelStep: sessionId => {
          const run = this.activeBySession.get(sessionId)
          if (!run) throw new Error('run no longer active')
          run.modelSteps += 1
          if (run.modelSteps > run.request.max_steps) {
            run.budgetExceeded = true
            throw new Error('MAX_STEPS_EXCEEDED')
          }
        },
      }))
      return { ctx, loaded: extensions.items, tools: extensions.tools }
    } catch (error) {
      await ctx.fiber.dispose().catch(() => undefined)
      throw error
    }
  }

  health(): Record<string, unknown> {
    return {
      status: this.ready ? 'ok' : 'starting',
      runtime: 'dsh',
      dsh_version: '0.1.0-rc.5',
      node: process.version,
      active_runs: this.activeByRun.size,
      hard_concurrency_limit: this.options.maxConcurrentRuns ?? 14,
      draining: this.draining,
      max_parallel_tool_calls: 1,
      release_id: this.releaseId,
      release_checksum: this.releaseChecksum,
      loaded_extensions: this.loadedExtensions,
      runtime_restarts: this.restarts,
      pending_disposals: this.pendingDisposals.size,
    }
  }

  private disposeInBackground(handle: AgentHandle): void {
    let disposal: Promise<void>
    disposal = Promise.resolve()
      .then(() => handle.dispose())
      .catch(error => {
        console.warn(`agent disposal failed: ${error instanceof Error ? error.message : String(error)}`)
      })
      .finally(() => this.pendingDisposals.delete(disposal))
    this.pendingDisposals.add(disposal)
  }

  async validateRelease(request: ReleaseRequest): Promise<Record<string, unknown>> {
    verifyRelease(request)
    const built = await this.buildContext(request.manifest)
    try {
      return { ok: true, release_id: request.release_id, loaded_extensions: built.loaded }
    } finally {
      await built.ctx.fiber.dispose().catch(() => undefined)
    }
  }

  async activateRelease(request: ReleaseRequest): Promise<Record<string, unknown>> {
    if (this.activating) throw new Error('another release activation is already in progress')
    verifyRelease(request)
    this.activating = true
    this.draining = true
    try {
      const deadline = Date.now() + 30_000
      while (this.activeByRun.size && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 100))
      }
      if (this.activeByRun.size) throw new Error('runtime drain timed out; current release remains active')
      const built = await this.buildContext(request.manifest)
      const previous = this.ctx
      this.ctx = built.ctx
      this.releaseId = request.release_id
      this.releaseChecksum = request.checksum
      this.loadedExtensions = built.loaded
      this.externalTools = built.tools
      this.restarts += 1
      await previous?.fiber.dispose().catch(() => undefined)
      return { ok: true, release_id: this.releaseId, checksum: this.releaseChecksum, health: this.health() }
    } finally {
      this.draining = false
      this.activating = false
    }
  }

  async run(request: RunRequest, emit: (event: RuntimeEvent) => void): Promise<void> {
    if (!this.ready) throw new Error('runtime not ready')
    if (this.draining) throw new Error('runtime is draining for a reviewed extension release')
    if (this.activeByRun.has(request.run_id)) throw new Error('run already active')
    if (this.activeByRun.size >= (this.options.maxConcurrentRuns ?? 14)) {
      emit({ type: 'status', status: 'busy' })
      emit({
        type: 'error', code: 'RUNTIME_BUSY',
        message: 'DSH Runtime is busy; retry after queued runs finish',
      })
      return
    }
    if (!Number.isInteger(request.max_steps) || request.max_steps < 1 || request.max_steps > 64) {
      throw new Error('max_steps must be between 1 and 64')
    }
    if (request.exec_mode !== 'craft' && request.tools.length) {
      throw new Error(`${request.exec_mode} mode cannot expose tools`)
    }

    const sessionId = `platform-${request.run_id}`
    const active: ActiveRun = {
      request, sessionId, modelSteps: 0, toolCalls: 0, finalText: '', budgetExceeded: false,
    }
    this.activeByRun.set(request.run_id, active)
    this.activeBySession.set(sessionId, active)
    const ctx = this.ctx
    if (!ctx) throw new Error('runtime context is unavailable')
    const listener = ctx.on('session/event', (session, event) => {
      if (String(session.id) !== sessionId) return
      if (event.type === 'step/start') {
        emit({ type: 'phase', phase: 'llm', index: event.data.step - 1 })
      } else if (event.type === 'assistant/chunk' && event.data.chunk.type === 'text-delta') {
        emit({ type: 'text_delta', delta: event.data.chunk.text })
      } else if (event.type === 'assistant/message') {
        active.finalText += contentText(event.data.message.content)
        const usage = event.data.usage
        if (usage) emit({
          type: 'usage',
          input_tokens: usage.inputTokens ?? 0,
          output_tokens: usage.outputTokens ?? 0,
        })
      } else if (event.type === 'tool/call') {
        active.toolCalls += 1
        emit({
          type: 'tool_call', id: String(event.data.callId), name: event.data.name,
          arguments: event.data.arguments,
        })
      } else if (event.type === 'tool/result') {
        const result = event.data.message.content.find(block => block.type === 'tool-result')
        if (!result) return
        const call = [...session.events]
          .reverse()
          .find(item => item.type === 'tool/call' && item.data.callId === result.toolCallId)
        emit({
          type: 'tool_result', id: String(result.toolCallId),
          name: call?.type === 'tool/call' ? call.data.name : 'tool',
          content: toolResultText(event), ok: !result.isError,
        })
      } else if (event.type === 'turn/end' && event.data.reason.kind === 'error') {
        // The agent loop's driver (`kick`) swallows turn exceptions, so `whenIdle()`
        // resolves normally after an LLM/adapter failure.  Record it here so the run
        // ends with a real `error` instead of an empty `done`.
        active.lastError = { code: event.data.reason.error.code, message: event.data.reason.error.message }
      }
    })
    const errorListener = ctx.on('agent/error', payload => {
      if (String(payload.agent.id) !== sessionId || active.lastError) return
      active.lastError = { code: 'AGENT_ERROR', message: errorMessageOf(payload.error) }
    })

    let handle: AgentHandle | undefined
    try {
      emit({ type: 'status', status: 'running' })
      handle = await ctx.agents.create({
        sessionId: SessionId(sessionId),
        agentOptions: {
          provider: 'ai-platform',
          model: request.model.alias || 'default',
          maxTokens: request.model.max_tokens ?? undefined,
        },
        setup: agentCtx => {
          agentCtx.systemPrompt.section({
            name: 'ai-platform-policy', order: 10, text: request.system_prompt,
          })
          const history = renderHistory(request.messages)
          if (history) agentCtx.systemPrompt.context({
            name: 'task-history', order: 20,
            text: `[任务历史：PostgreSQL 是事实源]\n${history}`,
          })
          if (request.memory_context) agentCtx.systemPrompt.context({
            name: 'long-term-memory', order: 30, text: request.memory_context,
          })
          for (const spec of request.tools) this.registerTool(agentCtx, active, spec)
        },
      })
      active.agent = handle.agent
      handle.agent.followup(createUserMessage({
        content: [{ type: 'text', text: request.message }],
        source: { kind: 'user' },
      }))
      await handle.agent.whenIdle()
      if (active.budgetExceeded) throw new Error('MAX_STEPS_EXCEEDED')
      if (active.lastError) throw new RunError(active.lastError.message, active.lastError.code)
      emit({ type: 'status', status: 'completed' })
      emit({
        type: 'done', text: active.finalText, steps: active.modelSteps, tool_calls: active.toolCalls,
      })
    } catch (error) {
      const message = errorMessageOf(error)
      const cancelled = message === 'cancelled' || message.toLowerCase().includes('abort')
      if (cancelled) emit({ type: 'status', status: 'cancelled' })
      const code = error instanceof RunError ? error.code : message === 'MAX_STEPS_EXCEEDED' ? message : undefined
      emit({ type: 'error', message, code })
    } finally {
      listener()
      errorListener()
      this.activeByRun.delete(request.run_id)
      this.activeBySession.delete(sessionId)
      // The terminal event is the request boundary.  DSH's lifecycle disposal
      // can drain internal continuations for much longer and must not hold the
      // NDJSON response or the platform admission slot open.
      if (handle) this.disposeInBackground(handle)
    }
  }

  cancel(runId: string): boolean {
    const run = this.activeByRun.get(runId)
    if (!run?.agent) return false
    run.agent.cancel({ kind: 'user' })
    return true
  }

  private registerTool(agentCtx: Context, active: ActiveRun, spec: ToolSpec): void {
    agentCtx.tools.register({
      name: spec.name,
      description: spec.description,
      parameters: safeToolSchema(spec.input_schema),
      output: {
        schema: {},
        render: (_args, value): ContentBlock[] => [{
          type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value),
        }],
      },
      execute: async (args, exec) => {
        const localHandler = this.externalTools.get(spec.name)
        if (localHandler) {
          return await localHandler(args, {
            signal: exec.signal,
            runId: active.request.run_id,
            taskId: active.request.task_id,
            invokePlatformTool: async (name, bridgeArgs) => {
              const result = await executePlatformTool({
                backendUrl: this.options.backendUrl,
                serviceToken: this.options.serviceToken,
                runToken: active.request.run_token,
                name,
                arguments: bridgeArgs,
                signal: exec.signal,
              })
              if (!result.ok) throw new Error(result.content || `platform bridge tool ${name} failed`)
              return result.value ?? { ok: true, content: result.content }
            },
          })
        }
        const result = await executePlatformTool({
          backendUrl: this.options.backendUrl,
          serviceToken: this.options.serviceToken,
          runToken: active.request.run_token,
          name: spec.name,
          arguments: args,
          signal: exec.signal,
        })
        if (!result.ok) throw new Error(result.content || `tool ${spec.name} failed`)
        return result.value ?? { ok: true, content: result.content }
      },
    })
  }
}
