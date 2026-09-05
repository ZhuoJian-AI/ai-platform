import { spawn } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { access, mkdir, mkdtemp, readFile, readdir, readlink, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join, normalize, resolve, sep } from 'node:path'
import { satisfies } from 'semver'

const MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
const MAX_UNPACKED_BYTES = 250 * 1024 * 1024
const MAX_ENTRIES = 5000
const MAX_COMMAND_OUTPUT_BYTES = 8 * 1024 * 1024

export interface BuildRequest {
  source_type: 'npm' | 'github' | 'archive'
  locator: string
  version?: string | null
  archive_url?: string
  archive_headers?: Record<string, string>
}

function safeRef(value: string): string {
  if (value.startsWith('-') || !/^[A-Za-z0-9._/@+-]{1,255}$/.test(value)) {
    throw new Error('unsafe package version or Git ref')
  }
  return value
}

async function run(file: string, args: string[], cwd?: string, timeout = 10 * 60_000) {
  const childEnv = Object.fromEntries(
    [
      'PATH', 'PNPM_HOME', 'LANG', 'LC_ALL', 'TZ',
      'NPM_CONFIG_REGISTRY', 'npm_config_registry',
    ]
      .map(key => [key, process.env[key]])
      .filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
  )
  childEnv.HOME = '/tmp/builder-home'
  childEnv.CI = 'true'
  return new Promise<{ stdout: string; stderr: string }>((resolvePromise, rejectPromise) => {
    const child = spawn(file, args, {
      cwd,
      detached: true,
      env: childEnv,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const stdout: Buffer[] = []
    const stderr: Buffer[] = []
    let outputBytes = 0
    let settled = false

    const killGroup = () => {
      if (!child.pid) return
      try { process.kill(-child.pid, 'SIGKILL') } catch { /* already stopped */ }
    }
    const fail = (error: Error) => {
      if (settled) return
      settled = true
      killGroup()
      rejectPromise(error)
    }
    const append = (target: Buffer[], chunk: Buffer) => {
      outputBytes += chunk.byteLength
      if (outputBytes > MAX_COMMAND_OUTPUT_BYTES) {
        fail(new Error(`command output exceeded ${MAX_COMMAND_OUTPUT_BYTES} bytes`))
        return
      }
      target.push(chunk)
    }
    child.stdout?.on('data', (chunk: Buffer) => append(stdout, chunk))
    child.stderr?.on('data', (chunk: Buffer) => append(stderr, chunk))
    child.on('error', fail)
    const timer = setTimeout(() => fail(new Error(`command timed out after ${timeout}ms`)), timeout)
    timer.unref()
    child.on('close', (code, signal) => {
      clearTimeout(timer)
      killGroup() // also removes detached grandchildren left by package scripts
      if (settled) return
      settled = true
      const stdoutText = Buffer.concat(stdout).toString('utf8')
      const stderrText = Buffer.concat(stderr).toString('utf8')
      if (code === 0) resolvePromise({ stdout: stdoutText, stderr: stderrText })
      else rejectPromise(new Error(`${file} exited with ${code ?? signal}: ${stderrText.slice(-4000)}`))
    })
  })
}

async function exists(path: string): Promise<boolean> {
  try { await access(path); return true } catch { return false }
}

async function uploadArtifact(bytes: Buffer, sha256: string): Promise<string> {
  const backend = (process.env.AI_PLATFORM_BACKEND_URL || '').replace(/\/$/, '')
  const token = process.env.EXTENSION_BUILDER_TOKEN || ''
  if (!backend || !token) throw new Error('artifact upload callback is not configured')
  const signed = await fetch(`${backend}/api/v1/platform/extensions/internal/artifacts/sign`, {
    method: 'POST',
    headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      filename: `platform-extension-${sha256.slice(0, 16)}.tar.gz`,
      size_bytes: bytes.byteLength,
      sha256,
    }),
  })
  if (!signed.ok) throw new Error(`artifact signing failed (${signed.status})`)
  const payload = await signed.json() as {
    url: string; headers?: Record<string, string>; content_ref: string
  }
  const body = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
  const uploaded = await fetch(payload.url, {
    method: 'PUT',
    headers: payload.headers ?? {},
    body,
  })
  if (!uploaded.ok) throw new Error(`artifact upload failed (${uploaded.status})`)
  return payload.content_ref
}

