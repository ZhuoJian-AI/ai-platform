#!/usr/bin/env sh
set -eu

# Build cache only. This command never prunes containers, images or volumes,
# so PostgreSQL/Redis/business data volumes are outside its scope.
docker builder prune --force --filter 'until=168h' --keep-storage 6GB
