#!/usr/bin/env bash
# preview-release.sh — 在发版服务器上为「DSH 加强版」预览栈重建有源码变更的应用镜像，
# 推到本机私有 Registry，并把 image@sha256 改写进 docker-compose.preview.yml。
#
# 只构建、推送、改文件；不 commit、不 push（服务器上没有写凭据）。改好的 compose 由操作者
# 从自己机器提交到 dsh-enhanced（脚本会把补丁写到 <source-dir>/preview-pin-<short sha>.patch）。
#
# 用法（在发版服务器上）：
#   scripts/preview-release.sh                                  # 检出目录用默认值，重建变更过的镜像
#   scripts/preview-release.sh --only backend,frontend          # 只重建这几个（跳过变更检测）
#   scripts/preview-release.sh --no-push                        # 本地构建，不推送、不改 compose
#
# 参数：
#   --source-dir <dir>   dsh-enhanced 的检出目录（默认 /root/zhuojian-builds/ai-platform-dsh-enhanced）
#   --commit <sha>       要发布的完整 commit（默认 git -C <dir> rev-parse HEAD；必须等于检出的 HEAD，
#                        因为构建上下文就是工作树）
#   --compose <path>     要改写的 compose（默认 <dir>/docker-compose.preview.yml）
#   --only <svc,svc>     只处理这些服务，并强制重建它们；可选值见下方 SERVICES
#   --force              全部重建，不做变更检测
#   --no-push            只构建
#   --allow-dirty        允许工作树有未提交改动（默认拒绝；compose 文件本身除外）
#
# 环境变量（基础镜像；都有默认值，除标注的两个）：
#   DSH_DEPS_BASE                 dsh-runtime 的依赖基础镜像，**必填**（重建 dsh-runtime 时）。
#                                 先在同一检出里跑 scripts/build-dsh-runtime-deps.sh，用它打印的
#                                 AI_PLATFORM_DSH_RUNTIME_DEPS_BASE=<ref>（也接受该变量名）。
#                                 rc.8 的 vendor 包变了，旧 deps 镜像会把 rc.5 的 node_modules 带上线。
#   MOCK_DEPS_BASE                mock 的依赖基础镜像；未设时从 Registry 的 tags 列表自动发现，
#                                 恰好一个 tag 才自动选，否则要求显式指定。
#   BACKEND_DEPS_BASE             默认 ai-platform-backend-deps@sha256:faa39695…（backend + workspace-preview 共用）
#   FRONTEND_DEPS_BASE            默认 ai-platform-frontend-deps@sha256:7045962b…
#   NGINX_BASE                    默认 ai-platform-nginx127@sha256:62223d64…
#   AI_PLATFORM_NODE22_BASE       默认 ai-platform-node22-pnpm:20260824-v1（dsh-runtime / extension-builder 运行层）
#   SKILL_RUNNER_DEPS_BASE        默认 ai-platform-skill-runner-deps:72797e5
#   EXTENSION_BUILDER_DEPS_BASE   默认 ai-platform-extension-builder-deps:034b277
#   AI_PLATFORM_REGISTRY          默认 127.0.0.1:5000/zhuojian
#   AI_PLATFORM_REGISTRY_API      默认 http://127.0.0.1:5000（只用来核对 tag 是否存在）
#   SOURCE_REPOSITORY             默认 https://github.com/ZhuoJian-AI/ai-platform.git
#
# 变更检测：读 compose 里当前钉住的镜像的 org.opencontainers.image.revision 标签，
# `git diff --quiet <那个 sha> <本次 commit> -- <该服务的构建上下文>` 无差异就跳过。
# 标签缺失 / 不在本地历史里 / 镜像拉不下来 → 一律重建。
#
# 构建配方与 COOLIFY_DEPLOYMENT.md「升级 DSH 版本后的发版步骤」一致：DOCKER_BUILDKIT=1、
# --progress=plain、--build-arg SOURCE_COMMIT / SOURCE_REPOSITORY，另加 OCI revision/source 标签
# （mock/Dockerfile.coolify 自己不写 LABEL，靠这里补上）。日志在 <source-dir>/build-<svc>.log。
set -euo pipefail

SERVICES=(backend workspace-preview frontend dsh-runtime skill-runner extension-builder mock)

usage() { sed -n '2,49p' "$0"; }

SOURCE_DIR=/root/zhuojian-builds/ai-platform-dsh-enhanced
COMMIT=""
COMPOSE=""
ONLY=""
PUSH=1
FORCE=0
ALLOW_DIRTY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --commit) COMMIT="$2"; shift 2 ;;
    --compose) COMPOSE="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --no-push) PUSH=0; shift ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

