#!/usr/bin/env sh
# End-to-end PoC setup. Idempotent. Run from anywhere.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$POC_DIR"

printf "[setup_demo] working directory: %s\n" "$POC_DIR"

# 1) Prereqs
if ! command -v docker >/dev/null 2>&1; then
    printf "[setup_demo] Docker not found. Install Docker.\n" >&2
    exit 1
fi
if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
    printf "[setup_demo] Python 3.10+ not found.\n" >&2
    exit 1
fi

# 2) docker compose up
printf "[setup_demo] starting Elasticsearch + Kibana...\n"
docker compose up -d

# 3) Wait for ES yellow status (up to 60s)
printf "[setup_demo] waiting for Elasticsearch (up to 60s)...\n"
ok=0
i=0
while [ $i -lt 30 ]; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 \
        "http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=2s" || true)
    if [ "$code" = "200" ]; then ok=1; break; fi
    sleep 2
    i=$((i + 1))
done
if [ "$ok" != "1" ]; then
    printf "[setup_demo] Elasticsearch did not become healthy. Check 'docker logs rst-elastic-ai-copilot-poc-es'.\n" >&2
    exit 1
fi
printf "[setup_demo] Elasticsearch healthy\n"

# 4) Wait for Kibana (up to 120s)
printf "[setup_demo] waiting for Kibana (up to 120s)...\n"
ok=0
i=0
while [ $i -lt 60 ]; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 "http://localhost:5601/api/status" || true)
    if [ "$code" = "200" ]; then ok=1; break; fi
    sleep 2
    i=$((i + 1))
done
if [ "$ok" != "1" ]; then
    printf "[setup_demo] Kibana did not become ready. Check 'docker logs rst-elastic-ai-copilot-poc-kibana'.\n" >&2
    exit 1
fi
printf "[setup_demo] Kibana ready\n"

# 5) Load sample data (idempotent)
sh "$SCRIPT_DIR/load_sample_data.sh"

# 6) .env scaffolding
printf "\n"
if [ ! -f "$POC_DIR/.env" ]; then
    cp "$POC_DIR/.env.example" "$POC_DIR/.env"
    printf "[setup_demo] 已创建 .env（复制自 .env.example）\n"
    printf "[setup_demo] 请编辑 .env 填入 LLM_API_KEY 和 LLM_MODEL（火山方舟接入点 ID）\n"
    printf "[setup_demo] 然后跑：python -m uvicorn backend.main:app --reload --port 8000\n"
else
    printf "[setup_demo] .env 已存在，跳过\n"
    printf "[setup_demo] 启动后端：python -m uvicorn backend.main:app --reload --port 8000\n"
fi
