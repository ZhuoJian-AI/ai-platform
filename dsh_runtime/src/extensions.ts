import { createHash } from 'node:crypto'
import { execFile as execFileCallback } from 'node:child_process'
import { access, mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join, normalize, resolve, sep } from 'node:path'
import { pathToFileURL } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'

const execFile = promisify(execFileCallback)

export interface ReleaseManifest {
  schema_version?: number
  node_version?: string
  dsh_version?: string
  plugins?: Array<Record<string, unknown>>
  external_extensions?: Array<Record<string, unknown>>
  system_tools?: Array<Record<string, unknown>>
}

export interface ReleaseRequest {
  release_id: string
  checksum: string
  manifest: ReleaseManifest
}

export type ExternalToolHandler = (
  args: unknown,
  context: { signal: AbortSignal; runId: string; taskId: string },
) => unknown | Promise<unknown>

export interface LoadedExtensions {
  items: Array<{ slug: string; version: string; checksum: string; checks?: Record<string, unknown> }>
  tools: Map<string, ExternalToolHandler>
}

async function runDeclaredCheck(
  module: Record<string, unknown>, item: Record<string, unknown>, key: 'smoke_test' | 'health_check', ctx: Context,
): Promise<unknown> {
  const declaration = item[key]
  if (!declaration) return undefined
  const exportName = typeof declaration === 'string'
    ? declaration
    : declaration && typeof declaration === 'object'
      ? String((declaration as Record<string, unknown>).export ?? '')
      : ''
  const check = module[exportName]
  if (!exportName || typeof check !== 'function') throw new Error(`${item.slug} ${key} export is invalid`)
  let timer: NodeJS.Timeout | undefined
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${item.slug} ${key} timed out`)), 10_000)
    timer.unref()
  })
  let result: unknown
  try {
    result = await Promise.race([
      check({ context: ctx, config: item.default_config ?? {} }),
      timeout,
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
  if (result === false || (result && typeof result === 'object' && (result as Record<string, unknown>).ok === false)) {
    throw new Error(`${item.slug} ${key} failed`)
  }
  return result ?? { ok: true }
}

function canonicalManifest(manifest: ReleaseManifest): Record<string, unknown> {
  const copy = structuredClone(manifest) as Record<string, unknown>
  const external = (copy.external_extensions as Array<Record<string, unknown>> | undefined) ?? []
  for (const item of external) {
    delete item.artifact_url
    delete item.artifact_headers
  }
  return copy
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(',')}}`
  }
  return JSON.stringify(value)
}

export function verifyRelease(request: ReleaseRequest): void {
  if (!request.release_id || !/^[a-f0-9-]{16,64}$/i.test(request.release_id)) throw new Error('invalid release id')
  const checksum = createHash('sha256').update(stable(canonicalManifest(request.manifest))).digest('hex')
  if (checksum !== request.checksum) throw new Error('release manifest checksum mismatch')
  if (request.manifest.node_version && request.manifest.node_version !== '22.19.0') {
    throw new Error(`release requires Node ${request.manifest.node_version}; runtime is 22.19.0`)
  }
  if (request.manifest.dsh_version && request.manifest.dsh_version !== '0.1.0-rc.5') {
    throw new Error(`release requires DSH ${request.manifest.dsh_version}; runtime is 0.1.0-rc.5`)
  }
  const all = [...(request.manifest.plugins ?? []), ...(request.manifest.external_extensions ?? [])]
  const enabled = all.filter(item => item.enabled !== false)
  const coordinators = enabled.filter(item => {
    const capabilities = (item.capabilities ?? item.provides ?? []) as unknown[]
    return capabilities.includes('coordinator')
  })
  if (coordinators.length !== 1) throw new Error('release must enable exactly one coordinator')
  for (const slug of ['dsh-llm-runtime', 'dsh-session', 'dsh-system-prompt', 'dsh-tools', 'dsh-agent']) {
    if (!enabled.some(item => item.slug === slug)) throw new Error(`required core plugin is missing: ${slug}`)
  }
  for (const item of request.manifest.external_extensions ?? []) {
    if (item.enabled === false) continue
    if (!['runtime_plugin', 'system_tool'].includes(String(item.type))) throw new Error(`extension ${item.slug} needs an adapter`)
    if (!item.entry || !item.artifact_url || !item.artifact_sha256) throw new Error(`extension ${item.slug} is missing a verified artifact or entry`)
    if (!/^[a-f0-9]{64}$/.test(String(item.artifact_sha256))) throw new Error(`extension ${item.slug} has an invalid artifact checksum`)
    if (item.type === 'system_tool') {
      const tools = item.tools
      if (!Array.isArray(tools) || tools.length === 0) throw new Error(`system tool extension ${item.slug} declares no tools`)
      for (const tool of tools) {
        const value = tool as Record<string, unknown>
        if (!tool || typeof tool !== 'object'
          || typeof value.name !== 'string'
          || typeof value.description !== 'string'
          || !value.input_schema || typeof value.input_schema !== 'object'
          || !['low', 'medium', 'high', 'critical'].includes(String(value.risk_level))
          || !Array.isArray(value.required_platform_capabilities)
          || typeof value.side_effects !== 'boolean') {
          throw new Error(`system tool extension ${item.slug} has an invalid tool schema`)
        }
      }
    }
  }
}

