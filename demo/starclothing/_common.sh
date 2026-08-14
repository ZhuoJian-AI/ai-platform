#!/usr/bin/env bash
# 星途服装 demo 通用函数库：登录 → 解析 agent_id → 调用 playground SSE。
# 由各 demo 脚本 source 引入，不直接执行。
#
# 用法（在 demo 脚本中）：
#   source "$(dirname "$0")/_common.sh"
#   AGENT_SLUG="starclothing-pd1-product-monitor"
#   DEMO_MSG="扫描所有逾期款号，给出推送清单"
#   run_demo   # 自动登录 → 找 agent → POST playground → SSE 流式打印

set -euo pipefail

# ──────── 配置（可被环境变量覆盖）────────
: "${BACKEND_HOST:=localhost}"
: "${BACKEND_PORT:=8000}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"

# 超级管理员（仅用于本演示）。生产环境请改为最小权限的 org_admin。
: "${ADMIN_USER:=root}"
: "${ADMIN_PASS:=Sjp19831209}"
: "${ORG_SLUG:=starclothing}"

# ──────── 工具函数 ────────
log() { printf '\033[36m[demo]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[31m[err]\033[0m %s\n' "$*" >&2; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { err "缺少依赖：$1（请先安装）"; exit 1; }
}

# 登录 → 打印 token 并写入 $ADMIN_TOKEN
do_login() {
    log "登录管理员 ${ADMIN_USER} ..."
    local resp
    resp=$(curl -sS -X POST "${BACKEND_URL}/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}")
    ADMIN_TOKEN=$(printf '%s' "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
    if [ -z "$ADMIN_TOKEN" ]; then
        err "登录失败：$resp"
        exit 1
    fi
    log "登录成功，token: ${ADMIN_TOKEN:0:32}..."
}

# 解析组织 ID
resolve_org_id() {
    ORG_ID=$(curl -sS "${BACKEND_URL}/api/v1/organizations" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(next((o['id'] for o in d if o.get('slug')=='${ORG_SLUG}'),''))")
    if [ -z "$ORG_ID" ]; then
        err "未找到组织 slug=${ORG_SLUG}"
        exit 1
    fi
    log "组织 ${ORG_SLUG} id=${ORG_ID}"
}

# 按 slug 查 agent_id → 写入 $AGENT_ID
resolve_agent_id() {
    [ -z "${AGENT_SLUG:-}" ] && { err "AGENT_SLUG 未设置"; exit 1; }
    AGENT_ID=$(curl -sS "${BACKEND_URL}/api/v1/organizations/${ORG_ID}/agents" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(next((a['id'] for a in d if a.get('slug')=='${AGENT_SLUG}'),''))")
    if [ -z "$AGENT_ID" ]; then
        err "未找到 agent slug=${AGENT_SLUG}（请先运行 demo/starclothing/scripts/seed_starclothing_agents.py）"
        exit 1
    fi
    log "Agent ${AGENT_SLUG} id=${AGENT_ID}"
}

# 调用 playground SSE，流式打印事件
run_playground() {
    [ -z "${DEMO_MSG:-}" ] && { err "DEMO_MSG 未设置"; exit 1; }
    log "发起 SSE 调用：${DEMO_MSG:0:80}"
    log "────────── SSE 事件流 ──────────"
    curl -sN -X POST "${BACKEND_URL}/api/v1/agents/${AGENT_ID}/playground" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"message\":\"${DEMO_MSG//\"/\\\"}\",\"stream\":true}" \
        | python3 -c '
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("data: "):
        continue
    try:
        ev = json.loads(line[6:])
    except Exception:
        continue
    t = ev.get("type")
    if t == "text":
        sys.stdout.write(ev.get("delta",""))
        sys.stdout.flush()
    elif t == "tool_call":
        name = ev.get("name","")
        args = ev.get("arguments","")[:200]
        print("\n\033[33m[tool_call]\033[0m " + name + " args=" + args)
    elif t == "tool_result":
        ok = "ok" if ev.get("ok") else "FAIL"
        content = ev.get("content","")[:500]
        print("\n\033[33m[tool_result " + ok + "]\033[0m " + content)
    elif t == "step":
        step = ev.get("step","")
        agent = ev.get("agent","")
        print("\n\033[36m[step]\033[0m " + step + " " + agent)
    elif t == "phase":
        phase = ev.get("phase","")
        idx = ev.get("index","")
        print("\n\033[36m[phase]\033[0m " + phase + " #" + str(idx))
    elif t == "final":
        latency = ev.get("latency_ms")
        sess = ev.get("session_id","")
        print("\n\033[35m[final]\033[0m latency=" + str(latency) + "ms session=" + sess)
    elif t == "error":
        print("\n\033[31m[error]\033[0m " + ev.get("error",""))
    else:
        print("\n[" + str(t) + "] " + json.dumps(ev, ensure_ascii=False)[:200])
'
    log "────────── SSE 结束 ──────────"
}

# 一站式入口（demo 脚本调用此函数即可）
run_demo() {
    require_cmd curl
    require_cmd python3
    cat <<EOF

╔══════════════════════════════════════════════════════════════════════╗
║  星途服装 · ${DEMO_TITLE:-${AGENT_SLUG:-demo}}
╚══════════════════════════════════════════════════════════════════════╝

EOF
    do_login
    resolve_org_id
    resolve_agent_id
    run_playground
}
