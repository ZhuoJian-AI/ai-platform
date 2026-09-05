# DSH runtime provenance

The `@deepseek-ai/*` packages in `vendor/` are pinned build artifacts from the
DeepSeek Harness release **`0.1.0-rc.8`** (upstream commit
`141eb6f`, tag `dsh-v0.1.0-rc.8`, branch `release/dsh-0.1.0-rc.8`).  That
release is not published as a complete installable set on npm, so the service
intentionally uses repository-owned tarballs plus `pnpm-lock.yaml` instead of
resolving a moving branch during Docker builds.

The runtime image is fixed to Node `22.19.0` and pnpm `11.7.0`
(`pnpm-11.7.0.tgz` in this directory; `packageManager` in `package.json`).
Verify vendored artifacts with `vendor/SHA256SUMS` before replacing or
upgrading them:

```sh
cd dsh_runtime/vendor && sha256sum -c SHA256SUMS
```

The single source of truth for the version string inside the runtime is
`src/extensions.ts::DSH_VERSION`; `health()` reports it and `verifyRelease`
rejects any release manifest naming another version.  Platform-side copies of
the same literal live in `extension_builder/src/builder.ts::compatibleDsh`,
`llm_router/backend/app/services/platform_extension_catalog.py`,
`platform_extension_discovery.py`, `platform_extension_service.py`,
`app/api/platform_extensions.py` and `extension-sdk/templates/*/ai-platform.extension.json`.

## Vendored packages

`upstream dir` is relative to the DeepSeek Harness repository root.  Every
`dsh-*` package shares the release version; `cordis` / `schemastery` keep their
own version line (upstream `vendor/`, see upstream `docs/rescope.md`) and were
byte-identical between rc.5 and rc.8, so their tarballs did not change.

| Package | Version | Upstream dir | Loaded by `runtime.ts` | Notes |
|---|---|---|---|---|
| `@deepseek-ai/cordis` | 4.0.1 | `vendor/cordis` | yes (framework) | unchanged since rc.5 |
| `@deepseek-ai/schemastery` | 3.18.1 | `vendor/schemastery` | transitive | unchanged since rc.5 |
| `@deepseek-ai/dsh-agent` | 0.1.0-rc.8 | `packages/core/agent` | yes | |
| `@deepseek-ai/dsh-agent-loop` | 0.1.0-rc.8 | `packages/core/agent-loop` | yes | coordinator; hooks `agent/turn-stopping`, `steer`, `maxParallelToolCalls` unchanged |
| `@deepseek-ai/dsh-attachment` | 0.1.0-rc.8 | `packages/attachment/attachment` | peer only | rc.8 adds image admission API (additive) |
| `@deepseek-ai/dsh-brand` | 0.1.0-rc.8 | `packages/util/brand` | peer only | |
| `@deepseek-ai/dsh-code-runtime` | 0.1.0-rc.8 | `packages/code-runtime/code-runtime` | peer only | interface layer |
| `@deepseek-ai/dsh-code-runtime-worker-thread` | 0.1.0-rc.8 | `packages/code-runtime/code-runtime-worker-thread` | **no (new)** | provider for roadmap C2; ships `lib/worker.cjs` |
| `@deepseek-ai/dsh-invariants` | 0.1.0-rc.8 | `packages/runtime-diagnostics/invariants` | peer only | |
| `@deepseek-ai/dsh-llm` | 0.1.0-rc.8 | `packages/llm/llm` | yes | rc.8 adds `ReplayEnvelope`, `offloadRequestImages`, `Assembler.interruptedBlocks`; retry default 2→5 |
| `@deepseek-ai/dsh-repeat-tool-reminder` | 0.1.0-rc.8 | `packages/guard/repeat-tool-reminder` | **no (new)** | advisory reminder plugin; platform keeps its own blocking guard in `policies.ts` |
| `@deepseek-ai/dsh-scope` | 0.1.0-rc.8 | `packages/core/scope` | peer only | |
| `@deepseek-ai/dsh-session` | 0.1.0-rc.8 | `packages/core/session` | yes | `assistant/message` gains `interrupted?: true` for aborted turns |
| `@deepseek-ai/dsh-session-persistence` | 0.1.0-rc.8 | `packages/session/session-persistence` | peer only | interface layer |
| `@deepseek-ai/dsh-session-persistence-jsonl` | 0.1.0-rc.8 | `packages/session/session-persistence-jsonl` | **no (new)** | provider for roadmap C1; pulls `koffi` (see below) |
| `@deepseek-ai/dsh-settings` | 0.1.0-rc.8 | `packages/settings/settings` | peer only | |
| `@deepseek-ai/dsh-system-prompt` | 0.1.0-rc.8 | `packages/core/system-prompt` | yes | |
| `@deepseek-ai/dsh-timeout` | 0.1.0-rc.8 | `packages/util/timeout` | yes (`deadline`, `timeoutOf`) | unchanged |
| `@deepseek-ai/dsh-tool-call-timeout-policy` | 0.1.0-rc.8 | `packages/guard/timeout-policy` | **no (new)** | upstream `tools/execute` timeout wrapper; platform enforces the deadline itself in `registerTool` |
| `@deepseek-ai/dsh-tools` | 0.1.0-rc.8 | `packages/core/tools` | yes | `timeoutMs` / `isConcurrencySafe` / `finalizeContent`, `tools/pre-execute|post-execute|result` unchanged |
| `@deepseek-ai/dsh-typert-protocol` | 0.1.0-rc.8 | `packages/typert/protocol` | peer only | |
| `@deepseek-ai/dsh-typert-registry` | 0.1.0-rc.8 | `packages/typert/registry` | peer only | registry dep `zod ^4.4.3` |
| `@deepseek-ai/dsh-user-approval` | 0.1.0-rc.8 | `packages/interaction/user-approval` | no (B1 wires it) | unchanged |