REGISTRY="${AI_PLATFORM_REGISTRY:-127.0.0.1:5000/zhuojian}"
REGISTRY_API="${AI_PLATFORM_REGISTRY_API:-http://127.0.0.1:5000}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-https://github.com/ZhuoJian-AI/ai-platform.git}"
BACKEND_DEPS_BASE="${BACKEND_DEPS_BASE:-127.0.0.1:5000/zhuojian/ai-platform-backend-deps@sha256:faa39695fd7ab957a81ebf9f8aa2b4113e249eb4b4ca641fd90a38ac502535a3}"
FRONTEND_DEPS_BASE="${FRONTEND_DEPS_BASE:-127.0.0.1:5000/zhuojian/ai-platform-frontend-deps@sha256:7045962b61998d14840600ec18b4f72a474bcb8418d7d41541fcede80a1340b4}"
NGINX_BASE="${NGINX_BASE:-127.0.0.1:5000/zhuojian/ai-platform-nginx127@sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8}"
NODE22_BASE="${AI_PLATFORM_NODE22_BASE:-127.0.0.1:5000/zhuojian/ai-platform-node22-pnpm:20260824-v1}"
SKILL_RUNNER_DEPS_BASE="${SKILL_RUNNER_DEPS_BASE:-127.0.0.1:5000/zhuojian/ai-platform-skill-runner-deps:72797e5}"
EXTENSION_BUILDER_DEPS_BASE="${EXTENSION_BUILDER_DEPS_BASE:-127.0.0.1:5000/zhuojian/ai-platform-extension-builder-deps:034b277}"
MOCK_DEPS_BASE="${MOCK_DEPS_BASE:-}"
DSH_DEPS_BASE="${DSH_DEPS_BASE:-${AI_PLATFORM_DSH_RUNTIME_DEPS_BASE:-}}"

declare -A DOCKERFILE CONTEXT
DOCKERFILE[backend]=llm_router/backend/Dockerfile.coolify;          CONTEXT[backend]=llm_router/backend
DOCKERFILE[workspace-preview]=llm_router/backend/Dockerfile.preview; CONTEXT[workspace-preview]=llm_router/backend
DOCKERFILE[frontend]=frontend/Dockerfile.prebuilt-deps;             CONTEXT[frontend]=frontend
DOCKERFILE[dsh-runtime]=dsh_runtime/Dockerfile.coolify;             CONTEXT[dsh-runtime]=dsh_runtime
DOCKERFILE[skill-runner]=skill_runner/Dockerfile.coolify;           CONTEXT[skill-runner]=skill_runner
DOCKERFILE[extension-builder]=extension_builder/Dockerfile.coolify; CONTEXT[extension-builder]=extension_builder
DOCKERFILE[mock]=mock/Dockerfile.coolify;                           CONTEXT[mock]=mock

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "==> $*"; }
image_of() { echo "$REGISTRY/ai-platform-$1-app"; }
# 把镜像名变成 ERE 字面量（转义 .）
image_re() { printf '%s' "$1" | sed 's/\./\\./g'; }

# 服务专属 build-arg（写入全局数组 BUILD_ARGS）
build_args_for() {
  BUILD_ARGS=()
  case "$1" in
    backend)
      BUILD_ARGS+=(--build-arg "AI_PLATFORM_BACKEND_DEPS_BASE=$BACKEND_DEPS_BASE") ;;
    workspace-preview)
      BUILD_ARGS+=(--build-arg "AI_PLATFORM_PYTHON_OFFICE_BASE=$BACKEND_DEPS_BASE") ;;
    frontend)
      BUILD_ARGS+=(--build-arg "AI_PLATFORM_FRONTEND_DEPS_BASE=$FRONTEND_DEPS_BASE"
                   --build-arg "AI_PLATFORM_NGINX_BASE=$NGINX_BASE") ;;
    dsh-runtime)
      BUILD_ARGS+=(--build-arg "AI_PLATFORM_DSH_RUNTIME_DEPS_BASE=$DSH_DEPS_BASE"
                   --build-arg "AI_PLATFORM_NODE22_BASE=$NODE22_BASE") ;;
    skill-runner)
      BUILD_ARGS+=(--build-arg "AI_PLATFORM_SKILL_RUNNER_DEPS_BASE=$SKILL_RUNNER_DEPS_BASE") ;;
    extension-builder)
      BUILD_ARGS+=(--build-arg "AI_PLATFORM_EXTENSION_BUILDER_DEPS_BASE=$EXTENSION_BUILDER_DEPS_BASE"
                   --build-arg "AI_PLATFORM_NODE22_BASE=$NODE22_BASE") ;;
    mock)
      BUILD_ARGS+=(--build-arg "AI_PLATFORM_MOCK_DEPS_BASE=$MOCK_DEPS_BASE") ;;
    *) die "unknown service: $1" ;;
  esac
}

