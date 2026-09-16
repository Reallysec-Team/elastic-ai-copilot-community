#!/usr/bin/env bash
# rst-reconcile.sh — compose stack update, L1 (design §12).
#
# When a release ships a changed docker-compose.prod.yml / .env.example, this
# reconciles the customer's on-host files WITHOUT a three-way merge engine:
#
#   * ownership split — compose is vendor-owned (overwrite, drift-guarded);
#     .env is customer-owned (append-only, values never touched)
#   * .env = key-set diff, not value merge — add missing keys with defaults;
#     a new REQUIRED key (no default) is appended empty and blocks startup
#     fail-closed until the operator fills it
#   * compose drift guard — overwrite only if the customer didn't hand-edit it;
#     otherwise drop the new template alongside as .new and warn
#
# Usage:
#   rst-reconcile.sh <new_compose> <new_env_example>
#
# Config (env):
#   ENV_FILE       customer .env               (default .env)
#   COMPOSE_FILE   customer compose            (default docker-compose.prod.yml)
#   RELEASE_DIR    state dir (stores compose.sha) (default ./release)
#   RELEASE_VERSION label for the "added by" comment (default next)
#
# Exit codes: 0 ok · 2 usage/IO · 3 fail-closed (new required keys need values)
set -uo pipefail

NEW_COMPOSE="${1:-}"
NEW_EXAMPLE="${2:-}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
RELEASE_DIR="${RELEASE_DIR:-./release}"
RELEASE_VERSION="${RELEASE_VERSION:-next}"
SHA_FILE="$RELEASE_DIR/compose.sha"

log() { printf '[rst-reconcile] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 2; }

[ -n "$NEW_COMPOSE" ] && [ -f "$NEW_COMPOSE" ] || die "new compose file missing: $NEW_COMPOSE"
[ -n "$NEW_EXAMPLE" ] && [ -f "$NEW_EXAMPLE" ] || die "new .env.example missing: $NEW_EXAMPLE"

sha256_of() { sha256sum "$1" | cut -d' ' -f1; }

# --- keys: uncommented KEY=... assignments only (commented = optional) ------
list_keys()  { grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$1" | sed 's/=.*//'; }
key_value()  { sed -n "s/^$2=\(.*\)$/\1/p" "$1" | head -1; }
has_key()    { grep -qE "^$2=" "$1"; }

# --- compose: vendor-owned, drift-guarded overwrite ------------------------
reconcile_compose() {
  mkdir -p "$RELEASE_DIR"
  local stored cur
  stored="$(cat "$SHA_FILE" 2>/dev/null || echo '')"
  cur=""; [ -f "$COMPOSE_FILE" ] && cur="$(sha256_of "$COMPOSE_FILE")"
  if [ ! -f "$COMPOSE_FILE" ] || [ -z "$stored" ] || [ "$cur" = "$stored" ]; then
    cp "$NEW_COMPOSE" "$COMPOSE_FILE"
    sha256_of "$NEW_COMPOSE" > "$SHA_FILE"
    log "compose updated to the shipped template"
  else
    cp "$NEW_COMPOSE" "$COMPOSE_FILE.new"
    log "WARNING: $COMPOSE_FILE was modified on this host; the new template was"
    log "written to $COMPOSE_FILE.new and NOT applied — reconcile it by hand."
  fi
}

# --- .env: customer-owned, append-only key-set diff ------------------------
# Returns the list of new REQUIRED (no-default) keys on stdout.
reconcile_env() {
  touch "$ENV_FILE"
  local key val missing=()
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    has_key "$ENV_FILE" "$key" && continue          # customer already has it — never touch
    val="$(key_value "$NEW_EXAMPLE" "$key")"
    if [ -z "$val" ]; then
      # new REQUIRED key with no safe default → append empty, block startup
      printf '%s=\n' "$key" >> "$ENV_FILE"
      missing+=("$key")
    else
      printf '%s=%s  # 本行由 v%s 升级新增，请复核\n' "$key" "$val" "$RELEASE_VERSION" >> "$ENV_FILE"
      log "added new key with default: $key"
    fi
  done < <(list_keys "$NEW_EXAMPLE")
  printf '%s\n' "${missing[@]:-}"
}

reconcile_compose
missing_out="$(reconcile_env)"
# strip blank lines produced by the empty-array guard
missing=$(printf '%s\n' "$missing_out" | grep -v '^$' || true)

if [ -n "$missing" ]; then
  log "FAIL-CLOSED: these new required variables have no safe default and must"
  log "be given a value in $ENV_FILE before the stack will start:"
  printf '  - %s\n' $missing >&2
  log "fill them in and re-run the update."
  exit 3
fi

log "stack reconciled for v$RELEASE_VERSION"
exit 0
