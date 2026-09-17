#!/usr/bin/env bash
# rst-update.sh — host-side installer for a STAGED release (design §8/§9/§10).
#
# The gateway (release_store.py, P3) has already downloaded + verified the
# release into $RELEASE_DIR/staging and written $RELEASE_DIR/current.json. This
# script — which runs on the host, NOT in a container, so it can drive
# docker/compose — loads the staged image, switches the compose tag, and
# health-checks the new container, rolling back on any failure.
#
# It NEVER auto-replaces itself: if the staged release needs a newer installer
# (min_updater_version > UPDATER_VERSION) it refuses with an actionable message
# and the operator copies the new rst-update.sh from the customer console.
#
# Usage:
#   rst-update.sh            install the staged release (health-gated)
#   rst-update.sh --rollback revert to the previous installed version
#   rst-update.sh --prune-old  docker image rm the previous image (manual)
#
# Config (env, with sane defaults):
#   RELEASE_DIR   staged release dir              (default ./release)
#   COMPOSE_FILE  compose file                    (default docker-compose.prod.yml)
#   ENV_FILE      compose .env (holds the tag)    (default .env)
#   SERVICE       compose service to restart      (default gateway)
#   HEALTH_URL    health endpoint                 (default http://127.0.0.1:8080/healthz)
#   IMAGE_REPO    image repo (tag appended)       (default rst-elastic-ai-copilot-gateway)
#   TAG_VAR       .env key holding the image tag  (default GATEWAY_IMAGE_TAG)
set -euo pipefail

# This installer's capability version. Bump when the install flow gains a step
# (e.g. a data migration) that older scripts can't perform. A staged release
# whose manifest requires a higher min_updater_version is refused (§8).
UPDATER_VERSION="${UPDATER_VERSION:-1}"

RELEASE_DIR="${RELEASE_DIR:-./release}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env}"
SERVICE="${SERVICE:-gateway}"
# Health probe. Default is the CONTAINER's own healthcheck, not an HTTP port:
# docker-compose.prod.yml publishes no ports for the gateway (only Caddy binds
# 80/443), so the previous default of http://127.0.0.1:8080/healthz could never
# connect. Every online update therefore failed its gate and rolled back, and
# the operator read that as "the new release is broken" — the rollback path was
# the only one ever exercised. Set HEALTH_URL to probe over HTTP instead
# (Caddy exposes /healthz without auth, so HEALTH_URL=https://127.0.0.1/healthz
# with CURL='curl -k' works).
HEALTH_URL="${HEALTH_URL:-}"
IMAGE_REPO="${IMAGE_REPO:-rst-elastic-ai-copilot-gateway}"
TAG_VAR="${TAG_VAR:-GATEWAY_IMAGE_TAG}"
# Health-check tuning (ops may relax on slow hosts; tests drive them tight).
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"   # seconds between probes
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"   # total budget
HEALTH_STREAK="${HEALTH_STREAK:-3}"       # consecutive 200s required

STAGING="$RELEASE_DIR/staging"
POINTER="$RELEASE_DIR/current.json"      # staged pointer (written by release_store)
INSTALLED="$RELEASE_DIR/installed.json"  # what we last installed (+ previous)
FAILED="$RELEASE_DIR/failed.json"
ROLLBACK_ENV="$RELEASE_DIR/rollback.env"
LOCKDIR="$RELEASE_DIR/.lock"             # mkdir = atomic cross-platform lock

# Allow tests / non-standard hosts to override the binaries.
DOCKER="${DOCKER:-docker}"
COMPOSE="${COMPOSE:-$DOCKER compose}"
CURL="${CURL:-curl}"
RECONCILE="${RECONCILE:-$(cd "$(dirname "$0")" && pwd)/rst-reconcile.sh}"

