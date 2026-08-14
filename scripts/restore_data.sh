#!/usr/bin/env bash
# 从备份目录恢复 LLM Router 平台数据（用于线上部署）。
#
# 前置条件：
#   - 一个运行中的 pgvector postgres 容器（默认 ai_infra_postgres，镜像须为 pgvector/pgvector:pg16）
#   - 容器内已存在目标库/用户（docker-compose 的 POSTGRES_DB/USER 会自动创建）
#   - 备份目录由 scripts/backup_data.sh 生成，含 ai_infra.dump + ai_infra.env
#
# 用法：
#   ./scripts/restore_data.sh backups/20260630_153000
#   ./scripts/restore_data.sh backups/20260630_153000 --yes   # 跳过确认
#
# 注意：恢复会清空目标库现有业务表（pg_restore --clean --if-exists）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PG_CONTAINER="${PG_CONTAINER:-ai_infra_postgres}"
REDIS_CONTAINER="${REDIS_CONTAINER:-ai_infra_redis}"
PG_USER="${PG_USER:-ai_infra}"
PG_DB="${PG_DB:-ai_infra}"
BACKEND_ENV="llm_router/backend/.env"

BACKUP_DIR=""
ASSUME_YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1; shift ;;
    *) BACKUP_DIR="$1"; shift ;;
  esac
done

if [[ -z "$BACKUP_DIR" ]]; then
  # 未指定则用 latest
  BACKUP_DIR="backups/latest"
  echo "未指定备份目录，使用 $BACKUP_DIR"
fi
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

DUMP="$BACKUP_DIR/ai_infra.dump"
ENV_BAK="$BACKUP_DIR/ai_infra.env"
RDB_BAK="$BACKUP_DIR/redis.rdb"

[[ -f "$DUMP" ]] || { echo "❌ 找不到 dump: $DUMP" >&2; exit 1; }

echo "恢复源:   $BACKUP_DIR"
echo "目标库:   $PG_CONTAINER / $PG_DB"
echo "将清空目标库现有业务表后导入备份。"
if [[ "$ASSUME_YES" -eq 0 ]]; then
  read -r -p "确认继续？[y/N] " ans; [[ "$ans" =~ ^[Yy]$ ]] || { echo "已取消"; exit 1; }
fi

# ── 校验源容器是否为 pgvector（vector 扩展依赖）──────────────────────
if ! docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -c \
     "SELECT 1 FROM pg_available_extensions WHERE name='vector';" 2>/dev/null | grep -q 1; then
  echo "❌ 目标 postgres 不支持 vector 扩展。请使用 pgvector/pgvector:pg16 镜像。" >&2
  exit 1
fi

# ── 1. 恢复 PostgreSQL ────────────────────────────────────────────────
echo "==> [1/3] pg_restore $DUMP"
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" \
  --no-owner --no-privileges --clean --if-exists --exit-on-error < "$DUMP"

echo "    alembic 版本: $(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -c 'SELECT version_num FROM alembic_version;')"
echo "    表行数核对:"
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -c \
  "SELECT relname AS table, n_live_tup AS rows FROM pg_stat_user_tables WHERE n_live_tup>0 ORDER BY n_live_tup DESC;" 2>&1

# ── 2. 恢复 .env（密钥）───────────────────────────────────────────────
if [[ -f "$ENV_BAK" ]]; then
  echo "==> [2/3] 恢复 .env -> $BACKEND_ENV"
  cp "$ENV_BAK" "$BACKEND_ENV"
  chmod 600 "$BACKEND_ENV"
  echo "    已恢复 MASTER_ENCRYPTION_KEY / SECRET_KEY（解密 api_keys、admin 密码必备）"
else
  echo "==> [2/3] 跳过 .env（备份中不存在）—— 务必手动保证密钥与备份一致，否则加密字段无法解密" >&2
fi

# ── 3. 恢复 Redis（可选）──────────────────────────────────────────────
if [[ -f "$RDB_BAK" ]]; then
  echo "==> [3/3] 恢复 redis dump.rdb"
  if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER}$"; then
    docker stop "$REDIS_CONTAINER" >/dev/null
    docker cp "$RDB_BAK" "$REDIS_CONTAINER:/data/dump.rdb"
    docker start "$REDIS_CONTAINER" >/dev/null
    echo "    redis 已恢复（DBSIZE=$(docker exec "$REDIS_CONTAINER" redis-cli DBSIZE 2>/dev/null || echo '?')）"
  else
    echo "    跳过（redis 容器未运行）"
  fi
else
  echo "==> [3/3] 跳过 redis（无 rdb 备份）"
fi

echo
echo "✅ 恢复完成。后续步骤："
echo "   - 确认 .env 中 DATABASE_URL / REDIS_URL 指向线上地址"
echo "   - 运行 backend: alembic upgrade head（应为 no-op，alembic_version 已对齐）"
echo "   - 启动后端服务验证登录 / 数据接口"
