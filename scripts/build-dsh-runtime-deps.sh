#!/usr/bin/env bash
# Build and push the dsh-runtime *dependency* base image after a DeepSeek Harness (DSH) upgrade.
#
# dsh_runtime/Dockerfile.coolify starts FROM ${AI_PLATFORM_DSH_RUNTIME_DEPS_BASE}, whose
# node_modules were installed from a previous pnpm-lock.yaml.  Whenever dsh_runtime/package.json,
# pnpm-lock.yaml, pnpm-workspace.yaml or vendor/*.tgz change, this image must be rebuilt first,
# otherwise the app image build reuses stale @deepseek-ai packages.
#
# Run on the release server from a checkout of the commit being released:
#
#   scripts/build-dsh-runtime-deps.sh            # build + push, prints the ARG line to use next
#   scripts/build-dsh-runtime-deps.sh --no-push  # local build only
#
# Environment overrides:
#   AI_PLATFORM_REGISTRY      default 127.0.0.1:5000/zhuojian
#   AI_PLATFORM_NODE22_BASE   default 127.0.0.1:5000/zhuojian/ai-platform-node22-pnpm:20260824-v1
#   DEPS_TAG                  default <short git sha of HEAD>
#
# Documented in COOLIFY_DEPLOYMENT.md "升级 DSH 版本后的发版步骤" and dsh_runtime/VENDOR.md.
set -euo pipefail

PUSH=1
for arg in "$@"; do
  case "$arg" in
    --no-push) PUSH=0 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="${AI_PLATFORM_REGISTRY:-127.0.0.1:5000/zhuojian}"
NODE22_BASE="${AI_PLATFORM_NODE22_BASE:-127.0.0.1:5000/zhuojian/ai-platform-node22-pnpm:20260824-v1}"
DOCKERFILE="$REPO_ROOT/infra/base-images/dsh-runtime-deps.Dockerfile"
IMAGE="$REGISTRY/ai-platform-dsh-runtime-deps"

cd "$REPO_ROOT"
FULL_SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short=7 HEAD)"
TAG="${DEPS_TAG:-$SHORT_SHA}"

# ── preflight ───────────────────────────────────────────────────────────────────────────
# The Dockerfile COPYs these paths relative to the repo root, so the build context is the root.
for required in \
  "$DOCKERFILE" \
  dsh_runtime/package.json \
  dsh_runtime/pnpm-lock.yaml \
  dsh_runtime/pnpm-workspace.yaml \
  dsh_runtime/vendor/SHA256SUMS; do
  [ -e "$required" ] || { echo "missing: $required" >&2; exit 1; }
done

if ! git diff --quiet HEAD -- dsh_runtime/package.json dsh_runtime/pnpm-lock.yaml \
     dsh_runtime/pnpm-workspace.yaml dsh_runtime/vendor; then
  echo "dsh_runtime dependency inputs have uncommitted changes; tag $TAG would not describe them." >&2
  echo "Commit first, or set DEPS_TAG explicitly." >&2
  exit 1
fi

echo "==> verifying vendored tarballs (dsh_runtime/vendor/SHA256SUMS)"
(cd dsh_runtime/vendor && sha256sum --quiet -c SHA256SUMS)

if [ -f .dockerignore ] && grep -Eq '^(dsh_runtime|dsh_runtime/vendor|\*\*/vendor)/?$' .dockerignore; then
  echo "root .dockerignore excludes dsh_runtime/vendor; the deps image would miss the tarballs." >&2
  exit 1
fi

# ── build ───────────────────────────────────────────────────────────────────────────────
echo "==> building $IMAGE:$TAG (source $FULL_SHA)"
DOCKER_BUILDKIT=1 docker build \
  --build-arg "AI_PLATFORM_NODE22_BASE=$NODE22_BASE" \
  --label "org.opencontainers.image.revision=$FULL_SHA" \
  --label "com.zhuojian.ai-platform.role=dsh-runtime-deps" \
  -f "$DOCKERFILE" \
  -t "$IMAGE:$TAG" \
  "$REPO_ROOT"

# Smoke: the vendored DSH version inside node_modules must match src/extensions.ts::DSH_VERSION.
EXPECTED_DSH="$(sed -nE "s/^export const DSH_VERSION = '([^']+)'.*/\1/p" dsh_runtime/src/extensions.ts)"
INSTALLED_DSH="$(docker run --rm "$IMAGE:$TAG" node -p "require('/app/node_modules/@deepseek-ai/dsh-agent-loop/package.json').version")"
if [ -n "$EXPECTED_DSH" ] && [ "$EXPECTED_DSH" != "$INSTALLED_DSH" ]; then
  echo "installed @deepseek-ai/dsh-agent-loop is $INSTALLED_DSH but src/extensions.ts says $EXPECTED_DSH" >&2
  exit 1
fi
echo "==> node_modules carry @deepseek-ai/dsh-* $INSTALLED_DSH"

# ── push + report ───────────────────────────────────────────────────────────────────────
REF="$IMAGE:$TAG"
if [ "$PUSH" = 1 ]; then
  echo "==> pushing $IMAGE:$TAG"
  docker push "$IMAGE:$TAG"
  DIGEST_REF="$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE:$TAG" 2>/dev/null || true)"
  [ -n "$DIGEST_REF" ] && REF="$DIGEST_REF"
fi

cat <<EOF

Dependency base image ready. Pass it to the dsh-runtime app image build:

AI_PLATFORM_DSH_RUNTIME_DEPS_BASE=$REF

DOCKER_BUILDKIT=1 docker build \\
  --build-arg AI_PLATFORM_DSH_RUNTIME_DEPS_BASE=$REF \\
  --build-arg AI_PLATFORM_NODE22_BASE=$NODE22_BASE \\
  --build-arg SOURCE_COMMIT=$FULL_SHA \\
  -f dsh_runtime/Dockerfile.coolify \\
  -t $REGISTRY/ai-platform-dsh-runtime-app:source-$SHORT_SHA \\
  dsh_runtime
EOF
