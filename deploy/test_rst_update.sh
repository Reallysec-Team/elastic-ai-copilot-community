#!/usr/bin/env bash
# Tests for rst-update.sh using stub docker/compose/curl (no real containers).
# Covers §15: health-fail rollback, --rollback, updater gate, concurrency lock,
# happy install. Run: bash deploy/test_rst_update.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/rst-update.sh"
PASS=0; FAIL=0
ok()   { echo "PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

make_env() { # sets up a fresh sandbox, echoes its dir
  local d; d="$(mktemp -d)"
  mkdir -p "$d/bin" "$d/release/staging"
  # --- stub binaries ---
  cat > "$d/bin/stub_docker" <<EOF
#!/usr/bin/env bash
case "\$1" in
  load) echo "Loaded image: rst-elastic-ai-copilot-gateway:test" ;;
  # The default health probe asks docker for the container's health, since the
  # gateway publishes no port. Answer from the same health_state the curl stub
  # uses, so a test can drive either probe path identically.
  inspect) [ "\$(cat "$d/health_state" 2>/dev/null)" = "200" ] && echo healthy || echo starting ;;
  image) exit 0 ;;   # image rm
  *) exit 0 ;;
esac
EOF
  cat > "$d/bin/stub_compose" <<EOF
#!/usr/bin/env bash
# \`ps -q\` must yield a container id: the default health probe resolves the
# container through compose and then asks docker for its health.
for a in "\$@"; do [ "\$a" = "ps" ] && { echo "deadbeefcafe"; exit 0; }; done
# record the tag that compose would run with (read from the --env-file)
ef=""; for a in "\$@"; do [ "\$prev" = "--env-file" ] && ef="\$a"; prev="\$a"; done
tag="\$(sed -n 's/^GATEWAY_IMAGE_TAG=//p' "\$ef" 2>/dev/null | tail -1)"
echo "up tag=\${tag:-<default>}" >> "$d/compose.calls"
exit 0
EOF
  cat > "$d/bin/stub_curl" <<EOF
