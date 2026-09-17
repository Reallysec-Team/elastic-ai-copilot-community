#!/bin/sh
# Drop the gateway to an unprivileged uid before starting uvicorn.
#
# Why not just `USER rst` in the Dockerfile: /app/state is a named volume. A
# FRESH volume inherits ownership from the image directory (which we chown), but
# an EXISTING deployment's volume was created by the old root-running image and
# is owned by uid 0 — switching the image to USER rst would leave the gateway
# unable to write license.key / sessions.json / .rst_secret_key on upgrade, i.e.
# "the container won't come up at the customer site". So we start as root, fix
# ownership once, then drop.
#
# setpriv comes from util-linux in the base image — no extra package, and unlike
# a setuid helper it works under `no-new-privileges`.
#
# If ownership cannot be fixed (capabilities dropped too far) we keep running as
# root rather than taking the deployment down, but say so loudly.
set -e

RST_UID=10001
RST_GID=10001

if [ "$(id -u)" != "0" ]; then
    exec "$@"          # compose already pinned a uid — nothing to drop
fi

# /app/release is the host-shared staging dir for online updates. Compose
# creates the bind source as root:root 755 when it does not exist, so without
# this the downloader (uid 10001) fails with PermissionError on every customer
# host — found on the 2026-09-17 demo box.
for d in /app/state /app/eval /app/release; do
    [ -d "$d" ] || mkdir -p "$d" || true
    if [ "$(stat -c %u "$d" 2>/dev/null)" != "$RST_UID" ]; then
        chown -R "$RST_UID:$RST_GID" "$d" 2>/dev/null || true
    fi
done

if su rst -s /bin/sh -c "test -w /app/state" 2>/dev/null; then
    exec setpriv --reuid="$RST_UID" --regid="$RST_GID" --init-groups "$@"
fi

echo "WARNING: /app/state is not writable by uid $RST_UID — staying root." >&2
echo "WARNING: fix with: docker run --rm -v <state volume>:/s alpine chown -R $RST_UID:$RST_GID /s" >&2
exec "$@"