# Registry tag 列表（只对 <repo>:<tag> 形式的基础镜像做存在性核对；Registry API 不通就只告警）
registry_tags() {  # $1 = repo path，如 zhuojian/ai-platform-mock-deps
  command -v curl >/dev/null 2>&1 || return 1
  curl -fsS --max-time 10 "$REGISTRY_API/v2/$1/tags/list" 2>/dev/null \
    | tr -d ' \n' | sed -nE 's/.*"tags":\[([^]]*)\].*/\1/p' | tr ',' '\n' | tr -d '"' | sed '/^$/d'
}
check_tag_exists() {  # $1 = <host>/<repo>:<tag>
  local ref="$1" repo tag tags
  case "$ref" in *@sha256:*) return 0 ;; esac
  repo="${ref#*/}"; repo="${repo%:*}"; tag="${ref##*:}"
  if ! tags="$(registry_tags "$repo")"; then
    echo "WARN: cannot list tags for $repo via $REGISTRY_API; skipping existence check for $ref" >&2
    return 0
  fi
  if ! printf '%s\n' "$tags" | grep -qx "$tag"; then
    die "base image tag not found in registry: $ref (available: $(printf '%s' "$tags" | tr '\n' ' '))"
  fi
}

# 当前钉住的镜像 → 其 revision 标签（拉不到/没标签输出空）
pinned_revision() {  # $1 = image ref
  local rev
  rev="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1" 2>/dev/null || true)"
  if [ -z "$rev" ]; then
    docker pull -q "$1" >/dev/null 2>&1 || true
    rev="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1" 2>/dev/null || true)"
  fi
  case "$rev" in unknown|"<no value>") rev="" ;; esac
  printf '%s' "$rev"
}

# ── preflight ───────────────────────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || die "docker not found"
command -v git >/dev/null 2>&1 || die "git not found"
[ -d "$SOURCE_DIR/.git" ] || die "not a git checkout: $SOURCE_DIR"
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
COMPOSE="${COMPOSE:-$SOURCE_DIR/docker-compose.preview.yml}"
[ -f "$COMPOSE" ] || die "compose file not found: $COMPOSE"
COMPOSE_REL="$(realpath --relative-to="$SOURCE_DIR" "$COMPOSE")"
case "$COMPOSE_REL" in ../*) die "compose must live inside $SOURCE_DIR (got $COMPOSE)" ;; esac

HEAD_SHA="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
if [ -z "$COMMIT" ]; then
  COMMIT="$HEAD_SHA"
else
  COMMIT="$(git -C "$SOURCE_DIR" rev-parse --verify "$COMMIT^{commit}")" || die "unknown commit: $COMMIT"
  [ "$COMMIT" = "$HEAD_SHA" ] || die "checkout is at $HEAD_SHA but --commit is $COMMIT; the build context is the working tree, so check out that commit first"
fi
SHORT_SHA="$(git -C "$SOURCE_DIR" rev-parse --short=7 "$COMMIT")"
BRANCH="$(git -C "$SOURCE_DIR" rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "dsh-enhanced" ] || echo "WARN: checkout is on '$BRANCH', not dsh-enhanced" >&2

DIRTY="$(git -C "$SOURCE_DIR" status --porcelain --untracked-files=no -- . ":(exclude)$COMPOSE_REL" || true)"
if [ -n "$DIRTY" ] && [ "$ALLOW_DIRTY" != 1 ]; then
  printf '%s\n' "$DIRTY" >&2
  die "working tree has uncommitted changes; images tagged preview-$SHORT_SHA would not describe them (use --allow-dirty to override)"
fi

for svc in "${SERVICES[@]}"; do
  [ -f "$SOURCE_DIR/${DOCKERFILE[$svc]}" ] || die "missing ${DOCKERFILE[$svc]}"
done

# ── 选出要构建的服务 ───────────────────────────────────────────────────────────────────
declare -A REASON OLD_REF NEW_REF STATUS
TO_BUILD=()
if [ -n "$ONLY" ]; then
  IFS=',' read -r -a wanted <<<"$ONLY"
  for svc in "${wanted[@]}"; do
    svc="$(echo "$svc" | tr -d ' ')"
    [ -n "${DOCKERFILE[$svc]:-}" ] || die "--only: unknown service '$svc' (choose from: ${SERVICES[*]})"
    TO_BUILD+=("$svc"); REASON[$svc]="--only"
  done
fi

for svc in "${SERVICES[@]}"; do
  IMAGE="$(image_of "$svc")"
  OLD_REF[$svc]="$(grep -E "^[[:space:]]*image:[[:space:]]*$(image_re "$IMAGE")@sha256:[0-9a-f]{64}[[:space:]]*$" "$COMPOSE" \
    | head -1 | sed -E 's/^[[:space:]]*image:[[:space:]]*//; s/[[:space:]]*$//' || true)"
  [ -n "$ONLY" ] && continue
  if [ "$FORCE" = 1 ]; then
    TO_BUILD+=("$svc"); REASON[$svc]="--force"; continue
  fi
  if [ -z "${OLD_REF[$svc]}" ]; then
    TO_BUILD+=("$svc"); REASON[$svc]="not pinned in compose"; continue
  fi
  rev="$(pinned_revision "${OLD_REF[$svc]}")"
  if [ -z "$rev" ]; then
    TO_BUILD+=("$svc"); REASON[$svc]="pinned image has no revision label"; continue
  fi
  if ! git -C "$SOURCE_DIR" cat-file -e "$rev^{commit}" 2>/dev/null; then
    TO_BUILD+=("$svc"); REASON[$svc]="pinned revision ${rev:0:7} not in local history"; continue
  fi
  if git -C "$SOURCE_DIR" diff --quiet "$rev" "$COMMIT" -- "${CONTEXT[$svc]}"; then
    STATUS[$svc]="skipped"; REASON[$svc]="unchanged since ${rev:0:7}"
  else
    TO_BUILD+=("$svc"); REASON[$svc]="changed since ${rev:0:7}"
  fi