log()  { printf '[rst-update] %s\n' "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

# --- tiny JSON reader (no jq dependency on the host) -----------------------
# Extracts a top-level string/number value for a key from a flat-ish JSON blob.
json_str() { # json_str <file> <key>
  sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$1" | head -1
}
json_num() { # json_num <file> <key>
  sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p" "$1" | head -1
}

lock() {
  if ! mkdir "$LOCKDIR" 2>/dev/null; then
    # EEXIST = a real lock. Anything else is "cannot write $RELEASE_DIR": the
    # gateway (uid 10001) owns it, so an unprivileged operator lands here.
    [ -d "$LOCKDIR" ] || die "cannot create $LOCKDIR — $RELEASE_DIR is not writable by $(id -un); run with sudo"
    die "another rst-update is running (lock $LOCKDIR held); aborting"
  fi
  trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT
}

# --- .env tag helpers: upsert a single key, reboot-safe --------------------
env_get_tag() {
  [ -f "$ENV_FILE" ] || { echo ""; return; }
  sed -n "s/^$TAG_VAR=\(.*\)$/\1/p" "$ENV_FILE" | tail -1
}
env_set_tag() { # env_set_tag <tag>
  touch "$ENV_FILE"
  if grep -q "^$TAG_VAR=" "$ENV_FILE"; then
    # in-place replace the one line; portable (no sed -i quirks across platforms)
    local tmp; tmp="$(mktemp)"
    sed "s|^$TAG_VAR=.*|$TAG_VAR=$1|" "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$TAG_VAR" "$1" >> "$ENV_FILE"
  fi
}

# COMPOSE_FILE follows docker's own convention: several files joined with ':'
# (an overlay on top of docker-compose.prod.yml, e.g. bundled ES for a demo).
# A single -f "$COMPOSE_FILE" would hand compose the literal "a.yml:b.yml".
compose_files() {
  local IFS=':' f
  for f in $COMPOSE_FILE; do printf -- '-f\n%s\n' "$f"; done
}
compose_cmd() {
  local -a args=()
  while IFS= read -r line; do args+=("$line"); done < <(compose_files)
  $COMPOSE "${args[@]}" --env-file "$ENV_FILE" "$@"
}

compose_up() { compose_cmd up -d "$SERVICE"; }

container_healthy() {
  # The gateway image declares a HEALTHCHECK, so docker already knows. This
  # needs no published port, which is what makes it the right default here.
  local st
  st="$(compose_cmd ps -q "$SERVICE" 2>/dev/null \
        | head -1 | xargs -r $DOCKER inspect --format '{{.State.Health.Status}}' 2>/dev/null)"
  if [ -z "$st" ]; then
    # No healthcheck defined (older image): fall back to "running".
    st="$(compose_cmd ps -q "$SERVICE" 2>/dev/null \
          | head -1 | xargs -r $DOCKER inspect --format '{{.State.Status}}' 2>/dev/null)"
    [ "$st" = "running" ] && return 0 || return 1
  fi
  [ "$st" = "healthy" ] && return 0 || return 1
}

health_ok() {
  # HEALTH_STREAK consecutive successes, HEALTH_INTERVAL apart, within
  # HEALTH_TIMEOUT. Probes the container's own health unless HEALTH_URL is set.
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) streak=0 code
  while [ "$SECONDS" -le "$deadline" ]; do
    if [ -z "$HEALTH_URL" ]; then
      code=$(container_healthy && echo 200 || echo 000)
    else
      code="$($CURL -fsS -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || echo 000)"
    fi
    if [ "$code" = "200" ]; then
      streak=$((streak + 1))
      [ "$streak" -ge "$HEALTH_STREAK" ] && return 0
    else
      streak=0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }

write_json() { # write_json <file> <k=v>...  (values are quoted strings)
  local f="$1"; shift
  { printf '{'; local first=1 kv
    for kv in "$@"; do
      [ "$first" = 1 ] || printf ','
      first=0
      printf '"%s":"%s"' "${kv%%=*}" "${kv#*=}"
    done
    printf '}\n'
  } > "$f"
}

artifact_sha() { # artifact_sha <kind> -> sha256 of that artifact in the pointer
  sed -n "s/.*\"kind\"[[:space:]]*:[[:space:]]*\"$1\"[^}]*\"sha256\"[[:space:]]*:[[:space:]]*\"\([0-9a-f]\{64\}\)\".*/\1/p" "$POINTER" | head -1
}

reconcile_stack() { # <version> — P5 §12; no-op unless the release ships compose+env
  local csha esha rc
  csha="$(artifact_sha compose)"
  esha="$(artifact_sha env-example)"
  [ -n "$csha" ] && [ -n "$esha" ] || return 0
  local cfile="$STAGING/$csha" efile="$STAGING/$esha"
  [ -f "$cfile" ] && [ -f "$efile" ] || die "staged compose/env-example artifact missing on disk"
  log "reconciling compose stack (P5) ..."
  if RELEASE_VERSION="$1" ENV_FILE="$ENV_FILE" COMPOSE_FILE="$COMPOSE_FILE" \
     RELEASE_DIR="$RELEASE_DIR" bash "$RECONCILE" "$cfile" "$efile"; then
    return 0
  fi
  rc=$?
  if [ "$rc" -eq 3 ]; then
    die "new required .env variables must be filled before this release can install (see above)"
  fi
  die "compose stack reconcile failed (rc=$rc)"
}

