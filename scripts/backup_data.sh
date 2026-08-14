#!/usr/bin/env bash
# 全量备份 LLM Router 平台数据，用于线上部署时直接恢复。
#
# 备份内容：
#   1. PostgreSQL（pgvector）整库 —— 含全部业务表 / 文件二进制内容 / 向量 / alembic 版本
#   2. backend/.env                 —— 含 MASTER_ENCRYPTION_KEY / SECRET_KEY（恢复时解密 api_keys、admin 密码必备）
#   3. Redis RDB 快照               —— 运行时缓存（当前为空，留作保险）
#   4. manifest.txt                 —— 表行数、体积、校验和，便于恢复后核对
#
# 用法：
#   ./scripts/backup_data.sh                # 默认备份到 ./backups/<时间戳>/
#   ./scripts/backup_data.sh -o /path/dir   # 指定输出目录
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PG_CONTAINER="${PG_CONTAINER:-ai_infra_postgres}"
REDIS_CONTAINER="${REDIS_CONTAINER:-ai_infra_redis}"
PG_USER="${PG_USER:-ai_infra}"
PG_DB="${PG_DB:-ai_infra}"
BACKEND_ENV="llm_router/backend/.env"

OUT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--out) OUT_DIR="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${OUT_DIR:-backups/$STAMP}"
mkdir -p "$OUT_DIR"

echo "==> 备份目标目录: $OUT_DIR"

# ── 1. PostgreSQL 整库（custom 格式，压缩 + 可选择性恢复）──────────────
echo "==> [1/4] pg_dump -> $OUT_DIR/ai_infra.dump"
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc \
  --no-owner --no-privileges > "$OUT_DIR/ai_infra.dump"

# ── 2. .env（密钥，敏感）──────────────────────────────────────────────
echo "==> [2/4] .env -> $OUT_DIR/ai_infra.env"
if [[ -f "$BACKEND_ENV" ]]; then
  cp "$BACKEND_ENV" "$OUT_DIR/ai_infra.env"
  chmod 600 "$OUT_DIR/ai_infra.env"
else
  echo "    警告: 未找到 $BACKEND_ENV，跳过（恢复后将无法解密已加密字段！）" >&2
fi

# ── 3. Redis RDB 快照 ─────────────────────────────────────────────────
echo "==> [3/4] redis BGSAVE -> $OUT_DIR/redis.rdb"
if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER}$"; then
  prev=$(docker exec "$REDIS_CONTAINER" redis-cli LASTSAVE 2>/dev/null || echo 0)
  docker exec "$REDIS_CONTAINER" redis-cli BGSAVE >/dev/null 2>&1 || true
  # 等 BGSAVE 完成（LASTSAVE 时间戳推进）
  for _ in $(seq 1 20); do
    cur=$(docker exec "$REDIS_CONTAINER" redis-cli LASTSAVE 2>/dev/null || echo 0)
    [[ "$cur" != "$prev" ]] && break
    sleep 1
  done
  docker cp "$REDIS_CONTAINER:/data/dump.rdb" "$OUT_DIR/redis.rdb" 2>/dev/null \
    || echo "    跳过 redis（无 dump.rdb）"
else
  echo "    跳过 redis（容器未运行）"
fi

# ── 4. manifest ───────────────────────────────────────────────────────
echo "==> [4/4] manifest -> $OUT_DIR/manifest.txt"
{
  echo "LLM Router 数据备份清单"
  echo "生成时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "源容器:   postgres=$PG_CONTAINER  redis=$REDIS_CONTAINER"
  echo
  echo "── 表行数 ──"
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -c \
    "SELECT relname AS table, n_live_tup AS rows FROM pg_stat_user_tables ORDER BY relname;" 2>&1
  echo
  echo "── alembic 版本 ──"
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -c \
    "SELECT version_num FROM alembic_version;" 2>&1
  echo
  echo "── 文件体积 / 校验和 ──"
  ls -lh "$OUT_DIR/ai_infra.dump" "$OUT_DIR/ai_infra.env" 2>/dev/null
  shasum -a 256 "$OUT_DIR/ai_infra.dump" "$OUT_DIR/ai_infra.env" 2>/dev/null \
    || sha256sum "$OUT_DIR/ai_infra.dump" "$OUT_DIR/ai_infra.env" 2>/dev/null
  [[ -f "$OUT_DIR/redis.rdb" ]] && { ls -lh "$OUT_DIR/redis.rdb"; shasum -a 256 "$OUT_DIR/redis.rdb" 2>/dev/null; }
} > "$OUT_DIR/manifest.txt" 2>&1

# latest 软链
ln -sfn "$(basename "$OUT_DIR")" "backups/latest"

echo
echo "✅ 备份完成: $OUT_DIR"
echo "   恢复命令: ./scripts/restore_data.sh $OUT_DIR"