done

if [ "${#TO_BUILD[@]}" -eq 0 ]; then
  log "nothing to build: every pinned image already matches $SHORT_SHA"
  for svc in "${SERVICES[@]}"; do printf '  %-18s %s\n' "$svc" "${REASON[$svc]}"; done
  exit 0
fi

# ── 基础镜像门槛 ───────────────────────────────────────────────────────────────────────
needs() { local s; for s in "${TO_BUILD[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }

if needs dsh-runtime && [ -z "$DSH_DEPS_BASE" ]; then
  cat >&2 <<EOF
ERROR: dsh-runtime is scheduled for rebuild but DSH_DEPS_BASE is unset.
       dsh_runtime/Dockerfile.coolify starts FROM the dependency base image; rc.8 changed
       dsh_runtime/vendor, so the old deps image would ship rc.5 node_modules.
       Run first, in this same checkout:
           $SOURCE_DIR/scripts/build-dsh-runtime-deps.sh
       then re-run with the line it prints:
           DSH_DEPS_BASE=<AI_PLATFORM_DSH_RUNTIME_DEPS_BASE value> $0 ...
EOF
  exit 1
fi
if needs mock && [ -z "$MOCK_DEPS_BASE" ]; then
  tags="$(registry_tags zhuojian/ai-platform-mock-deps || true)"
  count="$(printf '%s' "$tags" | grep -c . || true)"
  if [ "$count" = 1 ]; then
    MOCK_DEPS_BASE="$REGISTRY/ai-platform-mock-deps:$tags"
    log "MOCK_DEPS_BASE auto-discovered: $MOCK_DEPS_BASE"
  else
    die "MOCK_DEPS_BASE is unset and registry lists ${count:-0} tag(s) for ai-platform-mock-deps [$(printf '%s' "$tags" | tr '\n' ' ')]; set MOCK_DEPS_BASE=$REGISTRY/ai-platform-mock-deps:<tag>"
  fi
fi
if needs skill-runner; then check_tag_exists "$SKILL_RUNNER_DEPS_BASE"; fi
if needs extension-builder; then check_tag_exists "$EXTENSION_BUILDER_DEPS_BASE"; fi
if needs dsh-runtime || needs extension-builder; then check_tag_exists "$NODE22_BASE"; fi
if needs mock; then check_tag_exists "$MOCK_DEPS_BASE"; fi

# ── 构建 / 推送 / 改写 ────────────────────────────────────────────────────────────────
log "release $SHORT_SHA ($COMMIT) from $SOURCE_DIR [$BRANCH]"
log "building: ${TO_BUILD[*]}"

for svc in "${TO_BUILD[@]}"; do
  IMAGE="$(image_of "$svc")"
  TAG_REF="$IMAGE:preview-$SHORT_SHA"
  LOG="$SOURCE_DIR/build-$svc.log"
  build_args_for "$svc"
  log "building $TAG_REF  (${REASON[$svc]})  log: $LOG"
  DOCKER_BUILDKIT=1 docker build --progress=plain \
    --build-arg "SOURCE_COMMIT=$COMMIT" \
    --build-arg "SOURCE_REPOSITORY=$SOURCE_REPOSITORY" \
    "${BUILD_ARGS[@]}" \
    --label "org.opencontainers.image.revision=$COMMIT" \
    --label "org.opencontainers.image.source=$SOURCE_REPOSITORY" \
    -f "$SOURCE_DIR/${DOCKERFILE[$svc]}" \
    -t "$TAG_REF" \
    "$SOURCE_DIR/${CONTEXT[$svc]}" 2>&1 | tee "$LOG"
  built_rev="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$TAG_REF")"
  [ "$built_rev" = "$COMMIT" ] || die "$TAG_REF carries revision '$built_rev', expected $COMMIT"

  if [ "$PUSH" != 1 ]; then
    STATUS[$svc]="built (not pushed)"; NEW_REF[$svc]="$TAG_REF"; continue
  fi
  log "pushing $TAG_REF"
  docker push "$TAG_REF" | tee -a "$LOG"
  digest_ref="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$TAG_REF" | grep "^$IMAGE@sha256:" | head -1)"
  [ -n "$digest_ref" ] || die "no RepoDigest for $TAG_REF after push"
  NEW_REF[$svc]="$digest_ref"

  # 按镜像名改写 compose；backend 镜像被多个 worker 服务共用，会一起改
  hits="$(grep -cE "^[[:space:]]*image:[[:space:]]*$(image_re "$IMAGE")@sha256:[0-9a-f]{64}[[:space:]]*$" "$COMPOSE" || true)"
  if [ "$hits" = 0 ]; then
    STATUS[$svc]="pushed; compose has no $IMAGE@sha256 line (not rewritten)"
    continue
  fi
  sed -i -E "s#^([[:space:]]*image:[[:space:]]*)$(image_re "$IMAGE")@sha256:[0-9a-f]{64}([[:space:]]*)\$#\1${digest_ref}\2#" "$COMPOSE"
  after="$(grep -cF "image: $digest_ref" "$COMPOSE" || true)"
  [ "$after" = "$hits" ] || die "compose rewrite mismatch for $svc: matched $hits line(s) before, $after after"
  STATUS[$svc]="pinned in $hits service line(s)"
