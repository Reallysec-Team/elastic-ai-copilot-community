#!/usr/bin/env sh
# Local eval gate — run the eval and exit nonzero if pass rate is below threshold.
# Mirrors what the GitHub Actions workflow does, for pre-push verification.
#
# Usage:
#   ./scripts/eval_gate.sh                  # default threshold 0.9 (90%)
#   THRESHOLD=0.85 ./scripts/eval_gate.sh
#   ./scripts/eval_gate.sh --case top-urls

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$POC_DIR"

THRESHOLD="${THRESHOLD:-0.9}"
EXTRA_ARGS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --case) EXTRA_ARGS="$EXTRA_ARGS --case $2"; shift 2 ;;
        --threshold) THRESHOLD="$2"; shift 2 ;;
        *) EXTRA_ARGS="$EXTRA_ARGS $1"; shift ;;
    esac
done

printf "[eval_gate] threshold: %s\n" "$THRESHOLD"
exec python -m eval.run --gate "$THRESHOLD" $EXTRA_ARGS
