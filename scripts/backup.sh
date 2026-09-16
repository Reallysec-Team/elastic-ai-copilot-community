#!/usr/bin/env bash
# Elastic AI Copilot — 网关状态备份。
#
# 备份内容:网关可写状态(settings / llm_providers / dashboards / quota /
# license 激活记录 / server_guid)+ 反馈失败用例。ES 里的审计/知识库索引用
# ES 原生快照备份,见 docs/BACKUP.md。
#
# 用法:  bash scripts/backup.sh [备份目录]      默认 ./backups
# 建议:  每日 cron 跑一次,保留 30 天。

set -euo pipefail

# Linux 上无影响;Windows Git-Bash 下防止 /app/state 被 MSYS 改写成 Windows 路径。
export MSYS_NO_PATHCONV=1

CONTAINER=${RST_GATEWAY_CONTAINER:-rst-elastic-ai-copilot-gateway}
DEST=${1:-./backups}
TS=$(date +%Y%m%d-%H%M%S)

mkdir -p "$DEST"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "[backup] 错误:找不到容器 $CONTAINER(网关没起?)" >&2
  exit 1
fi

echo "[backup] /app/state -> $DEST/gateway-state-$TS.tar.gz"
docker exec "$CONTAINER" tar czf - -C /app/state . > "$DEST/gateway-state-$TS.tar.gz"

echo "[backup] failed_cases.yaml -> $DEST/failed_cases-$TS.yaml"
docker exec "$CONTAINER" sh -c 'cat /app/eval/failed_cases.yaml 2>/dev/null || true' \
  > "$DEST/failed_cases-$TS.yaml"
# 空文件(还没有反馈)就不留
[ -s "$DEST/failed_cases-$TS.yaml" ] || rm -f "$DEST/failed_cases-$TS.yaml"

# 保留 30 天
find "$DEST" -name 'gateway-state-*.tar.gz' -mtime +30 -delete 2>/dev/null || true
find "$DEST" -name 'failed_cases-*.yaml'    -mtime +30 -delete 2>/dev/null || true

echo "[backup] 完成。ES 审计/知识库索引请按 docs/BACKUP.md 做 ES 快照。"
