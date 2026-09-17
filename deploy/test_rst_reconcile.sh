#!/usr/bin/env bash
# Tests for rst-reconcile.sh (design §12 L1). Run: bash deploy/test_rst_reconcile.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/rst-reconcile.sh"
PASS=0; FAIL=0
ok()  { echo "PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

sandbox() { mktemp -d; }

run() { # run <dir> <new_compose> <new_example>
  local d="$1"
  ENV_FILE="$d/.env" COMPOSE_FILE="$d/compose.yml" RELEASE_DIR="$d/release" \
  RELEASE_VERSION="1.2.0" bash "$SCRIPT" "$2" "$3"
}

# --- 1. new key with default appended; existing values untouched -----------
d="$(sandbox)"
printf 'SECRET=customer-value\nDOMAIN=corp.example\n' > "$d/.env"
printf 'SECRET=\nDOMAIN=\nNEW_OPT=safe-default\n' > "$d/example"
: > "$d/compose.yml"; : > "$d/newcompose"
before="$(cat "$d/.env")"
if run "$d" "$d/newcompose" "$d/example" >/dev/null 2>&1; then
  grep -q '^NEW_OPT=safe-default' "$d/.env" \
    && grep -q '本行由 v1.2.0 升级新增' "$d/.env" \
    && grep -q '^SECRET=customer-value' "$d/.env" \
    && grep -q '^DOMAIN=corp.example' "$d/.env" \
    && ok "new default key appended; customer values untouched" \
    || bad "append/preserve wrong"
else
  bad "exit non-zero on defaulted key"
fi

# --- 2. customer-only key preserved (example lacks it) ---------------------
d="$(sandbox)"
printf 'CUSTOM_EXTRA=keepme\nSECRET=x\n' > "$d/.env"
printf 'SECRET=\n' > "$d/example"
: > "$d/compose.yml"; : > "$d/newcompose"
run "$d" "$d/newcompose" "$d/example" >/dev/null 2>&1
grep -q '^CUSTOM_EXTRA=keepme' "$d/.env" && ok "customer-only key preserved" || bad "customer key dropped"

# --- 3. new REQUIRED key (no default) -> fail-closed exit 3 -----------------
d="$(sandbox)"
printf 'SECRET=x\n' > "$d/.env"
printf 'SECRET=\nNEW_REQUIRED_KEY=\n' > "$d/example"
: > "$d/compose.yml"; : > "$d/newcompose"
out="$(run "$d" "$d/newcompose" "$d/example" 2>&1)"; rc=$?
if [ "$rc" -eq 3 ] && echo "$out" | grep -q 'NEW_REQUIRED_KEY' \
   && grep -q '^NEW_REQUIRED_KEY=$' "$d/.env"; then
  ok "new required key: fail-closed (exit 3) + appended empty + listed"
else
  bad "required-key fail-closed wrong (rc=$rc)"
fi

# --- 4. compose overwrite when unmodified ----------------------------------
d="$(sandbox)"
printf 'SECRET=x\n' > "$d/.env"; printf 'SECRET=\n' > "$d/example"
printf 'version: shipped-1\n' > "$d/compose.yml"
printf 'sha256sum-placeholder' | sha256sum "$d/compose.yml" >/dev/null 2>&1  # noop
# seed the stored sha = current compose sha (host never modified it)
mkdir -p "$d/release"; sha256sum "$d/compose.yml" | cut -d' ' -f1 > "$d/release/compose.sha"
printf 'version: shipped-2\n' > "$d/newcompose"
run "$d" "$d/newcompose" "$d/example" >/dev/null 2>&1
grep -q 'shipped-2' "$d/compose.yml" && [ ! -f "$d/compose.yml.new" ] \
  && ok "compose overwritten when unmodified" || bad "compose overwrite failed"

# --- 5. compose drift -> .new + warn, original kept ------------------------
d="$(sandbox)"
printf 'SECRET=x\n' > "$d/.env"; printf 'SECRET=\n' > "$d/example"
printf 'version: shipped-1\n' > "$d/compose.yml"
mkdir -p "$d/release"; echo "some-old-shipped-sha" > "$d/release/compose.sha"  # != current
printf 'HAND: edited by customer\n' >> "$d/compose.yml"                        # host modified it
printf 'version: shipped-2\n' > "$d/newcompose"
run "$d" "$d/newcompose" "$d/example" >/dev/null 2>&1
if grep -q 'HAND: edited by customer' "$d/compose.yml" \
   && [ -f "$d/compose.yml.new" ] && grep -q 'shipped-2' "$d/compose.yml.new"; then
  ok "compose drift: original kept, new template dropped as .new"
else
  bad "compose drift guard wrong"
fi

# --- 6. the REAL .env.example holds no placeholder-as-default --------------
# reconcile_env treats any uncommented non-empty value as a safe default and
# appends it to the customer's .env. Placeholders there (your_ark_api_key,
# es.corp.local, ep-xxxxxxxxxxxxxx-xxxxx) therefore got written into a live
# .env as if they were configuration, and the fail-closed path never fired.
# Placeholder examples belong in the comment; the value stays empty.
EXAMPLE="$HERE/../.env.example"
if [ -f "$EXAMPLE" ]; then
  offenders="$(grep -E '^[A-Za-z_][A-Za-z0-9_]*=.+' "$EXAMPLE" \
    | grep -Ei 'your_|xxxx|corp\.local|example\.(com|org)|changeme|<.*>' || true)"
  [ -z "$offenders" ] && ok ".env.example: no placeholder used as a default" \
    || { bad ".env.example placeholders would be appended to a customer .env:"; printf '    %s\n' $offenders; }
else
  bad ".env.example not found at $EXAMPLE"
fi

echo "-----"
echo "rst-reconcile.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