async function directorySize(root: string): Promise<{ bytes: number; entries: number }> {
  let bytes = 0
  let entries = 0
  const visit = async (path: string): Promise<void> => {
    for (const item of await readdir(path, { withFileTypes: true })) {
      entries += 1
      if (entries > MAX_ENTRIES) throw new Error('archive contains too many entries')
      const target = join(path, item.name)
      if (item.isSymbolicLink()) {
        const linked = resolve(dirname(target), await readlink(target))
        if (linked !== root && !linked.startsWith(`${root}${sep}`)) {
          throw new Error('symbolic link escapes the extension package')
        }
        continue
      }
      if (item.isDirectory()) await visit(target)
      else if (item.isFile()) {
        bytes += (await stat(target)).size
        if (bytes > MAX_UNPACKED_BYTES) throw new Error('unpacked extension exceeds size limit')
      }
    }
  }
  await visit(root)
  return { bytes, entries }
}

async function packageRoot(root: string): Promise<string> {
  if (await exists(join(root, 'package.json'))) return root
  const entries = (await readdir(root, { withFileTypes: true })).filter(item => item.name !== '__MACOSX')
  if (entries.length === 1 && entries[0]?.isDirectory()) {
    const nested = join(root, entries[0].name)
    if (await exists(join(nested, 'package.json'))) return nested
  }
  throw new Error('package.json was not found at the extension root')
}

async function acquire(request: BuildRequest, root: string): Promise<{ packageRoot: string; commitSha?: string }> {
  const source = join(root, 'source')
  await mkdir(source, { recursive: true })
  if (request.source_type === 'npm') {
    const spec = `${safeRef(request.locator)}@${safeRef(request.version || '')}`
    const downloads = join(root, 'downloads')
    await mkdir(downloads)
    await run('pnpm', ['pack', spec, '--pack-destination', downloads], root)
    const archive = (await readdir(downloads)).find(name => name.endsWith('.tgz'))
    if (!archive) throw new Error('npm package did not produce an archive')
    await run('tar', ['-xzf', join(downloads, archive), '-C', source])
    return { packageRoot: await packageRoot(source) }
  }
  if (request.source_type === 'github') {
    if (!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/.test(request.locator)) {
      throw new Error('only canonical github.com repository URLs are accepted')
    }
    const repository = join(source, 'repository')
    await run('git', ['clone', '--filter=blob:none', '--no-checkout', request.locator, repository], root)
    await run('git', ['checkout', '--detach', safeRef(request.version || '')], repository)
    const { stdout } = await run('git', ['rev-parse', 'HEAD'], repository)
    return { packageRoot: await packageRoot(repository), commitSha: stdout.trim() }
  }
  if (!request.archive_url) throw new Error('archive_url is required')
  const response = await fetch(request.archive_url, { headers: request.archive_headers })
  if (!response.ok || !response.body) throw new Error(`archive download failed: ${response.status}`)
  const declared = Number(response.headers.get('content-length') || 0)
  if (declared > MAX_ARCHIVE_BYTES) throw new Error('archive exceeds compressed size limit')
  const chunks: Uint8Array[] = []
  let total = 0
  for await (const chunk of response.body) {
    const value = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk)
    total += value.byteLength
    if (total > MAX_ARCHIVE_BYTES) throw new Error('archive exceeds compressed size limit')
    chunks.push(value)
  }
  const archive = join(root, 'source.zip')
  await writeFile(archive, Buffer.concat(chunks))
  const { stdout } = await run('unzip', ['-Z1', archive])
  const names = stdout.split(/\r?\n/).filter(Boolean)
  if (names.length > MAX_ENTRIES || names.some(name => {
    const cleaned = normalize(name).replaceAll('\\', '/')
    return cleaned.startsWith('../') || cleaned.startsWith('/') || cleaned.includes('/../')
  })) throw new Error('unsafe ZIP paths or too many entries')
  await run('unzip', ['-q', archive, '-d', source])
  return { packageRoot: await packageRoot(source) }
}

function entryFromPackage(pkg: Record<string, unknown>): string | null {
  const exportsValue = pkg.exports
  if (typeof exportsValue === 'string') return exportsValue
  if (exportsValue && typeof exportsValue === 'object') {
    const root = (exportsValue as Record<string, unknown>)['.'] ?? exportsValue
    if (typeof root === 'string') return root
    if (root && typeof root === 'object') {
      const values = root as Record<string, unknown>
      for (const key of ['import', 'default', 'require']) if (typeof values[key] === 'string') return values[key] as string
    }
  }
  for (const key of ['module', 'main']) if (typeof pkg[key] === 'string') return pkg[key] as string
  return null
}