# ---------------------------------------------------------------------------
do_install() {
  lock
  [ -f "$POINTER" ] || die "no staged release ($POINTER missing); the gateway must download one first"

  local version min_up
  version="$(json_str "$POINTER" staged_version)"
  [ -n "$version" ] || die "staged pointer has no staged_version"
  min_up="$(json_num "$POINTER" min_updater_version)"; min_up="${min_up:-0}"
  if [ "$min_up" -gt "$UPDATER_VERSION" ]; then
    die "staged release $version needs updater >= $min_up (this host has $UPDATER_VERSION). \
Download the newer rst-update.sh from the customer console and re-run."
  fi

  # Compose-stack reconcile (P5, §12): if this release ships a new compose /
  # .env.example (as 'compose' + 'env-example' artifacts), reconcile them BEFORE
  # switching the image — a new required .env key fail-closes here so we never
  # restart into a broken stack.
  reconcile_stack "$version"

  # Locate the staged image artifact. The pointer lists artifacts by kind;
  # we install the one tagged 'image'. Its file is staging/<sha256>.
  local image_sha
  image_sha="$(sed -n 's/.*"kind"[[:space:]]*:[[:space:]]*"image"[^}]*"sha256"[[:space:]]*:[[:space:]]*"\([0-9a-f]\{64\}\)".*/\1/p' "$POINTER" | head -1)"
  [ -n "$image_sha" ] || die "no 'image' artifact in the staged manifest"
  local image_file="$STAGING/$image_sha"
  [ -f "$image_file" ] || die "staged image artifact missing on disk: $image_file"

  # docker load — failure here leaves current/compose untouched (§10).
  log "loading image for release $version ..."
  $DOCKER load -i "$image_file" >/dev/null || die "docker load failed; current install untouched"

  # Record the tag we are replacing so --rollback and the failure path can
  # both restore it. Empty => first install (fall back to the compose default).
  local prev_tag; prev_tag="$(env_get_tag)"
  printf '%s=%s\n' "$TAG_VAR" "$prev_tag" > "$ROLLBACK_ENV"

  log "switching $SERVICE to $version and restarting ..."
  env_set_tag "$version"
  compose_up || die "compose up failed; run 'rst-update.sh --rollback' to revert"

  if health_ok; then
    log "health check passed; release $version is live"
    write_json "$INSTALLED" \
      "installed_version=$version" "previous=$prev_tag" "installed_at=$(now_iso)"
    rm -f "$FAILED"
    log "old image kept (never auto-pruned); use --prune-old to reclaim disk"
    return 0
  fi

  # Health failed → revert the tag, restart the old image, keep the new one
  # + logs for diagnosis, and exit non-zero (§10).
  log "health check FAILED; rolling back to '${prev_tag:-<compose default>}'"
  env_set_tag "$prev_tag"
  compose_up || log "WARNING: rollback compose up also failed — manual intervention needed"
  write_json "$FAILED" \
    "attempted_version=$version" "reverted_to=$prev_tag" "failed_at=$(now_iso)"
  die "release $version failed health check and was rolled back (see $FAILED)"
}

do_rollback() {
  lock
  [ -f "$INSTALLED" ] || die "nothing to roll back ($INSTALLED missing)"
  local prev; prev="$(json_str "$INSTALLED" previous)"
  log "rolling back to previous='${prev:-<compose default>}' ..."
  env_set_tag "$prev"
  compose_up || die "compose up failed during rollback"
  if health_ok; then
    write_json "$INSTALLED" \
      "installed_version=$prev" "previous=" "installed_at=$(now_iso)"
    log "rolled back to '${prev:-<compose default>}'"
    return 0
  fi
  die "rollback to '${prev}' did not pass health check; manual intervention needed"
}

do_prune_old() {
  [ -f "$ROLLBACK_ENV" ] || die "no rollback.env; nothing recorded to prune"
  local old; old="$(sed -n "s/^$TAG_VAR=\(.*\)$/\1/p" "$ROLLBACK_ENV")"
  [ -n "$old" ] || die "rollback.env has no previous tag (was a first install)"
  log "removing old image $IMAGE_REPO:$old ..."
  $DOCKER image rm "$IMAGE_REPO:$old" || die "docker image rm failed"
  log "pruned $IMAGE_REPO:$old"
}

case "${1:-install}" in
  install|"")   do_install ;;
  --rollback)   do_rollback ;;
  --prune-old)  do_prune_old ;;
  -h|--help)    sed -n '2,30p' "$0" ;;
  *)            die "unknown argument: $1 (try --help)" ;;
esac
