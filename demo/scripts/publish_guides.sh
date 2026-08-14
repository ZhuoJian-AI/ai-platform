#!/usr/bin/env bash
# 发布客户 POC 指南四件套到 demo/publish/guide/（nginx 专属 location /guide/ 直发）。
#
# 一次性同步发布：两份指南 + 两份访问页，四者绑定、不可只发其一；
# 发布前做硬性不变量校验，任何一项不符即中止、不动已发布文件，防止脱敏/拆页回退或漂移。
#
#   不变量（任一不符即报错退出）：
#     指南：不含 poc-access 引用、不含 terminal/login、不含统一密码 12345678、不含对方/本方归口用户名
#     访问页：含 terminal/login + 12345678、回链自己的指南、不出现对方租户 slug（不互引）
#
# 用法： bash demo/scripts/publish_guides.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/demo"
DIST="$ROOT/demo/publish/guide"

# 源 → 发布名（ASCII 文件名，避免中文 URL 编码）
declare -a PAIRS=(
  "starclothing/服装企业AI底座POC指南.html|starclothing-poc-guide.html|starclothing"
  "agileac/空调企业AI底座POC指南.html|agileac-poc-guide.html|agileac"
  "agilesteel/钢铁企业AI底座POC指南.html|agilesteel-poc-guide.html|agilesteel"
  "agilestationery/文具贸易企业AI底座POC指南.html|agilestationery-poc-guide.html|agilestationery"
  "starexploration/勘探设计企业AI底座POC指南.html|starexploration-poc-guide.html|starexploration"
  "starhma/热熔胶企业AI底座POC指南.html|starhma-poc-guide.html|starhma"
  "starclothing/poc-access.html|starclothing-poc-access.html|starclothing"
  "agileac/poc-access.html|agileac-poc-access.html|agileac"
  "agilesteel/poc-access.html|agilesteel-poc-access.html|agilesteel"
  "agilestationery/poc-access.html|agilestationery-poc-access.html|agilestationery"
  "starexploration/poc-access.html|starexploration-poc-access.html|starexploration"
  "starhma/poc-access.html|starhma-poc-access.html|starhma"
)

# 归口用户名样本（按租户），用于断言指南正文不残留
SC_USERS='dev-lead|fabric-dev|qc-lead|supply-lead|prod-lead|finance-lead|merch-lead'
AG_USERS='rnd-translator|pm-product|mfg-planner|qal-engineer|scm-buyer|sal-ops|svc-engineer|mkt-specialist|fin-accountant|hr-recruiter|hr-trainer|hr-compensation|scm-logistics|sal-ecom|fin-receivable'
AS_USERS='mfg-planner|eqp-engineer|qal-engineer|scm-buyer|sal-ops|ene-dispatcher|saf-inspector|fin-accountant|hr-recruiter|hr-trainer|hr-compensation|scm-logistics|sal-ecom|fin-receivable'
AGST_USERS='sal-channel|sal-ka|ecm-ops|mkt-analyst|scm-customs|scm-logistics|prd-quality|svc-agent|fin-accountant|fin-receivable|hr-recruiter|hr-trainer|leg-counsel|it-specialist|it-infra'
SE_USERS='des-engineer|cost-estimator|fin-accountant|admin-officer|leg-counsel|epc-manager|saf-inspector|sec-officer|hr-recruiter|it-specialist|it-infra'
SH_USERS='rd-formulator|rd-analyst|sales-rep|mfg-planner|eqp-maintainer|scm-manager|qas-engineer|admin-officer|doc-clerk|it-specialist|it-infra'

err() { echo "✗ $*" >&2; exit 1; }

assert_count() { # file label expected_max grep_pattern
  local f="$1" label="$2" max="$3" pat="$4" n
  n=$(grep -cE "$pat" "$f" || true)
  if [ "$n" -gt "$max" ]; then err "$label: 期望 ≤$max，实际 $n — $f"; fi
}

assert_min() { # file label expected_min grep_pattern
  local f="$1" label="$2" min="$3" pat="$4" n
  n=$(grep -cE "$pat" "$f" || true)
  if [ "$n" -lt "$min" ]; then err "$label: 期望 ≥$min，实际 $n — $f"; fi
}

