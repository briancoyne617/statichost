#!/usr/bin/env bash
#
# Deploy the current committed tree to the VM. Run from the DEV box (WSL).
#
#   scripts/deploy.sh [user@vm-host]
#
# Host resolution order: $1  →  $STATICHOST_VM  →  the default below. Set STATICHOST_VM in your
# shell (export STATICHOST_VM=bc@192.168.0.222) so you can just run `scripts/deploy.sh`.
#
# What it does, and why each step:
#   - push main first, so the VM can only ever receive committed, pushed code (no dirty-tree deploy).
#   - on the VM, `fetch` + `reset --hard origin/main` rather than `pull`: the VM MIRRORS main, it
#     never has its own commits, so reset can't hit a merge conflict and survives a force-push.
#     content/ and _manifest.json live outside the repo entirely (on the docker-compose volume
#     mount), so reset --hard never touches your hosted files or their curation.
#   - `docker compose up -d --build` picks up any Dockerfile/dependency changes; it's a no-op
#     rebuild (fast, cached layers) when only app.py/templates changed.
set -euo pipefail

VM="${1:-${STATICHOST_VM:-CHANGE-ME}}"
APP="/home/bc/statichost"

if [[ "$VM" == *CHANGE-ME* ]]; then
  echo "Set the VM host: scripts/deploy.sh user@<vm-ip>   (or export STATICHOST_VM)" >&2
  exit 2
fi

echo "→ pushing main…"
git push origin main

echo "→ deploying to $VM…"
ssh "$VM" APP="$APP" bash -s <<'REMOTE'
set -euo pipefail
cd "$APP"
git fetch --prune origin
git reset --hard origin/main
docker compose up -d --build
sleep 2
if docker compose ps --status running | grep -q library; then
  echo "✓ deployed $(git rev-parse --short HEAD) — container running"
else
  echo "✗ container NOT running after deploy — docker compose logs --tail 40" >&2
  exit 1
fi
REMOTE