Registry (non-vendored) dependencies the lockfile pins: `@deepseek-ai/cosmokit`,
`@standard-schema/spec`, `zod`, `koffi` + its `@koromix/koffi-*` optional
prebuilt binaries, `@types/node`, `typescript`.

### koffi and `pnpm-workspace.yaml`

`dsh-session-persistence-jsonl` depends on `koffi` (FFI), which it imports only
on Windows (`kernel32.dll` file locking); the Linux container never loads it.
koffi's prebuilt binary arrives through `@koromix/koffi-<platform>` optional
dependencies, and its `install` script is a from-source fallback (cmake + C++
toolchain).  pnpm 11 treats an unlisted dependency build script as a hard error
(`ERR_PNPM_IGNORED_BUILDS`) and no longer reads the `pnpm` field of
`package.json`, so the denial is recorded in `pnpm-workspace.yaml`
(`allowBuilds: { koffi: false }`).  **Every Dockerfile that runs `pnpm install`
here must COPY `pnpm-workspace.yaml` next to `package.json`** — `Dockerfile`,
`Dockerfile.coolify` and `infra/base-images/dsh-runtime-deps.Dockerfile` do.

## Upgrade procedure

Worked for rc.5 → rc.8 on 2026-09-05; needs no network beyond the npm registry
for the handful of registry dependencies above.

1. Check out the upstream release tag in a clean clone and build it once
   (`pnpm install && pnpm run build:lib`), so every package has `lib/`.  Only a
   package that lacks `lib/` needs `npx tsc -p <pkg>/tsconfig.json`.
2. Confirm the foundation versions upstream (`vendor/cordis/package.json`,
   `vendor/schemastery/package.json`).  If they changed, pack them too; if
   they are unchanged, compare the packed tree with the existing tarball
   (`tar -xzf` both, `diff -r`) and keep the old file when identical.
3. Pack each package with the pinned pnpm (the local tarball works without a
   global install; upstream's `scripts/release/pack.ts` runs the same command but
   insists on a complete official client build record, which we do not need):

   ```sh
   mkdir -p /tmp/pnpm117 && tar -xzf dsh_runtime/pnpm-11.7.0.tgz -C /tmp/pnpm117
   PNPM="node /tmp/pnpm117/package/bin/pnpm.cjs"
   cd <upstream clone>
   for d in packages/core/agent packages/core/agent-loop ... ; do
     $PNPM --dir "$d" pack --pack-destination /tmp/dsh-pack
   done
   ```

   `pnpm pack` rewrites `workspace:^` peers to `^<version>` (check
   `package/package.json` inside a tarball).  Tarball names are
   `<scope>-<name>-<version>.tgz`, matching upstream `tarballName()`.
4. Replace the tarballs in `vendor/`, then regenerate the checksum file in the
   two-space text format the repo uses:

   ```sh
   cd dsh_runtime/vendor && ls *.tgz | sort | xargs sha256sum | sed 's/ \*/  /' > SHA256SUMS
   ```

5. Point every `dependencies` entry in `package.json` at the new file names,
   add any new package, then regenerate the lockfile and install with the exact
   commands the Docker images run:

   ```sh
   cd dsh_runtime
   $PNPM install --lockfile-only
   $PNPM install --frozen-lockfile --trust-lockfile   # must exit 0 with no ERR_PNPM_IGNORED_BUILDS
   ```

   A new dependency with an install script surfaces here; decide it in
   `pnpm-workspace.yaml#allowBuilds`.
6. Bump `src/extensions.ts::DSH_VERSION` and the platform-side literals listed
   at the top (`grep -rn "0\.1\.0-rc\." --exclude-dir=node_modules --exclude-dir=vendor --exclude-dir=dist`).
7. `npx tsc --noEmit -p tsconfig.json && npm run build && npm test`; repeat
   `npx tsc --noEmit` in `extension_builder/`.
8. Diff the old and new `lib/types/**/*.d.ts` of every package `src/` imports
   (extract the old tarball, `diff -r -x '*.js' -x '*.map'` against upstream
   `lib/types`) and record breaking changes in the table above.
9. Rebuild `infra/base-images/dsh-runtime-deps.Dockerfile` before deploying:
   `Dockerfile.coolify` starts `FROM ${AI_PLATFORM_DSH_RUNTIME_DEPS_BASE}`,
   whose `node_modules` were installed from the previous lockfile.

## rc.5 → rc.8 change summary (2026-09-05)

- No breaking API change for `src/`: the `.d.ts` trees of `dsh-agent`,
  `dsh-agent-loop`, `dsh-tools`, `dsh-timeout`, `dsh-user-approval`,
  `dsh-session-persistence`, `dsh-system-prompt`, `dsh-scope`, `dsh-settings`,
  `dsh-brand`, `dsh-code-runtime`, `dsh-invariants`, `dsh-typert-*` are identical
  to rc.5.  `dsh-llm`, `dsh-session` and `dsh-attachment` only gained members.
- Behaviour: `dsh-agent-loop` now finalises the streamed text prefix of an
  aborted turn as an `assistant/message` with `interrupted: true`
  (`runtime.ts` ends cancelled runs with `CANCELLED` and never emits that text
  as `done`, so nothing changes for the platform).  `dsh-llm` retry default
  rose from 2 to 5 eligible retries (the platform adapter does not opt into the
  retry policy).
- All 26 runtime tests pass unchanged.