#!/usr/bin/env bash
cat "$d/health_state" 2>/dev/null || echo 000
EOF
  chmod +x "$d/bin"/*
  echo "200" > "$d/health_state"
  echo "$d"
}

# staged pointer as release_store writes it
write_pointer() { # write_pointer <dir> <version> <image_sha> <min_updater>
  cat > "$1/release/current.json" <<EOF
{"staged_version":"$2","manifest":{"app_id":"rst_elastic_ai_copilot","release_version":"$2","min_updater_version":$4,"artifacts":[{"kind":"image","sha256":"$3","size":10}]},"artifacts":[{"kind":"image","sha256":"$3","size":10},{"kind":"updater","sha256":"$(printf b%.0s $(seq 1 64) | cut -c1-64)","size":5}],"min_updater_version":$4,"staged_at":"2026-07-11T00:00:00Z"}
EOF
}

run() { # run <dir> [args...] ; exports config + returns exit code
  local d="$1"; shift
  DOCKER="$d/bin/stub_docker" COMPOSE="$d/bin/stub_compose" CURL="$d/bin/stub_curl" \
  RELEASE_DIR="$d/release" ENV_FILE="$d/.env" COMPOSE_FILE="$d/compose.yml" \
  HEALTH_INTERVAL=0 HEALTH_TIMEOUT=2 HEALTH_STREAK=2 UPDATER_VERSION=1 \
  bash "$SCRIPT" "$@"
}

IMG_SHA="$(printf a%.0s $(seq 1 64) | cut -c1-64)"

# --- 1. happy install ------------------------------------------------------
d="$(make_env)"; : > "$d/compose.yml"
printf 'GATEWAY_IMAGE_TAG=1.1.0\n' > "$d/.env"
echo "aaa" > "$d/release/staging/$IMG_SHA"
write_pointer "$d" "1.2.0" "$IMG_SHA" 0
if run "$d" >/dev/null 2>&1; then
  grep -q 'GATEWAY_IMAGE_TAG=1.2.0' "$d/.env" && grep -q '"installed_version":"1.2.0"' "$d/release/installed.json" \
    && ok "happy install: tag switched + installed.json" || bad "happy install: state wrong"
else
  bad "happy install: exited non-zero"
fi

# --- 2. health failure rolls back ------------------------------------------
d="$(make_env)"; : > "$d/compose.yml"
printf 'GATEWAY_IMAGE_TAG=1.1.0\n' > "$d/.env"
echo "aaa" > "$d/release/staging/$IMG_SHA"
write_pointer "$d" "1.2.0" "$IMG_SHA" 0
echo "500" > "$d/health_state"     # never healthy
if run "$d" >/dev/null 2>&1; then
  bad "health fail: should have exited non-zero"
else
  grep -q 'GATEWAY_IMAGE_TAG=1.1.0' "$d/.env" && [ -f "$d/release/failed.json" ] \
    && tail -1 "$d/compose.calls" | grep -q 'tag=1.1.0' \
    && ok "health fail: reverted tag + failed.json + restarted old" || bad "health fail: rollback state wrong"
fi

# --- 3. --rollback ---------------------------------------------------------
d="$(make_env)"; : > "$d/compose.yml"
printf 'GATEWAY_IMAGE_TAG=1.1.0\n' > "$d/.env"
echo "aaa" > "$d/release/staging/$IMG_SHA"
write_pointer "$d" "1.2.0" "$IMG_SHA" 0
run "$d" >/dev/null 2>&1   # install 1.2.0 (prev=1.1.0)
if run "$d" --rollback >/dev/null 2>&1; then
  grep -q 'GATEWAY_IMAGE_TAG=1.1.0' "$d/.env" && ok "--rollback: back to previous 1.1.0" || bad "--rollback: tag wrong"
else
  bad "--rollback: exited non-zero"
fi

# --- 4. updater too old refused --------------------------------------------
d="$(make_env)"; : > "$d/compose.yml"
printf 'GATEWAY_IMAGE_TAG=1.1.0\n' > "$d/.env"
echo "aaa" > "$d/release/staging/$IMG_SHA"
write_pointer "$d" "2.0.0" "$IMG_SHA" 99   # needs updater 99
if run "$d" >/dev/null 2>&1; then
  bad "updater gate: should refuse"
else
  [ ! -f "$d/compose.calls" ] && grep -q 'GATEWAY_IMAGE_TAG=1.1.0' "$d/.env" \
    && ok "updater gate: refused, no compose up, tag untouched" || bad "updater gate: side effects leaked"
fi

# --- 5. concurrency lock ---------------------------------------------------
d="$(make_env)"; : > "$d/compose.yml"
printf 'GATEWAY_IMAGE_TAG=1.1.0\n' > "$d/.env"
echo "aaa" > "$d/release/staging/$IMG_SHA"
write_pointer "$d" "1.2.0" "$IMG_SHA" 0
mkdir "$d/release/.lock"    # simulate another instance holding the lock
if run "$d" >/dev/null 2>&1; then
  bad "lock: second instance should abort"
else
  ok "lock: second instance blocked by held lock"
fi

# --- 6. P5 wiring: staged compose/env-example with a new required key -------
d="$(make_env)"; : > "$d/compose.yml"
printf 'SECRET=x\n' > "$d/.env"                       # lacks the new required key
echo "aaa" > "$d/release/staging/$IMG_SHA"
CSHA="$(printf c%.0s $(seq 1 64) | cut -c1-64)"
ESHA="$(printf e%.0s $(seq 1 64) | cut -c1-64)"
printf 'version: shipped-2\n' > "$d/release/staging/$CSHA"
printf 'SECRET=\nNEW_REQUIRED=\n'  > "$d/release/staging/$ESHA"   # NEW_REQUIRED has no default
cat > "$d/release/current.json" <<EOF
{"staged_version":"1.3.0","min_updater_version":0,"artifacts":[{"kind":"image","sha256":"$IMG_SHA","size":10},{"kind":"compose","sha256":"$CSHA","size":10},{"kind":"env-example","sha256":"$ESHA","size":10}]}
EOF
if run "$d" >/dev/null 2>&1; then
  bad "P5 wiring: should fail-closed on new required key"
else
  [ ! -f "$d/compose.calls" ] && grep -q '^NEW_REQUIRED=$' "$d/.env" \
    && ok "P5 wiring: new required key fail-closes before install (no compose up)" \
    || bad "P5 wiring: side effects wrong"
fi

echo "-----"
echo "rst-update.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
