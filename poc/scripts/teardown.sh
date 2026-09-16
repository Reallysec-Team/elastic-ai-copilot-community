#!/usr/bin/env sh
# Tear down PoC: docker compose down -v (DESTROYS local ES data).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$POC_DIR"

YES=0
[ "$1" = "-y" ] && YES=1

printf "[teardown] WARNING: this will destroy local Elasticsearch volumes (sample data, indices).\n"
if [ "$YES" != "1" ]; then
    printf "继续？输入 y 确认: "
    read -r ans
    case "$ans" in
        y|Y) ;;
        *) printf "[teardown] aborted\n"; exit 0 ;;
    esac
fi
docker compose down -v
printf "[teardown] done\n"
