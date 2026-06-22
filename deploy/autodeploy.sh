#!/usr/bin/env bash
# Auto-deploy: pull the latest code from GitHub (main) and, if it changed,
# rebuild and restart the bot. Run periodically by the systemd timer so every
# push is picked up automatically within a few minutes.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

git fetch origin main --quiet
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"

if [ "$LOCAL" != "$REMOTE" ]; then
  echo "$(date -u) — new version detected, deploying $REMOTE"
  # .env and the data/ dir are git-ignored, so they survive the reset.
  git reset --hard origin/main
  docker compose -f bot/docker-compose.yml up -d --build
  echo "$(date -u) — deploy done"
else
  echo "$(date -u) — already up to date"
fi