echo "== 校验源文件不变量 =="
for entry in "${PAIRS[@]}"; do
  IFS='|' read -r rel name tenant <<< "$entry"
  f="$SRC/$rel"
  [ -f "$f" ] || err "源文件不存在: $f"
  case "$name" in
    *-poc-guide.html)
      # 指南：零凭证、零访问页引用、零归口用户名
      assert_count "$f" "$name 指南含访问页引用" 0 'poc-access'
      assert_count "$f" "$name 指南含终端地址" 0 'terminal/login'
      assert_count "$f" "$name 指南含统一密码" 0 '12345678'
      if [ "$tenant" = starclothing ]; then assert_count "$f" "$name 指南残留用户名" 0 "$SC_USERS"; fi
      if [ "$tenant" = agileac ];    then assert_count "$f" "$name 指南残留用户名" 0 "$AG_USERS"; fi
      if [ "$tenant" = agilesteel ]; then assert_count "$f" "$name 指南残留用户名" 0 "$AS_USERS"; fi
      if [ "$tenant" = agilestationery ]; then assert_count "$f" "$name 指南残留用户名" 0 "$AGST_USERS"; fi
      if [ "$tenant" = starexploration ]; then assert_count "$f" "$name 指南残留用户名" 0 "$SE_USERS"; fi
      if [ "$tenant" = starhma ]; then assert_count "$f" "$name 指南残留用户名" 0 "$SH_USERS"; fi
      ;;
    *-poc-access.html)
      own_guide="${tenant}-poc-guide.html"
      # 访问页：必含凭证、必回链本指南、不出现其他租户（不互引）
      assert_min "$f" "$name 访问页缺终端地址" 1 'terminal/login'
      assert_min "$f" "$name 访问页缺统一密码" 1 '12345678'
      assert_min "$f" "$name 访问页缺本指南回链" 1 "$own_guide"
      # 三租户：访问页不得引用其余任一租户 slug
      for other in starclothing agileac agilesteel agilestationery starexploration starhma; do
        [ "$other" = "$tenant" ] && continue
        assert_count "$f" "$name 访问页误引 $other 租户" 0 "$other-poc-"
      done
      ;;
  esac
done

echo "== 发布（/bin/cp -f 绕开 cp -i 别名）=="
mkdir -p "$DIST"
for entry in "${PAIRS[@]}"; do
  IFS='|' read -r rel name tenant <<< "$entry"
  /bin/cp -f "$SRC/$rel" "$DIST/$name"
  chmod a+r "$DIST/$name"
done
# 旧合并访问页若残留则清除（已改为一企业一页，合并页不应再存在）
rm -f "$DIST/poc-access.html"

echo "== 校验发布副本 =="
for entry in "${PAIRS[@]}"; do
  IFS='|' read -r rel name tenant <<< "$entry"
  s="$SRC/$rel"; d="$DIST/$name"
  sm=$(md5sum "$s" | awk '{print $1}')
  dm=$(md5sum "$d" | awk '{print $1}')
  [ "$sm" = "$dm" ] || err "MD5 不一致: $name (源 $sm / 发布 $dm)"
  printf "  ✓ %-32s %s\n" "$name" "$dm"
done

echo
echo "已发布 4 件套到 $DIST："
ls -1 "$DIST"/*.html | sed 's#'"$DIST"'/#  #'
echo
echo "对外地址："
echo "  https://infra.aievolve.org.cn/guide/starclothing-poc-guide.html"
echo "  https://infra.aievolve.org.cn/guide/starclothing-poc-access.html"
echo "  https://infra.aievolve.org.cn/guide/agileac-poc-guide.html"
echo "  https://infra.aievolve.org.cn/guide/agileac-poc-access.html"
echo "  https://infra.aievolve.org.cn/guide/agilesteel-poc-guide.html"
echo "  https://infra.aievolve.org.cn/guide/agilesteel-poc-access.html"
echo "  https://infra.aievolve.org.cn/guide/agilestationery-poc-guide.html"
echo "  https://infra.aievolve.org.cn/guide/agilestationery-poc-access.html"
echo "  https://infra.aievolve.org.cn/guide/starexploration-poc-guide.html"
echo "  https://infra.aievolve.org.cn/guide/starexploration-poc-access.html"
echo "  https://infra.aievolve.org.cn/guide/starhma-poc-guide.html"
echo "  https://infra.aievolve.org.cn/guide/starhma-poc-access.html"