async function packageRoot(root: string): Promise<string> {
  try { await access(join(root, 'package.json')); return root } catch { /* nested package */ }
  const directories = (await readdir(root, { withFileTypes: true })).filter(item => item.isDirectory())
  if (directories.length === 1 && directories[0]) {
    const nested = join(root, directories[0].name)
    await access(join(nested, 'package.json'))
    return nested
  }
  throw new Error('extension artifact has no package root')
}

async function materialize(item: Record<string, unknown>, cacheRoot: string): Promise<string> {
  const checksum = String(item.artifact_sha256)
  const target = join(cacheRoot, checksum)
  try { return await packageRoot(target) } catch { /* cache miss */ }
  const temporary = await mkdtemp(join(tmpdir(), `dsh-extension-${checksum.slice(0, 8)}-`))
  try {
    const response = await fetch(String(item.artifact_url), {
      headers: (item.artifact_headers as Record<string, string> | undefined) ?? {},
    })
    if (!response.ok || !response.body) throw new Error(`artifact download failed: ${response.status}`)
    const chunks: Uint8Array[] = []
    let size = 0
    for await (const chunk of response.body) {
      const value = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk)
      size += value.byteLength
      if (size > 100 * 1024 * 1024) throw new Error('extension artifact exceeds runtime cache limit')
      chunks.push(value)
    }
    const bytes = Buffer.concat(chunks)
    if (createHash('sha256').update(bytes).digest('hex') !== checksum) throw new Error('extension artifact checksum mismatch')
    const archive = join(temporary, 'artifact.tar.gz')
    const unpacked = join(temporary, 'unpacked')
    await writeFile(archive, bytes)
    await mkdir(unpacked)
    const { stdout } = await execFile('tar', ['-tzf', archive], { maxBuffer: 4 * 1024 * 1024, timeout: 30_000 })
    const paths = stdout.split(/\r?\n/).filter(Boolean)
    if (paths.length > 5000 || paths.some(path => {
      const clean = normalize(path).replaceAll('\\', '/')
      return clean.startsWith('../') || clean.startsWith('/') || clean.includes('/../')
    })) throw new Error('unsafe extension artifact paths')
    await execFile('tar', ['-xzf', archive, '-C', unpacked], { timeout: 60_000 })
    await mkdir(dirname(target), { recursive: true })
    try {
      await rename(unpacked, target)
    } catch (error) {
      // A concurrent validation may have populated the immutable checksum cache.
      // Reuse it only when it is a complete package; otherwise surface the original failure.
      try { return await packageRoot(target) } catch { throw error }
    }
    return await packageRoot(target)
  } finally {
    await rm(temporary, { recursive: true, force: true })
  }
}

export async function loadExternalExtensions(
  ctx: Context, manifest: ReleaseManifest, cacheRoot: string,
): Promise<LoadedExtensions> {
  const loaded: LoadedExtensions = { items: [], tools: new Map() }
  await mkdir(cacheRoot, { recursive: true })
  for (const item of manifest.external_extensions ?? []) {
    if (item.enabled === false) continue
    const root = await materialize(item, cacheRoot)
    const entry = resolve(root, String(item.entry))
    if (entry !== root && !entry.startsWith(`${root}${sep}`)) throw new Error(`unsafe entry for ${item.slug}`)
    await access(entry)
    const module = await import(`${pathToFileURL(entry).href}?sha=${String(item.artifact_sha256)}`) as Record<string, unknown>
    if (item.type === 'system_tool') {
      const factory = module.createTools ?? module[String(item.export_name ?? 'default')]
      const produced = typeof factory === 'function'
        ? await factory(item.default_config ?? {})
        : module.tools ?? factory
      const handlers = produced && typeof produced === 'object'
        ? produced as Record<string, unknown>
        : {}
      for (const tool of item.tools as Array<Record<string, unknown>>) {
        const name = String(tool.name)
        const handler = handlers[name]
        if (typeof handler !== 'function') throw new Error(`system tool ${name} has no exported handler`)
        if (loaded.tools.has(name)) throw new Error(`duplicate external system tool: ${name}`)
        loaded.tools.set(name, handler as ExternalToolHandler)
      }
    } else {
      const exported = module[String(item.export_name ?? 'default')]
      if (typeof exported !== 'function' && (typeof exported !== 'object' || exported === null)) {
        throw new Error(`extension ${item.slug} does not export a Cordis plugin`)
      }
      await ctx.plugin(exported as never, (item.default_config ?? {}) as never)
    }
    const checks: Record<string, unknown> = {}
    const smoke = await runDeclaredCheck(module, item, 'smoke_test', ctx)
    const health = await runDeclaredCheck(module, item, 'health_check', ctx)
    if (smoke !== undefined) checks.smoke_test = smoke
    if (health !== undefined) checks.health_check = health
    loaded.items.push({
      slug: String(item.slug), version: String(item.version ?? 'unknown'),
      checksum: String(item.artifact_sha256), checks,
    })
  }
  return loaded
}