export function safeEntry(root: string, entry: unknown): string | null {
  if (typeof entry !== 'string' || !entry.trim() || entry.includes('\0')) return null
  const target = resolve(root, entry)
  if (target !== root && !target.startsWith(`${root}${sep}`)) return null
  return target
}

export function validSystemTools(value: unknown): boolean {
  if (!Array.isArray(value) || value.length === 0) return false
  return value.every(item => {
    if (!item || typeof item !== 'object') return false
    const tool = item as Record<string, unknown>
    return typeof tool.name === 'string'
      && typeof tool.description === 'string'
      && !!tool.input_schema && typeof tool.input_schema === 'object'
      && ['low', 'medium', 'high', 'critical'].includes(String(tool.risk_level))
      && Array.isArray(tool.required_platform_capabilities)
      && typeof tool.side_effects === 'boolean'
  })
}

export function compatibleNode(engine: unknown): boolean {
  if (typeof engine !== 'string' || !engine.trim()) return true
  try {
    return satisfies('22.19.0', engine, { includePrerelease: true })
  } catch {
    return false
  }
}

export function compatibleDsh(requirement: unknown): boolean {
  if (typeof requirement !== 'string' || !requirement.trim()) return true
  try {
    return satisfies('0.1.0-rc.8', requirement, { includePrerelease: true })
  } catch {
    return false
  }
}

export function resolveExtensionSlot(
  kind: string,
  explicit: Record<string, unknown> | null,
): { layer: string; operation: 'add' | 'replace'; warning: string | null } {
  const provides = Array.isArray(explicit?.provides) ? explicit.provides : []
  const inferredLayer = provides.includes('coordinator') ? 'coordinator' : kind === 'system_tool' ? 'system_tool' : 'runtime'
  const allowedLayers = new Set([
    'coordinator', 'runtime', 'memory_context', 'rag_strategy', 'system_tool',
    'model_adapter', 'hook_guard', 'skill_mcp', 'ui_plugin', 'library', 'unknown',
  ])
  const requestedLayer = typeof explicit?.layer === 'string' ? explicit.layer : inferredLayer
  const layer = allowedLayers.has(requestedLayer) ? requestedLayer : 'unknown'
  const requestedOperation = explicit?.operation === 'replace' ? 'replace' : 'add'
  const operation = layer === 'coordinator' ? 'replace' : requestedOperation
  let warning = requestedLayer !== layer ? `未知扩展层：${requestedLayer}` : null
  if (!warning && operation === 'replace' && !['coordinator', 'memory_context', 'rag_strategy', 'model_adapter'].includes(layer)) {
    warning = `扩展层 ${layer} 不支持替换操作`
  }
  return { layer, operation, warning }
}

