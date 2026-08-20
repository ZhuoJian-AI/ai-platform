#!/usr/bin/env sh
set -eu

# Build cache only. Coolify installs Buildx inside its helper image rather than
# in the deploy user's Docker CLI. This never prunes containers, images or
# volumes, so PostgreSQL/Redis/business data volumes are outside its scope.
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  coollabsio/coolify-helper:1.0.14 \
  docker buildx prune --force --filter 'until=168h' --max-used-space 6GB
