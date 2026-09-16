#!/usr/bin/env bash
# Elastic AI Copilot — 从备份恢复网关状态。
#
# 用法:  bash scripts/restore.sh <gateway-state-*.tar.gz> [failed_cases-*.yaml]
#
# 恢复后需重启网关:
#   docker compose -f docker-compose.prod.yml restart gateway

set -euo pipefail

# Linux 上无影响;Windows Git-Bash 下防止 /app/state 被 MSYS 改写成 Windows 路径。
export MSYS_NO_PATHCONV=1

CONTAINER=${RST_GATEWAY_CONTAINER:-rst-elastic-ai-copilot-gateway}
STATE_TGZ=${1:?用法: bash scripts/restore.sh <gateway-state-*.tar.gz> [failed_cases-*.yaml]}
FAILED_CASES=${2:-}

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "[restore] 错误:找不到容器 $CONTAINER" >&2
  exit 1
fi

echo "[restore] 恢复 /app/state  <-  $STATE_TGZ"
docker exec -i "$CONTAINER" sh -c 'rm -rf /app/state/* && tar xzf - -C /app/state' \
  < "$STATE_TGZ"

if [ -n "$FAILED_CASES" ] && [ -f "$FAILED_CASES" ]; then
  echo "[restore] 恢复 failed_cases.yaml  <-  $FAILED_CASES"
  docker exec -i "$CONTAINER" sh -c 'cat > /app/eval/failed_cases.yaml' < "$FAILED_CASES"
fi

echo "[restore] 完成。现在重启网关:"
echo "  docker compose -f docker-compose.prod.yml restart gateway"
