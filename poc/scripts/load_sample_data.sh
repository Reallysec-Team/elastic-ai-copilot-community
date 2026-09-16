#!/usr/bin/env sh
# Load a Kibana sample dataset via the public API. Idempotent.
# Usage: ./load_sample_data.sh [dataset]   (default: kibana_sample_data_logs)
set -e

DATASET="${1:-kibana_sample_data_logs}"
KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
KIBANA_URL="${KIBANA_URL%/}"

printf "[load_sample_data] target: %s  dataset: %s\n" "$KIBANA_URL" "$DATASET"

# Wait for Kibana to be fully AVAILABLE, not merely answering HTTP. `/api/status`
# returns 200 early in boot while plugins are still registering, and the
# sample_data route (the `home` plugin) 404s until that finishes — the exact
# failure this guards against. Poll the status level and only proceed on
# "available"; fall back to a plain 200 after the window so a status-shape change
# can't hang us forever.
ready=0
status_available=0
i=0
while [ $i -lt 60 ]; do
    body=$(curl -s -m 3 "$KIBANA_URL/api/status" || true)
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 "$KIBANA_URL/api/status" || true)
    if [ "$code" = "200" ]; then
        ready=1
        # Grab the overall level (first "level" in the doc is status.overall.level).
        level=$(printf '%s' "$body" | tr -d ' \n' | sed -n 's/.*"overall":{"level":"\([a-z]*\)".*/\1/p')
        if [ -z "$level" ]; then
            level=$(printf '%s' "$body" | tr -d ' \n' | sed -n 's/.*"level":"\([a-z]*\)".*/\1/p')
        fi
        if [ "$level" = "available" ]; then
            status_available=1
            break
        fi
    fi
    sleep 2
    i=$((i + 1))
done
if [ "$ready" != "1" ]; then
    printf "[load_sample_data] Kibana not ready after 120s at %s\n" "$KIBANA_URL" >&2
    exit 1
fi
if [ "$status_available" = "1" ]; then
    printf "[load_sample_data] Kibana available\n"
else
    printf "[load_sample_data] Kibana answered 200 but never reported 'available'; proceeding with retries\n"
fi

# POST install — retry through the brief window where the route may still 404/503
# even after status reports available (plugin route registration lags slightly).
TMP="${TMPDIR:-/tmp}/_load_sample_body.$$"
attempt=0
max_attempts=40
while [ $attempt -lt $max_attempts ]; do
    code=$(curl -s -o "$TMP" -w "%{http_code}" \
        -X POST "$KIBANA_URL/api/sample_data/$DATASET" \
        -H "kbn-xsrf: true" || echo "000")

    case "$code" in
        200|201)
            printf "[load_sample_data] installed (HTTP %s)\n" "$code"
            rm -f "$TMP"
            exit 0
            ;;
        400|409)
            # 400 = already installed; 409 = install in progress / conflict — both
            # mean the dataset is (being) present, so treat as success.
            printf "[load_sample_data] already installed (HTTP %s — treating as success)\n" "$code"
            rm -f "$TMP"
            exit 0
            ;;
        404|503|000)
            # Route not registered yet / Kibana still warming up — retry.
            attempt=$((attempt + 1))
            printf "[load_sample_data] not ready (HTTP %s), retry %s/%s\n" "$code" "$attempt" "$max_attempts" >&2
            sleep 3
            ;;
        *)
            printf "[load_sample_data] failed: HTTP %s\n" "$code" >&2
            cat "$TMP" >&2 2>/dev/null || true
            rm -f "$TMP"
            exit 1
            ;;
    esac
done

printf "[load_sample_data] gave up after %s attempts (last HTTP %s)\n" "$max_attempts" "$code" >&2
cat "$TMP" >&2 2>/dev/null || true
rm -f "$TMP"
exit 1