done

# ── 汇总 ───────────────────────────────────────────────────────────────────────────────
short() { case "$1" in *@sha256:*) echo "${1##*@sha256:}" | cut -c1-12 ;; "") echo "-" ;; *) echo "$1" ;; esac; }
echo
printf '%-18s %-14s %-14s %-32s %s\n' SERVICE OLD_DIGEST NEW_DIGEST STATUS REASON
printf '%-18s %-14s %-14s %-32s %s\n' ------- ---------- ---------- ------ ------
for svc in "${SERVICES[@]}"; do
  printf '%-18s %-14s %-14s %-32s %s\n' "$svc" "$(short "${OLD_REF[$svc]:-}")" "$(short "${NEW_REF[$svc]:-}")" "${STATUS[$svc]:-not selected}" "${REASON[$svc]:-}"
done
echo
if [ "$PUSH" = 1 ]; then
  git -C "$SOURCE_DIR" --no-pager diff --stat -- "$COMPOSE_REL"
  PATCH="$SOURCE_DIR/preview-pin-$SHORT_SHA.patch"
  git -C "$SOURCE_DIR" --no-pager diff -- "$COMPOSE_REL" > "$PATCH"
  echo
  git -C "$SOURCE_DIR" --no-pager diff -- "$COMPOSE_REL" | grep -E '^[-+] +image:' || true
  cat <<EOF

Compose rewritten in place: $COMPOSE
Patch for the operator's machine: $PATCH
Next (from a machine with GitHub write access, on branch dsh-enhanced at $SHORT_SHA):
  scp <server>:$PATCH . && git apply preview-pin-$SHORT_SHA.patch
  git commit -am "chore(deploy): pin preview images ($SHORT_SHA)" && git push origin dsh-enhanced
  then Deploy the preview Application in Coolify, and afterwards: git -C $SOURCE_DIR pull --ff-only
EOF
else
  echo "--no-push: images built locally only; compose not rewritten."
fi