export async function buildExtension(request: BuildRequest): Promise<Record<string, unknown>> {
  const work = await mkdtemp(join(tmpdir(), `extension-${randomUUID()}-`))
  try {
    const acquired = await acquire(request, work)
    const root = acquired.packageRoot
    // Validate the source tree before reading manifests or running any package script.
    await directorySize(root)
    const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8')) as Record<string, unknown>
    const platformManifestPath = join(root, 'ai-platform.extension.json')
    const explicit = await exists(platformManifestPath)
      ? JSON.parse(await readFile(platformManifestPath, 'utf8')) as Record<string, unknown>
      : null
    const dependencies = {
      ...((pkg.dependencies as Record<string, string> | undefined) ?? {}),
      ...((pkg.peerDependencies as Record<string, string> | undefined) ?? {}),
    }
    const entry = typeof explicit?.entry === 'string' ? explicit.entry : entryFromPackage(pkg)
    const entryTarget = safeEntry(root, entry)
    const inferredDsh = Object.keys(dependencies)
      .some(name => name === '@deepseek-ai/cordis' || name.startsWith('@deepseek-ai/dsh-'))
    const inferredDshRequirement = Object.entries(dependencies)
      .find(([name]) => name.startsWith('@deepseek-ai/dsh-'))?.[1]
    const dshRequirement = explicit?.dsh_version ?? inferredDshRequirement ?? null
    const kind = explicit?.type === 'runtime_plugin' || explicit?.type === 'system_tool'
      ? explicit.type
      : inferredDsh && entry
        ? 'runtime_plugin'
        : 'adapter_required'
    const nodeEngine = (pkg.engines as Record<string, unknown> | undefined)?.node
    const warnings: string[] = []
    if (!explicit) warnings.push('未提供 ai-platform.extension.json，入口与类型来自 package.json 推断')
    if (kind === 'adapter_required') warnings.push('普通 Node 库、MCP 服务或 CLI 不能直接装配为 DSH 插件')
    if (!entry) warnings.push('无法确认插件入口')
    else if (!entryTarget) warnings.push('插件入口越出包目录或格式无效')
    if (kind === 'runtime_plugin' && explicit && !Array.isArray(explicit.provides)) {
      warnings.push('Runtime 插件的平台清单必须声明 provides 能力')
    } else if (kind === 'runtime_plugin' && !explicit) {
      warnings.push('已从 DSH/Cordis 依赖推断 Runtime 插件，能力声明为空')
    }
    if (kind === 'system_tool' && !validSystemTools(explicit?.tools)) {
      warnings.push('系统工具必须声明工具 Schema、风险等级和外部副作用')
    }
    if (!compatibleNode(nodeEngine)) warnings.push(`Node 版本要求 ${String(nodeEngine)} 与平台 Node 22.19 不兼容`)
    if (!compatibleDsh(dshRequirement)) {
      warnings.push(`DSH 版本要求 ${String(dshRequirement)} 与平台 DSH 0.1.0-rc.8 不兼容`)
    }
    const provides = Array.isArray(explicit?.provides) ? explicit.provides : []
    const slot = resolveExtensionSlot(kind, explicit)
    const { layer, operation } = slot
    if (slot.warning) warnings.push(slot.warning)

    if (await exists(join(root, 'pnpm-lock.yaml'))) {
      await run('pnpm', ['install', '--frozen-lockfile', '--ignore-scripts'], root)
    } else {
      await run('pnpm', ['install', '--ignore-scripts'], root)
      warnings.push('来源未包含 pnpm-lock.yaml，Builder 已生成精确锁文件')
    }
    const scripts = (pkg.scripts as Record<string, string> | undefined) ?? {}
    if (scripts.build) await run('pnpm', ['run', 'build'], root)
    await run('pnpm', ['prune', '--prod', '--ignore-scripts'], root)
    if (entryTarget && !await exists(entryTarget)) warnings.push(`入口文件不存在：${entry}`)
    const stats = await directorySize(root)
    const manifest = {
      name: explicit?.name ?? pkg.name ?? basename(root),
      slug: explicit?.slug ?? String(pkg.name ?? basename(root)).replace(/^@/, '').replaceAll('/', '-'),
      version: explicit?.version ?? pkg.version ?? request.version ?? '0.0.0',
      description: explicit?.description ?? pkg.description ?? '',
      type: kind,
      layer,
      operation,
      entry,
      export_name: explicit?.export_name ?? 'default',
      provides,
      requires: explicit?.requires ?? [],
      conflicts: explicit?.conflicts ?? [],
      config_schema: explicit?.config_schema ?? {},
      default_config: explicit?.default_config ?? {},
      smoke_test: explicit?.smoke_test ?? null,
      health_check: explicit?.health_check ?? null,
      tools: explicit?.tools ?? [],
      node_engine: nodeEngine ?? null,
      dsh_version: dshRequirement,
      runtime_requirements: { node: nodeEngine ?? null, dsh: dshRequirement },
    }
    const protocolValid = kind === 'runtime_plugin'
      ? (explicit ? Array.isArray(explicit.provides) : inferredDsh)
      : kind === 'system_tool' && validSystemTools(explicit?.tools)
    const publishable = (kind === 'runtime_plugin' || kind === 'system_tool')
      && Boolean(entryTarget) && await exists(entryTarget as string)
      && compatibleNode(nodeEngine) && compatibleDsh(dshRequirement) && protocolValid
    const artifact = join(work, 'artifact.tar.gz')
    await run('tar', ['-czf', artifact, '-C', dirname(root), basename(root)])
    const bytes = await readFile(artifact)
    const sha256 = createHash('sha256').update(bytes).digest('hex')
    const artifactRef = await uploadArtifact(bytes, sha256)
    return {
      publishable,
      manifest,
      resolved_version: String(pkg.version ?? request.version ?? ''),
      commit_sha: acquired.commitSha,
      sha256,
      artifact_ref: artifactRef,
      compatibility: { node: '22.19.0', dsh: '0.1.0-rc.8', warnings },
      report: { entries: stats.entries, unpacked_bytes: stats.bytes, dependencies, scripts: Object.keys(scripts) },
      error: publishable ? null : warnings.join('；'),
    }
  } finally {
    await rm(work, { recursive: true, force: true })
  }
}
