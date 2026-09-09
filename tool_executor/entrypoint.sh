#!/bin/sh
set -eu

# Coolify injects application-wide variables into every Compose service. Keep
# the fixed tool executor isolated from database, model and storage secrets.
mkdir -p /tmp/tool-home

exec env -i \
  "PATH=${PATH:-/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin}" \
  "HOME=/tmp/tool-home" \
  "LANG=${LANG:-C.UTF-8}" \
  "LC_ALL=${LC_ALL:-}" \
  "TZ=${TZ:-}" \
  "SSL_CERT_FILE=${SSL_CERT_FILE:-}" \
  "SSL_CERT_DIR=${SSL_CERT_DIR:-}" \
  "PIP_INDEX_URL=${PIP_INDEX_URL:-}" \
  "PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST:-}" \
  "PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT:-}" \
  "PIP_RETRIES=${PIP_RETRIES:-}" \
  "PYTHONDONTWRITEBYTECODE=${PYTHONDONTWRITEBYTECODE:-1}" \
  "PYTHONUNBUFFERED=${PYTHONUNBUFFERED:-1}" \
  "SOURCE_COMMIT=${SOURCE_COMMIT:-unknown}" \
  "TOOL_EXECUTOR_TOKEN=${TOOL_EXECUTOR_TOKEN:-}" \
  "TOOL_EXECUTOR_MAX_CONCURRENCY=${TOOL_EXECUTOR_MAX_CONCURRENCY:-4}" \
  "TOOL_EXECUTOR_MAX_QUEUE=${TOOL_EXECUTOR_MAX_QUEUE:-100}" \
  "TOOL_EXECUTOR_QUEUE_WAIT_SECONDS=${TOOL_EXECUTOR_QUEUE_WAIT_SECONDS:-300}" \
  "TOOL_EXECUTOR_OFFICE_CONCURRENCY=${TOOL_EXECUTOR_OFFICE_CONCURRENCY:-1}" \
  "$@"
